"""Safe Docker Compose generation for local CyberRange proof-of-concepts."""
from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import yaml
from cr_contracts import iter_errors

from app import config, store
from app.planner.catalogue import component_by_id

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
_PORT_MIN = 1
_PORT_MAX = 65535
_PUBLISHED_PORT_MIN = 42000
_PUBLISHED_PORT_MAX = 42999
_DEMO_IMAGE = "python@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704"
_EDGE_NETWORK = "edge"
# Values that are resolved only at deploy time (never written to disk as literals).
_RUNTIME_REF_RE = re.compile(r"^\$\{CR_[A-Z0-9_]+(?::[?-][^${}]*)?\}$")
_HOSTPORT_RE = re.compile(r"^\$\{(CR_HOSTPORT_\d+):-(\d+)\}$")
# Capabilities a catalogue profile may add back after cap_drop: ALL. Nothing that
# grants host, network-admin or raw-socket power is allowed.
_ALLOWED_CAP_ADD = {"NET_BIND_SERVICE", "CHOWN", "SETUID", "SETGID", "DAC_OVERRIDE", "FOWNER"}
_DEFAULT_LIMITS = {"mem_limit": "512m", "cpus": 1.0, "pids_limit": 256}
_DEMO_LIMITS = {"mem_limit": "128m", "cpus": 0.5, "pids_limit": 64}
# The edge bridge exists only so a host port can be published. Containers on it must
# not talk to each other through it and must not get working outbound NAT.
_EDGE_DRIVER_OPTS = {"com.docker.network.bridge.enable_icc": "false",
                     "com.docker.network.bridge.enable_ip_masquerade": "false"}


# Plan networks carry lab traffic only. With gateway mode "isolated" Docker gives the
# host-side bridge no address, so a lab container cannot reach services the host binds
# on all interfaces (sshd, other projects) through the bridge. Requires Docker >= 28.
_INTERNAL_DRIVER_OPTS = {"com.docker.network.bridge.gateway_mode_ipv4": "isolated"}
# The only container allowed on the edge network. It forwards each published host port
# to one fixed lab service, so lab services themselves never sit on a bridge that has
# a route to the host or the outside.
GATEWAY_SERVICE = "cr-gateway"
_GATEWAY_LISTEN_BASE = 20000
_GATEWAY_FORWARDER = (
    "import asyncio,sys\n"
    "async def pipe(r,w):\n"
    " try:\n"
    "  while True:\n"
    "   d=await r.read(65536)\n"
    "   if not d: break\n"
    "   w.write(d); await w.drain()\n"
    " except Exception: pass\n"
    " finally:\n"
    "  try: w.close()\n"
    "  except Exception: pass\n"
    "async def serve(lp,h,p):\n"
    " async def handle(r,w):\n"
    "  try: r2,w2=await asyncio.wait_for(asyncio.open_connection(h,p),5)\n"
    "  except Exception:\n"
    "   w.close(); return\n"
    "  await asyncio.gather(pipe(r,w2),pipe(r2,w))\n"
    " s=await asyncio.start_server(handle,'0.0.0.0',lp)\n"
    " await s.serve_forever()\n"
    "async def main():\n"
    " rules=[a.split('=',1) for a in sys.argv[1:]]\n"
    " await asyncio.gather(*[serve(int(lp),t.rsplit(':',1)[0],int(t.rsplit(':',1)[1])) for lp,t in rules])\n"
    "asyncio.run(main())\n"
)


def hostport_env(index: int) -> str:
    return f"CR_HOSTPORT_{index}"


def _profile(catalogue: dict[str, Any] | None) -> dict[str, Any]:
    return (catalogue or {}).get("container") or {}


def _is_isolated_only(catalogue: dict[str, Any] | None) -> bool:
    return bool(catalogue) and (catalogue.get("exposure") == "isolated_only" or bool(catalogue.get("vulnerable")))


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


