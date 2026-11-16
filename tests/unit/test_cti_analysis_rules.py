"""Program-side rules applied to model output (replayed from recorded real responses)."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.cti import analysis  # noqa: E402
from app.cti.parser import parse_source  # noqa: E402
from app.planner.dependencies import plan_dependencies  # noqa: E402
from app.planner.topology import build_environment_plan  # noqa: E402
from cr_contracts import iter_errors  # noqa: E402

RECORDED = ROOT / "tests" / "fixtures" / "recorded"
SAMPLES = ROOT / "fixtures" / "sample-scenarios"


def run(content: str, model_result: dict, kind: str = "markdown") -> dict:
    units, parsed = parse_source(kind, content)
    with patch.object(analysis, "complete", lambda *a, **k: {"text": json.dumps(model_result)}):
        ir = analysis.analyze_source(input_kind=kind, content=content, source_name="t", units=units,
                                     parsed_source=parsed, method="single_pass", name="t")
    ir["id"] = "scn_test"
    assert iter_errors("scenario-ir", ir) == []
    return ir


def replay(sample: str, recorded: str, kind: str = "markdown") -> dict:
    return run((SAMPLES / sample).read_text(encoding="utf-8"),
               json.loads((RECORDED / recorded).read_text(encoding="utf-8")), kind)


class RecordedCisaRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ir = replay("cisa-aa22-320a.md", "cisa-aa22-320a.single_pass.llm.json")

    def test_catch_all_unknown_host_is_not_a_host(self):
        host_ids = {host["id"] for host in self.ir["hosts"]}
        self.assertNotIn("unknown", host_ids)
        self.assertEqual(self.ir["quality"]["dropped_placeholder_hosts"], 1)
        for action in self.ir["actions"]:
            self.assertTrue(action["target_host_ref"] == "unknown" or action["target_host_ref"] in host_ids)

    def test_relation_is_supported_only_when_its_quote_states_the_relation(self):
        evidence = {item["id"]: item["quote"] for item in self.ir["evidence"]}
        by_id = {relation["id"]: relation for relation in self.ir["relations"]}
        # "Specifically, CISA observed HTTPS activity ..." describes a4 only; it states no order.
        self.assertEqual(by_id["r3"]["epistemic_status"], "inferred")
        self.assertIn("epistemic_reason", by_id["r3"])
        # "Following HTTPS activity, ..." and "Using the newly created account, ..." do state it.
        self.assertEqual(by_id["r4"]["epistemic_status"], "supported")
        self.assertEqual(by_id["r18"]["epistemic_status"], "supported")
        for relation in self.ir["relations"]:
            if relation["epistemic_status"] == "supported":
                quotes = [evidence[ref] for ref in relation["evidence_refs"]]
                self.assertIsNotNone(analysis._relation_cue(relation["kind"], quotes), relation)

    def test_tactic_returned_as_list_is_kept(self):
        a1 = next(action for action in self.ir["actions"] if action["id"] == "a1")
        self.assertEqual(a1.get("attack_tactic"), "TA0001")

    def test_document_provenance_is_not_an_indicator(self):
        values = {item["value"] for item in self.ir["indicators"]}
        self.assertNotIn("www.cisa.gov", values)
        self.assertFalse(any(item["type"] == "hash" for item in self.ir["indicators"]))
        self.assertIn("182.54.217[.]2", values)
        self.assertIn("transfer[.]sh", values)


class RelationAndHostRules(unittest.TestCase):
    SOURCE = ("The actor phished a user on WS-01.\n\nThe actor dumped credentials on WS-01.\n\n"
              "Using the stolen credentials, the actor logged in to the file server FS-02 over SMB port 445.")

    def model(self, relations, hosts=None, services=None, action_hosts=("h1", "h1", "h2")):
        return {
            "actions": [
                {"id": "a1", "name": "Phish user", "target_host_ref": action_hosts[0], "epistemic_status": "supported",
                 "evidence": [{"quote": "The actor phished a user on WS-01.", "source_ref": "p1"}]},
                {"id": "a2", "name": "Dump credentials", "target_host_ref": action_hosts[1], "epistemic_status": "supported",
                 "evidence": [{"quote": "The actor dumped credentials on WS-01.", "source_ref": "p2"}]},
                {"id": "a3", "name": "Log in to file server", "target_host_ref": action_hosts[2], "epistemic_status": "supported",
                 "evidence": [{"quote": "the actor logged in to the file server FS-02", "source_ref": "p3"}]},
            ],
            "relations": relations,
            "target_context": {"hosts": hosts if hosts is not None else [
                {"id": "h1", "name": "WS-01", "role": "workstation", "epistemic_status": "supported",
                 "evidence": [{"quote": "a user on WS-01", "source_ref": "p1"}]},
                {"id": "h2", "name": "FS-02", "role": "file server", "epistemic_status": "supported",
                 "evidence": [{"quote": "the file server FS-02", "source_ref": "p3"}]},
            ], "services": services or []},
            "artifacts": [],
        }

    def test_dependency_with_enabling_words_is_supported(self):
        ir = run(self.SOURCE, self.model([{
            "id": "r1", "from_action": "a2", "to_action": "a3", "kind": "dependency", "epistemic_status": "supported",
            "evidence": [{"quote": "Using the stolen credentials, the actor logged in", "source_ref": "p3"}]}]), "text")
        self.assertEqual(ir["relations"][0]["epistemic_status"], "supported")
        self.assertNotIn("epistemic_reason", ir["relations"][0])

    def test_edge_citing_only_an_endpoint_sentence_is_inferred(self):
        ir = run(self.SOURCE, self.model([{
            "id": "r1", "from_action": "a1", "to_action": "a2", "kind": "temporal", "epistemic_status": "supported",
            "evidence": [{"quote": "The actor dumped credentials on WS-01.", "source_ref": "p2"}]}]), "text")
        self.assertEqual(ir["relations"][0]["epistemic_status"], "inferred")
        self.assertEqual(ir["quality"]["inferred_count"], 1)

    def test_dependency_backed_only_by_order_words_is_inferred(self):
        source = self.SOURCE + "\n\nThen the actor deleted logs on FS-02."
        model = self.model([{
            "id": "r1", "from_action": "a2", "to_action": "a3", "kind": "dependency", "epistemic_status": "supported",
            "evidence": [{"quote": "Then the actor deleted logs", "source_ref": "p4"}]}])
        ir = run(source, model, "text")
        self.assertEqual(ir["relations"][0]["kind"], "dependency")
        self.assertEqual(ir["relations"][0]["epistemic_status"], "inferred")

    def test_distinct_hosts_stay_distinct_and_dangling_refs_become_unknown(self):
        ir = run(self.SOURCE, self.model([], action_hosts=("h1", "h9", "h2")), "text")
        self.assertEqual([host["name"] for host in ir["hosts"]], ["WS-01", "FS-02"])
        self.assertEqual([host["epistemic_status"] for host in ir["hosts"]], ["supported", "supported"])
        # a2 names WS-01 in its own citation, so the explicit host mention resolves it.
        self.assertEqual([action["target_host_ref"] for action in ir["actions"]], ["h1", "h1", "h2"])

    def test_service_keeps_stated_host_port_and_cve_only(self):
        ir = run(self.SOURCE, self.model([], services=[{
            "id": "s1", "name": "SMB", "host_ref": "h2", "port": "445", "protocol": "TCP", "cve": ["CVE-2020-0796", "Log4Shell"],
            "epistemic_status": "supported", "evidence": [{"quote": "over SMB port 445", "source_ref": "p3"}]},
            {"id": "s2", "name": "RDP", "host_ref": "h7", "port": 99999}]), "text")
        smb, rdp = ir["services"]
        self.assertEqual((smb["host_ref"], smb["port"], smb["protocol"]), ("h2", 445, "tcp"))
        self.assertNotIn("cve", smb)  # model-only CVEs are dropped without a source relation
        self.assertNotIn("host_ref", rdp)
        self.assertNotIn("port", rdp)

    def test_labelled_ioc_hash_is_kept_but_source_checksum_is_not(self):
        source = ("- Source: Vendor report\n- URL: https://vendor.example.com/report.pdf\n"
                  "- Source SHA-256: " + "a" * 64 + "\n\n"
                  "Indicators: the dropper SHA256: " + "b" * 64 + " was downloaded from hxxp://bad[.]example/x.")
        ir = run(source, self.model([]) | {"actions": [], "target_context": {"hosts": [], "services": []}}, "text")
        values = {item["value"] for item in ir["indicators"]}
        self.assertIn("b" * 64, values)
        self.assertNotIn("a" * 64, values)
        self.assertNotIn("vendor.example.com", values)
        self.assertIn("hxxp://bad[.]example/x", values)


class HedgedSourceStatements(unittest.TestCase):
    SOURCE = ("The unauthorized party may have taken advantage of a weakness in an internet-facing system.\n\n"
              "The actor deleted the web server logs.")

    def test_hedged_sentence_is_flagged_even_when_the_quote_omits_the_hedge(self):
        ir = run(self.SOURCE, {
            "actions": [
                {"id": "a1", "name": "took advantage of a weakness", "epistemic_status": "supported",
                 "evidence": [{"quote": "taken advantage of a weakness in an internet-facing system", "source_ref": "p1"}]},
                {"id": "a2", "name": "deleted logs", "epistemic_status": "supported",
                 "evidence": [{"quote": "The actor deleted the web server logs.", "source_ref": "p2"}]},
            ], "relations": [], "target_context": {"hosts": [], "services": []}, "artifacts": []}, "text")
        a1, a2 = ir["actions"]
        self.assertEqual((a1["epistemic_status"], a1.get("source_certainty")), ("supported", "hedged"))
        self.assertIn("epistemic_reason", a1)
        self.assertNotIn("source_certainty", a2)
        self.assertEqual(ir["quality"]["hedged_action_count"], 1)


class CapabilitiesAndTrafficDescriptions(unittest.TestCase):
    SOURCE = ("The group installed a web shell on the portal server.\n\n"
              "The web shell can run commands that create a new administrator account with a randomly generated username.\n\n"
              "The attackers leveraged existing encrypted communication channels connected to the portal.")

    def test_capability_is_kept_but_never_presented_as_an_event(self):
        ir = run(self.SOURCE, {
            "actions": [
                {"id": "a1", "name": "installed a web shell", "occurrence": "performed", "epistemic_status": "supported",
                 "evidence": [{"quote": "The group installed a web shell on the portal server.", "source_ref": "p1"}]},
                {"id": "a2", "name": "create a new administrator account", "occurrence": "capability", "outcome": "succeeded",
                 "epistemic_status": "supported",
                 "evidence": [{"quote": "create a new administrator account with a randomly generated username", "source_ref": "p2"}]},
            ], "relations": [], "artifacts": [],
            "target_context": {"hosts": [], "services": [
                {"id": "s1", "name": "existing encrypted communication channels", "epistemic_status": "supported",
                 "evidence": [{"quote": "existing encrypted communication channels", "source_ref": "p3"}]}]}}, "text")
        a1, a2 = ir["actions"]
        self.assertNotIn("occurrence", a1)
        self.assertEqual((a2["occurrence"], a2["source_certainty"], a2["epistemic_status"]), ("capability", "capability", "supported"))
        self.assertIn("epistemic_reason", a2)
        self.assertNotIn("outcome", a2)
        self.assertEqual(ir["quality"]["capability_action_count"], 1)
        self.assertEqual(ir["quality"]["dropped_non_software_services"], ["existing encrypted communication channels"])
        self.assertEqual([service["id"] for service in ir["services"]], ["service-unspecified"])


class SameSentenceVerifiesTheSameEverywhere(unittest.TestCase):
    """QA round 2 (QA-I-R2-03): a relation quote without a locator must still be found in the source."""

    SOURCE = "The actor downloaded file.zip.\n\nfile.zip contained XMRig. The actor then executed the miner."

    def model(self, source_ref):
        return {"actions": [
            {"id": "a1", "name": "downloaded file.zip", "epistemic_status": "supported",
             "evidence": [{"quote": "The actor downloaded file.zip.", "source_ref": "p1"}]},
            {"id": "a2", "name": "executed the miner", "epistemic_status": "supported",
             "evidence": [{"quote": "The actor then executed the miner.", "source_ref": "p2"}]}],
            "relations": [{"id": "r1", "from_action": "a1", "to_action": "a2", "kind": "temporal", "epistemic_status": "supported",
                           "evidence": [{"quote": "The actor then executed the miner.", **source_ref}]}],
            "target_context": {"hosts": [], "services": []}, "artifacts": []}

    def test_missing_empty_or_wrong_locator_is_resolved_from_the_text(self):
        for source_ref in ({}, {"source_ref": ""}, {"source_ref": "p1"}, {"source_ref": "paragraph 9"}):
            ir = run(self.SOURCE, self.model(source_ref), "text")
            relation = ir["relations"][0]
            record = next(e for e in ir["evidence"] if e["id"] == relation["evidence_refs"][0])
            self.assertEqual((record["quote_match"], record["locator"]), ("exact", {"kind": "paragraph", "ref": "2"}), source_ref)
            self.assertEqual(relation["epistemic_status"], "supported", source_ref)
            # the action citing the same sentence shares the same evidence record
            self.assertEqual(ir["actions"][1]["evidence_refs"], relation["evidence_refs"], source_ref)

    def test_a_quote_that_is_nowhere_in_the_source_still_fails(self):
        model = self.model({})
        model["relations"][0]["evidence"][0]["quote"] = "The actor then wiped every server in the domain."
        relation = run(self.SOURCE, model, "text")["relations"][0]
        self.assertEqual(relation["epistemic_status"], "insufficient")


class CveBelongsToTheProductNamedWithIt(unittest.TestCase):
    """A CVE attaches only when the source explicitly states an affected relation."""

    def test_cve_merely_listed_in_the_same_sentence_is_not_attached(self):
        source = ("The group exploited a SQL injection vulnerability CVE-2023-34362 in MOVEit Transfer web applications.\n\n"
                  "Separately, CVE-2023-0669 affected a different product.")
        ir = run(source, {"actions": [], "relations": [], "artifacts": [], "target_context": {"hosts": [], "services": [
            {"id": "s1", "name": "MOVEit Transfer", "epistemic_status": "supported",
             "evidence": [{"quote": "MOVEit Transfer web applications", "source_ref": "p1"}]}]}}, "text")
        service = ir["services"][0]
        self.assertNotIn("cve", service)
        self.assertIn("missing-cve-cve-2023-34362-software", {item["id"] for item in ir["missing_items"]})


class ScenarioNameIsTheUsers(unittest.TestCase):
    """frontend-eng: the name given at import must survive analysis, whatever services are found."""

    def test_name_is_not_replaced_by_a_service_name(self):
        source = "The group exploited CVE-2023-34362 in MOVEit Transfer and queried databases containing PII."
        units, parsed = parse_source("text", source)
        reply = {"actions": [], "relations": [], "artifacts": [], "target_context": {"hosts": [], "services": [
            {"id": "s1", "name": "MOVEit Transfer", "epistemic_status": "supported",
             "evidence": [{"quote": "MOVEit Transfer", "source_ref": "p1"}]},
            {"id": "s2", "name": "Databases containing PII", "epistemic_status": "supported",
             "evidence": [{"quote": "databases containing PII", "source_ref": "p1"}]}]}}
        with patch.object(analysis, "complete", lambda *a, **k: {"text": json.dumps(reply)}):
            ir = analysis.analyze_source(input_kind="text", content=source, source_name="equifax-goal", units=units,
                                         parsed_source=parsed, method="single_pass", name="My Equifax scenario")
        self.assertEqual(ir["name"], "My Equifax scenario")
        self.assertEqual(ir["provenance"]["source_name"], "equifax-goal")
        self.assertEqual([service["name"] for service in ir["services"]], ["MOVEit Transfer", "Databases containing PII"])


class InlineTechniqueAndBareQuotes(unittest.TestCase):
    SOURCE = ("The group exploited the portal to install a web shell named helper.aspx [T1190].\n\n"
              "The web shell was then used to copy the customer table.")

    def analyse(self, source, actions):
        units, parsed = parse_source("text", source)
        reply = {"actions": actions, "relations": [], "artifacts": [], "target_context": {"hosts": [], "services": []}}
        with patch.object(analysis, "complete", lambda *a, **k: {"text": json.dumps(reply)}):
            return analysis.analyze_source(input_kind="text", content=source, source_name="t", units=units,
                                           parsed_source=parsed, method="single_pass", name="t")

    def test_single_inline_tag_in_the_cited_sentence_is_taken_from_the_source(self):
        ir = self.analyse(self.SOURCE, [
            {"id": "a1", "name": "exploited the portal", "epistemic_status": "supported",
             "evidence": [{"quote": "The group exploited the portal", "source_ref": "p1"}]},
            {"id": "a2", "name": "copy the customer table", "epistemic_status": "supported",
             "evidence": [{"quote": "used to copy the customer table", "source_ref": "p2"}]}])
        a1, a2 = ir["actions"]
        self.assertEqual((a1["attack_technique"], a1["field_sources"]), ("T1190", {"attack_technique": "source_quote"}))
        self.assertNotIn("attack_technique", a2)

    def test_sentence_with_several_tags_assigns_none(self):
        ir = self.analyse("The actors used RDP [T1021.001] and the DefaultAccount [T1078.001] to move laterally.", [
            {"id": "a1", "name": "used RDP", "epistemic_status": "supported",
             "evidence": [{"quote": "The actors used RDP", "source_ref": "p1"}]}])
        self.assertNotIn("attack_technique", ir["actions"][0])

    def test_bare_string_evidence_is_accepted_and_located_by_the_program(self):
        ir = self.analyse(self.SOURCE, [{"id": "a1", "name": "install a web shell named helper.aspx",
                                         "epistemic_status": "supported", "evidence": ["install a web shell named helper.aspx"]}])
        action = ir["actions"][0]
        self.assertEqual(action["epistemic_status"], "supported")
        record = next(e for e in ir["evidence"] if e["id"] == action["evidence_refs"][0])
        self.assertEqual((record["quote_match"], record["locator"]["ref"]), ("exact", "1"))


class ActorFilter(unittest.TestCase):
    def test_defender_actions_and_their_edges_stay_out_of_the_attack_flow(self):
        source = "The actor exploited the portal.\n\nThen the company blocked the addresses and notified the FBI."
        ir = run(source, {
            "actions": [
                {"id": "a1", "name": "exploited the portal", "actor": "attacker", "epistemic_status": "supported",
                 "evidence": [{"quote": "The actor exploited the portal.", "source_ref": "p1"}]},
                {"id": "a2", "name": "blocked the addresses", "actor": "defender", "epistemic_status": "supported",
                 "evidence": [{"quote": "the company blocked the addresses", "source_ref": "p2"}]},
            ],
            "relations": [{"id": "r1", "from_action": "a1", "to_action": "a2", "kind": "temporal", "epistemic_status": "supported",
                           "evidence": [{"quote": "Then the company blocked the addresses", "source_ref": "p2"}]}],
            "target_context": {"hosts": [], "services": []}, "artifacts": []}, "text")
        self.assertEqual([action["id"] for action in ir["actions"]], ["a1"])
        self.assertEqual(ir["relations"], [])
        self.assertEqual(ir["quality"]["excluded_non_attacker_actions"],
                         [{"id": "a2", "name": "blocked the addresses", "actor": "defender"}])


class FocusedPasses(unittest.TestCase):
    """The environment and relation passes replace the first pass's answers; a bad pass is ignored."""

    SOURCE = ("The actor exploited the portal server WEB-1.\n\n"
              "Using the portal foothold, the actor queried the database DB-1 over TCP/5432.")
    FIRST = {"actions": [
        {"id": "a1", "name": "exploited the portal", "target_host_ref": "x", "epistemic_status": "supported",
         "evidence": [{"quote": "The actor exploited the portal server WEB-1.", "source_ref": "p1"}]},
        {"id": "a2", "name": "queried the database", "target_host_ref": "x", "epistemic_status": "supported",
         "evidence": [{"quote": "the actor queried the database DB-1", "source_ref": "p2"}]}],
        "relations": [{"id": "r1", "from_action": "a1", "to_action": "a2", "kind": "temporal", "epistemic_status": "inferred"}],
        "target_context": {"hosts": [], "services": []}, "artifacts": []}
    CONTEXT = {"hosts": [
        {"id": "h1", "name": "WEB-1", "role": "portal server", "epistemic_status": "supported",
         "evidence": [{"quote": "the portal server WEB-1", "source_ref": "p1"}]},
        {"id": "h2", "name": "DB-1", "role": "database", "epistemic_status": "supported",
         "evidence": [{"quote": "the database DB-1", "source_ref": "p2"}]}],
        "services": [{"id": "s1", "name": "database", "host_ref": "h2", "port": 5432, "protocol": "tcp",
                      "epistemic_status": "supported", "evidence": [{"quote": "over TCP/5432", "source_ref": "p2"}]}],
        "artifacts": [],
        "action_hosts": [{"action_id": "a1", "target_host_ref": "h1"},
                         {"action_id": "a2", "target_host_ref": "h2", "source_host_ref": "h1"}]}
    RELATIONS = {"relations": [{"id": "r1", "from_action": "a1", "to_action": "a2", "kind": "dependency",
                                "epistemic_status": "supported", "rationale": "portal foothold",
                                "evidence": [{"quote": "Using the portal foothold, the actor queried the database DB-1", "source_ref": "p2"}]}]}

    def analyse(self, replies):
        units, parsed = parse_source("text", self.SOURCE)
        calls = []

        def fake(messages, **kwargs):
            calls.append(kwargs["purpose"])
            return {"text": json.dumps(replies[kwargs["purpose"]]) if not isinstance(replies[kwargs["purpose"]], str)
                    else replies[kwargs["purpose"]]}

        with patch.object(analysis, "complete", fake):
            ir = analysis.analyze_source(input_kind="text", content=self.SOURCE, source_name="t", units=units,
                                         parsed_source=parsed, method="single_pass", name="t")
        return ir, calls

    def test_passes_supply_hosts_services_action_placement_and_cited_relations(self):
        ir, calls = self.analyse({"cti_analysis_single_pass": self.FIRST, "cti_analysis_context": self.CONTEXT,
                                  "cti_analysis_relations": self.RELATIONS})
        self.assertEqual(calls, ["cti_analysis_single_pass", "cti_analysis_context", "cti_analysis_relations"])
        self.assertEqual([(h["id"], h["name"]) for h in ir["hosts"]], [("h1", "WEB-1"), ("h2", "DB-1")])
        self.assertEqual([(a["target_host_ref"], a.get("source_host_ref")) for a in ir["actions"]], [("h1", None), ("h2", "h1")])
        self.assertEqual((ir["services"][0]["host_ref"], ir["services"][0]["port"]), ("h2", 5432))
        relation = ir["relations"][0]
        self.assertEqual((relation["kind"], relation["epistemic_status"]), ("dependency", "supported"))

    def test_unusable_pass_output_falls_back_to_the_first_pass(self):
        ir, _ = self.analyse({"cti_analysis_single_pass": self.FIRST, "cti_analysis_context": "not json",
                              "cti_analysis_relations": {"relations": "nope"}})
        self.assertEqual([a["target_host_ref"] for a in ir["actions"]], ["unknown", "unknown"])
        self.assertEqual((ir["relations"][0]["kind"], ir["relations"][0]["epistemic_status"]), ("temporal", "inferred"))


