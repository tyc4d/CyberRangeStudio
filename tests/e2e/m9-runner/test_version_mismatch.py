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
         patch("app.poc.runner.runner.manager.probe_in_service",
               return_value={"returncode": 0, "stdout": "VULHUB_HEADER=None", "stderr": ""}):
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
        return {"returncode": 124, "stdout": "", "stderr": "timed out"}

    timer = threading.Timer(0.1, request.cancel.set)
    with patch("app.poc.runner.runner.manager.probe_in_service", side_effect=wait_for_cancel) as probe, \
         patch("app.poc.runner.runner._cleanup_probe", return_value="timed-out sandbox helper removed") as cleanup:
        timer.start()
        result, cleanup_note = _probe_with_cancel(request, payload, timeout=2)
    assert result["returncode"] == 125
    assert "removed" in cleanup_note
    probe.assert_called_once()
    cleanup.assert_called_once()
