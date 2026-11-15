"""Scenario IR editing endpoints (module 3)."""
from __future__ import annotations

import copy
import uuid
from typing import Any

from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Response

from app import store
from app.cti.citations import GRADER_VERSION, grade_evidence_against_units
from app.cti.missing import refresh_missing_items
from app.cti.parser import parse_source
from app.scenario.graph import mark_entity_field_edits, mark_user_change, reconcile_graph_sources, validate_ir

router = APIRouter(prefix="/api/scenario", tags=["scenario"])

# Demo backfill: give the existing CISA AA22-320A scenario its bundled PDF so the
# viewer works for scenarios imported before file capture. Idempotent, never fatal.
try:
    store.backfill_demo_source_file()
except Exception:
    pass


def _get_or_404(scenario_id: str) -> dict[str, Any]:
    ir = store.get(scenario_id)
    if ir is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return ir


def _validate_ir(ir: dict[str, Any]) -> None:
    errors = validate_ir(ir)
    if errors:
        raise HTTPException(status_code=422, detail={"message": "Scenario IR validation failed", "errors": errors})


def _save_user_edit(scenario_id: str, ir: dict[str, Any], note: str) -> dict[str, Any]:
    # The open questions describe the IR; an edited IR needs them recomputed.
    ir["missing_items"] = refresh_missing_items(ir)
    _validate_ir(ir)
    try:
        return store.update(scenario_id, ir, note=note, bump_version=True)
    except KeyError:
        raise HTTPException(status_code=404, detail="Scenario not found")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@router.get("/list")
def list_scenarios():
    return store.list_all()


@router.get("/{scenario_id}")
def get_scenario(scenario_id: str):
    ir = copy.deepcopy(_get_or_404(scenario_id))
    source = store.get_source(scenario_id)
    units = []
    if source is not None and isinstance(source.get("content"), str):
        try:
            units, _ = parse_source(source.get("input_kind", "text"), source["content"])
        except Exception:
            units = []
    for evidence in ir.get("evidence", []):
        if not isinstance(evidence, dict) or "quote_match" in evidence:
            continue
        if units:
            grade, locator = grade_evidence_against_units(
                evidence.get("quote", "") if isinstance(evidence.get("quote"), str) else "",
                evidence.get("locator", {}) if isinstance(evidence.get("locator"), dict) else {},
                units,
            )
            evidence["quote_match"] = grade["level"]
            evidence["match_score"] = grade["score"]
            evidence["matched_text"] = grade["matched"]
            evidence["quote_verified"] = grade["level"] in {"exact", "strong"}
            evidence["locator"] = locator
        else:
            evidence["quote_match"] = "未分級"
            evidence["match_score"] = 0.0
            evidence["matched_text"] = ""
            evidence["quote_verified"] = False
    ir.setdefault("quality", {})["grader_version"] = GRADER_VERSION
    for relation in ir.get("relations", []):
        relation.setdefault("confirmed", False)
    return ir


@router.delete("/{scenario_id}")
def delete_scenario(scenario_id: str):
    _get_or_404(scenario_id)
    delete_fn = getattr(store, "delete_scenario", None)
    if not callable(delete_fn):
        raise HTTPException(
            status_code=501,
            detail="Store deletion is not implemented. Lead must add store.delete_scenario(scenario_id: str) -> bool, deleting the scenario, versions, stored source, and source file atomically.",
        )
    if not delete_fn(scenario_id):
        raise HTTPException(status_code=404, detail="Scenario not found")
    return {"deleted": scenario_id}


@router.put("/{scenario_id}")
def put_scenario(scenario_id: str, payload: dict[str, Any]):
    """Save an edited IR snapshot. Body contract: {"ir": ..., "note": ...}."""
    current = _get_or_404(scenario_id)
    edited = payload.get("ir")
    if not isinstance(edited, dict):
        raise HTTPException(status_code=422, detail="Body must contain an 'ir' object")
    ir = copy.deepcopy(current)
    ir.update(copy.deepcopy(edited))
    ir["id"] = scenario_id
    reconcile_graph_sources(ir, current)
    mark_entity_field_edits(ir, current)
    note = payload.get("note", "scenario edit")
    if not isinstance(note, str):
        raise HTTPException(status_code=422, detail="note must be a string")
    return _save_user_edit(scenario_id, ir, note or "scenario edit")


@router.get("/{scenario_id}/source")
def get_source(scenario_id: str):
    """Return the original imported report verbatim, for review on the Import page.

    404 when the scenario predates source capture or was created from a fixture.
    """
    _get_or_404(scenario_id)
    src = store.get_source(scenario_id)
    if src is None:
        raise HTTPException(status_code=404, detail="No stored source for this scenario.")
    return src


