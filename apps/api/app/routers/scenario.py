"""Scenario IR editing endpoints (module 3)."""
from __future__ import annotations

import copy
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException

from app import store
from app.scenario.graph import mark_user_change, reconcile_graph_sources, validate_ir

router = APIRouter(prefix="/api/scenario", tags=["scenario"])


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
    for relation in ir.get("relations", []):
        relation.setdefault("confirmed", False)
    return ir


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
    note = payload.get("note", "scenario edit")
    if not isinstance(note, str):
        raise HTTPException(status_code=422, detail="note must be a string")
    return _save_user_edit(scenario_id, ir, note or "scenario edit")


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
