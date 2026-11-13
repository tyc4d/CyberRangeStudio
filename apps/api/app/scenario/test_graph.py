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
