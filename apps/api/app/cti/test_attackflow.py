import json
from pathlib import Path

from cr_contracts import iter_errors

from app.cti.attackflow import export_attackflow, import_attackflow


FIXTURE = Path(__file__).resolve().parents[4] / "fixtures/sample-scenarios/attackflow/official-attack-flow-example.json"


def test_official_attackflow_fixture_round_trip():
    bundle = json.loads(FIXTURE.read_text(encoding="utf-8"))
    ir = import_attackflow(bundle)
    assert iter_errors("scenario-ir", ir) == []
    assert ir["flow"]["name"] == "Example Flow"
    assert len(ir["actions"]) == 5
    assert ir["conditions"] and ir["operators"] and ir["assets"]
    assert any(a.get("attack_technique") == "T1190" for a in ir["actions"])

    exported = export_attackflow(ir)
    assert exported["type"] == "bundle"
    assert any(o.get("type") == "extension-definition" for o in exported["objects"])
    assert len([o for o in exported["objects"] if o.get("type") == "attack-action"]) == 5
    round_tripped = import_attackflow(exported)
    assert iter_errors("scenario-ir", round_tripped) == []
    assert {a.get("attack_technique") for a in round_tripped["actions"]} == {
        a.get("attack_technique") for a in ir["actions"]
    }


def test_effect_refs_create_dependency_relation():
    bundle = json.loads(FIXTURE.read_text(encoding="utf-8"))
    actions = [o for o in bundle["objects"] if o.get("type") == "attack-action"]
    actions[0]["effect_refs"] = [actions[1]["id"]]
    ir = import_attackflow(bundle)
    assert any(
        r["kind"] == "dependency"
        and r["from_action"] == actions[0]["id"]
        and r["to_action"] == actions[1]["id"]
        for r in ir["relations"]
    )


def test_technique_ref_resolves_mitre_external_id():
    bundle = json.loads(FIXTURE.read_text(encoding="utf-8"))
    action = next(o for o in bundle["objects"] if o.get("type") == "attack-action")
    action.pop("technique_id", None)
    action["technique_ref"] = "attack-pattern--00000000-0000-4000-8000-000000000099"
    bundle["objects"].append({
        "type": "attack-pattern", "spec_version": "2.1",
        "id": action["technique_ref"], "created": "2024-01-01T00:00:00Z",
        "modified": "2024-01-01T00:00:00Z", "name": "Exploit Public-Facing Application",
        "external_references": [{"source_name": "mitre-attack", "external_id": "T1190",
                                 "url": "https://attack.mitre.org/techniques/T1190/"}],
    })
    ir = import_attackflow(bundle)
    assert ir["actions"][0]["attack_technique"] == "T1190"


def test_conditions_operators_and_assets_round_trip():
    bundle = json.loads(FIXTURE.read_text(encoding="utf-8"))
    actions = [o for o in bundle["objects"] if o.get("type") == "attack-action"]
    condition_id = "attack-condition--00000000-0000-4000-8000-000000000001"
    operator_id = "attack-operator--00000000-0000-4000-8000-000000000002"
    asset_id = "attack-asset--00000000-0000-4000-8000-000000000003"
    actions[0]["effect_refs"] = [condition_id]
    bundle["objects"].extend([
        {"type": "attack-condition", "spec_version": "2.1", "id": condition_id,
         "created": "2024-01-01T00:00:00Z", "modified": "2024-01-01T00:00:00Z",
         "description": "Branch on whether access is available.", "on_true_refs": [actions[1]["id"]],
         "on_false_refs": [operator_id], "pattern": "[network-traffic:dst_port = 443]", "pattern_type": "stix"},
        {"type": "attack-operator", "spec_version": "2.1", "id": operator_id,
         "created": "2024-01-01T00:00:00Z", "modified": "2024-01-01T00:00:00Z",
         "operator": "OR", "effect_refs": [actions[2]["id"], actions[3]["id"]]},
        {"type": "attack-asset", "spec_version": "2.1", "id": asset_id,
         "created": "2024-01-01T00:00:00Z", "modified": "2024-01-01T00:00:00Z",
         "name": "Victim server", "object_ref": "identity--00000000-0000-4000-8000-000000000004"},
    ])
    actions[0]["asset_refs"] = [asset_id]
    ir = import_attackflow(bundle)
    assert iter_errors("scenario-ir", ir) == []
    branch_condition = next(c for c in ir["conditions"] if c["id"] == condition_id)
    branch_operator = next(o for o in ir["operators"] if o["id"] == operator_id)
    branch_asset = next(a for a in ir["assets"] if a["id"] == asset_id)
    assert branch_condition["on_false_refs"] == [operator_id]
    assert branch_operator["operator"] == "OR"
    assert branch_asset["object_ref"] == "identity--00000000-0000-4000-8000-000000000004"
    exported = export_attackflow(ir)
    round_tripped = import_attackflow(exported)
    assert iter_errors("scenario-ir", round_tripped) == []
    assert next(c for c in round_tripped["conditions"] if c.get("description") == "Branch on whether access is available.")["pattern_type"] == "stix"
    assert next(o for o in round_tripped["operators"] if o["operator"] == "OR")["operator"] == "OR"
    assert next(a for a in round_tripped["assets"] if a.get("name") == "Victim server")["name"] == "Victim server"
