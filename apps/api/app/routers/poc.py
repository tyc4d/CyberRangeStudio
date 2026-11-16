"""Module 9 router: PoC discovery, exploit validation & environment export.

Routes under /api/poc (CONTRACT §HTTP API). The response shapes and the six core
route names are frozen by CONTRACT.md. plan/discover/execute/chain/report/export are
wired to app.poc.service; execute/status, execute/cancel and export/download are the
additive routes the GUI needs (specified in reports/overnight/m9/requests/).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.iac.generator import PlanError
from app.poc import service
from app.poc.export import ExportError
from app.poc.runner import runner as poc_runner

router = APIRouter(prefix="/api/poc", tags=["poc"])


class ExecuteRequest(BaseModel):
    action_ids: list[str] | None = None


class ExportRequest(BaseModel):
    format: str | None = None


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
    try:
        return service.discover(scenario_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown scenario")


@router.post("/{scenario_id}/execute")
def poc_execute(scenario_id: str, request: ExecuteRequest | None = None):
    """ExecutionResult[] (m9-runner; auto-runs, ownership-gated; honest BLOCKED on local-docker)."""
    try:
        return service.execute(scenario_id, request.action_ids if request else None)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown scenario")


@router.get("/{scenario_id}/execute/status")
def poc_execute_status(scenario_id: str):
    """Live job state for the GUI execution panel."""
    return poc_runner.execution_status(scenario_id)


@router.post("/{scenario_id}/execute/cancel")
def poc_execute_cancel(scenario_id: str):
    """Set the cooperative cancel flag on the running execution job."""
    return poc_runner.cancel_execution(scenario_id)


@router.post("/{scenario_id}/chain")
def poc_chain(scenario_id: str):
    """ChainValidation (m9-chain)."""
    try:
        return service.chain(scenario_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown scenario")


@router.get("/{scenario_id}/report")
def poc_report(scenario_id: str):
    """FidelityReport (m9-chain aggregates runner + chain; 5 metrics kept separate)."""
    try:
        return service.report(scenario_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown scenario")


@router.post("/{scenario_id}/export")
def poc_export(scenario_id: str, request: ExportRequest | None = None):
    """{bundle_path, manifest} (m9-export). Optional body {format: full|iac|evidence}."""
    try:
        return service.export(scenario_id, request.format if request else None)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown scenario")
    except ExportError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except PlanError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{scenario_id}/export/download")
def poc_export_download(scenario_id: str):
    """Return the latest export ZIP bytes for this scenario."""
    from app.poc.export import latest_bundle

    path = latest_bundle(scenario_id)
    if not path:
        raise HTTPException(status_code=404, detail="no export bundle for scenario")
    return FileResponse(str(path), media_type="application/zip",
                        filename=f"cyberrange-export-{scenario_id}.zip")
