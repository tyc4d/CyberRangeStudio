"""Round-2 QA rules: outcomes, technique placement, gap questions, switched-off services, reproducibility."""
import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api"))

from app import store  # noqa: E402
from app.cti import analysis  # noqa: E402
from app.cti.missing import calculate_missing_items  # noqa: E402
from app.cti.parser import parse_source  # noqa: E402
from app.main import app  # noqa: E402
from app.planner.dependencies import plan_dependencies  # noqa: E402
from app.planner.topology import build_environment_plan  # noqa: E402


def analyse(source, model):
    units, parsed = parse_source("text", source)
    with patch.object(analysis, "complete", lambda *a, **k: {"text": json.dumps(model)}):
        return analysis.analyze_source(input_kind="text", content=source, source_name="t", units=units,
                                       parsed_source=parsed, method="single_pass", name="t")


def act(aid, name, quote, ref, **extra):
    return {"id": aid, "name": name, "epistemic_status": "supported", "evidence": [{"quote": quote, "source_ref": ref}], **extra}


def model(actions):
    return {"actions": actions, "relations": [], "artifacts": [], "target_context": {"hosts": [], "services": []}}


class Outcomes(unittest.TestCase):
    SOURCE = ("The actor was observed attempting to dump the LSASS process with task manager but this was stopped by "
              "additional anti-virus.\n\nThe attackers ran approximately 9,000 queries, a portion of which successfully "
              "returned data.\n\nThe actor created a scheduled task.")

    def test_blocked_and_partial_outcomes_come_from_the_source_sentence(self):
        ir = analyse(self.SOURCE, model([
            act("a1", "dump LSASS", "attempting to dump the LSASS process with task manager", "p1", outcome="succeeded"),
            act("a2", "ran queries", "The attackers ran approximately 9,000 queries", "p2"),
            act("a3", "created a scheduled task", "The actor created a scheduled task.", "p3", outcome="succeeded"),
            act("a4", "created a scheduled task again", "The actor created a scheduled task.", "p3", outcome="bogus")]))
        self.assertEqual([a.get("outcome") for a in ir["actions"]], ["failed", "partial", "succeeded", None])


class TechniquePlacement(unittest.TestCase):
    SOURCE = ("The payload installed XMRig mining software.\n\n"
              "RuntimeBroker.exe can create a local user account [T1136.001].\n\n"
              "The actors exploited Log4Shell [T1190] for initial access.\n\n"
              "Scheduled Task (T1053.005): The exploit payload created a Scheduled Task that ran daily as SYSTEM.")

    def test_id_listed_for_another_behaviour_is_removed_and_stated_ones_stay(self):
        ir = analyse(self.SOURCE, model([
            act("a1", "installed XMRig mining software", "The payload installed XMRig mining software.", "p1",
                attack_technique="T1136.001", attack_tactic="persistence"),
            act("a2", "exploited Log4Shell", "The actors exploited Log4Shell for initial access.", "p3", attack_technique="T1190"),
            act("a3", "created a Scheduled Task that ran daily as SYSTEM", "The exploit payload created a Scheduled Task", "p4",
                attack_technique="T1053.005"),
            act("a4", "installed XMRig", "The payload installed XMRig mining software.", "p1", attack_technique="T1496")]))
        self.assertEqual([a.get("attack_technique") for a in ir["actions"]], [None, "T1190", "T1053.005", None])
        self.assertNotIn("attack_tactic", ir["actions"][0])
        self.assertEqual(ir["quality"]["dropped_misplaced_techniques"],
                         [{"action": "a1", "technique": "T1136.001"}, {"action": "a4", "technique": "T1496"}])


def ir_with(actions, services=(), artifacts=(), hosts=None):
    return {"schema_version": "1.0", "id": "scn_t", "name": "t", "provenance": {"input_kind": "text", "input_sha256": "0"},
            "relations": [], "evidence": [], "missing_items": [], "actions": list(actions), "services": list(services),
            "artifacts": list(artifacts),
            "hosts": hosts if hosts is not None else [{"id": "h1", "role": "portal server", "epistemic_status": "supported", "source": "llm"}]}


def step(aid, name, host="h1", **extra):
    return {"id": aid, "name": name, "target_host_ref": host, "epistemic_status": "supported", "source": "llm",
            "evidence_refs": [], **extra}


