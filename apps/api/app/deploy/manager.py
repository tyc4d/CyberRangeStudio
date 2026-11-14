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


def vm_preflight(image: str | Path | None = None, *, authorized: bool = False) -> dict[str, Any]:
    """Check the optional local libvirt/KVM backend without changing the host."""
    required = ("qemu-system-x86_64", "qemu-img", "virsh", "libvirtd")
    paths = {name: shutil.which(name) for name in required}
    missing = [name for name, path in paths.items() if not path]
    if missing:
        return {"ok": False, "backend": "libvirt-qemu", "category": "tools_unavailable",
                "message": "VM 工具未安裝", "missing_tools": missing, "tools": paths,
                "kvm": Path("/dev/kvm").exists(), "image": str(image) if image else None}
    kvm = Path("/dev/kvm")
    if not kvm.exists() or not os.access(kvm, os.R_OK | os.W_OK):
        return {"ok": False, "backend": "libvirt-qemu", "category": "hardware_or_permission",
                "message": "KVM 硬體或權限不足", "missing_tools": [], "tools": paths,
                "kvm": kvm.exists(), "image": str(image) if image else None}
    if not image or not Path(image).is_file():
        return {"ok": False, "backend": "libvirt-qemu", "category": "image_missing",
                "message": "VM 映像缺失", "missing_tools": [], "tools": paths,
                "kvm": True, "image": str(image) if image else None}
    if not authorized:
        return {"ok": False, "backend": "libvirt-qemu", "category": "authorization_or_configuration",
                "message": "授權或設定尚未完成：需明確確認映像授權", "missing_tools": [], "tools": paths,
                "kvm": True, "image": str(image)}
    # A readable image alone does not establish libvirt authorization.
    return {"ok": False, "backend": "libvirt-qemu", "category": "authorization_or_configuration",
            "message": "授權或 libvirt 設定尚未確認", "missing_tools": [], "tools": paths,
            "kvm": True, "image": str(image), "requires_explicit_authorized_image": True}


def _vm_run(args: list[str], timeout: int = 30) -> dict[str, Any]:
    return _run(args, timeout=timeout)


def _vm_preflight_pass(image: str | Path | None, *, authorized: bool = False) -> dict[str, Any]:
    result = vm_preflight(image, authorized=authorized)
    if result["category"] == "authorization_or_configuration" and authorized:
        # Confirm local system libvirt is actually reachable. Never infer authorization
        # from installed binaries or silently elevate privileges.
        virsh = shutil.which("virsh")
        probe = _vm_run([virsh, "-c", VM_URI, "uri"], timeout=5) if virsh else {"returncode": 127}
        if probe["returncode"] == 0:
            result.update(ok=True, category="ready", message="VM backend 可用")
        else:
            result.update(category="authorization_or_configuration", message="授權或 libvirt 設定尚未完成",
                          detail=probe.get("stderr", "libvirt 不可達")[:500])
    return result


def _vm_identity(scenario_id: str, vm_id: str) -> str:
    return f"cr-{validate_id(scenario_id)}-{validate_id(vm_id)}"


def _vm_inspect(scenario_id: str, vm_id: str) -> dict[str, Any]:
    name = _vm_identity(scenario_id, vm_id)
    virsh = shutil.which("virsh")
    if not virsh:
        return {"state": "unavailable", "error": "virsh executable is not installed"}
    result = _vm_run([virsh, "-c", VM_URI, "domstate", name], timeout=10)
    if result["returncode"]:
        return {"state": "absent", "name": name}
    if not _vm_owned(scenario_id, vm_id):
        return {"state": "unverified", "name": name, "error": "VM ownership metadata is absent"}
    state = result["stdout"].strip().lower()
    return {"state": "running" if state == "running" else "stopped", "name": name}


def vm_status(scenario_id: str, vm_id: str) -> dict[str, Any]:
    """Read-only VM status, including ownership verification."""
    scenario_id = validate_id(scenario_id)
    result = _vm_inspect(scenario_id, vm_id)
    return {"scenario_id": scenario_id, "vm_id": validate_id(vm_id), **result}


