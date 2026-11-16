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
    _probe_operation,
)
from app.deploy.pve_client import PveClient, PveError, PveSettings
from app.deploy.backends.probe_supervisor import PROBE_SUPERVISOR_PATH

SID = "probe-ledger-test"
HOST = "worker"
VMID = 900100
SERVICE = "web"
OPERATION = "c" * 32


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


def reserve(path: Path) -> None:
    with _placement_lock(str(path)) as db:
        _persist_reservation(db, scenario_id=SID, host_id=HOST, vmid=VMID, state="active")


def response(state: str, absent: bool) -> dict:
    return {"exitcode": 0, "stdout": f"state={state}\nresource_absent={str(absent).lower()}\n", "stderr": ""}


def test_cancel_first_writes_durable_tombstone_and_late_start_is_refused(tmp_path: Path) -> None:
    db_path = tmp_path / "reservations.sqlite3"
    reserve(db_path)
    backend = backend_for(db_path)
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
    cancelled = backend.cancel_probe_operation(
        SID, operation_id=OPERATION, vmid=VMID, host_id=HOST, service_id=SERVICE)
    late = backend.start_probe_operation(
        SID, operation_id=OPERATION, vmid=VMID, host_id=HOST, service_id=SERVICE,
        script="print('harmless')", timeout=5)

    assert cancelled["state"] == "cancelled" and cancelled["resource_absent"] is True
    assert late["state"] == "cancelled" and late["resource_absent"] is True
    assert calls == ["cancel"]
    with _placement_lock(str(db_path)) as db:
        operation = _probe_operation(db, OPERATION)
        assert operation and operation["state"] == "cancelled"
        assert _active_probe_for_worker(db, VMID) is None


def test_probe_mode_blocks_before_recording_or_calling_guest(tmp_path: Path) -> None:
    db_path = tmp_path / "reservations.sqlite3"
    reserve(db_path)
    backend = backend_for(db_path, mode="probe")
    backend._guest_exec = Mock(side_effect=AssertionError("probe mode must not call QGA"))

    result = backend.start_probe_operation(
        SID, operation_id=OPERATION, vmid=VMID, host_id=HOST, service_id=SERVICE,
        script="print('harmless')", timeout=5)

    assert result == {
        "state": "blocked", "resource_absent": True,
        "error": "live Proxmox mode is required to start a probe operation",
    }
    backend._guest_exec.assert_not_called()
    with _placement_lock(str(db_path)) as db:
        assert _probe_operation(db, OPERATION) is None


def test_start_first_holds_shared_lock_until_cancel_joins_and_absence_is_saved(tmp_path: Path) -> None:
    db_path = tmp_path / "reservations.sqlite3"
    reserve(db_path)
    backend = backend_for(db_path)
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
        "start", backend.start_probe_operation(
            SID, operation_id=OPERATION, vmid=VMID, host_id=HOST, service_id=SERVICE,
            script="print('harmless')", timeout=5)))
    start_thread.start()
    assert launch_entered.wait(1)

    cancel_thread = threading.Thread(target=lambda: outcomes.setdefault(
        "cancel", backend.cancel_probe_operation(
            SID, operation_id=OPERATION, vmid=VMID, host_id=HOST, service_id=SERVICE)))
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
    reserve(db_path)
    first_id, second_id = "1" * 32, "2" * 32
    with _placement_lock(str(db_path)) as db:
        db.execute(
            "INSERT INTO pve_probe_operations(operation_id,scenario_id,host_id,vmid,service_id,"
            "target_name,state,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (first_id, SID, HOST, VMID, SERVICE, f"cr-demo-{SID}-{SERVICE}", "running", "now"),
        )
        db.commit()
    backend = backend_for(db_path)
    backend._guest_exec = Mock(side_effect=AssertionError("second operation must not launch"))

    result = backend.start_probe_operation(
        SID, operation_id=second_id, vmid=VMID, host_id=HOST, service_id=SERVICE,
        script="print('harmless')", timeout=5)

    assert result["state"] == "failed" and result["resource_absent"] is True
    backend._guest_exec.assert_not_called()
    with _placement_lock(str(db_path)) as db:
        second = _probe_operation(db, second_id)
        assert second and second["state"] == "failed" and second["exitcode"] == 127


def test_uncertain_operation_remains_a_lifecycle_blocker(tmp_path: Path) -> None:
    db_path = tmp_path / "reservations.sqlite3"
    reserve(db_path)
    with _placement_lock(str(db_path)) as db:
        db.execute(
            "INSERT INTO pve_probe_operations(operation_id,scenario_id,host_id,vmid,service_id,"
            "target_name,state,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (OPERATION, SID, HOST, VMID, SERVICE, f"cr-demo-{SID}-{SERVICE}", "uncertain", "now"),
        )
        db.commit()
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
    backend._guest_exec = Mock(side_effect=TimeoutError("QGA response was lost"))

    result = backend.start_probe_operation(
        SID, operation_id=OPERATION, vmid=VMID, host_id=HOST, service_id=SERVICE,
        script="print('harmless')", timeout=5)

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
    with _placement_lock(str(db_path)) as db:
        _create_probe_operation(db, operation_id=OPERATION, scenario_id=SID, host_id=HOST,
                                vmid=VMID, service_id=SERVICE, target_name=f"cr-demo-{SID}-{SERVICE}",
                                state="running")
    backend._guest_exec = Mock(side_effect=TimeoutError("QGA response was lost"))

    uncertain = backend.cancel_probe_operation(
        SID, operation_id=OPERATION, vmid=VMID, host_id=HOST, service_id=SERVICE)

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
