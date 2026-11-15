"""Validate dependency DAGs and explicit state transfers from execution evidence."""
from __future__ import annotations

import re
from typing import Any

from app.poc.chain.evidence import verify_execution

_CARRIED = ("cred", "session", "network", "token", "artifact")
_CAUSAL_KINDS = {"dependency", "causal"}


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value.lower()
    if isinstance(value, (list, tuple)):
        return " ".join(_text(part) for part in value)
    if isinstance(value, dict):
        return " ".join(_text(part) for part in value.values())
    return ""


def _order(results: list[dict[str, Any]]) -> dict[str, int]:
    return {str(item.get("action_id")): index for index, item in enumerate(results) if item.get("action_id")}


def _relation_has_causal_support(rel: dict[str, Any], ir_evidence: list[Any]) -> bool:
    """Require relation-local citation that resolves to an IR evidence record."""
    refs = rel.get("evidence_refs") or rel.get("evidence") or []
    if isinstance(refs, str):
        refs = [refs]
    if not refs:
        return False
    known = set()
    for entry in ir_evidence:
        if isinstance(entry, dict):
            for key in ("id", "evidence_id", "ref"):
                if entry.get(key):
                    known.add(str(entry[key]))
    return any(str(ref) in known for ref in refs)


def _transfer_for(rel: dict[str, Any], predecessor: dict[str, Any] | None, successor: dict[str, Any] | None) -> dict[str, Any] | None:
    """Match explicit carried type in predecessor evidence and successor precondition."""
    carried = rel.get("carried") or rel.get("transfer")
    if isinstance(carried, dict):
        carried = carried.get("type") or carried.get("kind")
    evidence = (predecessor or {}).get("evidence", []) or []
    preconditions = (successor or {}).get("preconditions", []) or []
    if not carried:
        evidence_text = " ".join(_text(item.get("note")) for item in evidence if isinstance(item, dict))
        condition_text = " ".join(_text(item) for item in preconditions)
        expected = [kind for kind in _CARRIED if re.search(rf"\b{re.escape(kind)}\b", condition_text)]
        # The successor precondition identifies what must transfer; predecessor evidence
        # determines verification. An absent/mismatched proof remains explicitly unverified.
        carried = expected[0] if len(expected) == 1 else ""
    carried = str(carried or "").lower()
    if carried not in _CARRIED:
        # No declared or uniquely evidenced transfer type means there is no verifiable transfer.
        return None
    evidence_refs: list[str] = []
    evidence_match = False
    for item in evidence:
        if not isinstance(item, dict):
            continue
        note = _text(item.get("note"))
        if item.get("kind") == "state_change" or re.search(rf"\b{re.escape(carried)}\b", note):
            if re.search(rf"\b{re.escape(carried)}\b", note):
                evidence_match = True
                ref = item.get("path")
                if ref:
                    evidence_refs.append(str(ref))
    condition = " ".join(_text(item) for item in preconditions)
    condition_match = bool(re.search(rf"\b{re.escape(carried)}\b", condition))
    if not evidence_match or not condition_match:
        return {"from_action": str(rel.get("from_action")), "to_action": str(rel.get("to_action")),
                "carried": carried, "verified": False}
    return {"from_action": str(rel.get("from_action")), "to_action": str(rel.get("to_action")),
            "carried": carried, "verified": True, "evidence_ref": evidence_refs[0]}


def validate_chain(scenario_id: str, ir: dict[str, Any], plan: dict[str, Any],
                   executions: list[dict[str, Any]]) -> dict[str, Any]:
    """Build ChainValidation from declared actions, cited dependencies and run evidence.

    Temporal/unclassified relations and uncited dependencies are not promoted into edges.
    """
    actions = [a for a in (ir.get("actions") or []) if isinstance(a, dict) and a.get("id")]
    action_ids = [str(a["id"]) for a in actions]
    items = {str(i.get("action_id")): i for i in plan.get("items", []) if isinstance(i, dict)}
    runs = {str(r.get("action_id")): r for r in executions if isinstance(r, dict) and r.get("action_id")}
    statuses: dict[str, str] = {}
    for action_id in action_ids:
        run = runs.get(action_id)
        item = items.get(action_id)
        if item and item.get("strategy") == "not_executable":
            statuses[action_id] = "NOT_TESTED"
        elif run is None:
            statuses[action_id] = "NOT_TESTED"
        else:
            statuses[action_id] = verify_execution(run, item)

    relations = [r for r in (ir.get("relations") or []) if isinstance(r, dict) and r.get("kind") in _CAUSAL_KINDS]
    ir_evidence = ir.get("evidence") or []
    edges = [r for r in relations if _relation_has_causal_support(r, ir_evidence)
             and str(r.get("from_action")) in statuses and str(r.get("to_action")) in statuses]

    # A declared dependency lacking causal citation is withheld, leaving order conservative.
    uncited_dependencies = [r for r in relations if r.get("kind") == "dependency"
                            and str(r.get("from_action")) in statuses and str(r.get("to_action")) in statuses
                            and not _relation_has_causal_support(r, ir_evidence)]
    positions = _order(executions)
    order_ok = not uncited_dependencies and all(
        str(edge["from_action"]) in positions and str(edge["to_action"]) in positions
        and positions[str(edge["from_action"])] < positions[str(edge["to_action"])]
        for edge in edges
    )
    transfers = []
    for edge in edges:
        transfer = _transfer_for(edge, runs.get(str(edge["from_action"])), items.get(str(edge["to_action"])))
        if transfer:
            transfers.append(transfer)

    # A failed/blocked predecessor prevents its dependent from being reported as PASS.
    for edge in edges:
        src, dst = str(edge["from_action"]), str(edge["to_action"])
        if statuses.get(src) in {"FAIL", "BLOCKED"} and statuses.get(dst) == "PASS":
            statuses[dst] = "PARTIAL"

    required = set(action_ids)
    required.update(str(r.get("to_action")) for r in relations)
    required.update(str(r.get("from_action")) for r in relations)
    per_action = [{"action_id": action_id, "status": statuses[action_id]} for action_id in action_ids]
    all_actions_pass = bool(required) and all(statuses.get(action_id) == "PASS" for action_id in required)
    transfers_ok = all(t["verified"] for t in transfers) and len(transfers) == len(edges)
    objective_reached = all_actions_pass and transfers_ok and order_ok
    return {"scenario_id": scenario_id, "objective_reached": objective_reached, "passes": objective_reached,
            "transfers": transfers, "order_ok": order_ok, "per_action": per_action}