def vm_create(scenario_id: str, vm_id: str, image: str | Path, *, authorized: bool = False, vcpus: int = 2,
              memory_mib: int = 2048, disk_gib: int = 30, timeout: int = 60,
              cancel_event: Any = None) -> dict[str, Any]:
    """Create a bounded, owned VM from an explicitly supplied local image."""
    scenario_id, vm_id = validate_id(scenario_id), validate_id(vm_id)
    if not (1 <= vcpus <= VM_LIMITS["vcpus"] and 512 <= memory_mib <= VM_LIMITS["memory_mib"]
            and 8 <= disk_gib <= VM_LIMITS["disk_gib"]):
        raise PlanError(["VM resources exceed configured limits"])
    preflight = _vm_preflight_pass(image, authorized=authorized)
    if not preflight["ok"]:
        record(scenario_id, "vm_create", "preflight_failed", {k: v for k, v in preflight.items() if k != "detail"})
        return {"ok": False, "state": "preflight_failed", "preflight": preflight}
    virsh = shutil.which("virsh")
    name = _vm_identity(scenario_id, vm_id)
    existing = vm_status(scenario_id, vm_id)
    if existing["state"] != "absent":
        return {"ok": False, "state": existing["state"], "error": "refusing to replace an existing or unverified VM"}
    list_result = _vm_run([virsh, "-c", VM_URI, "list", "--all", "--name"], timeout=10)
    owned_count = 0
    for candidate in list_result.get("stdout", "").splitlines():
        if not candidate.startswith("cr-"):
            continue
        metadata = _vm_run([virsh, "-c", VM_URI, "dumpxml", candidate], timeout=10)
        if metadata["returncode"] == 0 and (f"owner='{VM_OWNER}'" in metadata["stdout"]
                                            or f'owner="{VM_OWNER}"' in metadata["stdout"]):
            owned_count += 1
    if owned_count >= VM_LIMITS["count"]:
        return {"ok": False, "state": "resource_limit", "error": "VM count limit reached"}
    image_path = Path(image).resolve()
    # Create an owned qcow2 overlay so the supplied source image remains untouched.
    # The guest NIC has no host port forwards; management ports stay guest-only.
    vm_dir = config.DATA_DIR / "vms" / scenario_id
    vm_dir.mkdir(parents=True, exist_ok=True)
    disk_path = vm_dir / f"{vm_id}.qcow2"
    disk_result = _vm_run([shutil.which("qemu-img") or "qemu-img", "create", "-f", "qcow2", "-F", "qcow2",
                           "-b", str(image_path), str(disk_path), f"{disk_gib}G"], timeout=timeout)
    if disk_result["returncode"]:
        return {"ok": False, "state": "failed", "error": disk_result["stderr"],
                "preflight": preflight}
    xml = (f"<domain type='kvm' xmlns:cr='https://cyberrange.local/libvirt/1.0'><name>{name}</name>"
           f"<metadata><cr:ownership owner='{VM_OWNER}' scenario='{scenario_id}' vmid='{vm_id}'/>"
           f"</metadata><memory unit='MiB'>{memory_mib}</memory>"
           f"<vcpu>{vcpus}</vcpu><os><type arch='x86_64'>hvm</type></os><devices>"
           f"<disk type='file' device='disk'><driver name='qemu' type='qcow2'/><source file='{disk_path}'/>"
           f"<target dev='vda' bus='virtio'/></disk><interface type='network'><source network='default'/>"
           "<model type='virtio'/></interface><graphics type='none'/></devices></domain>")
    if cancel_event is not None and cancel_event.is_set():
        return {"ok": False, "state": "cancelled", "preflight": preflight}
    import tempfile
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".xml", encoding="utf-8") as domain_file:
            domain_file.write(xml)
            domain_file.flush()
            result = _vm_run([virsh, "-c", VM_URI, "define", domain_file.name], timeout=timeout)
        if result["returncode"]:
            outcome = {"ok": False, "state": "failed", "error": result["stderr"]}
            disk_path.unlink(missing_ok=True)
        else:
            outcome = {"ok": True, "state": "defined", "name": name, "preflight": preflight}
    except (OSError, subprocess.TimeoutExpired) as exc:
        outcome = {"ok": False, "state": "failed", "error": str(exc)}
        # Cleanup only after verifying the exact product owner/scenario metadata.
        current = _vm_inspect(scenario_id, vm_id)
        if current.get("state") in {"running", "stopped"}:
            vm_destroy(scenario_id, vm_id, timeout=timeout)
        else:
            disk_path.unlink(missing_ok=True)
    audit = record(scenario_id, "vm_create", outcome["state"],
                   {"vm_id": vm_id, "owner": VM_OWNER, "backend": "libvirt-qemu", "resources":
                    {"vcpus": vcpus, "memory_mib": memory_mib, "disk_gib": disk_gib},
                    "image": str(image_path), "disk": str(disk_path), "result": outcome})
    outcome["deployment_record"] = audit
    return outcome


