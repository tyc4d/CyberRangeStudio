"""Polling and cancellation interface over poc_jobs/poc_runs storage."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from app import config
from app.poc import store as poc_store
from app.poc.runner import cancel_execution, execution_status


def test_status_and_cancel_use_latest_scenario_execution_job(tmp_path: Path) -> None:
    db_path = tmp_path / "poc.db"
    job_id = "job-m9-status"
    sid = "m9-status-job"
    stages = {"started": True, "delivered": False, "responded": False,
              "vuln_behavior": False, "state_change": False, "action_complete": False}
    with patch.object(poc_store, "_DB", db_path), patch.object(config, "DATA_DIR", tmp_path):
        poc_store.init()
        poc_store.create_job(job_id, sid, "execute", timeout_s=120)
        poc_store.set_job_state(job_id, "running", json.dumps({"current_action_id": "a1", "stages": stages}))

        status = execution_status(sid)
        assert status["job_state"] == "running"
        assert status["per_action"] == [{"action_id": "a1", "stages": stages}]
        assert "logs_tail" in status

        cancelled = cancel_execution(sid)
        assert cancelled == {"cancelled": True, "joined": True,
                             "uncertain": False, "operations": 0}
        assert poc_store.is_cancelled(job_id) is True

        poc_store.set_job_state(job_id, "done")
        assert cancel_execution(sid)["cancelled"] is False
