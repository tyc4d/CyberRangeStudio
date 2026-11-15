"""Sandbox runner for pinned, ownership-gated PoC payloads."""
from __future__ import annotations

import hashlib
import json
import re
import queue
import threading
import time
import uuid
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app import config
from app.deploy import manager
from app.poc import store as poc_store
from app.poc.models import Evidence, ExecStages, ExecutionResult

from .adapters import get_adapter
from .guard import TargetBlocked, assert_target_owned
from .models import AdapterInput, ExecutionRequest
from .payloads import KNOWN_POC_PROOFS

_MAX_TIMEOUT = 300
_HELPER_IMAGE = "python@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704"
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


def _emit_progress(request: ExecutionRequest, stages: ExecStages) -> None:
    if request.on_progress:
        try:
            request.on_progress(asdict(stages))
        except Exception:
            # Progress reporting must never change the execution verdict or skip cleanup.
            pass


def _command_result(scenario_id: str, argv: list[str], timeout: int = 10) -> dict[str, Any]:
    """Run a fixed Docker inspection/cleanup command in the selected runtime."""
    if manager.deploy_backend() == "proxmox":
        return manager._pve_guest_exec(scenario_id, ["/usr/bin/docker", *argv], timeout,
                                       require_isolation=True)
    docker, error = manager._docker_context_preflight()
    if error or not docker:
        return {"returncode": 127, "stdout": "", "stderr": error or "Docker unavailable"}
    return manager._run([docker, *argv], timeout=timeout)


