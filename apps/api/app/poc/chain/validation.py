"""Conservative dependency DAG, execution order and consumed-state verification."""
from __future__ import annotations

import json
import re
from collections import Counter, deque
from typing import Any

from app.poc.chain.evidence import (
    artifact_bytes, current_deployment_id, evidence_is_bound, execution_log,
    registered_verifier, scenario_digest, timestamp, verify_execution,
)

_CARRIED = {"cred", "session", "network", "token", "artifact"}
_CAUSAL_KINDS = {"dependency", "causal"}


def latest_execute_job(scenario_id: str) -> dict[str, Any] | None:
    """Read the current batch even when it has not produced any execution rows.

    Job creation order determines the current batch; completion/run timestamps
    cannot do so when an older overlapping job finishes last. Read failures
    propagate instead of silently falling back to historical successes.
    """
    from app.poc import store

    with store._LOCK:
        db = store._conn()
        try:
            row = db.execute(
                "SELECT id, scenario_id, state, created_at, updated_at FROM poc_jobs "
                "WHERE scenario_id=? AND kind='execute' ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (scenario_id,),
            ).fetchone()
        finally:
            db.close()
    return dict(row) if row else None


def _index_runs(eligible: list[dict[str, Any]], logs: list[tuple[dict[str, Any], Any]]) -> tuple[dict[str, dict[str, Any]], set[str]]:
    selected: dict[str, dict[str, Any]] = {}
    ambiguous: set[str] = set()
    for run in eligible:
        action_id = str(run["action_id"])
        if action_id in selected and selected[action_id] != run:
            ambiguous.add(action_id)
        selected[action_id] = run
    if eligible:
        batch_start = min(timestamp(r["started_at"]) for r in eligible)
        ambiguous.update(str(r["action_id"]) for r, log in logs
                         if log is None and timestamp(r.get("started_at")) is not None
                         and timestamp(r["started_at"]) >= batch_start)
    return selected, ambiguous


def _relation_has_causal_support(rel: dict[str, Any], ir_evidence: list[Any]) -> bool:
    refs = rel.get("evidence_refs") or rel.get("evidence") or []
    if isinstance(refs, str):
        refs = [refs]
    known = {str(entry[key]) for entry in ir_evidence if isinstance(entry, dict)
             for key in ("id", "evidence_id", "ref") if entry.get(key)}
    return bool(refs) and any(str(ref) in known for ref in refs)


def _select_runs(executions: list[dict[str, Any]], *,
                 job: dict[str, Any] | None = None) -> tuple[dict[str, dict[str, Any]], set[str]]:
    """Use the selected persisted job, including an empty batch; never splice jobs.

    Without a persisted job, standalone artifact validation uses attempt identity.
    Legacy/malformed records can then explain FAIL/BLOCKED, but cannot verify PASS.
    Distinct attempts for the same action within a batch are ambiguous, not last-row wins.
    """
    candidates = [r for r in executions if isinstance(r, dict) and r.get("action_id")]
    if not candidates:
        return {}, set()
    logs = [(r, execution_log(r)) for r in candidates]
    if job is not None:
        eligible = [r for r, log in logs if log and log["context"].get("job_id") == job["id"]
                    and log["context"].get("scenario_id") == job["scenario_id"]]
        return _index_runs(eligible, logs)
    dated = [r for r in candidates if timestamp(r.get("started_at")) is not None]
    if len(dated) != len(candidates):
        return {}, {str(r["action_id"]) for r in candidates}
    newest_time = max(timestamp(r["started_at"]) for r in dated)
    newest = [r for r in dated if timestamp(r["started_at"]) == newest_time]
    anchors = [execution_log(r) for r in newest]
    jobs = {log["context"]["job_id"] for log in anchors if log}
    if len(jobs) > 1:
        return {}, {str(r["action_id"]) for r in candidates}
    if not jobs or any(log is None for log in anchors):
        # Do not fall back to older valid successes after a corrupt/missing newest log.
        eligible = [r for r, log in logs if log is None]
    else:
        job_id = next(iter(jobs))
        eligible = [r for r, log in logs if log and log["context"]["job_id"] == job_id]
    # A malformed newest attempt must never leave another action's old PASS eligible.
    return _index_runs(eligible, logs if jobs else [])


