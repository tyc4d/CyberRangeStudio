"""Real runner artifacts consumed by the strict chain verifier, with mock delivery only."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from app import config
from app.poc.chain.evidence import execution_log, scenario_digest, verify_execution
from app.poc.chain.validation import validate_chain
from app.poc.runner import guard, payloads, runner
from app.poc.runner.models import ExecutionRequest

SID = "runner-chain-integration"


@pytest.fixture
def lab(monkeypatch, tmp_path):
    ir = {"id": SID, "ir_version": 7, "name": "驗證同一份情境",
          "actions": [{"id": "a1", "name": "Exploit Struts"}], "relations": []}
    record = {"id": 41, "action": "up", "state": "running", "details": {"backend": "proxmox"}}
    ownership = {"scenario_id": SID, "service_ref": "web", "deployment_record_id": record["id"],
                 "container_id": "b" * 64, "vmid": 900100}
    proof = payloads.KNOWN_POC_PROOFS[payloads.STRUTS_S2045_PROOF_ID]
    req = ExecutionRequest("a1", SID, "web", proof["source_url"], {}, proof["sha256"],
                           proof["exec_method"], proof["payload"], proof["expected_marker"],
                           proof_id=payloads.STRUTS_S2045_PROOF_ID)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(runner.poc_store, "_DB", tmp_path / "poc.db")
    monkeypatch.setattr(runner.scenario_store, "get", lambda sid: ir if sid == SID else None)
    monkeypatch.setattr(runner.manager, "_lifecycle_records", lambda sid: [record] if sid == SID else [])
    monkeypatch.setattr(runner, "assert_target_owned", lambda *args: dict(ownership))
    monkeypatch.setattr("subprocess.run", Mock(side_effect=AssertionError("no real subprocess")))
    monkeypatch.setattr("urllib.request.urlopen", Mock(side_effect=AssertionError("no real HTTP")))
    monkeypatch.setattr(runner.manager, "_pve_guest_exec", Mock(side_effect=AssertionError("no real PVE")))
    transport = Mock(return_value=({"returncode": 0, "stdout": proof["expected_marker"], "stderr": ""}, None))
    monkeypatch.setattr(runner, "_probe_with_cancel", transport)
    return ir, record, ownership, req, transport


def test_real_runner_log_and_effect_verify_and_roll_up_per_action(lab):
    ir, record, _, req, transport = lab
    run, = runner.run_job(SID, [req])
    transport.assert_called_once()
    log = execution_log(run)
    assert log is not None
    context = log["context"]
    assert set(context) == {"run_id", "job_id", "scenario_id", "scenario_sha256", "deployment_record_id"}
    assert context["scenario_sha256"] == scenario_digest(ir)
    assert context["deployment_record_id"] == record["id"]
    prefix = Path("poc-runs") / hashlib.sha256(SID.encode()).hexdigest()[:16] / context["run_id"]
    assert Path(run["logs_path"]).parent == prefix
    for key in ("action_id", "status", "started_at", "ended_at", "payload_sha256"):
        assert log[key] == run[key]
    assert log["proof_id"] == req.proof_id
    assert log["evidence"] == [item for item in run["evidence"] if item["kind"] != "log"]
    for item in run["evidence"]:
        path = config.DATA_DIR / item["path"]
        assert Path(item["path"]).parent == prefix
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
    assert verify_execution(run) == "PASS"
    plan = {"items": [{"action_id": "a1", "strategy": "poc_exec"}]}
    chain = validate_chain(SID, ir, plan, [run])
    assert chain["per_action"] == [{"action_id": "a1", "status": "PASS"}]
    # This arithmetic proof verifies one action, not a credential/session transfer.
    assert chain["passes"] is False and chain["objective_reached"] is False


@pytest.mark.parametrize("change", ["edited-ir", "redeployed", "effect-bytes", "log-bytes"])
def test_real_runner_evidence_cannot_survive_changed_identity_or_artifacts(lab, change):
    ir, record, _, req, _ = lab
    run, = runner.run_job(SID, [req])
    assert verify_execution(run) == "PASS"
    if change == "edited-ir":
        ir["ir_version"] += 1
    elif change == "redeployed":
        record["id"] += 1
    else:
        kind = "exploit_effect" if change == "effect-bytes" else "log"
        evidence = next(item for item in run["evidence"] if item["kind"] == kind)
        (config.DATA_DIR / evidence["path"]).write_bytes(b"changed after the completed run")
    assert verify_execution(run) == "PARTIAL"


@pytest.mark.parametrize("identity", [None, "41", False])
def test_missing_or_invalid_owned_deployment_id_is_omitted_and_cannot_verify(lab, identity):
    _, _, ownership, req, _ = lab
    ownership["deployment_record_id"] = identity
    run, = runner.run_job(SID, [req])
    log = execution_log(run)
    assert log is not None
    assert "deployment_record_id" not in log["context"]
    assert verify_execution(run) == "PARTIAL"


def test_ir_and_deployment_are_captured_before_mock_delivery(lab):
    ir, record, _, req, transport = lab
    before_digest = scenario_digest(ir)
    before_deployment = record["id"]
    def changed_during_delivery(*args):
        ir["ir_version"] += 1
        record["id"] += 1
        return {"returncode": 0, "stdout": req.expected_marker, "stderr": ""}, None
    transport.side_effect = changed_during_delivery
    run, = runner.run_job(SID, [req])
    log = execution_log(run)
    assert log is not None
    assert log["context"]["scenario_sha256"] == before_digest
    assert log["context"]["deployment_record_id"] == before_deployment
    assert verify_execution(run) == "PARTIAL"


def test_blocked_ownership_still_writes_consistent_hashed_log(lab, monkeypatch):
    _, _, _, req, transport = lab
    def deny(*args):
        raise guard.TargetBlocked("not owned")
    monkeypatch.setattr(runner, "assert_target_owned", deny)
    run, = runner.run_job(SID, [req])
    transport.assert_not_called()
    assert verify_execution(run) == "BLOCKED"
    log = json.loads((config.DATA_DIR / run["logs_path"]).read_text())
    for key in ("action_id", "status", "started_at", "ended_at", "payload_sha256"):
        assert log[key] == run[key]
    assert log["ownership"] is None and log["evidence"] == []
    assert "deployment_record_id" not in log["context"]
    evidence, = run["evidence"]
    assert evidence["kind"] == "log"
    assert hashlib.sha256((config.DATA_DIR / evidence["path"]).read_bytes()).hexdigest() == evidence["sha256"]
