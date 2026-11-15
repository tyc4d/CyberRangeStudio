"""Sandbox runner for pinned, ownership-gated PoC payloads."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app import config
from app.deploy import manager
from app.poc.models import Evidence, ExecStages, ExecutionResult

from .adapters import get_adapter
from .guard import TargetBlocked, assert_target_owned
from .models import AdapterInput, ExecutionRequest

_MAX_TIMEOUT = 300
_PASS_KINDS = {"exploit_effect", "callback", "file_written", "shell_output", "state_change"}
_SECRET_RE = re.compile(r"(?i)(authorization\s*[:=]\s*|password\s*[:=]\s*|token\s*[:=]\s*)([^\s,;]+)")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redact(text: str) -> str:
    return _SECRET_RE.sub(r"\1[REDACTED]", text)


def _write_artifact(path: Path, content: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SandboxRunner:
    """Execute one adapter payload inside the target's isolated network namespace."""

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        started = _now()
        stages = ExecStages()
        evidence: list[Evidence] = []
        payload_hash = hashlib.sha256(request.payload.encode("utf-8")).hexdigest()
        ref = dict(request.ref or {})
        poc = {"source_url": request.source_url, "ref": ref, "sha256": request.sha256}
        logs_path = f"poc-runs/{request.scenario_id}/{request.action_id}.log"
        artifact = config.DATA_DIR / logs_path
        ownership: dict[str, Any] | None = None
        status = "BLOCKED"
        reason: str | None = None
        exit_code: int | None = None
        confidence = 0.0
        output = ""

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
        adapter = get_adapter(request.exec_method)
        if not adapter:
            status, reason = "BLOCKED", f"unsupported execution method: {request.exec_method}"
        elif request.exec_method in {"python", "http_seq"}:
            if len(request.sha256) != 64 or any(c not in "0123456789abcdef" for c in request.sha256.lower()):
                status, reason = "BLOCKED", "payload SHA-256 must be recorded as a 64-character digest"
            elif hashlib.sha256(request.payload.encode("utf-8")).hexdigest() != request.sha256.lower():
                status, reason = "BLOCKED", "payload SHA-256 does not match the supplied payload"
            elif request.source_url.startswith(("https://github.com/", "http://github.com/")) and not re.fullmatch(
                    r"[0-9a-f]{40,64}", ref.get("commit_sha", "")):
                status, reason = "BLOCKED", "GitHub PoCs must be pinned to a full commit SHA"
            elif bool(getattr(request.cancel, "is_set", lambda: False)()):
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
                        result = manager.probe_in_service(request.scenario_id, request.service_ref,
                                                          prepared.payload, timeout=timeout)
                        exit_code = int(result.get("returncode", 2))
                        output = _redact((result.get("stdout", "") + result.get("stderr", ""))[-12000:])
                        stages.delivered = exit_code != 127 and exit_code != 2
                        stages.responded = bool(output)
                        if exit_code == 124:
                            status, reason = "BLOCKED", f"sandbox timed out after {timeout}s"
                        elif bool(getattr(request.cancel, "is_set", lambda: False)()):
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
                            confidence = 0.99 if reproduced else 0.0
                            if reproduced:
                                evidence_text = f"Expected exploit-effect marker observed: {marker}\n"
                                effect_path = config.DATA_DIR / "poc-runs" / request.scenario_id / f"{request.action_id}-effect.txt"
                                digest = _write_artifact(effect_path, evidence_text)
                                evidence.append(Evidence("exploit_effect", str(effect_path.relative_to(config.DATA_DIR)),
                                                         digest, True, "concrete response marker proves vulnerability behavior"))
                            else:
                                reason = "real payload completed without the expected exploit effect"
                    except (TimeoutError, OSError) as exc:
                        status, reason = "BLOCKED", f"sandbox execution error: {type(exc).__name__}"
        else:
            prepared = adapter.prepare(AdapterInput(request.payload))
            status, reason = "BLOCKED", prepared.blocked_reason or "adapter is not supported by the pinned sandbox"

        log_text = json.dumps({"action_id": request.action_id, "status": status,
                               "ownership": ownership, "output": output, "reason": reason},
                              ensure_ascii=False, sort_keys=True)
        digest = _write_artifact(artifact, log_text)
        evidence.append(Evidence("log", logs_path, digest, True, "redacted runner log"))
        return ExecutionResult(request.action_id, poc, status, stages, logs_path, confidence,
                               True, payload_hash, started, _now(), evidence=evidence,
                               exit_code=exit_code, failure_reason=reason)
