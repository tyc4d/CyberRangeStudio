"""Sandbox runner for pinned, ownership-gated PoC payloads."""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app import config, store as scenario_store
from app.deploy import manager
from app.poc import store as poc_store
from app.poc.chain.evidence import execution_log, scenario_digest
from app.poc.models import Evidence, ExecStages, ExecutionResult

from .adapters import get_adapter
from .guard import TargetBlocked, assert_target_owned
from .models import AdapterInput, ExecutionRequest
from .payloads import KNOWN_POC_PROOFS, verifies_effect

_MAX_TIMEOUT = 300
_SECRET_RE = re.compile(r"(?i)(authorization\s*[:=]\s*|password\s*[:=]\s*|token\s*[:=]\s*)([^\s,;]+)")
_NON_EFFECT_MARKER = re.compile(
    r"(?i)^(?:\d{3}|http[_ -]?status\s*[:= ]\s*\d{3}|status\s*200|ok|up|healthy|ready|success|pass)$"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cancelled(cancel: Any) -> bool:
    if isinstance(cancel, bool):
        return cancel
    return bool(getattr(cancel, "is_set", lambda: False)())


def _redact(text: str) -> str:
    return _SECRET_RE.sub(r"\1[REDACTED]", text)


def _redact_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if parts.port:
            host = f"{host}:{parts.port}"
        if parts.username is not None or parts.password is not None:
            host = f"[REDACTED]@{host}"
        query = [(key, "[REDACTED]" if re.search(r"(?i)token|password|secret|key|auth", key) else value)
                 for key, value in parse_qsl(parts.query, keep_blank_values=True)]
        return urlunsplit((parts.scheme, host, parts.path, urlencode(query), ""))
    except (TypeError, ValueError):
        return "[REDACTED_URL]"


def _write_artifact(path: Path, content: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_context(request: ExecutionRequest, run_id: str,
                 ownership: dict[str, Any] | None) -> dict[str, Any]:
    """Bind hashed log evidence to this attempt, IR snapshot, and deployment."""
    ir = scenario_store.get(request.scenario_id)
    context: dict[str, Any] = {"run_id": run_id, "scenario_id": request.scenario_id}
    if request.job_id is not None:
        context["job_id"] = request.job_id
    if isinstance(ir, dict):
        context["scenario_sha256"] = scenario_digest(ir)
    deployment_id = (ownership or {}).get("deployment_record_id")
    if type(deployment_id) is int and deployment_id > 0:
        context["deployment_record_id"] = deployment_id
    return context


def _record_result(request: ExecutionRequest, result: ExecutionResult, context: dict[str, Any],
                   ownership: dict[str, Any] | None, output: str,
                   cleanup_note: str | None = None) -> ExecutionResult:
    """Hash the completed attempt and bind its effects before adding the log's own hash."""
    log = {"action_id": result.action_id, "status": result.status,
           "started_at": result.started_at, "ended_at": result.ended_at,
           "payload_sha256": result.payload_sha256, "proof_id": request.proof_id,
           "context": context, "ownership": ownership,
           "evidence": [asdict(item) for item in result.evidence],
           "output": output, "reason": result.failure_reason, "cleanup": cleanup_note}
    digest = _write_artifact(config.DATA_DIR / result.logs_path,
                             json.dumps(log, ensure_ascii=False, sort_keys=True))
    result.evidence.append(Evidence("log", result.logs_path, digest, True, "redacted runner log"))
    return result


def _result_dict(result: ExecutionResult) -> dict[str, Any]:
    # Shared model versions before to_dict still serialize safely during worker
    # integration. Never emit null for optional fields in the frozen contract.
    serializer = getattr(result, "to_dict", None)
    if callable(serializer):
        return serializer()
    return asdict(result, dict_factory=lambda items: {key: value for key, value in items if value is not None})


def _emit_progress(request: ExecutionRequest, stages: ExecStages) -> None:
    if request.on_progress:
        try:
            request.on_progress(asdict(stages))
        except Exception:
            # Progress reporting must never change the execution verdict or skip cleanup.
            pass


def _operation_result(operation: dict[str, Any]) -> dict[str, Any] | None:
    state = operation.get("state")
    if state not in {"cancelled", "completed", "failed"} or operation.get("resource_absent") is not True:
        return None
    if state == "cancelled":
        return {"returncode": 125, "stdout": "", "stderr": "cancelled and helper absence confirmed"}
    if state == "failed":
        return {"returncode": 127, "stdout": operation.get("stdout", ""),
                "stderr": operation.get("stderr", "probe helper failed before completing")}
    return {"returncode": int(operation.get("exitcode", 127)),
            "stdout": str(operation.get("stdout", "")),
            "stderr": str(operation.get("stderr", ""))}


def _cancel_and_join(request: ExecutionRequest, operation_id: str, *, job_id: str,
                     vmid: int, host_id: str, generation_id: str) -> tuple[dict[str, Any], str | None]:
    try:
        cancellation = manager.cancel_probe_operation(
            request.scenario_id, operation_id, request.service_ref, vmid, host_id,
            generation_id, job_id)
        joined = (cancellation if _operation_result(cancellation) is not None else
                  manager.join_probe_operation(
                      request.scenario_id, operation_id, request.service_ref,
                      vmid, host_id, generation_id, timeout=30))
    except Exception as exc:
        return {"state": "uncertain", "resource_absent": False}, (
            f"probe cancellation/join was not confirmed ({type(exc).__name__})")
    result = _operation_result(joined)
    if result is not None:
        return result, "guest supervisor confirmed the helper is absent"
    detail = joined.get("error") or cancellation.get("error") or joined.get("state", "unknown")
    return {"state": "uncertain", "resource_absent": False}, (
        f"probe cancellation/join is unconfirmed; worker down and reuse remain blocked: {detail}")


def _probe_with_cancel(request: ExecutionRequest, script: str, timeout: int) -> tuple[dict[str, Any], str | None]:
    """Run a pinned payload through a PVE guest supervisor with durable start/cancel fencing."""
    selected = manager.deploy_backend()
    if selected == "local-docker":
        return {"returncode": 127, "stdout": "", "stderr":
                "D6: local Docker is restricted to non-attack QA; PoC payload execution is forbidden"}, None
    if selected != "proxmox":
        return {"returncode": 127, "stdout": "", "stderr":
                "no approved cancellable probe transport is selected"}, None
    if _cancelled(request.cancel):
        return {"returncode": 125, "stdout": "", "stderr": "cancelled before payload delivery"}, None

    operation_id = uuid.uuid4().hex
    job_id = request.job_id or uuid.uuid4().hex
    try:
        worker_identity = (poc_store.get_job_worker_identity(request.job_id)
                           if request.job_id else manager.probe_worker_identity(request.scenario_id))
    except Exception:
        worker_identity = None
    if not isinstance(worker_identity, dict):
        return {"returncode": 127, "stdout": "",
                "stderr": "POC job has no pinned active Proxmox worker generation"}, None
    try:
        reservation = manager.reserve_probe_operation(
            request.scenario_id, request.service_ref, operation_id, job_id, worker_identity)
    except Exception as exc:
        reservation = {"state": "blocked", "resource_absent": True,
                       "error": f"probe launch reservation failed ({type(exc).__name__})"}
    if reservation.get("state") == "blocked" and reservation.get("resource_absent") is True:
        return {"returncode": 127, "stdout": "", "stderr": reservation.get(
            "error", "probe launch reservation was refused")}, None
    identity = (reservation.get("vmid"), reservation.get("host_id"), reservation.get("generation_id"))
    if (not isinstance(identity[0], int) or not isinstance(identity[1], str)
            or not isinstance(identity[2], str)):
        return {"returncode": 127, "stdout": "", "stderr": reservation.get(
            "error", "probe launch reservation identity is uncertain")}, None
    vmid, host_id, generation_id = identity
    if request.job_id and not poc_store.register_job_operation(
            request.job_id, operation_id, request.service_ref, request.action_id,
            vmid, host_id, generation_id):
        result, note = _cancel_and_join(request, operation_id, job_id=job_id, vmid=vmid,
                                        host_id=host_id, generation_id=generation_id)
        return (result if "returncode" in result else {"returncode": 127, "stdout": "",
                "stderr": "probe reservation cleanup is uncertain"}), note

    if reservation.get("state") != "reserved" or _cancelled(request.cancel):
        result, note = _cancel_and_join(request, operation_id, job_id=job_id, vmid=vmid,
                                        host_id=host_id, generation_id=generation_id)
        if request.job_id and "returncode" in result:
            poc_store.clear_job_operation(request.job_id, operation_id)
        return (result if "returncode" in result else {"returncode": 127, "stdout": "",
                "stderr": reservation.get("error", "probe reservation was cancelled before launch")}), note

    try:
        started = manager.start_probe_operation(
            request.scenario_id, request.service_ref, operation_id, job_id,
            vmid, host_id, generation_id, script,
            max(1, min(int(timeout), _MAX_TIMEOUT)))
    except Exception as exc:
        started = {"state": "uncertain", "resource_absent": False,
                   "error": f"probe start request outcome is uncertain ({type(exc).__name__})"}
    operation_result = _operation_result(started)
    if operation_result is not None:
        if request.job_id:
            poc_store.clear_job_operation(request.job_id, operation_id)
        note = ("guest supervisor confirmed the helper is absent"
                if operation_result["returncode"] in {124, 125} else None)
        return operation_result, note
    if started.get("state") == "blocked":
        if request.job_id:
            poc_store.clear_job_operation(request.job_id, operation_id)
        return {"returncode": 127, "stdout": "", "stderr": started.get("error", "probe transport is blocked")}, None

    deadline = time.monotonic() + max(1, min(int(timeout), _MAX_TIMEOUT))
    while True:
        if _cancelled(request.cancel):
            result, note = _cancel_and_join(request, operation_id, job_id=job_id, vmid=vmid,
                                            host_id=host_id, generation_id=generation_id)
            if request.job_id and "returncode" in result:
                poc_store.clear_job_operation(request.job_id, operation_id)
            return result, note
        if time.monotonic() >= deadline:
            result, note = _cancel_and_join(request, operation_id, job_id=job_id, vmid=vmid,
                                            host_id=host_id, generation_id=generation_id)
            if result.get("returncode") in {125, 0, 1}:
                # The runtime deadline is authoritative even if the helper raced to completion.
                result = {"returncode": 124, "stdout": "", "stderr": "probe timed out after helper cleanup"}
            if request.job_id and "returncode" in result:
                poc_store.clear_job_operation(request.job_id, operation_id)
            return result, note
        try:
            current = manager.wait_probe_operation(
                request.scenario_id, operation_id, vmid, host_id, generation_id, timeout=10)
        except Exception as exc:
            current = {"state": "uncertain", "resource_absent": False,
                       "error": f"probe wait failed ({type(exc).__name__})"}
        operation_result = _operation_result(current)
        if operation_result is not None:
            if request.job_id:
                poc_store.clear_job_operation(request.job_id, operation_id)
            note = ("guest supervisor confirmed the helper is absent"
                    if operation_result["returncode"] in {124, 125} else None)
            return operation_result, note
        if current.get("state") == "uncertain":
            # Attempt fenced cancellation, but retain the job operation if absence stays unknown.
            result, note = _cancel_and_join(request, operation_id, job_id=job_id, vmid=vmid,
                                            host_id=host_id, generation_id=generation_id)
            if request.job_id and "returncode" in result:
                poc_store.clear_job_operation(request.job_id, operation_id)
            return result, note or "probe transport was uncertain; the helper cleanup was confirmed"
        if current.get("state") not in {"starting", "running"}:
            result, note = _cancel_and_join(request, operation_id, job_id=job_id, vmid=vmid,
                                            host_id=host_id, generation_id=generation_id)
            if request.job_id and "returncode" in result:
                poc_store.clear_job_operation(request.job_id, operation_id)
            return result, note or "probe transport state was not recognized; helper absence was confirmed"
        time.sleep(0.25)


class SandboxRunner:
    """Execute one adapter payload inside the target's isolated network namespace."""

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        started = _now()
        stages = ExecStages()
        evidence: list[Evidence] = []
        payload_hash = hashlib.sha256(request.payload.encode("utf-8")).hexdigest()
        ref = dict(request.ref or {})
        safe_scenario = hashlib.sha256(request.scenario_id.encode("utf-8")).hexdigest()[:16]
        run_id = uuid.uuid4().hex
        run_directory = f"poc-runs/{safe_scenario}/{run_id}"
        logs_path = f"{run_directory}/output.log"
        poc = {"source_url": _redact_url(request.source_url),
               "ref": {key: _redact(str(value)) for key, value in ref.items()},
               "sha256": request.sha256}
        ownership: dict[str, Any] | None = None
        status = "BLOCKED"
        reason: str | None = None
        exit_code: int | None = None
        confidence = 0.0
        output = ""
        cleanup_note: str | None = None

        # This guard is deliberately the first operation with deployment context. A
        # blocked target never reaches adapter construction or the execution call.
        try:
            ownership = assert_target_owned(request.scenario_id, {
                "service_ref": request.service_ref, "target_host_ref": request.target_host_ref,
            })
        except TargetBlocked as exc:
            reason = str(exc)
            output = "BLOCKED: ownership/isolation not verified; payload was not executed."
            result = ExecutionResult(request.action_id, poc, "BLOCKED", stages, logs_path, confidence,
                                     False, payload_hash, started, _now(), failure_reason=reason)
            return _record_result(request, result, _run_context(request, run_id, None), None, output)

        context = _run_context(request, run_id, ownership)
        stages.started = True
        _emit_progress(request, stages)
        adapter = get_adapter(request.exec_method)
        verifier = KNOWN_POC_PROOFS.get(request.proof_id or "")
        if not adapter:
            status, reason = "BLOCKED", f"unsupported execution method: {request.exec_method}"
        elif (not verifier or request.exec_method != verifier["exec_method"]
              or request.source_url != verifier["source_url"]
              or request.payload != verifier["payload"]
              or request.expected_marker != verifier["expected_marker"]):
            status, reason = "BLOCKED", "no runner-owned exploit-effect verifier is registered for this payload"
        elif not request.expected_marker or _NON_EFFECT_MARKER.fullmatch(request.expected_marker.strip()):
            status, reason = "BLOCKED", "expected evidence must identify a concrete exploit effect, not liveness or HTTP status"
        elif request.exec_method in {"python", "http_seq"}:
            if len(request.sha256) != 64 or any(c not in "0123456789abcdef" for c in request.sha256.lower()):
                status, reason = "BLOCKED", "payload SHA-256 must be recorded as a 64-character digest"
            elif hashlib.sha256(request.payload.encode("utf-8")).hexdigest() != request.sha256.lower():
                status, reason = "BLOCKED", "payload SHA-256 does not match the supplied payload"
            elif request.sha256.lower() != verifier["sha256"]:
                status, reason = "BLOCKED", "payload is not the runner-owned SHA-pinned exploit with a registered evidence verifier"
            elif request.source_url.startswith(("https://github.com/", "http://github.com/")) and not re.fullmatch(
                    r"[0-9a-f]{40,64}", ref.get("commit_sha", "")):
                status, reason = "BLOCKED", "GitHub PoCs must be pinned to a full commit SHA"
            elif _cancelled(request.cancel):
                status, reason = "BLOCKED", "execution cancelled before payload delivery"
            else:
                prepared = adapter.prepare(AdapterInput(request.payload))
                if prepared.blocked_reason:
                    status, reason = "BLOCKED", prepared.blocked_reason
                else:
                    timeout = max(1, min(int(request.timeout), _MAX_TIMEOUT))
                    try:
                        result, cleanup_note = _probe_with_cancel(request, prepared.payload, timeout)
                        exit_code = int(result.get("returncode", 2))
                        output = _redact((result.get("stdout", "") + result.get("stderr", ""))[-12000:])
                        # Wrapper errors/cancellation do not attest target delivery
                        # or a target response. Preserve BLOCKED through roll-up.
                        stages.delivered = exit_code not in {2, 124, 125, 127}
                        stages.responded = stages.delivered and bool(output)
                        _emit_progress(request, stages)
                        if exit_code == 124:
                            status, reason = "BLOCKED", f"sandbox timed out after {timeout}s"
                            cleanup_note = cleanup_note or "probe helper cleanup could not be confirmed"
                        elif exit_code == 125:
                            status, reason = "BLOCKED", "execution cancelled; sandbox cleanup was attempted"
                        elif _cancelled(request.cancel):
                            status, reason = "BLOCKED", "execution cancelled; helper was asked to stop"
                        elif exit_code in {2, 127}:
                            status, reason = "BLOCKED", output[:500] or "sandbox could not start safely"
                        else:
                            marker = request.expected_marker
                            reproduced = verifies_effect(verifier, result)
                            status = "PASS" if reproduced else "FAIL"
                            stages.vuln_behavior = reproduced
                            stages.state_change = reproduced
                            stages.action_complete = True
                            _emit_progress(request, stages)
                            confidence = 0.99 if reproduced else 0.0
                            if reproduced:
                                evidence_text = _redact(f"Expected exploit-effect marker observed: {marker}\n")
                                effect_path = config.DATA_DIR / run_directory / "effect.txt"
                                digest = _write_artifact(effect_path, evidence_text)
                                evidence.append(Evidence("exploit_effect", str(effect_path.relative_to(config.DATA_DIR)),
                                                         digest, True,
                                                         _redact(f"concrete response marker observed: {marker}")))
                            else:
                                reason = "real payload completed without the expected exploit effect"
                    except (TimeoutError, OSError) as exc:
                        status, reason = "BLOCKED", f"sandbox execution error: {type(exc).__name__}"
        else:
            prepared = adapter.prepare(AdapterInput(request.payload))
            status, reason = "BLOCKED", prepared.blocked_reason or "adapter is not supported by the pinned sandbox"

        result = ExecutionResult(request.action_id, poc, status, stages, logs_path, confidence,
                                 True, payload_hash, started, _now(), evidence=evidence,
                                 exit_code=exit_code, failure_reason=reason)
        return _record_result(request, result, context, ownership, output, cleanup_note)


class _JobCancellation:
    def __init__(self, job_id: str):
        self.job_id = job_id

    def is_set(self) -> bool:
        return poc_store.is_cancelled(self.job_id)


def _blocked_predecessor_result(request: ExecutionRequest, unmet: list[str]) -> ExecutionResult:
    """Record an unmet prerequisite without inspecting a target or preparing a payload."""
    started = _now()
    run_id = uuid.uuid4().hex
    safe_scenario = hashlib.sha256(request.scenario_id.encode("utf-8")).hexdigest()[:16]
    logs_path = f"poc-runs/{safe_scenario}/{run_id}/output.log"
    poc = {"source_url": _redact_url(request.source_url),
           "ref": {key: _redact(str(value)) for key, value in (request.ref or {}).items()},
           "sha256": request.sha256}
    reason = f"required predecessor(s) {unmet} did not PASS in this job; dependent not executed"
    result = ExecutionResult(
        request.action_id, poc, "BLOCKED", ExecStages(), logs_path, 0.0, False,
        hashlib.sha256(request.payload.encode("utf-8")).hexdigest(), started, _now(),
        failure_reason=reason,
    )
    return _record_result(request, result, _run_context(request, run_id, None), None,
                          "BLOCKED: required predecessors were not verified in this execution job.")


def run_job(scenario_id: str, requests: list[ExecutionRequest], timeout_s: float | None = None) -> list[dict[str, Any]]:
    """Run one ordered batch, gating prerequisites and cancellation within its single job.

    Only a predecessor's completed PASS in this batch can permit its dependent.
    Missing, later, and previous-job predecessors do not satisfy a requirement.
    """
    if any(request.scenario_id != scenario_id for request in requests):
        raise ValueError("every execution request must belong to the job scenario")
    job_id = uuid.uuid4().hex
    try:
        worker_identity = (manager.probe_worker_identity(scenario_id)
                           if manager.deploy_backend() == "proxmox" else None)
    except Exception:
        worker_identity = None
    poc_store.create_job(job_id, scenario_id, "execute", timeout_s=timeout_s,
                         worker_identity=worker_identity)
    cancellation = _JobCancellation(job_id)
    results: list[dict[str, Any]] = []
    statuses: dict[str, str] = {}
    poc_store.set_job_state(job_id, "running", json.dumps({"current_action_id": None, "stages": {}}))
    deadline = time.monotonic() + timeout_s if timeout_s else None
    try:
        for request in requests:
            if cancellation.is_set():
                break
            initial = asdict(ExecStages())
            detail = {"current_action_id": request.action_id, "stages": initial}
            poc_store.set_job_state(job_id, "running", json.dumps(detail))

            def report_progress(stages: dict[str, bool], action_id: str = request.action_id) -> None:
                poc_store.set_job_state(job_id, "running", json.dumps(
                    {"current_action_id": action_id, "stages": stages}))

            remaining = int(deadline - time.monotonic()) if deadline else request.timeout
            if deadline and remaining <= 0:
                poc_store.request_cancel(job_id)
                break
            current = replace(request, timeout=max(1, min(request.timeout, remaining)),
                              cancel=cancellation, on_progress=report_progress, job_id=job_id)
            unmet = [predecessor for predecessor in current.required_predecessors
                     if statuses.get(predecessor) != "PASS"]
            result = (_blocked_predecessor_result(current, unmet) if unmet
                      else SandboxRunner().execute(current))
            serialized = _result_dict(result)
            results.append(serialized)
            poc_store.save_run(scenario_id, serialized)
            statuses[request.action_id] = result.status
            if deadline and time.monotonic() >= deadline:
                poc_store.request_cancel(job_id)
        unresolved_operation = poc_store.get_job_operation(job_id)
        if unresolved_operation:
            # Keep this job cancellable so a later request can retry guest-side
            # reconciliation. PVE down/up/reset also remain blocked by its ledger.
            poc_store.set_job_state(job_id, "running", json.dumps({
                "completed_actions": len(results), "operation_id": unresolved_operation["operation_id"],
                "cleanup": "unconfirmed; worker lifecycle is blocked"}))
        elif cancellation.is_set() or (deadline and time.monotonic() >= deadline):
            poc_store.set_job_state(job_id, "cancelled", json.dumps({"completed_actions": len(results)}))
        else:
            poc_store.set_job_state(job_id, "done", json.dumps({"completed_actions": len(results)}))
    except Exception as exc:
        poc_store.set_job_state(job_id, "error", f"execution job failed: {type(exc).__name__}")
        raise
    return results


def execution_status(scenario_id: str) -> dict[str, Any]:
    """Return selected-job results plus the identities/states of overlapping jobs.

    job_state is the scenario's activity summary for existing polling clients;
    selected_job_state always names the selected job's actual persisted state.
    A cancel flag is only a request: that job stays active until its state changes.
    """
    db = poc_store._conn()
    try:
        # Keep selected job, active jobs and result rows in one database snapshot.
        # Artifact verification below happens after this short read transaction.
        db.execute("BEGIN")
        job_rows = db.execute(
            "SELECT * FROM poc_jobs WHERE scenario_id=? AND kind='execute' "
            "ORDER BY created_at DESC, rowid DESC",
            (scenario_id,),
        ).fetchall()
        if not job_rows:
            return {"job_id": None, "job_state": "idle", "selected_job_state": "idle",
                    "jobs": [], "active_jobs": [], "per_action": [], "logs_tail": ""}
        job = dict(job_rows[0])
        jobs = [{"job_id": row["id"], "state": row["state"], "cancel_requested": bool(row["cancel"])}
                for row in job_rows]
        active_jobs = [entry for entry in jobs if entry["state"] in {"pending", "running"}]
        rows = db.execute(
            "SELECT result FROM poc_runs WHERE scenario_id=? ORDER BY id",
            (scenario_id,),
        ).fetchall()
    finally:
        db.close()
    per_action = []
    latest_log: dict[str, Any] | None = None
    for row in rows:
        try:
            result = json.loads(row["result"])
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(result, dict):
            continue
        # The frozen result shape has no job_id column/field. Its immutable,
        # hash-verified log is the persisted source of batch identity. A later
        # saved row may belong to an older overlapping job; timestamps cannot
        # associate that row with the selected job.
        log = execution_log(result)
        if (not log or log["context"].get("job_id") != job["id"]
                or log["context"].get("scenario_id") != scenario_id):
            continue
        latest_log = log
        per_action.append({"action_id": result.get("action_id"), "stages": result.get("stages") or {}})
    try:
        detail = json.loads(job.get("detail") or "{}")
    except json.JSONDecodeError:
        detail = {}
    current_id = detail.get("current_action_id")
    if current_id and not any(item.get("action_id") == current_id for item in per_action):
        per_action.append({"action_id": current_id, "stages": detail.get("stages") or asdict(ExecStages())})
    logs_tail = (_redact(json.dumps(latest_log, ensure_ascii=False, sort_keys=True)[-4000:])
                 if latest_log is not None else "")
    job_state = ("running" if any(entry["state"] == "running" for entry in active_jobs)
                 else "pending" if active_jobs else job["state"])
    return {"job_id": job["id"], "selected_job_state": job["state"], "job_state": job_state,
            "jobs": jobs, "active_jobs": active_jobs, "per_action": per_action, "logs_tail": logs_tail}


def cancel_execution(scenario_id: str) -> dict[str, Any]:
    """Flag jobs, then reconcile every durable PVE fence, including pre-job reservations."""
    flagged, job_operations = poc_store.request_cancel_operations(scenario_id)
    by_id = {operation["operation_id"]: operation for operation in job_operations}
    ledger_error = False
    try:
        for operation in manager.active_probe_operations(scenario_id):
            prior = by_id.get(operation["operation_id"], {})
            by_id[operation["operation_id"]] = {**prior, **operation,
                                                "job_id": operation.get("job_id") or prior.get("job_id")}
    except Exception:
        ledger_error = True
    operations = list(by_id.values())
    joined_all = not ledger_error
    uncertain = ledger_error
    for operation in operations:
        if (not isinstance(operation.get("vmid"), int) or not isinstance(operation.get("host_id"), str)
                or not isinstance(operation.get("generation_id"), str)):
            joined_all = False
            uncertain = True
            continue
        try:
            cancelled = manager.cancel_probe_operation(
                scenario_id, operation["operation_id"], operation["service_id"],
                operation["vmid"], operation["host_id"], operation["generation_id"],
                operation.get("job_id"))
            joined = (cancelled if _operation_result(cancelled) is not None else
                      manager.join_probe_operation(
                          scenario_id, operation["operation_id"], operation["service_id"],
                          operation["vmid"], operation["host_id"], operation["generation_id"], timeout=30))
        except Exception as exc:
            joined = {"state": "uncertain", "resource_absent": False,
                      "error": f"cancel operation failed ({type(exc).__name__})"}
        terminal = joined.get("state") in {"cancelled", "completed", "failed"}
        if terminal and joined.get("resource_absent") is True:
            if operation.get("job_id"):
                poc_store.clear_job_operation(operation["job_id"], operation["operation_id"])
                poc_store.set_job_state(operation["job_id"], "cancelled", json.dumps({
                    "operation_id": operation["operation_id"], "cleanup": "confirmed", "joined": True}))
        else:
            joined_all = False
            uncertain = True
    return {"cancelled": flagged, "joined": joined_all, "uncertain": uncertain,
            "operations": len(operations)}