def _ordered(predecessor: dict[str, Any] | None, successor: dict[str, Any] | None) -> bool:
    if not predecessor or not successor:
        return False
    start_a, end_a = timestamp(predecessor.get("started_at")), timestamp(predecessor.get("ended_at"))
    start_b, end_b = timestamp(successor.get("started_at")), timestamp(successor.get("ended_at"))
    return bool(start_a and end_a and start_b and end_b and start_a <= end_a <= start_b <= end_b)


def _receipts(run: dict[str, Any], log: dict[str, Any], event: str, carried: str) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    receipts = []
    for evidence in run.get("evidence", []):
        if not isinstance(evidence, dict) or evidence.get("kind") != "state_change" or not evidence_is_bound(evidence, log):
            continue
        try:
            receipt = json.loads(artifact_bytes(evidence))
        except (ValueError, TypeError, UnicodeDecodeError):
            continue
        if (isinstance(receipt, dict) and receipt.get("event") == event and receipt.get("carried") == carried
                and receipt.get("action_id") == run["action_id"]
                and receipt.get("run_id") == log["context"]["run_id"]
                and isinstance(receipt.get("state_id"), str)
                and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", receipt["state_id"])
                and isinstance(receipt.get("value_sha256"), str)
                and re.fullmatch(r"[0-9a-f]{64}", receipt["value_sha256"])):
            receipts.append((evidence, receipt))
    return receipts


def _transfer_for(rel: dict[str, Any], predecessor: dict[str, Any] | None,
                  successor: dict[str, Any] | None, statuses: dict[str, str]) -> dict[str, Any] | None:
    carried = rel.get("carried") or rel.get("transfer")
    if isinstance(carried, dict):
        carried = carried.get("type") or carried.get("kind")
    if not isinstance(carried, str) or carried not in _CARRIED:
        return None
    src, dst = str(rel.get("from_action")), str(rel.get("to_action"))
    transfer = {"from_action": src, "to_action": dst, "carried": carried, "verified": False}
    if statuses.get(src) != "PASS" or statuses.get(dst) != "PASS" or not _ordered(predecessor, successor):
        return transfer
    source_log, target_log = execution_log(predecessor), execution_log(successor)
    if not source_log or not target_log:
        return transfer
    if source_log["context"]["job_id"] != target_log["context"]["job_id"]:
        return transfer
    for run, log in ((predecessor, source_log), (successor, target_log)):
        proof = registered_verifier(run, log)
        # Arithmetic exploit evidence is not a credential/session/network transfer verifier.
        if not proof or carried not in proof.get("state_transfer_types", []):
            return transfer
        if run.get("stages", {}).get("state_change") is not True:
            return transfer
    produced = _receipts(predecessor, source_log, "produced", carried)
    consumed = _receipts(successor, target_log, "consumed", carried)
    matches = []
    for evidence, source in produced:
        for _, target in consumed:
            if (target.get("state_id") == source["state_id"]
                    and target.get("value_sha256") == source["value_sha256"]
                    and target.get("from_action") == src
                    and target.get("from_run_id") == source_log["context"]["run_id"]
                    and target.get("source_evidence") == {"path": evidence["path"], "sha256": evidence["sha256"]}):
                matches.append(evidence["path"])
    if len(matches) == 1:
        transfer.update(verified=True, evidence_ref=matches[0])
    return transfer


def _dag(action_ids: list[str], edges: list[dict[str, Any]]) -> tuple[list[str], set[str], bool]:
    successors = {aid: set() for aid in action_ids}
    degrees = dict.fromkeys(action_ids, 0)
    undirected = {aid: set() for aid in action_ids}
    for edge in edges:
        src, dst = str(edge.get("from_action")), str(edge.get("to_action"))
        if src not in successors or dst not in successors:
            continue
        if dst not in successors[src]:
            degrees[dst] += 1
        successors[src].add(dst)
        undirected[src].add(dst)
        undirected[dst].add(src)
    ready = deque(aid for aid, degree in degrees.items() if degree == 0)
    ordered = []
    while ready:
        src = ready.popleft()
        ordered.append(src)
        for dst in successors[src]:
            degrees[dst] -= 1
            if degrees[dst] == 0:
                ready.append(dst)
    reached = set()
    pending = [action_ids[0]] if action_ids else []
    while pending:
        aid = pending.pop()
        if aid not in reached:
            reached.add(aid)
            pending.extend(undirected[aid] - reached)
    return ordered, set(action_ids) - set(ordered), bool(edges) and reached == set(action_ids)


