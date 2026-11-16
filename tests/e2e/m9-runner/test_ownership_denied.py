"""Fail-closed runner acceptance: unowned targets receive no execution attempt."""
from __future__ import annotations

import hashlib
from unittest.mock import patch

from app.poc.runner import ExecutionRequest, SandboxRunner
from app.poc.runner.guard import TargetBlocked


def test_unowned_target_is_blocked_without_calling_sandbox() -> None:
    payload = "print('must-not-run')"
    request = ExecutionRequest(
        action_id="a1",
        scenario_id="m9-unowned-test",
        service_ref="web",
        source_url="https://github.com/example/poc",
        ref={"commit_sha": "a" * 40},
        sha256=hashlib.sha256(payload.encode()).hexdigest(),
        exec_method="python",
        payload=payload,
        expected_marker="must-not-run",
    )
    with patch("app.poc.runner.runner.assert_target_owned", side_effect=TargetBlocked("not owned")), \
         patch("app.poc.runner.runner.manager.start_probe_operation") as start:
        result = SandboxRunner().execute(request)
    assert result.status == "BLOCKED"
    assert result.target_ownership_verified is False
    assert result.stages.started is False
    assert result.stages.delivered is False
    start.assert_not_called()
