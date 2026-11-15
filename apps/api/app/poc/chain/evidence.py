"""Verify immutable runner artifacts; labels and nonempty paths are not proof."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from app import config
from app.poc.models import CheckStatus

_PROOF_KINDS = {"exploit_effect", "callback", "file_written", "shell_output", "state_change"}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RUN_ID = re.compile(r"^[0-9a-f]{32}$")
_MAX_ARTIFACT_BYTES = 4 * 1024 * 1024


def _get(obj: Any, key: str, default: Any = None) -> Any:
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def scenario_digest(ir: dict[str, Any]) -> str:
    """Fingerprint the exact IR used for the run, including its version."""
    content = json.dumps(ir, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def timestamp(value: Any) -> datetime | None:
    """Only actual timezone-aware timestamps can establish execution order."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else None
    except ValueError:
        return None


def current_deployment_id(scenario_id: str) -> int | None:
    """Read audit records only; no inspection, subprocess or payload is run here."""
    from app.deploy import manager

    try:
        latest: dict[str, dict[str, Any]] = {}
        for record in manager._lifecycle_records(scenario_id):
            backend = (record.get("details") or {}).get("backend") or "local-docker"
            latest.setdefault(backend, record)
        if any(not (r.get("action") == "up" and r.get("state") == "running")
               and not (r.get("action") == "down" and r.get("state") in {"stopped", "removed"})
               for r in latest.values()):
            return None
        active = [r for r in latest.values() if r.get("action") == "up" and r.get("state") == "running"]
        if len(active) != 1:
            return None
        identity = active[0].get("id")
        return identity if type(identity) is int and identity > 0 else None
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return None


def artifact_bytes(evidence: Any) -> bytes | None:
    """Read a hash-verified file confined to the runner artifact root."""
    path, digest = _get(evidence, "path"), _get(evidence, "sha256")
    if not isinstance(path, str) or not path or not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        return None
    try:
        data_root = config.DATA_DIR.resolve()
        root = (data_root / "poc-runs").resolve()
        if not root.is_relative_to(data_root):
            return None
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = data_root / candidate
        resolved = candidate.resolve(strict=True)
        if candidate != resolved or not resolved.is_relative_to(root) or not resolved.is_file():
            return None
        with resolved.open("rb") as stream:
            content = stream.read(_MAX_ARTIFACT_BYTES + 1)
        if len(content) > _MAX_ARTIFACT_BYTES or hashlib.sha256(content).hexdigest() != digest:
            return None
        return content
    except (OSError, ValueError, RuntimeError):
        return None


def proves_effect(evidence: Any) -> bool:
    """Require an effect artifact's actual bytes and digest, within the allowed root."""
    kind = _get(evidence, "kind")
    return isinstance(kind, str) and kind in _PROOF_KINDS and bool(artifact_bytes(evidence))


def registered_verifier(result: Any, log: dict[str, Any]) -> dict[str, Any] | None:
    from app.poc.runner.payloads import KNOWN_POC_PROOFS

    proof_id = log.get("proof_id")
    proof = KNOWN_POC_PROOFS.get(proof_id) if isinstance(proof_id, str) else None
    poc = _get(result, "poc", {}) or {}
    digest = _get(result, "payload_sha256")
    if not proof or not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        return None
    if (_get(poc, "source_url") != proof.get("source_url") or _get(poc, "sha256") != digest
            or proof.get("sha256") != digest
            or hashlib.sha256(proof.get("payload", "").encode("utf-8")).hexdigest() != digest):
        return None
    ref = _get(poc, "ref", {})
    if not isinstance(ref, dict):
        return None
    if proof.get("source_url", "").startswith(("https://github.com/", "http://github.com/")):
        commit = ref.get("commit_sha", "")
        if not re.fullmatch(r"[0-9a-f]{40,64}", commit) or ref != proof.get("ref"):
            return None
    elif ref != proof.get("ref", {}):
        return None
    return proof