class GapQuestions(unittest.TestCase):
    def ids(self, ir):
        return {item["id"]: item for item in calculate_missing_items(ir)}

    def test_thin_report_is_asked_for_the_weakness_and_the_tools(self):
        items = self.ids(ir_with(
            [step("a1", "may have taken advantage of a weakness in an internet-facing system"),
             step("a2", "used legitimate administrative tools")],
            artifacts=[{"id": "art1", "name": "legitimate administrative tools", "type": "tool"}]))
        self.assertEqual(items["missing-gap-exploited-weakness"]["severity"], "blocker")
        self.assertIn("missing-gap-unnamed-tools", items)
        self.assertNotIn("missing-gap-database-product", items)

    def test_credentials_database_and_exfiltration_are_asked_when_the_ir_lacks_them(self):
        items = self.ids(ir_with(
            [step("a1", "exploited a vulnerability in Apache Struts", attack_technique="T1190"),
             step("a2", "issued queries to other databases and found unencrypted usernames and passwords"),
             step("a3", "removed the data in small increments")],
            services=[{"id": "s1", "name": "Apache Struts", "host_ref": "h1", "epistemic_status": "supported", "source": "llm"}]))
        for code in ("exploited-weakness", "credential-material", "database-product", "exfiltration-path"):
            self.assertIn(f"missing-gap-{code}", items, code)
        self.assertEqual(items["missing-gap-exploited-weakness"]["severity"], "major")
        self.assertTrue(any(ref.startswith("action:a2 ") for ref in items["missing-gap-database-product"]["affects"]))

    def test_nothing_is_asked_when_the_ir_already_answers_it(self):
        items = self.ids(ir_with(
            [step("a1", "exploited CVE-2023-34362 in MOVEit Transfer", attack_technique="T1190"),
             step("a2", "queried the MySQL database with the service account"),
             step("a3", "named tool Mimikatz was run")],
            services=[{"id": "s1", "name": "MOVEit Transfer", "host_ref": "h1", "cve": ["CVE-2023-34362"],
                       "epistemic_status": "supported", "source": "llm"},
                      {"id": "s2", "name": "MySQL database", "host_ref": "h1", "epistemic_status": "supported", "source": "llm"}],
            artifacts=[{"id": "art1", "name": "Mimikatz", "type": "tool"}, {"id": "art2", "name": "service account", "type": "account"}]))
        self.assertFalse([key for key in items if key.startswith("missing-gap-")], list(items))


class SwitchedOffService(unittest.TestCase):
    """QA-I-R2-05: answering 'do not enable RDP' must change the plan, not only be recorded."""

    def setUp(self):
        ir = ir_with(
            [step("a1", "exploited the nginx web server", "h1", attack_technique="T1190"),
             step("a7", "used RDP to move laterally to the KMS host", "h2", source_host_ref="h1")],
            services=[{"id": "s1", "name": "nginx", "host_ref": "h1", "epistemic_status": "supported", "source": "llm"},
                      {"id": "s2", "name": "RDP", "host_ref": "h2", "epistemic_status": "supported", "source": "llm"}],
            hosts=[{"id": "h1", "role": "web server", "epistemic_status": "supported", "source": "llm"},
                   {"id": "h2", "role": "KMS host", "epistemic_status": "supported", "source": "llm"}])
        ir["missing_items"] = calculate_missing_items(ir)
        self.state = {"scn_t": ir}

        def update(sid, new, note=None, bump_version=False):
            self.state[sid] = copy.deepcopy(new)
            return new

        for item in (patch.object(store, "get", lambda sid: copy.deepcopy(self.state.get(sid))), patch.object(store, "update", update)):
            item.start()
            self.addCleanup(item.stop)

    def paths(self, ir):
        return {(c["from_host"], c["to_host"], c["port"]) for c in build_environment_plan(plan_dependencies(ir))["connections"]}

    def test_default_plan_opens_the_stated_rdp_path(self):
        self.assertIn(("h1", "h2", 3389), self.paths(self.state["scn_t"]))

    def test_not_enabling_the_service_removes_its_port_path_and_reproducibility(self):
        question = next(i for i in self.state["scn_t"]["missing_items"] if i["id"] == "missing-service-s2-configuration")
        self.assertEqual(question["target"], {"collection": "services", "id": "s2", "field": "configuration"})
        response = TestClient(app).post("/api/ingest/scn_t/supplement", json={
            "text": "不啟用 RDP，將此步驟標記未重現", "targets_missing_item": question["id"], "status": "substitute_chosen"})
        self.assertEqual(response.status_code, 200, response.text)
        ir = response.json()
        rdp = next(s for s in ir["services"] if s["id"] == "s2")
        self.assertIs(rdp["lab_enabled"], False)
        self.assertEqual(rdp["field_sources"]["lab_enabled"], "user")
        planned = plan_dependencies(ir)
        plan = build_environment_plan(planned)
        self.assertNotIn(("h1", "h2", 3389), {(c["from_host"], c["to_host"], c["port"]) for c in plan["connections"]})
        self.assertEqual(next(h for h in plan["hosts"] if h["id"] == "h2")["services"], [])
        self.assertTrue(any("not enabled in the lab" in note for note in plan["notes"]))
        a7 = next(a for a in planned["actions"] if a["id"] == "a7")
        self.assertEqual(a7["reproducibility"], "not_reproducible")
        self.assertIn("not enabled in the lab", a7["reproducibility_reason"])

    def test_an_enabling_answer_keeps_the_service(self):
        response = TestClient(app).post("/api/ingest/scn_t/supplement", json={
            "text": "TCP 3389，只允許 h1 連入", "targets_missing_item": "missing-service-s2-configuration"})
        rdp = next(s for s in response.json()["services"] if s["id"] == "s2")
        self.assertNotIn("lab_enabled", rdp)
        self.assertEqual(rdp["configuration"], "TCP 3389，只允許 h1 連入")
        self.assertIn(("h1", "h2", 3389), self.paths(response.json()))


