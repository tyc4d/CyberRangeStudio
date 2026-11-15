"""Module 9 contract + plan() unit tests.

Covers: (1) the poc-validation JSON Schema accepts valid CONTRACT shapes and rejects
malformed ones, via cr_contracts.iter_errors / iter_errors_shape; (2) poc.service.plan()
produces a schema-valid ValidationPlan and maps reproducibility to the correct strategy
(including the owner's rule that not_executable items are never executable).
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cr_contracts import iter_errors, iter_errors_shape

from app.poc import service


# --- sample valid shapes ----------------------------------------------------
VALID_PLAN = {
    "scenario_id": "s1",
    "generated_at": "2026-11-16T00:00:00Z",
    "items": [
        {
            "action_id": "a1",
            "target_host_ref": "web",
            "service_ref": "svc-struts",
            "cve": "CVE-2017-5638",
            "attack_technique": "T1190",
            "strategy": "poc_exec",
            "poc_required": True,
            "required_predecessors": [],
            "preconditions": ["target reachable on isolated net"],
            "expected_evidence": "OGNL arithmetic echoed in response",
        },
        {
            "action_id": "a2",
            "strategy": "not_executable",
            "poc_required": False,
            "required_predecessors": ["a1"],
            "preconditions": [],
            "expected_evidence": "none",
            "not_executable_reason": "closed-source appliance, no image",
        },
    ],
}

VALID_CANDIDATE = {
    "action_id": "a1",
    "cve": "CVE-2017-5638",
    "source": "github",
    "source_url": "https://github.com/x/y",
    "ref": {"commit_sha": "deadbeef"},
    "product": "Apache Struts",
    "version_range": "2.3.x",
    "language": "python",
    "dependencies": ["requests"],
    "preconditions": [],
    "exec_method": "python",
    "trust": "medium",
    "compatibility_score": 0.82,
    "score_breakdown": {"version": 0.9, "env": 0.8, "code_available": 1.0,
                        "source_trust": 0.6, "exec_cost": 0.7},
}

VALID_EXECUTION = {
    "action_id": "a1",
    "poc": {"source_url": "https://github.com/x/y", "ref": {"commit_sha": "deadbeef"},
            "sha256": "a" * 64},
    "status": "PASS",
    "stages": {"started": True, "delivered": True, "responded": True,
               "vuln_behavior": True, "state_change": True, "action_complete": True},
    "evidence": [{"kind": "exploit_effect", "path": "art/ev1", "sha256": "b" * 64,
                  "redacted": False, "note": "echoed 7*7=49"}],
    "logs_path": "art/logs/a1",
    "confidence": 0.95,
    "target_ownership_verified": True,
    "payload_sha256": "c" * 64,
    "started_at": "2026-11-16T00:00:00Z",
    "ended_at": "2026-11-16T00:01:00Z",
}

VALID_CHAIN = {
    "scenario_id": "s1",
    "objective_reached": True,
    "passes": True,
    "transfers": [{"from_action": "a1", "to_action": "a2", "carried": "cred",
                   "verified": True, "evidence_ref": "ev1"}],
    "order_ok": True,
    "per_action": [{"action_id": "a1", "status": "PASS"}],
}

VALID_EXPORT = {
    "scenario_id": "s1",
    "scenario_version": 3,
    "created_at": "2026-11-16T00:00:00Z",
    "files": [{"path": "infrastructure/docker-compose.yml", "sha256": "d" * 64,
               "generated_by": "iac.generator"}],
    "rebuildable": False,
    "missing_for_rebuild": ["vendor appliance image"],
    "contains_secrets": False,
}


class SchemaTests(unittest.TestCase):
    def test_valid_plan_passes_root(self):
        self.assertEqual(iter_errors("poc-validation", VALID_PLAN), [])

    def test_each_shape_valid(self):
        cases = {
            "ValidationPlan": VALID_PLAN,
            "PocCandidate": VALID_CANDIDATE,
            "PocManifest": {"scenario_id": "s1", "generated_at": "t", "items": [VALID_CANDIDATE]},
            "ExecutionResult": VALID_EXECUTION,
            "Evidence": VALID_EXECUTION["evidence"][0],
            "ChainValidation": VALID_CHAIN,
            "ExportManifest": VALID_EXPORT,
        }
        for shape, obj in cases.items():
            with self.subTest(shape=shape):
                self.assertEqual(iter_errors_shape(shape, obj), [], shape)

    def test_not_executable_requires_reason(self):
        bad = {"action_id": "a", "strategy": "not_executable", "poc_required": False,
               "required_predecessors": [], "preconditions": [], "expected_evidence": "x"}
        self.assertTrue(iter_errors_shape("ValidationItem", bad))

    def test_bad_strategy_rejected(self):
        bad = {**VALID_PLAN, "items": [{**VALID_PLAN["items"][0], "strategy": "nonsense"}]}
        self.assertTrue(iter_errors("poc-validation", bad))

    def test_execution_bad_status_rejected(self):
        bad = {**VALID_EXECUTION, "status": "GREEN"}
        self.assertTrue(iter_errors_shape("ExecutionResult", bad))

    def test_export_secrets_must_be_false(self):
        bad = {**VALID_EXPORT, "contains_secrets": True}
        self.assertTrue(iter_errors_shape("ExportManifest", bad))

    def test_unknown_shape_raises(self):
        with self.assertRaises(KeyError):
            iter_errors_shape("Nope", {})


def _ir(actions, services=None, relations=None):
    return {
        "schema_version": "1.0",
        "id": "plan-test",
        "name": "plan unit test",
        "provenance": {"input_kind": "text", "input_sha256": "0" * 64},
        "actions": actions,
        "relations": relations or [],
        "services": services or [],
        "hosts": [],
    }


class PlanTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._db = Path(self._tmp.name) / "poc.db"
        p = patch("app.poc.store._DB", self._db)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self._tmp.cleanup)

    def _plan_with(self, ir):
        with patch("app.store.get", return_value=ir):
            return service.plan("plan-test")

    def test_plan_is_schema_valid(self):
        ir = _ir([
            {"id": "a1", "name": "Exploit VMware Horizon connection server",
             "target_host_ref": "h1", "attack_technique": "T1190"},
            {"id": "a2", "name": "Move through Active Directory domain", "target_host_ref": "h2"},
        ])
        plan = self._plan_with(ir)
        self.assertEqual(iter_errors("poc-validation", plan), [])
        self.assertEqual(len(plan["items"]), 2)

    def test_horizon_is_not_executable(self):
        ir = _ir([{"id": "a1", "name": "Exploit VMware Horizon connection server",
                   "target_host_ref": "h1", "attack_technique": "T1190"}])
        item = self._plan_with(ir)["items"][0]
        self.assertEqual(item["strategy"], "not_executable")
        self.assertFalse(item["poc_required"])
        self.assertTrue(item["not_executable_reason"])

    def test_reproducible_exploit_maps_to_poc_exec(self):
        # Drive the mapping deterministically: force classify_action -> reproducible,
        # action carries an exploitation technique => poc_exec, poc_required.
        ir = _ir([{"id": "a1", "name": "exploit the thing", "target_host_ref": "h1",
                   "attack_technique": "T1190"}],
                 services=[{"id": "svc1", "host_ref": "h1", "name": "struts",
                            "cve": ["CVE-2017-5638"]}])
        with patch("app.poc.service.classify_action", return_value=("reproducible", "ok")):
            item = self._plan_with(ir)["items"][0]
        self.assertEqual(item["strategy"], "poc_exec")
        self.assertTrue(item["poc_required"])
        self.assertEqual(item["cve"], "CVE-2017-5638")
        self.assertEqual(item["service_ref"], "svc1")

    def test_reproducible_nonexploit_maps_to_config_check(self):
        ir = _ir([{"id": "a1", "name": "read a config value", "target_host_ref": "h1"}])
        with patch("app.poc.service.classify_action", return_value=("reproducible", "ok")):
            item = self._plan_with(ir)["items"][0]
        self.assertEqual(item["strategy"], "config_check")
        self.assertFalse(item["poc_required"])

    def test_substitute_only_maps_to_config_check(self):
        ir = _ir([{"id": "a1", "name": "exploit", "target_host_ref": "h1",
                   "attack_technique": "T1190"}])
        with patch("app.poc.service.classify_action", return_value=("substitute_only", "limited")):
            item = self._plan_with(ir)["items"][0]
        self.assertEqual(item["strategy"], "config_check")
        self.assertFalse(item["poc_required"])

    def test_dependency_predecessors_only(self):
        ir = _ir(
            [{"id": "a1", "name": "x"}, {"id": "a2", "name": "y"}, {"id": "a3", "name": "z"}],
            relations=[
                {"id": "r1", "from_action": "a1", "to_action": "a3", "kind": "dependency"},
                {"id": "r2", "from_action": "a2", "to_action": "a3", "kind": "temporal"},
            ],
        )
        plan = self._plan_with(ir)
        a3 = next(i for i in plan["items"] if i["action_id"] == "a3")
        self.assertEqual(a3["required_predecessors"], ["a1"])  # temporal excluded

    def test_plan_persisted(self):
        ir = _ir([{"id": "a1", "name": "x"}])
        self._plan_with(ir)
        from app.poc import store as poc_store
        self.assertIsNotNone(poc_store.get_plan("plan-test"))

    def test_unknown_scenario_raises(self):
        with patch("app.store.get", return_value=None):
            with self.assertRaises(KeyError):
                service.plan("missing")


if __name__ == "__main__":
    unittest.main()
