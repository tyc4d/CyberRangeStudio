"""Unit tests for conservative evidence, DAG and fidelity aggregation."""
from __future__ import annotations

import unittest

from app.poc.chain.evidence import verify_execution
from app.poc.chain.report import build_fidelity_report
from app.poc.chain.validation import validate_chain


def _run(action_id: str, status: str = "PASS", *, note: str = "", started: bool = True):
    return {"action_id": action_id, "status": status, "target_ownership_verified": True,
            "stages": {"started": started, "delivered": True, "responded": True,
                       "vuln_behavior": status == "PASS", "state_change": False, "action_complete": True},
            "evidence": ([{"kind": "exploit_effect", "path": f"/evidence/{action_id}", "sha256": "abc",
                           "redacted": True, "note": note}] if status == "PASS" else []),
            "logs_path": "", "confidence": 1.0, "payload_sha256": "abc", "started_at": "1", "ended_at": "2"}


class EvidenceTests(unittest.TestCase):
    def test_http_response_cannot_prove_exploit(self):
        result = _run("a1")
        result["evidence"] = [{"kind": "response", "path": "/response", "sha256": "abc"}]
        self.assertEqual(verify_execution(result), "FAIL")

    def test_unowned_target_is_blocked_even_with_proof(self):
        result = _run("a1")
        result["target_ownership_verified"] = False
        self.assertEqual(verify_execution(result), "BLOCKED")


class ChainTests(unittest.TestCase):
    def setUp(self):
        self.ir = {"actions": [{"id": "a1"}, {"id": "a2"}],
                   "evidence": [{"id": "ev1", "quote": "credential obtained and used by next step"}],
                   "relations": [{"id": "r1", "kind": "dependency", "from_action": "a1", "to_action": "a2",
                                  "evidence_refs": ["ev1"]}]}
        self.plan = {"items": [{"action_id": "a1", "strategy": "poc_exec", "preconditions": []},
                                {"action_id": "a2", "strategy": "poc_exec", "preconditions": ["cred from prior action"]}]}

    def test_verified_transfer_passes_only_with_ordered_effect_evidence(self):
        runs = [_run("a1", note="cred acquired"), _run("a2")]
        result = validate_chain("s1", self.ir, self.plan, runs)
        self.assertTrue(result["passes"])
        self.assertTrue(result["transfers"][0]["verified"])

    def test_broken_chain_predecessor_fail_blocks_dependent_pass(self):
        runs = [_run("a1", "FAIL"), _run("a2")]
        result = validate_chain("s1", self.ir, self.plan, runs)
        self.assertFalse(result["passes"])
        self.assertEqual(result["per_action"][1]["status"], "PARTIAL")

    def test_missing_transfer_is_not_inferred(self):
        runs = [_run("a1", note="completed step"), _run("a2")]
        result = validate_chain("s1", self.ir, self.plan, runs)
        self.assertFalse(result["passes"])
        self.assertFalse(result["transfers"][0]["verified"])

    def test_uncited_relation_does_not_create_passable_dependency(self):
        self.ir["relations"][0]["evidence_refs"] = ["missing"]
        result = validate_chain("s1", self.ir, self.plan, [_run("a1", note="cred acquired"), _run("a2")])
        self.assertFalse(result["passes"])
        self.assertFalse(result["order_ok"])


class FidelityTests(unittest.TestCase):
    def test_full_chain_requires_all_three_levels_and_chain(self):
        ir = {"actions": [{"id": "a1"}]}
        plan = {"items": [{"action_id": "a1", "strategy": "poc_exec", "expected_evidence": "effect"}]}
        chain = {"passes": True, "objective_reached": True, "per_action": [{"action_id": "a1", "status": "PASS"}]}
        report = build_fidelity_report("s1", ir, plan, [], chain,
                                       {"levels": {"env_build": "PASS", "behavior_repro": "NOT_TESTED"}, "checks": []})
        self.assertEqual(report["levels"]["full_chain"], "NOT_TESTED")
        self.assertEqual(report["fidelity"]["reproduced"], ["a1"])


if __name__ == "__main__":
    unittest.main()
