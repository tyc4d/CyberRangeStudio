"""Local-only Docker Compose lifecycle and durable deployment audit records."""
from __future__ import annotations

import json
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


def _docker_context_preflight() -> tuple[str | None, str | None]:
    docker = shutil.which("docker")
    if not docker:
        return None, "docker executable is not installed"
    env = os.environ.copy()
    host_env = env.get("DOCKER_HOST")
    if host_env:
        if not host_env.startswith("unix://"):
            return None, "refusing non-local Docker host; DOCKER_HOST must use a local unix:// socket"
        return docker, None
    try:
        current = subprocess.run([docker, "context", "show"], capture_output=True, text=True, timeout=5, env=env)
        if current.returncode != 0:
            return None, f"cannot read Docker context: {current.stderr.strip()[:500]}"
        context_name = env.get("DOCKER_CONTEXT") or current.stdout.strip()
        if not context_name or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for ch in context_name):
            return None, "invalid Docker context name"
        inspected = subprocess.run([docker, "context", "inspect", context_name], capture_output=True, text=True,
                                   timeout=5, env=env)
        if inspected.returncode != 0:
            return None, f"cannot inspect Docker context: {inspected.stderr.strip()[:500]}"
        contexts = json.loads(inspected.stdout)
        endpoint = contexts[0]["Endpoints"]["docker"]["Host"]
        if not endpoint.startswith("unix://"):
            return None, "refusing non-local Docker context; only local unix:// endpoints are allowed"
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, IndexError) as exc:
        return None, f"Docker local-context check failed: {exc}"
    return docker, None


def _compose_prefix(scenario_id: str, docker: str) -> tuple[list[str] | None, str | None]:
    scenario_id = validate_id(scenario_id)
    try:
        get_generated(scenario_id)
    except FileNotFoundError:
        return None, "compose file has not been generated"
    except PlanError as exc:
        return None, str(exc)
    compose_file = generated_dir(scenario_id) / "docker-compose.yml"
    prefix = [docker, "compose", "--env-file", "/dev/null", "-p", project_name(scenario_id), "-f", str(compose_file)]
    return prefix, None


def _run(args: list[str], timeout: int = 60, env_overrides: dict[str, str] | None = None) -> dict[str, Any]:
    try:
        env = os.environ.copy()
        # Buildx records builder activity under its config directory. The worker
        # sandbox keeps the home directory read-only, so keep that runtime state
        # under the permitted temporary directory instead.
        env["BUILDX_CONFIG"] = "/tmp/cr-demo-buildx"
        if env_overrides:
            env.update(env_overrides)
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=env)
        return {"returncode": result.returncode, "stdout": result.stdout[-12000:], "stderr": result.stderr[-4000:]}
    except subprocess.TimeoutExpired as exc:
        return {"returncode": 124, "stdout": (exc.stdout or "")[-12000:] if isinstance(exc.stdout, str) else "",
                "stderr": f"command timed out after {timeout}s"}
    except OSError as exc:
        return {"returncode": 127, "stdout": "", "stderr": str(exc)}


def _real_image_refs(scenario_id: str) -> tuple[list[str] | None, str | None]:
    """Return only catalogue-pinned images from the validated generated Compose file."""
    try:
        generated = get_generated(scenario_id)
        document = yaml.safe_load(generated["compose"])
    except (FileNotFoundError, PlanError, yaml.YAMLError) as exc:
        return None, str(exc)
    allowed = {entry.get("pinned_image") for entry in load_components()
               if entry.get("pinned_image") and entry.get("digest")}
    images: list[str] = []
    for service_name, service in document.get("services", {}).items():
        image = service.get("image")
        if not image or image == _BASE_IMAGE or image.startswith("cr-demo-") and service.get("build"):
            continue
        if image not in allowed or "@sha256:" not in image:
            return None, f"refusing to pull non-catalogue or unpinned image for {service_name}: {image!r}"
        if image not in images:
            images.append(image)
    return images, None


