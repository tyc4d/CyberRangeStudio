"""Attack Flow STIX 2.1 import/export endpoints."""
from __future__ import annotations

import json
from cr_contracts import iter_errors
from fastapi import APIRouter, HTTPException, Request

from app import store
from app.cti.attackflow import export_attackflow, import_attackflow

router = APIRouter(tags=["attackflow"])


@router.post("/api/ingest/attackflow/import")
async def import_attackflow_endpoint(request: Request):
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Request body must be a JSON STIX bundle.") from exc
    bundle = body.get("bundle", body) if isinstance(body, dict) else body
    try:
        ir = import_attackflow(bundle)
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    errors = iter_errors("scenario-ir", ir)
    if errors:
        raise HTTPException(status_code=422, detail={"message": "Imported Scenario IR failed validation", "errors": errors})
    saved = store.create(ir)
    store.set_source(saved["id"], "stix2.1", json.dumps(bundle, ensure_ascii=False), saved["name"])
    return saved


@router.get("/api/scenario/{scenario_id}/attackflow/export")
def export_attackflow_endpoint(scenario_id: str):
    ir = store.get(scenario_id)
    if ir is None:
        raise HTTPException(status_code=404, detail="Scenario not found.")
    try:
        return export_attackflow(ir)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