def _resolved_component(host: dict[str, Any], scenario_id: str, host_id: str) -> dict[str, Any]:
    """Resolve only curated catalogue IDs to real images; everything else is a demo.

    Explicit ``component_mode`` wins. For older plans, ``oss-*`` catalogue IDs mean
    real and ``demo-*`` IDs mean a harmless stand-in. Arbitrary image strings are never
    passed through to Compose.
    """
    hint = (host.get("image_hint") or "").strip().lower()
    catalogue_entry = component_by_id(hint)
    requested_mode = host.get("component_mode")
    if requested_mode is None:
        requested_mode = "real" if hint.startswith("oss-") else "substitute"

    if requested_mode == "real":
        if not catalogue_entry or not catalogue_entry.get("image") or not catalogue_entry.get("pinned_image") or not catalogue_entry.get("digest"):
            return {"runtime_component": None, "component": "unsupported", "component_mode": "real",
                    "image": None, "version": None, "digest": None, "catalogue": catalogue_entry,
                    "substitute": False}
        return {"runtime_component": "real", "component": catalogue_entry["id"], "component_mode": "real",
                "image": catalogue_entry["pinned_image"], "version": catalogue_entry.get("version"),
                "digest": catalogue_entry.get("digest"), "catalogue": catalogue_entry,
                "substitute": False}

    if requested_mode != "substitute":
        return {"runtime_component": None, "component": "unsupported", "component_mode": requested_mode,
                "image": None, "version": None, "digest": None, "catalogue": catalogue_entry,
                "substitute": False}

    # Only explicitly named demo scaffolds may use the benign Python templates.
    # Unknown software/runtime must stay unsupported; silently turning it into
    # demo-api/demo-client would falsely imply a deployable reproduction.
    explicit_demo_hints = {"demo-client", "cr-demo-client", "python", "python-worker",
                           "demo-api", "cr-demo-api", "harmless-http-demo"}
    if hint not in explicit_demo_hints:
        mapped_substitute = bool(catalogue_entry and catalogue_entry.get("runtime") == "container")
        if not mapped_substitute:
            return {"runtime_component": None, "component": "unsupported", "component_mode": "unsupported",
                    "image": None, "version": None, "digest": None, "catalogue": catalogue_entry,
                    "substitute": False}

    if hint in {"demo-client", "cr-demo-client", "python", "python-worker"}:
        runtime_component = "demo-client"
        image = _DEMO_IMAGE
        version = "pinned Python demo client base"
        digest = _DEMO_IMAGE.partition("@")[-1] if "@" in _DEMO_IMAGE else None
        base_image = None
    elif hint in {"demo-api", "cr-demo-api", "harmless-http-demo"} or (catalogue_entry and host.get("services")):
        runtime_component = "demo-api"
        image = f"cr-demo-{scenario_id}-{host_id}:local"
        version = "local demo-app template"
        digest = None
        base_image = _DEMO_IMAGE
    else:
        runtime_component = "demo-client"
        image = _DEMO_IMAGE
        version = "pinned Python demo client base"
        digest = _DEMO_IMAGE.partition("@")[-1] if "@" in _DEMO_IMAGE else None
        base_image = None
    is_explicit_demo_client = hint in {"demo-client", "cr-demo-client", "python", "python-worker"}
    is_substitute = not (runtime_component == "demo-client" and is_explicit_demo_client)
    return {"runtime_component": runtime_component, "component": runtime_component,
            "component_mode": "substitute", "image": image, "version": version,
            "digest": digest, "base_image": base_image, "catalogue": catalogue_entry,
            "substitute": is_substitute}


