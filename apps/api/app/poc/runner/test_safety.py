"""Runner safety regressions; every transport is mocked and no attack is delivered."""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from unittest.mock import Mock
from urllib.error import HTTPError

import pytest
import yaml

from cr_contracts import iter_errors_shape
from app import config
from app.poc.runner import guard, payloads, runner
from app.poc.runner.models import ExecutionRequest


def request(**kwargs):
    proof = payloads.KNOWN_POC_PROOFS[payloads.STRUTS_S2045_PROOF_ID]
    return ExecutionRequest("a1", "runner-safety", "web", proof["source_url"], {},
                            proof["sha256"], proof["exec_method"], proof["payload"],
                            proof["expected_marker"], proof_id=payloads.STRUTS_S2045_PROOF_ID,
                            **kwargs)


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(runner.scenario_store, "get", lambda sid: {"id": sid, "ir_version": 3})
    monkeypatch.setattr(runner.poc_store, "_DB", tmp_path / "poc.db")
    monkeypatch.setattr("subprocess.run", Mock(side_effect=AssertionError("no real subprocess")))
    monkeypatch.setattr("urllib.request.urlopen", Mock(side_effect=AssertionError("no real HTTP")))
    monkeypatch.setattr(runner.manager, "_pve_guest_exec", Mock(side_effect=AssertionError("no real PVE")))


@pytest.mark.parametrize("backend", ["local-docker", "proxmox"])
@pytest.mark.parametrize("cancelled", [False, True])
def test_unavailable_cancellable_transport_never_starts_a_helper(monkeypatch, backend, cancelled):
    monkeypatch.setattr(runner.manager, "deploy_backend", lambda: backend)
    start = Mock(side_effect=AssertionError("unsafe synchronous transport invoked"))
    monkeypatch.setattr(runner.manager, "probe_in_service", start)
    cancellation = threading.Event()
    if cancelled:
        cancellation.set()
    before = set(threading.enumerate())
    req = request(cancel=cancellation)
    result, _ = runner._probe_with_cancel(req, req.payload, 2)
    assert result["returncode"] in {125, 127}
    start.assert_not_called()
    assert set(threading.enumerate()) == before
    if backend == "local-docker":
        assert "D6" in result["stderr"]
    elif not cancelled:
        assert "guaranteed-cancel" in result["stderr"]


@pytest.mark.parametrize("stdout,stderr,code", [
    ("REQUEST_ERROR=HTTPError:HTTP Error 500: VULHUB_HEADER=54289", "", 0),
    ("REQUEST_ERROR=HTTPError\nVULHUB_HEADER=54289", "", 0),
    ("VULHUB_HEADER=54289\nREQUEST_ERROR=HTTPError", "", 0),
    ("prefix VULHUB_HEADER=54289", "", 0),
    ("", "VULHUB_HEADER=54289", 0),
    ("VULHUB_HEADER=54289", "REQUEST_ERROR=HTTPError", 0),
    ("VULHUB_HEADER=54289", "", 1),
])
def test_error_or_incidental_marker_never_proves_effect(monkeypatch, stdout, stderr, code):
    monkeypatch.setattr(runner, "assert_target_owned", lambda *args: {"service_ref": "web"})
    monkeypatch.setattr(runner, "_probe_with_cancel", lambda *args: (
        {"returncode": code, "stdout": stdout, "stderr": stderr}, None))
    result = runner.SandboxRunner().execute(request())
    assert result.status == "FAIL"
    assert not result.stages.vuln_behavior
    assert not any(item.kind == "exploit_effect" for item in result.evidence)


@pytest.mark.parametrize("status,header", [(200, "54289"), (200, None), (500, "54289"),
                                          (200, "54289\nVULHUB_HEADER=54289")])
