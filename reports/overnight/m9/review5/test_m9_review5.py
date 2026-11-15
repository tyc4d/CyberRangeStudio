"""Round-5 convergence probes. Synthetic credentials; no live process/HTTP/runtime.

Run from apps/api with worktree contracts and -p no:cacheprovider.
The builder and checker are the production functions; no redaction/verifier mocks.
"""
from __future__ import annotations

import importlib.util
from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path
import threading
import zipfile

import pytest
import yaml

from app.deploy import manager
from app.poc import service, store
from app.poc.chain import evidence
from app.poc.export import bundle as B
from app.poc.runner import runner

spec = importlib.util.spec_from_file_location(
    "round5_legacy", Path(__file__).parents[1] / "review/test_m9_review.py")
r1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r1)
spec2 = importlib.util.spec_from_file_location(
    "round5_round2", Path(__file__).parents[1] / "review2/test_m9_review2.py")
r2 = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(r2)
lab = r2.lab
ORIGINAL_PROBE = runner._probe_with_cancel

SECRET = "round5-synthetic-credential-M937"
MULTILINE = {
    "yaml-literal-block": "password: |\n  " + SECRET + "\n",
    "yaml-folded-block": "password: >\n  " + SECRET + "\n",
    "yaml-value-on-next-line": "password:\n  " + SECRET + "\n",
    "yaml-multiline-double-quote": 'password: "public\n  ' + SECRET + '"\n',
    "shell-line-continuation": "password=public\\\n" + SECRET + "\n",
}


