"""MITRE ATT&CK technique lookup.

Reads the distilled catalogue (built from the public ATT&CK Enterprise STIX; see
attack_catalogue.PROVENANCE.md) and resolves a technique id (e.g. "T1190",
"T1059.001") to its official name / tactics / description / URL.

This is *reference enrichment*, kept separate from the Scenario IR so an official
ATT&CK label is never mistaken for a fact the source report stated. The report's
own epistemic_status and source tags are untouched.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

_CATALOGUE_PATH = Path(__file__).with_name("attack_catalogue.json")
_ID_RE = re.compile(r"T\d{4}(?:\.\d{3})?", re.IGNORECASE)


@lru_cache(maxsize=1)
def _catalogue() -> dict[str, Any]:
    try:
        return json.loads(_CATALOGUE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"techniques": {}}


def _normalise(raw: str) -> str | None:
    """Pull a clean ATT&CK id out of a free-form string, e.g. 'T1190 — Exploit...' -> 'T1190'."""
    if not isinstance(raw, str):
        return None
    m = _ID_RE.search(raw)
    return m.group(0).upper() if m else None


def lookup(technique_id: str) -> dict[str, Any] | None:
    tid = _normalise(technique_id)
    if not tid:
        return None
    techniques = _catalogue().get("techniques", {})
    info = techniques.get(tid)
    if info is None and "." in tid:
        # Fall back to the parent technique when a sub-technique is absent.
        info = techniques.get(tid.split(".", 1)[0])
    if info is None:
        return None
    return {"id": tid, **info}


def techniques_for_ir(ir: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Resolve every technique id used by the scenario's actions. Returns {id: info}."""
    out: dict[str, dict[str, Any]] = {}
    for action in ir.get("actions", []):
        raw = action.get("attack_technique")
        if not raw:
            continue
        info = lookup(raw)
        if info and info["id"] not in out:
            out[info["id"]] = info
    return out


def catalogue_meta() -> dict[str, Any]:
    c = _catalogue()
    return {"source": c.get("source"), "downloaded": c.get("downloaded"), "count": c.get("count")}
