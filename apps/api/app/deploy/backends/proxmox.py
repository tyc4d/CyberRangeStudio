"""Proxmox runtime backend. Docker and Compose run only inside worker VMs via QGA."""
from __future__ import annotations

import hashlib
import base64
import json
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote

import yaml

from app.deploy.pve_client import PveClient, PveError, PveSettings, PROTECTED_VMIDS, redact
from app.deploy.backends.probe_supervisor import PROBE_SUPERVISOR_PATH, PROBE_SUPERVISOR_SCRIPT

WORKER_MEMORY_MIB = 4096
WORKER_VCPUS = 2
WORKER_DISK_GIB = 20
# Owner-approved 2026-11-16: at most five product worker VMs (900100-900999) at once.
# Node/pool/storage preflight remains authoritative and can allow fewer than five.
MAX_WORKER_VMS = 5
OWNER = "cyberrange"
_BACKEND_INSTANCE = "codex-20261115"
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
_ISOLATED_BRIDGE_OPT = "com.docker.network.bridge.gateway_mode_ipv4"
_ISOLATED_BRIDGE_OPTIONS = {_ISOLATED_BRIDGE_OPT: "isolated"}
_DEMO_APP_SOURCE = Path(__file__).resolve().parents[5] / "infra" / "templates" / "demo-app"
_DEMO_APP_GUEST = "/opt/cr-runtime/demo-app"
_COMPOSE_ENV_GUEST = "/opt/cr-runtime/compose.env"
_PROBE_ACTIVE_STATES = ("reserved", "starting", "running", "cancel_requested", "uncertain")
_PROBE_TERMINAL_STATES = ("cancelled", "completed", "failed")


class ProxmoxBackendError(RuntimeError):
    pass


def _safe_id(value: str, label: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ProxmoxBackendError(f"invalid {label}")
    return value


def _project_name(scenario_id: str) -> str:
    return f"cr-demo-{scenario_id}"


def _compose_command(scenario_id: str, *args: str) -> list[str]:
    return ["/usr/bin/docker", "compose", "--env-file", _COMPOSE_ENV_GUEST,
            "--project-name", _project_name(scenario_id),
            "--file", "/opt/cr-runtime/docker-compose.yml", *args]


def _safe_guest_diagnostic(value: Any, secrets_to_redact: tuple[str, ...] = ()) -> str:
    text = str(redact(str(value or "")))
    for secret in secrets_to_redact:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text[:1500]


def _pve_vm_name_id(scenario_id: str) -> str:
    """PVE VM names are DNS labels; scenario IDs may contain underscores."""
    return scenario_id.replace("_", "-")


def _data(result: Any) -> Any:
    return result.get("data", result) if isinstance(result, Mapping) else result


@contextmanager
def _placement_lock(database_path: str):
    """Serialize placement and expose the durable shared reservation database."""
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=60, isolation_level=None)
    try:
        connection.execute("PRAGMA busy_timeout=60000")
        connection.execute("BEGIN EXCLUSIVE")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS pve_worker_reservations ("
            "vmid INTEGER PRIMARY KEY CHECK(vmid BETWEEN 900100 AND 900999), "
            "scenario_id TEXT NOT NULL, host_id TEXT NOT NULL, state TEXT NOT NULL, "
            "updated_at TEXT NOT NULL, generation_id TEXT, UNIQUE(scenario_id, host_id))"
        )
        reservation_columns = {str(row[1]) for row in connection.execute(
            "PRAGMA table_info(pve_worker_reservations)").fetchall()}
        if "generation_id" not in reservation_columns:
            connection.execute("ALTER TABLE pve_worker_reservations ADD COLUMN generation_id TEXT")
        for (vmid,) in connection.execute(
                "SELECT vmid FROM pve_worker_reservations WHERE generation_id IS NULL OR generation_id=''"
        ).fetchall():
            connection.execute("UPDATE pve_worker_reservations SET generation_id=? WHERE vmid=?",
                                (secrets.token_hex(16), vmid))
        connection.execute(
            "CREATE TABLE IF NOT EXISTS pve_probe_operations ("
            "operation_id TEXT PRIMARY KEY CHECK(length(operation_id)=32), "
            "scenario_id TEXT NOT NULL, host_id TEXT NOT NULL, vmid INTEGER NOT NULL, "
            "service_id TEXT NOT NULL, target_name TEXT NOT NULL, job_id TEXT, generation_id TEXT, state TEXT NOT NULL, "
            "updated_at TEXT NOT NULL, exitcode INTEGER, stdout_b64 TEXT, stderr_b64 TEXT)"
        )
        operation_columns = {str(row[1]) for row in connection.execute(
            "PRAGMA table_info(pve_probe_operations)").fetchall()}
        if "job_id" not in operation_columns:
            connection.execute("ALTER TABLE pve_probe_operations ADD COLUMN job_id TEXT")
        if "generation_id" not in operation_columns:
            connection.execute("ALTER TABLE pve_probe_operations ADD COLUMN generation_id TEXT")
        connection.execute(
            "UPDATE pve_probe_operations SET generation_id=(SELECT generation_id "
            "FROM pve_worker_reservations WHERE pve_worker_reservations.vmid=pve_probe_operations.vmid) "
            "WHERE generation_id IS NULL OR generation_id=''"
        )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS pve_one_active_probe_per_worker_v2 "
            "ON pve_probe_operations(vmid) WHERE state IN "
            "('reserved','starting','running','cancel_requested','uncertain')"
        )
        _migrate_singleton_reservation(connection)
        connection.execute(
            "UPDATE pve_probe_operations SET generation_id=(SELECT generation_id "
            "FROM pve_worker_reservations WHERE pve_worker_reservations.vmid=pve_probe_operations.vmid) "
            "WHERE generation_id IS NULL OR generation_id=''"
        )
        # Persist schema upgrades and legacy generation backfills before callers
        # read or act on their values, then hold the lock for the caller's work.
        connection.commit()
        connection.execute("BEGIN EXCLUSIVE")
        yield connection
    finally:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        connection.close()


def _migrate_singleton_reservation(connection: sqlite3.Connection) -> None:
    """Move the pre-2026-11-15 single-slot row into the per-VMID table, atomically."""
    legacy = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='pve_worker_reservation'"
    ).fetchone()
    if legacy is None:
        return
    rows = connection.execute(
        "SELECT scenario_id, host_id, vmid, state, updated_at FROM pve_worker_reservation"
    ).fetchall()
    for row in rows:
        connection.execute(
            "INSERT INTO pve_worker_reservations(vmid, scenario_id, host_id, state, updated_at) "
            "VALUES(?, ?, ?, ?, ?)", (int(row[2]), row[0], row[1], row[3], row[4]),
        )
        connection.execute("UPDATE pve_worker_reservations SET generation_id=? WHERE vmid=?",
                           (secrets.token_hex(16), int(row[2])))
    connection.execute("DROP TABLE pve_worker_reservation")
    connection.commit()
    connection.execute("BEGIN EXCLUSIVE")


def _reservations(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT scenario_id, host_id, vmid, state, generation_id FROM pve_worker_reservations ORDER BY vmid"
    ).fetchall()
    return [{"scenario_id": row[0], "host_id": row[1], "vmid": int(row[2]), "state": row[3],
             "generation_id": row[4]}
            for row in rows]


def _reservation(connection: sqlite3.Connection, vmid: int) -> dict[str, Any] | None:
    return next((held for held in _reservations(connection) if held["vmid"] == vmid), None)


def _persist_reservation(connection: sqlite3.Connection, *, scenario_id: str,
                         host_id: str, vmid: int, state: str) -> None:
    cursor = connection.execute(
        "INSERT INTO pve_worker_reservations(vmid, scenario_id, host_id, state, updated_at,generation_id) "
        "VALUES(?, ?, ?, ?, ?, ?) ON CONFLICT(vmid) DO UPDATE SET "
        "state=excluded.state, updated_at=excluded.updated_at "
        "WHERE scenario_id=excluded.scenario_id AND host_id=excluded.host_id",
        (vmid, scenario_id, host_id, state, datetime.now(timezone.utc).isoformat(), secrets.token_hex(16)),
    )
    if cursor.rowcount != 1:
        raise ProxmoxBackendError("durable worker reservation identity changed; manual reconciliation required")
    connection.commit()
    connection.execute("BEGIN EXCLUSIVE")


def _clear_reservation(connection: sqlite3.Connection, *, scenario_id: str,
                       host_id: str, vmid: int) -> None:
    cursor = connection.execute(
        "DELETE FROM pve_worker_reservations WHERE vmid=? AND scenario_id=? AND host_id=?",
        (vmid, scenario_id, host_id),
    )
    if cursor.rowcount != 1:
        raise ProxmoxBackendError("durable worker reservation identity changed; manual reconciliation required")
    connection.commit()
    connection.execute("BEGIN EXCLUSIVE")


def _probe_operation(connection: sqlite3.Connection, operation_id: str) -> dict[str, Any] | None:
    row = connection.execute(
        "SELECT operation_id, scenario_id, host_id, vmid, service_id, target_name, state, "
        "exitcode, stdout_b64, stderr_b64, job_id, generation_id "
        "FROM pve_probe_operations WHERE operation_id=?",
        (operation_id,),
    ).fetchone()
    if row is None:
        return None
    return {"operation_id": row[0], "scenario_id": row[1], "host_id": row[2], "vmid": int(row[3]),
            "service_id": row[4], "target_name": row[5], "state": row[6], "exitcode": row[7],
            "stdout_b64": row[8], "stderr_b64": row[9], "job_id": row[10],
            "generation_id": row[11]}


def _bind_legacy_probe_job(connection: sqlite3.Connection, *, operation_id: str,
                            scenario_id: str, host_id: str, vmid: int, service_id: str,
                            target_name: str, generation_id: str, job_id: str) -> dict[str, Any]:
    """Bind an older operation row only when its complete pinned identity matches."""
    cursor = connection.execute(
        "UPDATE pve_probe_operations SET job_id=?, updated_at=? "
        "WHERE operation_id=? AND scenario_id=? AND host_id=? AND vmid=? AND service_id=? "
        "AND target_name=? AND generation_id=? AND job_id IS NULL",
        (job_id, datetime.now(timezone.utc).isoformat(), operation_id, scenario_id, host_id,
         vmid, service_id, target_name, generation_id),
    )
    if cursor.rowcount != 1:
        raise ProxmoxBackendError("legacy probe operation cannot be bound to this job identity")
    connection.commit()
    connection.execute("BEGIN EXCLUSIVE")
    operation = _probe_operation(connection, operation_id)
    expected = (scenario_id, host_id, vmid, service_id, target_name, generation_id)
    if (operation is None or (operation["scenario_id"], operation["host_id"], operation["vmid"],
                              operation["service_id"], operation["target_name"],
                              operation.get("generation_id")) != expected
            or operation.get("job_id") != job_id):
        raise ProxmoxBackendError("legacy probe operation job binding could not be confirmed")
    return operation


