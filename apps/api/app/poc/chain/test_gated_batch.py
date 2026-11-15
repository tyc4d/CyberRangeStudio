"""Real runner logs and SQLite; mocked ownership/transport, no payload execution."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.poc.chain.evidence import execution_log, verify_execution
from app.poc.chain.validation import _select_runs, validate_chain
from app.poc.runner import payloads, runner
from app.poc.runner.models import ExecutionRequest


class GatedBatchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.sid = "chain-gated-batch"
        self.ir = {"actions": [{"id": "a1"}, {"id": "a2"}], "evidence": [{"id": "e1"}],
                   "relations": [{"kind": "dependency", "from_action": "a1", "to_action": "a2",
                                  "evidence_refs": ["e1"], "carried": "cred"}]}
        self.plan = {"items": [{"action_id": aid, "strategy": "poc_exec"} for aid in ("a1", "a2")]}
        record = {"id": 73, "action": "up", "state": "running", "details": {"backend": "proxmox"}}
        self.transport = Mock(return_value=({"returncode": 1, "stdout": "no effect", "stderr": ""}, None))
        self.ownership = Mock(side_effect=lambda sid, target: {
            "scenario_id": sid, "service_ref": target["service_ref"], "deployment_record_id": 73,
        })
        for target, options in (
            ("app.config.DATA_DIR", {"new": self.root}),
            ("app.poc.store._DB", {"new": self.root / "poc.db"}),
            ("app.store.get", {"side_effect": lambda sid: self.ir if sid == self.sid else None}),
            ("app.deploy.manager._lifecycle_records", {"return_value": [record]}),
            ("app.poc.runner.runner.assert_target_owned", {"new": self.ownership}),
            ("app.poc.runner.runner._probe_with_cancel", {"new": self.transport}),
            ("subprocess.run", {"side_effect": AssertionError("test forbids real subprocesses")}),
        ):
            mock = patch(target, **options)
            mock.start()
            self.addCleanup(mock.stop)

    def run_batch(self, predecessor="a1"):
        proof = payloads.KNOWN_POC_PROOFS[payloads.STRUTS_S2045_PROOF_ID]
        requests = [ExecutionRequest(
            action_id=aid, scenario_id=self.sid, service_ref="web", source_url=proof["source_url"],
            ref={}, sha256=proof["sha256"], exec_method=proof["exec_method"], payload=proof["payload"],
            expected_marker=proof["expected_marker"], proof_id=payloads.STRUTS_S2045_PROOF_ID,
            required_predecessors=() if aid == "a1" else (predecessor,),
        ) for aid in ("a1", "a2")]
        return runner.run_job(self.sid, requests)

    def reseal(self, result, mutate):
        path = self.root / result["logs_path"]
        log = json.loads(path.read_bytes())
        mutate(log)
        content = json.dumps(log, sort_keys=True).encode()
        path.write_bytes(content)
        next(e for e in result["evidence"] if e["kind"] == "log")["sha256"] = hashlib.sha256(content).hexdigest()

    def assert_gated_batch(self, code, expected):
        self.transport.return_value = ({"returncode": code, "stdout": "no effect", "stderr": ""}, None)
        runs = self.run_batch()
        self.assertEqual([r["status"] for r in runs], [expected, "BLOCKED"])
        self.assertEqual(self.transport.call_count, 1)
        self.assertEqual(self.ownership.call_count, 1)
        blocked = runs[1]
        self.assertFalse(blocked["target_ownership_verified"])
        self.assertTrue(all(value is False for value in blocked["stages"].values()))
        log = execution_log(blocked)
        self.assertIsNotNone(log)
        self.assertIsNone(log["ownership"])
        self.assertEqual(log["evidence"], [])
        self.assertNotIn("deployment_record_id", log["context"])
        selected, ambiguous = _select_runs(runs)
        self.assertEqual(set(selected), {"a1", "a2"})
        self.assertEqual(ambiguous, set())
        self.assertEqual(execution_log(runs[0])["context"]["job_id"], log["context"]["job_id"])
        chain = validate_chain(self.sid, self.ir, self.plan, runs)
        self.assertEqual([p["status"] for p in chain["per_action"]], [expected, "BLOCKED"])
        self.assertFalse(chain["passes"])
        self.assertFalse(chain["objective_reached"])

    def test_failed_predecessor_and_gated_blocked_stay_in_same_batch(self):
        self.assert_gated_batch(1, "FAIL")

    def test_blocked_predecessor_and_gated_blocked_stay_in_same_batch(self):
        self.assert_gated_batch(127, "BLOCKED")

    def test_gated_block_does_not_drop_a_verified_independent_sibling(self):
        self.ir["relations"][0]["from_action"] = "missing"
        self.transport.return_value = ({"returncode": 0, "stdout": payloads.STRUTS_S2045_MARKER, "stderr": ""}, None)
        runs = self.run_batch(predecessor="missing")
        self.assertEqual(verify_execution(runs[0]), "PASS")
        chain = validate_chain(self.sid, self.ir, self.plan, runs)
        self.assertEqual([p["status"] for p in chain["per_action"]], ["PASS", "BLOCKED"])
        self.assertFalse(chain["passes"])

    def test_ownership_exemption_cannot_promote_a_gated_block_to_pass(self):
        blocked = self.run_batch()[1]
        blocked["status"] = "PASS"
        self.reseal(blocked, lambda log: log.update(status="PASS"))
        self.assertIsNone(execution_log(blocked))
        self.assertEqual(verify_execution(blocked), "BLOCKED")

    def test_ownership_exemption_requires_no_execution_stages_or_effects(self):
        for mutation in ("started", "effect"):
            with self.subTest(mutation=mutation):
                blocked = self.run_batch()[1]
                if mutation == "started":
                    blocked["stages"]["started"] = True
                else:
                    effect_path = Path(blocked["logs_path"]).parent / "effect.txt"
                    content = payloads.STRUTS_S2045_MARKER.encode()
                    (self.root / effect_path).write_bytes(content)
                    entry = {"kind": "exploit_effect", "path": str(effect_path),
                             "sha256": hashlib.sha256(content).hexdigest(), "redacted": True}
                    blocked["evidence"].append(entry)
                    self.reseal(blocked, lambda log: log.update(evidence=[entry]))
                self.assertIsNone(execution_log(blocked))
                self.assertEqual(verify_execution(blocked), "BLOCKED")

    def test_blocked_batch_member_still_requires_log_integrity_and_job_identity(self):
        for mutation in ("hash", "job", "action"):
            with self.subTest(mutation=mutation):
                blocked = self.run_batch()[1]
                if mutation == "hash":
                    blocked["evidence"][0]["sha256"] = "0" * 64
                elif mutation == "job":
                    self.reseal(blocked, lambda log: log["context"].pop("job_id"))
                else:
                    self.reseal(blocked, lambda log: log.update(action_id="other-action"))
                self.assertIsNone(execution_log(blocked))
                self.assertEqual(verify_execution(blocked), "BLOCKED")