def _vm_owned(scenario_id: str, vm_id: str) -> bool:
    """Verify exact domain metadata before any destructive operation."""
    name = _vm_identity(scenario_id, vm_id)
    virsh = shutil.which("virsh")
    if not virsh:
        return False
    result = _vm_run([virsh, "-c", VM_URI, "dumpxml", name], timeout=10)
    xml = result.get("stdout", "")
    return (result["returncode"] == 0 and f"<name>{name}</name>" in xml
            and (f"owner='{VM_OWNER}'" in xml or f'owner="{VM_OWNER}"' in xml)
            and (f"scenario='{scenario_id}'" in xml or f'scenario="{scenario_id}"' in xml)
            and (f"vmid='{validate_id(vm_id)}'" in xml or f'vmid="{validate_id(vm_id)}"' in xml))


def vm_boot(scenario_id: str, vm_id: str, *, timeout: int = 120, cancel_event: Any = None,
            authorized: bool = False) -> dict[str, Any]:
    scenario_id, vm_id = validate_id(scenario_id), validate_id(vm_id)
    virsh = shutil.which("virsh")
    preflight = _vm_preflight_pass("/nonexistent/validated-image-sentinel", authorized=authorized)
    # An existing defined domain carries its image, so only runtime/tool/authorization
    # checks apply here. Keep KVM and libvirt checks explicit.
    if preflight["category"] not in {"image_missing", "authorization_or_configuration"}:
        if not preflight["ok"]:
            return {"ok": False, "state": "preflight_failed", "preflight": preflight}
    if preflight["category"] in {"image_missing", "authorization_or_configuration"}:
        tools_ready = all(shutil.which(tool) for tool in ("qemu-system-x86_64", "qemu-img", "virsh", "libvirtd"))
        if not tools_ready or not Path("/dev/kvm").exists() or not os.access("/dev/kvm", os.R_OK | os.W_OK):
            return {"ok": False, "state": "preflight_failed", "preflight": vm_preflight()}
        if not authorized:
            return {"ok": False, "state": "preflight_failed", "preflight": vm_preflight(authorized=False)}
        probe = _vm_run([virsh, "-c", VM_URI, "uri"], timeout=5) if virsh else {"returncode": 127}
        if probe["returncode"]:
            return {"ok": False, "state": "preflight_failed", "preflight": {"ok": False,
                    "category": "authorization_or_configuration", "message": "授權或 libvirt 設定尚未完成"}}
    if not _vm_owned(scenario_id, vm_id):
        return {"ok": False, "state": "unverified", "error": "VM ownership could not be verified"}
    if cancel_event is not None and cancel_event.is_set():
        return {"ok": False, "state": "cancelled"}
    result = _vm_run([virsh, "-c", VM_URI, "start", _vm_identity(scenario_id, vm_id)], timeout=timeout)
    state = "booting" if result["returncode"] == 0 else "failed"
    if result["returncode"] and _vm_owned(scenario_id, vm_id):
        cleanup = vm_destroy(scenario_id, vm_id, timeout=min(timeout, 30))
    else:
        cleanup = None
    audit = record(scenario_id, "vm_boot", state, {"vm_id": vm_id, "backend": "libvirt-qemu",
                                                     "exit_code": result["returncode"],
                                                     "stderr": result["stderr"], "cleanup": cleanup})
    return {"ok": result["returncode"] == 0, "state": state, "vm_id": vm_id,
            "command_result": result, "deployment_record": audit}