def _cleanup_probe(scenario_id: str, service: str, payload: str, started_epoch: float) -> str:
    """Best-effort remove a timed-out helper, only when its identity is unambiguous."""
    target_name = f"cr-demo-{scenario_id}-{service}"
    target_inspect = _command_result(scenario_id, ["inspect", "-f", "{{.Id}}", target_name], 10)
    target_id = target_inspect.get("stdout", "").strip()
    if target_inspect.get("returncode") != 0 or not re.fullmatch(r"[0-9a-f]{12,64}", target_id):
        return "cleanup could not verify the owned target container"
    listed = _command_result(scenario_id, ["ps", "-q", "--filter", f"ancestor={_HELPER_IMAGE}"], 10)
    if listed.get("returncode") != 0:
        return "cleanup could not list sandbox helpers"
    ids = [line.strip() for line in listed.get("stdout", "").splitlines() if re.fullmatch(r"[0-9a-f]{12,64}", line.strip())]
    matching: list[str] = []
    for container_id in ids[:100]:
        inspected = _command_result(scenario_id, ["inspect", container_id], 10)
        try:
            info = json.loads(inspected.get("stdout", ""))[0]
        except (json.JSONDecodeError, IndexError, TypeError):
            continue
        cfg, host = info.get("Config") or {}, info.get("HostConfig") or {}
        created_text = str(info.get("Created", ""))
        try:
            created = datetime.fromisoformat(created_text.replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
        network_mode = str(host.get("NetworkMode", ""))
        command = cfg.get("Cmd") or []
        if (cfg.get("Image") == _HELPER_IMAGE and cfg.get("User") == "65532:65532"
                and host.get("ReadonlyRootfs") is True and "ALL" in (host.get("CapDrop") or [])
                and network_mode in {f"container:{target_name}", f"container:{target_id}"}
                and created >= started_epoch - 2 and "-c" in command and payload in command):
            matching.append(str(info.get("Id") or container_id))
    if len(matching) != 1:
        return "cleanup did not remove a helper because identity was not uniquely proven"
    removed = _command_result(scenario_id, ["rm", "-f", matching[0]], 10)
    return "timed-out sandbox helper removed" if removed.get("returncode") == 0 else "best-effort helper removal failed"


def _probe_with_cancel(request: ExecutionRequest, script: str, timeout: int) -> tuple[dict[str, Any], str | None]:
    """Bound the manager call, watch cancellation, and clean up a uniquely identified helper."""
    result_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
    attempt_started = time.time()

    def invoke() -> None:
        try:
            result_queue.put(manager.probe_in_service(request.scenario_id, request.service_ref,
                                                      script, timeout=timeout))
        except BaseException as exc:  # communicate worker errors without leaking their text
            result_queue.put({"returncode": 127, "stdout": "", "stderr": type(exc).__name__})

    worker = threading.Thread(target=invoke, name="poc-sandbox-probe", daemon=True)
    worker.start()
    deadline = time.monotonic() + timeout + 1
    while True:
        if _cancelled(request.cancel):
            cleanup = _cleanup_probe(request.scenario_id, request.service_ref, script, attempt_started)
            return {"returncode": 125, "stdout": "", "stderr": "cancelled"}, cleanup
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            cleanup = _cleanup_probe(request.scenario_id, request.service_ref, script, attempt_started)
            return {"returncode": 124, "stdout": "", "stderr": "probe wrapper timeout"}, cleanup
        try:
            return result_queue.get(timeout=min(0.1, remaining)), None
        except queue.Empty:
            continue


class SandboxRunner:
    """Execute one adapter payload inside the target's isolated network namespace."""

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        started = _now()
        stages = ExecStages()
        evidence: list[Evidence] = []
        payload_hash = hashlib.sha256(request.payload.encode("utf-8")).hexdigest()
        ref = dict(request.ref or {})
        safe_scenario = hashlib.sha256(request.scenario_id.encode("utf-8")).hexdigest()[:16]
        safe_action = hashlib.sha256(request.action_id.encode("utf-8")).hexdigest()[:16]
        logs_path = f"poc-runs/{safe_scenario}/{safe_action}.log"
        artifact = config.DATA_DIR / logs_path
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
            digest = _write_artifact(artifact, output)
            return ExecutionResult(request.action_id, poc, "BLOCKED", stages, logs_path, confidence,
                                   False, payload_hash, started, _now(), evidence=[Evidence(
                                       "log", logs_path, digest, True, "ownership guard blocked execution")],
                                   failure_reason=reason)

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
                        # manager.probe_in_service owns the `--rm --pull=never`,
                        # non-root, no-host-mount helper and shares only this target's
                        # namespace. The helper image is already pinned by deploy.
                        result, cleanup_note = _probe_with_cancel(request, prepared.payload, timeout)
                        exit_code = int(result.get("returncode", 2))
                        output = _redact((result.get("stdout", "") + result.get("stderr", ""))[-12000:])
                        stages.delivered = exit_code != 127 and exit_code != 2
                        stages.responded = bool(output)
                        _emit_progress(request, stages)
                        if exit_code == 124:
                            status, reason = "BLOCKED", f"sandbox timed out after {timeout}s"
                            cleanup_note = cleanup_note or _cleanup_probe(
                                request.scenario_id, request.service_ref, prepared.payload, time.time() - timeout)
                        elif exit_code == 125:
                            status, reason = "BLOCKED", "execution cancelled; sandbox cleanup was attempted"
                        elif _cancelled(request.cancel):
                            status, reason = "BLOCKED", "execution cancelled; helper was asked to stop"
                        elif exit_code in {2, 127}:
                            status, reason = "BLOCKED", output[:500] or "sandbox could not start safely"
                        else:
                            marker = request.expected_marker
                            reproduced = bool(marker and marker in output)
                            status = "PASS" if reproduced else "FAIL"
                            stages.vuln_behavior = reproduced
                            stages.state_change = reproduced
                            stages.action_complete = True
                            _emit_progress(request, stages)
                            confidence = 0.99 if reproduced else 0.0
                            if reproduced:
                                evidence_text = _redact(f"Expected exploit-effect marker observed: {marker}\n")
                                effect_path = config.DATA_DIR / "poc-runs" / safe_scenario / f"{safe_action}-effect.txt"
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

        log_text = json.dumps({"action_id": request.action_id, "status": status,
                               "ownership": ownership, "output": output, "reason": reason,
                               "cleanup": cleanup_note},
                              ensure_ascii=False, sort_keys=True)
        digest = _write_artifact(artifact, log_text)
        evidence.append(Evidence("log", logs_path, digest, True, "redacted runner log"))
        return ExecutionResult(request.action_id, poc, status, stages, logs_path, confidence,
                               True, payload_hash, started, _now(), evidence=evidence,
                               exit_code=exit_code, failure_reason=reason)


class _JobCancellation:
    def __init__(self, job_id: str):
        self.job_id = job_id

    def is_set(self) -> bool:
        return poc_store.is_cancelled(self.job_id)


def run_job(scenario_id: str, requests: list[ExecutionRequest], timeout_s: float | None = None) -> list[dict[str, Any]]:
    """Run a synchronous batch while persisting a pollable job and per-action results."""
    if any(request.scenario_id != scenario_id for request in requests):
        raise ValueError("every execution request must belong to the job scenario")
    job_id = uuid.uuid4().hex
    poc_store.create_job(job_id, scenario_id, "execute", timeout_s=timeout_s)
    cancellation = _JobCancellation(job_id)
    results: list[dict[str, Any]] = []
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
                              cancel=cancellation, on_progress=report_progress)
            result = SandboxRunner().execute(current)
            serialized = asdict(result)
            results.append(serialized)
            poc_store.save_run(scenario_id, serialized)
            if deadline and time.monotonic() >= deadline:
                poc_store.request_cancel(job_id)
        if cancellation.is_set() or (deadline and time.monotonic() >= deadline):
            poc_store.set_job_state(job_id, "cancelled", json.dumps({"completed_actions": len(results)}))
        else:
            poc_store.set_job_state(job_id, "done", json.dumps({"completed_actions": len(results)}))
    except Exception as exc:
        poc_store.set_job_state(job_id, "error", f"execution job failed: {type(exc).__name__}")
        raise
    return results


