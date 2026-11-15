"""Shared topology approval and scenario-version checks."""
from __future__ import annotations

from typing import Any

from app.planner.topology import connections_digest


_PLAN_VERSION_KEYS = ("based_on_ir_version", "approved_ir_version", "ir_version")
_APPROVAL_VERSION_KEYS = ("approved_ir_version", "based_on_ir_version", "ir_version")


def _version_values(record: Any, keys: tuple[str, ...]) -> tuple[list[int], str | None]:
    if not isinstance(record, dict):
        return [], None
    values: list[int] = []
    for key in keys:
        if key not in record or record[key] is None:
            continue
        value = record[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            return [], f"{key} is not a positive integer"
        values.append(value)
    if len(set(values)) > 1:
        return values, "recorded version fields disagree"
    return values, None


def _single(values: list[int]) -> int | None:
    return values[0] if values else None


def topology_approval_state(ir: Any) -> dict[str, Any]:
    """Return one fail-closed approval verdict for planning, status, preflight and deploy.

    Legacy approvals without any version metadata remain usable when their connection
    digest matches. Any recorded version must be valid, agree with every other recorded
    version, and equal the current Scenario IR version.
    """
    ir_dict = ir if isinstance(ir, dict) else {}
    plan = ir_dict.get("environment_plan")
    plan = plan if isinstance(plan, dict) else None
    approval = plan.get("approval") if plan else None
    approval = approval if isinstance(approval, dict) else None
    current = ir_dict.get("ir_version")
    current_valid = isinstance(current, int) and not isinstance(current, bool) and current >= 1

    state: dict[str, Any] = {
        "approved": bool(approval and approval.get("approved") is True),
        "stale": False,
        "deployable": False,
        "code": "not_approved",
        "message": "拓樸尚未核准；請先在拓樸頁核准。",
        "current_ir_version": current if current_valid else None,
        "plan_ir_version": None,
        "approved_ir_version": None,
        "versioned": False,
    }
    if plan is None:
        state.update(code="no_plan", message="尚未產生拓樸規劃。")
        return state
    if approval is None or approval.get("approved") is not True:
        return state

    plan_values, plan_error = _version_values(plan, _PLAN_VERSION_KEYS)
    approval_values, approval_error = _version_values(approval, _APPROVAL_VERSION_KEYS)
    state["plan_ir_version"] = _single(plan_values)
    state["approved_ir_version"] = _single(approval_values)
    all_versions = plan_values + approval_values
    state["versioned"] = bool(all_versions)

    version_error = plan_error or approval_error
    if not current_valid:
        version_error = version_error or "current Scenario IR version is missing or invalid"
    if version_error:
        state.update(stale=True, code="approval_metadata_invalid",
                     message="核准版本記錄不完整或不一致；請重新產生拓樸並核准。")
        return state

    if len(set(all_versions)) > 1:
        state.update(stale=True, code="scenario_changed",
                     message="拓樸與核准記錄的情境版本不一致；請重新產生拓樸並核准。")
        return state
    if all_versions and all_versions[0] != current:
        state.update(stale=True, code="scenario_changed",
                     message=(f"拓樸核准依情境第 {all_versions[0]} 版建立，但目前是第 {current} 版；"
                              "請重新產生拓樸並核准。"))
        return state

    if approval.get("connections_digest") != connections_digest(plan):
        state.update(stale=True, code="topology_changed",
                     message="核准後拓樸連線已變更；請重新產生拓樸並核准。")
        return state

    state.update(deployable=True, code="approved",
                 message=("拓樸已核准，且符合目前情境版本。" if all_versions
                          else "舊版拓樸已核准，連線內容相符；未記錄情境版本。"))
    return state