def inspect_plan(plan: Any, scenario_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate the contract and security-sensitive semantics without writing files."""
    scenario_id = validate_id(scenario_id)
    errors = list(iter_errors("environment-plan", plan)) if isinstance(plan, dict) else ["environment_plan must be an object"]
    components: list[dict[str, Any]] = []
    vm_definitions: list[dict[str, Any]] = []
    mappings: list[dict[str, Any]] = []
    if errors:
        report = {"scenario_id": scenario_id, "deployable": False, "components": components, "errors": errors}
        return {}, report

    hosts = plan.get("hosts", [])
    networks = plan.get("networks", [])
    network_by_id = {n.get("id"): n for n in networks if isinstance(n, dict)}
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
    resolved_by_host: dict[str, dict[str, Any]] = {}
    for host in hosts:
        host_id = host.get("id", "")
        if not _ID_RE.fullmatch(host_id):
            errors.append(f"invalid host id: {host_id!r}")
        if host_id in host_ids:
            errors.append(f"duplicate host id: {host_id}")
        if host_id == GATEWAY_SERVICE:
            errors.append(f"host id {GATEWAY_SERVICE!r} is reserved for the generated publishing gateway")
        host_ids.add(host_id)
        runtime = host.get("runtime")
        catalogue_hint = (host.get("image_hint") or "").strip().lower()
        catalogue_entry = component_by_id(catalogue_hint)
        if runtime == "vm" or (catalogue_entry and catalogue_entry.get("runtime") == "vm"):
            guest = host.get("guest") or {}
            vm_errors = []
            if guest.get("os_family") not in {"windows", "linux", "bsd", "other"}:
                vm_errors.append("guest.os_family must be an explicit supported family")
            for key in ("os_release", "image_ref", "image_digest"):
                if not isinstance(guest.get(key), str) or not guest.get(key).strip():
                    vm_errors.append(f"guest.{key} is required and must be validated")
            for key in ("cpu", "memory_mib", "disk_gib"):
                value = guest.get(key)
                if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                    vm_errors.append(f"guest.{key} must be a positive integer")
            vm_networks = host.get("networks", [])
            if not vm_networks or any(n not in network_ids for n in vm_networks):
                vm_errors.append("VM host must reference declared isolated networks")
            if any(not network_by_id.get(n, {}).get("internal", True) for n in vm_networks):
                vm_errors.append("VM networks must be isolated/internal")
            for svc in host.get("services", []):
                if not isinstance(svc.get("port"), int) or not 1 <= svc["port"] <= 65535 or svc.get("protocol", "tcp") not in {"tcp", "udp"}:
                    vm_errors.append(f"invalid VM service port/protocol: {svc!r}")
            resolved = {"runtime_component": None, "component": catalogue_hint or "vm-guest",
                        "component_mode": "vm", "image": None, "version": guest.get("os_release"),
                        "digest": guest.get("image_digest"), "catalogue": catalogue_entry, "substitute": False}
            vm_definitions.append({
                "host_id": host_id, "runtime": "vm",
                "guest": {"os_family": guest.get("os_family"), "os_release": guest.get("os_release"),
                          "image_ref": guest.get("image_ref"), "image_digest": guest.get("image_digest"),
                          "cpu": guest.get("cpu"), "memory_mib": guest.get("memory_mib"), "disk_gib": guest.get("disk_gib")},
                "networks": [{"id": n, "mode": "isolated"} for n in host.get("networks", [])],
                "services": [{"protocol": s.get("protocol", "tcp"), "port": s.get("port")}
                             for s in host.get("services", [])],
                "deployable": False,
                "reason": "VM backend is not installed/configured; " + ("; ".join(vm_errors) if vm_errors else "guest definition is valid but cannot be deployed here."),
            })
        elif runtime and runtime != "container":
            resolved = {"runtime_component": None, "component": runtime, "component_mode": runtime,
                        "image": None, "version": None, "digest": None, "catalogue": catalogue_entry, "substitute": False}
        else:
            resolved = _resolved_component(host, scenario_id, host_id)
        resolved_by_host[host_id] = resolved
        component = resolved["runtime_component"]
        host_report: dict[str, Any] = {
            "host_id": host_id,
            "image_hint": host.get("image_hint"),
            "component": resolved["component"],
            "component_mode": resolved["component_mode"],
            "runtime": runtime or ("vm" if resolved.get("component_mode") == "vm" else "container"),
            "deployable": component is not None,
            "image": resolved["image"],
            "version": resolved["version"],
            "digest": resolved["digest"],
            "substitute": resolved["substitute"],
        }
        if resolved.get("base_image"):
            host_report["base_image"] = resolved["base_image"]
        if resolved.get("catalogue"):
            host_report["catalogue_component"] = resolved["catalogue"]["id"]
        catalogue_for_host = resolved.get("catalogue") if resolved.get("component_mode") == "real" else None
        on_external_network = any(not network_by_id.get(n, {}).get("internal", True) for n in host.get("networks", []))
        isolated_only = _is_isolated_only(catalogue_for_host)
        publish = component in {"demo-api", "real"} and on_external_network and not isolated_only
        host_report["published"] = False  # set True below once a host port is actually mapped
        if component is not None:
            host_report["exposure"] = ("isolated_only" if isolated_only else
                                       "publishable" if on_external_network else "internal_only")
            host_report["healthcheck"] = bool(_profile(catalogue_for_host).get("healthcheck")) or component != "real"
            host_report["limits"] = {**(_DEMO_LIMITS if component != "real" else _DEFAULT_LIMITS),
                                     **(_profile(catalogue_for_host).get("limits") or {})}
        if catalogue_for_host and catalogue_for_host.get("vulnerable"):
            host_report["vulnerable"] = True
            host_report["cves"] = list(catalogue_for_host.get("cves", []))
            host_report["isolation"] = ("deliberately vulnerable exercise image: joined only to internal networks, "
                                        "never published to a host port")
        if resolved["substitute"]:
            host_report["fidelity_difference"] = (
                "harmless Python demo behavior; does not reproduce the named component or its vulnerabilities"
            )
        if component is None:
            host_report["reason"] = next((item["reason"] for item in vm_definitions if item["host_id"] == host_id),
                                          f"unsupported runtime/component for host {host_id}; no container fallback is permitted")
        elif resolved["component_mode"] == "real":
            host_report["reason"] = "resolved to a catalogue image pinned by version and sha256 digest"
        else:
            host_report["reason"] = "mapped to a harmless local demo component"
        components.append(host_report)

        host_networks = host.get("networks", [])
        if not host_networks:
            errors.append(f"host {host_id} must join at least one declared network")
        for network_id in host_networks:
            if network_id not in network_ids:
                errors.append(f"host {host_id} references unknown network {network_id}")

        services = host.get("services", [])
        if resolved.get("component_mode") == "vm" or (runtime and runtime != "container"):
            # VM/external runtimes are described in the VM manifest and never fed to Compose.
            continue
        if component == "demo-api" and len(services) > 1:
            errors.append(f"demo-api host {host_id} can expose only one service port")
        for service in services:
            port = service.get("port")
            if not isinstance(port, int) or isinstance(port, bool) or not _PORT_MIN <= port <= _PORT_MAX:
                errors.append(f"host {host_id} has invalid service port {port!r}")
                continue
            if service.get("protocol", "tcp") != "tcp":
                errors.append(f"host {host_id} declares a non-TCP service, which is not supported")
            if component == "demo-api" or component == "real":
                if component == "real":
                    catalogue = resolved["catalogue"] or {}
                    supported_ports = {p.get("port") for p in catalogue.get("default_ports", [])
                                       if p.get("protocol", "tcp") == "tcp"}
                    if port not in supported_ports:
                        errors.append(f"host {host_id} declares port {port}, unsupported by {catalogue.get('id')}")
                if not publish:
                    # Reachable only from containers on its declared internal networks.
                    continue
                host_port = next_published_port
                if host_port > _PUBLISHED_PORT_MAX:
                    errors.append("plan needs more than 1000 host ports in the allowed 42000-42999 range")
                else:
                    # host_port is only the default; the deploy runtime picks a free port in
                    # the same range and passes it through the named environment variable.
                    mappings.append({"host_id": host_id, "container_port": port, "host_port": host_port,
                                     "env": hostport_env(len(mappings)), "via": GATEWAY_SERVICE})
                    next_published_port += 1
                    host_report["published"] = True
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
            errors.append(f"connection {source} -> {target} uses a non-TCP protocol, which is not supported")
        if port is not None and connection.get("protocol", "tcp") == "tcp":
            target_services = next(h for h in hosts if h["id"] == target).get("services", [])
            if not any(s.get("port") == port and s.get("protocol", "tcp") == "tcp" for s in target_services):
                errors.append(f"connection {source} -> {target}:{port} does not match a declared target service")

    for host_report in components:
        if not host_report["deployable"]:
            errors.append(f"host {host_report['host_id']} cannot be resolved to a safe local image")
    if _EDGE_NETWORK in network_ids:
        errors.append(f"network id {_EDGE_NETWORK!r} is reserved for the generated publishing network")

    # Service wiring: a component that only works with a backing service (e.g. a web
    # application and its database) must have a declared connection to one.
    wiring: dict[str, dict[str, Any]] = {}
    for host in hosts:
        resolved = resolved_by_host.get(host.get("id", ""), {})
        catalogue = resolved.get("catalogue") if resolved.get("component_mode") == "real" else None
        for rule in (catalogue or {}).get("wiring", []):
            wanted = set(rule.get("software", []))
            match = None
            for connection in plan.get("connections", []):
                if connection.get("from_host") != host.get("id"):
                    continue
                target = resolved_by_host.get(connection.get("to_host"), {})
                target_catalogue = target.get("catalogue") if target.get("component_mode") == "real" else None
                if target_catalogue and target_catalogue.get("software") in wanted and connection.get("port"):
                    match = {"host": connection["to_host"], "port": connection["port"],
                             "software": target_catalogue["software"]}
                    break
            if match:
                environment = {key: str(value).replace("{host}", match["host"]).replace("{port}", str(match["port"]))
                               for key, value in rule.get("environment", {}).items()}
                wiring.setdefault(host["id"], {"environment": {}, "targets": []})
                wiring[host["id"]]["environment"].update(environment)
                wiring[host["id"]]["targets"].append(match)
            elif rule.get("required", False):
                errors.append(f"host {host.get('id')} ({catalogue.get('id')}) needs a declared connection to a "
                              f"{'/'.join(sorted(wanted))} host; without it the service cannot work")
    for host_report in components:
        if host_report["host_id"] in wiring:
            host_report["wired_to"] = wiring[host_report["host_id"]]["targets"]
    if not hosts:
        errors.append("at least one host is required")

    for vm in vm_definitions:
        errors.append(f"host {vm['host_id']} runtime=vm is not supported by the configured deployment backend: {vm['reason']}")
    report = {
        "scenario_id": scenario_id,
        "deployable": not errors,
        "components": components,
        "vms": vm_definitions,
        "host_port_mappings": mappings,
        "host_port_assignment": "host_port is a default; the deploy runtime assigns a free port in 42000-42999",
        "publishing": (f"published ports terminate on the generated {GATEWAY_SERVICE} forwarder; lab services "
                       "are attached to internal networks only" if mappings else "nothing is published on the host"),
        "host_isolation": "plan networks use Docker gateway mode 'isolated' (no host-side bridge address); needs Docker >= 28",
        "networks": [
            {"id": n.get("id"), "name": f"cr-demo-{scenario_id}-{n.get('id')}",
             "internal": True, "plan_internal": bool(n.get("internal", True))}
            for n in networks
        ],
        "errors": errors,
    }
    return {"hosts": hosts, "networks": networks, "components": resolved_by_host, "mappings": mappings,
            "wiring": wiring}, report


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
        resolved = normalized["components"][host_id]
        component = resolved["runtime_component"]
        service: dict[str, Any] = {
            "container_name": f"cr-demo-{scenario_id}-{host_id}",
            "networks": list(dict.fromkeys(host["networks"])),
            "read_only": True,
            "tmpfs": ["/tmp:rw,noexec,nosuid,size=16m"],
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges:true"],
            "restart": "no",
        }
        if component == "real":
            catalogue = resolved["catalogue"]
            profile = _profile(catalogue)
            service["image"] = resolved["image"]
            service["tmpfs"] = list(service["tmpfs"]) + list(profile.get("tmpfs", []))
            if profile.get("read_only") is False:
                # Some upstream images cannot run on a read-only root filesystem. This is
                # recorded in the catalogue and surfaced in report.json, never silent.
                service["read_only"] = False
            for key in ("user", "command", "entrypoint", "working_dir"):
                if profile.get(key) is not None:
                    service[key] = copy.deepcopy(profile[key])
            if profile.get("cap_add"):
                service["cap_add"] = list(profile["cap_add"])
            environment = {**profile.get("environment", {}),
                           **normalized.get("wiring", {}).get(host_id, {}).get("environment", {})}
            if environment:
                service["environment"] = environment
            if profile.get("healthcheck"):
                service["healthcheck"] = copy.deepcopy(profile["healthcheck"])
            limits = {**_DEFAULT_LIMITS, **(profile.get("limits") or {})}
        elif component == "demo-api":
            service["image"] = f"cr-demo-{scenario_id}-{host_id}:local"
            service["build"] = {"context": "../../templates/demo-app", "dockerfile": "Dockerfile", "pull": False}
            port = host.get("services", [{}])[0].get("port", 8080)
            service["environment"] = {"PORT": str(port)}
            limits = dict(_DEMO_LIMITS)
            service["user"] = "10001:10001"
            service["healthcheck"] = {
                "test": ["CMD", "python", "-c", f"import urllib.request; urllib.request.urlopen('http://127.0.0.1:{port}/health', timeout=2).read()"],
                "interval": "5s", "timeout": "3s", "retries": 5, "start_period": "2s",
            }
        elif component == "demo-client":
            service["image"] = _DEMO_IMAGE
            service["command"] = ["python", "-c", "import time; time.sleep(2147483647)"]
            limits = dict(_DEMO_LIMITS)
            service["user"] = "65532:65532"
            service["healthcheck"] = {
                "test": ["CMD", "python", "-c", "pass"],
                "interval": "10s", "timeout": "3s", "retries": 3,
            }
        else:
            raise PlanError([f"host {host_id} could not be resolved to a supported component"])

        service.update(limits)
        service_doc[host_id] = service

    # Start order and readiness follow the declared connections: a host that uses another
    # host's service waits for it (healthy when it has a healthcheck). Edges that would
    # close a cycle are skipped so Compose never rejects the file.
    depends: dict[str, dict[str, Any]] = {host_id: {} for host_id in service_doc}

    def _reaches(start: str, goal: str) -> bool:
        stack, seen = [start], set()
        while stack:
            current = stack.pop()
            if current == goal:
                return True
            if current in seen:
                continue
            seen.add(current)
            stack.extend(depends.get(current, {}))
        return False

    for connection in plan.get("connections", []):
        source, target = connection.get("from_host"), connection.get("to_host")
        if source not in service_doc or target not in service_doc or source == target:
            continue
        if _reaches(target, source):
            continue
        condition = "service_healthy" if service_doc[target].get("healthcheck") else "service_started"
        depends[source][target] = {"condition": condition}
    for host_id, wanted in depends.items():
        if wanted:
            service_doc[host_id]["depends_on"] = wanted

    document = {
        "name": f"cr-demo-{scenario_id}",
        "x-cr-test-approval-required": "POST /api/deploy/{id}/up with {\"test_approved\": true}",
        "services": service_doc,
        "networks": {
            network_id: {"name": network_names[network_id], "internal": True,
                         "driver_opts": dict(_INTERNAL_DRIVER_OPTS)}
            for network_id in sorted(network_names)
        },
    }
    if normalized["mappings"]:
        hosts_by_id = {host["id"]: host for host in normalized["hosts"]}
        gateway_networks = [_EDGE_NETWORK]
        rules, gateway_ports = [], []
        for index, mapping in enumerate(normalized["mappings"]):
            listen = _GATEWAY_LISTEN_BASE + index
            rules.append(f"{listen}={mapping['host_id']}:{mapping['container_port']}")
            gateway_ports.append({"target": listen, "published": "${%s:-%d}" % (mapping["env"], mapping["host_port"]),
                                  "host_ip": "${CR_BIND_IP:-127.0.0.1}", "protocol": "tcp"})
            target_network = hosts_by_id[mapping["host_id"]]["networks"][0]
            if target_network not in gateway_networks:
                gateway_networks.append(target_network)
        service_doc[GATEWAY_SERVICE] = {
            "container_name": f"cr-demo-{scenario_id}-{GATEWAY_SERVICE}",
            "image": _DEMO_IMAGE,
            "command": ["python", "-c", _GATEWAY_FORWARDER, *rules],
            "networks": gateway_networks,
            "ports": gateway_ports,
            "read_only": True,
            "tmpfs": ["/tmp:rw,noexec,nosuid,size=16m"],
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges:true"],
            "restart": "no",
            "user": "65532:65532",
            "healthcheck": {"test": ["CMD", "python", "-c",
                                     f"import socket; socket.create_connection(('127.0.0.1',{_GATEWAY_LISTEN_BASE}),2).close()"],
                            "interval": "5s", "timeout": "3s", "retries": 6},
            **_DEMO_LIMITS,
        }
        document["networks"][_EDGE_NETWORK] = {
            "name": f"cr-demo-{scenario_id}-edge", "internal": False,
            "driver_opts": dict(_EDGE_DRIVER_OPTS),
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
    # Deploy-time references (e.g. ${CR_DB_PASSWORD:?...}) are not literals; everything
    # else is scanned so no credential or privilege setting can be written to disk.
    scrubbed = copy.deepcopy(doc)
    for service in scrubbed["services"].values():
        environment = service.get("environment")
        if isinstance(environment, dict):
            service["environment"] = {key: value for key, value in environment.items()
                                      if not (isinstance(value, str) and _RUNTIME_REF_RE.fullmatch(value))}
    serialized = json.dumps(scrubbed, sort_keys=True).lower()
    forbidden = ("privileged", "password", "passwd", "api_key", "apikey", "secret", "private_key", "token")
    if any(term in serialized for term in forbidden):
        raise PlanError(["generated compose contains a forbidden credential or privilege setting"])
    for service_name, service in doc["services"].items():
        if not _ID_RE.fullmatch(service_name):
            raise PlanError([f"unsafe service name: {service_name}"])
        if service.get("privileged", False):
            raise PlanError([f"service {service_name} may not run privileged"])
        if "ALL" not in service.get("cap_drop", []):
            raise PlanError([f"service {service_name} must drop all Linux capabilities"])
        if not set(service.get("cap_add", [])) <= _ALLOWED_CAP_ADD:
            raise PlanError([f"service {service_name} adds a capability outside the allowed set"])
        if "no-new-privileges:true" not in service.get("security_opt", []):
            raise PlanError([f"service {service_name} must set no-new-privileges"])
        for forbidden_key in ("volumes", "devices", "network_mode", "pid", "ipc", "extra_hosts", "cap_add_all"):
            if forbidden_key in service:
                raise PlanError([f"service {service_name} may not set {forbidden_key}"])
        for limit in ("mem_limit", "cpus", "pids_limit"):
            if not service.get(limit):
                raise PlanError([f"service {service_name} must declare {limit}"])
        image = service.get("image", "")
        local_build = image == f"cr-demo-{scenario_id}-{service_name}:local" and isinstance(service.get("build"), dict)
        if not local_build and not re.search(r"@sha256:[0-9a-f]{64}$", image):
            raise PlanError([f"service {service_name} must use an image pinned by digest"])
        for port in service.get("ports", []):
            published = _HOSTPORT_RE.fullmatch(str(port.get("published", "")))
            if (not published or not _PUBLISHED_PORT_MIN <= int(published.group(2)) <= _PUBLISHED_PORT_MAX
                    or port.get("host_ip") != "${CR_BIND_IP:-127.0.0.1}"):
                raise PlanError([f"service {service_name} has an unsafe published port"])
        on_edge = _EDGE_NETWORK in service.get("networks", [])
        if (service.get("ports") or on_edge) and service_name != GATEWAY_SERVICE:
            raise PlanError([f"service {service_name} may not publish ports or join the edge network; "
                             f"only {GATEWAY_SERVICE} may"])
        if service_name == GATEWAY_SERVICE and (not on_edge or not service.get("ports")
                                                or service.get("image") != _DEMO_IMAGE):
            raise PlanError([f"{GATEWAY_SERVICE} must be the pinned forwarder on the edge network"])
    for network_id, network in doc.get("networks", {}).items():
        name = network.get("name", "")
        if not name.startswith(f"cr-demo-{scenario_id}-"):
            raise PlanError(["generated networks must use the cr-demo- prefix"])
        if network_id == _EDGE_NETWORK:
            if network.get("internal") is not False or network.get("driver_opts") != _EDGE_DRIVER_OPTS:
                raise PlanError(["the edge network must disable inter-container traffic and outbound NAT"])
        elif network.get("internal") is not True or network.get("driver_opts") != _INTERNAL_DRIVER_OPTS:
            raise PlanError(["plan networks must be internal with an isolated (address-less) host gateway"])


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
