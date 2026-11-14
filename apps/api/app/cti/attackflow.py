"""MITRE Attack Flow STIX 2.1 <-> Scenario IR conversion."""
from __future__ import annotations

import hashlib
import uuid
from typing import Any

from cr_contracts import iter_errors

_NS = uuid.UUID("d0eaa97b-8f6f-4cb0-b9ac-9c581407a2f2")
_EXT_ID = "extension-definition--fb9c968a-745b-4ade-9b25-c324172197f4"
_EXT_URL = "https://github.com/center-for-threat-informed-defense/attack-flow"


def _id(kind: str, value: str) -> str:
    return str(uuid.uuid5(_NS, f"{kind}:{value}"))


def _ext(obj: dict[str, Any]) -> dict[str, Any]:
    exts = obj.get("extensions") or {}
    value = exts.get(_EXT_ID) or next(iter(exts.values()), {})
    return value if isinstance(value, dict) else {}


def _get(obj: dict[str, Any], key: str, default: Any = None) -> Any:
    return obj.get(key, _ext(obj).get(key, default))


def import_attackflow(bundle: dict[str, Any]) -> dict[str, Any]:
    """Convert Attack Flow STIX objects in a bundle to a validated Scenario IR."""
    if not isinstance(bundle, dict):
        raise ValueError("Attack Flow input must be a STIX bundle object")
    objects = bundle.get("objects")
    if not isinstance(objects, list):
        raise ValueError("Attack Flow input must be a STIX bundle with an objects array")
    by_id = {o.get("id"): o for o in objects if isinstance(o, dict) and o.get("id")}
    flows = [o for o in objects if isinstance(o, dict) and o.get("type") == "attack-flow"]
    flow_obj = flows[0] if flows else {}
    name = flow_obj.get("name") or "Imported Attack Flow"
    refs_by_stix = {o.get("id"): o for o in objects if isinstance(o, dict)}
    external = {}
    for obj in objects:
        if isinstance(obj, dict) and obj.get("type") == "attack-pattern":
            for ref in obj.get("external_references", []):
                if ref.get("source_name") == "mitre-attack" and ref.get("external_id"):
                    external[obj.get("id")] = ref["external_id"]
                    break

    actions = []
    conditions = []
    operators = []
    assets = []
    stix_to_ir: dict[str, str] = {}
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        typ = obj.get("type")
        if typ not in {"attack-action", "attack-condition", "attack-operator", "attack-asset"}:
            continue
        sid = obj.get("id", "")
        iid = sid or f"{typ}-{len(stix_to_ir)}"
        stix_to_ir[sid] = iid
        ext = _ext(obj)
        metadata = ext.get("scenario_ir_metadata", {})
        status = metadata.get("epistemic_status", ext.get("epistemic_status", "supported"))
        source = metadata.get("source", ext.get("source", "stix"))
        evidence = metadata.get("evidence_refs", ext.get("evidence_refs"))
        base = {"id": iid, "epistemic_status": status, "source": source}
        if evidence:
            base["evidence_refs"] = evidence
        if typ == "attack-action":
            technique_ref = _get(obj, "technique_ref")
            technique = external.get(technique_ref) or _get(obj, "technique_id")
            action = {**base, "name": obj.get("name") or "Unnamed action"}
            for key in ("description", "tactic_id", "execution_start", "execution_end", "command_ref"):
                val = _get(obj, key)
                if val is not None:
                    action["attack_tactic" if key == "tactic_id" else key] = val
                    if key == "tactic_id":
                        action["tactic_id"] = val
            if technique:
                action["attack_technique"] = technique
                action["technique_id"] = technique
            if _get(obj, "effect_refs") is not None:
                action["effect_refs"] = _get(obj, "effect_refs")
            if _get(obj, "asset_refs") is not None:
                action["asset_refs"] = _get(obj, "asset_refs")
            actions.append(action)
        elif typ == "attack-condition":
            conditions.append({**base, **{k: v for k, v in {
                "description": obj.get("description"), "on_true_refs": _get(obj, "on_true_refs"),
                "on_false_refs": _get(obj, "on_false_refs"), "pattern": _get(obj, "pattern"),
                "pattern_type": _get(obj, "pattern_type"),
            }.items() if v is not None}})
        elif typ == "attack-operator":
            operators.append({**base, "operator": str(_get(obj, "operator", "AND")).upper(), **({"effect_refs": _get(obj, "effect_refs")} if _get(obj, "effect_refs") is not None else {})})
        else:
            assets.append({**base, "name": obj.get("name") or "Unnamed asset", **({"description": obj["description"]} if obj.get("description") else {}), "object_ref": _get(obj, "object_ref", sid)})

    # STIX refs are preserved in IR refs. Convert flow entrypoints where known.
    start_refs = flow_obj.get("start_refs", [])
    flow = {
        "name": name,
        "scope": _get(flow_obj, "scope", "other"),
        "start_refs": [stix_to_ir.get(r, r) for r in start_refs],
    }
    if flow_obj.get("description"):
        flow["description"] = flow_obj["description"]
    ir: dict[str, Any] = {
        "schema_version": "1.0", "id": "scn_" + uuid.uuid4().hex[:12], "name": name,
        "provenance": {"input_kind": "stix2.1", "input_sha256": hashlib.sha256(str(bundle).encode()).hexdigest(), "source_name": "Attack Flow STIX"},
        "actions": actions, "relations": [], "flow": flow,
    }
    if conditions:
        ir["conditions"] = conditions
    if operators:
        ir["operators"] = operators
    if assets:
        ir["assets"] = assets
    for action in actions:
        for ref in action.get("effect_refs", []):
            if ref in stix_to_ir:
                ir["relations"].append({
                    "id": "rel-" + _id("relation", action["id"] + ":" + ref)[:12],
                    "from_action": action["id"], "to_action": stix_to_ir[ref], "kind": "dependency",
                    "rationale": "Attack Flow effect_refs indicates the later object depends on this action's effect.",
                    "epistemic_status": action["epistemic_status"], "source": "stix",
                })
    errors = iter_errors("scenario-ir", ir)
    if errors:
        raise ValueError("Imported Attack Flow failed Scenario IR validation: " + "; ".join(errors))
    return ir