def _port_is_free(bind_ip: str, port: int) -> bool:
    """True when nothing (including a Docker proxy) is listening on bind_ip:port."""
    for address in {bind_ip, "0.0.0.0"}:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.bind((address, port))
        except OSError:
            return False
        finally:
            probe.close()
    return True


def allocate_host_ports(scenario_id: str, bind_ip: str = "127.0.0.1",
                        avoid: set[int] | None = None) -> dict[str, str]:
    """Pick a free host port in the allowed range for every published service.

    The generated Compose file only carries defaults (42000, 42001, ...); two scenarios
    deployed at the same time would otherwise fight over the same ports.
    """
    try:
        mappings = get_generated(scenario_id)["report"].get("host_port_mappings", [])
    except (FileNotFoundError, PlanError):
        return {}
    taken = set(avoid or ())
    span = _PUBLISHED_PORT_MAX - _PUBLISHED_PORT_MIN + 1
    start = secrets.randbelow(span)
    assigned: dict[str, str] = {}
    for mapping in mappings:
        chosen = None
        for offset in range(span):
            candidate = _PUBLISHED_PORT_MIN + (start + offset) % span
            if candidate not in taken and _port_is_free(bind_ip, candidate):
                chosen = candidate
                break
        if chosen is None:
            raise PlanError(["no free host port is available in 42000-42999"])
        taken.add(chosen)
        start = (chosen - _PUBLISHED_PORT_MIN + 1) % span
        assigned[mapping["env"]] = str(chosen)
    return assigned


def _compose_command(scenario_id: str, operation: str, extra: list[str] | None = None,
                     timeout: int = 60, *, expose: str = "internal", lan_host: str | None = None,
                     pg_password: str | None = None,
                     host_ports: dict[str, str] | None = None) -> dict[str, Any]:
    docker, error = _docker_context_preflight()
    if error:
        return {"returncode": 127, "stdout": "", "stderr": error}
    assert docker
    prefix, error = _compose_prefix(scenario_id, docker)
    if error:
        return {"returncode": 2, "stdout": "", "stderr": error}
    assert prefix
    bind_ip = "127.0.0.1"
    # Compose requires a non-empty value for interpolation even in internal mode.
    # Internal PostgreSQL still uses trust auth and this throwaway value is never persisted.
    generated_secret = pg_password or secrets.token_urlsafe(24)
    env_overrides = {"CR_BIND_IP": bind_ip, "CR_PG_AUTH_METHOD": "trust",
                     "CR_PG_PASSWORD": generated_secret, "CR_DB_PASSWORD": generated_secret}
    if expose == "lan":
        bind_ip = lan_host or detect_lan_ipv4()
        env_overrides.update({"CR_BIND_IP": bind_ip, "CR_PG_AUTH_METHOD": "scram-sha-256"})
    if host_ports:
        env_overrides.update(host_ports)
    config_check = _run(prefix + ["config", "--quiet"], timeout=15, env_overrides=env_overrides)
    if config_check["returncode"] != 0:
        return {"returncode": config_check["returncode"], "stdout": config_check["stdout"],
                "stderr": f"compose configuration rejected: {config_check['stderr']}"}
    if operation == "up":
        helper_pull = _run([docker, "pull", _BASE_IMAGE], timeout=300)
        if helper_pull["returncode"] != 0:
            return {"returncode": helper_pull["returncode"], "stdout": helper_pull["stdout"],
                    "stderr": f"could not pull pinned local demo/probe base image {_BASE_IMAGE}: {helper_pull['stderr']}"}
        real_images, image_error = _real_image_refs(scenario_id)
        if image_error:
            return {"returncode": 2, "stdout": "", "stderr": image_error}
        for image in real_images or []:
            pulled = _run([docker, "pull", image], timeout=900)
            if pulled["returncode"] != 0:
                return {"returncode": pulled["returncode"], "stdout": pulled["stdout"],
                        "stderr": f"could not pull pinned catalogue image {image}: {pulled['stderr']}"}
    command = prefix + [operation] + (extra or [])
    return _run(command, timeout=timeout, env_overrides=env_overrides)


def compose_ps_result(scenario_id: str) -> dict[str, Any]:
    return _compose_command(scenario_id, "ps", ["--all", "--format", "json"], timeout=20)


