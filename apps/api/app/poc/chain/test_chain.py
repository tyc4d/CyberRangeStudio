"""Artifact-backed synthetic unit fixtures; no payload, network or E2E is exercised."""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from cr_contracts import iter_errors, iter_errors_shape
from app.poc.chain.evidence import proves_effect, scenario_digest, verify_execution
from app.poc.chain.report import build_fidelity_report
from app.poc.chain.validation import validate_chain
from app.poc.runner.payloads import KNOWN_POC_PROOFS, STRUTS_S2045_PROOF_ID


class ArtifactFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ir = {"actions": [{"id": "a1"}, {"id": "a2"}], "evidence": [{"id": "ev1"}],
                   "relations": [{"kind": "dependency", "from_action": "a1", "to_action": "a2",
                                  "evidence_refs": ["ev1"], "carried": "cred"}]}
        self.plan = {"items": [{"action_id": "a1", "strategy": "poc_exec"},
                               {"action_id": "a2", "strategy": "poc_exec", "required_predecessors": ["a1"],
                                "preconditions": ["cred from prior action"]}]}
        self.records = [{"id": 7, "action": "up", "state": "running", "details": {"backend": "proxmox"}}]
        for target, options in (
            ("app.config.DATA_DIR", {"new": self.root}),
            ("app.deploy.manager._lifecycle_records", {"side_effect": lambda sid: self.records}),
            ("app.store.get", {"side_effect": lambda sid: self.ir if sid == "s1" else None}),
        ):
            mock = patch(target, **options)
            mock.start()
            self.addCleanup(mock.stop)
        self.logs = {}
        # Test-only verifier: the production arithmetic verifier stays unchanged and
        # cannot verify credential transfer. This is not real exploit/E2E evidence.
        payload = "QA receipt fixture; never executed"
        self.proof_id = "qa-state-receipt-fixture"
        self.proof = {"source_url": "local://qa/state-receipt-fixture", "payload": payload,
                      "sha256": hashlib.sha256(payload.encode()).hexdigest(), "exec_method": "http_seq",
                      "expected_marker": "QA_VERIFIED_EFFECT", "state_transfer_types": ["cred"]}
        registry = patch.dict(KNOWN_POC_PROOFS, {self.proof_id: self.proof})
        registry.start()
        self.addCleanup(registry.stop)

    def artifact(self, directory, name, content, kind="exploit_effect"):
        path = directory / name
        absolute = self.root / path
        absolute.parent.mkdir(parents=True, exist_ok=True)
        absolute.write_bytes(content)
        return {"kind": kind, "path": str(path), "sha256": hashlib.sha256(content).hexdigest(), "redacted": True}

    def run_result(self, action_id, status="PASS", *, job="1" * 32, start=None, proof_id=None):
        proof_id = proof_id or self.proof_id
        proof = KNOWN_POC_PROOFS[proof_id]
        run_id = uuid.uuid4().hex
        directory = Path("poc-runs") / hashlib.sha256(b"s1").hexdigest()[:16] / run_id
        second = start if start is not None else (int(action_id[1:]) - 1) * 10
        passed = status == "PASS"
        run = {"action_id": action_id, "status": status, "target_ownership_verified": True,
               "poc": {"source_url": proof["source_url"], "ref": {}, "sha256": proof["sha256"]},
               "payload_sha256": proof["sha256"], "logs_path": str(directory / "execution.log"),
               "exit_code": 0 if passed else 1, "confidence": .99 if passed else 0.,
               "started_at": f"2026-11-16T00:00:{second:02d}Z", "ended_at": f"2026-11-16T00:00:{second + 1:02d}Z",
               "stages": {"started": True, "delivered": True, "responded": True,
                          "vuln_behavior": passed, "state_change": passed, "action_complete": True},
               "evidence": [self.artifact(directory, "effect.txt", proof["expected_marker"].encode())] if passed else []}
        self.logs[id(run)] = {"proof_id": proof_id,
                              "context": {"run_id": run_id, "job_id": job, "scenario_id": "s1",
                                          "scenario_sha256": scenario_digest(self.ir), "deployment_record_id": 7},
                              "ownership": {"scenario_id": "s1", "service_ref": "web"},
                              "output": proof["expected_marker"] if passed else "no effect"}
        self.seal(run)
        return run

    def seal(self, run):
        """Create a correctly hashed log for this synthetic fixture."""
        log = self.logs[id(run)]
        log.update({key: run[key] for key in ("action_id", "status", "started_at", "ended_at", "payload_sha256")})
        run["evidence"] = [e for e in run["evidence"] if e["kind"] != "log"]
        log["evidence"] = copy.deepcopy(run["evidence"])
        path = Path(run["logs_path"])
        run["evidence"].append(self.artifact(path.parent, path.name, json.dumps(log, sort_keys=True).encode(), "log"))

    def state_pair(self, predecessor, successor):
        source_log, target_log = self.logs[id(predecessor)], self.logs[id(successor)]
        produced = {"event": "produced", "carried": "cred", "state_id": "qa-state-1",
                    "value_sha256": hashlib.sha256(b"synthetic-state").hexdigest(),
                    "action_id": predecessor["action_id"], "run_id": source_log["context"]["run_id"]}
        evidence = self.artifact(Path(predecessor["logs_path"]).parent, "produced.json", json.dumps(produced).encode(), "state_change")
        predecessor["evidence"].append(evidence)
        consumed = {**produced, "event": "consumed", "action_id": successor["action_id"],
                    "run_id": target_log["context"]["run_id"], "from_action": predecessor["action_id"],
                    "from_run_id": source_log["context"]["run_id"],
                    "source_evidence": {"path": evidence["path"], "sha256": evidence["sha256"]}}
        successor["evidence"].append(self.artifact(Path(successor["logs_path"]).parent, "consumed.json", json.dumps(consumed).encode(), "state_change"))
        self.seal(predecessor)
        self.seal(successor)

    def validate(self, runs):
        return validate_chain("s1", self.ir, self.plan, runs)