def test_pinned_response_protocol_checks_status_and_exact_header(monkeypatch, capsys, status, header):
    # The pinned Python program is evaluated only with a fully mocked urlopen;
    # no HTTP request, container, or exploit transport can run in this unit test.
    response = Mock(status=status, headers={"vulhub": header})
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    monkeypatch.setattr("urllib.request.urlopen", Mock(return_value=response))
    exec(compile(payloads.STRUTS_S2045_PAYLOAD, "<mocked-payload>", "exec"), {})
    output = capsys.readouterr()
    assert (output.out.strip() == payloads.STRUTS_S2045_MARKER) == (status == 200 and header == "54289")


def test_pinned_error_never_echoes_attacker_controlled_reason(monkeypatch, capsys):
    error = HTTPError("http://127.0.0.1:8080/", 500,
                      "\n" + payloads.STRUTS_S2045_MARKER, {}, None)
    monkeypatch.setattr("urllib.request.urlopen", Mock(side_effect=error))
    with pytest.raises(SystemExit) as exc:
        exec(compile(payloads.STRUTS_S2045_PAYLOAD, "<mocked-payload>", "exec"), {})
    assert exc.value.code == 1
    assert payloads.STRUTS_S2045_MARKER not in capsys.readouterr().out


def test_reruns_keep_evidence_and_bind_hashed_context(monkeypatch):
    owned = {"service_ref": "web", "deployment_record_id": 17, "container_id": "b" * 64}
    monkeypatch.setattr(runner, "assert_target_owned", lambda *args: owned)
    monkeypatch.setattr(runner, "_probe_with_cancel", lambda *args: (
        {"returncode": 0, "stdout": payloads.STRUTS_S2045_MARKER, "stderr": ""}, None))
    first = runner.SandboxRunner().execute(request(job_id="job-one"))
    original = {item.path: (config.DATA_DIR / item.path).read_bytes() for item in first.evidence}
    second = runner.SandboxRunner().execute(request(job_id="job-two"))
    assert first.status == second.status == "PASS"
    assert {item.path for item in first.evidence}.isdisjoint(item.path for item in second.evidence)
    for item in first.evidence:
        data = (config.DATA_DIR / item.path).read_bytes()
        assert data == original[item.path]
        assert hashlib.sha256(data).hexdigest() == item.sha256
    log = json.loads((config.DATA_DIR / first.logs_path).read_text())
    context = log["context"]
    ir = {"id": "runner-safety", "ir_version": 3}
    expected_hash = hashlib.sha256(json.dumps(ir, sort_keys=True, separators=(",", ":"),
                                             ensure_ascii=False).encode()).hexdigest()
    assert context["scenario_sha256"] == expected_hash
    assert context["deployment_record_id"] == 17
    assert context["job_id"] == "job-one"
    assert context["action_id"] == first.action_id
    assert context["payload_sha256"] == first.payload_sha256
    assert context["run_id"] in first.logs_path


@pytest.mark.parametrize("allowed", [False, True])
def test_batch_api_and_persistence_omit_optional_nulls(monkeypatch, allowed):
    if allowed:
        monkeypatch.setattr(runner, "assert_target_owned", lambda *args: {"service_ref": "web"})
        monkeypatch.setattr(runner, "_probe_with_cancel", lambda *args: (
            {"returncode": 0, "stdout": payloads.STRUTS_S2045_MARKER, "stderr": ""}, None))
    else:
        def deny(*args):
            raise guard.TargetBlocked("not owned")
        monkeypatch.setattr(runner, "assert_target_owned", deny)
    results = runner.run_job("runner-safety", [request()])
    result = results[0]
    assert not iter_errors_shape("ExecutionResult", result)
    if allowed:
        assert "failure_reason" not in result
    else:
        assert "exit_code" not in result
    assert runner.poc_store.get_runs("runner-safety")[0] == result


@pytest.mark.parametrize("code", [124, 125, 127])
def test_transport_safety_errors_preserve_blocked_without_confirmed_delivery(monkeypatch, code):
    monkeypatch.setattr(runner, "assert_target_owned", lambda *args: {"service_ref": "web"})
    monkeypatch.setattr(runner, "_probe_with_cancel", lambda *args: (
        {"returncode": code, "stdout": "", "stderr": "transport failed"}, "no helper started"))
    result = runner.SandboxRunner().execute(request())
    assert result.status == "BLOCKED"
    assert not result.stages.delivered and not result.stages.responded


