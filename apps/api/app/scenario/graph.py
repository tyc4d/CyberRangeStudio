"""Semantic validation and provenance helpers for editable Scenario IR graphs."""
from __future__ import annotations

import copy
from typing import Any

from cr_contracts import iter_errors


def validate_ir(ir: dict[str, Any]) -> list[str]:
    errors = iter_errors("scenario-ir", ir)
    if errors:
        return errors

    actions = ir.get("actions", [])
    relations = ir.get("relations", [])
    action_ids = [item.get("id") for item in actions]
    if len(set(action_ids)) != len(action_ids):
        return ["Action ids must be unique"]
    relation_ids = [item.get("id") for item in relations]
    if len(set(relation_ids)) != len(relation_ids):
        return ["Relation ids must be unique"]
    known_actions = set(action_ids)
    for relation in relations:
        if relation.get("from_action") not in known_actions or relation.get("to_action") not in known_actions:
            return [f"Relation {relation.get('id')} references an unknown action"]

    evidence_ids = {item.get("id") for item in ir.get("evidence", [])}
    for item in [*actions, *relations]:
        unknown = set(item.get("evidence_refs", [])) - evidence_ids
        if unknown:
            return [f"{item.get('id')} references unknown evidence: {sorted(unknown)}"]
    return []


_EMPTY = (None, "", [], {}, False)


def _meaningful(item: dict[str, Any]) -> dict[str, Any]:
    """Fields that carry content. A key that is absent, null, empty or false says the same
    thing in every spelling, so a client that omits a default (for example ``confirmed``)
    has not edited the item."""
    return {key: value for key, value in item.items() if key != "source" and value not in _EMPTY}


def mark_user_change(current: dict[str, Any] | None, updated: dict[str, Any]) -> dict[str, Any]:
    """Keep provenance on untouched items; edits and new graph nodes belong to the user."""
    result = copy.deepcopy(updated)
    if current is not None:
        if _meaningful(current) == _meaningful(result):
            # Untouched: the stored provenance stands, whatever source the client echoed back.
            result["source"] = current.get("source", "user")
            return result
    result["source"] = "user"
    return result


def reconcile_graph_sources(ir: dict[str, Any], current: dict[str, Any]) -> None:
    for field in ("actions", "relations"):
        old = {item.get("id"): item for item in current.get(field, [])}
        ir[field] = [mark_user_change(old.get(item.get("id")), item) for item in ir.get(field, [])]
    for relation in ir.get("relations", []):
        relation.setdefault("confirmed", False)


_ENTITY_BOOKKEEPING = {"id", "source", "epistemic_status", "field_sources", "evidence_refs", "service_refs"}


def mark_entity_field_edits(ir: dict[str, Any], current: dict[str, Any]) -> None:
    """Record which host/service fields a scenario edit changed as the user's.

    A value the user set by editing (for example which host a service runs on) must be
    distinguishable from what the analysis or the planner produced. Only the changed fields
    are marked; the record's own source and epistemic status are left alone. A host or
    service that did not exist before is the user's.
    """
    for collection in ("hosts", "services"):
        before = {item.get("id"): item for item in current.get(collection, []) or [] if isinstance(item, dict)}
        for item in ir.get(collection, []) or []:
            if not isinstance(item, dict):
                continue
            previous = before.get(item.get("id"))
            if previous is None:
                item.setdefault("source", "user")
                continue
            for key in set(item) | set(previous):
                if key in _ENTITY_BOOKKEEPING:
                    continue
                old, new = previous.get(key), item.get(key)
                if old != new and not (old in _EMPTY and new in _EMPTY):
                    item.setdefault("field_sources", {})[key] = "user"