def _create_probe_operation(connection: sqlite3.Connection, *, operation_id: str,
                            scenario_id: str, host_id: str, vmid: int, service_id: str,
                            target_name: str, generation_id: str, state: str,
                            job_id: str | None = None) -> None:
    try:
        connection.execute(
            "INSERT INTO pve_probe_operations(operation_id,scenario_id,host_id,vmid,service_id,"
            "target_name,job_id,generation_id,state,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (operation_id, scenario_id, host_id, vmid, service_id, target_name, job_id,
             generation_id, state,
             datetime.now(timezone.utc).isoformat()),
        )
    except sqlite3.IntegrityError as exc:
        raise ProxmoxBackendError("probe operation is already registered or another operation is unresolved") from exc
    connection.commit()
    connection.execute("BEGIN EXCLUSIVE")


def _update_probe_operation(connection: sqlite3.Connection, operation_id: str, *, state: str,
                            exitcode: int | None = None, stdout_b64: str | None = None,
                            stderr_b64: str | None = None) -> None:
    cursor = connection.execute(
        "UPDATE pve_probe_operations SET state=?, updated_at=?, exitcode=?, stdout_b64=?, stderr_b64=? "
        "WHERE operation_id=?",
        (state, datetime.now(timezone.utc).isoformat(), exitcode, stdout_b64, stderr_b64, operation_id),
    )
    if cursor.rowcount != 1:
        raise ProxmoxBackendError("durable probe operation identity changed; manual reconciliation required")
    connection.commit()
    connection.execute("BEGIN EXCLUSIVE")


def _active_probe_for_worker(connection: sqlite3.Connection, vmid: int) -> dict[str, Any] | None:
    placeholders = ",".join("?" for _ in _PROBE_ACTIVE_STATES)
    row = connection.execute(
        f"SELECT operation_id,state FROM pve_probe_operations WHERE vmid=? AND state IN ({placeholders}) LIMIT 1",
        (vmid, *_PROBE_ACTIVE_STATES),
    ).fetchone()
    return {"operation_id": row[0], "state": row[1]} if row else None


def _active_probe_operations_for_scenario(connection: sqlite3.Connection,
                                          scenario_id: str) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in _PROBE_ACTIVE_STATES)
    rows = connection.execute(
        "SELECT operation_id,scenario_id,host_id,vmid,service_id,state,job_id,generation_id "
        f"FROM pve_probe_operations WHERE scenario_id=? AND state IN ({placeholders}) "
        "ORDER BY updated_at,operation_id",
        (scenario_id, *_PROBE_ACTIVE_STATES),
    ).fetchall()
    return [{"operation_id": row[0], "scenario_id": row[1], "host_id": row[2],
             "vmid": int(row[3]), "service_id": row[4], "state": row[5], "job_id": row[6],
             "generation_id": row[7]}
            for row in rows]


def _normalize_compose(document: str, scenario_id: str) -> tuple[str, dict[str, Any]]:
    """Remove API-host-only gateway wiring and reject ports/non-internal lab networks."""
    try:
        parsed = yaml.safe_load(document)
    except yaml.YAMLError as exc:
        raise ProxmoxBackendError(f"invalid Compose YAML: {exc}") from None
    if not isinstance(parsed, dict) or not isinstance(parsed.get("services"), dict):
        raise ProxmoxBackendError("Compose must define a services mapping")
    services = parsed["services"]
    services.pop("cr-gateway", None)
    networks = parsed.get("networks", {})
    if not isinstance(networks, dict):
        raise ProxmoxBackendError("Compose networks must be a mapping")
    networks.pop("edge", None)
    for service_name, service in services.items():
        if not isinstance(service, dict):
            raise ProxmoxBackendError(f"Compose service {service_name} must be a mapping")
        service.pop("ports", None)
        attachments = service.get("networks")
        if isinstance(attachments, list):
            service["networks"] = [name for name in attachments if name != "edge"]
        elif isinstance(attachments, dict):
            attachments.pop("edge", None)
        elif attachments is not None:
            raise ProxmoxBackendError(f"Compose service {service_name} has invalid network attachments")
        else:
            raise ProxmoxBackendError(f"Compose service {service_name} must name an internal lab network")
        if service.get("network_mode") or service.get("external_links"):
            raise ProxmoxBackendError(f"Compose service {service_name} uses unsupported host networking")
        if "build" in service:
            build = service["build"]
            name_prefix = f"cr-demo-{scenario_id}-"
            container_name = service.get("container_name")
            host_id = (container_name[len(name_prefix):]
                       if isinstance(container_name, str) and container_name.startswith(name_prefix) else "")
            if (not isinstance(build, dict)
                    or build != {"context": "../../templates/demo-app", "dockerfile": "Dockerfile", "pull": False}
                    or not host_id or not _ID_RE.fullmatch(host_id)
                    or container_name != f"cr-demo-{scenario_id}-{host_id}"
                    or service.get("image") != f"{container_name}:local"):
                raise ProxmoxBackendError(
                    f"Compose service {service_name} has an unsupported build identity or context; "
                    "only the fixed demo-app template with generated scenario/host identity is supported"
                )
            service["build"] = {"context": "./demo-app", "dockerfile": "Dockerfile", "pull": False}
        referenced = set(service.get("networks", [])) if isinstance(service.get("networks"), list) else set(service.get("networks", {}))
        if not referenced or not referenced.issubset(networks):
            raise ProxmoxBackendError(f"Compose service {service_name} has no valid internal network attachment")
    for network_name, network in networks.items():
        if (not isinstance(network, dict) or network.get("internal") is not True
                or network.get("driver") not in (None, "bridge")
                or network.get("driver_opts") != _ISOLATED_BRIDGE_OPTIONS):
            raise ProxmoxBackendError(
                f"Compose network {network_name} must use the default bridge with internal isolated gateway mode"
            )
    parsed["networks"] = networks
    normalized = yaml.safe_dump(parsed, sort_keys=False, allow_unicode=True)
    return normalized, parsed


def _demo_app_files(compose: Mapping[str, Any]) -> dict[str, str]:
    services = compose.get("services", {})
    if not any(isinstance(service, dict) and "build" in service for service in services.values()):
        return {}
    files: dict[str, str] = {}
    for filename in ("Dockerfile", "server.py"):
        source = _DEMO_APP_SOURCE / filename
        try:
            content = source.read_text(encoding="utf-8")
        except OSError as exc:
            raise ProxmoxBackendError(f"fixed demo-app build file is unavailable: {filename}") from exc
        if len(content.encode("utf-8")) > 60_000:
            raise ProxmoxBackendError(f"fixed demo-app build file exceeds the QGA write bound: {filename}")
        files[f"{_DEMO_APP_GUEST}/{filename}"] = content
    return files


