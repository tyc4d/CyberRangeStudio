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
from app.planner.catalogue import load_components

_BASE_IMAGE = "python@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704"


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


def _compose_command(scenario_id: str, operation: str, extra: list[str] | None = None,
                     timeout: int = 60, *, expose: str = "internal", lan_host: str | None = None,
                     pg_password: str | None = None) -> dict[str, Any]:
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
    env_overrides = {"CR_BIND_IP": bind_ip, "CR_PG_AUTH_METHOD": "trust",
                     "CR_PG_PASSWORD": pg_password or secrets.token_urlsafe(24)}
    if expose == "lan":
        bind_ip = lan_host or detect_lan_ipv4()
        env_overrides.update({"CR_BIND_IP": bind_ip, "CR_PG_AUTH_METHOD": "scram-sha-256",
                              "CR_PG_PASSWORD": pg_password or secrets.token_urlsafe(24)})
    config_check = _run(prefix + ["config", "--quiet"], timeout=15, env_overrides=env_overrides)
    if config_check["returncode"] != 0:
        return {"returncode": config_check["returncode"], "stdout": config_check["stdout"],
                "stderr": f"compose configuration rejected: {config_check['stderr']}"}
    if operation == "up":
        helper_pull = _run([docker, "pull", _BASE_IMAGE], timeout=180)
        if helper_pull["returncode"] != 0:
            return {"returncode": helper_pull["returncode"], "stdout": helper_pull["stdout"],
                    "stderr": f"could not pull pinned local demo/probe base image {_BASE_IMAGE}: {helper_pull['stderr']}"}
        real_images, image_error = _real_image_refs(scenario_id)
        if image_error:
            return {"returncode": 2, "stdout": "", "stderr": image_error}
        for image in real_images or []:
            pulled = _run([docker, "pull", image], timeout=180)
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
    result = _compose_command(scenario_id, "up", ["-d", "--pull", "never"], timeout=180,
                              expose=expose, lan_host=resolved_host, pg_password=password)
    if password:
        result = {**result,
                  "stdout": result.get("stdout", "").replace(password, "[REDACTED]"),
                  "stderr": result.get("stderr", "").replace(password, "[REDACTED]")}
    live = live_containers(scenario_id) if result["returncode"] == 0 else {
        "scenario_id": validate_id(scenario_id), "project_name": project_name(scenario_id),
        "state": "error", "containers": [], "error": result["stderr"],
    }
    success = result["returncode"] == 0 and live["state"] == "running"
    details = {"exit_code": result["returncode"], "stdout": result["stdout"], "stderr": result["stderr"],
               "expose": expose, "password_set": password is not None, **live}
    audit = record(scenario_id, "up", "running" if success else "failed", details)
    response = {**live, "ok": success, "command_result": result, "deployment_record": audit,
                "expose": expose, "lan_host": resolved_host}
    if password is not None:
        response["db_password"] = password
    return response


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
    result = _compose_command(scenario_id, "down", ["-v"], timeout=120)
    state = "stopped" if result["returncode"] == 0 else "failed"
    details = {"exit_code": result["returncode"], "stdout": result["stdout"], "stderr": result["stderr"]}
    audit = record(scenario_id, "down", state, details)
    return {"scenario_id": validate_id(scenario_id), "project_name": project_name(scenario_id),
            "state": state, "ok": result["returncode"] == 0, "command_result": result,
            "deployment_record": audit}