@router.get("/{scenario_id}/source/file")
def get_source_file(scenario_id: str):
    """Return the original uploaded file (PDF) bytes for inline viewing; 404 when none."""
    _get_or_404(scenario_id)
    f = store.get_source_file(scenario_id)
    if f is None:
        raise HTTPException(status_code=404, detail="No stored source file for this scenario.")
    filename = f["filename"] or "source.pdf"
    return Response(
        content=f["data"],
        media_type=f["content_type"] or "application/octet-stream",
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(filename)}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.get("/{scenario_id}/attack")
def get_attack(scenario_id: str):
    """Official MITRE ATT&CK info for the technique ids this scenario's actions use.

    Reference enrichment only (name/tactics/description/url); it does not change the
    Scenario IR or claim the report stated these — the report's own source tags stand.
    """
    from app.cti import attack

    ir = _get_or_404(scenario_id)
    return {"meta": attack.catalogue_meta(), "techniques": attack.techniques_for_ir(ir)}


@router.get("/{scenario_id}/versions")
def get_versions(scenario_id: str):
    _get_or_404(scenario_id)
    return store.versions(scenario_id)


@router.post("/{scenario_id}/actions")
def add_action(scenario_id: str, payload: dict[str, Any]):
    ir = _get_or_404(scenario_id)
    action = copy.deepcopy(payload)
    action.setdefault("id", _new_id("act"))
    action.setdefault("epistemic_status", "supported")
    action["source"] = "user"
    ir.setdefault("actions", []).append(action)
    return _save_user_edit(scenario_id, ir, "add action")


@router.patch("/{scenario_id}/actions/{action_id}")
@router.put("/{scenario_id}/actions/{action_id}")
def update_action(scenario_id: str, action_id: str, payload: dict[str, Any]):
    ir = _get_or_404(scenario_id)
    for index, action in enumerate(ir.get("actions", [])):
        if action.get("id") == action_id:
            updated = {**action, **copy.deepcopy(payload), "id": action_id}
            ir["actions"][index] = mark_user_change(action, updated)
            return _save_user_edit(scenario_id, ir, f"edit action {action_id}")
    raise HTTPException(status_code=404, detail="Action not found")


@router.delete("/{scenario_id}/actions/{action_id}")
def delete_action(scenario_id: str, action_id: str):
    ir = _get_or_404(scenario_id)
    if not any(item.get("id") == action_id for item in ir.get("actions", [])):
        raise HTTPException(status_code=404, detail="Action not found")
    ir["actions"] = [item for item in ir.get("actions", []) if item.get("id") != action_id]
    ir["relations"] = [item for item in ir.get("relations", [])
                       if item.get("from_action") != action_id and item.get("to_action") != action_id]
    return _save_user_edit(scenario_id, ir, f"delete action {action_id}")


@router.post("/{scenario_id}/relations")
def add_relation(scenario_id: str, payload: dict[str, Any]):
    ir = _get_or_404(scenario_id)
    relation = copy.deepcopy(payload)
    relation.setdefault("id", _new_id("rel"))
    relation.setdefault("epistemic_status", "inferred")
    relation.setdefault("confirmed", False)
    relation["source"] = "user"
    ir.setdefault("relations", []).append(relation)
    return _save_user_edit(scenario_id, ir, "add relation")


@router.patch("/{scenario_id}/relations/{relation_id}")
@router.put("/{scenario_id}/relations/{relation_id}")
def update_relation(scenario_id: str, relation_id: str, payload: dict[str, Any]):
    ir = _get_or_404(scenario_id)
    for index, relation in enumerate(ir.get("relations", [])):
        if relation.get("id") == relation_id:
            updated = {**relation, **copy.deepcopy(payload), "id": relation_id}
            ir["relations"][index] = mark_user_change(relation, updated)
            return _save_user_edit(scenario_id, ir, f"edit relation {relation_id}")
    raise HTTPException(status_code=404, detail="Relation not found")


@router.delete("/{scenario_id}/relations/{relation_id}")
def delete_relation(scenario_id: str, relation_id: str):
    ir = _get_or_404(scenario_id)
    if not any(item.get("id") == relation_id for item in ir.get("relations", [])):
        raise HTTPException(status_code=404, detail="Relation not found")
    ir["relations"] = [item for item in ir.get("relations", []) if item.get("id") != relation_id]
    return _save_user_edit(scenario_id, ir, f"delete relation {relation_id}")