class ReproducibilityIsAboutTheBehaviour(unittest.TestCase):
    """QA-I-R2-04: an available image does not make every step on that host reproducible."""

    def test_only_the_step_acting_on_the_deployed_software_is_reproducible(self):
        planned = plan_dependencies(ir_with(
            [step("a1", "exploited a vulnerability in Apache Struts to run commands", attack_technique="T1190"),
             step("a2", "leveraged existing encrypted communication channels to send queries and retrieve PII"),
             step("a3", "removed the data in small increments")],
            services=[{"id": "s1", "name": "Apache Struts", "host_ref": "h1", "epistemic_status": "supported", "source": "llm"}]))
        by_id = {a["id"]: a for a in planned["actions"]}
        self.assertEqual(by_id["a1"]["reproducibility"], "reproducible")
        self.assertIn("assumed", by_id["a1"]["reproducibility_reason"])
        for aid in ("a2", "a3"):
            self.assertEqual(by_id[aid]["reproducibility"], "not_reproducible", aid)
            self.assertIn("remains untested", by_id[aid]["reproducibility_reason"])
        self.assertEqual(planned["fidelity"], "not_reproducible")


class AttackerRole(unittest.TestCase):
    def test_only_a_role_that_is_the_attackers_machine_counts(self):
        from app.cti.missing import is_attacker_role
        for role in ("attacker", "Attacker host", "local attacker host", "red-team operator workstation",
                     "attacker-controlled C2 server", "threat actor infrastructure", "operator"):
            self.assertTrue(is_attacker_role(role), role)
        for role in ("additional databases queried by the attackers", "server the attacker exploited",
                     "operator console of the SCADA system", "web server", ""):
            self.assertFalse(is_attacker_role(role), role)

    def test_victim_host_that_mentions_attackers_is_planned_as_a_target(self):
        planned = plan_dependencies(ir_with(
            [step("a1", "exploited a vulnerability in Apache Struts", "h1", attack_technique="T1190"),
             step("a2", "queried the additional databases", "h3", source_host_ref="h1")],
            services=[{"id": "s1", "name": "Apache Struts", "host_ref": "h1", "epistemic_status": "supported", "source": "llm"}],
            hosts=[{"id": "h1", "role": "portal server", "epistemic_status": "supported", "source": "llm"},
                   {"id": "h3", "role": "additional databases accessed by the attackers", "epistemic_status": "supported", "source": "llm"}]))
        plan = build_environment_plan(planned)
        hosts = {h["id"]: h for h in plan["hosts"]}
        self.assertEqual(hosts["h3"]["networks"], ["scenario-internal"])
        self.assertNotEqual(hosts["h3"].get("image_hint"), "oss-attacker")
        self.assertIn("attacker", hosts)


class UnsupportedSoftwareQuestion(unittest.TestCase):
    def test_question_is_in_plain_language_and_suggests_fitting_substitutes(self):
        planned = plan_dependencies(ir_with(
            [step("a1", "queried the databases associated with the portal", "h2")],
            services=[{"id": "s2", "name": "databases associated with the online dispute portal", "host_ref": "h2",
                       "epistemic_status": "supported", "source": "llm"}],
            hosts=[{"id": "h2", "role": "database servers", "epistemic_status": "supported", "source": "llm"}]))
        question = next(i for i in planned["missing_items"] if i["id"].startswith("planner_dep_software"))
        self.assertEqual(question["service_ref"], "s2")
        self.assertIn("教學替代", question["question"])
        self.assertTrue(any("PostgreSQL" in s for s in question["suggestions"]), question["suggestions"])
        self.assertFalse(any("NGINX" in s for s in question["suggestions"]))


if __name__ == "__main__":
    unittest.main()
