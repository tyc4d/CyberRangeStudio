"""Reservation crash-recovery contract tests; no PVE, QGA, Docker, or network calls."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import Mock
from types import SimpleNamespace

import pytest

from app.deploy.backends import proxmox
from app.deploy.backends.proxmox import (
    OWNER,
    ProxmoxBackend,
    ProxmoxBackendError,
    _placement_lock,
    _persist_reservation,
    _reservation,
)
from app.deploy.pve_client import PveClient, PveError, PveSettings

SCENARIO = "recovery-scenario"
HOST = "worker"
VMID = 900100
CLONE_UPID = "UPID:pve4-bbf:00000001:00000002:00000003:qmclone:900000:root@pam:"
DELETE_UPID = "UPID:pve4-bbf:00000004:00000005:00000006:qmdestroy:900100:root@pam:"
PENDING_NAME = "cr-pending-recovery-scenari-abcdef123456"
NONCE = "abcdef123456"
SOURCE = {"source_sha256": "a" * 64, "source_commit": "c44e2e6", "host_id": "template-builder-01"}


def owned_config(scenario_id: str = SCENARIO, host_id: str = HOST,
                 creation_nonce: str | None = NONCE) -> dict:
    description = {"created_by": OWNER, "scenario_id": scenario_id, "host_id": host_id,
                   "role": "worker", "template": 900000,
                   "backend_instance": "codex-20261115"}
    if creation_nonce is not None:
        description["creation_nonce"] = creation_nonce
    return {
        "name": f"cr-{scenario_id}-worker",
        "tags": f"cyberrange;cr-scn-{scenario_id};cr-role-worker;cr-inst-codex-20261115",
        "description": json.dumps(description),
    }


class FakeRecoveryClient:
    def __init__(self, *, config: dict | None = None, task: dict | None = None,
                 in_pool: bool = True, delete_result: dict | None = None,
                 available_vmid: int = VMID, remove_on_wait: bool = True,
                 delete_terminal_result: dict | None = None):
        self.config = config or {"name": PENDING_NAME}
        self.task = task or {"status": "stopped", "exitstatus": "OK",
                             "task": "qmclone", "id": "900000", "node": "pve4-bbf"}
        self.members = [{"vmid": VMID}] if in_pool else []
        self.available_vmid = available_vmid
        self.remove_on_wait = remove_on_wait
        self.delete_result = delete_result or {"data": DELETE_UPID}
        self.delete_terminal_result = delete_terminal_result or {
            "data": {"status": "stopped", "exitstatus": "OK"}}
        self.task_calls: list[str] = []
        self.delete_calls: list[tuple] = []
        self.waited: list[str] = []
        self.before_delete = None
        self.before_wait = None

    def task_status(self, upid: str) -> dict:
        self.task_calls.append(upid)
        return dict(self.task)

    def request(self, method: str, path: str, **kwargs):
        assert method == "GET"
        if path == "/api2/json/pools/cr-range":
            return {"data": {"members": list(self.members)}}
        if path == "/api2/json/cluster/nextid":
            assert kwargs.get("params") == {"vmid": VMID}
            return {"data": self.available_vmid}
        if path == f"/api2/json/nodes/pve4-bbf/qemu/{VMID}/config":
            return {"data": dict(self.config)}
        raise AssertionError(f"unexpected API request: {method} {path}")

    def delete_creating_clone(self, vmid: int, *, pending_name: str,
                              source_metadata: dict, creation_nonce: str):
        if self.before_delete is not None:
            self.before_delete()
        self.delete_calls.append((vmid, pending_name, dict(source_metadata), creation_nonce))
        return self.delete_result

    def wait_task(self, upid: str):
        self.waited.append(upid)
        if self.remove_on_wait:
            self.members.clear()
        return {"data": {"status": "stopped", "exitstatus": "OK"}}

    def wait_task_exact(self, upid: str, *, task: str, task_id: str):
        if upid != DELETE_UPID or task != "qmdestroy" or task_id != str(VMID):
            raise PveError("exact delete task identity mismatch")
        if self.before_wait is not None:
            self.before_wait()
        self.waited.append(upid)
        if self.remove_on_wait:
            self.members.clear()
        return self.delete_terminal_result


class FakeOwnedDeleteClient:
    def __init__(self, *, delete_result, terminal_result=None, members=None,
                 available_vmid=VMID):
        self.delete_result = delete_result
        self.terminal_result = terminal_result
        self.members = [{"vmid": VMID}] if members is None else list(members)
        self.available_vmid = available_vmid
        self.delete_calls = []
        self.wait_calls = []
        self.before_delete = None
        self.before_wait = None

    def request(self, method, path, **kwargs):
        assert method == "GET"
        if path == "/api2/json/pools/cr-range":
            return {"data": {"members": list(self.members)}}
        if path == f"/api2/json/nodes/pve4-bbf/qemu/{VMID}/status/current":
            return {"data": {"status": "stopped"}}
        if path == "/api2/json/cluster/nextid":
            assert kwargs.get("params") == {"vmid": VMID}
            return {"data": self.available_vmid}
        raise AssertionError(f"unexpected API request: {method} {path}")

    def delete_owned_vmid(self, vmid, *, scenario_id, host_id, backend_instance, creation_nonce):
        if self.before_delete is not None:
            self.before_delete()
        self.delete_calls.append((vmid, scenario_id, host_id, backend_instance, creation_nonce))
        return self.delete_result

    def wait_task_exact(self, upid, *, task, task_id):
        self.wait_calls.append((upid, task, task_id))
        if self.before_wait is not None:
            self.before_wait()
        return self.terminal_result


def backend_for(path: Path, client) -> ProxmoxBackend:
    settings = PveSettings(base_url="https://192.0.2.1:8006", fingerprint="0" * 64,
                           token_id="unit-test", token_secret="unit-test", mode="live",
                           reservation_db=str(path))
    return ProxmoxBackend(settings, client=client)


def reserve(path: Path, *, scenario_id: str = SCENARIO, host_id: str = HOST,
            state: str = "cloning", upid: str | None = CLONE_UPID,
            pending_name: str | None = PENDING_NAME,
            source_metadata: dict | None = SOURCE,
            recovery_identity: dict | None = None,
            delete_upid: str | None = None,
            delete_intent: str | None = "not_requested") -> None:
    with _placement_lock(str(path)) as db:
        _persist_reservation(db, scenario_id=scenario_id, host_id=host_id, vmid=VMID,
                             state=state, provisional_name=pending_name, clone_upid=upid,
                             source_metadata=source_metadata,
                             recovery_identity=(recovery_identity if recovery_identity is not None else
                                                proxmox._recovery_identity(scenario_id, host_id, NONCE)),
                             delete_upid=delete_upid, delete_intent=delete_intent)


def get_reservation(path: Path) -> dict | None:
    with _placement_lock(str(path)) as db:
        return _reservation(db, VMID)


def capture_persistence(monkeypatch):
    persisted = []
    real_persist = proxmox._persist_reservation

    def capture(connection, **kwargs):
        persisted.append(dict(kwargs))
        return real_persist(connection, **kwargs)

    monkeypatch.setattr(proxmox, "_persist_reservation", capture)
    return persisted


def assert_pending_intent_persisted(persisted):
    assert any(row.get("delete_intent") == "pending" for row in persisted)


def test_absent_reservation_is_a_read_only_not_found(tmp_path):
    client = FakeRecoveryClient()
    backend = backend_for(tmp_path / "reservations.sqlite3", client)
    result = backend.recover_down(SCENARIO, host_id=HOST)
    assert result == {"found": False, "ok": True, "state": "not_found"}
    assert client.task_calls == []
    assert client.delete_calls == []


@pytest.mark.parametrize("state", ["cloning", "reconcile"])
def test_exact_provisional_clone_is_deleted_only_after_task_and_identity_proofs(monkeypatch, tmp_path, state):
    db_path = tmp_path / "reservations.sqlite3"
    reserve(db_path, state=state)
    client = FakeRecoveryClient()
    backend = backend_for(db_path, client)
    persisted = []
    real_persist = proxmox._persist_reservation

    def capture_persist(connection, **kwargs):
        persisted.append(dict(kwargs))
        return real_persist(connection, **kwargs)

    monkeypatch.setattr(proxmox, "_persist_reservation", capture_persist)

    client.before_delete = lambda: assert_pending_intent_persisted(persisted)

    def assert_delete_upid_precedes_poll():
        assert any(row.get("state") == "deleting" and row.get("delete_upid") == DELETE_UPID
                   for row in persisted)

    client.before_wait = assert_delete_upid_precedes_poll

    result = backend.recover_down(SCENARIO, host_id=HOST)

    assert result["found"] and result["ok"] and result["recovered_provisional"]
    assert client.task_calls == [CLONE_UPID]
    assert client.delete_calls == [(VMID, PENDING_NAME, SOURCE, NONCE)]
    assert client.waited == [DELETE_UPID]
    assert any(row.get("state") == "deleting" and row.get("delete_upid") == DELETE_UPID
               for row in persisted)
    assert get_reservation(db_path) is None


@pytest.mark.parametrize("delete_result,terminal_result", [
    ({"data": None}, None),
    ({"data": DELETE_UPID}, {"data": {"status": "stopped"}}),
    ({"data": DELETE_UPID}, {"data": {"status": "stopped", "exitstatus": "ERROR"}}),
    ({"data": DELETE_UPID}, {"data": {"status": "running", "exitstatus": "OK"}}),
])
def test_owned_down_retains_reservation_without_exact_successful_delete_proof(
        monkeypatch, tmp_path, delete_result, terminal_result):
    db_path = tmp_path / "reservations.sqlite3"
    reserve(db_path, state="active")
    client = FakeOwnedDeleteClient(delete_result=delete_result,
                                   terminal_result=terminal_result)
    backend = backend_for(db_path, client)
    backend._assert_owned = Mock(return_value=owned_config())
    backend._guest_exec = Mock(return_value={"exitcode": 0, "stdout": "", "stderr": ""})
    persisted = capture_persistence(monkeypatch)
    client.before_delete = lambda: assert_pending_intent_persisted(persisted)

    with pytest.raises(ProxmoxBackendError):
        backend.down(SCENARIO, vmid=VMID, host_id=HOST)

    assert client.delete_calls == [(VMID, SCENARIO, HOST, "codex-20261115", NONCE)]
    assert get_reservation(db_path)["state"] == "deleting"
    assert get_reservation(db_path)["delete_intent"] == "pending"


def test_owned_down_persists_delete_upid_before_poll_then_requires_absence(monkeypatch, tmp_path):
    db_path = tmp_path / "reservations.sqlite3"
    reserve(db_path, state="active")
    client = FakeOwnedDeleteClient(delete_result={"data": DELETE_UPID},
                                   terminal_result={"data": {"status": "stopped", "exitstatus": "OK"}},
                                   members=[])
    backend = backend_for(db_path, client)
    backend._assert_owned = Mock(return_value=owned_config())
    backend._guest_exec = Mock(return_value={"exitcode": 0, "stdout": "", "stderr": ""})
    persisted = []
    real_persist = proxmox._persist_reservation

    def capture_persist(connection, **kwargs):
        persisted.append(dict(kwargs))
        return real_persist(connection, **kwargs)

    monkeypatch.setattr(proxmox, "_persist_reservation", capture_persist)
    client.before_delete = lambda: assert_pending_intent_persisted(persisted)

    def assert_delete_upid_precedes_poll():
        assert any(row.get("state") == "deleting" and row.get("delete_upid") == DELETE_UPID
                   for row in persisted)

    client.before_wait = assert_delete_upid_precedes_poll

    result = backend.down(SCENARIO, vmid=VMID, host_id=HOST)

    assert result["ok"] is True
    assert client.wait_calls == [(DELETE_UPID, "qmdestroy", str(VMID))]
    assert any(row.get("state") == "deleting" and row.get("delete_upid") == DELETE_UPID
               for row in persisted)
    assert get_reservation(db_path) is None


def test_pve_delete_owned_vmid_rechecks_expected_creation_nonce_before_delete():
    client = PveClient.__new__(PveClient)
    client.request = Mock(side_effect=[
        {"data": {"members": [{"vmid": VMID}]}},
        {"data": owned_config(creation_nonce="000000000000")},
    ])

    with pytest.raises(PveError, match="ownership description"):
        client.delete_owned_vmid(VMID, scenario_id=SCENARIO, host_id=HOST,
                                 backend_instance="codex-20261115", creation_nonce=NONCE)

    assert client.request.call_count == 2


def test_pve_delete_guard_requires_nonce_bound_owned_proof():
    client = PveClient.__new__(PveClient)
    client.settings = SimpleNamespace(mode="live")
    path = f"/api2/json/nodes/pve4-bbf/qemu/{VMID}"

    client._delete_proof = (VMID, NONCE)
    client._guard("DELETE", path, {}, {})
    for proof in (VMID, (VMID, "bad")):
        client._delete_proof = proof
        with pytest.raises(PveError, match="ownership proof"):
            client._guard("DELETE", path, {}, {})


def test_pve_provisional_delete_requires_suffix_nonce_and_fresh_clone_proof():
    client = PveClient.__new__(PveClient)
    client.settings = SimpleNamespace(mode="live")
    calls = []

    def request(method, path, **kwargs):
        calls.append((method, path))
        if method == "GET" and path == "/api2/json/pools/cr-range":
            return {"data": {"members": [{"vmid": VMID}]}}
        if method == "GET" and path.endswith(f"/{VMID}/config"):
            return {"data": {"name": PENDING_NAME, "description": json.dumps(SOURCE)}}
        if method == "DELETE":
            client._guard(method, path, {}, kwargs.get("data") or {})
            return {"data": DELETE_UPID}
        raise AssertionError((method, path))

    client.request = request

    with pytest.raises(PveError, match="provisional clone identity"):
        client.delete_creating_clone(VMID, pending_name=PENDING_NAME,
                                     source_metadata=SOURCE, creation_nonce="000000000000")
    assert calls == []

    result = client.delete_creating_clone(VMID, pending_name=PENDING_NAME,
                                          source_metadata=SOURCE, creation_nonce=NONCE)
    assert result == {"data": DELETE_UPID}
    assert calls[-1] == ("DELETE", f"/api2/json/nodes/pve4-bbf/qemu/{VMID}")


@pytest.mark.parametrize("upid,terminal", [
    ("UPID:pve4-bbf:00000004:00000005:00000006:qmstart:900100:root@pam:",
     {"data": {"status": "stopped", "exitstatus": "OK"}}),
    ("UPID:pve4-bbf:00000004:00000005:00000006:qmdestroy:900101:root@pam:",
     {"data": {"status": "stopped", "exitstatus": "OK"}}),
    ("UPID:pve3-other:00000004:00000005:00000006:qmdestroy:900100:root@pam:",
     {"data": {"status": "stopped", "exitstatus": "OK"}}),
    (DELETE_UPID, {"data": {"status": "stopped"}}),
    (DELETE_UPID, {"data": {"status": "stopped", "exitstatus": "ERROR"}}),
])
def test_pve_wait_task_exact_rejects_wrong_task_or_non_success_terminal(upid, terminal):
    client = PveClient.__new__(PveClient)
    client.settings = SimpleNamespace(node="pve4-bbf", task_timeout=1,
                                      max_task_polls=1, task_poll_interval=0)
    client.request = Mock(return_value=terminal)

    with pytest.raises(PveError):
        client.wait_task_exact(upid, task="qmdestroy", task_id=str(VMID))

    if upid != DELETE_UPID:
        client.request.assert_not_called()


@pytest.mark.parametrize("state", ["active", "cloning", "clone_complete"])
def test_exact_owned_worker_uses_existing_down_path_and_clears_reservation(tmp_path, state):
    db_path = tmp_path / "reservations.sqlite3"
    reserve(db_path, state=state)
    client = FakeRecoveryClient(config=owned_config())
    backend = backend_for(db_path, client)
    backend._guest_exec = Mock(side_effect=PveError("guest agent unavailable"))
    backend._shutdown_and_destroy_owned = Mock()

    result = backend.recover_down(SCENARIO, host_id=HOST)

    assert result["found"] and result["ok"] and result["recovered_owned"]
    backend._shutdown_and_destroy_owned.assert_called_once()
    args, kwargs = backend._shutdown_and_destroy_owned.call_args
    assert args == (VMID, SCENARIO, HOST)
    assert kwargs["creation_nonce"] == NONCE
    assert callable(kwargs["on_delete_task"])
    assert get_reservation(db_path) is None


@pytest.mark.parametrize("creation_nonce", [None, "000000000000", "not-a-nonce"])
def test_owned_recovery_requires_the_reserved_creation_nonce(tmp_path, creation_nonce):
    db_path = tmp_path / "reservations.sqlite3"
    reserve(db_path, state="active")
    client = FakeRecoveryClient(config=owned_config(creation_nonce=creation_nonce))
    backend = backend_for(db_path, client)
    backend._shutdown_and_destroy_owned = Mock()

    result = backend.recover_down(SCENARIO, host_id=HOST)

    assert result["found"] and result["ok"] is False and result["state"] == "uncertain"
    assert "nonce" in result["error"]
    backend._shutdown_and_destroy_owned.assert_not_called()
    assert client.delete_calls == []
    assert get_reservation(db_path)["state"] == "active"


def test_wrong_scenario_does_not_select_reservation(tmp_path):
    db_path = tmp_path / "reservations.sqlite3"
    reserve(db_path)
    client = FakeRecoveryClient()
    backend = backend_for(db_path, client)

    result = backend.recover_down("other-scenario", host_id=HOST)

    assert result["found"] is False
    assert client.task_calls == [] and client.delete_calls == []
    assert get_reservation(db_path)["state"] == "cloning"


def test_wrong_host_is_uncertain_instead_of_reported_as_already_stopped(tmp_path):
    db_path = tmp_path / "reservations.sqlite3"
    reserve(db_path, host_id="other-host")
    client = FakeRecoveryClient()
    backend = backend_for(db_path, client)

    result = backend.recover_down(SCENARIO, host_id=HOST)

    assert result["found"] is True and result["ok"] is False
    assert result["state"] == "uncertain"
    assert "different host" in result["error"]
    assert client.task_calls == [] and client.delete_calls == []
    assert get_reservation(db_path)["state"] == "cloning"


@pytest.mark.parametrize("client_kwargs", [
    {"config": {"name": "cr-pending-other-scenario-abcdef123456"}},
    {"in_pool": False},
    {"task": {"status": "running", "task": "qmclone", "id": "900000", "node": "pve4-bbf"}},
    {"task": {"status": "stopped", "task": "qmclone", "id": "900000", "node": "pve4-bbf"}},
    {"task": {"status": "stopped", "exitstatus": "OK", "task": "qmstart", "id": "900000", "node": "pve4-bbf"}},
    {"task": {"status": "stopped", "exitstatus": "OK", "task": "qmclone", "id": "900100", "node": "pve4-bbf"}},
    {"task": {"status": "stopped", "exitstatus": "OK", "task": "qmclone", "id": "900000", "node": "pve3-other"}},
])
def test_wrong_name_pool_or_uncertain_task_retains_reservation(tmp_path, client_kwargs):
    db_path = tmp_path / "reservations.sqlite3"
    reserve(db_path)
    client = FakeRecoveryClient(**client_kwargs)
    backend = backend_for(db_path, client)

    result = backend.recover_down(SCENARIO, host_id=HOST)

    assert result["found"] and result["ok"] is False and result["state"] == "uncertain"
    assert client.delete_calls == []
    assert get_reservation(db_path)["state"] == "cloning"


def test_missing_persisted_upid_refuses_to_guess_or_clear_reservation(tmp_path):
    db_path = tmp_path / "reservations.sqlite3"
    reserve(db_path, state="clone_requested", upid=None)
    client = FakeRecoveryClient()
    backend = backend_for(db_path, client)

    result = backend.recover_down(SCENARIO, host_id=HOST)

    assert result["found"] and result["ok"] is False
    assert "not durably recorded" in result["error"]
    assert client.task_calls == [] and client.delete_calls == []
    assert get_reservation(db_path)["state"] == "clone_requested"


@pytest.mark.parametrize("identity", [
    {"scenario_id": "other-scenario", "host_id": HOST, "template_vmid": 900000,
     "backend_instance": "codex-20261115"},
    {"scenario_id": SCENARIO, "host_id": "other-host", "template_vmid": 900000,
     "backend_instance": "codex-20261115"},
    {"scenario_id": SCENARIO, "host_id": HOST, "template_vmid": 900001,
     "backend_instance": "codex-20261115"},
    {"scenario_id": SCENARIO, "host_id": HOST, "template_vmid": 900000,
     "backend_instance": "other-backend"},
])
def test_recovery_identity_mismatch_retains_reservation_without_delete(tmp_path, identity):
    db_path = tmp_path / "reservations.sqlite3"
    reserve(db_path, recovery_identity=identity)
    client = FakeRecoveryClient()
    backend = backend_for(db_path, client)

    result = backend.recover_down(SCENARIO, host_id=HOST)

    assert result["found"] and result["ok"] is False and result["state"] == "uncertain"
    assert client.task_calls == [] and client.delete_calls == []
    assert get_reservation(db_path)["state"] == "cloning"


def test_uncertain_post_to_upid_gap_remains_blocked_for_new_placement(tmp_path):
    db_path = tmp_path / "reservations.sqlite3"
    reserve(db_path, state="clone_requested", upid=None)
    client = FakeRecoveryClient()
    backend = backend_for(db_path, client)

    with _placement_lock(str(db_path)) as db:
        result = backend._up_locked(SCENARIO, "unused", host_id=HOST, reservation_db=db)

    assert result["ok"] is False and result["state"] == "reservation_conflict"
    assert "manual reconciliation" in result["error"]
    assert client.task_calls == [] and client.delete_calls == []
    assert get_reservation(db_path)["state"] == "clone_requested"


def test_deleting_reservation_without_upid_stays_manual_even_if_vm_looks_absent(tmp_path):
    db_path = tmp_path / "reservations.sqlite3"
    reserve(db_path, state="deleting", upid=None, delete_intent="pending")
    client = FakeRecoveryClient(in_pool=False, available_vmid=VMID)
    backend = backend_for(db_path, client)

    result = backend.recover_down(SCENARIO, host_id=HOST)

    assert result["found"] and result["ok"] is False and result["state"] == "uncertain"
    assert "without a durable UPID" in result["error"]
    assert client.task_calls == []
    assert get_reservation(db_path)["state"] == "deleting"


def test_pending_delete_intent_without_upid_is_manual_and_never_retried(tmp_path):
    db_path = tmp_path / "reservations.sqlite3"
    reserve(db_path, state="reconcile", delete_upid=None, delete_intent="pending")
    client = FakeRecoveryClient(in_pool=False, available_vmid=VMID)
    backend = backend_for(db_path, client)

    result = backend.recover_down(SCENARIO, host_id=HOST)

    assert result["found"] and result["ok"] is False and result["state"] == "uncertain"
    assert "delete may have been sent" in result["error"]
    assert client.task_calls == []
    assert client.delete_calls == []
    assert get_reservation(db_path)["state"] == "reconcile"


def test_provisional_delete_without_upid_stays_pending_after_reconcile_rewrite(tmp_path):
    db_path = tmp_path / "reservations.sqlite3"
    reserve(db_path, state="clone_complete", delete_upid=None,
            delete_intent="not_requested")
    client = FakeRecoveryClient(delete_result={"data": None})
    backend = backend_for(db_path, client)

    first = backend.recover_down(SCENARIO, host_id=HOST)
    assert first["found"] and first["ok"] is False and first["state"] == "uncertain"
    assert len(client.delete_calls) == 1
    assert get_reservation(db_path)["delete_intent"] == "pending"

    # This is the outer cleanup exception handler's lifecycle rewrite. The
    # monotonic marker must survive it so a later /down cannot send DELETE again.
    with _placement_lock(str(db_path)) as db:
        _persist_reservation(db, scenario_id=SCENARIO, host_id=HOST,
                             vmid=VMID, state="reconcile")

    second = backend.recover_down(SCENARIO, host_id=HOST)
    assert second["found"] and second["ok"] is False and second["state"] == "uncertain"
    assert "without a durable UPID" in second["error"]
    assert client.delete_calls == [(VMID, PENDING_NAME, SOURCE, NONCE)]
    assert get_reservation(db_path)["state"] == "reconcile"
    assert get_reservation(db_path)["delete_intent"] == "pending"


def test_legacy_reconcile_without_delete_marker_is_manual_only(tmp_path):
    db_path = tmp_path / "reservations.sqlite3"
    reserve(db_path, state="reconcile", delete_upid=None, delete_intent=None)
    client = FakeRecoveryClient(in_pool=False, available_vmid=VMID)
    backend = backend_for(db_path, client)

    result = backend.recover_down(SCENARIO, host_id=HOST)

    assert result["found"] and result["ok"] is False and result["state"] == "uncertain"
    assert "delete may have been sent" in result["error"]
    assert client.task_calls == []
    assert client.delete_calls == []
    assert get_reservation(db_path)["state"] == "reconcile"


@pytest.mark.parametrize("state", ["deleting", "reconcile"])
def test_saved_delete_upid_clears_only_after_exact_task_and_absence_proofs(tmp_path, state):
    db_path = tmp_path / "reservations.sqlite3"
    reserve(db_path, state=state, delete_upid=DELETE_UPID)
    client = FakeRecoveryClient(in_pool=False, available_vmid=VMID)
    backend = backend_for(db_path, client)

    result = backend.recover_down(SCENARIO, host_id=HOST)

    assert result["found"] and result["ok"] and result["recovered_deleted"]
    assert client.task_calls == []
    assert client.delete_calls == []
    assert client.waited == [DELETE_UPID]
    assert get_reservation(db_path) is None


@pytest.mark.parametrize("client_kwargs", [
    {"in_pool": True, "available_vmid": VMID, "remove_on_wait": False},
    {"in_pool": False, "available_vmid": VMID + 1},
])
def test_deleting_reservation_is_retained_without_independent_absence_proof(tmp_path, client_kwargs):
    db_path = tmp_path / "reservations.sqlite3"
    reserve(db_path, state="deleting", upid=None, delete_upid=DELETE_UPID)
    client = FakeRecoveryClient(**client_kwargs)
    backend = backend_for(db_path, client)

    result = backend.recover_down(SCENARIO, host_id=HOST)

    assert result["found"] and result["ok"] is False and result["state"] == "uncertain"
    assert "not proven absent" in result["error"]
    assert get_reservation(db_path)["state"] == "deleting"


def test_deleting_reservation_rejects_wrong_delete_upid_and_retains_row(tmp_path):
    db_path = tmp_path / "reservations.sqlite3"
    wrong_upid = "UPID:pve4-bbf:00000004:00000005:00000006:qmstart:900100:root@pam:"
    reserve(db_path, state="deleting", upid=None, delete_upid=wrong_upid)
    client = FakeRecoveryClient(in_pool=False, available_vmid=VMID)
    backend = backend_for(db_path, client)

    result = backend.recover_down(SCENARIO, host_id=HOST)

    assert result["found"] and result["ok"] is False and result["state"] == "uncertain"
    assert client.waited == []
    assert client.delete_calls == []
    assert get_reservation(db_path)["state"] == "deleting"


def test_reconcile_with_saved_delete_upid_retains_row_without_second_delete_when_task_uncertain(tmp_path):
    db_path = tmp_path / "reservations.sqlite3"
    reserve(db_path, state="reconcile", delete_upid=DELETE_UPID)
    client = FakeRecoveryClient(in_pool=False, available_vmid=VMID,
                                delete_terminal_result={"data": {"status": "running"}})
    backend = backend_for(db_path, client)

    result = backend.recover_down(SCENARIO, host_id=HOST)

    assert result["found"] and result["ok"] is False and result["state"] == "uncertain"
    assert client.waited == [DELETE_UPID]
    assert client.task_calls == []
    assert client.delete_calls == []
    assert get_reservation(db_path)["state"] == "reconcile"


def test_legacy_reservation_database_migrates_nullable_recovery_columns(tmp_path):
    db_path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE pve_worker_reservations ("
                       "vmid INTEGER PRIMARY KEY, scenario_id TEXT NOT NULL, host_id TEXT NOT NULL, "
                       "state TEXT NOT NULL, updated_at TEXT NOT NULL, generation_id TEXT, "
                       "UNIQUE(scenario_id, host_id))")
    connection.execute("INSERT INTO pve_worker_reservations VALUES(?,?,?,?,?,?)",
                       (VMID, SCENARIO, HOST, "active", "old", "legacy-generation"))
    connection.commit()
    connection.close()

    with _placement_lock(str(db_path)) as db:
        reservation = _reservation(db, VMID)
        columns = {row[1] for row in db.execute("PRAGMA table_info(pve_worker_reservations)")}

    assert {"provisional_name", "clone_upid", "source_metadata_json",
            "recovery_identity_json", "delete_upid", "delete_intent"}.issubset(columns)
    assert reservation["state"] == "active"
    assert reservation["generation_id"] == "legacy-generation"
    assert reservation["provisional_name"] is None
    assert reservation["clone_upid"] is None
    assert reservation["recovery_identity_json"] is None
    assert reservation["delete_upid"] is None
    assert reservation["delete_intent"] is None


def test_legacy_single_slot_database_migrates_without_claiming_recovery_identity(tmp_path):
    db_path = tmp_path / "legacy-singleton.sqlite3"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE pve_worker_reservation ("
                       "slot INTEGER PRIMARY KEY CHECK(slot=1), scenario_id TEXT NOT NULL, "
                       "host_id TEXT NOT NULL, vmid INTEGER NOT NULL, state TEXT NOT NULL, updated_at TEXT NOT NULL)")
    connection.execute("INSERT INTO pve_worker_reservation VALUES(1,?,?,?,?,?)",
                       (SCENARIO, HOST, VMID, "active", "old"))
    connection.commit()
    connection.close()

    with _placement_lock(str(db_path)) as db:
        reservation = _reservation(db, VMID)
        old_table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pve_worker_reservation'").fetchone()

    assert old_table is None
    assert reservation["scenario_id"] == SCENARIO
    assert reservation["host_id"] == HOST
    assert reservation["state"] == "active"
    assert reservation["clone_upid"] is None
    assert reservation["recovery_identity_json"] is None
    assert reservation["delete_upid"] is None
    assert reservation["delete_intent"] is None


def test_manager_calls_reservation_recovery_when_lifecycle_record_is_missing(monkeypatch):
    calls = []

    class Backend:
        def recover_down(self, scenario_id, *, host_id):
            calls.append((scenario_id, host_id))
            return {"found": True, "ok": False, "state": "uncertain",
                    "error": "clone task identity was not durably recorded; reservation retained"}

    monkeypatch.setattr(proxmox, "ProxmoxBackend", ProxmoxBackend)
    from app.deploy import manager
    monkeypatch.setattr(manager, "deploy_backend", lambda: "proxmox")
    monkeypatch.setattr(manager, "_backend_conflict", lambda *_: None)
    monkeypatch.setattr(manager, "_active_proxmox_deployment", lambda *_: None)
    monkeypatch.setattr(manager, "_proxmox_backend", lambda: Backend())
    monkeypatch.setattr(manager, "record", lambda sid, action, state, details: {"state": state, "details": details})

    result = manager.do_down(SCENARIO)

    assert calls == [(SCENARIO, "worker")]
    assert result["ok"] is False and result["state"] == "failed"
    assert "reservation retained" in result["command_result"]["stderr"]
    assert result["deployment_record"]["details"]["recovered_reservation"] is True


def test_manager_recovers_failed_up_orphan_instead_of_normal_down(monkeypatch):
    calls = []

    class Backend:
        def recover_down(self, scenario_id, *, host_id):
            calls.append(("recover", scenario_id, host_id))
            return {"found": True, "ok": False, "state": "uncertain",
                    "vmid": VMID, "error": "clone task is not terminal; reservation retained"}

        def down(self, scenario_id, *, vmid, host_id):
            calls.append(("down", scenario_id, vmid, host_id))
            raise AssertionError("orphan recovery must not use normal owned-worker down")

    from app.deploy import manager
    monkeypatch.setattr(manager, "deploy_backend", lambda: "proxmox")
    monkeypatch.setattr(manager, "_backend_conflict", lambda *_: None)
    monkeypatch.setattr(manager, "_active_proxmox_deployment",
                        lambda *_: {"vmid": VMID, "host_id": HOST, "orphan": True,
                                    "details": {"result": {"recoverable_orphan": {
                                        "vmid": VMID, "scenario_id": SCENARIO, "host_id": HOST}}}})
    monkeypatch.setattr(manager, "_proxmox_backend", lambda: Backend())
    monkeypatch.setattr(manager, "record", lambda sid, action, state, details:
                        {"state": state, "details": details})

    result = manager.do_down(SCENARIO)

    assert calls == [("recover", SCENARIO, HOST)]
    assert result["ok"] is False and result["state"] == "failed"
    assert "reservation retained" in result["command_result"]["stderr"]
    assert result["deployment_record"]["details"]["failed_up_orphan_record"] is True


def test_manager_does_not_report_orphan_record_stopped_when_reservation_is_absent(monkeypatch):
    class Backend:
        def recover_down(self, scenario_id, *, host_id):
            return {"found": False, "ok": True, "state": "not_found"}

        def down(self, *args, **kwargs):
            raise AssertionError("orphan record must not use normal down")

    from app.deploy import manager
    monkeypatch.setattr(manager, "deploy_backend", lambda: "proxmox")
    monkeypatch.setattr(manager, "_backend_conflict", lambda *_: None)
    monkeypatch.setattr(manager, "_active_proxmox_deployment",
                        lambda *_: {"vmid": VMID, "host_id": HOST, "orphan": True,
                                    "details": {"result": {"recoverable_orphan": {
                                        "vmid": VMID, "scenario_id": SCENARIO, "host_id": HOST}}}})
    monkeypatch.setattr(manager, "_proxmox_backend", lambda: Backend())
    monkeypatch.setattr(manager, "record", lambda sid, action, state, details:
                        {"state": state, "details": details})

    result = manager.do_down(SCENARIO)

    assert result["ok"] is False and result["state"] == "failed"
    assert "no matching durable PVE reservation" in result["command_result"]["stderr"]
    assert result["deployment_record"]["details"]["failed_up_orphan_record"] is True


def test_manager_active_up_record_uses_recovery_for_persisted_deleting_task(monkeypatch, tmp_path):
    db_path = tmp_path / "reservations.sqlite3"
    reserve(db_path, state="deleting", upid=None, delete_upid=DELETE_UPID)
    client = FakeRecoveryClient(in_pool=False, available_vmid=VMID)
    backend = backend_for(db_path, client)

    from app.deploy import manager
    monkeypatch.setattr(manager, "deploy_backend", lambda: "proxmox")
    monkeypatch.setattr(manager, "_backend_conflict", lambda *_: None)
    monkeypatch.setattr(manager, "_active_proxmox_deployment",
                        lambda *_: {"vmid": VMID, "host_id": HOST,
                                    "details": {"backend": "proxmox", "vmid": VMID,
                                                "host_id": HOST}})
    monkeypatch.setattr(manager, "_proxmox_backend", lambda: backend)
    monkeypatch.setattr(manager, "record", lambda sid, action, state, details:
                        {"state": state, "details": details})

    result = manager.do_down(SCENARIO)

    assert result["ok"] is True and result["state"] == "stopped"
    assert client.waited == [DELETE_UPID]
    assert get_reservation(db_path) is None
    assert result["deployment_record"]["details"]["lifecycle_record_present"] is True