def export_attackflow(ir: dict[str, Any]) -> dict[str, Any]:
    """Export Scenario IR as an Attack Flow extension STIX 2.1 bundle."""
    errors = iter_errors("scenario-ir", ir)
    if errors:
        raise ValueError("Scenario IR failed validation: " + "; ".join(errors))
    objects: list[dict[str, Any]] = [{
        "type": "extension-definition", "spec_version": "2.1", "id": _EXT_ID,
        "created": "2024-01-01T00:00:00.000Z", "modified": "2024-01-01T00:00:00.000Z",
        "name": "MITRE ATT&CK Flow", "description": "Attack Flow extension for STIX 2.1",
        "schema": "https://center-for-threat-informed-defense.github.io/attack-flow/stix/attack-flow-schema-2.0.0.json", "version": "2.0.0",
        "external_references": [{"source_name": "GitHub", "url": _EXT_URL}], "extension_types": ["new-sdo"],
    }]
    def sid(kind: str, ident: str) -> str:
        return f"{kind}--{_id(kind, ident)}"
    def extension(item: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any]:
        meta = {k: item[k] for k in ("epistemic_status", "source", "evidence_refs") if item.get(k) is not None}
        return {"extensions": {_EXT_ID: {"extension_type": "new-sdo", **({"scenario_ir_metadata": meta} if meta else {})}}}

    ref_map = {a["id"]: sid("attack-action", a["id"]) for a in ir.get("actions", [])}
    ref_map.update({a["id"]: sid("attack-condition", a["id"]) for a in ir.get("conditions", [])})
    ref_map.update({a["id"]: sid("attack-operator", a["id"]) for a in ir.get("operators", [])})
    ref_map.update({a["id"]: sid("attack-asset", a["id"]) for a in ir.get("assets", [])})
    for action in ir.get("actions", []):
        ext = {k: action[k] for k in ("execution_start", "execution_end", "command_ref") if action.get(k) is not None}
        technique_id = action.get("technique_id", action.get("attack_technique"))
        if technique_id is not None:
            ext["technique_id"] = technique_id
        tactic_id = action.get("tactic_id", action.get("attack_tactic"))
        if tactic_id is not None:
            ext["tactic_id"] = tactic_id
        ext["effect_refs"] = [ref_map.get(r, r) for r in action.get("effect_refs", [])]
        ext["asset_refs"] = [ref_map.get(r, r) for r in action.get("asset_refs", [])]
        obj = {"type": "attack-action", "spec_version": "2.1", "id": ref_map[action["id"]], "created": "2024-01-01T00:00:00.000Z", "modified": "2024-01-01T00:00:00.000Z", "name": action["name"], **ext, **extension(action, ext)}
        if action.get("description"):
            obj["description"] = action["description"]
        if action.get("attack_technique"):
            obj["technique_ref"] = next((o["id"] for o in objects if o.get("type") == "attack-pattern" and o.get("external_references", [{}])[0].get("external_id") == action["attack_technique"]), None)
            if not obj["technique_ref"]:
                obj.pop("technique_ref")
                objects.append({"type": "attack-pattern", "spec_version": "2.1", "id": sid("attack-pattern", action["attack_technique"]), "created": "2024-01-01T00:00:00.000Z", "modified": "2024-01-01T00:00:00.000Z", "name": action.get("name", action["attack_technique"]), "external_references": [{"source_name": "mitre-attack", "external_id": action["attack_technique"], "url": "https://attack.mitre.org/techniques/" + action["attack_technique"].replace('.', '/') + "/"}]})
                obj["technique_ref"] = sid("attack-pattern", action["attack_technique"])
        objects.append(obj)
    for condition in ir.get("conditions", []):
        fields = {k: [ref_map.get(r, r) for r in condition[k]] if k.endswith("_refs") else condition[k] for k in ("on_true_refs", "on_false_refs", "pattern", "pattern_type", "description") if condition.get(k) is not None}
        objects.append({"type": "attack-condition", "spec_version": "2.1", "id": ref_map[condition["id"]], "created": "2024-01-01T00:00:00.000Z", "modified": "2024-01-01T00:00:00.000Z", **fields, **extension(condition, fields)})
    for operator in ir.get("operators", []):
        fields = {"operator": operator["operator"], "effect_refs": [ref_map.get(r, r) for r in operator.get("effect_refs", [])]}
        objects.append({"type": "attack-operator", "spec_version": "2.1", "id": ref_map[operator["id"]], "created": "2024-01-01T00:00:00.000Z", "modified": "2024-01-01T00:00:00.000Z", **fields, **extension(operator, fields)})
    for asset in ir.get("assets", []):
        fields = {"object_ref": asset.get("object_ref", "")}
        objects.append({"type": "attack-asset", "spec_version": "2.1", "id": ref_map[asset["id"]], "created": "2024-01-01T00:00:00.000Z", "modified": "2024-01-01T00:00:00.000Z", "name": asset.get("name", "Asset"), **fields, **extension(asset, fields)})
    flow = ir.get("flow", {})
    flow_fields = {"scope": flow.get("scope", "other")}
    objects.append({"type": "attack-flow", "spec_version": "2.1", "id": sid("attack-flow", ir["id"]), "created": ir.get("created_at", "2024-01-01T00:00:00.000Z"), "modified": ir.get("updated_at", "2024-01-01T00:00:00.000Z"), "name": flow.get("name", ir["name"]), "description": flow.get("description", ""), "start_refs": [ref_map.get(r, r) for r in flow.get("start_refs", [])], **flow_fields, **extension({}, flow_fields)})
    return {"type": "bundle", "id": "bundle--" + _id("bundle", ir["id"]), "objects": objects}