class EvidenceTests(ArtifactFixture):
    def test_http_response_cannot_prove_exploit(self):
        result = self.run_result("a1")
        result["evidence"][0]["kind"] = "response"
        self.seal(result)
        self.assertEqual(verify_execution(result), "FAIL")

    def test_unowned_target_is_blocked_even_with_proof(self):
        result = self.run_result("a1")
        result["target_ownership_verified"] = False
        self.assertEqual(verify_execution(result), "BLOCKED")

    def test_registered_artifact_bound_to_current_deployment_can_pass(self):
        self.assertEqual(verify_execution(self.run_result("a1", proof_id=STRUTS_S2045_PROOF_ID)), "PASS")

    def test_missing_tampered_or_outside_root_artifact_is_unverified(self):
        for mutation in ("missing", "hash", "outside", "symlink"):
            with self.subTest(mutation=mutation):
                result = self.run_result("a1")
                artifact = result["evidence"][0]
                path = self.root / artifact["path"]
                if mutation == "missing":
                    path.unlink()
                elif mutation == "hash":
                    path.write_bytes(b"changed")
                else:
                    outside = self.root / "outside.txt"
                    outside.write_text(self.proof["expected_marker"])
                    if mutation == "outside":
                        artifact["path"] = str(outside)
                    else:
                        path.unlink()
                        path.symlink_to(outside)
                self.assertFalse(proves_effect(artifact))
                self.assertEqual(verify_execution(result), "PARTIAL")

    def test_unregistered_source_or_changed_payload_cannot_pass(self):
        for key in ("source_url", "sha256"):
            result = self.run_result("a1")
            result["poc"][key] = "unregistered"
            self.assertEqual(verify_execution(result), "PARTIAL")

    def test_cross_run_artifact_cannot_be_reused(self):
        first, second = self.run_result("a1"), self.run_result("a1", start=20)
        second["evidence"][0] = first["evidence"][0]
        self.seal(second)
        self.assertEqual(verify_execution(second), "PARTIAL")

    def test_changed_scenario_or_redeployment_invalidates_old_success(self):
        result = self.run_result("a1")
        self.ir["ir_version"] = 2
        self.assertEqual(verify_execution(result), "PARTIAL")
        self.ir.pop("ir_version")
        self.records[0]["id"] = 8
        self.assertEqual(verify_execution(result), "PARTIAL")

    def test_stopped_failed_or_ambiguous_deployment_is_unverified(self):
        original = copy.deepcopy(self.records)
        cases = [[{"id": 8, "action": action, "state": state, "details": {"backend": "proxmox"}}]
                 for action, state in (("down", "stopped"), ("up", "failed"))]
        cases.append(original + [{"id": 9, "action": "up", "state": "running", "details": {"backend": "local-docker"}}])
        for records in cases:
            self.records = records
            self.assertEqual(verify_execution(self.run_result("a1")), "PARTIAL")

    def test_blocked_timeout_stays_blocked_despite_delivery(self):
        self.assertEqual(verify_execution(self.run_result("a1", "BLOCKED")), "BLOCKED")

    def test_status_failure_error_output_or_nonzero_exit_cannot_pass(self):
        for mutation in ("status", "error", "exit", "reason"):
            result = self.run_result("a1")
            if mutation == "status":
                result["status"] = "FAIL"
            elif mutation == "error":
                self.logs[id(result)]["output"] += "\nREQUEST_ERROR=HTTPError"
                self.seal(result)
            elif mutation == "exit":
                result["exit_code"] = 1
            else:
                result["failure_reason"] = "transport failure"
            self.assertNotEqual(verify_execution(result), "PASS")