class ProxmoxBackend:
    """One disposable worker VM per scenario; no host Docker fallback exists here."""

    def __init__(self, settings: PveSettings | None = None, *, client: PveClient | None = None):
        self.settings = settings or PveSettings.from_env()
        self.client = client or PveClient(self.settings)

    @classmethod
    def from_env(cls) -> "ProxmoxBackend":
        return cls(PveSettings.from_env())

    def _get(self, path: str, *, params: Mapping[str, Any] | None = None) -> Any:
        return _data(self.client.request("GET", path, params=params))

    def _write(self, method: str, path: str, data: Mapping[str, Any] | None = None, purpose: str = "") -> Any:
        result = self.client.request(method, path, data=data, purpose=purpose)
        if self.settings.mode == "dry-run":
            return result
        self._await_operation(result)
        return result

    def _clone_worker(self, vmid: int, pending_name: str) -> None:
        path = f"/api2/json/nodes/pve4-bbf/qemu/900000/clone"
        result = self.client.request("POST", path,
                                     data={"newid": vmid, "name": pending_name, "pool": "cr-range", "full": 0},
                                     purpose="clone approved Linux worker template")
        if self.settings.mode == "dry-run":
            return
        payload = _data(result)
        upid = payload.get("upid") if isinstance(payload, Mapping) else payload
        if not isinstance(upid, str) or not upid.startswith("UPID:"):
            raise PveError("clone response did not contain a valid asynchronous task UPID")
        self.client.wait_task(upid)

    def _owned_write(self, method: str, path: str, data: Mapping[str, Any] | None,
                     scenario_id: str, host_id: str, purpose: str) -> Any:
        result = self.client.request_owned(method, path, scenario_id=scenario_id, host_id=host_id,
                                           backend_instance=_BACKEND_INSTANCE, data=data, purpose=purpose)
        if self.settings.mode != "dry-run":
            self._await_operation(result)
        return result

    def _await_operation(self, result: Any) -> None:
        payload = _data(result)
        if isinstance(payload, str) and payload.startswith("UPID:"):
            self.client.wait_task(payload)
        elif isinstance(payload, Mapping) and payload.get("upid"):
            self.client.wait_task(str(payload["upid"]))

    def bridge_v1_report(self) -> dict[str, Any]:
        """Read-only fail-closed proof that the approved lab bridge has no address/uplink."""
        iface = self.settings.bridge
        try:
            rows = self._get("/api2/json/nodes/pve4-bbf/network")
            if not isinstance(rows, list):
                raise ProxmoxBackendError("node network response is not a list")
            matches = [row for row in rows if isinstance(row, Mapping) and row.get("iface") == iface]
            if len(matches) != 1:
                raise ProxmoxBackendError(f"node network response must contain exactly one {iface} interface")
            row = matches[0]
            errors: list[str] = []
            if row.get("type") != "bridge":
                errors.append("interface is not explicitly a Linux bridge")
            for method_field in ("method", "method6"):
                if row.get(method_field) != "manual":
                    errors.append(f"{method_field} is not explicitly manual")
            # The list endpoint schema exposes bridge_ports. Missing is unknown, not empty.
            if "bridge_ports" not in row:
                errors.append("bridge member-port configuration is missing")
            elif row.get("bridge_ports") != "":
                errors.append("bridge has a configured or unverified member port")
            address_fields = ("address", "netmask", "cidr", "address6", "netmask6", "cidr6",
                              "gateway", "gateway6", "gw", "gw6")
            configured_addresses = {key: row[key] for key in address_fields
                                    if key in row and row[key] not in (None, "")}
            if configured_addresses:
                errors.append("bridge has configured address or gateway fields")
            evidence_fields = ("iface", "type", "active", "exists", "autostart", "method", "method6",
                               "families", "bridge_ports", *address_fields)
            evidence = {key: row[key] for key in evidence_fields if key in row}
            evidence["address_state"] = {
                key: ("not_configured" if key not in row or row[key] in (None, "") else row[key])
                for key in address_fields
            }
            return {"checked": True, "ok": not errors, "iface": iface,
                    "evidence": evidence, "errors": errors}
        except (PveError, ProxmoxBackendError, KeyError, TypeError, ValueError) as exc:
            return {"checked": False, "ok": False, "iface": iface,
                    "evidence": {}, "errors": [str(redact(str(exc)))[:500]]}

    def preflight(self) -> dict[str, Any]:
        """Read-only readiness and capacity report; absence/failure means not ready."""
        report: dict[str, Any] = {"backend": "proxmox", "mode": self.settings.mode, "ok": False, "checks": {},
                                  "placement_target": self.placement_target()}
        try:
            bridge_v1 = self.bridge_v1_report()
            report["checks"]["bridge_v1"] = bridge_v1
            if not bridge_v1.get("checked") or not bridge_v1.get("ok"):
                detail = "; ".join(bridge_v1.get("errors", [])) or "bridge state is unverified"
                raise ProxmoxBackendError(f"V1 isolated bridge check failed: {detail}")
            version = self._get("/api2/json/version")
            report["checks"]["version"] = version
            if str(version.get("version", "")).split(".")[:2] != ["9", "2"]:
                raise ProxmoxBackendError("PVE version is not the approved 9.2.x line")
            node_status = self._get("/api2/json/nodes/pve4-bbf/status")
            pool = self._get("/api2/json/pools/cr-range")
            storage = self._get("/api2/json/nodes/pve4-bbf/storage/local-lvm/status")
            template = self._get("/api2/json/nodes/pve4-bbf/qemu/900000/config")
            template_status = self._get("/api2/json/nodes/pve4-bbf/qemu/900000/status/current")
            pool_members = _pool_vmids(pool.get("members", []))
            tags = set(filter(None, str(template.get("tags", "")).split(";")))
            desc = _description(template.get("description", ""))
            boot_disk = str(template.get("bootdisk", ""))
            if not boot_disk:
                boot_match = re.search(r"(?:^|;)order=([a-z]+\d+)", str(template.get("boot", "")))
                boot_disk = boot_match.group(1) if boot_match else ""
            boot_volume = str(template.get(boot_disk, "")) if boot_disk else ""
            boot_size_gib = _disk_size_gib(boot_volume)
            disk_keys = {key for key in template
                         if re.fullmatch(r"(?:scsi|sata|virtio|ide)\d+|unused\d+|efidisk\d+|tpmstate\d+", key)}
            disks_approved = (disk_keys == {"scsi0", "ide2"}
                              and str(template.get("scsi0", "")).startswith("local-lvm:")
                              and str(template.get("ide2", "")) ==
                              "local-lvm:vm-900000-cloudinit,media=cdrom")
            guest_agent = str(template.get("agent", ""))
            agent_enabled = guest_agent == "1" or "enabled=1" in guest_agent.split(",")
            template_ok = (900000 in pool_members and
                           {"cyberrange", "cr-template", "cr-role-template", "cr-inst-codex-20261115"}.issubset(tags) and
                           bool(re.fullmatch(r"[a-fA-F0-9]{64}", str(desc.get("source_sha256", "")))) and
                           bool(desc.get("source_commit")) and bool(desc.get("host_id")) and
                           str(template.get("template", "0")) == "1" and
                           template_status.get("status") == "stopped" and
                           not any(re.fullmatch(r"net\d+", key) and value for key, value in template.items()) and
                           agent_enabled and bool(boot_disk) and boot_volume.startswith("local-lvm:")
                           and boot_disk == "scsi0" and boot_size_gib == WORKER_DISK_GIB
                           and disks_approved)
            memory_available = int(node_status.get("memory", {}).get("free", 0)) // (1024 * 1024)
            storage_free = int(storage.get("avail", 0))
            pool_memory_allocated = 0
            running_workers = 0
            worker_vmid_count = sum(member >= 900100 for member in pool_members)
            running_pool_vms = 0
            for member_vmid in sorted(pool_members):
                if member_vmid in PROTECTED_VMIDS or not 900000 <= member_vmid <= 900999:
                    raise ProxmoxBackendError("cr-range contains a VM outside the approved product VMID range")
                member_config = template if member_vmid == 900000 else self._get(
                    f"/api2/json/nodes/pve4-bbf/qemu/{member_vmid}/config")
                pool_memory_allocated += int(member_config.get("memory", 0))
                if member_vmid >= 900100:
                    member_status = self._get(f"/api2/json/nodes/pve4-bbf/qemu/{member_vmid}/status/current")
                    if member_status.get("status") == "running":
                        running_pool_vms += 1
                        member_tags = set(filter(None, str(member_config.get("tags", "")).split(";")))
                        if "cr-role-worker" in member_tags:
                            running_workers += 1
            pool_memory_available = max(0, self.settings.pool_memory_mib - pool_memory_allocated)
            report["checks"].update(pool_members=sorted(pool_members), template_owned=template_ok,
                                    template_status=template_status.get("status"), template_bootdisk=boot_disk,
                                    template_boot_size_gib=boot_size_gib,
                                    template_disk_keys=sorted(disk_keys), template_disks_approved=disks_approved,
                                    template_agent_enabled=agent_enabled,
                                    template_source={key: desc[key] for key in ("source_sha256", "source_commit", "host_id")
                                                     if key in desc},
                                    node_memory_free_mib=memory_available,
                                    pool_memory_allocated_mib=pool_memory_allocated,
                                    pool_memory_available_mib=pool_memory_available,
                                    running_pool_vms=running_pool_vms, running_workers=running_workers,
                                    worker_vmid_count=worker_vmid_count,
                                    datastore_free_bytes=storage_free)
            if not template_ok:
                raise ProxmoxBackendError("worker template 900000 failed pool/owner/tag verification")
            if memory_available < self.settings.reserved_memory_mib + WORKER_MEMORY_MIB:
                raise ProxmoxBackendError("insufficient node memory; notify product owner, no existing VM will be stopped")
            if pool_memory_available < WORKER_MEMORY_MIB:
                raise ProxmoxBackendError("cr-range memory budget is exhausted; notify product owner")
            if worker_vmid_count >= MAX_WORKER_VMS or running_pool_vms >= MAX_WORKER_VMS:
                raise ProxmoxBackendError("cr-range runtime VM quota is exhausted")
            if storage_free < (self.settings.datastore_reserve_gib + WORKER_DISK_GIB) * 1024**3:
                raise ProxmoxBackendError("insufficient local-lvm space; notify product owner")
            report.update(ok=True, state="ready")
        except (PveError, ProxmoxBackendError, KeyError, TypeError, ValueError) as exc:
            report.update(state="unavailable", error=str(redact(str(exc))))
        return report

    def placement_target(self) -> dict[str, Any]:
        """Configured PVE resource path and worker size; facility/rack locations are not modeled."""
        return {"provider": "Proxmox VE", "node": self.settings.node, "pool": self.settings.pool,
                "template_vmid": self.settings.template_vmid, "worker_vmid_range": "900100–900999",
                "worker_vcpus": WORKER_VCPUS, "worker_memory_mib": WORKER_MEMORY_MIB,
                "worker_disk_gib": WORKER_DISK_GIB}

    def plan(self, scenario_id: str, compose_yaml: str, *, compose_sha256: str | None = None,
             attach_lab_network: bool = False) -> dict[str, Any]:
        """Read-only dry plan; no compose content or credential is returned."""
        scenario_id = _safe_id(scenario_id, "scenario id")
        if attach_lab_network:
            raise ProxmoxBackendError("PVE workers are zero-NIC; attach_lab_network is unsupported")
        source_digest = hashlib.sha256(compose_yaml.encode()).hexdigest()
        if compose_sha256 and not secrets.compare_digest(source_digest, compose_sha256):
            raise ProxmoxBackendError("source Compose digest mismatch")
        compose_yaml, parsed_compose = _normalize_compose(compose_yaml, scenario_id)
        demo_files = _demo_app_files(parsed_compose)
        digest = hashlib.sha256(compose_yaml.encode()).hexdigest()
        if not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ProxmoxBackendError("invalid Compose digest")
        candidate = self._next_vmid()
        return {"backend": "proxmox", "scenario_id": scenario_id, "mode": self.settings.mode,
                "vmid": candidate, "compose_sha256": digest,
                "planned_calls": [
                    {"method": "GET", "path": "/cluster/nextid?vmid=<candidate>", "purpose": "collision check"},
                    {"method": "POST", "path": f"/nodes/{self.settings.node}/qemu/{self.settings.template_vmid}/clone", "newid": candidate},
                    {"method": "POST", "path": f"/nodes/{self.settings.node}/qemu/{candidate}/status/start"},
                    {"method": "POST", "path": f"/nodes/{self.settings.node}/qemu/{candidate}/agent/file-write", "purpose": "write compose and ephemeral environment into guest"},
                    {"method": "POST", "path": f"/nodes/{self.settings.node}/qemu/{candidate}/agent/exec", "purpose": "docker compose up --wait inside guest"},
                ] + ([{"method": "POST", "path": f"/nodes/{self.settings.node}/qemu/<candidate>/agent/file-write",
                       "guest_file": path} for path in sorted({*demo_files, _COMPOSE_ENV_GUEST,
                                                                PROBE_SUPERVISOR_PATH})]),
                "attach_lab_network": False, "writes_sent": False}

    def up(self, scenario_id: str, compose_yaml: str, *, host_id: str = "worker",
           attach_lab_network: bool = False, compose_sha256: str | None = None) -> dict[str, Any]:
        with _placement_lock(self.settings.reservation_db) as reservation_db:
            return self._up_locked(scenario_id, compose_yaml, host_id=host_id,
                                   attach_lab_network=attach_lab_network, compose_sha256=compose_sha256,
                                   reservation_db=reservation_db)

    def _up_locked(self, scenario_id: str, compose_yaml: str, *, host_id: str,
           attach_lab_network: bool = False, compose_sha256: str | None = None,
           reservation_db: sqlite3.Connection) -> dict[str, Any]:
        scenario_id, host_id = _safe_id(scenario_id, "scenario id"), _safe_id(host_id, "host id")
        if attach_lab_network:
            raise ProxmoxBackendError("PVE workers are zero-NIC; attach_lab_network is unsupported")
        held_reservations = _reservations(reservation_db) if self.settings.mode == "live" else []
        if any(held["state"] != "active" for held in held_reservations):
            return {"ok": False, "state": "reservation_conflict",
                    "error": "a durable worker reservation is not active; manual reconciliation is required"}
        if any(held["scenario_id"] == scenario_id and held["host_id"] == host_id for held in held_reservations):
            return {"ok": False, "state": "reservation_conflict",
                    "error": "this scenario host already holds a durable worker reservation"}
        if len(held_reservations) >= MAX_WORKER_VMS:
            return {"ok": False, "state": "reservation_conflict",
                    "error": "the approved worker VM limit is fully reserved"}
        if not isinstance(compose_yaml, str) or not compose_yaml:
            raise ProxmoxBackendError("Compose document is empty")
        source_digest = hashlib.sha256(compose_yaml.encode()).hexdigest()
        if compose_sha256 and not secrets.compare_digest(source_digest, compose_sha256):
            raise ProxmoxBackendError("source Compose digest mismatch")
        compose_yaml, parsed_compose = _normalize_compose(compose_yaml, scenario_id)
        demo_files = _demo_app_files(parsed_compose)
        if len(compose_yaml.encode()) > 60_000:
            raise ProxmoxBackendError("normalized Compose document exceeds the PVE guest-agent 60 KB write bound")
        digest = hashlib.sha256(compose_yaml.encode()).hexdigest()
        ready = self.preflight()
        if not ready["ok"]:
            return {"ok": False, "state": "preflight_failed", "preflight": ready}
        vmid = self._next_vmid()
        if any(held["vmid"] == vmid for held in held_reservations):
            raise ProxmoxBackendError("candidate VMID already holds a durable reservation; manual reconciliation required")
        bridge_v1_before = self.bridge_v1_report()
        if not bridge_v1_before.get("checked") or not bridge_v1_before.get("ok"):
            detail = "; ".join(bridge_v1_before.get("errors", [])) or "bridge state is unverified"
            return {"ok": False, "state": "preflight_failed",
                    "error": f"V1 isolated bridge check failed immediately before deployment: {detail}",
                    "bridge_v1": {"before": bridge_v1_before}}
        reservation_written = self.settings.mode == "live"
        generation_id = None
        if reservation_written:
            _persist_reservation(reservation_db, scenario_id=scenario_id, host_id=host_id,
                                 vmid=vmid, state="creating")
            generation_id = _reservation(reservation_db, vmid)["generation_id"]
        nonce = secrets.token_hex(6)
        pending_name = f"cr-pending-{_pve_vm_name_id(scenario_id[:16])}-{nonce}"
        source_metadata = ready["checks"].get("template_source", {})
        description = json.dumps({"created_by": OWNER, "scenario_id": scenario_id, "host_id": host_id,
                                  "created_at": datetime.now(timezone.utc).isoformat(), "template": 900000,
                                  "compose_sha256": digest, "backend_instance": _BACKEND_INSTANCE, "role": "worker",
                                  "creation_nonce": nonce},
                                 sort_keys=True, separators=(",", ":"))
        vmname = f"cr-{_pve_vm_name_id(scenario_id[:20])}-worker"
        result: dict[str, Any] = {"ok": False, "vmid": vmid, "scenario_id": scenario_id,
                                  "generation_id": generation_id, "state": "creating"}
        ownership_configured = False
        clone_completed = False
        try:
            self._clone_worker(vmid, pending_name)
            clone_completed = True
            self.client.configure_creating_clone(vmid, pending_name=pending_name,
                                                 source_metadata=source_metadata,
                                                 data={"name": vmname, "cores": WORKER_VCPUS, "memory": WORKER_MEMORY_MIB,
                                                       "tags": f"cyberrange;cr-scn-{_pve_vm_name_id(scenario_id[:20])};cr-role-worker;cr-inst-{_BACKEND_INSTANCE}",
                                                       "description": description})
            ownership_configured = True
            if self.settings.mode == "dry-run":
                return {"ok": True, "state": "planned", "vmid": vmid, "scenario_id": scenario_id,
                        "compose_sha256": digest, "writes_sent": False, "plan": redact(self.client.records)}
            self._assert_owned(vmid, scenario_id, host_id)
            self._owned_write("POST", f"/api2/json/nodes/pve4-bbf/qemu/{vmid}/status/start", {},
                              scenario_id, host_id, "start owned worker VM")
            self._wait_qga(vmid, scenario_id, host_id)
            self._guest_write(vmid, "/opt/cr-runtime/docker-compose.yml", compose_yaml, scenario_id, host_id)
            generated_secret = secrets.token_urlsafe(24)
            compose_env = ("CR_BIND_IP=127.0.0.1\nCR_PG_AUTH_METHOD=trust\n"
                           f"CR_PG_PASSWORD={generated_secret}\nCR_DB_PASSWORD={generated_secret}\n")
            self._guest_write(vmid, _COMPOSE_ENV_GUEST, compose_env, scenario_id, host_id)
            chmod_result = self._guest_exec(
                vmid, ["/usr/bin/chmod", "0600", _COMPOSE_ENV_GUEST],
                scenario_id=scenario_id, host_id=host_id, timeout=20)
            if int(chmod_result.get("exitcode", 1)) != 0:
                raise ProxmoxBackendError("could not restrict permissions on the worker Compose environment file")
            for guest_path, content in demo_files.items():
                self._guest_write(vmid, guest_path, content, scenario_id, host_id)
            self._guest_write(vmid, PROBE_SUPERVISOR_PATH, PROBE_SUPERVISOR_SCRIPT,
                              scenario_id, host_id)
            supervisor_permissions = self._guest_exec(
                vmid, ["/usr/bin/chmod", "0700", PROBE_SUPERVISOR_PATH],
                scenario_id=scenario_id, host_id=host_id, timeout=20)
            if int(supervisor_permissions.get("exitcode", 1)) != 0:
                raise ProxmoxBackendError("could not restrict permissions on the probe supervisor")
            command = _compose_command(scenario_id, "up", "--detach", "--pull", "never",
                                       "--wait", "--wait-timeout", "240")
            exec_result = self._guest_exec(vmid, command, scenario_id=scenario_id, host_id=host_id, timeout=900)
            if int(exec_result.get("exitcode", 1)) != 0:
                code = _safe_guest_diagnostic(exec_result.get("exitcode", 1), (generated_secret,))
                detail = _safe_guest_diagnostic(exec_result.get("stderr") or exec_result.get("stdout"),
                                                 (generated_secret,))
                message = f"guest docker compose up failed (exit code {code})"
                if detail:
                    message += f": {detail}"
                raise ProxmoxBackendError(message)
            isolation = self.isolation_report(scenario_id, vmid=vmid, host_id=host_id)
            if not isolation.get("checked") or not isolation.get("isolated"):
                raise ProxmoxBackendError("worker isolation verification failed; deployment rejected")
            self._owned_write("POST", f"/api2/json/nodes/pve4-bbf/qemu/{vmid}/snapshot",
                              {"snapname": "deployed", "description": f"compose_sha256={digest}"},
                              scenario_id, host_id, "record deployed reset point")
            containers = self._compose_ps(vmid, scenario_id, host_id)
            self._require_healthy_compose(containers, set(parsed_compose["services"]))
            bridge_v1_after = self.bridge_v1_report()
            result["bridge_v1"] = {"preflight": ready["checks"].get("bridge_v1"),
                                   "before": bridge_v1_before, "after": bridge_v1_after}
            if not bridge_v1_after.get("checked") or not bridge_v1_after.get("ok"):
                detail = "; ".join(bridge_v1_after.get("errors", [])) or "bridge state is unverified"
                raise ProxmoxBackendError(f"V1 isolated bridge check failed after deployment: {detail}")
            result.update(ok=True, state="running", compose_sha256=digest, isolation=isolation,
                          containers=containers)
            if reservation_written:
                try:
                    _persist_reservation(reservation_db, scenario_id=scenario_id, host_id=host_id,
                                         vmid=vmid, state="active")
                except (sqlite3.Error, ProxmoxBackendError) as exc:
                    # The worker is already running. Preserve the durable creating row (or
                    # the possibly committed active row) and make a best-effort transition
                    # to reconcile; never report success or delete a live worker just because
                    # the final reservation write had an uncertain outcome.
                    result.update(ok=False, state="failed",
                                  error=f"could not persist active worker reservation ({type(exc).__name__}); "
                                        "worker retained for reconciliation")
                    try:
                        _persist_reservation(reservation_db, scenario_id=scenario_id,
                                             host_id=host_id, vmid=vmid, state="reconcile")
                        result["reservation_state"] = "reconcile"
                    except (sqlite3.Error, ProxmoxBackendError):
                        result["reservation_state"] = "unconfirmed"
                    result["recoverable_orphan"] = {
                        "vmid": vmid, "scenario_id": scenario_id, "host_id": host_id,
                        "state": "requires_manual_reconciliation",
                    }
                    return result
            return result
        except (PveError, ProxmoxBackendError) as exc:
            result.update(ok=False, state="failed", error=str(redact(str(exc))))
            # Clean only if all three live ownership checks still pass.
            try:
                if ownership_configured:
                    self._shutdown_and_destroy_owned(vmid, scenario_id, host_id)
                    result["cleanup"] = "removed newly created owned VM"
                    if reservation_written:
                        _clear_reservation(reservation_db, scenario_id=scenario_id,
                                           host_id=host_id, vmid=vmid)
                else:
                    clone_record = next((entry for entry in reversed(self.client.records)
                                         if entry.get("method") == "POST" and entry.get("path", "").endswith("/qemu/900000/clone")), None)
                    if self.settings.mode != "live" or clone_record is None:
                        result["cleanup"] = "clone write was not sent"
                        if reservation_written:
                            _clear_reservation(reservation_db, scenario_id=scenario_id,
                                               host_id=host_id, vmid=vmid)
                    else:
                        clone_rejected = bool(clone_record and clone_record.get("http_status") == 400)
                        cleanup = self.client.delete_creating_clone(vmid, pending_name=pending_name,
                                                                    source_metadata=source_metadata)
                        if cleanup.get("absent"):
                            result["cleanup"] = "no provisional clone found"
                            if reservation_written and (clone_completed or clone_rejected):
                                _clear_reservation(reservation_db, scenario_id=scenario_id,
                                                   host_id=host_id, vmid=vmid)
                            if not clone_completed and not clone_rejected:
                                result["clone_result_uncertain"] = True
                                if reservation_written:
                                    _persist_reservation(reservation_db, scenario_id=scenario_id,
                                                         host_id=host_id, vmid=vmid, state="reconcile")
                        else:
                            self._await_operation(cleanup)
                            result["cleanup"] = "removed exact provisional clone"
                            if reservation_written:
                                _clear_reservation(reservation_db, scenario_id=scenario_id,
                                                   host_id=host_id, vmid=vmid)
            except (PveError, ProxmoxBackendError) as cleanup_exc:
                if reservation_written:
                    try:
                        _persist_reservation(reservation_db, scenario_id=scenario_id,
                                             host_id=host_id, vmid=vmid, state="reconcile")
                    except sqlite3.Error:
                        pass
                result["cleanup"] = f"refused or failed: {redact(str(cleanup_exc))}"
                result["recoverable_orphan"] = {"vmid": vmid, "scenario_id": scenario_id,
                                                 "host_id": host_id, "pending_name": pending_name,
                                                 "state": "requires_manual_reconciliation"}
            return result

    def status(self, scenario_id: str, *, vmid: int, host_id: str = "worker") -> dict[str, Any]:
        scenario_id, host_id = _safe_id(scenario_id, "scenario id"), _safe_id(host_id, "host id")
        config = self._assert_owned(vmid, scenario_id, host_id)
        status = self._get(f"/api2/json/nodes/pve4-bbf/qemu/{vmid}/status/current")
        nic_fields = sorted(key for key, value in config.items()
                            if re.fullmatch(r"net\d+", str(key)) and value)
        placement = {**self.placement_target(), "worker_vm": {
            "vmid": vmid, "name": config.get("name"), "state": status.get("status", "unknown"),
            "vcpus": int(config.get("cores", WORKER_VCPUS)),
            "memory_mib": int(config.get("memory", WORKER_MEMORY_MIB)),
            "disk_gib": _disk_size_gib(str(config.get("scsi0", ""))),
            "nic_count": len(nic_fields), "nic_fields": nic_fields,
        }}
        if status.get("status") != "running":
            return {"backend": "proxmox", "scenario_id": scenario_id, "vmid": vmid,
                    "placement": placement,
                    "state": status.get("status", "unknown"), "qmpstatus": status.get("qmpstatus"),
                    "compose": {"returncode": 127, "exitcode": 127, "stdout": "",
                                "stderr": "worker VM is not running; guest Compose status unavailable"}}
        qga = self._guest_exec(vmid, _compose_command(scenario_id, "ps", "--format", "json"),
                               scenario_id=scenario_id, host_id=host_id, timeout=60)
        return {"backend": "proxmox", "scenario_id": scenario_id, "vmid": vmid, "placement": placement,
                "state": status.get("status", "unknown"), "qmpstatus": status.get("qmpstatus"),
                "compose": qga}

    def reset(self, scenario_id: str, *, vmid: int, host_id: str = "worker") -> dict[str, Any]:
        """Rollback only to this reservation's deployed snapshot and re-prove isolation."""
        scenario_id, host_id = _safe_id(scenario_id, "scenario id"), _safe_id(host_id, "host id")
        with _placement_lock(self.settings.reservation_db) as reservation_db:
            held = _reservation(reservation_db, vmid)
            if (held is None or held["scenario_id"] != scenario_id or held["host_id"] != host_id
                    or held["vmid"] != vmid or held["state"] != "active"):
                raise ProxmoxBackendError("matching active durable worker reservation is required for reset")
            active_probe = _active_probe_for_worker(reservation_db, vmid)
            if active_probe:
                raise ProxmoxBackendError(
                    f"worker reset is blocked by {active_probe['state']} probe operation {active_probe['operation_id']}"
                )
            config = self._assert_owned(vmid, scenario_id, host_id)
            if any(re.fullmatch(r"net\d+", str(key)) and value for key, value in config.items()):
                raise ProxmoxBackendError("refusing reset because the worker is not zero-NIC")
            expected_digest = _description(config.get("description", "")).get("compose_sha256")
            if not isinstance(expected_digest, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_digest):
                raise ProxmoxBackendError("owned worker has no valid deployed Compose digest")
            snapshot_path = f"/api2/json/nodes/pve4-bbf/qemu/{vmid}/snapshot"
            snapshots = _data(self.client.request("GET", snapshot_path, purpose="verify deployed reset snapshot"))
            if not isinstance(snapshots, list) or not any(
                    isinstance(item, Mapping) and item.get("name") == "deployed" for item in snapshots):
                raise ProxmoxBackendError("approved deployed snapshot is missing")
            snapshot = _data(self.client.request(
                "GET", f"{snapshot_path}/deployed/config", purpose="verify deployed snapshot identity"))
            snapshot_description = str(snapshot.get("description", "")) if isinstance(snapshot, Mapping) else ""
            if snapshot_description != f"compose_sha256={expected_digest}":
                raise ProxmoxBackendError("deployed snapshot Compose digest does not match this worker")

            state = self._get(f"/api2/json/nodes/pve4-bbf/qemu/{vmid}/status/current")
            if state.get("status") == "running":
                self._owned_write("POST", f"/api2/json/nodes/pve4-bbf/qemu/{vmid}/status/shutdown", {},
                                  scenario_id, host_id, "stop owned worker before reset")
                self._wait_stopped(vmid)
            elif state.get("status") != "stopped":
                raise ProxmoxBackendError("worker state is not safe for reset")
            self._assert_owned(vmid, scenario_id, host_id)
            self._owned_write("POST", f"/api2/json/nodes/pve4-bbf/qemu/{vmid}/snapshot/deployed/rollback", {},
                              scenario_id, host_id, "rollback owned worker to approved deployed snapshot")
            self._assert_owned(vmid, scenario_id, host_id)
            self._owned_write("POST", f"/api2/json/nodes/pve4-bbf/qemu/{vmid}/status/start", {},
                              scenario_id, host_id, "start reset owned worker")
            self._wait_qga(vmid, scenario_id, host_id)
            isolation = self.isolation_report(scenario_id, vmid=vmid, host_id=host_id)
            if not isolation.get("checked") or not isolation.get("isolated"):
                raise ProxmoxBackendError("worker isolation could not be confirmed after reset; reservation retained")
            compose_start = self._guest_exec(
                vmid, _compose_command(scenario_id, "up", "--detach", "--pull", "never",
                                       "--wait", "--wait-timeout", "240"),
                scenario_id=scenario_id, host_id=host_id, timeout=900)
            if int(compose_start.get("exitcode", 1)) != 0:
                detail = _safe_guest_diagnostic(compose_start.get("stderr") or compose_start.get("stdout"))
                message = f"worker Compose services could not be restored after reset (exit code {compose_start.get('exitcode', 1)})"
                if detail:
                    message += f": {detail}"
                raise ProxmoxBackendError(message)
            isolation = self.isolation_report(scenario_id, vmid=vmid, host_id=host_id)
            if not isolation.get("checked") or not isolation.get("isolated"):
                raise ProxmoxBackendError("worker isolation could not be confirmed after restoring services; reservation retained")
            compose = self._compose_ps(vmid, scenario_id, host_id)
            self._require_healthy_compose(compose)
            return {"backend": "proxmox", "scenario_id": scenario_id, "vmid": vmid,
                    "state": "running", "ok": True, "compose_sha256": expected_digest,
                    "isolation": isolation, "containers": compose}

    @staticmethod
    def _require_healthy_compose(result: Mapping[str, Any],
                                 expected_services: set[str] | None = None) -> None:
        """Require successful Compose JSON/JSONL status and optionally every planned service."""
        exitcode = result.get("exitcode")
        if isinstance(exitcode, bool) or not isinstance(exitcode, int) or exitcode != 0:
            raise ProxmoxBackendError("worker Compose status could not be confirmed")
        output = result.get("stdout")
        if not isinstance(output, str) or not output.strip():
            raise ProxmoxBackendError("worker Compose status returned no containers")
        try:
            decoded = json.loads(output)
        except json.JSONDecodeError:
            # Compose 5.7 emits one JSON object per line for `ps --format json`.
            rows = []
            try:
                for line in output.splitlines():
                    if line.strip():
                        rows.append(json.loads(line))
            except json.JSONDecodeError:
                raise ProxmoxBackendError("worker Compose status returned invalid JSONL") from None
        else:
            rows = decoded if isinstance(decoded, list) else [decoded]
        if not rows or any(not isinstance(row, Mapping) for row in rows):
            raise ProxmoxBackendError("worker Compose status returned no valid container records")
        observed_services: set[str] = set()
        for row in rows:
            service = row.get("Service")
            state = str(row.get("State") or "").strip().lower()
            health = str(row.get("Health") or "").strip().lower()
            if not isinstance(service, str) or not service:
                raise ProxmoxBackendError("worker Compose status omitted a service identity")
            observed_services.add(service)
            if state != "running" or health not in {"", "healthy"}:
                raise ProxmoxBackendError("one or more worker Compose services are not healthy")
        if expected_services is not None and not expected_services.issubset(observed_services):
            raise ProxmoxBackendError("worker Compose status omitted one or more planned services")

    def isolation_report(self, scenario_id: str, *, vmid: int, host_id: str) -> dict[str, Any]:
        """Fail-closed isolation evidence from PVE config and the owned guest's Docker networks."""
        scenario_id, host_id = _safe_id(scenario_id, "scenario id"), _safe_id(host_id, "host id")
        report: dict[str, Any] = {"isolated": False, "checked": False,
                                  "evidence": {"backend": "proxmox", "vmid": vmid}, "details": []}
        try:
            config = self._assert_owned(vmid, scenario_id, host_id)
            nic_fields = {key: value for key, value in config.items()
                          if re.fullmatch(r"net\d+", str(key)) and value}
            report["evidence"]["vm_has_nic"] = bool(nic_fields)
            report["evidence"]["vm_nics"] = sorted(nic_fields)
            if nic_fields:
                report["checked"] = True
                report["details"].append("worker VM has a configured NIC")
                return report
            status = self._get(f"/api2/json/nodes/pve4-bbf/qemu/{vmid}/status/current")
            report["evidence"]["vm_state"] = status.get("status", "unknown")
            if status.get("status") != "running":
                report["details"].append("guest Docker network isolation could not be checked while VM is stopped")
                return report
            compose_config = self._guest_exec(
                vmid, _compose_command(scenario_id, "config", "--format", "json"),
                scenario_id=scenario_id, host_id=host_id, timeout=60)
            if int(compose_config.get("exitcode", 1)) != 0:
                report["details"].append("guest Compose network configuration could not be read")
                return report
            try:
                compose_document = json.loads(compose_config.get("stdout", ""))
                configured_networks = compose_document.get("networks", {})
            except (TypeError, ValueError, AttributeError):
                configured_networks = {}
            if not isinstance(configured_networks, dict) or not configured_networks:
                report["details"].append("scenario Compose has no verifiable lab networks")
                return report
            expected_prefix = _project_name(scenario_id) + "-"
            expected_networks: list[str] = []
            for network_config in configured_networks.values():
                if not isinstance(network_config, dict):
                    report["details"].append("scenario Compose network definition is invalid")
                    return report
                name = network_config.get("name")
                if (not isinstance(name, str) or not name.startswith(expected_prefix)
                        or network_config.get("internal") is not True
                        or network_config.get("driver") not in (None, "bridge")
                        or network_config.get("driver_opts") != _ISOLATED_BRIDGE_OPTIONS
                        or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", name)):
                    report["details"].append(
                        "scenario Compose network name, driver, internal flag, or isolated gateway option is invalid"
                    )
                    return report
                expected_networks.append(name)
            if len(expected_networks) != len(set(expected_networks)):
                report["details"].append("scenario Compose network names are not unique")
                return report
            networks: list[dict[str, Any]] = []
            for name in expected_networks:
                inspected = self._guest_exec(
                    vmid, ["/usr/bin/docker", "network", "inspect", "--format", "{{json .}}", name],
                    scenario_id=scenario_id, host_id=host_id, timeout=30)
                if int(inspected.get("exitcode", 1)) != 0:
                    report["details"].append(f"Docker network inspect failed for {name}")
                    return report
                try:
                    network = json.loads(inspected.get("stdout", ""))
                except (TypeError, ValueError):
                    report["details"].append(f"Docker network inspect returned invalid evidence for {name}")
                    return report
                if not isinstance(network, dict) or network.get("Name") != name:
                    report["details"].append(f"Docker network identity did not match for {name}")
                    return report
                options = network.get("Options")
                isolated_gateway = isinstance(options, dict) and options.get(_ISOLATED_BRIDGE_OPT) == "isolated"
                networks.append({"name": name, "internal": network.get("Internal") is True,
                                 "driver": network.get("Driver"),
                                 "isolated_gateway": isolated_gateway})
            report["evidence"]["docker_networks"] = networks
            report["checked"] = True
            report["isolated"] = all(item["internal"] and item["driver"] == "bridge"
                                     and item["isolated_gateway"] for item in networks)
            if not report["isolated"]:
                report["details"].append(
                    "one or more scenario Docker networks are not bridge/internal/isolated"
                )
            return report
        except (PveError, ProxmoxBackendError, KeyError, TypeError, ValueError) as exc:
            report["details"].append(str(redact(str(exc))))
            return report

    def down(self, scenario_id: str, *, vmid: int, host_id: str = "worker") -> dict[str, Any]:
        with _placement_lock(self.settings.reservation_db) as reservation_db:
            return self._down_locked(scenario_id, vmid=vmid, host_id=host_id,
                                     reservation_db=reservation_db)

    def _down_locked(self, scenario_id: str, *, vmid: int, host_id: str,
                     reservation_db: sqlite3.Connection) -> dict[str, Any]:
        scenario_id, host_id = _safe_id(scenario_id, "scenario id"), _safe_id(host_id, "host id")
        held = _reservation(reservation_db, vmid)
        if (held is None or held["scenario_id"] != scenario_id or held["host_id"] != host_id
                or held["vmid"] != vmid
                or held["state"] not in {"active", "creating", "reconcile", "deleting"}):
            raise ProxmoxBackendError("matching durable worker reservation is required for down")
        active_probe = _active_probe_for_worker(reservation_db, vmid)
        if active_probe:
            raise ProxmoxBackendError(
                f"worker down is blocked by {active_probe['state']} probe operation {active_probe['operation_id']}"
            )
        # Reservation state alone is never authority to delete. Prove this is the exact
        # owned worker before advancing even a stale/partial lifecycle row to deleting.
        self._assert_owned(vmid, scenario_id, host_id)
        _persist_reservation(reservation_db, scenario_id=scenario_id, host_id=host_id,
                             vmid=vmid, state="deleting")
        self._assert_owned(vmid, scenario_id, host_id)
        compose_cleanup: dict[str, Any]
        try:
            compose_cleanup = self._guest_exec(
                vmid, _compose_command(scenario_id, "down", "--volumes", "--remove-orphans"),
                scenario_id=scenario_id, host_id=host_id, timeout=240)
            if int(compose_cleanup.get("exitcode", 1)) != 0:
                compose_cleanup["cleanup_error"] = "guest Compose down returned a nonzero exit code"
        except (PveError, ProxmoxBackendError) as exc:
            compose_cleanup = {"exitcode": 127, "stdout": "", "stderr": str(redact(str(exc))),
                               "cleanup_error": "guest Compose cleanup failed; continuing with owned VM shutdown"}
        self._shutdown_and_destroy_owned(vmid, scenario_id, host_id)
        # Keep terminal operation IDs as durable tombstones so a late duplicate
        # start cannot reuse one after this worker is destroyed and recreated.
        _clear_reservation(reservation_db, scenario_id=scenario_id, host_id=host_id, vmid=vmid)
        return {"backend": "proxmox", "scenario_id": scenario_id, "vmid": vmid, "state": "removed", "ok": True,
                "compose_cleanup": compose_cleanup}

    def _next_vmid(self) -> int:
        for vmid in range(900100, 901000):
            if vmid in PROTECTED_VMIDS:
                continue
            try:
                result = self._get("/api2/json/cluster/nextid", params={"vmid": vmid})
                if int(result) == vmid:
                    return vmid
            except PveError as exc:
                if "already exists" in str(exc).lower():
                    continue
                raise
        raise ProxmoxBackendError("no unoccupied worker VMID available in 900100–900999")

    def _assert_owned(self, vmid: int, scenario_id: str, host_id: str) -> dict[str, Any]:
        if isinstance(vmid, bool) or not isinstance(vmid, int) or not 900100 <= vmid <= 900999 or vmid in PROTECTED_VMIDS:
            raise ProxmoxBackendError("VMID is outside the product worker range")
        pool = self._get("/api2/json/pools/cr-range")
        members = _pool_vmids(pool.get("members", []))
        if vmid not in members:
            raise ProxmoxBackendError("VM is not a member of cr-range")
        config = self._get(f"/api2/json/nodes/pve4-bbf/qemu/{vmid}/config")
        tags = set(filter(None, str(config.get("tags", "")).split(";")))
        description = _description(config.get("description", ""))
        if OWNER not in tags or f"cr-scn-{_pve_vm_name_id(scenario_id[:20])}" not in tags or "cr-role-worker" not in tags:
            raise ProxmoxBackendError("VM ownership tags do not match the requested scenario")
        if (description.get("created_by") != OWNER or description.get("scenario_id") != scenario_id
                or description.get("host_id") != host_id or description.get("role") != "worker"
                or description.get("template") != 900000 or description.get("backend_instance") != _BACKEND_INSTANCE):
            raise ProxmoxBackendError("VM ownership description does not match backend identity")
        return config

    def _destroy_owned(self, vmid: int, scenario_id: str, host_id: str) -> None:
        self._assert_owned(vmid, scenario_id, host_id)
        status = self._get(f"/api2/json/nodes/pve4-bbf/qemu/{vmid}/status/current")
        if status.get("status") != "stopped":
            raise ProxmoxBackendError("refusing worker deletion until the owned VM is stopped")
        response = self.client.delete_owned_vmid(vmid, scenario_id=scenario_id, host_id=host_id,
                                                 backend_instance=_BACKEND_INSTANCE)
        self._await_operation(response)

    def _shutdown_and_destroy_owned(self, vmid: int, scenario_id: str, host_id: str) -> None:
        self._assert_owned(vmid, scenario_id, host_id)
        status = self._get(f"/api2/json/nodes/pve4-bbf/qemu/{vmid}/status/current")
        if status.get("status") == "running":
            self._owned_write("POST", f"/api2/json/nodes/pve4-bbf/qemu/{vmid}/status/shutdown", {},
                              scenario_id, host_id, "gracefully shutdown owned worker")
            self._wait_stopped(vmid)
        elif status.get("status") != "stopped":
            raise ProxmoxBackendError("worker state is not safe for deletion")
        self._destroy_owned(vmid, scenario_id, host_id)

    def _wait_qga(self, vmid: int, scenario_id: str, host_id: str) -> None:
        deadline = time.monotonic() + self.settings.task_timeout
        while time.monotonic() < deadline:
            try:
                self._guest_exec(vmid, ["/bin/true"], scenario_id=scenario_id, host_id=host_id, timeout=20)
                return
            except PveError:
                time.sleep(self.settings.task_poll_interval)
        raise ProxmoxBackendError("guest agent did not become ready before timeout")

    def guest_exec(self, scenario_id: str, *, vmid: int, host_id: str,
                   command: list[str], timeout: int = 60,
                   require_isolation: bool = True) -> dict[str, Any]:
        """Run a bounded command through QGA after rechecking worker ownership."""
        scenario_id = _safe_id(scenario_id, "scenario id")
        host_id = _safe_id(host_id, "host id")
        with _placement_lock(self.settings.reservation_db) as reservation_db:
            held = _reservation(reservation_db, vmid)
            if (held is None or held["scenario_id"] != scenario_id or held["host_id"] != host_id
                    or held["vmid"] != vmid or held["state"] != "active"):
                raise ProxmoxBackendError("public guest command requires its matching active durable reservation")
            self._assert_owned(vmid, scenario_id, host_id)
            if require_isolation:
                isolation = self.isolation_report(scenario_id, vmid=vmid, host_id=host_id)
                if not isolation.get("checked") or not isolation.get("isolated"):
                    raise ProxmoxBackendError("guest command requires verified worker isolation")
            return self._guest_exec(vmid, command, scenario_id=scenario_id,
                                    host_id=host_id, timeout=timeout)

    @staticmethod
    def _probe_operation_id(operation_id: str) -> str:
        if not isinstance(operation_id, str) or not re.fullmatch(r"[a-f0-9]{32}", operation_id):
            raise ProxmoxBackendError("probe operation id must be 32 lowercase hexadecimal characters")
        return operation_id

    @staticmethod
    def _parse_supervisor_result(result: Mapping[str, Any]) -> dict[str, Any]:
        output = str(result.get("stdout", ""))
        fields: dict[str, str] = {}
        for line in output.splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key in fields:
                raise ProxmoxBackendError("probe supervisor returned duplicate fields")
            fields[key] = value
        state = fields.get("state")
        if state not in {"starting", "running", "cancel_requested", "uncertain", *_PROBE_TERMINAL_STATES}:
            raise ProxmoxBackendError("probe supervisor returned an invalid operation state")
        absent_text = fields.get("resource_absent")
        if absent_text not in {"true", "false"}:
            raise ProxmoxBackendError("probe supervisor did not confirm resource state")
        parsed: dict[str, Any] = {"state": state, "resource_absent": absent_text == "true"}
        if "exitcode" in fields:
            if not re.fullmatch(r"-?\d{1,4}", fields["exitcode"]):
                raise ProxmoxBackendError("probe supervisor returned an invalid exit code")
            parsed["exitcode"] = int(fields["exitcode"])
        for encoded, target in (("stdout_b64", "stdout"), ("stderr_b64", "stderr")):
            value = fields.get(encoded, "")
            if len(value) > 24_000 or (value and not re.fullmatch(r"[A-Za-z0-9+/]*={0,2}", value)):
                raise ProxmoxBackendError("probe supervisor output exceeds the bounded format")
            try:
                parsed[target] = base64.b64decode(value, validate=True).decode("utf-8", errors="replace") if value else ""
            except (ValueError, base64.binascii.Error):
                raise ProxmoxBackendError("probe supervisor output is not valid base64") from None
        if state in _PROBE_TERMINAL_STATES and not parsed["resource_absent"]:
            raise ProxmoxBackendError("probe supervisor reported terminal state before resource disappearance")
        return parsed

    def _call_probe_supervisor(self, scenario_id: str, *, vmid: int, host_id: str,
                               operation_id: str, service_id: str, target_name: str,
                               action: str, timeout: int, payload: str | None = None,
                               require_isolation: bool) -> dict[str, Any]:
        service_id = _safe_id(service_id, "service id")
        if target_name != f"{_project_name(scenario_id)}-{service_id}":
            raise ProxmoxBackendError("probe supervisor target does not match its service identity")
        self._assert_owned(vmid, scenario_id, host_id)
        if require_isolation:
            isolation = self.isolation_report(scenario_id, vmid=vmid, host_id=host_id)
            if not isolation.get("checked") or not isolation.get("isolated"):
                raise ProxmoxBackendError("probe start requires verified worker isolation")
        encoded = base64.b64encode(payload.encode("utf-8")).decode("ascii") if payload is not None else ""
        command = ["/bin/sh", PROBE_SUPERVISOR_PATH, action, operation_id,
                   scenario_id, target_name, str(timeout), encoded]
        raw = self._guest_exec(vmid, command, scenario_id=scenario_id,
                               host_id=host_id, timeout=30)
        parsed = self._parse_supervisor_result(raw)
        parsed["qga_exitcode"] = raw.get("exitcode", 1)
        if raw.get("exitcode") not in {0, None} and parsed["state"] != "uncertain":
            raise ProxmoxBackendError("probe supervisor command failed before confirming operation state")
        return parsed

    def _install_probe_supervisor(self, vmid: int, scenario_id: str, host_id: str) -> None:
        self._guest_write(vmid, PROBE_SUPERVISOR_PATH, PROBE_SUPERVISOR_SCRIPT,
                          scenario_id, host_id)
        permissions = self._guest_exec(
            vmid, ["/usr/bin/chmod", "0700", PROBE_SUPERVISOR_PATH],
            scenario_id=scenario_id, host_id=host_id, timeout=20)
        if int(permissions.get("exitcode", 1)) != 0:
            raise ProxmoxBackendError("could not restrict permissions on the probe supervisor")

    @staticmethod
    def _probe_job_id(job_id: str) -> str:
        if not isinstance(job_id, str) or not re.fullmatch(r"[a-f0-9]{32}", job_id):
            raise ProxmoxBackendError("probe job id must be 32 lowercase hexadecimal characters")
        return job_id

    @staticmethod
    def _probe_generation_id(generation_id: str) -> str:
        if not isinstance(generation_id, str) or not re.fullmatch(r"[a-f0-9]{32}", generation_id):
            raise ProxmoxBackendError("worker generation id must be 32 lowercase hexadecimal characters")
        return generation_id

    def reserve_probe_operation(self, scenario_id: str, *, vmid: int, host_id: str,
                                generation_id: str, operation_id: str,
                                service_id: str, job_id: str) -> dict[str, Any]:
        """Persist a generation-bound launch fence before the POC job can start a probe."""
        scenario_id, host_id = _safe_id(scenario_id, "scenario id"), _safe_id(host_id, "host id")
        service_id = _safe_id(service_id, "service id")
        operation_id = self._probe_operation_id(operation_id)
        job_id = self._probe_job_id(job_id)
        generation_id = self._probe_generation_id(generation_id)
        if self.settings.mode != "live":
            return {"state": "blocked", "error": "live Proxmox mode is required to reserve a probe operation"}
        target_name = f"{_project_name(scenario_id)}-{service_id}"
        with _placement_lock(self.settings.reservation_db) as reservation_db:
            held = _reservation(reservation_db, vmid)
            if (held is None or held["scenario_id"] != scenario_id or held["host_id"] != host_id
                    or held["vmid"] != vmid or held["state"] != "active"
                    or held.get("generation_id") != generation_id):
                raise ProxmoxBackendError("probe reservation requires its matching active worker")
            generation_id = self._probe_generation_id(held.get("generation_id"))
            existing = _probe_operation(reservation_db, operation_id)
            if existing:
                if (existing["scenario_id"], existing["host_id"], existing["vmid"],
                        existing["service_id"], existing["target_name"], existing["job_id"],
                        existing["generation_id"]) != (
                        scenario_id, host_id, vmid, service_id, target_name, job_id, generation_id):
                    raise ProxmoxBackendError("probe operation id is already bound to another job or worker generation")
                return {"state": existing["state"], "operation_id": operation_id,
                        "vmid": vmid, "host_id": host_id, "generation_id": generation_id,
                        "resource_absent": existing["state"] in _PROBE_TERMINAL_STATES}
            active_probe = _active_probe_for_worker(reservation_db, vmid)
            if active_probe:
                raise ProxmoxBackendError(
                    f"worker is already fenced by probe operation {active_probe['operation_id']}"
                )
            _create_probe_operation(
                reservation_db, operation_id=operation_id, scenario_id=scenario_id,
                host_id=host_id, vmid=vmid, service_id=service_id, target_name=target_name,
                generation_id=generation_id, job_id=job_id, state="reserved")
            return {"state": "reserved", "operation_id": operation_id, "vmid": vmid,
                    "host_id": host_id, "generation_id": generation_id,
                    "resource_absent": True}

    def active_probe_operations(self, scenario_id: str) -> list[dict[str, Any]]:
        """Read durable active fences, including reservations not yet attached to a POC job."""
        scenario_id = _safe_id(scenario_id, "scenario id")
        with _placement_lock(self.settings.reservation_db) as reservation_db:
            return _active_probe_operations_for_scenario(reservation_db, scenario_id)

    def probe_operation(self, operation_id: str) -> dict[str, Any] | None:
        operation_id = self._probe_operation_id(operation_id)
        with _placement_lock(self.settings.reservation_db) as reservation_db:
            return _probe_operation(reservation_db, operation_id)

    def start_probe_operation(self, scenario_id: str, *, vmid: int, host_id: str,
                              generation_id: str, job_id: str, operation_id: str,
                              service_id: str, script: str,
                              timeout: int) -> dict[str, Any]:
        """Start only an operation already reserved for this exact worker generation."""
        scenario_id, host_id = _safe_id(scenario_id, "scenario id"), _safe_id(host_id, "host id")
        service_id = _safe_id(service_id, "service id")
        generation_id = self._probe_generation_id(generation_id)
        job_id = self._probe_job_id(job_id)
        operation_id = self._probe_operation_id(operation_id)
        if not isinstance(script, str) or not script or "\x00" in script or len(script.encode("utf-8")) > 20_000:
            raise ProxmoxBackendError("probe script is empty or exceeds the strict bound")
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 300:
            raise ProxmoxBackendError("probe timeout exceeds the approved bound")
        if self.settings.mode != "live":
            return {"state": "blocked", "resource_absent": True,
                    "error": "live Proxmox mode is required to start a probe operation"}
        wrapped_script = ("import signal,sys" + chr(10)
                          + "signal.signal(signal.SIGALRM, lambda *_: sys.exit(124))" + chr(10)
                          + "signal.alarm(" + str(timeout) + ")" + chr(10)
                          + "exec(compile(" + repr(script) + ", '<cr-poc>', 'exec'))")
        target_name = f"{_project_name(scenario_id)}-{service_id}"
        with _placement_lock(self.settings.reservation_db) as reservation_db:
            held = _reservation(reservation_db, vmid)
            if (held is None or held["scenario_id"] != scenario_id or held["host_id"] != host_id
                    or held["state"] != "active" or held.get("generation_id") != generation_id):
                raise ProxmoxBackendError("probe start requires its matching active worker reservation")
            existing = _probe_operation(reservation_db, operation_id)
            if (existing is None or (existing["scenario_id"], existing["host_id"], existing["vmid"],
                                     existing["service_id"], existing["target_name"], existing["job_id"],
                                     existing["generation_id"]) != (
                    scenario_id, host_id, vmid, service_id, target_name, job_id, generation_id)):
                raise ProxmoxBackendError("probe start requires its exact durable job and worker-generation fence")
            if existing["state"] != "reserved":
                if existing["state"] in _PROBE_TERMINAL_STATES:
                    return {"state": existing["state"], "resource_absent": True,
                            "exitcode": existing["exitcode"], "stdout": "", "stderr": ""}
                return {"state": existing["state"], "resource_absent": False}
            active_probe = _active_probe_for_worker(reservation_db, vmid)
            if active_probe and active_probe["operation_id"] != operation_id:
                raise ProxmoxBackendError("worker is fenced by a different probe operation")
            isolation = self.isolation_report(scenario_id, vmid=vmid, host_id=host_id)
            if not isolation.get("checked") or not isolation.get("isolated"):
                raise ProxmoxBackendError("probe start requires verified worker isolation")
            self._install_probe_supervisor(vmid, scenario_id, host_id)
            _update_probe_operation(reservation_db, operation_id, state="starting")
            try:
                result = self._call_probe_supervisor(
                    scenario_id, vmid=vmid, host_id=host_id, operation_id=operation_id,
                    service_id=service_id, target_name=target_name, action="start",
                    timeout=timeout, payload=wrapped_script, require_isolation=True)
            except Exception as exc:
                _update_probe_operation(reservation_db, operation_id, state="uncertain")
                return {"state": "uncertain", "resource_absent": False,
                        "error": f"probe launch outcome is uncertain ({type(exc).__name__})"}
            state = result["state"]
            _update_probe_operation(
                reservation_db, operation_id,
                state="running" if state == "running" else state,
                exitcode=result.get("exitcode"), stdout_b64=base64.b64encode(
                    result.get("stdout", "").encode("utf-8")).decode("ascii"),
                stderr_b64=base64.b64encode(result.get("stderr", "").encode("utf-8")).decode("ascii"),
            )
            return result

    def wait_probe_operation(self, scenario_id: str, *, operation_id: str,
                             vmid: int, host_id: str, generation_id: str,
                             timeout: int = 30) -> dict[str, Any]:
        """Read and persist one supervisor state without holding the placement lock while waiting."""
        scenario_id, host_id = _safe_id(scenario_id, "scenario id"), _safe_id(host_id, "host id")
        generation_id = self._probe_generation_id(generation_id)
        operation_id = self._probe_operation_id(operation_id)
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 300:
            raise ProxmoxBackendError("probe wait timeout exceeds the approved bound")
        with _placement_lock(self.settings.reservation_db) as reservation_db:
            held = _reservation(reservation_db, vmid)
            operation = _probe_operation(reservation_db, operation_id)
            if (held is None or held["scenario_id"] != scenario_id or held["host_id"] != host_id
                    or held["state"] != "active" or held.get("generation_id") != generation_id
                    or operation is None
                    or (operation["scenario_id"], operation["host_id"], operation["vmid"]) != (
                        scenario_id, host_id, vmid)
                    or operation.get("generation_id") != generation_id):
                raise ProxmoxBackendError("probe wait requires its matching active operation and reservation")
            if operation["state"] in _PROBE_TERMINAL_STATES:
                return {"state": operation["state"], "resource_absent": True,
                        "exitcode": operation["exitcode"],
                        "stdout": base64.b64decode(operation["stdout_b64"] or "").decode("utf-8", "replace"),
                        "stderr": base64.b64decode(operation["stderr_b64"] or "").decode("utf-8", "replace")}
            try:
                result = self._call_probe_supervisor(
                    scenario_id, vmid=vmid, host_id=host_id, operation_id=operation_id,
                    service_id=operation["service_id"], target_name=operation["target_name"],
                    action="wait", timeout=timeout, require_isolation=False)
            except Exception as exc:
                _update_probe_operation(reservation_db, operation_id, state="uncertain")
                return {"state": "uncertain", "resource_absent": False,
                        "error": f"probe wait outcome is uncertain ({type(exc).__name__})"}
            state = result["state"]
            _update_probe_operation(
                reservation_db, operation_id,
                state="running" if state == "running" else state,
                exitcode=result.get("exitcode"),
                stdout_b64=base64.b64encode(result.get("stdout", "").encode("utf-8")).decode("ascii"),
                stderr_b64=base64.b64encode(result.get("stderr", "").encode("utf-8")).decode("ascii"),
            )
            return result

    def cancel_probe_operation(self, scenario_id: str, *, operation_id: str,
                               vmid: int, host_id: str, generation_id: str,
                               service_id: str, job_id: str | None = None) -> dict[str, Any]:
        """Persist a cancel fence before asking the guest to stop and prove absence."""
        scenario_id, host_id = _safe_id(scenario_id, "scenario id"), _safe_id(host_id, "host id")
        service_id = _safe_id(service_id, "service id")
        generation_id = self._probe_generation_id(generation_id)
        if job_id is not None:
            job_id = self._probe_job_id(job_id)
        operation_id = self._probe_operation_id(operation_id)
        target_name = f"{_project_name(scenario_id)}-{service_id}"
        with _placement_lock(self.settings.reservation_db) as reservation_db:
            operation = _probe_operation(reservation_db, operation_id)
            expected = (scenario_id, host_id, vmid, service_id, target_name, generation_id)
            if operation and (operation["scenario_id"], operation["host_id"], operation["vmid"],
                              operation["service_id"], operation["target_name"],
                              operation.get("generation_id")) == expected:
                if job_id is not None and operation.get("job_id") is None:
                    operation = _bind_legacy_probe_job(
                        reservation_db, operation_id=operation_id, scenario_id=scenario_id,
                        host_id=host_id, vmid=vmid, service_id=service_id,
                        target_name=target_name, generation_id=generation_id, job_id=job_id)
                elif job_id is not None and operation.get("job_id") != job_id:
                    raise ProxmoxBackendError("probe cancellation job identity does not match its durable operation")
                if operation["state"] in _PROBE_TERMINAL_STATES:
                    return {"state": operation["state"], "resource_absent": True,
                            "exitcode": operation["exitcode"],
                            "stdout": base64.b64decode(operation["stdout_b64"] or "").decode("utf-8", "replace"),
                            "stderr": base64.b64decode(operation["stderr_b64"] or "").decode("utf-8", "replace")}
            held = _reservation(reservation_db, vmid)
            if (held is None or held["scenario_id"] != scenario_id or held["host_id"] != host_id
                    or held["state"] != "active" or held.get("generation_id") != generation_id):
                raise ProxmoxBackendError("probe cancellation requires its matching active worker reservation")
            if operation is None:
                _create_probe_operation(reservation_db, operation_id=operation_id,
                                        scenario_id=scenario_id, host_id=host_id, vmid=vmid,
                                        service_id=service_id, target_name=target_name,
                                        generation_id=generation_id, job_id=job_id,
                                        state="cancel_requested")
                operation = _probe_operation(reservation_db, operation_id)
            elif (operation["scenario_id"], operation["host_id"], operation["vmid"],
                  operation["service_id"], operation["target_name"], operation["generation_id"]) != (
                    scenario_id, host_id, vmid, service_id, target_name, generation_id):
                raise ProxmoxBackendError("probe cancellation identity does not match its durable operation")
            if job_id is not None and operation.get("job_id") != job_id:
                raise ProxmoxBackendError("probe cancellation job identity does not match its durable operation")
            _update_probe_operation(reservation_db, operation_id, state="cancel_requested")
            try:
                self._install_probe_supervisor(vmid, scenario_id, host_id)
                result = self._call_probe_supervisor(
                    scenario_id, vmid=vmid, host_id=host_id, operation_id=operation_id,
                    service_id=service_id, target_name=target_name, action="cancel",
                    timeout=30, require_isolation=False)
            except Exception as exc:
                _update_probe_operation(reservation_db, operation_id, state="uncertain")
                return {"state": "uncertain", "resource_absent": False,
                        "error": f"probe cancellation is unconfirmed ({type(exc).__name__})"}
            state = result["state"]
            _update_probe_operation(
                reservation_db, operation_id, state=state,
                exitcode=result.get("exitcode"),
                stdout_b64=base64.b64encode(result.get("stdout", "").encode("utf-8")).decode("ascii"),
                stderr_b64=base64.b64encode(result.get("stderr", "").encode("utf-8")).decode("ascii"),
            )
            return result

    def join_probe_operation(self, scenario_id: str, *, operation_id: str,
                             vmid: int, host_id: str, generation_id: str,
                             service_id: str,
                             timeout: int = 30) -> dict[str, Any]:
        """Poll until the helper is terminal and absent, or mark the operation uncertain."""
        scenario_id, host_id = _safe_id(scenario_id, "scenario id"), _safe_id(host_id, "host id")
        service_id = _safe_id(service_id, "service id")
        generation_id = self._probe_generation_id(generation_id)
        operation_id = self._probe_operation_id(operation_id)
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 300:
            raise ProxmoxBackendError("probe join timeout exceeds the approved bound")
        with _placement_lock(self.settings.reservation_db) as reservation_db:
            operation = _probe_operation(reservation_db, operation_id)
            if (operation is None or (operation["scenario_id"], operation["host_id"],
                                      operation["vmid"], operation["service_id"],
                                      operation.get("generation_id")) != (
                    scenario_id, host_id, vmid, service_id, generation_id)):
                raise ProxmoxBackendError("probe join identity does not match its durable operation")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = self.wait_probe_operation(scenario_id, operation_id=operation_id,
                                               vmid=vmid, host_id=host_id,
                                               generation_id=generation_id,
                                               timeout=min(30, max(1, int(deadline - time.monotonic()))))
            if result.get("state") in _PROBE_TERMINAL_STATES and result.get("resource_absent") is True:
                return result
            if result.get("state") == "uncertain":
                return result
            time.sleep(min(self.settings.task_poll_interval, max(0, deadline - time.monotonic())))
        with _placement_lock(self.settings.reservation_db) as reservation_db:
            operation = _probe_operation(reservation_db, operation_id)
            if operation and (operation["scenario_id"], operation["host_id"], operation["vmid"]) == (
                    scenario_id, host_id, vmid) and operation.get("generation_id") == generation_id \
                    and operation["state"] not in _PROBE_TERMINAL_STATES:
                _update_probe_operation(reservation_db, operation_id, state="uncertain")
        return {"state": "uncertain", "resource_absent": False,
                "error": "probe helper did not reach a confirmed terminal state before join timeout"}

    def _guest_exec(self, vmid: int, command: list[str], *, scenario_id: str,
                    host_id: str, timeout: int = 60) -> dict[str, Any]:
        if not 900100 <= vmid <= 900999 or vmid in PROTECTED_VMIDS:
            raise ProxmoxBackendError("guest command VMID is outside the worker range")
        if not command or any(not isinstance(arg, str) or "\x00" in arg for arg in command):
            raise ProxmoxBackendError("invalid guest command")
        if timeout < 1 or timeout > 900:
            raise ProxmoxBackendError("guest command timeout exceeds bound")
        self._assert_owned(vmid, scenario_id, host_id)
        response = _data(self.client.request_owned("POST", f"/api2/json/nodes/pve4-bbf/qemu/{vmid}/agent/exec",
                                                   scenario_id=scenario_id, host_id=host_id,
                                                   backend_instance=_BACKEND_INSTANCE,
                                                   data={"command": command},
                                                   purpose="execute inside owned guest via QGA"))
        pid = int(response.get("pid", 0))
        if pid <= 0:
            return dict(response) if isinstance(response, Mapping) else {"result": response}
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = _data(self.client.request("GET", f"/api2/json/nodes/pve4-bbf/qemu/{vmid}/agent/exec-status", params={"pid": pid}, purpose="poll QGA process"))
            if result.get("exited"):
                stdout = str(result.get("out-data", "") or "")[:65536]
                stderr = str(result.get("err-data", "") or "")[:16384]
                return {"exitcode": result.get("exitcode", 1), "stdout": str(redact(stdout)), "stderr": str(redact(stderr))}
            time.sleep(min(self.settings.task_poll_interval, max(0, deadline - time.monotonic())))
        raise ProxmoxBackendError("guest process exceeded timeout")

    def _guest_write(self, vmid: int, path: str, content: str, scenario_id: str, host_id: str) -> None:
        allowed_paths = {"/opt/cr-runtime/docker-compose.yml", _COMPOSE_ENV_GUEST,
                         f"{_DEMO_APP_GUEST}/Dockerfile", f"{_DEMO_APP_GUEST}/server.py",
                         PROBE_SUPERVISOR_PATH}
        if path not in allowed_paths or len(content.encode()) > 60_000:
            raise ProxmoxBackendError("guest file path or size is not allowed")
        self._assert_owned(vmid, scenario_id, host_id)
        self._guest_exec(vmid, ["/usr/bin/install", "-d", "-m", "0700", "/opt/cr-runtime",
                                _DEMO_APP_GUEST],
                         scenario_id=scenario_id, host_id=host_id, timeout=20)
        self.client.request_owned("POST", f"/api2/json/nodes/pve4-bbf/qemu/{vmid}/agent/file-write",
                                  scenario_id=scenario_id, host_id=host_id, backend_instance=_BACKEND_INSTANCE,
                                  data={"file": path, "content": content},
                                  purpose="write compose file inside owned guest via QGA")

    def _compose_ps(self, vmid: int, scenario_id: str, host_id: str) -> dict[str, Any]:
        return self._guest_exec(vmid, _compose_command(scenario_id, "ps", "--format", "json"),
                                scenario_id=scenario_id, host_id=host_id, timeout=60)

    def _wait_stopped(self, vmid: int) -> None:
        deadline = time.monotonic() + min(self.settings.task_timeout, 180)
        while time.monotonic() < deadline:
            status = self._get(f"/api2/json/nodes/pve4-bbf/qemu/{vmid}/status/current")
            if status.get("status") == "stopped":
                return
            time.sleep(self.settings.task_poll_interval)
        raise ProxmoxBackendError("worker did not shut down within bound")


def _pool_vmids(members: Any) -> set[int]:
    result: set[int] = set()
    if not isinstance(members, list):
        return result
    for member in members:
        value = member.get("vmid") if isinstance(member, Mapping) else member
        try:
            result.add(int(value))
        except (TypeError, ValueError):
            continue
    return result


def _disk_size_gib(volume_config: str) -> int | None:
    match = re.search(r"(?:^|,)size=(\d+(?:\.\d+)?)([KMGTP])(?:i?B)?(?:,|$)", volume_config, re.IGNORECASE)
    if not match:
        return None
    size = float(match.group(1))
    unit = match.group(2).upper()
    scale = {"K": 1 / 1024**2, "M": 1 / 1024, "G": 1, "T": 1024, "P": 1024**2}[unit]
    gib = size * scale
    if not gib.is_integer():
        return None
    return int(gib)


def _description(value: Any) -> dict[str, Any]:
    if not isinstance(value, str) or len(value) > 4096:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}
