"""Runner safety regressions; every transport is mocked and no attack is delivered."""
from __future__ import annotations

import hashlib
import json
import threading
from unittest.mock import Mock
from urllib.error import HTTPError

import pytest
import yaml

from cr_contracts import iter_errors_shape
from app import config
from app.poc.runner import guard, payloads, runner
from app.poc.runner.models import ExecutionRequest

TEST_VMID = 900100
TEST_HOST = "worker"
TEST_GENERATION = "a" * 32


def pinned_reservation(_scenario_id, _service_id, operation_id, job_id, _worker_identity):
    return {"state": "reserved", "resource_absent": True, "operation_id": operation_id,
            "vmid": TEST_VMID, "host_id": TEST_HOST, "generation_id": TEST_GENERATION,
            "job_id": job_id}


def pinned_worker_identity(_scenario_id):
    return {"vmid": TEST_VMID, "host_id": TEST_HOST, "generation_id": TEST_GENERATION}


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
    monkeypatch.setattr(runner.manager, "probe_worker_identity", pinned_worker_identity)


@pytest.mark.parametrize("backend", ["local-docker", "proxmox"])
@pytest.mark.parametrize("cancelled", [False, True])
def test_poc_transport_uses_pve_supervisor_and_keeps_local_d6_block(monkeypatch, backend, cancelled):
    monkeypatch.setattr(runner.manager, "deploy_backend", lambda: backend)
    monkeypatch.setattr(runner.manager, "reserve_probe_operation", Mock(side_effect=pinned_reservation))
    start = Mock(return_value={"state": "running", "resource_absent": False})
    wait = Mock(return_value={"state": "completed", "resource_absent": True,
                              "exitcode": 0, "stdout": payloads.STRUTS_S2045_MARKER, "stderr": ""})
    monkeypatch.setattr(runner.manager, "start_probe_operation", start)
    monkeypatch.setattr(runner.manager, "wait_probe_operation", wait)
    monkeypatch.setattr(runner.manager, "cancel_probe_operation",
                        Mock(return_value={"state": "cancelled", "resource_absent": True}))
    monkeypatch.setattr(runner.manager, "probe_in_service", start)
    cancellation = threading.Event()
    if cancelled:
        cancellation.set()
    req = request(cancel=cancellation)
    result, _ = runner._probe_with_cancel(req, req.payload, 2)
    if backend == "local-docker":
        assert result["returncode"] == 127
        assert "D6" in result["stderr"]
        start.assert_not_called()
    elif cancelled:
        assert result["returncode"] == 125
        start.assert_not_called()
    else:
        assert result["returncode"] == 0
        start.assert_called_once()
        wait.assert_called_once()


def test_cancel_during_wait_stops_and_joins_the_registered_operation(monkeypatch):
    monkeypatch.setattr(runner.manager, "deploy_backend", lambda: "proxmox")
    monkeypatch.setattr(runner.manager, "reserve_probe_operation", Mock(side_effect=pinned_reservation))
    cancellation = threading.Event()
    monkeypatch.setattr(runner.manager, "start_probe_operation", Mock(return_value={
        "state": "running", "resource_absent": False}))

    def wait(*args, **kwargs):
        cancellation.set()
        return {"state": "running", "resource_absent": False}

    cancel = Mock(return_value={"state": "cancelled", "resource_absent": True})
    monkeypatch.setattr(runner.manager, "wait_probe_operation", wait)
    monkeypatch.setattr(runner.manager, "cancel_probe_operation", cancel)
    monkeypatch.setattr(runner.manager, "join_probe_operation",
                        Mock(side_effect=AssertionError("terminal cancel result is already joined")))

    result, note = runner._probe_with_cancel(request(cancel=cancellation), request().payload, 10)

    assert result["returncode"] == 125
    assert "helper is absent" in note
    cancel.assert_called_once()


def test_uncertain_transport_keeps_operation_id_for_later_reconciliation(monkeypatch):
    job_id = "a" * 32
    runner.poc_store.create_job(job_id, "runner-safety", "execute", worker_identity=pinned_worker_identity("runner-safety"))
    runner.poc_store.set_job_state(job_id, "running")
    monkeypatch.setattr(runner.manager, "deploy_backend", lambda: "proxmox")
    monkeypatch.setattr(runner.manager, "reserve_probe_operation", Mock(side_effect=pinned_reservation))
    uncertain = {"state": "uncertain", "resource_absent": False}
    monkeypatch.setattr(runner.manager, "start_probe_operation", Mock(return_value=uncertain))
    monkeypatch.setattr(runner.manager, "wait_probe_operation", Mock(return_value=uncertain))
    monkeypatch.setattr(runner.manager, "cancel_probe_operation", Mock(return_value=uncertain))
    monkeypatch.setattr(runner.manager, "join_probe_operation", Mock(return_value=uncertain))

    result, note = runner._probe_with_cancel(request(job_id=job_id), request().payload, 10)

    assert result["state"] == "uncertain"
    assert "down and reuse remain blocked" in note
    operation = runner.poc_store.get_job_operation(job_id)
    assert operation and len(operation["operation_id"]) == 32


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
    first = runner.SandboxRunner().execute(request(job_id="1" * 32))
    original = {item.path: (config.DATA_DIR / item.path).read_bytes() for item in first.evidence}
    second = runner.SandboxRunner().execute(request(job_id="2" * 32))
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
    assert context["job_id"] == "1" * 32
    assert log["action_id"] == first.action_id
    assert log["payload_sha256"] == first.payload_sha256
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


