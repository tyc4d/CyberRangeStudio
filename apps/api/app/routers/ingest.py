"""CTI analysis and user supplementation endpoints (modules 1 and 2)."""
from __future__ import annotations

import uuid
from typing import Literal

from cr_contracts import iter_errors
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import store
from app.cti.analysis import AnalysisError, analyze_source
from app.cti.parser import SourceParseError, parse_source


router = APIRouter(prefix="/api/ingest", tags=["ingest"])


class AnalyzeRequest(BaseModel):
    input_kind: Literal["text", "markdown", "stix2.1"]
    content: str
    method: Literal["single_pass", "staged", "staged_review"] = "single_pass"
    name: str | None = None


class SupplementRequest(BaseModel):
    missing_item_id: str = Field(min_length=1)
    text: str = Field(min_length=1)


@router.post("/analyze")
def analyze(request: AnalyzeRequest):
    try:
        units, parsed_source = parse_source(request.input_kind, request.content)
    except SourceParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    scenario_name = (request.name or "").strip() or "Untitled scenario"
    try:
        ir = analyze_source(
            input_kind=request.input_kind,
            content=request.content,
            source_name=request.name,
            units=units,
            parsed_source=parsed_source,
            method=request.method,
            name=scenario_name,
        )
    except AnalysisError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        # Preserve the LLM/budget exception so a caller can retry or diagnose it.
        raise HTTPException(status_code=502, detail=f"CTI analysis failed: {type(exc).__name__}: {exc}") from exc

    ir["id"] = store.new_id()
    errors = iter_errors("scenario-ir", ir)
    if errors:
        raise HTTPException(status_code=502, detail={"message": "Generated Scenario IR failed contract validation.", "errors": errors})
    saved = store.create(ir)
    saved_errors = iter_errors("scenario-ir", saved)
    if saved_errors:
        raise HTTPException(status_code=500, detail={"message": "Stored Scenario IR failed contract validation.", "errors": saved_errors})
    return saved


@router.post("/{scenario_id}/supplement")
def supplement(scenario_id: str, request: SupplementRequest):
    ir = store.get(scenario_id)
    if ir is None:
        raise HTTPException(status_code=404, detail="Scenario not found.")
    missing_items = ir.get("missing_items", [])
    target = next((item for item in missing_items if item.get("id") == request.missing_item_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Missing item not found.")

    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Supplement text must not be empty.")
    supplement_id = "supplement-" + uuid.uuid4().hex[:12]
    ir.setdefault("supplements", []).append({
        "id": supplement_id,
        "text": text,
        "targets_missing_item": request.missing_item_id,
        "source": "user",
    })
    target["status"] = "user_supplied"
    target["resolution"] = text
    target["resolution_source"] = "user"

    # Keep the generated checklist and record this response as a separate user
    # supplement instead of rewriting original report evidence or inventing a
    # structured host/service fact from free text.
    errors = iter_errors("scenario-ir", ir)
    if errors:
        raise HTTPException(status_code=500, detail={"message": "Supplemented Scenario IR failed contract validation.", "errors": errors})
    return store.update(scenario_id, ir, note="user supplement")