def execution_log(result: Any) -> dict[str, Any] | None:
    """Resolve one immutable attempt by its log, never by scenario/action last row."""
    logs_path = _get(result, "logs_path")
    matches = [e for e in (_get(result, "evidence", []) or [])
               if _get(e, "kind") == "log" and _get(e, "path") == logs_path]
    if len(matches) != 1:
        return None
    content = artifact_bytes(matches[0])
    if content is None:
        return None
    try:
        log = json.loads(content)
        if not isinstance(log, dict):
            return None
        context = log.get("context")
        if not isinstance(context, dict) or not _RUN_ID.fullmatch(str(context.get("run_id", ""))):
            return None
        if not _RUN_ID.fullmatch(str(context.get("job_id", ""))):
            return None
        scenario_id = context.get("scenario_id")
        if not isinstance(scenario_id, str) or not scenario_id:
            return None
        prefix = Path("poc-runs") / hashlib.sha256(scenario_id.encode()).hexdigest()[:16] / context["run_id"]
        relative_log = Path(logs_path)
        if relative_log.is_absolute():
            relative_log = relative_log.relative_to(config.DATA_DIR.resolve())
        if relative_log.parent != prefix:
            return None
        for key in ("action_id", "status", "payload_sha256", "started_at", "ended_at"):
            if log.get(key) != _get(result, key):
                return None
        start, end = timestamp(log.get("started_at")), timestamp(log.get("ended_at"))
        if start is None or end is None or start > end:
            return None
        ownership = log.get("ownership")
        if not isinstance(log.get("evidence"), list):
            return None
        # A prerequisite/ownership gate can stop an attempt before any target is
        # inspected. Its hashed job identity is still valid for batch grouping,
        # without attesting ownership or exploit effect. verify_execution keeps
        # this record BLOCKED; executed results retain the ownership requirement.
        stages = _get(result, "stages", {}) or {}
        gated_block = (
            _get(result, "status") == "BLOCKED" and ownership is None
            and _get(result, "target_ownership_verified") is False
            and all(_get(stages, key) is False for key in (
                "started", "delivered", "responded", "vuln_behavior", "state_change", "action_complete"))
            and not log["evidence"]
            and all(_get(e, "kind") == "log" for e in (_get(result, "evidence", []) or []))
        )
        if not gated_block and (not isinstance(ownership, dict)
                                or ownership.get("scenario_id") != scenario_id or not ownership.get("service_ref")):
            return None
        # Every attached effect must be in the immutable log and in THIS run's directory.
        for evidence in (_get(result, "evidence", []) or []):
            if _get(evidence, "kind") == "log":
                continue
            if not evidence_is_bound(evidence, log):
                return None
        return log
    except (ValueError, TypeError, KeyError, UnicodeDecodeError):
        return None


def evidence_is_bound(evidence: Any, log: dict[str, Any]) -> bool:
    """Bind a receipt/effect to its own run, not merely to some existing artifact."""
    fields = ("kind", "path", "sha256")
    if not any(all(_get(entry, key) == _get(evidence, key) for key in fields) for entry in log.get("evidence", [])):
        return False
    context = log["context"]
    try:
        path = Path(_get(evidence, "path"))
        if path.is_absolute():
            path = path.relative_to(config.DATA_DIR.resolve())
        prefix = Path("poc-runs") / hashlib.sha256(context["scenario_id"].encode()).hexdigest()[:16] / context["run_id"]
        return path.parent == prefix and artifact_bytes(evidence) is not None
    except (ValueError, TypeError):
        return False


def identity_matches(log: dict[str, Any], expected: dict[str, Any] | None = None) -> bool:
    """Old deployments, edited scenarios, and missing context remain unverified."""
    context = log["context"]
    if expected is None:
        from app import store
        try:
            ir = store.get(context["scenario_id"])
        except (OSError, sqlite3.Error, ValueError):
            return False
        if not ir:
            return False
        expected = {"scenario_id": context["scenario_id"], "scenario_sha256": scenario_digest(ir),
                    "deployment_record_id": current_deployment_id(context["scenario_id"])}
    return (type(expected.get("deployment_record_id")) is int
            and type(context.get("deployment_record_id")) is int
            and all(context.get(key) == expected.get(key)
                    for key in ("scenario_id", "scenario_sha256", "deployment_record_id")))


def verify_execution(result: Any, plan_item: Any | None = None, *,
                     expected_context: dict[str, Any] | None = None) -> CheckStatus:
    """Preserve safety outcomes and require registered, run-bound proof for PASS."""
    if plan_item is not None:
        if _get(plan_item, "action_id") != _get(result, "action_id"):
            return "BLOCKED"
        if _get(plan_item, "strategy") == "not_executable":
            return "NOT_TESTED"
    status = _get(result, "status")
    if _get(result, "target_ownership_verified") is not True or status == "BLOCKED":
        return "BLOCKED"
    if not isinstance(status, str):
        return "PARTIAL"
    if status in {"FAIL", "PARTIAL", "NOT_TESTED"}:
        return status
    stages = _get(result, "stages", {}) or {}
    if _get(stages, "vuln_behavior") is True:
        if not any(isinstance(_get(e, "kind"), str) and _get(e, "kind") in _PROOF_KINDS
                   for e in (_get(result, "evidence", []) or [])):
            return "FAIL"
        log = execution_log(result)
        proof = registered_verifier(result, log) if log else None
        marker = proof.get("expected_marker") if proof else None
        if (status == "PASS" and log and proof and identity_matches(log, expected_context)
                and _get(result, "exit_code") == 0 and not _get(result, "failure_reason")
                and all(_get(stages, key) is True for key in ("started", "delivered", "responded", "action_complete"))
                and isinstance(marker, str) and marker and isinstance(log.get("output"), str)
                and marker in log["output"].splitlines()
                and "REQUEST_ERROR=" not in log["output"]
                and any(isinstance(_get(e, "kind"), str) and _get(e, "kind") in _PROOF_KINDS
                        and (content := artifact_bytes(e)) is not None and marker.encode("utf-8") in content
                        for e in (_get(result, "evidence", []) or []))):
            return "PASS"
        return "PARTIAL"
    if _get(stages, "delivered") is True and _get(stages, "responded") is True:
        return "FAIL"
    if _get(result, "failure_reason"):
        return "FAIL"
    return "PARTIAL" if _get(stages, "started") is True else "NOT_TESTED"
