"""A delivered Struts probe against a patched response never counts as PASS."""
from __future__ import annotations

import hashlib
from unittest.mock import patch

from app.poc.runner import ExecutionRequest, SandboxRunner
from app.poc.runner.payloads import (
    STRUTS_S2045_MARKER,
    STRUTS_S2045_PAYLOAD,
    STRUTS_S2045_PROOF_ID,
    STRUTS_S2045_SHA256,
    STRUTS_S2045_SOURCE,
)


def test_version_mismatch_response_is_not_pass() -> None:
    payload = STRUTS_S2045_PAYLOAD
    request = ExecutionRequest(
        action_id="a1",
        scenario_id="m9-version-mismatch",
        service_ref="web",
        source_url=STRUTS_S2045_SOURCE,
        ref={"release": "internal-payload-v1"},
        sha256=STRUTS_S2045_SHA256,
        exec_method="http_seq",
        payload=payload,
        expected_marker=STRUTS_S2045_MARKER,
        proof_id=STRUTS_S2045_PROOF_ID,
    )
    with patch("app.poc.runner.runner.assert_target_owned", return_value={"service_ref": "web"}), \
         patch("app.poc.runner.runner.manager.deploy_backend", return_value="proxmox"), \
         patch("app.poc.runner.runner.manager.start_probe_operation",
               return_value={"state": "running", "resource_absent": False}), \
         patch("app.poc.runner.runner.manager.wait_probe_operation",
               return_value={"state": "completed", "resource_absent": True,
                             "exitcode": 0, "stdout": "VULHUB_HEADER=None", "stderr": ""}):
        result = SandboxRunner().execute(request)
    assert result.status == "FAIL"
    assert result.status != "PASS"
    assert result.stages.delivered is True
    assert result.stages.responded is True
    assert result.stages.vuln_behavior is False


def test_http_200_marker_is_blocked_as_non_exploit_evidence() -> None:
    payload = "print('HTTP_STATUS=200')"
    request = ExecutionRequest(
        action_id="a1", scenario_id="m9-status-only", service_ref="web",
        source_url="local://cyberrange/test", ref={"release": "test"},
        sha256=hashlib.sha256(payload.encode()).hexdigest(), exec_method="http_seq",
        payload=payload, expected_marker="HTTP_STATUS=200",
    )
    with patch("app.poc.runner.runner.assert_target_owned", return_value={"service_ref": "web"}), \
         patch("app.poc.runner.runner.manager.probe_in_service") as probe:
        result = SandboxRunner().execute(request)
    assert result.status == "BLOCKED"
    probe.assert_not_called()


def test_payload_cannot_print_the_registered_success_marker_to_fake_pass() -> None:
    payload = "print('VULHUB_HEADER=54289')"
    request = ExecutionRequest(
        action_id="a1", scenario_id="m9-spoofed-effect", service_ref="web",
        source_url=STRUTS_S2045_SOURCE, ref={"release": "internal-payload-v1"},
        sha256=hashlib.sha256(payload.encode()).hexdigest(), exec_method="http_seq",
        payload=payload, expected_marker=STRUTS_S2045_MARKER, proof_id=STRUTS_S2045_PROOF_ID,
    )
    with patch("app.poc.runner.runner.assert_target_owned", return_value={"service_ref": "web"}), \
         patch("app.poc.runner.runner.manager.probe_in_service") as probe:
        result = SandboxRunner().execute(request)
    assert result.status == "BLOCKED"
    probe.assert_not_called()


def test_cancel_during_probe_requests_best_effort_helper_cleanup() -> None:
    import threading
    from app.poc.runner.runner import _probe_with_cancel

    payload = "print('would-run')"
    request = ExecutionRequest(
        action_id="a1", scenario_id="m9-cancel-test", service_ref="web",
        source_url="https://example.invalid/poc", ref={"release": "local-test"},
        sha256=hashlib.sha256(payload.encode()).hexdigest(), exec_method="http_seq",
        payload=payload, expected_marker="would-run", cancel=threading.Event(),
    )
    def wait_for_cancel(*_args, **_kwargs):
        request.cancel.wait(1)
        return {"state": "running", "resource_absent": False}

    timer = threading.Timer(0.1, request.cancel.set)
    with patch("app.poc.runner.runner.manager.deploy_backend", return_value="proxmox"), \
         patch("app.poc.runner.runner.manager.start_probe_operation",
               return_value={"state": "running", "resource_absent": False}) as start, \
         patch("app.poc.runner.runner.manager.wait_probe_operation", side_effect=wait_for_cancel) as wait, \
         patch("app.poc.runner.runner.manager.cancel_probe_operation",
               return_value={"state": "cancelled", "resource_absent": True}) as cancel, \
         patch("app.poc.runner.runner.manager.join_probe_operation",
               side_effect=AssertionError("cancel already confirmed terminal absence")):
        timer.start()
        result, cleanup_note = _probe_with_cancel(request, payload, timeout=2)
    assert result["returncode"] == 125
    assert "absent" in cleanup_note
    start.assert_called_once()
    wait.assert_called_once()
    cancel.assert_called_once()
