"""Local-only Docker Compose lifecycle and durable deployment audit records."""
from __future__ import annotations

import json
import hashlib
import ipaddress
import os
import secrets
import socket
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any

import yaml

from app import config
from app.deploy import vm
from app.iac.generator import PlanError, generated_dir, get_generated, validate_id
from app.iac.generator import _PUBLISHED_PORT_MAX, _PUBLISHED_PORT_MIN
from app.planner.catalogue import load_components

_BASE_IMAGE = "python@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704"

# VM settings are deliberately bounded independently of the Compose backend.
VM_LIMITS = {"vcpus": 4, "memory_mib": 8192, "disk_gib": 100, "count": 4}
VM_OWNER = "cyberrange"
VM_URI = "qemu:///system"

# `compose up --wait` blocks until every service is running (and healthy when it has a
# healthcheck). JVM-based exercise targets need the longer bound.
_UP_WAIT_SECONDS = 240
_UP_ATTEMPTS = 3
_PROJECT_ONLY_OPERATIONS = {"ps", "down"}


def project_name(scenario_id: str) -> str:
    return f"cr-demo-{validate_id(scenario_id)}"


def _db() -> sqlite3.Connection:
    path = config.DATA_DIR / "deployments.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute(
        """CREATE TABLE IF NOT EXISTS deployment_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scenario_id TEXT NOT NULL,
            project_name TEXT NOT NULL,
            action TEXT NOT NULL,
            state TEXT NOT NULL,
            details TEXT NOT NULL,
            recorded_at TEXT NOT NULL
        )"""
    )
    db.execute("CREATE INDEX IF NOT EXISTS deployment_records_scenario_idx ON deployment_records(scenario_id, id)")
    db.execute("CREATE INDEX IF NOT EXISTS deployment_records_lifecycle_idx ON deployment_records(scenario_id, action, id)")
    return db


def record(scenario_id: str, action: str, state: str, details: dict[str, Any]) -> dict[str, Any]:
    scenario_id = validate_id(scenario_id)
    recorded_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with _db() as db:
        cursor = db.execute(
            "INSERT INTO deployment_records(scenario_id,project_name,action,state,details,recorded_at) VALUES(?,?,?,?,?,?)",
            (scenario_id, project_name(scenario_id), action, state, json.dumps(details, ensure_ascii=False), recorded_at),
        )
        record_id = int(cursor.lastrowid)
    return {"id": record_id, "scenario_id": scenario_id, "project_name": project_name(scenario_id),
            "action": action, "state": state, "details": details, "recorded_at": recorded_at}


def records(scenario_id: str, limit: int = 100) -> list[dict[str, Any]]:
    scenario_id = validate_id(scenario_id)
    with _db() as db:
        rows = db.execute(
            "SELECT * FROM deployment_records WHERE scenario_id=? ORDER BY id DESC LIMIT ?",
            (scenario_id, max(1, min(limit, 500))),
        ).fetchall()
    return [{"id": row["id"], "scenario_id": row["scenario_id"], "project_name": row["project_name"],
             "action": row["action"], "state": row["state"], "details": json.loads(row["details"]),
             "recorded_at": row["recorded_at"]} for row in rows]


def _lifecycle_records(scenario_id: str) -> list[dict[str, Any]]:
    """Read every up/down event so UI audit pagination cannot hide active ownership."""
    scenario_id = validate_id(scenario_id)
    with _db() as db:
        rows = db.execute(
            "SELECT * FROM deployment_records WHERE scenario_id=? AND action IN ('up','down') ORDER BY id DESC",
            (scenario_id,),
        ).fetchall()
    return [{"id": row["id"], "scenario_id": row["scenario_id"], "project_name": row["project_name"],
             "action": row["action"], "state": row["state"], "details": json.loads(row["details"]),
             "recorded_at": row["recorded_at"]} for row in rows]


# --- VM backend (B4 phase 1) -------------------------------------------------------
# The real implementation lives in app.deploy.vm. These wrappers keep the names used by
# the rest of the API, add the explicit licence acknowledgement and write audit records.

def _vm_run(args: list[str], timeout: int = 30) -> dict[str, Any]:
    """Run a virsh command line. Accepts the legacy ``[virsh, "-c", VM_URI, ...]`` form."""
    if len(args) >= 3 and args[1] == "-c" and args[2] == VM_URI:
        return vm.virsh(list(args[3:]), timeout=timeout)
    return _run(args, timeout=timeout)


def _vm_identity(scenario_id: str, vm_id: str) -> str:
    return vm.domain_name(validate_id(scenario_id), validate_id(vm_id))


def vm_preflight(image: str | Path | None = None, *, authorized: bool = False) -> dict[str, Any]:
    """Read-only readiness of the local libvirt/KVM backend.

    ``image`` is a template id (``tpl-<id>.qcow2`` in the pool). ``authorized`` is the
    caller's explicit confirmation that the evaluation licence terms were accepted;
    without it the backend reports not-ready even when everything else is in place.
    """
    report = vm.preflight()
    report["image"] = str(image) if image else None
    if not report["ok"]:
        return report
    if image is not None:
        try:
            present = vm.volume_exists(f"tpl-{validate_id(str(image))}.qcow2")
        except (vm.VmError, PlanError):
            present = False
        if not present:
            return {**report, "ok": False, "category": "image_missing",
                    "message": "VM 範本映像不存在：需先用評估版 ISO 建置範本"}
    if not authorized:
        return {**report, "ok": False, "category": "authorization_or_configuration",
                "message": "需明確確認已接受 Windows 評估版授權條款", "requires_explicit_authorized_image": True}
    return report


def vm_status(scenario_id: str, vm_id: str) -> dict[str, Any]:
    """Read-only VM status, including ownership verification."""
    scenario_id, vm_id = validate_id(scenario_id), validate_id(vm_id)
    name = _vm_identity(scenario_id, vm_id)
    state = vm.domain_state(name)
    if state == "absent":
        result: dict[str, Any] = {"state": "absent", "name": name}
    elif not vm.domain_owned(scenario_id, vm_id):
        result = {"state": "unverified", "name": name, "error": "VM ownership metadata is absent"}
    else:
        result = {"state": "running" if state == "running" else "stopped", "name": name, "libvirt_state": state}
    return {"scenario_id": scenario_id, "vm_id": vm_id, **result}


def _vm_audited(scenario_id: str, action: str, vm_id: str, call: Any) -> dict[str, Any]:
    try:
        outcome = {"ok": True, **call()}
    except vm.VmError as exc:
        outcome = {"ok": False, "state": "failed", "error": str(exc)}
    audit = record(scenario_id, action, str(outcome.get("state", "ok" if outcome["ok"] else "failed")),
                   {"vm_id": vm_id, "backend": "libvirt-qemu", "result": outcome})
    return {**outcome, "deployment_record": audit}


