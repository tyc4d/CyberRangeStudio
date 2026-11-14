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


_STIX_TEXT_PROPERTIES = (
    "name", "description", "pattern", "value", "relationship_type",
    "source_ref", "target_ref",
)

_TEMPORAL_RELATIONSHIPS = {
    "precedes": ("temporal", False),
    "followed-by": ("temporal", False),
    "occurs-before": ("temporal", False),
    "occurs-after": ("temporal", True),
}
_DEPENDENCY_RELATIONSHIPS = {
    # The relationship points from the action that needs a prerequisite to
    # the action that provides it, so Scenario IR direction is reversed.
    "requires": ("dependency", True),
    "depends-on": ("dependency", True),
    "depends_on": ("dependency", True),
    # This relationship points from prerequisite to dependent action.
    "prerequisite-for": ("dependency", False),
}


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

        # Public producers such as MITRE ATT&CK use STIX custom properties and
        # custom object types. The library still validates standard STIX 2.1
        # properties while allowing those producer extensions to pass through.
        stix2.parse(content, allow_custom=True, version="2.1")
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
        for key in _STIX_TEXT_PROPERTIES:
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


def extract_stix_candidates(parsed_source: dict[str, Any], units: list[SourceUnit]) -> dict[str, list[dict[str, Any]]]:
    """Extract conservative Scenario IR candidates from a validated STIX source.

    STIX objects often describe a technique, an indicator, or an observable;
    their presence alone does not prove that a specific target host used or was
    affected by them. Candidate status and scope retain that distinction.
    """
    if not isinstance(parsed_source, dict):
        raise SourceParseError("Invalid STIX 2.1 input: expected a parsed object.")

    if parsed_source.get("type") == "bundle":
        objects = parsed_source.get("objects")
        if not isinstance(objects, list):
            raise SourceParseError("Invalid STIX 2.1 bundle: objects must be an array.")
        object_prefix = "objects"
    else:
        objects = [parsed_source]
        object_prefix = "object"

    unit_ids_by_ref = {unit.locator.get("ref"): unit.id for unit in units}

    def evidence(index: int, *properties: str) -> list[str]:
        prefix = f"objects[{index}]" if object_prefix == "objects" else "object"
        refs = [
            ref for key in properties
            if (ref := unit_ids_by_ref.get(f"{prefix}.{key}")) is not None
        ]
        if not refs:
            refs = [unit_ids_by_ref.get(prefix)]
        return list(dict.fromkeys(ref for ref in refs if ref))

    def candidate_base(obj: dict[str, Any], index: int, *properties: str) -> dict[str, Any]:
        candidate: dict[str, Any] = {
            "source": "stix",
            "epistemic_status": "supported",
            "evidence_refs": evidence(index, *properties),
        }
        if isinstance(obj.get("id"), str):
            candidate["stix_id"] = obj["id"]
        return candidate

    result: dict[str, list[dict[str, Any]]] = {
        "actions": [], "relations": [], "hosts": [], "services": [], "artifacts": [],
    }
    action_ids = {
        obj.get("id", f"stix-action-{index}")
        for index, obj in enumerate(objects)
        if isinstance(obj, dict) and obj.get("type") == "attack-pattern" and isinstance(obj.get("name"), str)
    }

    for index, obj in enumerate(objects):
        if not isinstance(obj, dict):
            continue
        obj_type = obj.get("type")
        name = obj.get("name") if isinstance(obj.get("name"), str) else None

        if obj_type == "attack-pattern" and name:
            action = candidate_base(obj, index, "name", "description")
            action.update({
                "id": obj.get("id", f"stix-action-{index}"),
                "name": name,
                "candidate_type": "technique_definition",
                "epistemic_status": "insufficient",
                "epistemic_reason": "A technique definition does not establish that the behavior occurred in this case.",
            })
            if isinstance(obj.get("description"), str) and obj["description"].strip():
                action["description"] = obj["description"]
            result["actions"].append(action)

        elif obj_type == "indicator" and isinstance(obj.get("pattern"), str):
            artifact = candidate_base(obj, index, "name", "pattern", "description")
            artifact.update({
                "id": obj.get("id", f"stix-indicator-{index}"),
                "type": "indicator_pattern",
                "candidate_type": "detection_pattern",
                "pattern": obj["pattern"],
                "claim_scope": "The source defines a detection pattern; it does not assert a sighting.",
            })
            if name:
                artifact["name"] = name
            result["artifacts"].append(artifact)

        elif obj_type in {"malware", "tool", "vulnerability", "file", "artifact"} and name:
            artifact = candidate_base(obj, index, "name", "description", "value")
            artifact.update({"id": obj.get("id", f"stix-artifact-{index}"), "type": obj_type, "name": name})
            if isinstance(obj.get("description"), str) and obj["description"].strip():
                artifact["description"] = obj["description"]
            if isinstance(obj.get("value"), str) and obj["value"].strip():
                artifact["value"] = obj["value"]
            result["artifacts"].append(artifact)

        elif obj_type == "software" and name:
            software_types = obj.get("software_types")
            if isinstance(software_types, list) and any(
                isinstance(value, str) and value.casefold() in {"application", "web-application"}
                for value in software_types
            ):
                service = candidate_base(obj, index, "name", "description")
                service.update({
                    "id": obj.get("id", f"stix-service-{index}"),
                    "name": name,
                    "candidate_type": "software_service_candidate",
                    "epistemic_status": "insufficient",
                    "epistemic_reason": "The software object does not establish that this application ran on the target.",
                })
                if isinstance(obj.get("version"), str) and obj["version"].strip():
                    service["version"] = obj["version"]
                result["services"].append(service)

        elif obj_type in {"ipv4-addr", "ipv6-addr", "domain-name"} and isinstance(obj.get("value"), str):
            host = candidate_base(obj, index, "value")
            host.update({
                "id": obj.get("id", f"stix-host-{index}"),
                "value": obj["value"],
                "role": "unspecified",
                "candidate_type": "network_endpoint",
                "epistemic_status": "insufficient",
                "epistemic_reason": "The observable does not identify a target host or its role.",
            })
            result["hosts"].append(host)

        elif obj_type == "network-traffic":
            protocols = obj.get("protocols")
            protocol = next((value for value in reversed(protocols) if isinstance(value, str)), None) if isinstance(protocols, list) else None
            ports = [obj.get(key) for key in ("dst_port", "src_port") if isinstance(obj.get(key), int)]
            for port_index, port in enumerate(ports, start=1):
                service = candidate_base(obj, index, "src_port", "dst_port", "protocols")
                service.update({
                    "id": f"{obj.get('id', f'stix-service-{index}')}-{port_index}",
                    "port": port,
                    "candidate_type": "network_port_candidate",
                    "epistemic_status": "insufficient",
                    "epistemic_reason": "A network-traffic port does not identify an application service or which endpoint provides it.",
                })
                if protocol:
                    service["protocol"] = protocol
                result["services"].append(service)

        elif obj_type == "relationship":
            relationship_type = obj.get("relationship_type")
            source_ref = obj.get("source_ref")
            target_ref = obj.get("target_ref")
            if not isinstance(relationship_type, str) or not isinstance(source_ref, str) or not isinstance(target_ref, str):
                continue
            normalized_type = relationship_type.casefold()
            kind, reverse = _TEMPORAL_RELATIONSHIPS.get(
                normalized_type,
                _DEPENDENCY_RELATIONSHIPS.get(normalized_type, ("unclassified", False)),
            )
            relation = candidate_base(obj, index, "relationship_type", "source_ref", "target_ref")
            relation.update({
                "id": obj.get("id", f"stix-relation-{index}"),
                "relationship_type": relationship_type,
                "source_ref": source_ref,
                "target_ref": target_ref,
                "kind": kind,
                "candidate_type": "stix_relationship",
            })
            if kind in {"temporal", "dependency"}:
                from_action, to_action = (target_ref, source_ref) if reverse else (source_ref, target_ref)
                if from_action in action_ids and to_action in action_ids:
                    relation["from_action"] = from_action
                    relation["to_action"] = to_action
                else:
                    relation["epistemic_status"] = "insufficient"
                    relation["epistemic_reason"] = "The relationship endpoints are not both recognized action candidates."
            else:
                relation["claim_scope"] = "An explicit STIX relationship; its type is not temporal or a dependency."
            result["relations"].append(relation)

    return result

