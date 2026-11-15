"""Round-2 independent adversarial QA. No payload, subprocess, real HTTP or PVE.

Run from apps/api, with this worktree's contracts and -p no:cacheprovider.
The assertions express the safety/accuracy contract; failures are not xfailed.
Only synthetic secrets and temporary runner artifacts are used.
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
from pathlib import Path
from unittest.mock import Mock
import zipfile

import pytest

from cr_contracts import iter_errors_shape
from app import config
from app.deploy import manager
from app.poc import service, store
from app.poc.chain import evidence, validation
from app.poc.discovery.engine import DiscoveryEngine
from app.poc.discovery.ranking import score_candidate
from app.poc.export import bundle as B
from app.poc.runner import guard, payloads, runner

# Reuse fixture constructors, never change/redefine the round-1 assertions.
spec = importlib.util.spec_from_file_location("m9_round1_fixtures", Path(__file__).parents[1] / "review/test_m9_review.py")
legacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy)
SID = legacy.SID
MARKER = payloads.STRUTS_S2045_MARKER


@pytest.fixture(autouse=True)
def prohibit_external_calls(monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError("QA forbids real process, HTTP and PVE execution")
    monkeypatch.setattr("subprocess.run", forbidden)
    monkeypatch.setattr("urllib.request.urlopen", forbidden)
    monkeypatch.setattr(manager, "_pve_guest_exec", forbidden)


@pytest.fixture
def lab(monkeypatch, tmp_path):
    """Genuine production artifact writer + SQLite; only ownership/delivery mocked."""
    ir = legacy.struts_ir()
    record = {"id": 73, "action": "up", "state": "running", "details": {"backend": "proxmox"}}
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "_DB", tmp_path / "poc.db")
    monkeypatch.setattr(service.store, "get", lambda sid: ir if sid == SID else None)
    monkeypatch.setattr(manager, "deploy_backend", lambda: "proxmox")
    monkeypatch.setattr(manager, "_lifecycle_records", lambda sid: [record] if sid == SID else [])
    monkeypatch.setattr(runner, "assert_target_owned", lambda sid, target: {
        "scenario_id": sid, "service_ref": target["service_ref"], "container_id": "c" * 64,
        "vmid": 900100, "deployment_record_id": record["id"],
    })
    transport = Mock(return_value=({"returncode": 0, "stdout": MARKER, "stderr": ""}, None))
    monkeypatch.setattr(runner, "_probe_with_cancel", transport)
    return ir, record, transport


def run_one(action="a1"):
    return runner.run_job(SID, [legacy.request(action)])[0]


def add_second(ir, relation="dependency"):
    ir["actions"].append({**ir["actions"][0], "id": "a2"})
    ir["evidence"] = [{"id": "source-citation"}]
    ir["relations"] = [] if relation is None else [{
        "kind": relation, "from_action": "a1", "to_action": "a2", "carried": "cred",
        "evidence_refs": ["source-citation"],
    }]


def reseal(run, mutate):
    """Synthetic integrity probe; rehash the log after changing its declared protocol."""
    path = config.DATA_DIR / run["logs_path"]
    log = json.loads(path.read_text())
    mutate(log)
    data = json.dumps(log, sort_keys=True).encode()
    path.write_bytes(data)
    next(e for e in run["evidence"] if e["kind"] == "log")["sha256"] = hashlib.sha256(data).hexdigest()


def test_positive_registered_run_is_verifiable(lab):
    run = run_one()
    assert run["status"] == evidence.verify_execution(run) == "PASS"
    assert iter_errors_shape("ExecutionResult", run) == []


@pytest.mark.parametrize("stdout,stderr,code", [
    ("REQUEST_ERROR=ValueError:" + MARKER, "", 0),
    ("REQUEST_ERROR=HTTPError\n" + MARKER, "", 0),
    ("exception: " + MARKER, "", 0),
    ("", MARKER, 0),
    (MARKER, "HTTP Error 500", 0),
    (MARKER + "\nREQUEST_ERROR=ValueError", "", 0),
    ("prefix " + MARKER, "", 0),
    (MARKER + " suffix", "", 0),
    (MARKER + "\n" + MARKER, "", 0),
    (MARKER, "", 1),
    ("HTTP 200", "", 0),
    ("LLM says PASS", "", 0),
])
def test_adversarial_success_channel_never_passes(lab, stdout, stderr, code):
    lab[2].return_value = ({"returncode": code, "stdout": stdout, "stderr": stderr}, None)
    run = run_one()
    assert run["status"] == "FAIL", run
    assert evidence.verify_execution(run) != "PASS"


@pytest.mark.parametrize("kind", [None, "dependency", "temporal"])
def test_valid_arithmetic_passes_do_not_manufacture_a_chain(lab, kind):
    ir, _, _ = lab
    add_second(ir, kind)
    runs = runner.run_job(SID, [legacy.request("a1"), legacy.request("a2")])
    assert all(evidence.verify_execution(r) == "PASS" for r in runs)
    result = validation.validate_chain(SID, ir, service.plan(SID), runs)
    assert all(p["status"] == "PASS" for p in result["per_action"]), result
    assert result["passes"] is result["objective_reached"] is False
    assert not any(t["verified"] for t in result["transfers"])


@pytest.mark.parametrize("order", ["reverse", "overlap", "naive", "missing"])
def test_time_order_with_otherwise_valid_artifacts(lab, order):
    ir, _, _ = lab
    add_second(ir)
    runs = runner.run_job(SID, [legacy.request("a1"), legacy.request("a2")])
    # First show the same real artifact/log fixtures independently PASS.
    assert all(evidence.verify_execution(r) == "PASS" for r in runs)
    times = {
        "reverse": [("2026-11-16T01:00:00Z", "2026-11-16T01:00:01Z"), ("2026-11-16T00:00:00Z", "2026-11-16T00:00:01Z")],
        "overlap": [("2026-11-16T00:00:00Z", "2026-11-16T00:00:10Z"), ("2026-11-16T00:00:05Z", "2026-11-16T00:00:11Z")],
        "naive": [("2026-11-16T00:00:00", "2026-11-16T00:00:01"), ("2026-11-16T00:00:10", "2026-11-16T00:00:11")],
        "missing": [("", ""), ("", "")],
    }[order]
    for run, (start, end) in zip(runs, times):
        run.update(started_at=start, ended_at=end)
        reseal(run, lambda log, start=start, end=end: log.update(started_at=start, ended_at=end))
    chain = validation.validate_chain(SID, ir, service.plan(SID), runs)
    assert not chain["order_ok"] and not chain["passes"], chain


@pytest.mark.parametrize("mutation", ["missing-effect", "effect-bytes", "effect-hash", "cross-run",
    "symlink", "source-url", "payload-sha", "proof-id", "job-id", "scenario-id", "ir-version",
    "deployment", "log-hash", "log-path", "action-id", "failure-reason", "exit-code"])
def test_artifact_integrity_is_not_just_nonempty_paths(lab, mutation):
    ir, record, _ = lab
    run = run_one()
    assert evidence.verify_execution(run) == "PASS"
    eff = next(e for e in run["evidence"] if e["kind"] == "exploit_effect")
    path = config.DATA_DIR / eff["path"]
    if mutation == "missing-effect":
        path.unlink()
    elif mutation == "effect-bytes":
        path.write_text("HTTP 200")
    elif mutation == "effect-hash":
        eff["sha256"] = "0" * 64
    elif mutation == "cross-run":
        other = run_one()
        eff.update(next(e for e in other["evidence"] if e["kind"] == "exploit_effect"))
    elif mutation == "symlink":
        dest = config.DATA_DIR / "elsewhere.txt"
        dest.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(dest)
    elif mutation == "source-url":
        run["poc"]["source_url"] = "local://unregistered/qa"
    elif mutation == "payload-sha":
        run["payload_sha256"] = "0" * 64
    elif mutation in {"proof-id", "job-id", "scenario-id"}:
        if mutation == "proof-id":
            reseal(run, lambda log: log.update(proof_id="unknown-proof"))
        else:
            key = "job_id" if mutation == "job-id" else "scenario_id"
            reseal(run, lambda log: log["context"].update({key: "unknown"}))
    elif mutation == "ir-version":
        ir["ir_version"] = 999
    elif mutation == "deployment":
        record["id"] += 1
    elif mutation == "log-hash":
        next(e for e in run["evidence"] if e["kind"] == "log")["sha256"] = "0" * 64
    elif mutation == "log-path":
        run["logs_path"] = "poc-runs/nonexistent.log"
    elif mutation == "action-id":
        run["action_id"] = "other-action"
    elif mutation == "failure-reason":
        run["failure_reason"] = "transport failed"
    elif mutation == "exit-code":
        run["exit_code"] = 3
    assert evidence.verify_execution(run) != "PASS", mutation


@pytest.mark.parametrize("code", [1, 127])
def test_predecessor_nonpass_blocks_full_batch(lab, code):
    ir, _, transport = lab
    add_second(ir)
    # Actual runner result for a failure/environment block, not a forged PASS dict.
    transport.side_effect = [({"returncode": code, "stdout": "no effect", "stderr": ""}, None),
                             ({"returncode": 0, "stdout": MARKER, "stderr": ""}, None)]
    results = service.execute(SID)
    assert [r["status"] for r in results] == ["FAIL" if code == 1 else "BLOCKED", "BLOCKED"]
    assert transport.call_count == 1


@pytest.mark.parametrize("mode", ["omit-predecessor", "not-executable-predecessor", "substitute-predecessor"])
def test_predecessor_cannot_be_bypassed_by_selection_or_strategy(lab, mode):
    ir, _, transport = lab
    add_second(ir)
    if mode in {"not-executable-predecessor", "substitute-predecessor"}:
        ir["hosts"].append({"id": "prior"})
        prior = {**ir["services"][0], "id": "svc-prior", "host_ref": "prior"}
        if mode == "not-executable-predecessor":
            prior.update(name="nginx", catalogue_component="oss-nginx", cve=["CVE-2099-0001"])
            ir["actions"][0]["name"] = "Exploit nginx"
        else:
            prior["is_substitute"] = True
        ir["services"].append(prior)
        ir["actions"][0]["target_host_ref"] = "prior"
    selected = ["a2"] if mode == "omit-predecessor" else None
    results = service.execute(SID, selected)
    dependent = next(r for r in results if r["action_id"] == "a2")
    assert dependent["status"] == "BLOCKED", {"mode": mode, "attempts": transport.call_count,
                                              "results": [(r["action_id"], r["status"]) for r in results]}


def test_public_execute_and_chain_keep_each_valid_action_verified(lab):
    ir, _, _ = lab
    add_second(ir, None)
    results = service.execute(SID)
    assert [r["status"] for r in results] == ["PASS", "PASS"]
    assert all(evidence.verify_execution(r) == "PASS" for r in results)
    jobs = [evidence.execution_log(r)["context"]["job_id"] for r in results]
    chain = service.chain(SID)
    assert [p["status"] for p in chain["per_action"]] == ["PASS", "PASS"], {"jobs": jobs, "chain": chain}
    assert not chain["passes"]  # Both are arithmetic only; full chain must stay unverified.


def test_cancel_public_batch_stops_later_independent_actions(lab):
    ir, _, transport = lab
    add_second(ir, None)
    cancellations = []
    def cancel_current(*args):
        cancellations.append(runner.cancel_execution(SID))
        return {"returncode": 125, "stdout": "", "stderr": "cancelled before delivery"}, None
    transport.side_effect = cancel_current
    results = service.execute(SID)
    assert cancellations[0] == {"cancelled": True}
    assert transport.call_count == 1, {"attempts": transport.call_count, "cancellations": cancellations,
                                       "results": [(r["action_id"], r["status"]) for r in results]}


@pytest.mark.parametrize("backend,cancel", [("local-docker", False), ("local-docker", True),
    ("proxmox", False), ("proxmox", True)])
def test_real_transport_is_fail_closed_without_launch(monkeypatch, tmp_path, backend, cancel):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(manager, "deploy_backend", lambda: backend)
    monkeypatch.setattr(service.store, "get", lambda *a: legacy.struts_ir())
    monkeypatch.setattr(runner, "assert_target_owned", lambda *a: {"service_ref": "web"})
    launch = Mock(side_effect=AssertionError("a deferred helper must never launch"))
    monkeypatch.setattr(manager, "probe_in_service", launch)
    run = runner.SandboxRunner().execute(legacy.request(cancel=cancel))
    assert run.status == "BLOCKED" and not run.stages.delivered and not run.stages.responded
    launch.assert_not_called()
    assert not any(e.kind == "exploit_effect" for e in run.evidence)
    if backend == "proxmox" and not cancel:
        assert "guaranteed-cancel transport handle" in run.failure_reason


@pytest.mark.parametrize("mutation", ["external", "edge", "other-lab", "non-isolated", "not-member"])
def test_every_attached_network_must_be_owned_and_isolated(monkeypatch, mutation):
    info = legacy.setup_guard(monkeypatch)
    if mutation in {"external", "edge", "other-lab"}:
        name = {"external": "internet", "edge": f"cr-demo-{SID}-edge",
                "other-lab": "cr-demo-another-scenario-lab"}[mutation]
        info["NetworkSettings"]["Networks"][name] = {}
    else:
        original = guard._docker_json
        def inspect(args):
            out = original(args)
            if args[0] == "network":
                if mutation == "non-isolated":
                    out[0]["Internal"] = False
                else:
                    out[0]["Containers"] = {}
            return out
        monkeypatch.setattr(guard, "_docker_json", inspect)
    with pytest.raises(guard.TargetBlocked):
        guard.assert_target_owned(SID, "web")


@pytest.mark.parametrize("case", ["no-verifier", "substitute", "missing-technique", "disabled"])
def test_plan_categories_are_explicit_and_do_not_fake_execution(lab, case):
    ir, _, transport = lab
    if case == "no-verifier":
        ir["services"][0].update(name="nginx", catalogue_component="oss-nginx", cve=["CVE-2099-0123"])
        ir["actions"][0]["name"] = "Exploit nginx"
    elif case == "substitute":
        ir["services"][0]["is_substitute"] = True
    elif case == "missing-technique":
        ir["actions"][0].pop("attack_technique")
    else:
        ir["services"][0]["lab_enabled"] = False
    item = service.plan(SID)["items"][0]
    assert item["strategy"] == {"no-verifier": "not_executable", "substitute": "config_check",
                                "missing-technique": "poc_exec", "disabled": "not_executable"}[case]
    if item["strategy"] == "not_executable":
        assert item["not_executable_reason"]
    results = service.execute(SID)
    if case != "missing-technique":
        assert results == []
        transport.assert_not_called()


@pytest.mark.parametrize("kind", ["normal-url", "quoted-url", "default", "generic-secret-field-default",
    "default-error-message", "url-token-username", "nested-default", "query-token"])
def test_bundle_fresh_secret_syntax_does_not_escape_redaction(monkeypatch, kind):
    secret = "round2-qa-only-credential-Z483"
    descriptions = {
        "normal-url": "postgresql://qa-user:" + secret + "@example.invalid/db",
        "quoted-url": "https://qa-user:" + secret + "'ok@example.invalid/private",
        "default": "Use ${SERVICE_TOKEN:-" + secret + "}",
        "generic-secret-field-default": "",
        "default-error-message": "",
        "url-token-username": "https://" + secret + "@example.invalid/private",
        "nested-default": "",
        "query-token": "https://example.invalid/?access_token=" + secret,
    }
    hosts = None
    if kind == "generic-secret-field-default":
        hosts = [{"id": "web", "password": "${VALUE:-" + secret + "}"}]
    elif kind == "default-error-message":
        hosts = [{"id": "web", "password": "${DB_PASSWORD:?" + secret + "}"}]
    elif kind == "nested-default":
        hosts = [{"id": "web", "password": "${DB_PASSWORD:-${FALLBACK:-" + secret + "}}"}]
    try:
        data, manifest, zf = legacy.build_in_memory_bundle(monkeypatch, description=descriptions[kind], hosts=hosts)
    except B.ExportError:
        return  # Explicit fail-closed refusal is honest.
    leaking = [p for p in zf.namelist() if secret.encode() in zf.read(p)]
    assert not leaking, {"syntax": kind, "leaks": leaking, "contains_secrets": manifest["contains_secrets"],
                         "verify_bundle": B.verify_bundle(data)}


@pytest.mark.parametrize("version,expression,compatible", [
    ("2.15.0", "< 2.15.0", False), ("2.14.1", "< 2.15.0", True),
    ("2.15.0", "<= 2.15.0", True), ("2.9.0", "2.10.0 through 2.14.1", False),
    ("2.14.1", "2.10.0 through 2.14.1", True), ("2.15.0", "2.10.0 through 2.14.1", False),
    ("2.10.0", "2.10.x", True), ("2.11.0", "2.10.x", False),
    ("2.15.0-rc1", "2.15.0", False), ("2.15.0", "unparsed prose 2.15.0", False),
])
def test_version_range_extra_boundaries(version, expression, compatible):
    score = score_candidate({"product": "QA product", "version_range": expression},
                            {"product": "QA product", "version": version})["version"]
    assert (score > .9) == compatible, (version, expression, score)


def test_persisted_nonempty_discovery_and_chain_are_in_export(lab, monkeypatch):
    from app.poc import discovery
    ir, _, _ = lab
    candidate = {"action_id": "a1", "source": "github", "source_url": "https://github.com/qa/fixture",
                 "compatibility_score": .5, "ref": {"commit_sha": "a" * 40}}
    manifest = {"scenario_id": SID, "generated_at": "2026-11-16T00:00:00Z", "items": [candidate]}
    monkeypatch.setattr(discovery, "discover", lambda *a: manifest)
    service.discover(SID)
    run_one()
    chain = service.chain(SID)
    saved_manifest = store.get_manifest(SID)
    assert saved_manifest["items"] == [candidate]
    def missing_iac(*a):
        raise FileNotFoundError("Synthetic fixture: IaC not generated")
    monkeypatch.setattr(B.generator, "get_generated", missing_iac)
    monkeypatch.setattr(B, "_env_secret_values", lambda: [])
    data, _ = B.build_bundle(SID)
    zf = zipfile.ZipFile(io.BytesIO(data))
    assert json.loads(zf.read("validation/poc-manifest.json"))["items"] == [candidate]
    assert json.loads(zf.read("validation/results.json"))["chain_validation"] == chain


def test_empty_but_completed_discovery_is_preserved_for_export(lab, monkeypatch):
    from app.poc import discovery
    manifest = {"scenario_id": SID, "generated_at": "2026-11-16T00:00:00Z", "items": []}
    monkeypatch.setattr(discovery, "discover", lambda *a: manifest)
    service.discover(SID)
    assert store.get_manifest(SID) == manifest, "completed zero-candidate discovery is lost"


def test_blocked_dependent_result_is_persisted_for_export(lab):
    ir, _, transport = lab
    add_second(ir)
    transport.return_value = ({"returncode": 1, "stdout": "no exploit effect", "stderr": ""}, None)
    returned = service.execute(SID)
    assert [(r["action_id"], r["status"]) for r in returned] == [("a1", "FAIL"), ("a2", "BLOCKED")]
    saved = store.get_runs(SID)
    assert [(r["action_id"], r["status"]) for r in saved] == [("a1", "FAIL"), ("a2", "BLOCKED")], {
        "returned": [(r["action_id"], r["status"]) for r in returned],
        "persisted": [(r["action_id"], r["status"]) for r in saved]}


@pytest.mark.parametrize("description,compatible", [
    ("versions before 2.3.30", False), ("versions after 2.3.30", False),
    ("versions < 2.3.30", False), ("versions 2.3.0 through 2.3.30", True),
])
def test_discovery_preserves_range_operators_before_ranking(description, compatible):
    ir = legacy.struts_ir()
    client = Mock()
    client.nvd_search.return_value = None
    client.exploitdb_search.return_value = []
    client.github_search.return_value = [{"source_url": "https://github.com/qa/fixture",
        "product": "Struts", "description": "Struts CVE-2017-5638 exploit affects " + description,
        "language": "Python"}]
    manifest = DiscoveryEngine(client).discover(SID, ir)
    assert len(manifest["items"]) == 1
    candidate = manifest["items"][0]
    assert (candidate["score_breakdown"]["version"] > .9) == compatible, {
        "description": description, "extracted_range": candidate["version_range"],
        "score": candidate["score_breakdown"]["version"]}


def test_normal_ir_host_service_refs_reach_discovery_and_execution_plan(lab):
    ir, _, _ = lab
    ir["services"][0].pop("host_ref")
    ir["hosts"][0].update(role="victim-web", service_refs=["svc-struts"])
    client = Mock()
    client.nvd_search.return_value = None
    client.exploitdb_search.return_value = []
    client.github_search.return_value = [{"source_url": "https://github.com/qa/fixture",
        "product": "Struts", "description": "Struts CVE-2017-5638 exploit", "language": "Python"}]
    assert DiscoveryEngine(client).discover(SID, ir)["items"]
    item = service.plan(SID)["items"][0]
    assert item["strategy"] == "poc_exec" and item.get("service_ref") == "svc-struts", item


def test_arithmetic_receipt_files_cannot_upgrade_to_credential_verifier(lab):
    ir, _, _ = lab
    add_second(ir)
    runs = runner.run_job(SID, [legacy.request("a1"), legacy.request("a2")])
    logs = [evidence.execution_log(r) for r in runs]
    produced = {"event": "produced", "carried": "cred", "state_id": "qa-state",
                "value_sha256": hashlib.sha256(b"QA fake state; never a real credential").hexdigest(),
                "action_id": "a1", "run_id": logs[0]["context"]["run_id"]}
    def append_receipt(run, name, receipt):
        relative = Path(run["logs_path"]).parent / name
        content = json.dumps(receipt).encode()
        (config.DATA_DIR / relative).write_bytes(content)
        entry = {"kind": "state_change", "path": str(relative), "sha256": hashlib.sha256(content).hexdigest(),
                 "redacted": True, "note": "cred produced/consumed synthetic receipt"}
        run["evidence"].insert(0, entry)
        reseal(run, lambda log: log.update(evidence=[e for e in run["evidence"] if e["kind"] != "log"]))
        return entry
    source = append_receipt(runs[0], "produced.json", produced)
    consumed = {**produced, "event": "consumed", "action_id": "a2", "run_id": logs[1]["context"]["run_id"],
                "from_action": "a1", "from_run_id": logs[0]["context"]["run_id"],
                "source_evidence": {"path": source["path"], "sha256": source["sha256"]}}
    append_receipt(runs[1], "consumed.json", consumed)
    assert all(evidence.verify_execution(r) == "PASS" for r in runs)
    chain = validation.validate_chain(SID, ir, service.plan(SID), runs)
    assert not chain["passes"] and chain["transfers"][0]["verified"] is False, chain


@pytest.mark.parametrize("cited", [False, True])
def test_valid_artifacts_still_propagate_failure_transitively(lab, cited):
    ir, _, transport = lab
    add_second(ir)
    ir["actions"].append({**ir["actions"][0], "id": "a3"})
    ir["relations"].append({**ir["relations"][0], "from_action": "a2", "to_action": "a3"})
    if not cited:
        for relation in ir["relations"]:
            relation.pop("evidence_refs")
    transport.side_effect = [({"returncode": code, "stdout": MARKER if code == 0 else "no effect", "stderr": ""}, None)
                             for code in [1, 0, 0]]
    runs = runner.run_job(SID, [legacy.request(a) for a in ["a1", "a2", "a3"]])
    assert [evidence.verify_execution(r) for r in runs] == ["FAIL", "PASS", "PASS"]
    chain = validation.validate_chain(SID, ir, service.plan(SID), runs)
    assert [p["status"] for p in chain["per_action"]] == ["FAIL", "BLOCKED", "BLOCKED"], chain


def test_rerun_does_not_overwrite_previous_attempt(lab):
    first = run_one()
    paths = {e["path"]: (config.DATA_DIR / e["path"]).read_bytes() for e in first["evidence"]}
    second = run_one()
    assert set(paths).isdisjoint(e["path"] for e in second["evidence"])
    assert all((config.DATA_DIR / path).read_bytes() == content for path, content in paths.items())
    assert evidence.verify_execution(first) == evidence.verify_execution(second) == "PASS"


@pytest.mark.parametrize("blocked", [False, True])
def test_public_serialization_matches_original_nonnullable_contract(lab, monkeypatch, blocked):
    from jsonschema import Draft7Validator
    if blocked:
        def deny(*a):
            raise guard.TargetBlocked("QA ownership denied")
        monkeypatch.setattr(runner, "assert_target_owned", deny)
    run = run_one()
    # Freeze the original types independently of the broadened current schema.
    schema = json.loads((Path(__file__).resolve().parents[4] / "packages/contracts/schemas/poc-validation.schema.json").read_text())
    definition = schema["definitions"]["ExecutionResult"]
    definition["properties"]["exit_code"] = {"type": "integer"}
    definition["properties"]["failure_reason"] = {"type": "string"}
    validator = Draft7Validator({"$ref": "#/definitions/ExecutionResult", "definitions": schema["definitions"]})
    assert list(validator.iter_errors(run)) == []