def vm_create(scenario_id: str, vm_id: str, image: str | Path, *, authorized: bool = False, vcpus: int = 2,
              memory_mib: int = 4096, networks: list[str] | None = None, **_ignored: Any) -> dict[str, Any]:
    """Create an owned VM from a template on isolated networks. Requires licence acknowledgement."""
    scenario_id, vm_id = validate_id(scenario_id), validate_id(vm_id)
    if not (1 <= vcpus <= VM_LIMITS["vcpus"] and 1024 <= memory_mib <= VM_LIMITS["memory_mib"]):
        raise PlanError(["VM resources exceed configured limits"])
    preflight = vm_preflight(image, authorized=authorized)
    if not preflight["ok"]:
        record(scenario_id, "vm_create", "preflight_failed", {"vm_id": vm_id, "preflight": preflight})
        return {"ok": False, "state": "preflight_failed", "preflight": preflight}
    return _vm_audited(scenario_id, "vm_create", vm_id, lambda: vm.vm_create(
        scenario_id, vm_id, str(image), networks=networks or ["lab"], vcpus=vcpus, memory_mib=memory_mib))


def vm_boot(scenario_id: str, vm_id: str, *, authorized: bool = False, **_ignored: Any) -> dict[str, Any]:
    scenario_id, vm_id = validate_id(scenario_id), validate_id(vm_id)
    preflight = vm_preflight(None, authorized=authorized)
    if not preflight["ok"]:
        return {"ok": False, "state": "preflight_failed", "preflight": preflight}
    return _vm_audited(scenario_id, "vm_boot", vm_id, lambda: vm.vm_boot(scenario_id, vm_id))


def vm_readiness(scenario_id: str, vm_id: str, *, timeout: int = 600, **_ignored: Any) -> dict[str, Any]:
    """Ready only when Windows answers through the guest agent; a running hypervisor is not enough."""
    scenario_id, vm_id = validate_id(scenario_id), validate_id(vm_id)
    try:
        return vm.vm_wait_ready(scenario_id, vm_id, timeout=timeout)
    except vm.VmError as exc:
        return {"ready": False, "state": "unverified", "guest_ready": False, "error": str(exc)}


def vm_health(scenario_id: str, vm_id: str) -> dict[str, Any]:
    return vm.vm_health(validate_id(scenario_id), validate_id(vm_id))


def vm_stop(scenario_id: str, vm_id: str, *, timeout: int = 180) -> dict[str, Any]:
    scenario_id, vm_id = validate_id(scenario_id), validate_id(vm_id)
    return _vm_audited(scenario_id, "vm_stop", vm_id, lambda: vm.vm_stop(scenario_id, vm_id, timeout=timeout))


def vm_destroy(scenario_id: str, vm_id: str, *, networks: list[str] | None = None, **_ignored: Any) -> dict[str, Any]:
    """Remove the VM, its overlay disk and (when listed) its isolated networks; ownership is verified first."""
    scenario_id, vm_id = validate_id(scenario_id), validate_id(vm_id)

    def run() -> dict[str, Any]:
        outcome = vm.vm_destroy(scenario_id, vm_id)
        outcome["networks"] = [vm.network_destroy(scenario_id, network_id) for network_id in networks or []]
        outcome["remaining"] = vm.scenario_inventory(scenario_id)
        if not outcome.get("ok"):
            raise vm.VmError(outcome.get("error") or "VM could not be removed")
        return outcome
    return _vm_audited(scenario_id, "vm_destroy", vm_id, run)


from app.deploy.backends import local_docker

# Stable manager API; Compose implementation is isolated in its backend module.
_docker_context_preflight = local_docker._docker_context_preflight
_compose_prefix = local_docker._compose_prefix
_run = local_docker._run
_real_image_refs = local_docker._real_image_refs
_port_is_free = local_docker._port_is_free
allocate_host_ports = local_docker.allocate_host_ports
_compose_command = local_docker._compose_command
_local_compose_ps_result = local_docker.compose_ps_result
_local_exec_in_service = local_docker.exec_in_service
_local_probe_in_service = local_docker.probe_in_service
_local_container_ipv4_addresses = local_docker.container_ipv4_addresses
_local_container_ipv4 = local_docker.container_ipv4
_parse_compose_ps = local_docker._parse_compose_ps


def deploy_backend() -> str:
    """Explicit runtime selection; invalid configuration never implies local fallback."""
    value = os.getenv("CR_DEPLOY_BACKEND", "local-docker").strip().lower()
    if value not in {"local-docker", "proxmox"}:
        raise PlanError(["CR_DEPLOY_BACKEND must be 'local-docker' or 'proxmox'"])
    return value


def _proxmox_backend() -> Any:
    """Load PVE code/config only when selected; configuration failures stay fail-closed."""
    try:
        from app.deploy.backends.proxmox import ProxmoxBackend
        return ProxmoxBackend.from_env()
    except Exception as exc:
        # Do not expose transport details or credentials through API errors.
        raise PlanError([f"Proxmox backend unavailable: {type(exc).__name__}"]) from None


def _active_proxmox_deployment(scenario_id: str) -> dict[str, Any] | None:
    """Resolve the latest still-live PVE up record; VMID never comes from the UI."""
    for entry in _lifecycle_records(scenario_id):
        details = entry.get("details") or {}
        if details.get("backend") != "proxmox":
            continue
        if entry.get("action") == "down" and entry.get("state") in {"stopped", "removed"}:
            return None
        if entry.get("action") == "up" and entry.get("state") == "running":
            vmid = details.get("vmid")
            host_id = details.get("host_id")
            if isinstance(vmid, int) and not isinstance(vmid, bool) and isinstance(host_id, str):
                return {"vmid": vmid, "host_id": host_id, "details": details}
        if entry.get("action") == "up" and entry.get("state") == "failed":
            outcome = details.get("result") or {}
            orphan = outcome.get("recoverable_orphan") if isinstance(outcome, dict) else None
            if isinstance(orphan, dict):
                vmid, host_id = orphan.get("vmid"), orphan.get("host_id")
                if isinstance(vmid, int) and isinstance(host_id, str):
                    return {"vmid": vmid, "host_id": host_id, "details": details, "orphan": True}
    return None


def _recorded_active_backend(scenario_id: str) -> str | None:
    """Find the latest active up/down state per backend, including legacy local records."""
    resolved: dict[str, bool] = {}
    for entry in _lifecycle_records(scenario_id):
        details = entry.get("details") or {}
        backend = details.get("backend") or "local-docker"
        if backend in resolved:
            continue
        if entry.get("action") == "down" and entry.get("state") in {"stopped", "removed"}:
            resolved[backend] = False
        elif entry.get("action") == "up" and entry.get("state") == "running":
            resolved[backend] = True
        elif entry.get("action") == "up" and entry.get("state") == "failed":
            outcome = details.get("result") or {}
            resolved[backend] = bool(isinstance(outcome, dict) and outcome.get("recoverable_orphan"))
    active = [backend for backend, is_active in resolved.items() if is_active]
    return active[0] if len(active) == 1 else ("conflict" if len(active) > 1 else None)


def _backend_conflict(scenario_id: str, selected: str) -> str | None:
    active = _recorded_active_backend(scenario_id)
    if active and active != selected:
        return f"scenario has an active {active} deployment; select that backend to inspect or stop it"
    return None


def _pve_result(result: Any) -> dict[str, Any]:
    """Normalize QGA process output to the manager's command-result shape."""
    if not isinstance(result, dict):
        return {"returncode": 127, "stdout": "", "stderr": "invalid PVE guest result"}
    return {"returncode": int(result.get("exitcode", result.get("returncode", 1))),
            "stdout": str(result.get("stdout", "")), "stderr": str(result.get("stderr", ""))}


