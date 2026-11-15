"""Conservative evidence checks for runner results."""
from __future__ import annotations

from typing import Any

from app.poc.models import CheckStatus

_PROOF_KINDS = {"exploit_effect", "callback", "file_written", "shell_output", "state_change"}


def _get(obj: Any, key: str, default: Any = None) -> Any:
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def proves_effect(evidence: Any) -> bool:
    """True only for traceable, content-addressed evidence of an exploit effect."""
    kind = _get(evidence, "kind")
    path = _get(evidence, "path")
    digest = _get(evidence, "sha256")
    return kind in _PROOF_KINDS and isinstance(path, str) and bool(path.strip()) and isinstance(digest, str) and bool(digest.strip())


def verify_execution(result: Any, plan_item: Any | None = None) -> CheckStatus:
    """Derive a defensible status; never trust runner's PASS without proof.

    Optional plan item preserves the contract rule that not_executable can never pass.
    """
    action_id = _get(result, "action_id")
    if plan_item is not None:
        if _get(plan_item, "action_id") != action_id:
            return "BLOCKED"
        if _get(plan_item, "strategy") == "not_executable":
            return "NOT_TESTED"

    if not _get(result, "target_ownership_verified", False):
        return "BLOCKED"

    stages = _get(result, "stages", {}) or {}
    evidence = list(_get(result, "evidence", []) or [])
    proof = any(proves_effect(item) for item in evidence)
    vuln_behavior = bool(_get(stages, "vuln_behavior", False))
    delivered = bool(_get(stages, "delivered", False))
    responded = bool(_get(stages, "responded", False))

    if vuln_behavior and proof:
        return "PASS"
    if vuln_behavior or (delivered and responded):
        return "FAIL"
    if _get(result, "status") == "BLOCKED":
        return "BLOCKED"
    if _get(result, "status") == "PARTIAL":
        return "PARTIAL"
    if _get(result, "status") == "FAIL" or _get(result, "failure_reason"):
        return "FAIL"
    if not _get(stages, "started", False):
        return "NOT_TESTED"
    return "PARTIAL"
