"""Aggregate module 9 outcomes into the existing validation-report shape."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.poc.chain.evidence import artifact_bytes, execution_log
from app.poc.chain.validation import _select_runs

_VALID_LEVELS = {"PASS", "FAIL", "PARTIAL", "NOT_TESTED"}


def _level(value: Any) -> str:
    value = str(value or "NOT_TESTED").upper()
    if value == "BLOCKED":
        return "NOT_TESTED"
    return value if value in _VALID_LEVELS else "NOT_TESTED"


def _action_name(action: dict[str, Any]) -> str:
    return str(action.get("name") or action.get("description") or action.get("id") or "")


def build_fidelity_report(scenario_id: str, ir: dict[str, Any], plan: dict[str, Any],
                          executions: list[dict[str, Any]], chain: dict[str, Any],
                          validation_report: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return report schema fields, retaining all five fidelity buckets independently.

    ``validation_report`` is the module 8 report; its environment and behavior levels are
    preserved. Module 9 cannot upgrade either level based on runner results.
    """
    base = validation_report or {}
    base_levels = base.get("levels") if isinstance(base.get("levels"), dict) else {}
    env_build = _level(base_levels.get("env_build"))
    behavior_repro = _level(base_levels.get("behavior_repro"))

    actions = [a for a in (ir.get("actions") or []) if isinstance(a, dict) and a.get("id")]
    action_by_id = {str(a["id"]): a for a in actions}
    items = {str(i.get("action_id")): i for i in plan.get("items", []) if isinstance(i, dict)}
    statuses = {str(i.get("action_id")): str(i.get("status", "NOT_TESTED"))
                for i in chain.get("per_action", []) if isinstance(i, dict) and i.get("action_id")}

    reproduced: list[str] = []
    partial: list[str] = []
    not_reproduced: list[str] = []
    not_tested: list[str] = []
    for action_id in action_by_id:
        status = statuses.get(action_id, "NOT_TESTED")
        item = items.get(action_id, {})
        if status == "PASS" and item.get("strategy") != "not_executable":
            reproduced.append(action_id)
        elif status in {"PARTIAL", "BLOCKED"}:
            partial.append(action_id)
        elif status == "FAIL":
            not_reproduced.append(action_id)
        else:
            not_tested.append(action_id)

    # Keep substitute declarations from the existing validation report as a separate bucket.
    base_fidelity = base.get("fidelity") if isinstance(base.get("fidelity"), dict) else {}
    substitutes = list(base_fidelity.get("substitutes_used") or [])
    chain_ok = bool(chain.get("passes")) and bool(chain.get("objective_reached"))
    chain_status = "PASS" if chain_ok else "NOT_TESTED"
    if not chain_ok and any(status == "FAIL" for status in statuses.values()):
        chain_status = "FAIL"
    elif not chain_ok and any(status in {"PASS", "PARTIAL"} for status in statuses.values()):
        chain_status = "PARTIAL"
    full_chain = "NOT_TESTED"
    if env_build == "FAIL" or behavior_repro == "FAIL" or chain_status == "FAIL":
        full_chain = "FAIL"
    elif env_build == behavior_repro == "PASS" and chain_ok:
        full_chain = "PASS"
    elif chain_status == "PARTIAL":
        full_chain = "PARTIAL"

    checks = list(base.get("checks") or [])
    runs, ambiguous = _select_runs(executions)
    for aid in action_by_id:
        run = runs.get(aid, {}) if aid not in ambiguous else {}
        check = {"id": f"poc-{aid}", "name": _action_name(action_by_id[aid]), "category": "behavior",
                 "status": _level(statuses.get(aid)), "action_ref": aid,
                 "expected": items.get(aid, {}).get("expected_evidence", ""),
                 "observed": str(run.get("failure_reason") or statuses.get(aid) or "Not executed")}
        if execution_log(run):
            evidence = next((e.get("path") for e in run.get("evidence", []) if artifact_bytes(e) is not None), None)
            if evidence:
                check["evidence"] = evidence
        checks.append(check)
    checks.append({"id": "poc-full-chain", "name": "End-to-end attack chain", "category": "chain",
                   "status": chain_status,
                   "expected": "All required actions, cited dependencies, actual order and consumed-state transfers verified.",
                   "observed": (f"passes={str(bool(chain.get('passes'))).lower()}; "
                                f"objective_reached={str(bool(chain.get('objective_reached'))).lower()}; "
                                f"order_ok={str(bool(chain.get('order_ok'))).lower()}; "
                                f"verified_transfers={sum(t.get('verified') is True for t in chain.get('transfers', []))}/"
                                f"{len(chain.get('transfers', []))}")})
    return {
        "scenario_id": scenario_id,
        "run_at": datetime.now(timezone.utc).isoformat(),
        "levels": {"env_build": env_build, "behavior_repro": behavior_repro, "full_chain": full_chain},
        "level_criteria": {
            "env_build": "Preserved from the module 8 deployment report.",
            "behavior_repro": "Preserved from module 8; PoC execution cannot upgrade this level.",
            "full_chain": "PASS only when env_build, behavior_repro, and the evidence-verified attack chain all PASS.",
        },
        "checks": checks,
        "fidelity": {"reproduced": reproduced, "partial": partial, "not_reproduced": not_reproduced,
                     "not_tested": not_tested, "substitutes_used": substitutes,
                     "summary": "Fidelity buckets are reported separately; no combined success rate is calculated."},
    }