def _pve_isolation_confirmed(report: Any) -> bool:
    return bool(isinstance(report, dict) and report.get("checked") is True
                and report.get("isolated") is True and report.get("evidence"))


def _pve_guest_exec(scenario_id: str, command: list[str], timeout: int, *,
                    require_isolation: bool = False) -> dict[str, Any]:
    deployment = _active_proxmox_deployment(scenario_id)
    if deployment is None:
        return {"returncode": 127, "stdout": "", "stderr": "no owned Proxmox worker is recorded"}
    try:
        backend = _proxmox_backend()
        result = backend.guest_exec(scenario_id, vmid=deployment["vmid"],
                                   host_id=deployment["host_id"], command=command,
                                   timeout=timeout, require_isolation=require_isolation)
        return _pve_result(result)
    except Exception as exc:
        return {"returncode": 127, "stdout": "", "stderr": f"Proxmox guest operation unavailable: {type(exc).__name__}"}


def compose_ps_result(scenario_id: str) -> dict[str, Any]:
    scenario_id = validate_id(scenario_id)
    selected = deploy_backend()
    conflict = _backend_conflict(scenario_id, selected)
    if conflict:
        return {"returncode": 127, "stdout": "", "stderr": conflict, "backend": selected}
    if selected == "local-docker":
        return _local_compose_ps_result(scenario_id)
    deployment = _active_proxmox_deployment(scenario_id)
    if deployment is None:
        return {"returncode": 0, "stdout": "", "stderr": ""}
    try:
        backend = _proxmox_backend()
        result = backend.status(scenario_id, vmid=deployment["vmid"], host_id=deployment["host_id"])
        vm_state = result.get("state", "unknown")
        compose = result.get("compose") or {}
        normalized = _pve_result(compose)
        normalized["vm_state"] = vm_state
        normalized["backend"] = "proxmox"
        if isinstance(result.get("placement"), dict):
            normalized["placement"] = result["placement"]
        return normalized
    except Exception as exc:
        return {"returncode": 127, "stdout": "", "stderr": f"Proxmox status unavailable: {type(exc).__name__}",
                "vm_state": "unknown", "backend": "proxmox"}


def exec_in_service(scenario_id: str, service_id: str, command: list[str], timeout: int = 10) -> dict[str, Any]:
    validate_id(service_id)
    if not command or any(not isinstance(arg, str) or "\x00" in arg for arg in command):
        return {"returncode": 2, "stdout": "", "stderr": "invalid internal check command"}
    selected = deploy_backend()
    conflict = _backend_conflict(scenario_id, selected)
    if conflict:
        return {"returncode": 127, "stdout": "", "stderr": conflict}
    if selected == "local-docker":
        return _local_exec_in_service(scenario_id, service_id, command, timeout)
    project = project_name(scenario_id)
    return _pve_guest_exec(scenario_id, ["/usr/bin/docker", "compose", "--env-file",
                                        "/opt/cr-runtime/compose.env", "--project-name", project,
                                        "--file", "/opt/cr-runtime/docker-compose.yml", "exec", "-T",
                                        service_id, *command], timeout, require_isolation=True)


def probe_in_service(scenario_id: str, service_id: str, python_script: str, timeout: int = 10) -> dict[str, Any]:
    scenario_id, service_id = validate_id(scenario_id), validate_id(service_id)
    if not isinstance(python_script, str) or not python_script or "\x00" in python_script:
        return {"returncode": 2, "stdout": "", "stderr": "invalid internal network probe"}
    selected = deploy_backend()
    conflict = _backend_conflict(scenario_id, selected)
    if conflict:
        return {"returncode": 127, "stdout": "", "stderr": conflict}
    if selected == "local-docker":
        return _local_probe_in_service(scenario_id, service_id, python_script, timeout)
    source = f"{project_name(scenario_id)}-{service_id}"
    command = ["/usr/bin/docker", "run", "--rm", "--pull=never", "--network", f"container:{source}",
               "--read-only", "--cap-drop=ALL", "--security-opt", "no-new-privileges:true",
               "--user", "65532:65532", "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m",
               local_docker._BASE_IMAGE, "python", "-c", python_script]
    return _pve_guest_exec(scenario_id, command, timeout, require_isolation=True)


def container_ipv4_addresses(scenario_id: str, service_id: str) -> list[dict[str, str]]:
    scenario_id, service_id = validate_id(scenario_id), validate_id(service_id)
    selected = deploy_backend()
    if _backend_conflict(scenario_id, selected):
        return []
    if selected == "local-docker":
        return _local_container_ipv4_addresses(scenario_id, service_id)
    result = _pve_guest_exec(scenario_id, ["/usr/bin/docker", "inspect", "-f",
                                           "{{json .NetworkSettings.Networks}}",
                                           f"{project_name(scenario_id)}-{service_id}"], 15,
                             require_isolation=True)
    if result["returncode"] != 0:
        return []
    try:
        networks = json.loads(result["stdout"])
    except json.JSONDecodeError:
        return []
    prefix = project_name(scenario_id) + "-"
    addresses = []
    for name, settings in sorted((networks or {}).items()):
        if not name.startswith(prefix) or name == prefix + "edge":
            continue
        try:
            ip = ipaddress.IPv4Address((settings or {}).get("IPAddress", ""))
        except ValueError:
            continue
        if not ip.is_loopback and not ip.is_unspecified:
            addresses.append({"network": name[len(prefix):], "ip": str(ip)})
    return addresses


def container_ipv4(scenario_id: str, service_id: str, from_service: str | None = None) -> str | None:
    addresses = container_ipv4_addresses(scenario_id, service_id)
    if not addresses:
        return None
    if from_service:
        source_networks = {item["network"] for item in container_ipv4_addresses(scenario_id, from_service)}
        for item in addresses:
            if item["network"] in source_networks:
                return item["ip"]
    return addresses[0]["ip"]

def live_containers(scenario_id: str) -> dict[str, Any]:
    result = compose_ps_result(scenario_id)
    containers = _parse_compose_ps(result["stdout"]) if result["returncode"] == 0 else []
    states = [c["state"] for c in containers]
    if result.get("backend") == "proxmox" and result.get("vm_state") != "running":
        state = "stopped" if result.get("vm_state") == "stopped" else "error"
    elif result["returncode"] != 0:
        state = "error"
    elif not containers:
        state = "not_created"
    elif all(s == "running" for s in states):
        state = "running"
    elif any(s == "running" for s in states):
        state = "partial"
    else:
        state = "stopped"
    live = {"scenario_id": validate_id(scenario_id), "project_name": project_name(scenario_id),
            "state": state, "containers": containers, "error": (result["stderr"] or None) if state == "error" else None}
    live["iac"] = iac_state(scenario_id)
    live["published_ports"] = [] if deploy_backend() == "proxmox" else published_ports(scenario_id, containers)
    if isinstance(result.get("placement"), dict):
        live["placement"] = result["placement"]
    return live


def iac_state(scenario_id: str) -> str:
    """'current' (generated and matching the plan), 'stale' (plan changed since) or 'not_generated'."""
    try:
        get_generated(scenario_id)
        return "current"
    except FileNotFoundError:
        return "not_generated"
    except PlanError:
        return "stale"


