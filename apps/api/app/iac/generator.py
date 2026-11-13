"""Safe Docker Compose generation for local CyberRange proof-of-concepts."""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import yaml
from cr_contracts import iter_errors

from app import config, store

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
_PORT_MIN = 1
_PORT_MAX = 65535
_PUBLISHED_PORT_MIN = 42000
_PUBLISHED_PORT_MAX = 42999
_DEMO_IMAGE = "python@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704"


class PlanError(ValueError):
    def __init__(self, errors: list[str], report: dict[str, Any] | None = None):
        super().__init__("; ".join(errors))
        self.errors = errors
        self.report = report or {"deployable": False, "components": [], "errors": errors}


def validate_id(scenario_id: str) -> str:
    if not _ID_RE.fullmatch(scenario_id):
        raise PlanError(["scenario id must contain only lowercase letters, digits, underscores, or hyphens (max 48 chars)"])
    return scenario_id


def generated_dir(scenario_id: str, create: bool = False) -> Path:
    scenario_id = validate_id(scenario_id)
    root = config.REPO_ROOT / "infra" / "generated"
    if root.exists() and root.is_symlink():
        raise PlanError(["generated output directory must not be a symlink"])
    if create:
        root.mkdir(parents=True, exist_ok=True)
    output = root / scenario_id
    if output.exists() and output.is_symlink():
        raise PlanError(["scenario output directory must not be a symlink"])
    if create:
        output.mkdir(parents=True, exist_ok=True)
    if output.resolve() != (root.resolve() / scenario_id):
        raise PlanError(["generated output path escapes the repository"])
    return output


def _resolved_component(host: dict[str, Any]) -> tuple[str | None, str | None, bool]:
    """Resolve a plan host to a harmless local component.

    By design the range never deploys the real-world software (nginx, postgres, ...).
    A host that exposes a listening service becomes a harmless HTTP stand-in (demo-api)
    on that port; a host with no service becomes a sleeping client/toolbox (demo-client).
    The catalogue component (what it STANDS FOR) travels on the service as is_substitute,
    and module 8 records the difference in the fidelity report. `substitute=True` here
    marks that this image is a benign stand-in, not the real software.
    """
    hint = (host.get("image_hint") or host.get("role") or "").strip().lower()
    if hint in {"demo-client", "cr-demo-client", "python", "python-worker"}:
        return "demo-client", _DEMO_IMAGE, False
    if hint in {"demo-api", "cr-demo-api", "harmless-http-demo"}:
        return "demo-api", None, True
    if host.get("services"):
        return "demo-api", None, True
    return "demo-client", _DEMO_IMAGE, True


