"""Shared data contracts. JSON Schemas under ../schemas are the source of truth."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema
from jsonschema import Draft7Validator, RefResolver

_SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"

SCHEMAS = {
    "scenario-ir": "scenario-ir.schema.json",
    "environment-plan": "environment-plan.schema.json",
    "validation-report": "validation-report.schema.json",
}


@lru_cache(maxsize=None)
def load_schema(name: str) -> dict[str, Any]:
    path = _SCHEMA_DIR / SCHEMAS[name]
    return json.loads(path.read_text(encoding="utf-8"))


def _resolver(name: str) -> RefResolver:
    # Resolve cross-schema $ref by filename relative to the schema dir.
    store = {}
    for fname in SCHEMAS.values():
        s = json.loads((_SCHEMA_DIR / fname).read_text(encoding="utf-8"))
        store[fname] = s
        if "$id" in s:
            store[s["$id"]] = s
    base = load_schema(name)
    return RefResolver(base_uri=f"{SCHEMAS[name]}", referrer=base, store=store)


def validate(name: str, instance: dict[str, Any]) -> None:
    """Raise jsonschema.ValidationError if instance does not match schema `name`."""
    schema = load_schema(name)
    Draft7Validator(schema, resolver=_resolver(name)).validate(instance)


def iter_errors(name: str, instance: dict[str, Any]) -> list[str]:
    """Return a list of human-readable validation error strings (empty = valid)."""
    schema = load_schema(name)
    v = Draft7Validator(schema, resolver=_resolver(name))
    return [f"{'/'.join(map(str, e.path))}: {e.message}" for e in v.iter_errors(instance)]


__all__ = ["load_schema", "validate", "iter_errors", "SCHEMAS"]
