"""Dependency and topology planning endpoints (modules 4 and 5)."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
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


class InventoryOverrideRequest(BaseModel):
    ref_id: str = Field(min_length=1)
    action: Literal["accept", "replace", "version", "clear"]
    component_id: str | None = None
    version: str | None = None


def _get_or_404(scenario_id: str) -> dict[str, Any]:
    ir = store.get(scenario_id)
    if ir is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return ir


def _validated_update(scenario_id: str, ir: dict[str, Any], note: str, *, bump_version: bool = False) -> dict[str, Any]:
    errors = iter_errors("scenario-ir", ir)
    if errors:
        raise HTTPException(status_code=422, detail={"message": "Scenario IR validation failed", "errors": errors})
    try:
        return store.update(scenario_id, ir, note=note, bump_version=bump_version)
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


# --- Inventory read endpoints (module 4 pre-check / substitute transparency) ---
from app.planner import inventory as _inv  # noqa: E402


def _inventory_items(ir: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for service in ir.get("services", []) or []:
        if not isinstance(service, dict):
            continue
        cve = service.get("cve")
        cves = [str(value) for value in cve] if isinstance(cve, list) else ([str(cve)] if cve else [])
        technique = service.get("attack_technique")
        automatic = _inv.resolve(service.get("name"), service.get("version"), cves, technique)
        override = service.get("inventory_override")
        resolution = _inv.resolve_with_override(service.get("name"), service.get("version"), cves, technique, override)
        items.append({
            "ref_kind": "service", "ref_id": service.get("id"), "name": service.get("name"),
            "version": service.get("version"), "cves": cves, "attack_technique": technique,
            "resolution": resolution,
            "auto_resolution": automatic if override and resolution != automatic else None,
            "pending_confirmation": bool(not override and automatic.get("is_substitute")),
            "override": override,
        })
    for host in ir.get("hosts", []) or []:
        if not isinstance(host, dict) or not host.get("os"):
            continue
        automatic = _inv.resolve(host.get("os"), host.get("os_version"), None, None)
        items.append({
            "ref_kind": "host", "ref_id": host.get("id"), "name": host.get("os"),
            "version": host.get("os_version"), "cves": [], "attack_technique": None,
            "resolution": automatic, "auto_resolution": None, "pending_confirmation": False,
            "override": host.get("inventory_override"),
        })
    return items


@router.get("/inventory")
def get_inventory():
    """Full inventory (have/obtainable/unavailable) for component selection."""
    return {"entries": _inv.inventory_entries()}


@router.get("/{scenario_id}/inventory")
def get_scenario_inventory(scenario_id: str):
    """Per-service and host inventory resolution for this scenario."""
    return {"items": _inventory_items(_get_or_404(scenario_id))}


@router.post("/{scenario_id}/inventory/override")
def override_scenario_inventory(scenario_id: str, request: InventoryOverrideRequest):
    """Persist a user decision for one service and return the effective inventory view."""
    ir = _get_or_404(scenario_id)
    ref_id = request.ref_id.strip()
    if not ref_id:
        raise HTTPException(status_code=422, detail="ref_id must not be blank")
    service = next((item for item in ir.get("services", []) or []
                    if isinstance(item, dict) and item.get("id") == ref_id), None)
    host = next((item for item in ir.get("hosts", []) or []
                 if isinstance(item, dict) and item.get("id") == ref_id), None)
    if service is None and host is None:
        raise HTTPException(status_code=404, detail=f"Inventory reference {ref_id!r} was not found in this scenario")

    target = service if service is not None else host
    assert target is not None
    current = target.get("inventory_override")
    if request.action in {"accept", "clear"} and (request.component_id is not None or request.version is not None):
        raise HTTPException(status_code=422, detail=f"{request.action} does not accept component_id or version")
    if request.action == "replace" and request.version is not None:
        raise HTTPException(status_code=422, detail="replace does not accept version")
    if request.action == "version" and request.component_id is not None:
        raise HTTPException(status_code=422, detail="version does not accept component_id")
    if host is not None and request.action != "clear":
        raise HTTPException(status_code=422, detail="Host OS overrides are not supported yet; no host value was changed")

    if request.action == "clear":
        changed = bool(current)
        target.pop("inventory_override", None)
    else:
        override: dict[str, Any] = {"action": request.action}
        if request.action == "replace":
            component_id = str(request.component_id or "").strip()
            if not component_id:
                raise HTTPException(status_code=422, detail="component_id is required for replace")
            override["component_id"] = component_id
        elif request.action == "version":
            selected_version = str(request.version or "").strip()
            if not selected_version:
                raise HTTPException(status_code=422, detail="version is required for version")
            override["version"] = selected_version

        if service is not None:
            cve = service.get("cve")
            cves = [str(value) for value in cve] if isinstance(cve, list) else ([str(cve)] if cve else [])
            tech = next((action.get("attack_technique") for action in ir.get("actions", []) or []
                         if action.get("target_host_ref") == service.get("host_ref") and action.get("attack_technique")), None)
            try:
                _inv.resolve_with_override(service.get("name"), service.get("version"), cves, tech, override)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc))
        override["at"] = datetime.now(timezone.utc).isoformat()
        target["inventory_override"] = override
        changed = True

    if changed:
        # Component selection can change the deployed image even when topology connections stay
        # the same. Invalidate approval explicitly and bump the IR version for version-bound plans.
        plan = ir.get("environment_plan")
        approval = plan.get("approval") if isinstance(plan, dict) else None
        if isinstance(approval, dict):
            approval["approved"] = False
        updated = _validated_update(scenario_id, ir, "inventory-override", bump_version=True)
    else:
        updated = ir

    return {"items": _inventory_items(updated), "scenario": updated}
