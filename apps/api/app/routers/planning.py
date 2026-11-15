"""Dependency and topology planning endpoints (modules 4 and 5)."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from cr_contracts import iter_errors

from app import store
from app.planner.catalogue import public_catalogue
from app.planner.dependencies import plan_dependencies
from app.planner.approval import topology_approval_state
from app.planner.topology import attach_environment_plan, connections_digest

router = APIRouter(prefix="/api/planning", tags=["planning"])


class ApprovalRequest(BaseModel):
    approved: bool = True
    approved_by: str | None = None
    note: str | None = None


def _get_or_404(scenario_id: str) -> dict[str, Any]:
    ir = store.get(scenario_id)
    if ir is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return ir


def _validated_update(scenario_id: str, ir: dict[str, Any], note: str) -> dict[str, Any]:
    errors = iter_errors("scenario-ir", ir)
    if errors:
        raise HTTPException(status_code=422, detail={"message": "Scenario IR validation failed", "errors": errors})
    try:
        return store.update(scenario_id, ir, note=note, bump_version=False)
    except KeyError:
        raise HTTPException(status_code=404, detail="Scenario not found")


@router.get("/catalogue")
def get_catalogue():
    return public_catalogue()


@router.post("/{scenario_id}/dependencies")
def generate_dependencies(scenario_id: str):
    ir = _get_or_404(scenario_id)
    try:
        updated = plan_dependencies(ir)
    except (TypeError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=f"Could not derive dependencies: {exc}")
    return _validated_update(scenario_id, updated, "dependencies")


@router.post("/{scenario_id}/topology")
def generate_topology(scenario_id: str):
    ir = _get_or_404(scenario_id)
    try:
        updated = attach_environment_plan(ir)
    except (TypeError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=f"Could not generate a valid topology: {exc}")
    return _validated_update(scenario_id, updated, "topology")


@router.post("/{scenario_id}/topology/approve")
def approve_topology(scenario_id: str, request: ApprovalRequest):
    """Record human approval of the planned topology and its connection rules.

    Approval is bound to the current connections via a digest; any later topology
    regeneration or edit resets approval and deployment is refused again.
    """
    ir = _get_or_404(scenario_id)
    plan = ir.get("environment_plan")
    if not isinstance(plan, dict):
        raise HTTPException(status_code=409, detail="Topology has not been generated")
    current_version = ir.get("ir_version")
    if request.approved and (isinstance(current_version, bool) or not isinstance(current_version, int) or current_version < 1):
        raise HTTPException(status_code=409, detail={
            "code": "approval_stale",
            "message": "無法確認目前情境版本；請重新載入情境後再核准。",
        })
    # Legacy plans have no source version. Since the user is approving the plan now,
    # bind that approval to the current IR. Do not overwrite a recorded older version.
    if request.approved and not any(key in plan and plan[key] is not None
                                    for key in ("based_on_ir_version", "approved_ir_version", "ir_version")):
        plan["based_on_ir_version"] = current_version
    approval: dict[str, Any] = {
        "approved": bool(request.approved),
        "approved_by": request.approved_by or "user",
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "connections_digest": connections_digest(plan),
    }
    if request.approved:
        approval["approved_ir_version"] = current_version
        approval["based_on_ir_version"] = current_version
    if request.note:
        approval["note"] = request.note
    plan["approval"] = approval
    ir["environment_plan"] = plan
    state = topology_approval_state(ir)
    if request.approved and not state["deployable"]:
        raise HTTPException(status_code=409, detail={
            "code": "approval_stale",
            "message": state["message"],
            "approval": state,
        })
    saved = _validated_update(scenario_id, ir, "topology-approval")
    response = copy.deepcopy(saved["environment_plan"])
    response["approval_state"] = topology_approval_state(saved)
    return response


@router.get("/{scenario_id}/topology")
def get_topology(scenario_id: str):
    ir = _get_or_404(scenario_id)
    plan = ir.get("environment_plan")
    if plan is None:
        raise HTTPException(status_code=404, detail="Topology has not been generated")
    errors = iter_errors("environment-plan", plan)
    if errors:
        raise HTTPException(status_code=409, detail={"message": "Stored topology is invalid", "errors": errors})
    response = copy.deepcopy(plan)
    response["approval_state"] = topology_approval_state(ir)
    return response
