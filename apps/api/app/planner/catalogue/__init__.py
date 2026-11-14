"""Curated open-source component catalogue used by planning and IaC modules."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_CATALOGUE_FILE = Path(__file__).with_name("components.json")


@lru_cache(maxsize=1)
def load_components() -> list[dict[str, Any]]:
    return json.loads(_CATALOGUE_FILE.read_text(encoding="utf-8"))


def public_catalogue() -> dict[str, Any]:
    return {"components": load_components()}


def component_by_id(component_id: str | None) -> dict[str, Any] | None:
    if not component_id:
        return None
    return next((item for item in load_components() if item["id"] == component_id), None)


def match_software(name: str) -> tuple[dict[str, Any] | None, bool]:
    """Return an exact catalogue entry or a clearly labelled substitute."""
    normalized = " ".join(name.casefold().replace("_", " ").split())
    for component in load_components():
        aliases = {alias.casefold() for alias in component.get("aliases", [])}
        if normalized in aliases:
            return component, False
    for component in load_components():
        for substitute in component.get("substitutes_for", []):
            if normalized in {name.casefold() for name in substitute.get("names", [])}:
                return component, True
    return None, False


def runtime_for(component_id: str | None) -> str | None:
    """Return the declared execution runtime for a catalogue entry."""
    component = component_by_id(component_id)
    return component.get("runtime") if component else None
