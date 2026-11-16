"""Dependency and topology planning endpoints (modules 4 and 5)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from cr_contracts import iter_errors

from app import store
from app.planner.catalogue import public_catalogue
from app.planner.dependencies import plan_dependencies
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
    approval: dict[str, Any] = {
        "approved": bool(request.approved),
        "approved_by": request.approved_by or "user",
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "connections_digest": connections_digest(plan),
    }
    if request.note:
        approval["note"] = request.note
    plan["approval"] = approval
    ir["environment_plan"] = plan
    _validated_update(scenario_id, ir, "topology-approval")
    return plan


@router.get("/{scenario_id}/topology")
def get_topology(scenario_id: str):
    ir = _get_or_404(scenario_id)
    plan = ir.get("environment_plan")
    if plan is None:
        raise HTTPException(status_code=404, detail="Topology has not been generated")
    errors = iter_errors("environment-plan", plan)
    if errors:
        raise HTTPException(status_code=409, detail={"message": "Stored topology is invalid", "errors": errors})
    return plan


# --- Inventory read endpoints (module 4 pre-check / substitute transparency) ---
# inv-gui frontend calls these. The POST override endpoint is a documented follow-up
# (needs an IR schema field + inv-map/inv-missing to honour it); the panel degrades
# gracefully (404 -> "unimplemented") until it exists.
from app.planner import inventory as _inv  # noqa: E402


def _inventory_items(ir: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for s in ir.get("services", []) or []:
        if not isinstance(s, dict):
            continue
        cve = s.get("cve")
        cves = [str(c) for c in cve] if isinstance(cve, list) else ([str(cve)] if cve else [])
        tech = s.get("attack_technique")
        items.append({"ref_kind": "service", "ref_id": s.get("id"), "name": s.get("name"),
                      "version": s.get("version"), "cves": cves, "attack_technique": tech,
                      "resolution": _inv.resolve(s.get("name"), s.get("version"), cves, tech),
                      "auto_resolution": None, "override": s.get("inventory_override")})
    for h in ir.get("hosts", []) or []:
        if not isinstance(h, dict) or not h.get("os"):
            continue
        items.append({"ref_kind": "host", "ref_id": h.get("id"), "name": h.get("os"),
                      "version": h.get("os_version"), "cves": [], "attack_technique": None,
                      "resolution": _inv.resolve(h.get("os"), h.get("os_version"), None, None),
                      "auto_resolution": None, "override": h.get("inventory_override")})
    return items


@router.get("/inventory")
def get_inventory():
    """Full inventory (have/obtainable/unavailable) for the 'use another component' picker."""
    return {"entries": _inv.inventory_entries()}


@router.get("/{scenario_id}/inventory")
def get_scenario_inventory(scenario_id: str):
    """Per-service/host inventory resolution for this scenario (substitute transparency)."""
    return {"items": _inventory_items(_get_or_404(scenario_id))}
