"""Proxmox runtime backend. Docker and Compose run only inside worker VMs via QGA."""
from __future__ import annotations

import hashlib
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

WORKER_MEMORY_MIB = 4096
WORKER_VCPUS = 2
WORKER_DISK_GIB = 20
# Owner-approved 2026-11-15: at most two product worker VMs (900100-900999) at once.
MAX_WORKER_VMS = 2
OWNER = "cyberrange"
_BACKEND_INSTANCE = "codex-20261115"
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
_ISOLATED_BRIDGE_OPT = "com.docker.network.bridge.gateway_mode_ipv4"
_ISOLATED_BRIDGE_OPTIONS = {_ISOLATED_BRIDGE_OPT: "isolated"}
_DEMO_APP_SOURCE = Path(__file__).resolve().parents[5] / "infra" / "templates" / "demo-app"
_DEMO_APP_GUEST = "/opt/cr-runtime/demo-app"
_COMPOSE_ENV_GUEST = "/opt/cr-runtime/compose.env"


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
            "updated_at TEXT NOT NULL, UNIQUE(scenario_id, host_id))"
        )
        _migrate_singleton_reservation(connection)
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
    connection.execute("DROP TABLE pve_worker_reservation")
    connection.commit()
    connection.execute("BEGIN EXCLUSIVE")


def _reservations(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT scenario_id, host_id, vmid, state FROM pve_worker_reservations ORDER BY vmid"
    ).fetchall()
    return [{"scenario_id": row[0], "host_id": row[1], "vmid": int(row[2]), "state": row[3]}
            for row in rows]


def _reservation(connection: sqlite3.Connection, vmid: int) -> dict[str, Any] | None:
    return next((held for held in _reservations(connection) if held["vmid"] == vmid), None)


def _persist_reservation(connection: sqlite3.Connection, *, scenario_id: str,
                         host_id: str, vmid: int, state: str) -> None:
    cursor = connection.execute(
        "INSERT INTO pve_worker_reservations(vmid, scenario_id, host_id, state, updated_at) "
        "VALUES(?, ?, ?, ?, ?) ON CONFLICT(vmid) DO UPDATE SET "
        "state=excluded.state, updated_at=excluded.updated_at "
        "WHERE scenario_id=excluded.scenario_id AND host_id=excluded.host_id",
        (vmid, scenario_id, host_id, state, datetime.now(timezone.utc).isoformat()),
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

    def preflight(self) -> dict[str, Any]:
        """Read-only readiness and capacity report; absence/failure means not ready."""
        report: dict[str, Any] = {"backend": "proxmox", "mode": self.settings.mode, "ok": False, "checks": {},
                                  "placement_target": self.placement_target()}
        try:
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
            if worker_vmid_count >= MAX_WORKER_VMS or running_pool_vms >= 4:
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
                       "guest_file": path} for path in sorted({*demo_files, _COMPOSE_ENV_GUEST})]),
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
        reservation_written = self.settings.mode == "live"
        if reservation_written:
            _persist_reservation(reservation_db, scenario_id=scenario_id, host_id=host_id,
                                 vmid=vmid, state="creating")
        nonce = secrets.token_hex(6)
        pending_name = f"cr-pending-{_pve_vm_name_id(scenario_id[:16])}-{nonce}"
        source_metadata = ready["checks"].get("template_source", {})
        description = json.dumps({"created_by": OWNER, "scenario_id": scenario_id, "host_id": host_id,
                                  "created_at": datetime.now(timezone.utc).isoformat(), "template": 900000,
                                  "compose_sha256": digest, "backend_instance": _BACKEND_INSTANCE, "role": "worker",
                                  "creation_nonce": nonce},
                                 sort_keys=True, separators=(",", ":"))
        vmname = f"cr-{_pve_vm_name_id(scenario_id[:20])}-worker"
        result: dict[str, Any] = {"ok": False, "vmid": vmid, "scenario_id": scenario_id, "state": "creating"}
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
            result.update(ok=True, state="running", compose_sha256=digest, isolation=isolation,
                          containers=self._compose_ps(vmid, scenario_id, host_id))
            if reservation_written:
                _persist_reservation(reservation_db, scenario_id=scenario_id, host_id=host_id,
                                     vmid=vmid, state="active")
            return result
        except (PveError, ProxmoxBackendError) as exc:
            result.update(state="failed", error=str(redact(str(exc))))
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
                or held["vmid"] != vmid or held["state"] != "active"):
            raise ProxmoxBackendError("matching active durable worker reservation is required for down")
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
                         f"{_DEMO_APP_GUEST}/Dockerfile", f"{_DEMO_APP_GUEST}/server.py"}
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
