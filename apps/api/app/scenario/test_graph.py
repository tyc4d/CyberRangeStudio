"""Offline tests for user edits to Scenario action graphs."""
import copy
import json
from pathlib import Path

from app.scenario.graph import reconcile_graph_sources, validate_ir

FIXTURE = Path(__file__).parents[1] / "planner" / "fixtures" / "offline_scenario.json"


def test_unchanged_llm_items_keep_source_during_full_ir_put():
    current = json.loads(FIXTURE.read_text(encoding="utf-8"))
    edited = copy.deepcopy(current)
    for relation in edited["relations"]:
        relation.setdefault("confirmed", False)

    reconcile_graph_sources(edited, current)

    assert edited["actions"][0]["source"] == "llm"
    assert edited["relations"][0]["source"] == "llm"
    assert edited["relations"][0]["confirmed"] is False
    assert validate_ir(edited) == []


def test_editing_an_llm_relation_changes_its_source_to_user():
    current = json.loads(FIXTURE.read_text(encoding="utf-8"))
    edited = copy.deepcopy(current)
    edited["relations"][0]["confirmed"] = True

    reconcile_graph_sources(edited, current)

    assert edited["relations"][0]["source"] == "user"
    assert edited["relations"][0]["confirmed"] is True


def test_unedited_items_keep_provenance_when_client_omits_defaults():
    """A payload built from a response without the `confirmed` default must not look edited."""
    current = {
        "actions": [{"id": "a1", "name": "A", "source": "llm", "epistemic_status": "supported", "evidence_refs": ["e1"]},
                    {"id": "a2", "name": "B", "source": "llm", "epistemic_status": "supported", "evidence_refs": []}],
        "relations": [{"id": "r1", "from_action": "a1", "to_action": "a2", "kind": "temporal", "source": "llm",
                       "epistemic_status": "inferred", "evidence_refs": []},
                      {"id": "r2", "from_action": "a1", "to_action": "a2", "kind": "dependency", "source": "llm",
                       "epistemic_status": "inferred", "evidence_refs": [], "confirmed": False}],
    }
    edited = {
        "actions": [{**current["actions"][0]}, {**current["actions"][1], "name": "B edited", "source": "user"}],
        # r1 echoed without `confirmed`; r2 echoed with the key dropped and an empty rationale added.
        "relations": [{**current["relations"][0]},
                      {k: v for k, v in current["relations"][1].items() if k != "confirmed"} | {"rationale": ""}],
    }
    from app.scenario.graph import reconcile_graph_sources
    reconcile_graph_sources(edited, current)
    assert [a["source"] for a in edited["actions"]] == ["llm", "user"]
    assert [r["source"] for r in edited["relations"]] == ["llm", "llm"]
    assert all(r["confirmed"] is False for r in edited["relations"])


def test_confirming_a_relation_is_a_user_change():
    from app.scenario.graph import reconcile_graph_sources
    current = {"actions": [], "relations": [{"id": "r1", "from_action": "a1", "to_action": "a2", "kind": "dependency",
                                              "source": "llm", "epistemic_status": "inferred", "evidence_refs": []}]}
    edited = {"actions": [], "relations": [{**current["relations"][0], "confirmed": True}]}
    reconcile_graph_sources(edited, current)
    assert edited["relations"][0]["source"] == "user"
