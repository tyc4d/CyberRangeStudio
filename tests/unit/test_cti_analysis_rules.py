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
        self.assertEqual((smb["host_ref"], smb["port"], smb["protocol"], smb["cve"]), ("h2", 445, "tcp", ["CVE-2020-0796"]))
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


if __name__ == "__main__":
    unittest.main()
