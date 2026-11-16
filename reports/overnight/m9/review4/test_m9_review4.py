"""Final-gate independent QA. All inputs synthetic; no subprocess/HTTP/deploy.

Uses unchanged older fixture constructors, real runner/artifacts/SQLite/verifiers.
Ordinary failures are evidence; no xfail and no product edits.
"""
from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import io
import json
from pathlib import Path
import threading
from urllib.parse import quote
from unittest.mock import Mock
import zipfile

import pytest

from app import config
from app.deploy import manager
from app.poc import service, store
from app.poc.chain import evidence
from app.poc.export import bundle as B
from app.poc.runner import runner

spec = importlib.util.spec_from_file_location(
    "round4_older_helpers", Path(__file__).parents[1] / "review2/test_m9_review2.py")
r2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r2)
r1 = r2.legacy
SID, MARKER, lab = r2.SID, r2.MARKER, r2.lab
ORIGINAL_PROBE = runner._probe_with_cancel
SECRET = "round4-synthetic-credential-K842"
BASIC = base64.b64encode(("qa-user:" + SECRET).encode()).decode()


@pytest.fixture(autouse=True)
def no_external_execution(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Round-4 forbids real process, HTTP, PVE and attack execution")
    for target in ("subprocess.run", "subprocess.Popen", "urllib.request.urlopen"):
        monkeypatch.setattr(target, forbidden)
    monkeypatch.setattr(manager, "_pve_guest_exec", forbidden)
    monkeypatch.setattr(manager, "probe_in_service", forbidden)


CASES = {
    "json-quoted-key": {"description": json.dumps({"password": SECRET})},
    "single-quoted-key": {"description": "'password': '" + SECRET + "'"},
    "escaped-json-nesting": {"description": json.dumps({"nested": json.dumps({"token": SECRET})})},
    "basic-authorization": {"description": "Authorization: Basic " + BASIC},
    "cookie-header": {"description": "Cookie: session_id=" + SECRET},
    "protocol-relative-url": {"description": "//qa-user:" + SECRET + "@example.invalid/private"},
    "double-quote-in-url-password": {"description": 'https://qa-user:public"' + SECRET + '@example.invalid/'},
    "shell-concatenated-quotes": {"description": "password='public'\"" + SECRET + '\"'},
    "sql-doubled-quotes": {"description": "password='public''" + SECRET + "'"},
    "redacted-prefix-with-secret": {"description": "password=[REDACTED]" + SECRET},
    "reference-with-literal-suffix": {"description": 'password="${DB_PASSWORD}' + SECRET + '"'},
    "inline-generic-default": {"description": 'password="${VALUE:-' + SECRET + '}"'},
    "inline-generic-error": {"description": "password='${VALUE:?" + SECRET + "}'"},
    "encoded-full-query-key": {"description": "https://example.invalid/?" + quote("access_token", safe="").replace("a", "%61") + "=" + SECRET},
    "all-encoded-query-key": {"description": "https://example.invalid/?%61%63%63%65%73%73%5f%74%6f%6b%65%6e=" + SECRET},
    "encoded-secret-field": {"hosts": [{"id": "web", "%70%61%73%73%77%6f%72%64": SECRET}]},
    "nested-secret-mapping-list": {"hosts": [{"id": "web", "credentials": [{SECRET: {"value": SECRET}}]}]},
    "nested-reference-secret-field": {"hosts": [{"id": "web", "password": "${OUTER:-${INNER:-" + SECRET + "}}"}]},
    "generic-ref-with-secret-child": {"description": "${OUTER:-${DB_PASSWORD:+" + SECRET + "}}"},
    "quoted-value-control": {"description": 'password="' + SECRET + '"'},
    "quoted-query-control": {"description": "https://example.invalid/?access_token=public'" + SECRET},
    "url-control": {"description": "https://qa-user:" + SECRET + "@example.invalid/"},
    "secret-field-control": {"hosts": [{"id": "web", "password": SECRET}]},
    "bare-inline-control": {"description": "password=" + SECRET},
}


def leak_paths(zf):
    # BASIC is a reversible encoding of the same synthetic credential.
    return [path for path in zf.namelist()
            if any(value.encode() in zf.read(path) for value in (SECRET, BASIC))]


@pytest.mark.parametrize("kind", list(CASES))
def test_export_new_syntax_removed_or_refused(monkeypatch, kind):
    try:
        data, manifest, zf = r1.build_in_memory_bundle(monkeypatch, **CASES[kind])
    except B.ExportError:
        return
    leaked = leak_paths(zf)
    assert not leaked, {"case": kind, "files": leaked,
                        "contains_secrets": manifest["contains_secrets"],
                        "verify_bundle": B.verify_bundle(data)}


CHECK_CASES = ["json-quoted-key", "single-quoted-key", "escaped-json-nesting", "basic-authorization",
               "cookie-header", "protocol-relative-url", "shell-concatenated-quotes",
               "redacted-prefix-with-secret", "reference-with-literal-suffix", "inline-generic-default",
               "all-encoded-query-key", "nested-secret-mapping-list"]


@pytest.mark.parametrize("kind", CHECK_CASES)
def test_checker_detects_secret_even_when_hash_is_correct(monkeypatch, kind):
    _, _, zf = r1.build_in_memory_bundle(monkeypatch)
    files = {path: zf.read(path) for path in zf.namelist()}
    obj = json.loads(files["scenario/scenario.json"])
    obj.update(CASES[kind])
    files["scenario/scenario.json"] = json.dumps(obj).encode()
    manifest = json.loads(files["manifest.json"])
    for item in manifest["files"]:
        if item["path"] == "scenario/scenario.json":
            item["sha256"] = B._sha256(files[item["path"]])
    files["manifest.json"] = json.dumps(manifest).encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as dest:
        for path, content in files.items():
            dest.writestr(path, content)
    errors = B.verify_bundle(buf.getvalue())
    assert errors, {"case": kind, "verify_bundle": errors}
    assert not any("sha256" in error for error in errors), errors


@pytest.mark.parametrize("mode", ["older-active", "cancel-accepted"])
def test_status_cannot_announce_terminal_while_older_execute_is_running(lab, mode):
    ir, _, transport = lab
    r2.add_second(ir, None)
    observed = {}

    def interleaved(req, *args):
        if req.action_id == "a1":
            nested = service.execute(SID, ["a2"])
            observed["newer_job"] = evidence.execution_log(nested[0])["context"]["job_id"]
            if mode == "cancel-accepted":
                observed["cancel"] = runner.cancel_execution(SID)
            job = store.get_job(req.job_id)
            observed["older_job"] = {key: job[key] for key in ("id", "state", "cancel")}
            status = runner.execution_status(SID)
            observed["status"] = {"job_state": status["job_state"],
                                  "actions": [p["action_id"] for p in status["per_action"]]}
        return {"returncode": 0, "stdout": MARKER, "stderr": ""}, None

    transport.side_effect = interleaved
    service.execute(SID, ["a1"])
    assert observed["older_job"]["state"] == "running"
    if mode == "cancel-accepted":
        assert observed["cancel"] == {"cancelled": True}
        assert observed["older_job"]["cancel"] == 1
    assert observed["status"]["job_state"] not in {"done", "cancelled", "error"}, observed


def test_actual_concurrent_jobs_both_receive_cancel_and_keep_results_separate(lab):
    ir, _, transport = lab
    r2.add_second(ir, None)
    arrived = {aid: threading.Event() for aid in ("a1", "a2")}
    release = threading.Event()
    jobs = {}

    def controlled(req, *args):
        jobs[req.action_id] = req.job_id
        arrived[req.action_id].set()
        assert release.wait(5), "synthetic transport release timed out"
        assert store.is_cancelled(req.job_id)
        return {"returncode": 125, "stdout": "", "stderr": "synthetic cancellation"}, None

    transport.side_effect = controlled
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(service.execute, SID, ["a1"])
        second = None
        try:
            assert arrived["a1"].wait(3)
            second = pool.submit(service.execute, SID, ["a2"])
            assert arrived["a2"].wait(3)
            status = runner.execution_status(SID)
            assert [p["action_id"] for p in status["per_action"]] == ["a2"]
            assert runner.cancel_execution(SID) == {"cancelled": True}
            assert len(set(jobs.values())) == 2
            assert all(store.is_cancelled(jid) for jid in jobs.values())
        finally:
            release.set()
        runs = first.result() + second.result()
    assert [r["status"] for r in runs] == ["BLOCKED", "BLOCKED"]
    assert all(store.get_job(jid)["state"] == "cancelled" for jid in jobs.values())
    assert [p["action_id"] for p in runner.execution_status(SID)["per_action"]] == ["a2"]


def test_real_threads_newer_done_does_not_hide_older_active_from_cancel_confirmation(lab):
    ir, _, transport = lab
    r2.add_second(ir, None)
    arrived, release = threading.Event(), threading.Event()
    old_id = []

    def controlled(req, *args):
        if req.action_id == "a1":
            old_id.append(req.job_id)
            arrived.set()
            assert release.wait(5)
            return {"returncode": 125, "stdout": "", "stderr": "synthetic cancellation"}, None
        return {"returncode": 0, "stdout": MARKER, "stderr": ""}, None

    transport.side_effect = controlled
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(service.execute, SID, ["a1"])
        try:
            assert arrived.wait(3)
            service.execute(SID, ["a2"])
            accepted = runner.cancel_execution(SID)
            old = store.get_job(old_id[0])
            snapshot = runner.execution_status(SID)
        finally:
            release.set()
        first.result()
    assert accepted == {"cancelled": True}
    assert old["state"] == "running" and old["cancel"] == 1
    assert snapshot["job_state"] not in {"done", "cancelled", "error"}, {
        "older_job_state": old["state"], "older_cancel_flag": old["cancel"],
        "cancel_response": accepted, "status_job_state": snapshot["job_state"],
        "status_actions": [p["action_id"] for p in snapshot["per_action"]]}


@pytest.mark.parametrize("mode", ["cancel-before-first-action", "error-before-first-result"])
def test_new_empty_terminal_job_never_reuses_older_verified_passes(lab, monkeypatch, mode):
    ir, _, transport = lab
    r2.add_second(ir, None)
    previous = service.execute(SID)
    assert all(evidence.verify_execution(r) == "PASS" for r in previous)
    previous_id = evidence.execution_log(previous[0])["context"]["job_id"]
    assert service.report(SID)["fidelity"]["reproduced"] == ["a1", "a2"]
    transport.reset_mock()

    if mode == "cancel-before-first-action":
        real_create = store.create_job

        def cancel_after_insert(*args, **kwargs):
            real_create(*args, **kwargs)
            assert runner.cancel_execution(SID) == {"cancelled": True}

        monkeypatch.setattr(store, "create_job", cancel_after_insert)
        assert service.execute(SID) == []
    else:
        def unavailable(*args, **kwargs):
            raise OSError("synthetic ownership inspection unavailable")

        monkeypatch.setattr(runner, "assert_target_owned", unavailable)
        with pytest.raises(OSError):
            service.execute(SID)

    transport.assert_not_called()
    c = store._conn()
    try:
        newest = dict(c.execute("SELECT * FROM poc_jobs WHERE scenario_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1",
                                (SID,)).fetchone())
    finally:
        c.close()
    assert newest["id"] != previous_id
    assert newest["state"] == ("cancelled" if mode == "cancel-before-first-action" else "error")
    chain = service.chain(SID)
    fidelity = service.report(SID)["fidelity"]
    assert not fidelity["reproduced"] and all(p["status"] != "PASS" for p in chain["per_action"]), {
        "mode": mode, "newest_job_state": newest["state"], "new_job_has_results": False,
        "chain": chain["per_action"], "reproduced": fidelity["reproduced"]}


@pytest.mark.parametrize("backend", ["local-docker", "proxmox", "unknown-backend"])
@pytest.mark.parametrize("already_cancelled", [False, True])
def test_original_transport_is_fail_closed_even_with_accepted_ownership(lab, monkeypatch, backend, already_cancelled):
    monkeypatch.setattr(manager, "deploy_backend", lambda: backend)
    monkeypatch.setattr(runner, "_probe_with_cancel", ORIGINAL_PROBE)
    launch = Mock(side_effect=AssertionError("no actual launch is permitted"))
    monkeypatch.setattr(manager, "probe_in_service", launch)
    req = r1.request()
    if already_cancelled:
        from dataclasses import replace
        req = replace(req, cancel=True)
        result = runner.SandboxRunner().execute(req).to_dict()
    else:
        result = runner.run_job(SID, [req])[0]
    assert result["status"] == "BLOCKED"
    launch.assert_not_called()
    assert not any(result["stages"][key] for key in ("delivered", "responded", "vuln_behavior", "state_change"))
    assert not any(e["kind"] != "log" for e in result["evidence"])


@pytest.mark.parametrize("stdout,stderr,code", [
    (MARKER + "\x00", "", 0), ("\x1b[32m" + MARKER + "\x1b[0m", "", 0),
    (MARKER + "\nHTTP_ERROR=500", "", 0), ("REQUEST_ERROR=" + MARKER, "", 0),
    (MARKER.replace("=", "＝"), "", 0), (MARKER + "\n", "warning", 0),
    (MARKER, "", 124), (MARKER, "", 125), (MARKER, "", 127),
    ("{\"status\":\"PASS\",\"output\":\"" + MARKER + "\"}", "", 0),
])
def test_fresh_output_spoofs_cannot_manufacture_pass(lab, stdout, stderr, code, monkeypatch):
    # Timeout cleanup is also synthetic, even though production wrapper is replaced here.
    monkeypatch.setattr(runner, "_cleanup_probe", lambda *args: "synthetic no helper")
    lab[2].return_value = ({"returncode": code, "stdout": stdout, "stderr": stderr}, None)
    runs = service.execute(SID)
    assert runs[0]["status"] != "PASS"
    assert evidence.verify_execution(runs[0]) != "PASS"
    assert service.report(SID)["fidelity"]["reproduced"] == []


def test_failed_root_blocks_two_branches_and_merge_but_keeps_independent_action(lab):
    ir, _, transport = lab
    for n in range(2, 6):
        ir["actions"].append({**ir["actions"][0], "id": f"a{n}"})
    ir["relations"] = [{"kind": "dependency", "from_action": a, "to_action": b}
                       for a, b in [("a1", "a2"), ("a1", "a3"), ("a2", "a4"), ("a3", "a4")]]
    transport.side_effect = [({"returncode": 1, "stdout": "no effect", "stderr": ""}, None),
                             ({"returncode": 0, "stdout": MARKER, "stderr": ""}, None)]
    runs = service.execute(SID)
    assert [r["status"] for r in runs] == ["FAIL", "BLOCKED", "BLOCKED", "BLOCKED", "PASS"]
    assert transport.call_count == 2
    assert len({evidence.execution_log(r)["context"]["job_id"] for r in runs}) == 1
    assert len(store.get_runs(SID)) == 5
    chain = service.chain(SID)
    assert [p["status"] for p in chain["per_action"]] == [r["status"] for r in runs]
    assert not chain["passes"]