def exec_in_service(scenario_id: str, service_id: str, command: list[str], timeout: int = 10) -> dict[str, Any]:
    validate_id(service_id)
    if not command or any(not isinstance(arg, str) or "\x00" in arg for arg in command):
        return {"returncode": 2, "stdout": "", "stderr": "invalid internal check command"}
    return _compose_command(scenario_id, "exec", ["-T", service_id, *command], timeout=timeout)


def probe_in_service(scenario_id: str, service_id: str, python_script: str, timeout: int = 10) -> dict[str, Any]:
    """Run a network probe inside the source container's network namespace.

    The source image may be nginx/httpd/PostgreSQL and need not contain Python or a
    network utility. A short-lived, non-root pinned Python helper shares only that
    service's network namespace and is removed immediately after the probe.
    """
    scenario_id = validate_id(scenario_id)
    validate_id(service_id)
    if not isinstance(python_script, str) or not python_script or "\x00" in python_script:
        return {"returncode": 2, "stdout": "", "stderr": "invalid internal network probe"}
    docker, error = _docker_context_preflight()
    if error or not docker:
        return {"returncode": 127, "stdout": "", "stderr": error or "docker executable is not installed"}
    _, error = _compose_prefix(scenario_id, docker)
    if error:
        return {"returncode": 2, "stdout": "", "stderr": error}
    source_container = f"{project_name(scenario_id)}-{service_id}"
    command = [
        docker, "run", "--rm", "--pull=never", "--network", f"container:{source_container}",
        "--read-only", "--cap-drop=ALL", "--security-opt", "no-new-privileges:true",
        "--user", "65532:65532", "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m",
        _BASE_IMAGE, "python", "-c", python_script,
    ]
    return _run(command, timeout=timeout)


def container_ipv4_addresses(scenario_id: str, service_id: str) -> list[dict[str, str]]:
    """IPv4 addresses of a running container on the networks declared in the plan.

    The generated ``edge`` network is deliberately excluded: it exists only to publish a
    host port, inter-container traffic on it is disabled, and no other host's declared
    path runs through it. Probing an edge address says nothing about plan segmentation.
    Result is sorted by network id so callers get a stable order.
    """
    scenario_id = validate_id(scenario_id)
    validate_id(service_id)
    docker, error = _docker_context_preflight()
    if error or not docker:
        return []
    prefix = project_name(scenario_id) + "-"
    result = _run([docker, "inspect", "-f", "{{json .NetworkSettings.Networks}}", prefix + service_id], timeout=15)
    if result["returncode"] != 0:
        return []
    try:
        networks = json.loads(result["stdout"])
    except json.JSONDecodeError:
        return []
    addresses: list[dict[str, str]] = []
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
    """Return the target's IPv4 on a plan network, for IP-based probing.

    Used by segmentation checks so a blocked path is proven by an actual TCP outcome
    to the target IP, never by a hostname that merely failed to resolve. The address is
    never taken from the publishing-only ``edge`` network. When ``from_service`` is
    given and it shares a plan network with the target, the address on that shared
    network is returned, so a closed port on a reachable host shows up as a refusal
    rather than as "network unreachable".
    """
    addresses = container_ipv4_addresses(scenario_id, service_id)
    if not addresses:
        return None
    if from_service:
        source_networks = {item["network"] for item in container_ipv4_addresses(scenario_id, from_service)}
        for item in addresses:
            if item["network"] in source_networks:
                return item["ip"]
    return addresses[0]["ip"]


def _parse_compose_ps(output: str) -> list[dict[str, Any]]:
    if not output.strip():
        return []
    try:
        decoded = json.loads(output)
        rows = decoded if isinstance(decoded, list) else [decoded]
    except json.JSONDecodeError:
        rows = []
        for line in output.splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    containers = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        containers.append({
            "service": row.get("Service") or row.get("Name", ""),
            "name": row.get("Name", ""),
            "id": row.get("ID", ""),
            "state": row.get("State", "unknown").lower(),
            "status": row.get("Status", ""),
            "health": row.get("Health", "").lower(),
            "exit_code": row.get("ExitCode"),
            "ports": [{"host_ip": pub.get("URL"), "host_port": pub.get("PublishedPort"),
                       "container_port": pub.get("TargetPort"), "protocol": pub.get("Protocol")}
                      for pub in (row.get("Publishers") or []) if pub.get("PublishedPort")],
        })
    return containers


