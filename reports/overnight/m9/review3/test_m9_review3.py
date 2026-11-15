"""Round-3 independent probes. Synthetic data, real SQLite/artifacts, mocked delivery only.

Run from apps/api with the worktree contracts and -p no:cacheprovider.
No product file or older assertion is changed. Failures remain ordinary failures.
"""
from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
from unittest.mock import Mock
import zipfile

import pytest

from app import config
from app.deploy import manager
from app.deploy.backends import local_docker
from app.poc import service, store
from app.poc.chain import evidence, validation
from app.poc.export import bundle as B
from app.poc.runner import guard, runner

spec = importlib.util.spec_from_file_location(
    "m9_round2_fixture_helpers", Path(__file__).parents[1] / "review2/test_m9_review2.py")
r2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r2)
r1 = r2.legacy
SID, MARKER = r2.SID, r2.MARKER
lab = r2.lab


@pytest.fixture(autouse=True)
def no_external_execution(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Round-3 QA forbids subprocesses, HTTP, deployment and real delivery")
    for target in ("subprocess.run", "subprocess.Popen", "urllib.request.urlopen"):
        monkeypatch.setattr(target, forbidden)
    monkeypatch.setattr(manager, "_pve_guest_exec", forbidden)
    monkeypatch.setattr(manager, "probe_in_service", forbidden)


def three_actions(ir):
    r2.add_second(ir)
    ir["actions"].append({**ir["actions"][0], "id": "a3"})


def assert_one_job(runs):
    logs = [evidence.execution_log(r) for r in runs]
    assert all(log is not None for log in logs)
    assert len({log["context"]["job_id"] for log in logs}) == 1


@pytest.mark.parametrize("code", [1, 127])
def test_fail_blocked_plus_independent_sibling_keeps_entire_job(lab, code):
    ir, _, transport = lab
    three_actions(ir)
    transport.side_effect = [({"returncode": code, "stdout": "no effect", "stderr": ""}, None),
                             ({"returncode": 0, "stdout": MARKER, "stderr": ""}, None)]
    runs = service.execute(SID)
    want = ["FAIL" if code == 1 else "BLOCKED", "BLOCKED", "PASS"]
    assert [r["status"] for r in runs] == want
    assert_one_job(runs)
    assert transport.call_count == 2
    assert store.get_runs(SID) == runs
    result = service.chain(SID)
    assert [p["status"] for p in result["per_action"]] == want
    assert not result["passes"] and not result["objective_reached"]


@pytest.mark.parametrize("code", [1, 127])
def test_fail_blocked_newest_job_never_resurrects_previous_successes(lab, code):
    ir, _, transport = lab
    r2.add_second(ir)
    prior = service.execute(SID)
    assert all(evidence.verify_execution(r) == "PASS" for r in prior)
    transport.reset_mock()
    transport.side_effect = [({"returncode": code, "stdout": "no effect", "stderr": ""}, None)]
    current = service.execute(SID)
    assert_one_job(current)
    assert transport.call_count == 1
    expected = ["FAIL" if code == 1 else "BLOCKED", "BLOCKED"]
    assert [p["status"] for p in service.chain(SID)["per_action"]] == expected
    f = service.report(SID)["fidelity"]
    assert f["reproduced"] == []


def test_ownership_block_with_no_ownership_log_keeps_independent_sibling(lab, monkeypatch):
    ir, _, transport = lab
    three_actions(ir)
    original = runner.assert_target_owned
    n = 0
    def inspect(sid, target):
        nonlocal n
        n += 1
        if n == 1:
            raise guard.TargetBlocked("synthetic first target not owned")
        return original(sid, target)
    monkeypatch.setattr(runner, "assert_target_owned", inspect)
    runs = service.execute(SID)
    assert [r["status"] for r in runs] == ["BLOCKED", "BLOCKED", "PASS"]
    assert_one_job(runs)
    assert n == 2 and transport.call_count == 1
    assert [p["status"] for p in service.chain(SID)["per_action"]] == ["BLOCKED", "BLOCKED", "PASS"]


@pytest.mark.parametrize("shape", ["self", "cycle", "missing", "diamond-missing", "prior-job"])
def test_topology_and_missing_predecessors_cannot_manufacture_pass(lab, shape):
    ir, _, transport = lab
    three_actions(ir)
    if shape == "prior-job":
        service.execute(SID, ["a1"])
        transport.reset_mock()
    pairs = {
        "self": [("a2", "a2")], "cycle": [("a1", "a2"), ("a2", "a1")],
        "missing": [("absent", "a2")],
        "diamond-missing": [("a1", "a3"), ("a2", "a3")],
        "prior-job": [("a1", "a2")],
    }[shape]
    ir["relations"] = [{"kind": "dependency", "from_action": a, "to_action": b} for a, b in pairs]
    selected = (["a1", "a3"] if shape == "diamond-missing"
                else ["a1", "a2"] if shape == "cycle" else ["a2"])
    runs = service.execute(SID, selected)
    assert_one_job(runs)
    dependent = "a3" if shape == "diamond-missing" else "a2"
    assert next(r for r in runs if r["action_id"] == dependent)["status"] == "BLOCKED"
    assert transport.call_count == (1 if shape == "diamond-missing" else 0)


def test_reverse_ir_order_is_topologically_executed_without_inventing_temporal_dependency(lab):
    ir, _, transport = lab
    three_actions(ir)
    ir["relations"].append({"kind": "temporal", "from_action": "a2", "to_action": "a3"})
    ir["actions"].reverse()
    runs = service.execute(SID)
    assert [r["action_id"] for r in runs] == ["a3", "a1", "a2"]
    assert [r["status"] for r in runs] == ["PASS"] * 3
    assert transport.call_count == 3
    assert_one_job(runs)
    assert service.chain(SID)["passes"] is False


@pytest.mark.parametrize("backend", ["local-docker", "proxmox", "unknown-backend"])
def test_public_batch_with_real_wrapper_never_launches_even_when_guard_accepts(lab, monkeypatch, backend):
    ir, _, _ = lab
    three_actions(ir)
    monkeypatch.setattr(runner, "_probe_with_cancel", ORIGINAL_PROBE)
    monkeypatch.setattr(manager, "deploy_backend", lambda: backend)
    launch = Mock(side_effect=AssertionError("no real helper is permitted"))
    monkeypatch.setattr(manager, "probe_in_service", launch)
    runs = service.execute(SID)
    assert [r["status"] for r in runs] == ["BLOCKED"] * 3
    assert_one_job(runs)
    launch.assert_not_called()
    assert all(not r["stages"][key] for r in runs for key in ("delivered", "responded", "vuln_behavior", "state_change"))
    assert not any(e["kind"] != "log" for r in runs for e in r["evidence"])


ORIGINAL_PROBE = runner._probe_with_cancel


@pytest.mark.parametrize("count", [2, 4])
def test_cancel_covers_all_remaining_independent_actions_in_one_job(lab, count):
    ir, _, transport = lab
    for n in range(2, count + 1):
        ir["actions"].append({**ir["actions"][0], "id": f"a{n}"})
    def cancelled(req, *args):
        assert runner.cancel_execution(SID) == {"cancelled": True}
        return {"returncode": 125, "stdout": "", "stderr": ""}, None
    transport.side_effect = cancelled
    runs = service.execute(SID)
    assert len(runs) == transport.call_count == 1
    assert runs[0]["status"] == "BLOCKED"
    job = evidence.execution_log(runs[0])["context"]["job_id"]
    assert store.get_job(job)["state"] == "cancelled"
    assert len(store.get_runs(SID)) == 1


def test_local_benign_helper_really_constructs_all_resource_caps(monkeypatch):
    monkeypatch.setattr(local_docker, "vulnerable_hosts", lambda *a: [])
    monkeypatch.setattr(local_docker, "_docker_context_preflight", lambda: ("docker", None))
    monkeypatch.setattr(local_docker, "_compose_prefix", lambda *a: (["docker", "compose"], None))
    run = Mock(return_value={"returncode": 0, "stdout": "", "stderr": ""})
    monkeypatch.setattr(local_docker, "_run", run)
    local_docker.probe_in_service(SID, "web", "print('benign synthetic QA')")
    args = run.call_args.args[0]
    for flag, value in (("--memory", "256m"), ("--cpus", "1"), ("--pids-limit", "128")):
        assert args[args.index(flag) + 1] == value


def test_status_must_not_mix_overlapping_jobs(lab):
    ir, _, transport = lab
    r2.add_second(ir, None)
    nested = []
    def interleaved(req, *args):
        if req.action_id == "a1":
            nested.extend(service.execute(SID, ["a2"]))
        return {"returncode": 0, "stdout": MARKER, "stderr": ""}, None
    transport.side_effect = interleaved
    first = service.execute(SID, ["a1"])
    assert all(evidence.verify_execution(r) == "PASS" for r in first + nested)
    status = runner.execution_status(SID)
    # Job a2 is newer, but job a1 completes/saves after it.
    assert [a["action_id"] for a in status["per_action"]] == ["a2"], status


def test_completed_newer_job_cannot_hide_an_older_still_running_job_from_cancel(lab):
    ir, _, transport = lab
    r2.add_second(ir, None)
    cancels = []
    active = []
    def interleaved(req, *args):
        if req.action_id == "a1":
            service.execute(SID, ["a2"])
            # a1's job is still running here, while a2's newer job is done.
            active.append(store.get_job(req.job_id)["state"])
            cancels.append(runner.cancel_execution(SID))
        return {"returncode": 0, "stdout": MARKER, "stderr": ""}, None
    transport.side_effect = interleaved
    service.execute(SID, ["a1"])
    assert active == ["running"]
    assert cancels == [{"cancelled": True}], cancels


SECRET = "round3-synthetic-credential-N627"
SECRET_CASES = {
    "quoted-password-single": {"description": "password='" + SECRET + "'"},
    "quoted-password-double": {"description": 'password="' + SECRET + '"'},
    "quoted-query-suffix": {"description": "https://example.invalid/?access_token=public'" + SECRET},
    "encoded-query-key": {"description": "https://example.invalid/?%61ccess_token=" + SECRET},
    "camelcase-secret-field": {"hosts": [{"id": "web", "clientSecret": SECRET}]},
    "secret-dictionary-key": {"hosts": [{"id": "web", "credentials": {SECRET: "[REDACTED]"}}]},
    # Positive controls must stay green: these formats were handled in older rounds.
    "plain-password-control": {"description": "password=" + SECRET},
    "url-control": {"description": "https://u:" + SECRET + "@example.invalid/"},
    "query-control": {"description": "https://example.invalid/?access_token=" + SECRET},
    "branch-control": {"hosts": [{"id": "web", "password": "${VALUE:+" + SECRET + "}"}]},
}


@pytest.mark.parametrize("kind", list(SECRET_CASES))
def test_fresh_bundle_secrets_are_removed_or_export_is_refused(monkeypatch, kind):
    try:
        data, manifest, zf = r1.build_in_memory_bundle(monkeypatch, **SECRET_CASES[kind])
    except B.ExportError:
        return
    leaks = [p for p in zf.namelist() if SECRET.encode() in zf.read(p)]
    assert not leaks, {"kind": kind, "files": leaks, "contains_secrets": manifest["contains_secrets"],
                       "verify_bundle": B.verify_bundle(data)}


@pytest.mark.parametrize("kind", ["quoted-password-single", "quoted-query-suffix", "encoded-query-key", "camelcase-secret-field", "secret-dictionary-key"])
def test_verify_bundle_independently_detects_unredacted_structured_secret(monkeypatch, kind):
    data, _, zf = r1.build_in_memory_bundle(monkeypatch)
    files = {p: zf.read(p) for p in zf.namelist()}
    obj = json.loads(files["scenario/scenario.json"])
    obj.update(SECRET_CASES[kind])
    files["scenario/scenario.json"] = json.dumps(obj).encode()
    manifest = json.loads(files["manifest.json"])
    for f in manifest["files"]:
        if f["path"] == "scenario/scenario.json":
            f["sha256"] = B._sha256(files[f["path"]])
    files["manifest.json"] = json.dumps(manifest).encode()
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dest:
        for path, content in files.items():
            dest.writestr(path, content)
    errors = B.verify_bundle(out.getvalue())
    assert errors, {"kind": kind, "verify_bundle": errors}
