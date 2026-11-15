"""Module 9 router: PoC discovery, exploit validation & environment export.

Six routes under /api/poc (CONTRACT §HTTP API). m9-contracts stubs them to 501;
the owning workers fill them in (plan() is already real in poc.service). The route
signatures, prefix and response shapes are frozen by CONTRACT.md — owners must not
rename them.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.poc import service

router = APIRouter(prefix="/api/poc", tags=["poc"])


class ExecuteRequest(BaseModel):
    action_ids: list[str] | None = None


@router.post("/{scenario_id}/plan")
def poc_plan(scenario_id: str):
    """ValidationPlan from the IR (poc.service.plan, uses planner.reproducibility)."""
    try:
        return service.plan(scenario_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown scenario")


@router.post("/{scenario_id}/discover")
def poc_discover(scenario_id: str):
    """PocManifest (m9-discovery)."""
    raise HTTPException(status_code=501, detail="not implemented: m9-discovery owns /discover")


@router.post("/{scenario_id}/execute")
def poc_execute(scenario_id: str, request: ExecuteRequest | None = None):
    """ExecutionResult[] (m9-runner; auto-runs, ownership-gated)."""
    raise HTTPException(status_code=501, detail="not implemented: m9-runner owns /execute")


@router.post("/{scenario_id}/chain")
def poc_chain(scenario_id: str):
    """ChainValidation (m9-chain)."""
    raise HTTPException(status_code=501, detail="not implemented: m9-chain owns /chain")


@router.get("/{scenario_id}/report")
def poc_report(scenario_id: str):
    """FidelityReport (m9-chain aggregates runner + chain)."""
    raise HTTPException(status_code=501, detail="not implemented: m9-chain owns /report")


@router.post("/{scenario_id}/export")
def poc_export(scenario_id: str):
    """{bundle_path, manifest} (m9-export)."""
    raise HTTPException(status_code=501, detail="not implemented: m9-export owns /export")