def inspect_plan(plan: Any, scenario_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate the contract and security-sensitive semantics without writing files."""
    scenario_id = validate_id(scenario_id)
    errors = list(iter_errors("environment-plan", plan)) if isinstance(plan, dict) else ["environment_plan must be an object"]
    components: list[dict[str, Any]] = []
    mappings: list[dict[str, Any]] = []
    if errors:
        report = {"scenario_id": scenario_id, "deployable": False, "components": components, "errors": errors}
        return {}, report

    hosts = plan.get("hosts", [])
    networks = plan.get("networks", [])
    host_ids: set[str] = set()
    network_ids: set[str] = set()
    for network in networks:
        network_id = network.get("id", "")
        if not _ID_RE.fullmatch(network_id):
            errors.append(f"invalid network id: {network_id!r}")
        if network_id in network_ids:
            errors.append(f"duplicate network id: {network_id}")
        network_ids.add(network_id)
    if not networks:
        errors.append("at least one internal network is required")

    next_published_port = _PUBLISHED_PORT_MIN
    supported_by_host: dict[str, str | None] = {}
    for host in hosts:
        host_id = host.get("id", "")
        if not _ID_RE.fullmatch(host_id):
            errors.append(f"invalid host id: {host_id!r}")
        if host_id in host_ids:
            errors.append(f"duplicate host id: {host_id}")
        host_ids.add(host_id)
        component, image, substitute = _resolved_component(host)
        supported_by_host[host_id] = component
        host_report: dict[str, Any] = {
            "host_id": host_id,
            "image_hint": host.get("image_hint"),
            "component": component or "unsupported",
            "deployable": component is not None,
            "image": image or (f"cr-demo-{scenario_id}-{host_id}:local" if component == "demo-api" else None),
            "substitute": substitute,
        }
        if component is None:
            host_report["reason"] = "image_hint is not in the safe local component allowlist"
        else:
            host_report["reason"] = "mapped to a fixed-version local demo component"
        components.append(host_report)

        host_networks = host.get("networks", [])
        if not host_networks:
            errors.append(f"host {host_id} must join at least one declared network")
        for network_id in host_networks:
            if network_id not in network_ids:
                errors.append(f"host {host_id} references unknown network {network_id}")

        services = host.get("services", [])
        if component == "demo-api" and len(services) > 1:
            errors.append(f"demo-api host {host_id} can expose only one service port")
        for service in services:
            port = service.get("port")
            if not isinstance(port, int) or isinstance(port, bool) or not _PORT_MIN <= port <= _PORT_MAX:
                errors.append(f"host {host_id} has invalid service port {port!r}")
                continue
            if service.get("protocol", "tcp") != "tcp":
                errors.append(f"host {host_id} declares a UDP service, which the harmless demo component does not implement")
            if component == "demo-api":
                host_port = next_published_port
                if host_port > _PUBLISHED_PORT_MAX:
                    errors.append("plan needs more than 1000 host ports in the allowed 42000-42999 range")
                else:
                    mappings.append({"host_id": host_id, "container_port": port, "host_port": host_port})
                    next_published_port += 1
            elif component == "demo-client":
                errors.append(f"host {host_id} declares a listening service but its safe client image has no server")

    for connection in plan.get("connections", []):
        source, target = connection.get("from_host"), connection.get("to_host")
        if source not in host_ids or target not in host_ids:
            errors.append(f"connection references unknown host: {source!r} -> {target!r}")
            continue
        if not set(next(h for h in hosts if h["id"] == source).get("networks", [])).intersection(
            next(h for h in hosts if h["id"] == target).get("networks", [])
        ):
            errors.append(f"connection {source} -> {target} has no shared internal network")
        port = connection.get("port")
        if port is not None and (not isinstance(port, int) or isinstance(port, bool) or not _PORT_MIN <= port <= _PORT_MAX):
            errors.append(f"connection {source} -> {target} has invalid port {port!r}")
        if connection.get("protocol", "tcp") != "tcp":
            errors.append(f"connection {source} -> {target} uses UDP, which is not supported by the harmless demo components")
        if port is not None and connection.get("protocol", "tcp") == "tcp":
            target_services = next(h for h in hosts if h["id"] == target).get("services", [])
            if not any(s.get("port") == port and s.get("protocol", "tcp") == "tcp" for s in target_services):
                errors.append(f"connection {source} -> {target}:{port} does not match a declared target service")

    for host_report in components:
        if not host_report["deployable"]:
            errors.append(f"host {host_report['host_id']} cannot be resolved to a safe local image")
    if not hosts:
        errors.append("at least one host is required")

    report = {
        "scenario_id": scenario_id,
        "deployable": not errors,
        "components": components,
        "host_port_mappings": mappings,
        "networks": [{"id": n.get("id"), "internal": bool(n.get("internal", True))} for n in networks],
        "errors": errors,
    }
    return {"hosts": hosts, "networks": networks, "components": supported_by_host, "mappings": mappings}, report


def compose_document(plan: dict[str, Any], scenario_id: str) -> str:
    scenario_id = validate_id(scenario_id)
    normalized, report = inspect_plan(plan, scenario_id)
    if not report["deployable"]:
        raise PlanError(report["errors"], report)
    network_names = {n["id"]: f"cr-demo-{scenario_id}-{n['id']}" for n in normalized["networks"]}
    service_doc: dict[str, Any] = {}
    ports_by_host: dict[str, list[dict[str, Any]]] = {}
    for mapping in normalized["mappings"]:
        ports_by_host.setdefault(mapping["host_id"], []).append(mapping)

    for host in normalized["hosts"]:
        host_id = host["id"]
        component = normalized["components"][host_id]
        service: dict[str, Any] = {
            "container_name": f"cr-demo-{scenario_id}-{host_id}",
            "networks": list(dict.fromkeys(host["networks"])),
            "read_only": True,
            "tmpfs": ["/tmp:rw,noexec,nosuid,size=16m"],
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges:true"],
            "restart": "no",
        }
        if component == "demo-api":
            service["image"] = f"cr-demo-{scenario_id}-{host_id}:local"
            service["build"] = {"context": "../../templates/demo-app", "dockerfile": "Dockerfile", "pull": False}
            port = host.get("services", [{}])[0].get("port", 8080)
            service["environment"] = {"PORT": str(port)}
            service["user"] = "10001:10001"
            service["healthcheck"] = {
                "test": ["CMD", "python", "-c", f"import urllib.request; urllib.request.urlopen('http://127.0.0.1:{port}/health', timeout=2).read()"],
                "interval": "5s", "timeout": "3s", "retries": 5, "start_period": "2s",
            }
            service_ports = []
            for mapping in ports_by_host.get(host_id, []):
                service_ports.append({
                    "target": mapping["container_port"], "published": str(mapping["host_port"]),
                    "host_ip": "127.0.0.1", "protocol": "tcp",
                })
            if service_ports:
                service["ports"] = service_ports
                service["expose"] = [str(p["target"]) for p in service_ports]
        else:
            service["image"] = _DEMO_IMAGE
            service["command"] = ["python", "-c", "import time; time.sleep(2147483647)"]
            service["user"] = "65532:65532"
            service["healthcheck"] = {
                "test": ["CMD", "python", "-c", "pass"],
                "interval": "10s", "timeout": "3s", "retries": 3,
            }
        service_doc[host_id] = service

    document = {
        "name": f"cr-demo-{scenario_id}",
        "x-cr-test-approval-required": "POST /api/deploy/{id}/up with {\"test_approved\": true}",
        "services": service_doc,
        "networks": {
            network_id: {"name": network_names[network_id], "internal": True}
            for network_id in sorted(network_names)
        },
    }
    content = "# CR_TEST_APPROVAL_REQUIRED: explicit local PoC approval is required before deployment.\n"
    content += yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
    _assert_compose_safe(content, scenario_id)
    return content


def _assert_compose_safe(content: str, scenario_id: str) -> None:
    try:
        doc = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise PlanError([f"generated YAML is invalid: {exc}"]) from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("services"), dict) or not doc["services"]:
        raise PlanError(["generated compose must contain at least one service"])
    serialized = json.dumps(doc, sort_keys=True).lower()
    forbidden = ("privileged", "password", "passwd", "api_key", "apikey", "secret", "private_key", "token")
    if any(term in serialized for term in forbidden):
        raise PlanError(["generated compose contains a forbidden credential or privilege setting"])
    for service_name, service in doc["services"].items():
        if not service_name.startswith(("demo", "api", "client", "web", "host", "node", "svc", "h")) and not _ID_RE.fullmatch(service_name):
            raise PlanError([f"unsafe service name: {service_name}"])
        if service.get("privileged", False):
            raise PlanError([f"service {service_name} may not run privileged"])
        for port in service.get("ports", []):
            published = int(port["published"])
            if not _PUBLISHED_PORT_MIN <= published <= _PUBLISHED_PORT_MAX or port.get("host_ip") != "127.0.0.1":
                raise PlanError([f"service {service_name} has an unsafe published port"])
    for network in doc.get("networks", {}).values():
        if not network.get("internal") or not network.get("name", "").startswith(f"cr-demo-{scenario_id}-"):
            raise PlanError(["all generated networks must be internal and use the cr-demo- prefix"])


def generate(scenario_id: str) -> dict[str, Any]:
    scenario_id = validate_id(scenario_id)
    ir = store.get(scenario_id)
    if ir is None:
        raise KeyError(scenario_id)
    plan = ir.get("environment_plan")
    _, report = inspect_plan(plan, scenario_id)
    if not report["deployable"]:
        raise PlanError(report["errors"], report)
    content = compose_document(plan, scenario_id)
    output = generated_dir(scenario_id, create=True)
    _atomic_write(output / "docker-compose.yml", content)
    _atomic_write(output / "report.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return {"compose": content, "report": report}


def get_generated(scenario_id: str) -> dict[str, Any]:
    scenario_id = validate_id(scenario_id)
    output = generated_dir(scenario_id)
    compose_path = output / "docker-compose.yml"
    report_path = output / "report.json"
    if not compose_path.is_file() or compose_path.is_symlink() or not report_path.is_file() or report_path.is_symlink():
        raise FileNotFoundError(scenario_id)
    content = compose_path.read_text(encoding="utf-8")
    ir = store.get(scenario_id)
    if ir is None:
        raise FileNotFoundError(scenario_id)
    expected = compose_document(ir.get("environment_plan"), scenario_id)
    if content != expected:
        raise PlanError(["generated compose content differs from the current validated environment plan"])
    _, report = inspect_plan(ir.get("environment_plan"), scenario_id)
    return {"compose": content, "report": report}


def _atomic_write(path: Path, content: str) -> None:
    fd, temporary_name = tempfile.mkstemp(prefix=".cr-demo-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