class ChainTests(ArtifactFixture):
    def test_verified_transfer_passes_only_with_ordered_effect_evidence(self):
        runs = [self.run_result("a1"), self.run_result("a2")]
        self.state_pair(*runs)
        result = self.validate(runs)
        self.assertTrue(result["passes"])
        self.assertTrue(result["objective_reached"])
        self.assertTrue(result["transfers"][0]["verified"])
        self.assertEqual(iter_errors_shape("ChainValidation", result), [])

    def test_broken_chain_predecessor_fail_blocks_dependent_pass(self):
        result = self.validate([self.run_result("a1", "FAIL"), self.run_result("a2")])
        self.assertFalse(result["passes"])
        self.assertEqual(result["per_action"][1]["status"], "BLOCKED")

    def test_missing_transfer_is_not_inferred(self):
        result = self.validate([self.run_result("a1"), self.run_result("a2")])
        self.assertTrue(all(item["status"] == "PASS" for item in result["per_action"]))
        self.assertFalse(result["passes"])
        self.assertFalse(result["transfers"][0]["verified"])

    def test_uncited_relation_does_not_create_passable_dependency(self):
        self.ir["relations"][0]["evidence_refs"] = ["missing"]
        result = self.validate([self.run_result("a1"), self.run_result("a2")])
        self.assertFalse(result["passes"])
        self.assertFalse(result["order_ok"])

    def test_independent_valid_action_passes_cannot_prove_chain(self):
        self.ir["relations"] = []
        self.plan["items"][1]["required_predecessors"] = []
        result = self.validate([self.run_result("a1"), self.run_result("a2")])
        self.assertTrue(all(item["status"] == "PASS" for item in result["per_action"]))
        self.assertFalse(result["passes"])
        self.assertFalse(result["objective_reached"])

    def test_failure_propagates_three_hops_independent_of_relation_order_or_citation(self):
        self.ir["actions"].extend([{"id": "a3"}, {"id": "a4"}])
        self.ir["relations"] = [{"kind": "dependency", "from_action": src, "to_action": dst}
                                for src, dst in (("a3", "a4"), ("a2", "a3"), ("a1", "a2"))]
        for initial in ("FAIL", "BLOCKED", "PARTIAL", "NOT_TESTED"):
            runs = [self.run_result("a1", initial)] + [self.run_result(a) for a in ("a2", "a3", "a4")]
            result = self.validate(runs)
            self.assertEqual([p["status"] for p in result["per_action"]][1:], ["BLOCKED"] * 3)

    def test_time_order_uses_timestamps_not_array_position(self):
        a, b = self.run_result("a1"), self.run_result("a2")
        self.state_pair(a, b)
        self.assertTrue(self.validate([b, a])["passes"])
        b = self.run_result("a2", start=0)
        self.state_pair(a, b)
        self.assertFalse(self.validate([a, b])["order_ok"])

    def test_missing_naive_or_reversed_time_cannot_verify_order(self):
        for value in ("", "yesterday", "2026-11-16T00:00:10", "2026-11-16T00:00:00Z"):
            a, b = self.run_result("a1"), self.run_result("a2")
            b["started_at"] = value
            self.seal(b)
            self.assertFalse(self.validate([a, b])["order_ok"])

    def test_cycles_missing_endpoints_and_disconnected_graph_cannot_pass(self):
        for defect in ("cycle", "missing", "disconnected"):
            original = copy.deepcopy(self.ir)
            if defect == "cycle":
                self.ir["relations"].append({**self.ir["relations"][0], "from_action": "a2", "to_action": "a1"})
            elif defect == "missing":
                self.ir["relations"][0]["from_action"] = "missing"
            else:
                self.ir["actions"].append({"id": "a3"})
            a, b = self.run_result("a1"), self.run_result("a2")
            self.state_pair(a, b)
            runs = [a, b] + ([self.run_result("a3")] if defect == "disconnected" else [])
            self.assertFalse(self.validate(runs)["passes"])
            self.ir = original

    def test_temporal_relation_and_plan_only_dependency_are_not_invented(self):
        self.ir["relations"][0]["kind"] = "temporal"
        a, b = self.run_result("a1"), self.run_result("a2")
        self.state_pair(a, b)
        result = self.validate([a, b])
        self.assertEqual(result["transfers"], [])
        self.assertFalse(result["passes"])
        self.assertEqual(result["per_action"][1]["status"], "BLOCKED")

    def test_old_successes_cannot_fill_missing_actions_of_new_batch(self):
        a, b = self.run_result("a1"), self.run_result("a2")
        self.state_pair(a, b)
        newer = self.run_result("a1", job="2" * 32, start=30)
        result = self.validate([a, b, newer])
        self.assertEqual(result["per_action"][1]["status"], "NOT_TESTED")
        self.assertFalse(result["passes"])

    def test_corrupted_latest_log_does_not_fall_back_to_previous_success(self):
        a, b = self.run_result("a1"), self.run_result("a2")
        self.state_pair(a, b)
        latest = self.run_result("a1", job="2" * 32, start=30)
        (self.root / latest["logs_path"]).unlink()
        result = self.validate([a, b, latest])
        self.assertFalse(any(p["status"] == "PASS" for p in result["per_action"]))

    def test_duplicate_attempt_in_one_job_is_ambiguous(self):
        a, b = self.run_result("a1"), self.run_result("a2")
        self.state_pair(a, b)
        result = self.validate([a, b, self.run_result("a1", start=20)])
        self.assertEqual(result["per_action"][0]["status"], "BLOCKED")
        self.assertFalse(result["passes"])

    def test_receipts_require_matching_consumed_state_source_run_and_digest(self):
        for key in ("state_id", "value_sha256", "from_run_id", "source_evidence"):
            a, b = self.run_result("a1"), self.run_result("a2")
            self.state_pair(a, b)
            evidence = next(e for e in b["evidence"] if e["kind"] == "state_change")
            receipt = json.loads((self.root / evidence["path"]).read_bytes())
            receipt[key] = {"path": "wrong", "sha256": "0" * 64} if key == "source_evidence" else "different"
            evidence.update(self.artifact(Path(evidence["path"]).parent, "consumed.json", json.dumps(receipt).encode(), "state_change"))
            self.seal(b)
            result = self.validate([a, b])
            self.assertTrue(all(p["status"] == "PASS" for p in result["per_action"]))
            self.assertFalse(result["transfers"][0]["verified"])

    def test_arithmetic_proof_cannot_verify_credential_transfer_even_with_receipts(self):
        a = self.run_result("a1", proof_id=STRUTS_S2045_PROOF_ID)
        b = self.run_result("a2", proof_id=STRUTS_S2045_PROOF_ID)
        self.state_pair(a, b)
        result = self.validate([a, b])
        self.assertTrue(all(p["status"] == "PASS" for p in result["per_action"]))
        self.assertFalse(result["transfers"][0]["verified"])