def live_containers(scenario_id: str) -> dict[str, Any]:
    result = compose_ps_result(scenario_id)
    containers = _parse_compose_ps(result["stdout"]) if result["returncode"] == 0 else []
    states = [c["state"] for c in containers]
    if result["returncode"] != 0:
        state = "error"
    elif not containers:
        state = "not_created"
    elif all(s == "running" for s in states):
        state = "running"
    elif any(s == "running" for s in states):
        state = "partial"
    else:
        state = "stopped"
    return {"scenario_id": validate_id(scenario_id), "project_name": project_name(scenario_id),
            "state": state, "containers": containers, "error": result["stderr"] or None}


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
               "expose": expose, "password_set": password is not None, "attempts": attempts,
               "published_ports": published, "host_isolation": isolation, **live}
    if diagnostics is not None:
        details["diagnostics"] = diagnostics
    if cleanup is not None:
        details["cleanup"] = cleanup
    audit = record(scenario_id, "up", "running" if success else "failed", details)
    response = {**live, "ok": success, "command_result": result, "deployment_record": audit,
                "expose": expose, "lan_host": resolved_host, "attempts": attempts,
                "published_ports": published, "isolation_preflight": preflight}
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


def vulnerable_hosts(scenario_id: str) -> list[str]:
    """Host ids that the generated report marks as deliberately vulnerable images."""
    try:
        components = get_generated(scenario_id)["report"].get("components", [])
    except (FileNotFoundError, PlanError):
        return []
    return [component["host_id"] for component in components if component.get("vulnerable")]


def isolation_preflight(scenario_id: str) -> dict[str, Any]:
    """Before deploying: can this Docker engine isolate lab networks from the host?

    Gateway mode ``isolated`` (no host-side bridge address) exists from Docker Engine 28.
    Older engines would silently create ordinary internal networks whose containers can
    reach every service the host binds on all interfaces, so vulnerable images are refused.
    """
    docker, error = _docker_context_preflight()
    vulnerable = vulnerable_hosts(scenario_id)
    result: dict[str, Any] = {"ok": True, "vulnerable_hosts": vulnerable, "docker_version": None}
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
        if vulnerable:
            result.update(ok=False, reason="refusing to deploy deliberately vulnerable images "
                          f"({', '.join(vulnerable)}): {result['risk']}. Upgrade Docker Engine to 28 or later.")
    return result


def host_isolation_report(scenario_id: str) -> dict[str, Any]:
    """After deploying: verify on the real host that no plan network bridge has a host address."""
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


def _cleanup_failed_up(scenario_id: str) -> dict[str, Any]:
    down = _compose_command(scenario_id, "down", ["-v", "--remove-orphans"], timeout=180)
    remaining = live_containers(scenario_id)
    return {"exit_code": down["returncode"], "stderr": down["stderr"][-1000:],
            "remaining_containers": [c.get("name") for c in remaining.get("containers", [])],
            "clean": down["returncode"] == 0 and not remaining.get("containers")}


def do_status(scenario_id: str) -> dict[str, Any]:
    # Read-only poll: must NOT write an audit record (GUI polls this often).
    return live_containers(scenario_id)


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
    result = _compose_command(scenario_id, "down", ["-v", "--remove-orphans"], timeout=180)
    state = "stopped" if result["returncode"] == 0 else "failed"
    details = {"exit_code": result["returncode"], "stdout": result["stdout"], "stderr": result["stderr"]}
    audit = record(scenario_id, "down", state, details)
    return {"scenario_id": validate_id(scenario_id), "project_name": project_name(scenario_id),
            "state": state, "ok": result["returncode"] == 0, "command_result": result,
            "deployment_record": audit}

