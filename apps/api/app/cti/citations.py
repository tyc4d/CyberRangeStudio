"""Program-side quote and locator verification."""
from __future__ import annotations

import json
import re
from typing import Any

from app.cti.parser import SourceUnit


_STIX_PATH = re.compile(r"^(?:objects\[(\d+)\]|object)(?:\.([A-Za-z0-9_]+))?$")


def verify_quote(quote: str, locator: dict[str, str], units: list[SourceUnit], parsed_source: dict[str, Any] | None) -> bool:
    """Check that a verbatim quote is present at the supplied source locator."""
    if not isinstance(quote, str) or not quote:
        return False
    kind = locator.get("kind")
    ref = locator.get("ref", "")
    if kind == "paragraph":
        try:
            index = int(ref)
        except (TypeError, ValueError):
            return False
        return any(unit.locator == {"kind": "paragraph", "ref": str(index)} and quote in unit.text for unit in units)
    if kind != "stix_path" or parsed_source is None:
        return False
    match = _STIX_PATH.fullmatch(ref)
    if not match:
        return False
    object_index, property_name = match.groups()
    if object_index is None:
        obj = parsed_source
    else:
        objects = parsed_source.get("objects")
        idx = int(object_index)
        if not isinstance(objects, list) or idx >= len(objects) or not isinstance(objects[idx], dict):
            return False
        obj = objects[idx]
    value: Any = obj.get(property_name) if property_name else obj
    if isinstance(value, str):
        return quote in value
    if isinstance(value, (dict, list)):
        canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return quote in canonical
    return False


def evidence_record(evidence_id: str, quote: str, source_ref: str, units: list[SourceUnit], parsed_source: dict[str, Any] | None) -> dict[str, Any]:
    """Build a schema-shaped evidence record and retain failed citations."""
    unit_by_id = {unit.id: unit for unit in units}
    unit = unit_by_id.get(source_ref)
    if unit is None:
        locator = {"kind": "paragraph", "ref": f"unresolved:{source_ref or 'empty'}"}
    else:
        locator = dict(unit.locator)
    return {
        "id": evidence_id,
        "quote": quote if isinstance(quote, str) else "",
        "locator": locator,
        "quote_verified": verify_quote(quote, locator, units, parsed_source),
    }

