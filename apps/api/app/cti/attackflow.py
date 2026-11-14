"""MITRE Attack Flow STIX 2.1 <-> Scenario IR conversion."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from typing import Any

import stix2
from cr_contracts import iter_errors

from app.cti import attack

_NS = uuid.UUID("d0eaa97b-8f6f-4cb0-b9ac-9c581407a2f2")
_EXT_ID = "extension-definition--fb9c968a-745b-4ade-9b25-c324172197f4"
_EXT_URL = "https://github.com/center-for-threat-informed-defense/attack-flow"
_STIX_ID_RE = re.compile(r"^[a-z][a-z0-9-]*--[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_TECHNIQUE_RE = re.compile(r"^T\d{4}(?:\.\d{3})?$", re.IGNORECASE)


def _uuid(kind: str, value: str) -> str:
    return str(uuid.uuid5(_NS, f"{kind}:{value}"))


def _sid(kind: str, ident: str) -> str:
    if _STIX_ID_RE.fullmatch(ident) and ident.startswith(kind + "--"):
        return ident
    return f"{kind}--{_uuid(kind, ident)}"


def _ext(obj: dict[str, Any]) -> dict[str, Any]:
    exts = obj.get("extensions") or {}
    value = exts.get(_EXT_ID) or next(iter(exts.values()), {})
    return value if isinstance(value, dict) else {}


def _get(obj: dict[str, Any], key: str, default: Any = None) -> Any:
    return obj.get(key, _ext(obj).get(key, default))


def _graph_nodes(objects: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {o["id"]: o for o in objects if o.get("type") in {
        "attack-flow", "attack-action", "attack-condition", "attack-operator", "attack-asset"
    } and isinstance(o.get("id"), str)}


def _iter_out_edges(obj: dict[str, Any]):
    """Yield (target, kind, reason) from every Attack Flow graph reference field."""
    ext = _ext(obj)
    kind_map = ext.get("edge_kinds", {})
    for ref in _get(obj, "effect_refs", []) or []:
        yield ref, kind_map.get(ref, "dependency"), "Attack Flow effect_refs"
    for ref in _get(obj, "asset_refs", []) or []:
        yield ref, kind_map.get(ref, "dependency"), "Attack Flow asset_refs"
    for key in ("on_true_refs", "on_false_refs"):
        for ref in _get(obj, key, []) or []:
            yield ref, kind_map.get(ref, "dependency"), f"Attack Flow {key} branch"
    for edge in ext.get("edge_refs", []) or []:
        if isinstance(edge, dict) and edge.get("target_ref"):
            yield edge["target_ref"], edge.get("kind", "dependency"), "CyberRange Attack Flow edge metadata"


def _validate_bundle(bundle: dict[str, Any]) -> list[str]:
    if not isinstance(bundle, dict) or bundle.get("type") != "bundle":
        raise ValueError("Input must be a STIX 2.1 bundle.")
    if not isinstance(bundle.get("id"), str) or not _STIX_ID_RE.fullmatch(bundle["id"]) or not bundle["id"].startswith("bundle--"):
        raise ValueError("Invalid or missing STIX bundle id.")
    objects = bundle.get("objects")
    if not isinstance(objects, list):
        raise ValueError("STIX bundle must contain an objects array.")
    ids: set[str] = set()
    for obj in objects:
        if not isinstance(obj, dict):
            raise ValueError("Every STIX bundle object must be a JSON object.")
        oid, typ = obj.get("id"), obj.get("type")
        if not isinstance(typ, str) or not isinstance(oid, str) or not _STIX_ID_RE.fullmatch(oid) or not oid.startswith(typ + "--"):
            raise ValueError(f"Invalid STIX object id: {oid!r} (type {typ!r}).")
        if oid in ids:
            raise ValueError(f"Duplicate STIX object id: {oid}.")
        ids.add(oid)
    try:
        stix2.parse(bundle, allow_custom=True, version="2.1")
    except Exception as exc:
        raise ValueError(f"STIX 2.1 schema validation failed: {exc}") from exc
    flows = [o for o in objects if o.get("type") == "attack-flow"]
    if len(flows) != 1:
        raise ValueError(f"Expected exactly one attack-flow object; found {len(flows)}.")
    node_ids = set(_graph_nodes(objects))
    warnings: list[str] = []
    for obj in objects:
        if obj.get("type") not in {"attack-flow", "attack-action", "attack-condition", "attack-operator", "attack-asset"}:
            continue
        for ref, _kind, field in _iter_out_edges(obj):
            if ref not in node_ids:
                raise ValueError(f"Dangling {field} reference {ref!r} on {obj['id']}.")
        if obj.get("type") == "attack-flow":
            for ref in obj.get("start_refs", []):
                if ref not in node_ids:
                    raise ValueError(f"Dangling start_refs reference {ref!r} on {obj['id']}.")
        if obj.get("type") == "attack-action":
            for ref in obj.get("asset_refs", []) or []:
                if ref not in node_ids:
                    raise ValueError(f"Dangling asset_refs reference {ref!r} on {obj['id']}.")
        if obj.get("type") == "attack-asset":
            ref = _get(obj, "object_ref")
            if ref and ref not in ids:
                warnings.append(f"Asset {obj['id']} has dangling object_ref {ref!r}; it will be omitted on export.")
    return warnings


def import_attackflow(bundle: dict[str, Any]) -> dict[str, Any]:
    """Validate and convert a STIX 2.1 Attack Flow bundle to Scenario IR.

    Private metadata is retained for direct Python round-trips; the API router
    removes it from the response and persists the same original bundle as source.
    """
    warnings = _validate_bundle(bundle)
    objects = bundle["objects"]
    by_id = {o["id"]: o for o in objects}
    nodes = _graph_nodes(objects)
    flow_obj = next(o for o in objects if o.get("type") == "attack-flow")
    name = flow_obj.get("name") or "Imported Attack Flow"
    external: dict[str, str] = {}
    for obj in objects:
        if obj.get("type") == "attack-pattern":
            for ref in obj.get("external_references", []):
                if ref.get("source_name") == "mitre-attack" and ref.get("external_id"):
                    external[obj["id"]] = ref["external_id"]
                    break

    actions: list[dict[str, Any]] = []
    conditions: list[dict[str, Any]] = []
    operators: list[dict[str, Any]] = []
    assets: list[dict[str, Any]] = []
    for obj in objects:
        typ = obj.get("type")
        if typ not in {"attack-action", "attack-condition", "attack-operator", "attack-asset"}:
            continue
        ext = _ext(obj)
        meta = ext.get("scenario_ir_metadata", {})
        base: dict[str, Any] = {
            "id": obj["id"],
            "epistemic_status": meta.get("epistemic_status", "supported"),
            "source": meta.get("source", "stix"),
        }
        if meta.get("evidence_refs"):
            base["evidence_refs"] = meta["evidence_refs"]
        if typ == "attack-action":
            ref = _get(obj, "technique_ref")
            tid = external.get(ref) or _get(obj, "technique_id")
            act = {**base, "name": obj.get("name") or "Unnamed action"}
            if obj.get("description"):
                act["description"] = obj["description"]
            for key in ("tactic_id", "execution_start", "execution_end", "command_ref"):
                val = _get(obj, key)
                if val is not None:
                    act[key] = val
                    if key == "tactic_id":
                        act["attack_tactic"] = val
            if isinstance(tid, str):
                act["attack_technique"] = tid
                act["technique_id"] = tid
            for key in ("effect_refs", "asset_refs"):
                if _get(obj, key) is not None:
                    act[key] = list(_get(obj, key))
            actions.append(act)
        elif typ == "attack-condition":
            cond = {**base}
            for key in ("description", "on_true_refs", "on_false_refs", "pattern", "pattern_type"):
                val = _get(obj, key)
                if val is not None:
                    cond[key] = list(val) if key.endswith("_refs") else val
            conditions.append(cond)
        elif typ == "attack-operator":
            op = {**base, "operator": str(_get(obj, "operator", "AND")).upper()}
            if _get(obj, "effect_refs") is not None:
                op["effect_refs"] = list(_get(obj, "effect_refs"))
            operators.append(op)
        else:
            asset = {**base, "name": obj.get("name") or "Unnamed asset"}
            if obj.get("description"):
                asset["description"] = obj["description"]
            if _get(obj, "object_ref"):
                asset["object_ref"] = _get(obj, "object_ref")
            assets.append(asset)

    flow = {
        "name": name,
        "scope": _get(flow_obj, "scope", "other"),
        "start_refs": list(flow_obj.get("start_refs", [])),
    }
    if flow_obj.get("description"):
        flow["description"] = flow_obj["description"]
    canonical = json.dumps(bundle, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    ir: dict[str, Any] = {
        "schema_version": "1.0", "id": "scn_" + uuid.uuid4().hex[:12], "name": name,
        "provenance": {"input_kind": "stix2.1", "input_sha256": hashlib.sha256(canonical.encode()).hexdigest(), "source_name": "Attack Flow STIX"},
        "actions": actions, "relations": [], "flow": flow,
        "_attackflow_original_bundle": copy.deepcopy(bundle), "_attackflow_warnings": warnings,
    }
    if conditions:
        ir["conditions"] = conditions
    if operators:
        ir["operators"] = operators
    if assets:
        ir["assets"] = assets

    relation_keys: set[tuple[str, str, str]] = set()
    for obj in objects:
        if obj["id"] not in nodes:
            continue
        for ref, kind, reason in _iter_out_edges(obj):
            key = (obj["id"], ref, kind)
            if key in relation_keys:
                continue
            relation_keys.add(key)
            ir["relations"].append({
                "id": "rel-" + _uuid("relation", ":".join(key))[:12],
                "from_action": obj["id"], "to_action": ref,
                "kind": kind if kind in {"temporal", "dependency"} else "dependency",
                "rationale": reason, "epistemic_status": "supported", "source": "stix",
            })
    # Standard STIX relationship objects can also carry temporal ordering.
    for rel in objects:
        if rel.get("type") != "relationship" or rel.get("relationship_type") not in {"temporal", "dependency"}:
            continue
        src, dst, kind = rel.get("source_ref"), rel.get("target_ref"), rel["relationship_type"]
        if src in nodes and dst in nodes and (src, dst, kind) not in relation_keys:
            relation_keys.add((src, dst, kind))
            ir["relations"].append({"id": rel["id"], "from_action": src, "to_action": dst, "kind": kind,
                                    "rationale": rel.get("description", "Imported STIX relationship."),
                                    "epistemic_status": "supported", "source": "stix"})
    errors = iter_errors("scenario-ir", ir)
    if errors:
        raise ValueError("Imported Attack Flow failed Scenario IR validation: " + "; ".join(errors))
    return ir


def _official_extension_definition() -> dict[str, Any]:
    # Exact official Attack Flow 2.0.0 definition from its published STIX example.
    return {
        "type": "extension-definition", "id": _EXT_ID, "spec_version": "2.1",
        "name": "Attack Flow", "description": "Extends STIX 2.1 with features to create Attack Flows.",
        "created": "2022-08-02T19:34:35.143Z", "modified": "2022-08-02T19:34:35.143Z",
        "created_by_ref": "identity--d673f8cb-c168-42da-8ed4-0cb26725f86c",
        "schema": "https://center-for-threat-informed-defense.github.io/attack-flow/stix/attack-flow-schema-2.0.0.json",
        "version": "2.0.0", "extension_types": ["new-sdo"],
        "external_references": [
            {"source_name": "Documentation", "description": "Documentation for Attack Flow", "url": "https://center-for-threat-informed-defense.github.io/attack-flow"},
            {"source_name": "GitHub", "description": "Source code repository for Attack Flow", "url": _EXT_URL},
        ],
    }


def _valid_technique(action: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    raw = action.get("technique_id") or action.get("attack_technique")
    if action.get("epistemic_status") == "absent" or not isinstance(raw, str) or not _TECHNIQUE_RE.fullmatch(raw):
        return None, None
    info = attack.lookup_exact(raw)
    if info is None:
        return None, None
    return info["id"], info


def _encode_tactic(raw: Any) -> str | None:
    if not isinstance(raw, str):
        return None
    if re.fullmatch(r"TA\d{4}", raw, re.IGNORECASE):
        return raw.upper()
    return attack.tactic_identifier(raw)


def export_attackflow(ir: dict[str, Any], original_bundle: dict[str, Any] | None = None) -> dict[str, Any]:
    """Export Scenario IR as Attack Flow STIX, preserving imported bundles verbatim."""
    errors = iter_errors("scenario-ir", ir)
    if errors:
        raise ValueError("Scenario IR failed validation: " + "; ".join(errors))
    original = original_bundle or ir.get("_attackflow_original_bundle")
    if original:
        copied = copy.deepcopy(original)
        warnings = _validate_bundle(copied)
        ids = {o["id"] for o in copied["objects"]}
        # Repair dangling asset object_refs, while retaining the source IDs and other object bytes.
        for obj in copied["objects"]:
            if obj.get("type") == "attack-asset":
                ref = _get(obj, "object_ref")
                if ref and ref not in ids:
                    obj.pop("object_ref", None)
                    ext = obj.get("extensions", {}).get(_EXT_ID)
                    if isinstance(ext, dict):
                        ext.pop("object_ref", None)
        _validate_bundle(copied)
        return copied

    objects: list[dict[str, Any]] = [_official_extension_definition()]
    # Supply the identity referenced by the canonical extension definition.
    objects.append({"type": "identity", "spec_version": "2.1", "id": "identity--d673f8cb-c168-42da-8ed4-0cb26725f86c",
                    "created_by_ref": "identity--d673f8cb-c168-42da-8ed4-0cb26725f86c",
                    "created": "2022-08-02T19:34:35.143Z", "modified": "2022-08-02T19:34:35.143Z",
                    "name": "MITRE Center for Threat-Informed Defense", "identity_class": "organization"})
    node_kind: dict[str, str] = {}
    for kind, key in (("attack-action", "actions"), ("attack-condition", "conditions"), ("attack-operator", "operators"), ("attack-asset", "assets")):
        for item in ir.get(key, []):
            node_kind[item["id"]] = kind
    ref_map = {ident: _sid(kind, ident) for ident, kind in node_kind.items()}
    edge_kinds: dict[tuple[str, str], str] = {}
    outgoing: dict[str, list[str]] = {ident: [] for ident in node_kind}
    incoming: set[str] = set()
    def add_edge(src: str, dst: str, kind: str = "dependency") -> None:
        if src not in node_kind or dst not in node_kind:
            raise ValueError(f"Cannot export dangling Attack Flow edge {src!r} -> {dst!r}.")
        if dst not in outgoing[src]:
            outgoing[src].append(dst)
        incoming.add(dst)
        edge_kinds[(src, dst)] = kind

    for item in ir.get("actions", []):
        for dst in item.get("effect_refs", []):
            add_edge(item["id"], dst)
    for item in ir.get("conditions", []):
        for key in ("on_true_refs", "on_false_refs"):
            for dst in item.get(key, []):
                add_edge(item["id"], dst)
    for item in ir.get("operators", []):
        for dst in item.get("effect_refs", []):
            add_edge(item["id"], dst)
    for rel in ir.get("relations", []):
        add_edge(rel["from_action"], rel["to_action"], rel.get("kind", "dependency"))

    def refs(item: dict[str, Any], field: str) -> list[str]:
        return [ref_map.get(r, r) for r in item.get(field, [])]
    def extension(item: dict[str, Any], edge_src: str | None = None) -> dict[str, Any]:
        metadata = {k: item[k] for k in ("epistemic_status", "source", "evidence_refs") if item.get(k) is not None}
        edge_meta = {ref_map[dst]: kind for (src, dst), kind in edge_kinds.items() if src == edge_src}
        fields: dict[str, Any] = {"extension_type": "new-sdo"}
        if metadata:
            fields["scenario_ir_metadata"] = metadata
        if edge_meta:
            fields["edge_kinds"] = edge_meta
            fields["edge_refs"] = [{"target_ref": target, "kind": kind} for target, kind in edge_meta.items()]
        return {"extensions": {_EXT_ID: fields}}

    added_techniques: set[str] = set()
    for action in ir.get("actions", []):
        tid, info = _valid_technique(action)
        obj: dict[str, Any] = {"type": "attack-action", "spec_version": "2.1", "id": ref_map[action["id"]],
                               "created": action.get("created", ir.get("created_at", "2022-08-02T19:34:35.143Z")),
                               "modified": action.get("modified", ir.get("updated_at", "2022-08-02T19:34:35.143Z")),
                               "name": action["name"], "effect_refs": [ref_map[r] for r in outgoing[action["id"]]],
                               **extension(action, action["id"])}
        if action.get("description"):
            obj["description"] = action["description"]
        if tid and info:
            obj["technique_id"] = tid
            obj["technique_ref"] = _sid("attack-pattern", tid)
            # The official ATT&CK name must not be replaced by the scenario step label.
            if tid not in added_techniques:
                objects.append({"type": "attack-pattern", "spec_version": "2.1", "id": obj["technique_ref"],
                                "created": "2022-08-02T19:34:35.143Z", "modified": "2022-08-02T19:34:35.143Z",
                                "name": info["name"], "external_references": [{"source_name": "mitre-attack", "external_id": tid, "url": info.get("url")}]})
                added_techniques.add(tid)
        tactic_id = _encode_tactic(action.get("tactic_id", action.get("attack_tactic")))
        if tactic_id:
            obj["tactic_id"] = tactic_id
        for key in ("execution_start", "execution_end", "command_ref"):
            if action.get(key) is not None:
                obj[key] = action[key]
        asset_refs = [ref_map[r] for r in action.get("asset_refs", []) if r in ref_map]
        if asset_refs:
            obj["asset_refs"] = asset_refs
        objects.append(obj)

    for condition in ir.get("conditions", []):
        obj = {"type": "attack-condition", "spec_version": "2.1", "id": ref_map[condition["id"]],
               "created": condition.get("created", ir.get("created_at", "2022-08-02T19:34:35.143Z")),
               "modified": condition.get("modified", ir.get("updated_at", "2022-08-02T19:34:35.143Z")),
               **extension(condition, condition["id"])}
        for key in ("description", "pattern", "pattern_type"):
            if condition.get(key) is not None:
                obj[key] = condition[key]
        for key in ("on_true_refs", "on_false_refs"):
            if condition.get(key):
                obj[key] = refs(condition, key)
        objects.append(obj)
    for operator in ir.get("operators", []):
        objects.append({"type": "attack-operator", "spec_version": "2.1", "id": ref_map[operator["id"]],
                        "created": operator.get("created", ir.get("created_at", "2022-08-02T19:34:35.143Z")),
                        "modified": operator.get("modified", ir.get("updated_at", "2022-08-02T19:34:35.143Z")),
                        "operator": operator["operator"], "effect_refs": [ref_map[r] for r in outgoing[operator["id"]]],
                        **extension(operator, operator["id"])})
    for asset in ir.get("assets", []):
        obj = {"type": "attack-asset", "spec_version": "2.1", "id": ref_map[asset["id"]],
               "created": asset.get("created", ir.get("created_at", "2022-08-02T19:34:35.143Z")),
               "modified": asset.get("modified", ir.get("updated_at", "2022-08-02T19:34:35.143Z")),
               "name": asset.get("name", "Asset"), **extension(asset)}
        if asset.get("description"):
            obj["description"] = asset["description"]
        object_ref = asset.get("object_ref")
        # Only emit references that resolve inside the outgoing STIX bundle.
        if object_ref and any(o.get("id") == object_ref for o in objects):
            obj["object_ref"] = object_ref
        objects.append(obj)

    flow = ir.get("flow", {})
    action_ids = {a["id"] for a in ir.get("actions", [])}
    roots = [ref_map[a] for a in action_ids if a not in incoming]
    flow_obj = {"type": "attack-flow", "spec_version": "2.1", "id": _sid("attack-flow", ir["id"]),
                "created": ir.get("created_at", "2022-08-02T19:34:35.143Z"),
                "modified": ir.get("updated_at", "2022-08-02T19:34:35.143Z"),
                "name": flow.get("name", ir["name"]), "scope": flow.get("scope", "other"),
                "start_refs": roots, **extension({})}
    if flow.get("description"):
        flow_obj["description"] = flow["description"]
    objects.append(flow_obj)

    # Evidence quotes and their source locators are delivered in readable STIX notes.
    evidence = {e["id"]: e for e in ir.get("evidence", []) if e.get("id")}
    evidence_to_actions: dict[str, list[str]] = {}
    for action in ir.get("actions", []):
        for eid in action.get("evidence_refs", []):
            if eid in evidence:
                evidence_to_actions.setdefault(eid, []).append(ref_map[action["id"]])
    for relation in ir.get("relations", []):
        targets = [ref_map[r] for r in (relation.get("from_action"), relation.get("to_action")) if r in ref_map]
        for eid in relation.get("evidence_refs", []):
            if eid in evidence:
                evidence_to_actions.setdefault(eid, []).extend(targets)
    if evidence:
        author_id = "identity--" + _uuid("evidence-author", ir["id"])
        objects.append({"type": "identity", "spec_version": "2.1", "id": author_id, "created": "2022-08-02T19:34:35.143Z",
                        "modified": "2022-08-02T19:34:35.143Z", "name": "CyberRange evidence export", "identity_class": "organization"})
        for eid, item in evidence.items():
            locator = item.get("locator", {})
            note_id = "note--" + _uuid("evidence-note", eid)
            abstract = f"Evidence {eid}" + (f" ({locator.get('kind')}: {locator.get('ref')})" if locator else "")
            objects.append({"type": "note", "spec_version": "2.1", "id": note_id, "created": "2022-08-02T19:34:35.143Z",
                            "modified": "2022-08-02T19:34:35.143Z", "created_by_ref": author_id, "abstract": abstract,
                            "content": item.get("quote", ""), "object_refs": evidence_to_actions.get(eid) or [_sid("attack-flow", ir["id"])]})
    result = {"type": "bundle", "id": "bundle--" + _uuid("bundle", ir["id"]), "objects": objects}
    _validate_bundle(result)
    return result
