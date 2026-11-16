"""Real runner artifacts consumed by the strict chain verifier, with mock delivery only."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
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


def assert_one_persisted_job(runs):
    db = runner.poc_store._conn()
    try:
        jobs = [dict(row) for row in db.execute("SELECT * FROM poc_jobs WHERE scenario_id=?", (SID,))]
    finally:
        db.close()
    assert len(jobs) == 1
    for run in runs:
        log = json.loads((config.DATA_DIR / run["logs_path"]).read_text())
        assert log["context"]["job_id"] == jobs[0]["id"]
    assert runner.poc_store.get_runs(SID) == runs
    return jobs[0]


@pytest.mark.parametrize("code", [0, 1, 127])
def test_batch_predecessor_gate_uses_completed_status_in_the_same_job(lab, monkeypatch, code):
    ir, _, _, req, transport = lab
    ir["actions"].append({"id": "a2", "name": "Dependent action"})
    guard_spy = Mock(side_effect=runner.assert_target_owned)
    monkeypatch.setattr(runner, "assert_target_owned", guard_spy)
    transport.side_effect = [
        ({"returncode": code, "stdout": req.expected_marker if code == 0 else "no effect", "stderr": ""}, None),
        ({"returncode": 0, "stdout": req.expected_marker, "stderr": ""}, None),
    ]
    dependent = replace(req, action_id="a2", required_predecessors=("a1",))
    runs = runner.run_job(SID, [req, dependent])
    assert [run["status"] for run in runs] == (
        ["PASS", "PASS"] if code == 0 else ["FAIL" if code == 1 else "BLOCKED", "BLOCKED"])
    assert transport.call_count == guard_spy.call_count == (2 if code == 0 else 1)
    assert assert_one_persisted_job(runs)["state"] == "done"
    if code == 0:
        assert all(verify_execution(run) == "PASS" for run in runs)
    else:
        assert not any(runs[1]["stages"].values())
        assert verify_execution(runs[1]) == "BLOCKED"
        assert "a1" in runs[1]["failure_reason"]


def test_missing_predecessor_blocks_without_inspection_or_delivery(lab, monkeypatch):
    _, _, _, req, transport = lab
    guard_spy = Mock(side_effect=AssertionError("a blocked dependent must not inspect a target"))
    monkeypatch.setattr(runner, "assert_target_owned", guard_spy)
    dependent = replace(req, action_id="a2", required_predecessors=("unselected",))
    runs = runner.run_job(SID, [dependent])
    assert runs[0]["status"] == "BLOCKED"
    assert verify_execution(runs[0]) == "BLOCKED"
    assert not any(runs[0]["stages"].values())
    transport.assert_not_called()
    guard_spy.assert_not_called()
    assert_one_persisted_job(runs)


def test_previous_job_pass_cannot_satisfy_current_job_predecessor(lab):
    _, _, _, req, transport = lab
    old, = runner.run_job(SID, [req])
    assert verify_execution(old) == "PASS"
    transport.reset_mock()
    dependent = replace(req, action_id="a2", required_predecessors=("a1",))
    current, = runner.run_job(SID, [dependent])
    assert current["status"] == "BLOCKED"
    transport.assert_not_called()
    old_context = json.loads((config.DATA_DIR / old["logs_path"]).read_text())["context"]
    current_context = json.loads((config.DATA_DIR / current["logs_path"]).read_text())["context"]
    assert old_context["job_id"] != current_context["job_id"]
    assert runner.poc_store.get_runs(SID) == [old, current]


def test_one_missing_among_multiple_predecessors_still_blocks(lab):
    _, _, _, req, transport = lab
    dependent = replace(req, action_id="a2", required_predecessors=("a1", "unselected"))
    runs = runner.run_job(SID, [req, dependent])
    assert [run["status"] for run in runs] == ["PASS", "BLOCKED"]
    transport.assert_called_once()
    assert "unselected" in runs[1]["failure_reason"]
    assert_one_persisted_job(runs)


def test_failed_predecessor_blocks_all_transitive_requests_and_persists_them(lab):
    _, _, _, req, transport = lab
    transport.return_value = ({"returncode": 1, "stdout": "no effect", "stderr": ""}, None)
    middle = replace(req, action_id="a2", required_predecessors=("a1",))
    last = replace(req, action_id="a3", required_predecessors=("a2",))
    runs = runner.run_job(SID, [req, middle, last])
    assert [run["status"] for run in runs] == ["FAIL", "BLOCKED", "BLOCKED"]
    transport.assert_called_once()
    assert_one_persisted_job(runs)


def test_request_order_does_not_treat_a_later_predecessor_as_completed(lab):
    _, _, _, req, transport = lab
    dependent = replace(req, action_id="a2", required_predecessors=("a1",))
    runs = runner.run_job(SID, [dependent, req])
    assert [(run["action_id"], run["status"]) for run in runs] == [("a2", "BLOCKED"), ("a1", "PASS")]
    transport.assert_called_once()
    assert_one_persisted_job(runs)


def test_cancel_one_batch_stops_every_later_independent_action(lab):
    _, _, _, req, transport = lab
    cancellations = []
    def cancel_during_first(*args):
        cancellations.append(runner.cancel_execution(SID))
        return {"returncode": 125, "stdout": "", "stderr": "cancelled before delivery"}, None
    transport.side_effect = cancel_during_first
    runs = runner.run_job(SID, [req, replace(req, action_id="a2"), replace(req, action_id="a3")])
    assert cancellations == [{"cancelled": True}]
    transport.assert_called_once()
    assert [(run["action_id"], run["status"]) for run in runs] == [("a1", "BLOCKED")]
    job = assert_one_persisted_job(runs)
    assert job["state"] == "cancelled" and job["cancel"] == 1
    assert runner.execution_status(SID)["job_state"] == "cancelled"
    assert runner.cancel_execution(SID) == {"cancelled": False}


def test_overlapping_same_action_status_and_tail_belong_to_newest_job(lab):
    _, _, _, req, transport = lab
    nested = []
    entered = False
    def interleaved(current, *args):
        nonlocal entered
        if not entered:
            entered = True
            nested.extend(runner.run_job(SID, [current]))
        return {"returncode": 0, "stdout": req.expected_marker, "stderr": ""}, None
    transport.side_effect = interleaved
    outer, = runner.run_job(SID, [req])
    inner, = nested
    assert verify_execution(outer) == verify_execution(inner) == "PASS"
    outer_job = execution_log(outer)["context"]["job_id"]
    inner_job = execution_log(inner)["context"]["job_id"]
    assert outer_job != inner_job
    status = runner.execution_status(SID)
    assert status["per_action"] == [{"action_id": "a1", "stages": inner["stages"]}]
    assert json.loads(status["logs_tail"])["context"]["job_id"] == inner_job


def test_job_membership_uses_identity_when_timestamps_tie_or_rows_are_backdated(lab):
    _, _, _, req, _ = lab
    older, = runner.run_job(SID, [req])
    newer, = runner.run_job(SID, [replace(req, action_id="a2")])
    db = runner.poc_store._conn()
    try:
        db.execute("UPDATE poc_jobs SET created_at=100 WHERE scenario_id=?", (SID,))
        db.execute("UPDATE poc_runs SET ts=0 WHERE scenario_id=?", (SID,))
        db.commit()
    finally:
        db.close()
    status = runner.execution_status(SID)
    assert status["per_action"] == [{"action_id": "a2", "stages": newer["stages"]}]
    context = json.loads(status["logs_tail"])["context"]
    assert context["job_id"] == execution_log(newer)["context"]["job_id"]
    assert context["job_id"] != execution_log(older)["context"]["job_id"]


def test_cancel_flags_all_active_execute_jobs_without_touching_other_jobs(lab):
    for job_id, scenario, kind, state in (
        ("old-pending", SID, "execute", "pending"),
        ("old-running", SID, "execute", "running"),
        ("other-scenario", "unrelated", "execute", "running"),
        ("other-kind", SID, "discover", "running"),
        ("newer-done", SID, "execute", "done"),
    ):
        runner.poc_store.create_job(job_id, scenario, kind)
        runner.poc_store.set_job_state(job_id, state)
    assert runner.cancel_execution(SID) == {"cancelled": True}
    for job_id in ("old-pending", "old-running"):
        assert runner.poc_store.get_job(job_id)["cancel"] == 1
    for job_id in ("other-scenario", "other-kind", "newer-done"):
        assert runner.poc_store.get_job(job_id)["cancel"] == 0
    for job_id in ("old-pending", "old-running"):
        runner.poc_store.set_job_state(job_id, "cancelled")
    assert runner.cancel_execution(SID) == {"cancelled": False}


def test_idle_status_exposes_no_selected_or_active_job(lab):
    status = runner.execution_status(SID)
    assert status["job_id"] is None
    assert status["job_state"] == status["selected_job_state"] == "idle"
    assert status["jobs"] == status["active_jobs"] == status["per_action"] == []


@pytest.mark.parametrize("older_state", ["pending", "running"])
def test_status_tracks_cancelled_job_identity_through_its_own_terminal_transition(lab, older_state):
    _, _, _, req, _ = lab
    older_id = "0" * 32
    runner.poc_store.create_job(older_id, SID, "execute")
    runner.poc_store.set_job_state(older_id, older_state)
    newer, = runner.run_job(SID, [req])
    newer_id = execution_log(newer)["context"]["job_id"]
    for job_id, scenario, kind in (("f" * 32, "unrelated", "execute"), ("d" * 32, SID, "discover")):
        runner.poc_store.create_job(job_id, scenario, kind)
        runner.poc_store.set_job_state(job_id, "running")

    before = runner.execution_status(SID)
    assert before["job_id"] == newer_id
    assert before["selected_job_state"] == "done"
    assert before["job_state"] == older_state
    assert {entry["job_id"] for entry in before["jobs"]} == {older_id, newer_id}
    assert before["active_jobs"] == [{"job_id": older_id, "state": older_state, "cancel_requested": False}]
    assert before["per_action"] == [{"action_id": "a1", "stages": newer["stages"]}]

    assert runner.cancel_execution(SID) == {"cancelled": True}
    requested = runner.execution_status(SID)
    assert requested["job_id"] == newer_id
    assert requested["selected_job_state"] == "done"
    assert requested["job_state"] == older_state
    assert requested["active_jobs"] == [{"job_id": older_id, "state": older_state, "cancel_requested": True}]

    runner.poc_store.set_job_state(older_id, "cancelled")
    completed = runner.execution_status(SID)
    assert completed["job_id"] == newer_id
    assert completed["job_state"] == completed["selected_job_state"] == "done"
    assert completed["active_jobs"] == []
    states = {entry["job_id"]: entry for entry in completed["jobs"]}
    assert states[older_id] == {"job_id": older_id, "state": "cancelled", "cancel_requested": True}
    assert states[newer_id] == {"job_id": newer_id, "state": "done", "cancel_requested": False}