class FidelityTests(unittest.TestCase):
    def test_full_chain_requires_all_three_levels_and_chain(self):
        ir = {"actions": [{"id": "a1"}]}
        plan = {"items": [{"action_id": "a1", "strategy": "poc_exec", "expected_evidence": "effect"}]}
        chain = {"passes": True, "objective_reached": True, "per_action": [{"action_id": "a1", "status": "PASS"}]}
        report = build_fidelity_report("s1", ir, plan, [], chain,
                                       {"levels": {"env_build": "PASS", "behavior_repro": "NOT_TESTED"}, "checks": []})
        self.assertEqual(report["levels"]["full_chain"], "NOT_TESTED")
        self.assertEqual(report["fidelity"]["reproduced"], ["a1"])

    def test_full_chain_metric_is_separate_from_two_action_passes(self):
        ir = {"actions": [{"id": "a1"}, {"id": "a2"}]}
        chain = {"passes": False, "objective_reached": False, "order_ok": True,
                 "per_action": [{"action_id": aid, "status": "PASS"} for aid in ("a1", "a2")],
                 "transfers": [{"verified": False}]}
        report = build_fidelity_report("s1", ir, {"items": []}, [], chain,
                                       {"levels": {"env_build": "PASS", "behavior_repro": "PASS"}})
        self.assertEqual(report["levels"]["full_chain"], "PARTIAL")
        self.assertEqual(report["fidelity"]["reproduced"], ["a1", "a2"])
        self.assertEqual(report["checks"][-1]["category"], "chain")
        self.assertEqual(report["checks"][-1]["status"], "PARTIAL")
        self.assertIn("passes=false", report["checks"][-1]["observed"])
        self.assertEqual(iter_errors("validation-report", report), [])


if __name__ == "__main__":
    unittest.main()