class CveServiceAssociation(unittest.TestCase):
    def model(self):
        return {
            "actions": [{
                "id": "a1", "name": "exploited Apache Struts", "target_host_ref": "h1",
                "epistemic_status": "supported",
                "evidence": [{"quote": "Apache Struts Web Framework was vulnerable under CVE-2017-5638.", "source_ref": "p1"}],
            }],
            "relations": [],
            "target_context": {
                "hosts": [{"id": "h1", "role": "online dispute portal",
                           "epistemic_status": "supported",
                           "evidence": [{"quote": "Apache Struts Web Framework", "source_ref": "p1"}]}],
                "services": [{"id": "s1", "name": "Apache Struts component", "host_ref": "h1",
                              "epistemic_status": "supported",
                              "evidence": [{"quote": "Apache Struts Web Framework", "source_ref": "p1"}]}],
            },
            "artifacts": [],
        }

    def test_literal_cve_is_attached_through_unique_product_alias_and_version_stays_unknown(self):
        source = "Apache Struts Web Framework was vulnerable under CVE-2017-5638."
        ir = run(source, self.model(), "text")
        service = ir["services"][0]
        self.assertEqual(service["name"], "Apache Struts component")
        self.assertEqual(service["cve"], ["CVE-2017-5638"])
        self.assertEqual(service["field_sources"]["cve"], "source_quote")
        self.assertNotIn("version", service)
        cve_refs = next(indicator["evidence_refs"] for indicator in ir["indicators"]
                        if indicator["type"] == "cve" and indicator["value"] == "CVE-2017-5638")
        self.assertTrue(set(cve_refs) <= set(service["evidence_refs"]))
        relationship_evidence = [item for item in ir["evidence"] if item["id"] in service["evidence_refs"]]
        self.assertTrue(any(
            item["quote"] == source and all(term.casefold() in item["quote"].casefold()
                                             for term in ("CVE-2017-5638", "Apache Struts", "vulnerable"))
            and item["locator"] == {"kind": "paragraph", "ref": "1"}
            for item in relationship_evidence))
        missing_ids = {item["id"] for item in ir["missing_items"]}
        # The integrated inventory resolves this exact CVE to its pinned vulnerable Struts
        # exercise image, so asking the user for a version would repeat a decision the CVE fixes.
        self.assertNotIn("missing-service-s1-version", missing_ids)
        self.assertNotIn("missing-cve-cve-2017-5638-software", missing_ids)
        self.assertNotIn("missing-gap-exploited-weakness", missing_ids)

        planned = plan_dependencies(ir)
        self.assertEqual([entry["id"] for entry in planned["services"]], ["s1"])
        planned_service = planned["services"][0]
        self.assertEqual((planned_service["name"], planned_service["cve"]),
                         ("Apache Struts component", ["CVE-2017-5638"]))
        self.assertNotIn("version", planned_service)
        self.assertEqual(planned_service["version_basis"], "assumed")
        self.assertEqual(planned_service["catalogue_component"], "vuln-struts2-s2-045")
        self.assertEqual(planned_service["reproduces_cve"], ["CVE-2017-5638"])
        self.assertFalse(any("affected software for CVE-2017-5638" == item.get("field")
                             for item in planned["missing_items"]))
        host = next(host for host in build_environment_plan(planned)["hosts"] if host["id"] == "h1")
        self.assertEqual(host["services"], [{"name": "Apache Struts component", "port": 8080, "protocol": "tcp"}])

    def test_cve_in_a_separate_unit_is_not_guessed_onto_struts_and_asks_for_affected_product(self):
        source = ("The online dispute portal used the Apache Struts Web Framework.\n\n"
                  "CVE-2017-5638 is listed in a separate vulnerability table.")
        model = self.model()
        model["actions"][0]["evidence"] = [{"quote": "the Apache Struts Web Framework", "source_ref": "p1"}]
        ir = run(source, model, "text")
        service = ir["services"][0]
        self.assertEqual(service["name"], "Apache Struts component")
        self.assertNotIn("cve", service)
        self.assertNotIn("version", service)
        missing = {item["id"]: item for item in ir["missing_items"]}
        self.assertIn("missing-cve-cve-2017-5638-software", missing)
        self.assertIn("CVE-2017-5638", missing["missing-cve-cve-2017-5638-software"]["question"])
        self.assertNotIn("missing-gap-exploited-weakness", missing)
        planned = plan_dependencies(ir)
        planned_service = next(item for item in planned["services"] if item["id"] == "s1")
        self.assertFalse(planned_service.get("cve"))
        self.assertEqual(len([item for item in planned["missing_items"]
                              if item.get("field") == "affected software for CVE-2017-5638"]), 1)

    def test_cve_for_http_server_is_not_attached_to_struts_mentioned_in_same_clause(self):
        source = "Apache Struts runs the portal, while CVE-2024-12345 affects Apache HTTP Server."
        model = self.model()
        model["actions"] = []
        model["target_context"]["hosts"] = []
        model["target_context"]["services"] = [{
            "id": "s1", "name": "Apache Struts component", "epistemic_status": "supported",
            "evidence": [{"quote": "Apache Struts runs the portal", "source_ref": "p1"}],
        }]
        ir = run(source, model, "text")
        self.assertNotIn("cve", ir["services"][0])
        self.assertTrue(any(item["type"] == "cve" and item["value"] == "CVE-2024-12345"
                            for item in ir["indicators"]))
        self.assertIn("missing-cve-cve-2024-12345-software", {item["id"] for item in ir["missing_items"]})

    def test_multi_product_affected_phrase_is_not_substring_matched_to_struts(self):
        source = "CVE-2024-12345 affects Apache Struts and Apache HTTP Server."
        model = self.model()
        model["actions"] = []
        model["target_context"]["hosts"] = []
        model["target_context"]["services"] = [{
            "id": "s1", "name": "Apache Struts component", "epistemic_status": "supported",
            "evidence": [{"quote": "Apache Struts", "source_ref": "p1"}],
        }]
        ir = run(source, model, "text")
        self.assertNotIn("cve", ir["services"][0])
        self.assertIn("missing-cve-cve-2024-12345-software", {item["id"] for item in ir["missing_items"]})

    def test_comma_separated_affected_products_are_not_truncated_to_struts(self):
        source = "CVE-2024-12345 affects Apache Struts, Apache HTTP Server."
        model = self.model()
        model["actions"] = []
        model["target_context"]["hosts"] = []
        model["target_context"]["services"] = [{
            "id": "s1", "name": "Apache Struts component", "epistemic_status": "supported",
            "evidence": [{"quote": "Apache Struts", "source_ref": "p1"}],
        }]
        ir = run(source, model, "text")
        self.assertNotIn("cve", ir["services"][0])
        self.assertTrue(any(item["type"] == "cve" and item["value"] == "CVE-2024-12345"
                            for item in ir["indicators"]))
        self.assertIn("missing-cve-cve-2024-12345-software", {item["id"] for item in ir["missing_items"]})

    def test_semicolon_separated_affected_products_are_not_truncated_to_struts(self):
        source = "CVE-2024-12345 affects Apache Struts; Apache HTTP Server."
        model = self.model()
        model["actions"] = []
        model["target_context"]["hosts"] = []
        model["target_context"]["services"] = [{
            "id": "s1", "name": "Apache Struts component", "epistemic_status": "supported",
            "evidence": [{"quote": "Apache Struts", "source_ref": "p1"}],
        }]
        ir = run(source, model, "text")
        self.assertNotIn("cve", ir["services"][0])
        self.assertIn("missing-cve-cve-2024-12345-software", {item["id"] for item in ir["missing_items"]})

    def test_unverified_model_supplied_cve_is_removed_and_asks_for_affected_product(self):
        source = "Struts 用於入口網站。CVE-2024-12345 影響 Apache HTTP Server。"
        model = self.model()
        model["actions"] = []
        model["target_context"]["hosts"] = []
        model["target_context"]["services"] = [{
            "id": "s1", "name": "Apache Struts component", "cve": ["CVE-2024-12345"],
            "epistemic_status": "supported", "evidence": [{"quote": "Struts", "source_ref": "p1"}],
        }]
        ir = run(source, model, "text")
        self.assertNotIn("cve", ir["services"][0])
        self.assertTrue(any(item["type"] == "cve" and item["value"] == "CVE-2024-12345"
                            for item in ir["indicators"]))
        self.assertIn("missing-cve-cve-2024-12345-software", {item["id"] for item in ir["missing_items"]})

    def test_product_editions_and_versions_are_not_normalized_together(self):
        cases = (
            ("CVE-2024-12345 affects Microsoft Windows Server.", "Microsoft Windows"),
            ("CVE-2024-12345 affects Apache Struts 1.", "Apache Struts 2"),
        )
        for source, service_name in cases:
            with self.subTest(service_name=service_name):
                model = self.model()
                model["actions"] = []
                model["target_context"]["hosts"] = []
                model["target_context"]["services"] = [{
                    "id": "s1", "name": service_name, "epistemic_status": "supported",
                    "evidence": [{"quote": service_name, "source_ref": "p1"}],
                }]
                ir = run(source, model, "text")
                self.assertNotIn("cve", ir["services"][0])
                self.assertIn("missing-cve-cve-2024-12345-software", {item["id"] for item in ir["missing_items"]})

    def test_weak_cve_relation_wording_does_not_attach_product(self):
        for source in ("CVE-2024-12345 is present in Apache Struts.", "CVE-2024-12345 in Apache Struts."):
            with self.subTest(source=source):
                model = self.model()
                model["actions"] = []
                model["target_context"]["hosts"] = []
                model["target_context"]["services"] = [{
                    "id": "s1", "name": "Apache Struts component", "epistemic_status": "supported",
                    "evidence": [{"quote": "Apache Struts", "source_ref": "p1"}],
                }]
                ir = run(source, model, "text")
                self.assertNotIn("cve", ir["services"][0])
                self.assertIn("missing-cve-cve-2024-12345-software",
                              {item["id"] for item in ir["missing_items"]})

    def test_product_in_another_sentence_of_the_paragraph_does_not_receive_cve(self):
        source = "The portal runs Apache Struts. CVE-2024-12345 affects Apache HTTP Server."
        model = self.model()
        model["actions"] = []
        model["target_context"]["hosts"] = []
        model["target_context"]["services"] = [{
            "id": "s1", "name": "Apache Struts component", "epistemic_status": "supported",
            "evidence": [{"quote": "Apache Struts", "source_ref": "p1"}],
        }]
        ir = run(source, model, "text")
        self.assertNotIn("cve", ir["services"][0])
        self.assertIn("missing-cve-cve-2024-12345-software", {item["id"] for item in ir["missing_items"]})


