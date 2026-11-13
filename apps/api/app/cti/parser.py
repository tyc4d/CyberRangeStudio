"""Source parsing with stable, verifiable locators."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SourceUnit:
    id: str
    text: str
    locator: dict[str, str]


class SourceParseError(ValueError):
    """Raised when input cannot be parsed or validated as its declared kind."""


def parse_source(input_kind: str, content: str) -> tuple[list[SourceUnit], dict[str, Any] | None]:
    """Return numbered paragraphs or STIX object text, plus parsed STIX JSON."""
    if not isinstance(content, str) or not content.strip():
        raise SourceParseError("Input content is empty.")

    if input_kind in {"text", "markdown"}:
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", content.strip()) if p.strip()]
        return [
            SourceUnit(f"p{index}", paragraph, {"kind": "paragraph", "ref": str(index)})
            for index, paragraph in enumerate(paragraphs, start=1)
        ], None

    if input_kind != "stix2.1":
        raise SourceParseError(f"Unsupported input_kind: {input_kind!r}.")

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise SourceParseError(f"Invalid STIX 2.1 JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}.") from exc
    if not isinstance(parsed, dict):
        raise SourceParseError("Invalid STIX 2.1 input: the top-level JSON value must be an object.")

    try:
        import stix2

        stix2.parse(content, allow_custom=False, version="2.1")
    except Exception as exc:
        raise SourceParseError(f"Invalid STIX 2.1 object: {type(exc).__name__}: {exc}") from exc

    if parsed.get("type") == "bundle":
        # STIX 2.1 Bundle itself has no spec_version property. If a producer
        # includes one, reject a conflicting version explicitly.
        if parsed.get("spec_version") not in (None, "2.1"):
            raise SourceParseError("Invalid STIX 2.1 bundle: spec_version, when present, must be '2.1'.")
        objects = parsed.get("objects")
        if not isinstance(objects, list):
            raise SourceParseError("Invalid STIX 2.1 bundle: objects must be an array.")
        object_prefix = "objects"
    else:
        objects = [parsed]
        object_prefix = "object"

    units: list[SourceUnit] = []
    for index, obj in enumerate(objects):
        if not isinstance(obj, dict):
            raise SourceParseError(f"Invalid STIX 2.1 object at {object_prefix}[{index}]: expected an object.")
        prefix = f"objects[{index}]" if object_prefix == "objects" else "object"
        found_text = False
        for key in ("name", "description", "pattern", "value"):
            value = obj.get(key)
            if isinstance(value, str) and value.strip():
                units.append(SourceUnit(
                    f"s{index}_{key}", value,
                    {"kind": "stix_path", "ref": f"{prefix}.{key}"},
                ))
                found_text = True
        if not found_text:
            units.append(SourceUnit(
                f"s{index}_object",
                json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                {"kind": "stix_path", "ref": prefix},
            ))
    return units, parsed