def published_ports(scenario_id: str, containers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Host ports that are really bound right now, attributed to the lab host they forward to.

    Read from the running gateway container, so every screen that shows a port can use
    this one list instead of remembering what an earlier deploy call returned.
    """
    if deploy_backend() == "proxmox":
        return []
    gateway = next((c for c in containers if c.get("service") == "cr-gateway"), None)
    if not gateway or gateway.get("state") != "running":
        return []
    try:
        mappings = get_generated(scenario_id)["report"].get("host_port_mappings", [])
    except (FileNotFoundError, PlanError):
        mappings = []
    by_listen = {20000 + index: mapping for index, mapping in enumerate(mappings)}
    seen: set[tuple[Any, Any]] = set()
    ports = []
    for item in gateway.get("ports", []):
        key = (item.get("host_ip"), item.get("host_port"))
        if key in seen:
            continue
        seen.add(key)
        target = by_listen.get(item.get("container_port"), {})
        ports.append({"host_id": target.get("host_id"), "container_port": target.get("container_port"),
                      "host_ip": item.get("host_ip"), "host_port": item.get("host_port")})
    return sorted(ports, key=lambda entry: (str(entry["host_id"]), entry["host_port"] or 0))


def callback_listener(scenario_id: str) -> dict[str, Any] | None:
    """The validation listener of this scenario as generated (name, port, networks), or None."""
    try:
        components = get_generated(scenario_id)["report"].get("platform_components", [])
    except (FileNotFoundError, PlanError):
        return None
    return next((item for item in components if item.get("kind") == "callback_listener"), None)


def callback_events(scenario_id: str, since: str | None = None) -> dict[str, Any]:
    """Connections the in-lab listener has recorded, each attributed to the lab host that made it.

    Evidence comes from the listener container's own output. ``since`` (an ISO timestamp
    from a previous call, e.g. the last event's ``ts``) returns only later events, so a
    caller can prove "this request produced this callback". ``peer_host`` is the service
    whose address made the connection, or None when it is not one of this scenario's.
    """
    scenario_id = validate_id(scenario_id)
    listener = callback_listener(scenario_id)
    result: dict[str, Any] = {"listener": listener, "running": False, "events": []}
    selected = deploy_backend()
    conflict = _backend_conflict(scenario_id, selected)
    if conflict:
        result["error"] = conflict
        return result
    if selected == "proxmox":
        if not listener:
            result["error"] = "this scenario has no callback listener"
            return result
        container = f"{project_name(scenario_id)}-{listener['id']}"
        state = _pve_guest_exec(scenario_id, ["/usr/bin/docker", "inspect", "-f", "{{.State.Running}}", container],
                                15, require_isolation=True)
        result["running"] = state["returncode"] == 0 and state["stdout"].strip() == "true"
        if not result["running"]:
            result["error"] = state["stderr"] or "listener container is not running"
            return result
        logs = _pve_guest_exec(scenario_id, ["/usr/bin/docker", "logs", container], 20, require_isolation=True)
        owners = {address["ip"]: host_id for component in get_generated(scenario_id)["report"].get("components", [])
                  for host_id in [component["host_id"]]
                  for address in container_ipv4_addresses(scenario_id, host_id)}
        for line in (logs.get("stdout", "") + logs.get("stderr", "")).splitlines():
            if not line.startswith("CALLBACK "):
                continue
            try:
                event = json.loads(line[len("CALLBACK "):])
            except json.JSONDecodeError:
                continue
            if since and str(event.get("ts", "")) <= since:
                continue
            event["peer_host"] = owners.get(event.get("peer_ip"))
            result["events"].append(event)
        return result
    docker, error = _docker_context_preflight()
    if not listener or error or not docker:
        result["error"] = error if listener else "this scenario has no callback listener"
        return result
    container = f"{project_name(scenario_id)}-{listener['id']}"
    state = _run([docker, "inspect", "-f", "{{.State.Running}}", container], timeout=15)
    result["running"] = state["returncode"] == 0 and state["stdout"].strip() == "true"
    if not result["running"]:
        result["error"] = "listener container is not running"
        return result
    logs = _run([docker, "logs", container], timeout=20)
    owners: dict[str, str] = {}
    try:
        hosts = [c["host_id"] for c in get_generated(scenario_id)["report"].get("components", [])]
    except (FileNotFoundError, PlanError):
        hosts = []
    for host_id in hosts:
        for address in container_ipv4_addresses(scenario_id, host_id):
            owners[address["ip"]] = host_id
    for line in (logs.get("stdout", "") + logs.get("stderr", "")).splitlines():
        if not line.startswith("CALLBACK "):
            continue
        try:
            event = json.loads(line[len("CALLBACK "):])
        except json.JSONDecodeError:
            continue
        if since and str(event.get("ts", "")) <= since:
            continue
        event["peer_host"] = owners.get(event.get("peer_ip"))
        result["events"].append(event)
    return result


def compose_fingerprint(scenario_id: str) -> str | None:
    try:
        import hashlib
        return hashlib.sha256(get_generated(scenario_id)["compose"].encode("utf-8")).hexdigest()
    except (FileNotFoundError, PlanError):
        return None


def _deployed_fingerprint(scenario_id: str) -> str | None:
    """Fingerprint recorded by the last successful `up` that has not been taken down since."""
    for entry in records(scenario_id, limit=50):
        if entry["action"] == "down" and entry["state"] == "stopped":
            return None
        if entry["action"] == "up" and entry["state"] == "running":
            return entry["details"].get("compose_sha256")
    return None


def capacity_preflight(scenario_id: str) -> dict[str, Any]:
    """Compare what the generated environment may use with what this machine has free.

    Requirements are the sum of the per-container limits in the generated file (the most
    the environment is allowed to use). Memory is a hard check; CPU and disk are reported.
    """
    if deploy_backend() == "proxmox":
        try:
            return _proxmox_backend().preflight()
        except PlanError as exc:
            return {"ok": False, "checked": True, "state": "unavailable", "reason": "; ".join(exc.errors)}
    report: dict[str, Any] = {"ok": True, "checked": False}
    try:
        document = yaml.safe_load(get_generated(scenario_id)["compose"])
    except (FileNotFoundError, PlanError, yaml.YAMLError):
        return {**report, "reason": "IaC 尚未生成，無法估算需求"}

    def to_mib(value: Any) -> float:
        text = str(value).strip().lower()
        units = {"k": 1 / 1024, "m": 1, "g": 1024}
        return float(text[:-1]) * units[text[-1]] if text and text[-1] in units else float(text) / 1048576

    services = document.get("services", {})
    required_mem = sum(to_mib(service.get("mem_limit", 0)) for service in services.values())
    required_cpus = sum(float(service.get("cpus", 0)) for service in services.values())
    available_mem = None
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                available_mem = int(line.split()[1]) / 1024
    except OSError:
        pass
    disk_free = None
    docker, error = _docker_context_preflight()
    missing_images: list[str] = []
    if docker and not error:
        root = _run([docker, "info", "--format", "{{.DockerRootDir}}"], timeout=10)["stdout"].strip()
        for candidate in (root, str(Path(root).parent) if root else "", "/"):
            try:
                disk_free = shutil.disk_usage(candidate).free / 1073741824 if candidate else None
                if disk_free is not None:
                    break
            except OSError:
                continue
        for image in sorted({service.get("image") for service in services.values()
                             if service.get("image") and not service.get("build")}):
            if _run([docker, "image", "inspect", image], timeout=15)["returncode"] != 0:
                missing_images.append(image)
    report.update(
        checked=True, containers=len(services),
        required={"memory_mib": round(required_mem), "cpus": round(required_cpus, 2)},
        available={"memory_mib": round(available_mem) if available_mem is not None else None,
                   "cpus": os.cpu_count(), "disk_free_gib": round(disk_free, 1) if disk_free is not None else None},
        images_to_download=missing_images,
    )
    problems = []
    if available_mem is not None and required_mem > available_mem:
        problems.append(f"記憶體不足：此環境上限合計 {round(required_mem)} MiB，本機目前可用 {round(available_mem)} MiB")
    if disk_free is not None and disk_free < 2 + 1.5 * len(missing_images):
        problems.append(f"磁碟空間不足：可用 {round(disk_free, 1)} GiB，仍需下載 {len(missing_images)} 個映像")
    notes = []
    if os.cpu_count() and required_cpus > os.cpu_count():
        notes.append(f"CPU 上限合計 {round(required_cpus, 2)} 核，超過本機 {os.cpu_count()} 核；可以執行但會變慢")
    if missing_images:
        notes.append(f"首次部署需下載 {len(missing_images)} 個映像")
    report.update(ok=not problems, problems=problems, notes=notes)
    return report


def deploy_preflight(scenario_id: str) -> dict[str, Any]:
    """Everything a person should see before pressing deploy. Read-only."""
    if deploy_backend() == "proxmox":
        conflict = _backend_conflict(scenario_id, "proxmox")
        if conflict:
            return {"scenario_id": validate_id(scenario_id), "backend": "proxmox", "ok": False,
                    "current_state": "backend_conflict", "error": conflict}
        live = live_containers(scenario_id)
        capacity = capacity_preflight(scenario_id)
        return {"scenario_id": validate_id(scenario_id), "backend": "proxmox", "iac": live["iac"],
                "current_state": live["state"], "isolation": capacity, "capacity": capacity,
                "would_change_running_environment": (live["state"] == "running" and
                    (_active_proxmox_deployment(scenario_id) or {}).get("details", {}).get("compose_source_sha256")
                    != compose_fingerprint(scenario_id))}
    live = live_containers(scenario_id)
    return {"scenario_id": validate_id(scenario_id), "iac": live["iac"], "current_state": live["state"],
            "isolation": isolation_preflight(scenario_id), "capacity": capacity_preflight(scenario_id),
            "would_change_running_environment": (live["state"] != "not_created"
                                                 and _deployed_fingerprint(scenario_id) != compose_fingerprint(scenario_id))}


def detect_lan_ipv4() -> str:
    """Ask the host routing table which IPv4 address it uses for outbound traffic."""
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("192.0.2.1", 80))
            address = probe.getsockname()[0]
        finally:
            probe.close()
        parsed = ipaddress.IPv4Address(address)
        if parsed.is_loopback or parsed.is_unspecified or parsed.is_link_local:
            raise ValueError("no usable LAN IPv4 address")
        return str(parsed)
    except (OSError, ValueError) as exc:
        raise PlanError(["could not detect a primary LAN IPv4 address; provide lan_host explicitly"]) from exc


def do_up(scenario_id: str, expose: str = "internal", lan_host: str | None = None) -> dict[str, Any]:
    scenario_id = validate_id(scenario_id)
    selected = deploy_backend()
    conflict = _backend_conflict(scenario_id, selected)
    if conflict:
        raise PlanError([conflict])
    if selected == "proxmox":
        if expose != "internal" or lan_host is not None:
            raise PlanError(["Proxmox deployment only supports expose='internal'; no host LAN publishing is available"])
        try:
            generated = get_generated(scenario_id)
        except (FileNotFoundError, PlanError) as exc:
            raise PlanError(["generate IaC before deploying to Proxmox"]) from exc
        compose = generated["compose"]
        source_digest = hashlib.sha256(compose.encode("utf-8")).hexdigest()
        existing = _active_proxmox_deployment(scenario_id)
        if existing:
            existing_isolation = host_isolation_report(scenario_id)
            if not _pve_isolation_confirmed(existing_isolation):
                audit = record(scenario_id, "up", "isolation_failed",
                               {"backend": "proxmox", "vmid": existing["vmid"],
                                "host_id": existing["host_id"], "isolation": existing_isolation,
                                "result": {"recoverable_orphan": {"vmid": existing["vmid"],
                                                                     "host_id": existing["host_id"]}}})
                return {"scenario_id": scenario_id, "project_name": project_name(scenario_id),
                        "backend": "proxmox", "state": "error", "ok": False,
                        "error": existing_isolation.get("error") or "PVE worker isolation was not confirmed",
                        "host_isolation": existing_isolation, "deployment_record": audit}
            live = live_containers(scenario_id)
            if (live["state"] == "running" and
                    existing["details"].get("compose_source_sha256") == source_digest):
                audit = record(scenario_id, "up", "running", {**existing["details"], "already_running": True,
                                                                 "isolation": existing_isolation})
                return {**live, "ok": True, "already_running": True, "backend": "proxmox",
                        "deployment_record": audit, "host_isolation": existing_isolation,
                        "command_result": {"returncode": 0, "stdout": "", "stderr": "already running"}}
            return {"scenario_id": scenario_id, "project_name": project_name(scenario_id), "backend": "proxmox",
                    "state": "error", "ok": False, "containers": [],
                    "error": "an owned Proxmox deployment already exists; stop it before replacing its Compose plan",
                    "command_result": {"returncode": 2, "stdout": "", "stderr": "existing deployment must be stopped first"}}
        backend = _proxmox_backend()
        try:
            outcome = backend.up(scenario_id, compose, host_id="worker", attach_lab_network=False,
                                 compose_sha256=source_digest)
        except Exception as exc:
            outcome = {"ok": False, "state": "failed", "error": f"Proxmox deployment failed: {type(exc).__name__}"}
        success = outcome.get("ok") is True and outcome.get("state") == "running"
        isolation = None
        if success:
            isolation = _proxmox_isolation_report(scenario_id, outcome.get("vmid"), "worker", backend=backend)
            outcome["isolation"] = isolation
            if not isolation["isolated"]:
                success = False
                outcome.update(ok=False, state="failed", error="Proxmox worker isolation was not confirmed")
                try:
                    cleanup = backend.down(scenario_id, vmid=outcome["vmid"], host_id="worker")
                    outcome["cleanup"] = cleanup
                    if not cleanup.get("ok"):
                        outcome["recoverable_orphan"] = {"vmid": outcome["vmid"], "scenario_id": scenario_id,
                                                         "host_id": "worker", "state": "isolation_unconfirmed"}
                except Exception as exc:
                    outcome["cleanup"] = {"ok": False, "error": type(exc).__name__}
                    outcome["recoverable_orphan"] = {"vmid": outcome["vmid"], "scenario_id": scenario_id,
                                                     "host_id": "worker", "state": "isolation_unconfirmed"}
        state = "running" if success else str(outcome.get("state") or "failed")
        details = {"backend": "proxmox", "vmid": outcome.get("vmid"), "host_id": "worker",
                   "compose_sha256": source_digest, "compose_source_sha256": source_digest,
                   "proxmox_compose_sha256": outcome.get("compose_sha256"),
                   "isolation": isolation or outcome.get("isolation"),
                   "result": outcome, "published_ports": []}
        audit = record(scenario_id, "up", state, details)
        raw_containers = outcome.get("containers")
        if success and isinstance(raw_containers, dict):
            parsed_containers = _pve_result(raw_containers)
            containers = (_parse_compose_ps(parsed_containers["stdout"])
                          if parsed_containers["returncode"] == 0 else [])
        else:
            containers = raw_containers if success and isinstance(raw_containers, list) else []
        return {"scenario_id": scenario_id, "project_name": project_name(scenario_id), "backend": "proxmox",
                "state": "running" if success else ("planned" if state == "planned" else "error"),
                "containers": containers, "published_ports": [], "ok": bool(outcome.get("ok")),
                "already_running": False, "compose_sha256": source_digest,
                "error": None if success or state == "planned" else outcome.get("error"),
                "command_result": {"returncode": 0 if outcome.get("ok") else 2,
                                   "stdout": "", "stderr": "" if outcome.get("ok") else str(outcome.get("error", state))},
                "deployment_record": audit, "preflight": outcome.get("preflight"), "host_isolation": isolation}
    if expose not in {"internal", "lan"}:
        raise PlanError(["expose must be 'internal' or 'lan'"])
    resolved_host = None
    password = None
    if expose == "lan":
        try:
            resolved_host = str(ipaddress.IPv4Address(lan_host)) if lan_host else detect_lan_ipv4()
            parsed = ipaddress.IPv4Address(resolved_host)
            if parsed.is_loopback or parsed.is_unspecified or parsed.is_link_local or parsed.is_multicast:
                raise ValueError("not a usable LAN IPv4 address")
        except ValueError as exc:
            raise PlanError(["lan_host must be a usable LAN IPv4 address"] if lan_host else
                            ["could not detect a primary LAN IPv4 address; provide lan_host explicitly"]) from exc
        password = secrets.token_urlsafe(24)
    bind_ip = resolved_host or "127.0.0.1"
    preflight = isolation_preflight(scenario_id)
    if not preflight["ok"] and preflight.get("vulnerable_hosts"):
        audit = record(scenario_id, "up", "rejected", {"reason": preflight.get("reason"), "preflight": preflight})
        return {"scenario_id": validate_id(scenario_id), "project_name": project_name(scenario_id),
                "state": "error", "containers": [], "error": preflight.get("reason"), "ok": False,
                "command_result": {"returncode": 2, "stdout": "", "stderr": preflight.get("reason", "")},
                "deployment_record": audit, "expose": expose, "lan_host": resolved_host,
                "isolation_preflight": preflight}
    fingerprint = compose_fingerprint(scenario_id)
    before = live_containers(scenario_id)
    if before["state"] == "running" and fingerprint and _deployed_fingerprint(scenario_id) == fingerprint:
        current_ips = {entry["host_ip"] for entry in before["published_ports"]}
        if current_ips and current_ips != {bind_ip}:
            raise PlanError(["環境已在執行，且目前對外綁定在 " + "、".join(sorted(map(str, current_ips)))
                             + f"；要改成綁定 {bind_ip}，請先清除環境再重新部署"])
        healthy = all(c.get("health") in {"", "healthy"} for c in before["containers"])
        if healthy:
            # Same generated environment is already up and healthy: starting it again must
            # not recreate the database or move published ports.
            audit = record(scenario_id, "up", "running", {"already_running": True, "compose_sha256": fingerprint,
                                                          "published_ports": before["published_ports"]})
            return {**before, "ok": True, "already_running": True,
                    "message": "環境已在執行且與目前的 IaC 相同；沒有重建任何容器，連接埠維持不變。",
                    "command_result": {"returncode": 0, "stdout": "", "stderr": "already running; nothing changed"},
                    "deployment_record": audit, "expose": expose, "lan_host": resolved_host, "attempts": [],
                    "isolation_preflight": preflight, "host_isolation": host_isolation_report(scenario_id)}
    replacing = before["state"] != "not_created"
    capacity = capacity_preflight(scenario_id)
    if not capacity["ok"] and not replacing:
        audit = record(scenario_id, "up", "rejected", {"reason": "insufficient host capacity", "capacity": capacity})
        message = "；".join(capacity["problems"])
        return {"scenario_id": validate_id(scenario_id), "project_name": project_name(scenario_id),
                "state": "not_created", "containers": [], "error": message, "ok": False,
                "command_result": {"returncode": 2, "stdout": "", "stderr": message},
                "deployment_record": audit, "expose": expose, "lan_host": resolved_host,
                "isolation_preflight": preflight, "capacity": capacity}
    attempts: list[dict[str, Any]] = []
    cleanup = None
    diagnostics = None
    avoid: set[int] = set()
    result: dict[str, Any] = {"returncode": 2, "stdout": "", "stderr": "deployment was not attempted"}
    live: dict[str, Any] = {}
    success = False
    for attempt in range(1, _UP_ATTEMPTS + 1):
        host_ports = allocate_host_ports(scenario_id, bind_ip, avoid)
        result = _compose_command(
            scenario_id, "up",
            ["-d", "--pull", "never", "--wait", "--wait-timeout", str(_UP_WAIT_SECONDS)],
            timeout=_UP_WAIT_SECONDS + 1200, expose=expose, lan_host=resolved_host, pg_password=password,
            host_ports=host_ports)
        if password:
            result = {**result,
                      "stdout": result.get("stdout", "").replace(password, "[REDACTED]"),
                      "stderr": result.get("stderr", "").replace(password, "[REDACTED]")}
        live = live_containers(scenario_id)
        success = result["returncode"] == 0 and live["state"] == "running"
        attempts.append({"attempt": attempt, "exit_code": result["returncode"],
                         "host_ports": {key: int(value) for key, value in host_ports.items()}})
        if success:
            break
        # A failed deployment must not leave half an environment behind: capture why it
        # failed first, then remove everything this attempt created.
        created_something = bool(live.get("containers")) or "Created" in result.get("stderr", "")
        diagnostics = failure_diagnostics(scenario_id, live) if created_something else None
        cleanup = _cleanup_failed_up(scenario_id) if created_something else None
        port_clash = "port is already allocated" in result.get("stderr", "") or \
            "address already in use" in result.get("stderr", "")
        if not port_clash:
            break
        avoid.update(int(value) for value in host_ports.values())
    isolation = host_isolation_report(scenario_id) if success else None
    if success and not isolation["isolated"] and preflight.get("vulnerable_hosts"):
        # Never leave a deliberately vulnerable image running on a network from which
        # it can reach the host.
        diagnostics = {"isolation": isolation}
        cleanup = _cleanup_failed_up(scenario_id)
        success = False
        result = {**result, "returncode": 3,
                  "stderr": "deployment removed: lab networks are not isolated from the host, and the plan contains "
                            "deliberately vulnerable images (" + ", ".join(preflight["vulnerable_hosts"]) + ")"}
        live = live_containers(scenario_id)
    published = []
    if success and attempts:
        try:
            for mapping in get_generated(scenario_id)["report"].get("host_port_mappings", []):
                assigned = attempts[-1]["host_ports"].get(mapping["env"])
                published.append({"host_id": mapping["host_id"], "container_port": mapping["container_port"],
                                  "host_ip": bind_ip, "host_port": assigned})
        except (FileNotFoundError, PlanError):
            published = []
    if not success:
        live = {**live, "state": "error", "error": result["stderr"] or live.get("error")}
    details = {"exit_code": result["returncode"], "stdout": result["stdout"], "stderr": result["stderr"],
               "backend": "local-docker",
               "expose": expose, "password_set": password is not None, "attempts": attempts,
               "host_isolation": isolation, "compose_sha256": fingerprint if success else None,
               "replaced_existing_environment": replacing, **live, "published_ports": published}
    if diagnostics is not None:
        details["diagnostics"] = diagnostics
    if cleanup is not None:
        details["cleanup"] = cleanup
    audit = record(scenario_id, "up", "running" if success else "failed", details)
    response = {**live, "ok": success, "command_result": result, "deployment_record": audit,
                "expose": expose, "lan_host": resolved_host, "attempts": attempts,
                "published_ports": published, "isolation_preflight": preflight, "capacity": capacity,
                "already_running": False, "replaced_existing_environment": replacing}
    if success and replacing:
        response["message"] = ("部署前已有這個情境的容器，且 IaC 與上次部署不同（或環境不完整）；"
                               "已依目前的 IaC 重建，資料庫等服務的資料已重設，對外連接埠可能改變。")
    if isolation is not None:
        response["host_isolation"] = isolation
    if diagnostics is not None:
        response["diagnostics"] = diagnostics
    if cleanup is not None:
        response["cleanup"] = cleanup
    if password is not None:
        response["db_password"] = password
    return response


def _bridge_ipv4(interface: str) -> str | None:
    """IPv4 address of a host network interface, or None when it has none / does not exist."""
    import fcntl
    import struct
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        packed = fcntl.ioctl(probe.fileno(), 0x8915, struct.pack("256s", interface[:15].encode()))  # SIOCGIFADDR
        return socket.inet_ntoa(packed[20:24])
    except OSError:
        return None
    finally:
        probe.close()


def _proxmox_isolation_report(scenario_id: str, vmid: Any, host_id: str, *, backend: Any = None) -> dict[str, Any]:
    """Ask only the selected PVE backend for guest-side isolation evidence; absence fails closed."""
    unavailable = {"isolated": False, "checked": False, "evidence": None}
    if isinstance(vmid, bool) or not isinstance(vmid, int) or not host_id:
        return {**unavailable, "error": "invalid Proxmox deployment identity for isolation check"}
    try:
        backend = backend or _proxmox_backend()
        reporter = getattr(backend, "isolation_report", None)
        if not callable(reporter):
            return {**unavailable, "error": "Proxmox backend does not provide isolation_report"}
        report = reporter(validate_id(scenario_id), vmid=vmid, host_id=host_id)
        if not isinstance(report, dict):
            return {**unavailable, "error": "Proxmox isolation_report returned invalid data"}
        evidence = report.get("evidence", report.get("details"))
        checked = report.get("checked") is True
        isolated = report.get("isolated") is True and checked and bool(evidence)
        return {**report, "checked": checked, "evidence": evidence, "isolated": isolated,
                **({} if isolated else {"error": report.get("error") or
                                       "Proxmox isolation evidence is missing or does not confirm isolation"})}
    except Exception as exc:
        return {**unavailable, "error": f"Proxmox isolation check unavailable: {type(exc).__name__}"}


def vulnerable_hosts(scenario_id: str) -> list[str]:
    return local_docker.vulnerable_hosts(scenario_id)


def isolation_preflight(scenario_id: str) -> dict[str, Any]:
    """Check Docker readiness and enforce D6 before any Docker or isolation checks.

    For non-vulnerable plans the Docker Engine 28 isolation check is unchanged.
    """
    if deploy_backend() == "proxmox":
        return _proxmox_backend().preflight()
    vulnerable = vulnerable_hosts(scenario_id)
    result: dict[str, Any] = {"ok": True, "vulnerable_hosts": vulnerable, "docker_version": None}
    if vulnerable:
        return {**result, "ok": False, "reason":
                "local Docker is restricted to non-attack QA and refuses deliberately vulnerable images: "
                + ", ".join(vulnerable)}
    docker, error = _docker_context_preflight()
    if error or not docker:
        return {**result, "ok": False, "reason": error or "docker executable is not installed"}
    version = _run([docker, "version", "--format", "{{.Server.Version}}"], timeout=10)
    text = version.get("stdout", "").strip()
    result["docker_version"] = text or None
    try:
        major = int(text.split(".")[0])
    except ValueError:
        major = 0
    result["host_isolation_supported"] = major >= 28
    if major < 28:
        result["risk"] = ("this Docker engine cannot create address-less internal bridges; lab containers could "
                          "reach host services bound on all interfaces")
    return result


def host_isolation_report(scenario_id: str) -> dict[str, Any]:
    """After deploying: verify on the real host that no plan network bridge has a host address."""
    scenario_id = validate_id(scenario_id)
    if deploy_backend() == "proxmox":
        conflict = _backend_conflict(scenario_id, "proxmox")
        if conflict:
            return {"isolated": False, "checked": False, "evidence": None, "error": conflict}
        deployment = _active_proxmox_deployment(scenario_id)
        if deployment is None:
            return {"isolated": False, "checked": False, "evidence": None,
                    "error": "no owned Proxmox worker is recorded"}
        return _proxmox_isolation_report(scenario_id, deployment["vmid"], deployment["host_id"])
    docker, error = _docker_context_preflight()
    project = project_name(scenario_id)
    report: dict[str, Any] = {"isolated": False, "networks": []}
    if error or not docker:
        return {**report, "error": error}
    listed = _run([docker, "network", "ls", "--filter", f"label=com.docker.compose.project={project}",
                   "--format", "{{.ID}} {{.Name}}"], timeout=15)
    if listed["returncode"] != 0:
        return {**report, "error": listed["stderr"][:500]}
    all_isolated = True
    for line in listed["stdout"].splitlines():
        short_id, _, name = line.partition(" ")
        if not name.startswith(project + "-"):
            continue
        is_edge = name == f"{project}-edge"
        bridge = f"br-{short_id[:12]}"
        address = _bridge_ipv4(bridge)
        entry = {"network": name[len(project) + 1:], "bridge": bridge, "host_address": address,
                 "role": "publishing (gateway container only)" if is_edge else "lab",
                 "host_reachable_from_containers": address is not None}
        if not is_edge and address is not None:
            all_isolated = False
        report["networks"].append(entry)
    report["isolated"] = all_isolated and bool(report["networks"])
    report["checked"] = bool(report["networks"])
    report["evidence"] = report["networks"]
    return report


def failure_diagnostics(scenario_id: str, live: dict[str, Any] | None = None) -> dict[str, Any]:
    """Per-container state, exit code and last log lines for a deployment that did not come up."""
    live = live or live_containers(scenario_id)
    docker, error = _docker_context_preflight()
    report: dict[str, Any] = {"containers": []}
    if error or not docker:
        report["error"] = error
        return report
    for container in live.get("containers", []):
        ok = container.get("state") == "running" and container.get("health") in {"", "healthy"}
        entry = {key: container.get(key) for key in ("service", "state", "status", "health", "exit_code")}
        entry["ok"] = ok
        if not ok and container.get("name", "").startswith(project_name(scenario_id) + "-"):
            logs = _run([docker, "logs", "--tail", "40", container["name"]], timeout=20)
            entry["log_tail"] = (logs.get("stdout", "") + logs.get("stderr", ""))[-3000:]
            if container.get("health") == "unhealthy":
                health = _run([docker, "inspect", "-f",
                               "{{range .State.Health.Log}}{{.ExitCode}} {{.Output}}{{end}}", container["name"]],
                              timeout=15)
                entry["healthcheck_output"] = health.get("stdout", "")[-1000:]
        report["containers"].append(entry)
    return report


def _remove_local_images(scenario_id: str) -> list[str]:
    """Delete the demo images this scenario built locally (``cr-demo-<id>-<host>:local``).

    Catalogue images are shared between scenarios and stay cached; only the per-scenario
    build output is removed so repeated deployments do not pile images up on the host.
    """
    docker, error = _docker_context_preflight()
    if error or not docker:
        return []
    prefix = project_name(scenario_id) + "-"
    listed = _run([docker, "images", "--filter", f"reference={prefix}*:local",
                   "--format", "{{.Repository}}:{{.Tag}}"], timeout=20)
    removed = []
    for reference in listed.get("stdout", "").split():
        if reference.startswith(prefix) and reference.endswith(":local"):
            if _run([docker, "image", "rm", reference], timeout=30)["returncode"] == 0:
                removed.append(reference)
    return removed


def _cleanup_failed_up(scenario_id: str) -> dict[str, Any]:
    down = _compose_command(scenario_id, "down", ["-v", "--remove-orphans"], timeout=180)
    remaining = live_containers(scenario_id)
    _remove_local_images(scenario_id)
    return {"exit_code": down["returncode"], "stderr": down["stderr"][-1000:],
            "remaining_containers": [c.get("name") for c in remaining.get("containers", [])],
            "clean": down["returncode"] == 0 and not remaining.get("containers")}


def do_status(scenario_id: str) -> dict[str, Any]:
    # Read-only poll: must NOT write an audit record (GUI polls this often).
    return {**live_containers(scenario_id), "backend": deploy_backend()}


def do_health(scenario_id: str) -> dict[str, Any]:
    live = live_containers(scenario_id)
    running = [c for c in live["containers"] if c["state"] == "running"]
    unhealthy = [c for c in running if c["health"] == "unhealthy"]
    starting = [c for c in running if c["health"] == "starting"]
    healthy = live["state"] == "running" and not unhealthy and not starting
    if unhealthy:
        state = "unhealthy"
    elif starting and live["state"] == "running":
        state = "starting"
    elif healthy:
        state = "healthy"
    else:
        state = live["state"]
    # Read-only health poll: must NOT write an audit record (GUI polls this often).
    return {"scenario_id": live["scenario_id"], "project_name": live["project_name"], "state": state,
            "healthy": healthy, "containers": live["containers"], "error": live["error"]}


def do_down(scenario_id: str) -> dict[str, Any]:
    scenario_id = validate_id(scenario_id)
    selected = deploy_backend()
    conflict = _backend_conflict(scenario_id, selected)
    if conflict:
        return {"scenario_id": scenario_id, "project_name": project_name(scenario_id), "backend": selected,
                "state": "failed", "ok": False,
                "command_result": {"returncode": 2, "stdout": "", "stderr": conflict}}
    if selected == "proxmox":
        existing = _active_proxmox_deployment(scenario_id)
        if existing is None:
            audit = record(scenario_id, "down", "stopped", {"backend": "proxmox", "already_stopped": True})
            return {"scenario_id": scenario_id, "project_name": project_name(scenario_id),
                    "backend": "proxmox", "state": "stopped", "ok": True,
                    "command_result": {"returncode": 0, "stdout": "", "stderr": "no active Proxmox worker"},
                    "deployment_record": audit}
        try:
            outcome = _proxmox_backend().down(scenario_id, vmid=existing["vmid"], host_id=existing["host_id"])
        except Exception as exc:
            outcome = {"ok": False, "state": "failed", "error": f"Proxmox cleanup failed: {type(exc).__name__}"}
        success = outcome.get("ok") is True
        audit = record(scenario_id, "down", "stopped" if success else "failed",
                       {"backend": "proxmox", "vmid": existing["vmid"], "host_id": existing["host_id"],
                        "result": outcome})
        return {"scenario_id": scenario_id, "project_name": project_name(scenario_id), "backend": "proxmox",
                "state": "stopped" if success else "failed", "ok": success,
                "command_result": {"returncode": 0 if success else 2, "stdout": "",
                                   "stderr": "" if success else str(outcome.get("error", "Proxmox cleanup failed"))},
                "deployment_record": audit}
    result = _compose_command(scenario_id, "down", ["-v", "--remove-orphans"], timeout=180)
    state = "stopped" if result["returncode"] == 0 else "failed"
    removed_images = _remove_local_images(scenario_id) if result["returncode"] == 0 else []
    details = {"exit_code": result["returncode"], "stdout": result["stdout"], "stderr": result["stderr"],
               "backend": "local-docker", "removed_local_images": removed_images}
    audit = record(scenario_id, "down", state, details)
    return {"scenario_id": validate_id(scenario_id), "project_name": project_name(scenario_id),
            "state": state, "ok": result["returncode"] == 0, "command_result": result,
            "deployment_record": audit}


def do_reset(scenario_id: str) -> dict[str, Any]:
    """Reset the active Proxmox worker to its approved deployed snapshot."""
    scenario_id = validate_id(scenario_id)
    selected = deploy_backend()
    if selected != "proxmox":
        return {"scenario_id": scenario_id, "backend": selected, "state": "failed", "ok": False,
                "error": "reset is supported only for an active Proxmox worker"}
    conflict = _backend_conflict(scenario_id, selected)
    if conflict:
        return {"scenario_id": scenario_id, "backend": selected, "state": "failed", "ok": False,
                "error": conflict}
    existing = _active_proxmox_deployment(scenario_id)
    if existing is None or existing.get("orphan"):
        return {"scenario_id": scenario_id, "backend": selected, "state": "failed", "ok": False,
                "error": "active owned Proxmox worker deployment is required for reset"}
    try:
        outcome = _proxmox_backend().reset(scenario_id, vmid=existing["vmid"], host_id=existing["host_id"])
    except Exception as exc:
        outcome = {"ok": False, "state": "failed", "error": f"Proxmox reset failed: {type(exc).__name__}"}
    success = outcome.get("ok") is True
    audit = record(scenario_id, "reset", "running" if success else "failed",
                   {"backend": "proxmox", "vmid": existing["vmid"], "host_id": existing["host_id"],
                    "result": outcome})
    return {"scenario_id": scenario_id, "project_name": project_name(scenario_id), "backend": selected,
            "state": "running" if success else "failed", "ok": success, "result": outcome,
            "deployment_record": audit}

