"""A user's answer to a missing item must reach the IR fields the planning modules read."""
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api"))

from app import store  # noqa: E402
from app.cti.missing import calculate_missing_items, refresh_missing_items  # noqa: E402
from app.main import app  # noqa: E402
from app.planner.dependencies import plan_dependencies  # noqa: E402
from app.planner.topology import build_environment_plan  # noqa: E402


def make_ir():
    ir = {
        "schema_version": "1.0", "id": "scn_t", "name": "t",
        "provenance": {"input_kind": "text", "input_sha256": "0"},
        "evidence": [],
        "actions": [{"id": "a1", "name": "Exploit the file transfer application", "target_host_ref": "h1",
                     "attack_technique": "T1190", "epistemic_status": "supported", "source": "llm", "evidence_refs": []}],
        "relations": [],
        "hosts": [{"id": "h1", "role": "file transfer server", "epistemic_status": "inferred", "source": "llm", "evidence_refs": []}],
        "services": [{"id": "s1", "name": "Progress MOVEit Transfer", "host_ref": "h1", "cve": ["CVE-2023-34362"],
                      "epistemic_status": "supported", "source": "llm", "evidence_refs": []}],
    }
    ir["missing_items"] = calculate_missing_items(ir)
    return ir


class Harness(unittest.TestCase):
    def setUp(self):
        self.state = {"scn_t": make_ir()}

        def update(scenario_id, ir, note=None, bump_version=False):
            self.state[scenario_id] = copy.deepcopy(ir)
            return ir

        patches = [patch.object(store, "get", lambda sid: copy.deepcopy(self.state.get(sid))),
                   patch.object(store, "update", update)]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.client = TestClient(app)

    def answer(self, item_id, text, status="user_supplied"):
        response = self.client.post("/api/ingest/scn_t/supplement",
                                    json={"text": text, "targets_missing_item": item_id, "status": status})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def item(self, ir, item_id):
        return next(entry for entry in ir["missing_items"] if entry["id"] == item_id)


class WriteBack(Harness):
    def test_questions_name_where_their_answer_belongs(self):
        ir = self.state["scn_t"]
        self.assertEqual(self.item(ir, "missing-hosts-h1-os")["target"], {"collection": "hosts", "id": "h1", "field": "os"})
        self.assertEqual(self.item(ir, "missing-service-s1-version")["target"],
                         {"collection": "services", "id": "s1", "field": "version"})

    def test_answer_sent_the_way_the_ui_sends_it_reaches_the_host_record(self):
        ir = self.answer("missing-hosts-h1-os", "Windows Server 2019")
        host = ir["hosts"][0]
        self.assertEqual(host["os"], "Windows Server 2019")
        self.assertEqual(host["field_sources"], {"os": "user"})
        # Only the supplied field is the user's; what the report supported is unchanged.
        self.assertEqual((host["source"], host["epistemic_status"]), ("llm", "inferred"))
        resolved = self.item(ir, "missing-hosts-h1-os")
        self.assertEqual((resolved["status"], resolved["resolution"], resolved["resolution_source"]),
                         ("user_supplied", "Windows Server 2019", "user"))
        self.assertEqual(resolved["applied_to"], {"collection": "hosts", "id": "h1", "field": "os"})
        # Still-open questions about the same host remain open.
        self.assertEqual(self.item(ir, "missing-hosts-h1-os-version")["status"], "open")
        self.assertEqual(len([e for e in ir["missing_items"] if e["id"] == "missing-hosts-h1-os"]), 1)

    def test_supplied_version_and_placement_reach_dependencies_and_topology(self):
        self.answer("missing-service-s1-version", "2023.0.1")
        ir = self.answer("missing-hosts-h1-network", "internal management segment")
        self.assertEqual(ir["services"][0]["version"], "2023.0.1")
        planned = plan_dependencies(ir)
        self.assertEqual(next(s for s in planned["services"] if s["id"] == "s1")["version"], "2023.0.1")
        self.assertFalse(any(e["status"] == "open" and "version" in e["id"] and "s1" in e["id"] for e in planned["missing_items"]))
        plan = build_environment_plan(planned)
        self.assertNotIn("external", next(h for h in plan["hosts"] if h["id"] == "h1")["networks"])

    def test_accepting_unknown_writes_nothing(self):
        ir = self.answer("missing-hosts-h1-os", "The report does not say.", status="accepted_unknown")
        self.assertNotIn("os", ir["hosts"][0])
        self.assertEqual(self.item(ir, "missing-hosts-h1-os")["status"], "accepted_unknown")

    def test_an_explanation_is_kept_as_text_and_not_forced_into_a_field(self):
        text = "We are not sure. " * 12
        ir = self.answer("missing-hosts-h1-os", text)
        self.assertNotIn("os", ir["hosts"][0])
        entry = self.item(ir, "missing-hosts-h1-os")
        self.assertEqual(entry["status"], "user_supplied")
        self.assertIn("write_back", entry)
        self.assertNotIn("applied_to", entry)

    def test_inconsistent_answer_is_reported_not_written(self):
        self.answer("missing-hosts-h1-os", "Windows Server 2019")
        ir = self.answer("missing-hosts-h1-os-version", "Ubuntu 22.04")
        self.assertNotIn("os_version", ir["hosts"][0])
        self.assertIn("inconsistent", self.item(ir, "missing-hosts-h1-os-version")["write_back"])


class RefreshOnEdit(Harness):
    def test_deleting_an_action_drops_its_open_questions_but_keeps_answers(self):
        self.answer("missing-hosts-h1-os", "Windows Server 2019")
        with patch("app.routers.scenario.validate_ir", lambda ir: []):
            response = self.client.delete("/api/scenario/scn_t/actions/a1")
        self.assertEqual(response.status_code, 200, response.text)
        ir = response.json()
        ids = {entry["id"]: entry["status"] for entry in ir["missing_items"]}
        self.assertEqual(ids["missing-hosts-h1-os"], "user_supplied")
        for entry in ir["missing_items"]:
            self.assertFalse(any(ref.startswith("action:a1 ") for ref in entry.get("affects", []))
                             and entry["status"] == "open", entry)

    def test_refresh_leaves_other_modules_items_alone(self):
        ir = make_ir()
        ir["missing_items"].append({"id": "planner_dep_x", "field": "f", "category": "software", "reason": "r", "status": "open"})
        self.assertIn("planner_dep_x", [entry["id"] for entry in refresh_missing_items(ir)])


if __name__ == "__main__":
    unittest.main()