def execution_status(scenario_id: str) -> dict[str, Any]:
    """Return the newest execution job's state, live stages, and a redacted log tail."""
    db = poc_store._conn()
    try:
        job_row = db.execute(
            "SELECT * FROM poc_jobs WHERE scenario_id=? AND kind='execute' ORDER BY created_at DESC LIMIT 1",
            (scenario_id,),
        ).fetchone()
        if not job_row:
            return {"job_state": "idle", "per_action": [], "logs_tail": ""}
        job = dict(job_row)
        rows = db.execute(
            "SELECT result FROM poc_runs WHERE scenario_id=? AND ts>=? ORDER BY id",
            (scenario_id, job["created_at"]),
        ).fetchall()
    finally:
        db.close()
    per_action = []
    latest_result: dict[str, Any] | None = None
    for row in rows:
        try:
            result = json.loads(row["result"])
        except (TypeError, json.JSONDecodeError):
            continue
        latest_result = result
        per_action.append({"action_id": result.get("action_id"), "stages": result.get("stages") or {}})
    try:
        detail = json.loads(job.get("detail") or "{}")
    except json.JSONDecodeError:
        detail = {}
    current_id = detail.get("current_action_id")
    if current_id and not any(item.get("action_id") == current_id for item in per_action):
        per_action.append({"action_id": current_id, "stages": detail.get("stages") or asdict(ExecStages())})
    logs_tail = ""
    if latest_result and latest_result.get("logs_path"):
        candidate = (config.DATA_DIR / latest_result["logs_path"]).resolve()
        try:
            candidate.relative_to(config.DATA_DIR.resolve())
            logs_tail = _redact(candidate.read_text(encoding="utf-8", errors="replace")[-4000:])
        except (OSError, ValueError):
            logs_tail = ""
    return {"job_state": job["state"], "per_action": per_action, "logs_tail": logs_tail}


def cancel_execution(scenario_id: str) -> dict[str, bool]:
    """Request cancellation of the newest pending/running execution job."""
    db = poc_store._conn()
    try:
        row = db.execute(
            "SELECT id,state FROM poc_jobs WHERE scenario_id=? AND kind='execute' ORDER BY created_at DESC LIMIT 1",
            (scenario_id,),
        ).fetchone()
    finally:
        db.close()
    if not row or row["state"] not in {"pending", "running"}:
        return {"cancelled": False}
    poc_store.request_cancel(row["id"])
    return {"cancelled": True}