class ProtocolListenerClassification(unittest.TestCase):
    def test_outbound_https_is_not_kept_as_a_listener_or_opened_inbound(self):
        source = "The portal server made an outbound HTTPS request to external domain update.example."
        model = {
            "actions": [{"id": "a1", "name": "The portal server made an outbound HTTPS request",
                         "target_host_ref": "h1", "epistemic_status": "supported",
                         "evidence": [{"quote": source, "source_ref": "p1"}]}],
            "relations": [], "artifacts": [],
            "target_context": {
                "hosts": [{"id": "h1", "name": "portal", "role": "endpoint",
                           "epistemic_status": "supported", "evidence": [{"quote": source, "source_ref": "p1"}]}],
                "services": [{"id": "s1", "name": "HTTPS", "host_ref": "h1", "port": 443,
                              "epistemic_status": "supported", "evidence": [{"quote": source, "source_ref": "p1"}]}],
            },
        }
        ir = run(source, model, "text")
        self.assertFalse(any(service.get("id") == "s1" for service in ir["services"]))
        self.assertIn("HTTPS", ir["quality"]["dropped_non_software_services"])

        planned = plan_dependencies(ir)
        plan = build_environment_plan(planned)
        self.assertFalse(any(connection.get("from_host") == "attacker" and connection.get("to_host") == "h1"
                             and connection.get("port") == 443 for connection in plan["connections"]))
        self.assertTrue(any("outbound HTTPS from portal to update.example" in note
                            and "No egress allow rule" in note for note in plan["notes"]))

    def test_source_confirmed_inbound_https_listener_is_preserved(self):
        source = "The public portal listens for inbound HTTPS requests on port 443."
        model = {
            "actions": [{"id": "a1", "name": "The attacker requested the portal over HTTPS",
                         "target_host_ref": "h1", "epistemic_status": "supported",
                         "evidence": [{"quote": source, "source_ref": "p1"}]}],
            "relations": [], "artifacts": [],
            "target_context": {
                "hosts": [{"id": "h1", "name": "portal", "role": "public web server",
                           "epistemic_status": "supported", "evidence": [{"quote": source, "source_ref": "p1"}]}],
                "services": [{"id": "s1", "name": "HTTPS", "host_ref": "h1", "port": 443,
                              "epistemic_status": "supported", "evidence": [{"quote": source, "source_ref": "p1"}]}],
            },
        }
        ir = run(source, model, "text")
        listener = next(service for service in ir["services"] if service["id"] == "s1")
        self.assertEqual(listener.get("service_kind"), "network_listener")
        planned = plan_dependencies(ir)
        self.assertTrue(any(service.get("id") == "s1" for service in planned["services"]))
        plan = build_environment_plan(planned)
        self.assertTrue(any(connection.get("from_host") == "attacker" and connection.get("to_host") == "h1"
                            and connection.get("port") == 443 for connection in plan["connections"]))

    def test_absent_https_listener_is_not_confirmed_by_does_not_have_or_lacks(self):
        for absence in ("does not have", "lacks"):
            with self.subTest(absence=absence):
                source = f"The public portal {absence} an HTTPS listener."
                model = {
                    "actions": [{"id": "a1", "name": "The attacker targeted the portal",
                                 "target_host_ref": "h1", "epistemic_status": "supported",
                                 "evidence": [{"quote": source, "source_ref": "p1"}]}],
                    "relations": [], "artifacts": [],
                    "target_context": {
                        "hosts": [{"id": "h1", "name": "portal", "role": "public web server",
                                   "epistemic_status": "supported", "evidence": [{"quote": source, "source_ref": "p1"}]}],
                        "services": [{"id": "s1", "name": "HTTPS", "host_ref": "h1", "port": 443,
                                      "epistemic_status": "supported", "evidence": [{"quote": source, "source_ref": "p1"}]}],
                    },
                }
                ir = run(source, model, "text")
                self.assertFalse(any(service.get("id") == "s1" for service in ir["services"]))
                self.assertIn("HTTPS", ir["quality"]["dropped_non_software_services"])


if __name__ == "__main__":
    unittest.main()