def test_pve_supervisor_result_requires_absence_for_terminal_state():
    assert runner._operation_result({"state": "completed", "resource_absent": False,
                                     "exitcode": 0}) is None
    assert runner._operation_result({"state": "completed", "resource_absent": True,
                                     "exitcode": 0})["returncode"] == 0


def test_cancel_endpoint_cancels_and_joins_persisted_guest_operation(monkeypatch):
    job_id, operation_id = "1" * 32, "d" * 32
    runner.poc_store.create_job(job_id, "runner-safety", "execute", worker_identity=pinned_worker_identity("runner-safety"))
    runner.poc_store.set_job_state(job_id, "running")
    assert runner.poc_store.register_job_operation(
        job_id, operation_id, "web", "a1", TEST_VMID, TEST_HOST, TEST_GENERATION)
    cancel = Mock(return_value={"state": "cancelled", "resource_absent": True})
    join = Mock(return_value={"state": "cancelled", "resource_absent": True})
    monkeypatch.setattr(runner.manager, "cancel_probe_operation", cancel)
    monkeypatch.setattr(runner.manager, "join_probe_operation", join)
    monkeypatch.setattr(runner.manager, "active_probe_operations", Mock(return_value=[]))

    response = runner.cancel_execution("runner-safety")

    assert response == {"cancelled": True, "joined": True, "uncertain": False, "operations": 1}
    cancel.assert_called_once_with("runner-safety", operation_id, "web", TEST_VMID, TEST_HOST,
                                   TEST_GENERATION, job_id)
    join.assert_not_called()
    assert runner.poc_store.get_job_operation(job_id) is None
    assert runner.poc_store.get_job(job_id)["state"] == "cancelled"


def test_uncertain_cancel_keeps_job_operation_registered_and_active(monkeypatch):
    job_id, operation_id = "2" * 32, "e" * 32
    runner.poc_store.create_job(job_id, "runner-safety", "execute", worker_identity=pinned_worker_identity("runner-safety"))
    runner.poc_store.set_job_state(job_id, "running")
    assert runner.poc_store.register_job_operation(
        job_id, operation_id, "web", "a1", TEST_VMID, TEST_HOST, TEST_GENERATION)
    uncertain = {"state": "uncertain", "resource_absent": False}
    monkeypatch.setattr(runner.manager, "cancel_probe_operation", Mock(return_value=uncertain))
    monkeypatch.setattr(runner.manager, "join_probe_operation", Mock(return_value=uncertain))
    monkeypatch.setattr(runner.manager, "active_probe_operations", Mock(return_value=[]))

    response = runner.cancel_execution("runner-safety")

    assert response == {"cancelled": True, "joined": False, "uncertain": True, "operations": 1}
    assert runner.poc_store.get_job_operation(job_id)["operation_id"] == operation_id
    assert runner.poc_store.get_job(job_id)["state"] == "running"


def test_cancel_flag_allows_binding_a_pre_reserved_operation_for_cleanup():
    job_id = "3" * 32
    runner.poc_store.create_job(job_id, "runner-safety", "execute", worker_identity=pinned_worker_identity("runner-safety"))
    runner.poc_store.set_job_state(job_id, "running")
    runner.poc_store.request_cancel(job_id)

    assert not runner.poc_store.register_job_operation(
        job_id, "f" * 32, "web", "a1", TEST_VMID, TEST_HOST, "b" * 32)
    assert runner.poc_store.register_job_operation(
        job_id, "f" * 32, "web", "a1", TEST_VMID, TEST_HOST, TEST_GENERATION)
    assert runner.poc_store.get_job_operation(job_id)["generation_id"] == TEST_GENERATION


def test_error_job_with_unresolved_operation_remains_cancellable(monkeypatch):
    job_id, operation_id = "4" * 32, "5" * 32
    runner.poc_store.create_job(job_id, "runner-safety", "execute", worker_identity=pinned_worker_identity("runner-safety"))
    runner.poc_store.set_job_state(job_id, "running")
    assert runner.poc_store.register_job_operation(
        job_id, operation_id, "web", "a1", TEST_VMID, TEST_HOST, TEST_GENERATION)
    runner.poc_store.set_job_state(job_id, "error", "execution worker failed after launch")
    cancel = Mock(return_value={"state": "cancelled", "resource_absent": True})
    monkeypatch.setattr(runner.manager, "cancel_probe_operation", cancel)
    monkeypatch.setattr(runner.manager, "join_probe_operation", Mock(side_effect=AssertionError("already joined")))
    monkeypatch.setattr(runner.manager, "active_probe_operations", Mock(return_value=[]))

    response = runner.cancel_execution("runner-safety")

    assert response == {"cancelled": True, "joined": True, "uncertain": False, "operations": 1}
    cancel.assert_called_once_with("runner-safety", operation_id, "web", TEST_VMID, TEST_HOST,
                                   TEST_GENERATION, job_id)
    assert runner.poc_store.get_job_operation(job_id) is None
    assert runner.poc_store.get_job(job_id)["state"] == "cancelled"