def validate_chain(scenario_id: str, ir: dict[str, Any], plan: dict[str, Any],
                   executions: list[dict[str, Any]], *,
                   execution_job: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the frozen ChainValidation shape with a separate full-chain outcome.

    Only declared IR dependencies affect propagation. Citations are additionally required
    to verify a causal transfer; temporal/textual coincidences never create dependencies.
    """
    actions = [a for a in (ir.get("actions") or []) if isinstance(a, dict) and a.get("id")]
    action_ids = [str(a["id"]) for a in actions]
    items = {str(i.get("action_id")): i for i in plan.get("items", []) if isinstance(i, dict)}
    job = execution_job if execution_job is not None else latest_execute_job(scenario_id)
    runs, ambiguous = _select_runs(executions, job=job)
    expected = {"scenario_id": scenario_id, "scenario_sha256": scenario_digest(ir),
                "deployment_record_id": current_deployment_id(scenario_id)}
    statuses: dict[str, str] = {}
    for aid in action_ids:
        item, run = items.get(aid), runs.get(aid)
        if item and item.get("strategy") == "not_executable":
            statuses[aid] = "NOT_TESTED"
        elif aid in ambiguous:
            statuses[aid] = "BLOCKED"
        elif run is None:
            statuses[aid] = "NOT_TESTED"
        else:
            statuses[aid] = verify_execution(run, item, expected_context=expected)
    relations = [r for r in (ir.get("relations") or []) if isinstance(r, dict) and r.get("kind") in _CAUSAL_KINDS]
    declared = {(str(r.get("from_action")), str(r.get("to_action"))) for r in relations}
    edges = [r for r in relations if str(r.get("from_action")) in statuses and str(r.get("to_action")) in statuses]
    cited = [r for r in edges if _relation_has_causal_support(r, ir.get("evidence") or [])]
    ordered, cyclic, connected = _dag(action_ids, edges)
    # Missing/extra plan requirements block a dependent, but never invent an IR edge.
    for aid, item in items.items():
        if any((str(src), aid) not in declared for src in (item.get("required_predecessors") or [])):
            if statuses.get(aid) in {"PASS", "PARTIAL"}:
                statuses[aid] = "BLOCKED"
    for aid in cyclic:
        if statuses[aid] in {"PASS", "PARTIAL"}:
            statuses[aid] = "BLOCKED"
    for aid in ordered:
        predecessors = [src for src, dst in declared if dst == aid]
        if any(statuses.get(src) != "PASS" for src in predecessors) and statuses[aid] in {"PASS", "PARTIAL"}:
            statuses[aid] = "BLOCKED"
    unique_actions = all(count == 1 for count in Counter(action_ids).values())
    order_ok = bool(cited) and unique_actions and not cyclic and len(cited) == len(relations) and all(
        _ordered(runs.get(str(edge["from_action"])), runs.get(str(edge["to_action"]))) for edge in edges)
    transfers = []
    for edge in cited:
        transfer = _transfer_for(edge, runs.get(str(edge["from_action"])), runs.get(str(edge["to_action"])), statuses)
        if transfer:
            transfers.append(transfer)
    transfers_ok = bool(transfers) and len(transfers) == len(relations) and all(t["verified"] for t in transfers)
    objective_reached = bool(action_ids) and connected and order_ok and transfers_ok and all(
        statuses[aid] == "PASS" for aid in action_ids)
    return {"scenario_id": scenario_id, "objective_reached": objective_reached, "passes": objective_reached,
            "transfers": transfers, "order_ok": order_ok,
            "per_action": [{"action_id": aid, "status": statuses[aid]} for aid in action_ids]}
