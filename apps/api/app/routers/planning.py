"""Dependency and topology planning endpoints (modules 4 and 5)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from cr_contracts import iter_errors

from app import store
from app.planner.catalogue import public_catalogue
from app.planner.dependencies import plan_dependencies
from app.planner.topology import attach_environment_plan

router = APIRouter(prefix="/api/planning", tags=["planning"])


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