def network_fixture(monkeypatch, names, invalid=None):
    sid, project = "runner-safety", "cr-demo-runner-safety"
    monkeypatch.setattr(guard, "get_generated", lambda *args: {"compose": yaml.safe_dump({
        "services": {"web": {"container_name": f"{project}-web", "networks": ["lab", "second", "edge"]}}})})
    monkeypatch.setattr(runner.manager, "deploy_backend", lambda: "local-docker")
    monkeypatch.setattr(runner.manager, "records", lambda *args, **kwargs: [{
        "id": 17, "action": "up", "state": "running", "details": {
            "backend": "local-docker", "host_isolation": {"isolated": True}}}])
    info = {"Id": "b" * 64, "State": {"Running": True}, "Config": {"Labels": {
        "com.docker.compose.project": project, "com.docker.compose.service": "web"}},
        "NetworkSettings": {"Networks": {name: {} for name in names}}}
    def inspect(args):
        if args[0] == "inspect":
            return [info]
        return [{"Internal": args[-1] != invalid, "Options": {
            "com.docker.network.bridge.gateway_mode_ipv4": "isolated"}, "Containers": {"b" * 64: {}}}]
    monkeypatch.setattr(guard, "_docker_json", inspect)
    return sid, project


@pytest.mark.parametrize("extra", ["external", "cr-demo-runner-safety-edge", "bridge"])
def test_any_additional_non_lab_attachment_blocks(monkeypatch, extra):
    sid, _ = network_fixture(monkeypatch, ["cr-demo-runner-safety-lab", extra])
    with pytest.raises(guard.TargetBlocked):
        guard.assert_target_owned(sid, "web")


def test_second_declared_network_must_also_be_isolated(monkeypatch):
    sid, _ = network_fixture(monkeypatch, ["cr-demo-runner-safety-lab", "cr-demo-runner-safety-second"],
                             invalid="cr-demo-runner-safety-second")
    with pytest.raises(guard.TargetBlocked):
        guard.assert_target_owned(sid, "web")


def test_all_isolated_declared_networks_are_accepted(monkeypatch):
    names = ["cr-demo-runner-safety-lab", "cr-demo-runner-safety-second"]
    sid, _ = network_fixture(monkeypatch, names)
    assert guard.assert_target_owned(sid, "web")["networks"] == names


def test_cleanup_removes_all_verified_same_action_helpers(monkeypatch):
    req = request()
    target, one, two, unrelated = (char * 64 for char in "abcd")
    removed = []
    def command(scenario_id, args, timeout):
        if args[:2] == ["inspect", "-f"]:
            return {"returncode": 0, "stdout": target}
        if args[0] == "ps":
            return {"returncode": 0, "stdout": "\n".join([one, two, unrelated])}
        if args[0] == "inspect":
            info = {"Id": args[1], "Created": datetime.now(timezone.utc).isoformat(),
                    "Config": {"Image": runner._HELPER_IMAGE, "User": "65532:65532",
                               "Cmd": ["python", "-c", req.payload]},
                    "HostConfig": {"ReadonlyRootfs": True, "CapDrop": ["ALL"],
                                   "NetworkMode": f"container:{target}"}}
            if args[1] == unrelated:
                info["HostConfig"]["NetworkMode"] = "container:someone-else"
            return {"returncode": 0, "stdout": json.dumps([info])}
        if args[:2] == ["rm", "-f"]:
            removed.append(args[2])
            return {"returncode": 0}
        raise AssertionError(args)
    monkeypatch.setattr(runner, "_command_result", command)
    note = runner._cleanup_probe(req.scenario_id, req.service_ref, req.payload, 0)
    assert removed == [one, two]
    assert "removed" in note
