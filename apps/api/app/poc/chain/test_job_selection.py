"""Current job selection with real SQLite/artifacts and mocked payload delivery."""
from __future__ import annotations

import sqlite3
import uuid
from unittest.mock import patch

from cr_contracts import iter_errors, iter_errors_shape

from app.poc import store
from app.poc.chain.evidence import execution_log, verify_execution
from app.poc.chain.report import build_fidelity_report
from app.poc.chain.test_gated_batch import GatedBatchFixture
from app.poc.chain.validation import latest_execute_job, validate_chain
from app.poc.runner import payloads


class JobSelectionTests(GatedBatchFixture):
    def successful_batch(self):
        self.transport.return_value = ({"returncode": 0, "stdout": payloads.STRUTS_S2045_MARKER, "stderr": ""}, None)
        runs = self.run_batch()
        self.assertTrue(all(verify_execution(run) == "PASS" for run in runs))
        chain = validate_chain(self.sid, self.ir, self.plan, runs)
        self.assertEqual([p["status"] for p in chain["per_action"]], ["PASS", "PASS"])
        return runs, chain

    def empty_job(self, state, *, scenario_id=None, kind="execute"):
        job_id = uuid.uuid4().hex
        store.create_job(job_id, scenario_id or self.sid, kind)
        store.set_job_state(job_id, state)
        return job_id

    def assert_current_empty(self, history, stale_chain, job_id):
        chain = validate_chain(self.sid, self.ir, self.plan, history)
        self.assertEqual([p["status"] for p in chain["per_action"]], ["NOT_TESTED", "NOT_TESTED"])
        self.assertFalse(chain["passes"])
        self.assertEqual(iter_errors_shape("ChainValidation", chain), [])
        # A report caller may have a chain built before the new job existed.
        report = build_fidelity_report(self.sid, self.ir, self.plan, history, stale_chain)
        self.assertEqual(report["fidelity"]["reproduced"], [])
        self.assertEqual(report["fidelity"]["not_tested"], ["a1", "a2"])
        self.assertEqual(report["levels"]["full_chain"], "NOT_TESTED")
        self.assertEqual(iter_errors("validation-report", report), [])
        checks = [check for check in report["checks"] if check["id"].startswith("poc-")]
        self.assertTrue(all(check["status"] == "NOT_TESTED" and "evidence" not in check for check in checks))
        self.assertTrue(all(f"job_id={job_id}" in check["observed"] for check in checks))
        current = latest_execute_job(self.sid)
        self.assertEqual(current["id"], job_id)
        self.assertIn(f"job_state={current['state']}", checks[-1]["observed"])
        self.assertIn("created_at=", checks[-1]["observed"])
        self.assertIn("updated_at=", checks[-1]["observed"])
        return report

    def test_empty_current_job_never_reuses_verified_history_in_any_state(self):
        history, old_chain = self.successful_batch()
        for state in ("cancelled", "error", "pending", "running", "done"):
            with self.subTest(state=state):
                job_id = self.empty_job(state)
                self.assert_current_empty(history, old_chain, job_id)
                self.assertEqual(store.get_runs(self.sid), history)
                self.assertTrue(all(verify_execution(run) == "PASS" for run in history))

    def test_newest_execute_job_uses_creation_order_and_rowid_tiebreak(self):
        history, old_chain = self.successful_batch()
        current = self.empty_job("cancelled")
        # Updated/completion times, another scenario and a newer discovery job
        # must not change which execute job belongs to this report.
        self.empty_job("error", scenario_id="other-scenario")
        self.empty_job("done", kind="discover")
        db = store._conn()
        try:
            db.execute("UPDATE poc_jobs SET created_at=1 WHERE scenario_id=? AND kind='execute'", (self.sid,))
            db.execute("UPDATE poc_jobs SET updated_at=9999999999 WHERE id=?",
                       (execution_log(history[0])["context"]["job_id"],))
            db.commit()
        finally:
            db.close()
        self.assert_current_empty(history, old_chain, current)

    def test_old_overlapping_batch_finishing_last_cannot_become_current(self):
        newer = []

        def delivery(*args):
            if not newer:
                newer.append(self.empty_job("error"))
            return {"returncode": 0, "stdout": payloads.STRUTS_S2045_MARKER, "stderr": ""}, None

        self.transport.side_effect = delivery
        history = self.run_batch()
        self.assertTrue(all(verify_execution(run) == "PASS" for run in history))
        self.assertNotEqual(execution_log(history[-1])["context"]["job_id"], newer[0])
        stale_chain = {"passes": False, "objective_reached": False,
                       "per_action": [{"action_id": aid, "status": "PASS"} for aid in ("a1", "a2")]}
        self.assert_current_empty(history, stale_chain, newer[0])

    def test_current_job_without_verifiable_logs_does_not_fall_back(self):
        previous, old_chain = self.successful_batch()
        current = self.run_batch()
        current_job_id = execution_log(current[0])["context"]["job_id"]
        for run in current:
            (self.root / run["logs_path"]).unlink()
        history = store.get_runs(self.sid)
        self.assert_current_empty(history, old_chain, current_job_id)
        self.assertEqual(history[:2], previous)

    def test_job_read_failure_cannot_silently_restore_historical_passes(self):
        history, old_chain = self.successful_batch()
        with patch("app.poc.store._conn", side_effect=sqlite3.OperationalError("synthetic read failure")):
            with self.assertRaises(sqlite3.OperationalError):
                validate_chain(self.sid, self.ir, self.plan, history)
            with self.assertRaises(sqlite3.OperationalError):
                build_fidelity_report(self.sid, self.ir, self.plan, history, old_chain)
