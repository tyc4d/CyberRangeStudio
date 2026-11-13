"""Local-only Docker Compose lifecycle and durable deployment audit records."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any

from app import config
from app.iac.generator import PlanError, generated_dir, get_generated, validate_id

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


def _run(args: list[str], timeout: int = 60) -> dict[str, Any]:
    try:
        env = os.environ.copy()
        # Buildx records builder activity under its config directory. The worker
        # sandbox keeps the home directory read-only, so keep that runtime state
        # under the permitted temporary directory instead.
        env["BUILDX_CONFIG"] = "/tmp/cr-demo-buildx"
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=env)
        return {"returncode": result.returncode, "stdout": result.stdout[-12000:], "stderr": result.stderr[-4000:]}
    except subprocess.TimeoutExpired as exc:
        return {"returncode": 124, "stdout": (exc.stdout or "")[-12000:] if isinstance(exc.stdout, str) else "",
                "stderr": f"command timed out after {timeout}s"}
    except OSError as exc:
        return {"returncode": 127, "stdout": "", "stderr": str(exc)}


def _compose_command(scenario_id: str, operation: str, extra: list[str] | None = None,
                     timeout: int = 60) -> dict[str, Any]:
    docker, error = _docker_context_preflight()
    if error:
        return {"returncode": 127, "stdout": "", "stderr": error}
    assert docker
    prefix, error = _compose_prefix(scenario_id, docker)
    if error:
        return {"returncode": 2, "stdout": "", "stderr": error}
    assert prefix
    config_check = _run(prefix + ["config", "--quiet"], timeout=15)
    if config_check["returncode"] != 0:
        return {"returncode": config_check["returncode"], "stdout": config_check["stdout"],
                "stderr": f"compose configuration rejected: {config_check['stderr']}"}
    if operation == "up":
        image_check = _run([docker, "image", "inspect", _BASE_IMAGE], timeout=15)
        if image_check["returncode"] != 0:
            return {"returncode": 125, "stdout": "", "stderr": f"required base image is not cached locally: {_BASE_IMAGE}; network pulls are disabled"}
    command = prefix + [operation] + (extra or [])
    return _run(command, timeout=timeout)


def compose_ps_result(scenario_id: str) -> dict[str, Any]:
    return _compose_command(scenario_id, "ps", ["--all", "--format", "json"], timeout=20)


def exec_in_service(scenario_id: str, service_id: str, command: list[str], timeout: int = 10) -> dict[str, Any]:
    validate_id(service_id)
    if not command or any(not isinstance(arg, str) or "\x00" in arg for arg in command):
        return {"returncode": 2, "stdout": "", "stderr": "invalid internal check command"}
    return _compose_command(scenario_id, "exec", ["-T", service_id, *command], timeout=timeout)


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


def do_up(scenario_id: str) -> dict[str, Any]:
    result = _compose_command(scenario_id, "up", ["-d", "--pull", "never"], timeout=180)
    live = live_containers(scenario_id) if result["returncode"] == 0 else {
        "scenario_id": validate_id(scenario_id), "project_name": project_name(scenario_id),
        "state": "error", "containers": [], "error": result["stderr"],
    }
    success = result["returncode"] == 0 and live["state"] == "running"
    details = {"exit_code": result["returncode"], "stdout": result["stdout"], "stderr": result["stderr"], **live}
    audit = record(scenario_id, "up", "running" if success else "failed", details)
    return {**live, "ok": success, "command_result": result, "deployment_record": audit}


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