@pytest.fixture(autouse=True)
def no_external_execution(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Round-5 forbids real process, HTTP, PVE and payload execution")
    for target in ("subprocess.run", "subprocess.Popen", "urllib.request.urlopen"):
        monkeypatch.setattr(target, forbidden)
    monkeypatch.setattr(manager, "_pve_guest_exec", forbidden)
    monkeypatch.setattr(manager, "probe_in_service", forbidden)


@pytest.mark.parametrize("kind", list(MULTILINE))
def test_multiline_secret_builder_redacts_entire_value_or_refuses(monkeypatch, kind):
    if kind.startswith("yaml-"):
        assert SECRET in yaml.safe_load(MULTILINE[kind])["password"]
    try:
        data, manifest, zf = r1.build_in_memory_bundle(monkeypatch, description=MULTILINE[kind])
    except B.ExportError:
        return
    leaked = [name for name in zf.namelist() if SECRET.encode() in zf.read(name)]
    assert not leaked, {"case": kind, "files": leaked,
                        "contains_secrets": manifest["contains_secrets"],
                        "verify_bundle": B.verify_bundle(data),
                        "exported_description": json.loads(zf.read("scenario/scenario.json"))["description"]}


@pytest.mark.parametrize("kind", list(MULTILINE))
def test_multiline_secret_checker_detects_even_with_correct_hash(monkeypatch, kind):
    _, _, zf = r1.build_in_memory_bundle(monkeypatch)
    files = {name: zf.read(name) for name in zf.namelist()}
    ir = json.loads(files["scenario/scenario.json"])
    ir["description"] = MULTILINE[kind]
    files["scenario/scenario.json"] = json.dumps(ir).encode()
    manifest = json.loads(files["manifest.json"])
    for entry in manifest["files"]:
        if entry["path"] == "scenario/scenario.json":
            entry["sha256"] = B._sha256(files[entry["path"]])
    files["manifest.json"] = json.dumps(manifest).encode()
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dest:
        for name, data in files.items():
            dest.writestr(name, data)
    errors = B.verify_bundle(out.getvalue())
    assert errors, {"case": kind, "verify_bundle": errors}
    assert not any("sha256" in error for error in errors), errors


@pytest.mark.parametrize("kind", list(MULTILINE))
def test_actual_secret_mapping_is_safe_control(monkeypatch, kind):
    try:
        _, _, zf = r1.build_in_memory_bundle(monkeypatch, hosts=[{"id": "web", "password": MULTILINE[kind]}])
    except B.ExportError:
        return
    assert not any(SECRET.encode() in zf.read(name) for name in zf.namelist())


def test_clean_bundle_still_verifies(monkeypatch):
    data, manifest, _ = r1.build_in_memory_bundle(monkeypatch, description="Public configuration documentation")
    assert manifest["contains_secrets"] is False
    assert B.verify_bundle(data) == []


def test_real_backend_can_return_prior_chain_report_while_execute_is_pending(lab, monkeypatch):
    """Establish that the web race's response order is possible with real artifacts/DB.

    Pause the execute handler before it reaches run_job (also models ordinary request transit).
    Chain/report are unchanged. Only delivery/ownership, not evidence verification, are mocked.
    This is a positive reachability control, not a claim that the backend lies about the old batch.
    """
    ir, _, transport = lab
    r2.add_second(ir, None)
    previous = service.execute(r2.SID)
    assert [r["status"] for r in previous] == ["PASS", "PASS"]
    assert [evidence.verify_execution(r) for r in previous] == ["PASS", "PASS"]
    original = runner.run_job
    entered, release = threading.Event(), threading.Event()

    def delayed(*args, **kwargs):
        entered.set()
        assert release.wait(5), "test failed to release paused handler"
        return original(*args, **kwargs)

    monkeypatch.setattr(runner, "run_job", delayed)
    with ThreadPoolExecutor(max_workers=1) as executor:
        flight = executor.submit(service.execute, r2.SID)
        try:
            assert entered.wait(3)
            during_chain = service.chain(r2.SID)
            during_report = service.report(r2.SID)
            assert [a["status"] for a in during_chain["per_action"]] == ["PASS", "PASS"]
            assert during_chain["passes"] is False  # independent steps never prove a full chain
            assert during_report["fidelity"]["reproduced"] == ["a1", "a2"]
            transport.return_value = ({"returncode": 0, "stdout": "EXPLOIT_NOT_CONFIRMED", "stderr": ""}, None)
        finally:
            release.set()
        current = flight.result(timeout=5)
    assert [r["status"] for r in current] == ["FAIL", "FAIL"]
    assert [a["status"] for a in service.chain(r2.SID)["per_action"]] == ["FAIL", "FAIL"]
    assert service.report(r2.SID)["fidelity"]["reproduced"] == []
    assert len(store.get_runs(r2.SID)) == 4


@pytest.mark.parametrize("backend", ["local-docker", "proxmox", "unknown-backend"])
def test_public_execute_original_transport_remains_fail_closed(lab, monkeypatch, backend):
    ir, _, _ = lab
    r2.add_second(ir, None)
    monkeypatch.setattr(manager, "deploy_backend", lambda: backend)
    monkeypatch.setattr(runner, "_probe_with_cancel", ORIGINAL_PROBE)
    # no_external_execution makes any real launch fail this test, including a PVE launch.
    results = service.execute(r2.SID)
    assert len(results) == len(store.get_runs(r2.SID)) == 2
    for result in results:
        assert result["status"] == "BLOCKED"
        assert not any(result["stages"][name] for name in
                       ("delivered", "responded", "vuln_behavior", "state_change"))
        assert {entry["kind"] for entry in result["evidence"]} == {"log"}
    assert service.report(r2.SID)["fidelity"]["reproduced"] == []


@pytest.mark.parametrize("state", ["pending", "running", "cancelled", "error"])
def test_empty_latest_job_never_selects_historical_passes(lab, state):
    ir, _, _ = lab
    r2.add_second(ir, None)
    assert [r["status"] for r in service.execute(r2.SID)] == ["PASS", "PASS"]
    store.create_job("round5-empty-" + state, r2.SID, "execute")
    store.set_job_state("round5-empty-" + state, state)
    assert [r["status"] for r in service.chain(r2.SID)["per_action"]] == ["NOT_TESTED", "NOT_TESTED"]
    assert service.report(r2.SID)["fidelity"]["reproduced"] == []
