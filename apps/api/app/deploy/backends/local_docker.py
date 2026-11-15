"""Local Docker Compose command backend (local Unix socket only)."""
from __future__ import annotations

import ipaddress
import json
import os
import secrets
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Any

import yaml

from app.iac.generator import PlanError, generated_dir, get_generated, validate_id
from app.iac.generator import _PUBLISHED_PORT_MAX, _PUBLISHED_PORT_MIN
from app.planner.catalogue import load_components

_BASE_IMAGE = "python@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704"
_PROJECT_ONLY_OPERATIONS = {"ps", "down"}

def project_name(scenario_id: str) -> str:
    return f"cr-demo-{validate_id(scenario_id)}"

def vulnerable_hosts(scenario_id: str) -> list[str]:
    """Host ids whose generated plan uses deliberately vulnerable images."""
    try:
        components = get_generated(scenario_id)["report"].get("components", [])
    except (FileNotFoundError, PlanError):
        return []
    return [component["host_id"] for component in components if component.get("vulnerable")]


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
    blocked = vulnerable_hosts(scenario_id) if operation not in _PROJECT_ONLY_OPERATIONS else []
    if blocked:
        return {"returncode": 2, "stdout": "", "stderr":
                "local Docker refuses deployment and checks for deliberately vulnerable images: " + ", ".join(blocked)}
    docker, error = _docker_context_preflight()
    if error:
        return {"returncode": 127, "stdout": "", "stderr": error}
    assert docker
    if operation in _PROJECT_ONLY_OPERATIONS:
        # Looking at or removing a deployment must not depend on the generated file: it
        # may never have existed, or the plan may have changed since. Compose finds the
        # project's containers and networks by label.
        return _run([docker, "compose", "-p", project_name(scenario_id), operation] + (extra or []), timeout=timeout)
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
    blocked = vulnerable_hosts(scenario_id)
    if blocked:
        return {"returncode": 2, "stdout": "", "stderr":
                "local Docker checks are disabled for deliberately vulnerable images: " + ", ".join(blocked)}
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
    blocked = vulnerable_hosts(scenario_id)
    if blocked:
        return {"returncode": 2, "stdout": "", "stderr":
                "local Docker probes are disabled for deliberately vulnerable images: " + ", ".join(blocked)}
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