def vm_readiness(scenario_id: str, vm_id: str, *, timeout: int = 60, cancel_event: Any = None,
                 guest_command: list[str] | None = None) -> dict[str, Any]:
    """Poll hypervisor state only; guest readiness requires an explicit safe agent command."""
    scenario_id, vm_id = validate_id(scenario_id), validate_id(vm_id)
    deadline = time.monotonic() + max(1, timeout)
    virsh = shutil.which("virsh")
    if not virsh or not _vm_owned(scenario_id, vm_id):
        return {"ready": False, "state": "unverified", "guest_ready": False}
    while time.monotonic() < deadline:
        if cancel_event is not None and cancel_event.is_set():
            return {"ready": False, "state": "cancelled", "guest_ready": False}
        state = _vm_inspect(scenario_id, vm_id).get("state")
        if state != "running":
            return {"ready": False, "state": state, "guest_ready": False}
        # Never count hypervisor running alone as Windows ready.
        if guest_command:
            if any(token.lower() in {"cmdkey", "password", "passwd", "secret"} for token in guest_command):
                return {"ready": False, "state": "unsafe_probe_rejected", "guest_ready": False}
            result = _vm_run([virsh, "-c", VM_URI, "qemu-agent-command", _vm_identity(scenario_id, vm_id),
                              json.dumps({"execute": "guest-ping"})], timeout=5)
            if result["returncode"] == 0:
                return {"ready": True, "state": "running", "guest_ready": True,
                        "probe": "libvirt qemu guest-ping"}
        else:
            return {"ready": False, "state": "running", "guest_ready": False,
                    "reason": "guest readiness probe is not configured"}
        time.sleep(min(1, max(0, deadline - time.monotonic())))
    return {"ready": False, "state": "timeout", "guest_ready": False}


def vm_stop(scenario_id: str, vm_id: str, *, timeout: int = 30) -> dict[str, Any]:
    scenario_id, vm_id = validate_id(scenario_id), validate_id(vm_id)
    virsh = shutil.which("virsh")
    if not virsh or not _vm_owned(scenario_id, vm_id):
        return {"ok": False, "state": "unverified", "error": "VM ownership could not be verified"}
    result = _vm_run([virsh, "-c", VM_URI, "shutdown", _vm_identity(scenario_id, vm_id)], timeout=timeout)
    state = "stopping" if result["returncode"] == 0 else "failed"
    audit = record(scenario_id, "vm_stop", state, {"vm_id": vm_id, "exit_code": result["returncode"],
                                                     "stderr": result["stderr"]})
    return {"ok": result["returncode"] == 0, "state": state, "command_result": result,
            "deployment_record": audit}


def vm_destroy(scenario_id: str, vm_id: str, *, timeout: int = 30) -> dict[str, Any]:
    scenario_id, vm_id = validate_id(scenario_id), validate_id(vm_id)
    virsh = shutil.which("virsh")
    if not virsh or not _vm_owned(scenario_id, vm_id):
        return {"ok": False, "state": "unverified", "error": "VM ownership could not be verified"}
    name = _vm_identity(scenario_id, vm_id)
    state = _vm_inspect(scenario_id, vm_id).get("state")
    stop = None
    if state == "running":
        stop = _vm_run([virsh, "-c", VM_URI, "destroy", name], timeout=timeout)
        if stop["returncode"]:
            return {"ok": False, "state": "failed", "error": stop["stderr"]}
    result = _vm_run([virsh, "-c", VM_URI, "undefine", name], timeout=timeout)
    final_state = "destroyed" if result["returncode"] == 0 else "failed"
    removed_storage = False
    if result["returncode"] == 0:
        disk = config.DATA_DIR / "vms" / scenario_id / f"{vm_id}.qcow2"
        try:
            if disk.resolve().parent == (config.DATA_DIR / "vms" / scenario_id).resolve():
                disk.unlink(missing_ok=True)
                removed_storage = True
        except OSError:
            removed_storage = False
    audit = record(scenario_id, "vm_destroy", final_state, {"vm_id": vm_id, "verified_owner": VM_OWNER,
                                                              "exit_code": result["returncode"],
                                                              "stderr": result["stderr"],
                                                              "removed_storage": removed_storage})
    return {"ok": result["returncode"] == 0, "state": final_state,
            "deployment_record": audit}


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
    if not success:
        live = {**live, "state": "error", "error": result["stderr"] or live.get("error")}
    details = {"exit_code": result["returncode"], "stdout": result["stdout"], "stderr": result["stderr"],
               "expose": expose, "password_set": password is not None, "attempts": attempts, **live}
    if diagnostics is not None:
        details["diagnostics"] = diagnostics
    if cleanup is not None:
        details["cleanup"] = cleanup
    audit = record(scenario_id, "up", "running" if success else "failed", details)
    response = {**live, "ok": success, "command_result": result, "deployment_record": audit,
                "expose": expose, "lan_host": resolved_host, "attempts": attempts}
    if diagnostics is not None:
        response["diagnostics"] = diagnostics
    if cleanup is not None:
        response["cleanup"] = cleanup
    if password is not None:
        response["db_password"] = password
    return response


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

