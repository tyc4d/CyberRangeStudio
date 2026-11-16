"""Host-side operation ledger tests using an in-memory simulated QGA response.

These tests verify SQLite fencing and lock ordering only. They do not exercise PVE,
QGA, Docker, or a vulnerable image.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.deploy.backends.proxmox import (
    ProxmoxBackendError,
    ProxmoxBackend,
    _active_probe_for_worker,
    _create_probe_operation,
    _placement_lock,
    _persist_reservation,
    _reservation,
    _probe_operation,
    _update_probe_operation,
)
from app.deploy.pve_client import PveClient, PveError, PveSettings
from app.deploy.backends.probe_supervisor import PROBE_SUPERVISOR_PATH

SID = "probe-ledger-test"
HOST = "worker"
VMID = 900100
SERVICE = "web"
OPERATION = "c" * 32
JOB_ID = "d" * 32


def backend_for(path: Path, *, mode: str = "live") -> ProxmoxBackend:
    settings = PveSettings(
        base_url="https://192.0.2.1:8006", fingerprint="0" * 64,
        token_id="unit-test", token_secret="unit-test", mode=mode,
        reservation_db=str(path), task_poll_interval=0.01,
    )
    backend = ProxmoxBackend(settings, client=Mock())
    backend._assert_owned = Mock(return_value={})
    backend.isolation_report = Mock(return_value={"checked": True, "isolated": True})
    backend._install_probe_supervisor = Mock()
    return backend


def reserve(path: Path) -> str:
    with _placement_lock(str(path)) as db:
        _persist_reservation(db, scenario_id=SID, host_id=HOST, vmid=VMID, state="active")
        return _reservation(db, VMID)["generation_id"]


def reserve_operation(backend: ProxmoxBackend, *, operation_id: str = OPERATION,
                      job_id: str = JOB_ID, vmid: int = VMID,
                      host_id: str = HOST, scenario_id: str = SID,
                      service_id: str = SERVICE, generation_id: str | None = None) -> dict:
    if generation_id is None:
        with _placement_lock(str(backend.settings.reservation_db)) as db:
            held = _reservation(db, vmid)
            generation_id = held["generation_id"]
    return backend.reserve_probe_operation(scenario_id, vmid=vmid, host_id=host_id,
                                           generation_id=generation_id,
                                           operation_id=operation_id, service_id=service_id,
                                           job_id=job_id)


def start_operation(backend: ProxmoxBackend, reservation: dict, *,
                    operation_id: str = OPERATION, job_id: str = JOB_ID,
                    vmid: int = VMID, host_id: str = HOST,
                    scenario_id: str = SID, service_id: str = SERVICE) -> dict:
    return backend.start_probe_operation(
        scenario_id, vmid=vmid, host_id=host_id, generation_id=reservation["generation_id"],
        job_id=job_id, operation_id=operation_id, service_id=service_id,
        script="print('harmless')", timeout=5)


def cancel_operation(backend: ProxmoxBackend, reservation: dict, *,
                     operation_id: str = OPERATION, job_id: str | None = JOB_ID,
                     vmid: int = VMID, host_id: str = HOST,
                     scenario_id: str = SID, service_id: str = SERVICE) -> dict:
    return backend.cancel_probe_operation(
        scenario_id, operation_id=operation_id, vmid=vmid, host_id=host_id,
        generation_id=reservation["generation_id"], service_id=service_id, job_id=job_id)


def response(state: str, absent: bool) -> dict:
    return {"exitcode": 0, "stdout": f"state={state}\nresource_absent={str(absent).lower()}\n", "stderr": ""}


def test_cancel_first_writes_durable_tombstone_and_late_start_is_refused(tmp_path: Path) -> None:
    db_path = tmp_path / "reservations.sqlite3"
    reserve(db_path)
    backend = backend_for(db_path)
    reservation = reserve_operation(backend)
    guest_state: dict[str, str] = {}
    calls: list[str] = []

    def guest_exec(vmid, command, **kwargs):
        action, operation_id = command[2], command[3]
        calls.append(action)
        if action == "cancel":
            guest_state[operation_id] = "cancelled"
            return response("cancelled", True)
        if action == "start":
            if guest_state.get(operation_id) == "cancelled":
                return response("cancelled", True)
            guest_state[operation_id] = "running"
            return response("running", False)
        raise AssertionError(action)

    backend._guest_exec = guest_exec
    cancelled = cancel_operation(backend, reservation)
    late = start_operation(backend, reservation)

    assert cancelled["state"] == "cancelled" and cancelled["resource_absent"] is True
    assert late["state"] == "cancelled" and late["resource_absent"] is True
    assert calls == ["cancel"]
    with _placement_lock(str(db_path)) as db:
        operation = _probe_operation(db, OPERATION)
        assert operation and operation["state"] == "cancelled"
        assert _active_probe_for_worker(db, VMID) is None


def test_cancel_binds_legacy_operation_to_job_when_full_identity_matches(tmp_path: Path) -> None:
    db_path = tmp_path / "reservations.sqlite3"
    generation_id = reserve(db_path)
    with _placement_lock(str(db_path)) as db:
        _create_probe_operation(
            db, operation_id=OPERATION, scenario_id=SID, host_id=HOST, vmid=VMID,
            service_id=SERVICE, target_name=f"cr-demo-{SID}-{SERVICE}",
            generation_id=generation_id, state="running")
    backend = backend_for(db_path)
    calls: list[str] = []

    def guest_exec(vmid, command, **kwargs):
        action = command[2]
        calls.append(action)
        assert action == "cancel"
        return response("cancelled", True)

    backend._guest_exec = guest_exec
    cancelled = cancel_operation(backend, {"generation_id": generation_id}, job_id=JOB_ID)

    assert cancelled["state"] == "cancelled" and cancelled["resource_absent"] is True
    assert calls == ["cancel"]
    with _placement_lock(str(db_path)) as db:
        operation = _probe_operation(db, OPERATION)
        assert operation and operation["job_id"] == JOB_ID
        assert operation["state"] == "cancelled"


def test_cancel_does_not_bind_legacy_operation_when_identity_mismatches(tmp_path: Path) -> None:
    db_path = tmp_path / "reservations.sqlite3"
    generation_id = reserve(db_path)
    with _placement_lock(str(db_path)) as db:
        _create_probe_operation(
            db, operation_id=OPERATION, scenario_id=SID, host_id=HOST, vmid=VMID,
            service_id=SERVICE, target_name=f"cr-demo-{SID}-{SERVICE}",
            generation_id=generation_id, state="running")
    backend = backend_for(db_path)
    backend._guest_exec = Mock(side_effect=AssertionError("mismatched identity must not reach QGA"))

    with pytest.raises(ProxmoxBackendError, match="identity does not match"):
        cancel_operation(backend, {"generation_id": generation_id}, job_id=JOB_ID,
                         service_id="different-service")

    backend._guest_exec.assert_not_called()
    with _placement_lock(str(db_path)) as db:
        operation = _probe_operation(db, OPERATION)
        assert operation and operation["job_id"] is None
        assert operation["state"] == "running"


def test_cancel_migrates_1e0c4a3_ledger_and_binds_matching_job(tmp_path: Path) -> None:
    db_path = tmp_path / "reservations.sqlite3"
    connection = sqlite3.connect(db_path)
    connection.execute(
        "CREATE TABLE pve_worker_reservations ("
        "vmid INTEGER PRIMARY KEY CHECK(vmid BETWEEN 900100 AND 900999), "
        "scenario_id TEXT NOT NULL, host_id TEXT NOT NULL, state TEXT NOT NULL, "
        "updated_at TEXT NOT NULL, UNIQUE(scenario_id, host_id))")
    connection.execute(
        "CREATE TABLE pve_probe_operations ("
        "operation_id TEXT PRIMARY KEY CHECK(length(operation_id)=32), "
        "scenario_id TEXT NOT NULL, host_id TEXT NOT NULL, vmid INTEGER NOT NULL, "
        "service_id TEXT NOT NULL, target_name TEXT NOT NULL, state TEXT NOT NULL, "
        "updated_at TEXT NOT NULL, exitcode INTEGER, stdout_b64 TEXT, stderr_b64 TEXT)")
    connection.execute(
        "INSERT INTO pve_worker_reservations(vmid,scenario_id,host_id,state,updated_at) "
        "VALUES(?,?,?,?,?)", (VMID, SID, HOST, "active", "2026-11-15T00:00:00+00:00"))
    connection.execute(
        "INSERT INTO pve_probe_operations(operation_id,scenario_id,host_id,vmid,service_id,"
        "target_name,state,updated_at) VALUES(?,?,?,?,?,?,?,?)",
        (OPERATION, SID, HOST, VMID, SERVICE, f"cr-demo-{SID}-{SERVICE}", "running",
         "2026-11-15T00:01:00+00:00"))
    connection.commit()
    connection.close()

    backend = backend_for(db_path)
    with _placement_lock(str(db_path)) as db:
        worker = _reservation(db, VMID)
        operation = _probe_operation(db, OPERATION)
        assert worker and worker["state"] == "active" and worker["generation_id"]
        assert operation and operation["job_id"] is None
        assert operation["generation_id"] == worker["generation_id"]

    guest_commands: list[list[str]] = []

    def guest_exec(vmid, command, **kwargs):
        guest_commands.append(command)
        return response("cancelled", True)

    backend._guest_exec = guest_exec
    cancelled = cancel_operation(
        backend, {"generation_id": worker["generation_id"]}, job_id=JOB_ID)

    assert cancelled["state"] == "cancelled" and cancelled["resource_absent"] is True
    assert len(guest_commands) == 1
    assert guest_commands[0][2:4] == ["cancel", OPERATION]
    with _placement_lock(str(db_path)) as db:
        operation = _probe_operation(db, OPERATION)
        assert operation and operation["job_id"] == JOB_ID
        assert operation["generation_id"] == worker["generation_id"]
        assert operation["state"] == "cancelled"


def test_probe_mode_blocks_before_recording_or_calling_guest(tmp_path: Path) -> None:
    db_path = tmp_path / "reservations.sqlite3"
    reserve(db_path)
    backend = backend_for(db_path, mode="probe")
    backend._guest_exec = Mock(side_effect=AssertionError("probe mode must not call QGA"))

    result = reserve_operation(backend)

    assert result == {
        "state": "blocked",
        "error": "live Proxmox mode is required to reserve a probe operation",
    }
    backend._guest_exec.assert_not_called()
    with _placement_lock(str(db_path)) as db:
        assert _probe_operation(db, OPERATION) is None


def test_launch_fence_blocks_lifecycle_and_old_generation_cannot_start_after_same_vmid_redeploy(
        tmp_path: Path) -> None:
    db_path = tmp_path / "reservations.sqlite3"
    old_generation = reserve(db_path)
    backend = backend_for(db_path)
    backend._guest_exec = Mock(side_effect=AssertionError("stale operation must not reach QGA"))
    pinned = reserve_operation(backend)
    assert pinned["generation_id"] == old_generation

    with pytest.raises(ProxmoxBackendError, match="blocked by reserved probe operation"):
        backend.down(SID, vmid=VMID, host_id=HOST)
    with pytest.raises(ProxmoxBackendError, match="blocked by reserved probe operation"):
        backend.reset(SID, vmid=VMID, host_id=HOST)

    # Model a replacement with the same scenario, host, and VMID after an external
    # lifecycle actor ignored the fence. The immutable generation must still differ.
    with _placement_lock(str(db_path)) as db:
        db.execute("DELETE FROM pve_worker_reservations WHERE vmid=?", (VMID,))
        db.commit()
        _persist_reservation(db, scenario_id=SID, host_id=HOST, vmid=VMID, state="active")
        new_generation = _reservation(db, VMID)["generation_id"]
    assert new_generation != old_generation

    with pytest.raises(ProxmoxBackendError, match="matching active worker reservation"):
        start_operation(backend, pinned)
    backend._guest_exec.assert_not_called()


def test_start_first_holds_shared_lock_until_cancel_joins_and_absence_is_saved(tmp_path: Path) -> None:
    db_path = tmp_path / "reservations.sqlite3"
    reserve(db_path)
    backend = backend_for(db_path)
    reservation = reserve_operation(backend)
    launch_entered, allow_launch, cancel_entered = threading.Event(), threading.Event(), threading.Event()
    guest_state: dict[str, str] = {}
    outcomes: dict[str, dict] = {}

    def guest_exec(vmid, command, **kwargs):
        action, operation_id = command[2], command[3]
        if action == "start":
            launch_entered.set()
            assert allow_launch.wait(2)
            guest_state[operation_id] = "running"
            return response("running", False)
        if action == "cancel":
            cancel_entered.set()
            guest_state[operation_id] = "cancelled"
            return response("cancelled", True)
        if action == "wait":
            state = guest_state[operation_id]
            return response(state, state == "cancelled")
        raise AssertionError(action)

    backend._guest_exec = guest_exec
    start_thread = threading.Thread(target=lambda: outcomes.setdefault(
        "start", start_operation(backend, reservation)))
    start_thread.start()
    assert launch_entered.wait(1)

    cancel_thread = threading.Thread(target=lambda: outcomes.setdefault(
        "cancel", cancel_operation(backend, reservation)))
    cancel_thread.start()
    time.sleep(0.05)
    assert not cancel_entered.is_set(), "shared placement lock did not serialize cancel behind start"
    allow_launch.set()
    start_thread.join(2)
    cancel_thread.join(2)
    assert not start_thread.is_alive() and not cancel_thread.is_alive()
    assert outcomes["start"]["state"] == "running"
    assert outcomes["cancel"]["state"] == "cancelled"
    with _placement_lock(str(db_path)) as db:
        operation = _probe_operation(db, OPERATION)
        assert operation and operation["state"] == "cancelled"
        assert _active_probe_for_worker(db, VMID) is None


def test_second_operation_is_tombstoned_without_guest_launch(tmp_path: Path) -> None:
    db_path = tmp_path / "reservations.sqlite3"
    generation_id = reserve(db_path)
    first_id, second_id = "1" * 32, "2" * 32
    with _placement_lock(str(db_path)) as db:
        _create_probe_operation(db, operation_id=first_id, scenario_id=SID, host_id=HOST,
                                vmid=VMID, service_id=SERVICE, target_name=f"cr-demo-{SID}-{SERVICE}",
                                generation_id=generation_id, job_id=JOB_ID, state="running")
    backend = backend_for(db_path)
    backend._guest_exec = Mock(side_effect=AssertionError("second operation must not launch"))

    with pytest.raises(ProxmoxBackendError, match="worker is already fenced"):
        reserve_operation(backend, operation_id=second_id, job_id="2" * 32)

    backend._guest_exec.assert_not_called()
    with _placement_lock(str(db_path)) as db:
        second = _probe_operation(db, second_id)
        assert second is None


def test_uncertain_operation_remains_a_lifecycle_blocker(tmp_path: Path) -> None:
    db_path = tmp_path / "reservations.sqlite3"
    generation_id = reserve(db_path)
    with _placement_lock(str(db_path)) as db:
        _create_probe_operation(db, operation_id=OPERATION, scenario_id=SID, host_id=HOST,
                                vmid=VMID, service_id=SERVICE, target_name=f"cr-demo-{SID}-{SERVICE}",
                                generation_id=generation_id, job_id=JOB_ID, state="uncertain")
        active = _active_probe_for_worker(db, VMID)
        assert active == {"operation_id": OPERATION, "state": "uncertain"}

    backend = backend_for(db_path)
    with pytest.raises(ProxmoxBackendError, match="blocked by uncertain probe operation"):
        backend.down(SID, vmid=VMID, host_id=HOST)
    with pytest.raises(ProxmoxBackendError, match="blocked by uncertain probe operation"):
        backend.reset(SID, vmid=VMID, host_id=HOST)
    backend._assert_owned.assert_not_called()


def test_uncertain_launch_response_is_persisted_and_blocks_lifecycle(tmp_path: Path) -> None:
    db_path = tmp_path / "reservations.sqlite3"
    reserve(db_path)
    backend = backend_for(db_path)
    reservation = reserve_operation(backend)
    backend._guest_exec = Mock(side_effect=TimeoutError("QGA response was lost"))

    result = start_operation(backend, reservation)

    assert result["state"] == "uncertain" and result["resource_absent"] is False
    with _placement_lock(str(db_path)) as db:
        operation = _probe_operation(db, OPERATION)
        assert operation and operation["state"] == "uncertain"
        assert _active_probe_for_worker(db, VMID) == {"operation_id": OPERATION, "state": "uncertain"}
    with pytest.raises(ProxmoxBackendError, match="blocked by uncertain probe operation"):
        backend.down(SID, vmid=VMID, host_id=HOST)
    with pytest.raises(ProxmoxBackendError, match="blocked by uncertain probe operation"):
        backend.reset(SID, vmid=VMID, host_id=HOST)


def test_uncertain_cancel_response_keeps_worker_blocked_until_retry_confirms_absence(tmp_path: Path) -> None:
    db_path = tmp_path / "reservations.sqlite3"
    reserve(db_path)
    backend = backend_for(db_path)
    reservation = reserve_operation(backend)
    with _placement_lock(str(db_path)) as db:
        _update_probe_operation(db, OPERATION, state="running")
    backend._guest_exec = Mock(side_effect=TimeoutError("QGA response was lost"))

    uncertain = cancel_operation(backend, reservation)

    assert uncertain["state"] == "uncertain" and uncertain["resource_absent"] is False
    with _placement_lock(str(db_path)) as db:
        operation = _probe_operation(db, OPERATION)
        assert operation and operation["state"] == "uncertain"
    with pytest.raises(ProxmoxBackendError, match="blocked by uncertain probe operation"):
        backend.down(SID, vmid=VMID, host_id=HOST)


def test_pve_client_allows_only_the_fixed_supervisor_guest_file() -> None:
    client = PveClient.__new__(PveClient)
    client.settings = SimpleNamespace(mode="live")
    client._owner_proof = VMID
    path = f"/api2/json/nodes/pve4-bbf/qemu/{VMID}/agent/file-write"

    client._guard("POST", path, {}, {"file": PROBE_SUPERVISOR_PATH, "content": "#!/bin/sh\n"})
    with pytest.raises(PveError, match="strict allowlist"):
        client._guard("POST", path, {}, {"file": "/tmp/probe-supervisor.sh", "content": "bad"})
