"""Fail-closed ownership and isolation check for PoC targets."""
from __future__ import annotations

import json
import re
import shutil
from typing import Any

from app.deploy import manager
from app.iac.generator import PlanError, get_generated, validate_id

PROTECTED_VMIDS = {"501", "2001", "2002", "3001", "3002", "3003", "3004", "80000", "80001"}
_SERVICE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")


class TargetBlocked(RuntimeError):
    """The target is not proven to belong to this isolated scenario deployment."""


def _docker_json(args: list[str]) -> Any:
    docker, error = manager._docker_context_preflight()
    if error or not docker:
        raise TargetBlocked(error or "local Docker is unavailable")
    result = manager._run([docker, *args], timeout=15)
    if result.get("returncode") != 0:
        raise TargetBlocked("Docker ownership inspection failed")
    try:
        return json.loads(result.get("stdout", ""))
    except (TypeError, json.JSONDecodeError) as exc:
        raise TargetBlocked("Docker returned invalid ownership metadata") from exc


def assert_target_owned(scenario_id: str, target: str | dict[str, Any]) -> dict[str, Any]:
    """Return verified target metadata or raise before payload construction/execution.

    ``target`` is normally a service id. An optional ``vmid`` is explicitly rejected
    for now; the PVE runtime is not wired for PoC execution.
    """
    try:
        scenario_id = validate_id(scenario_id)
    except (PlanError, TypeError) as exc:
        raise TargetBlocked("invalid scenario id") from exc
    data = target if isinstance(target, dict) else {"service_ref": target}
    vmid = str(data.get("vmid", ""))
    if vmid:
        if vmid in PROTECTED_VMIDS:
            raise TargetBlocked("protected VMID is never an allowed PoC target")
        raise TargetBlocked("Proxmox VM targets are not wired for PoC execution")
    service = data.get("service_ref") or data.get("service_id") or data.get("target_host_ref")
    if not isinstance(service, str) or not _SERVICE_ID.fullmatch(service):
        raise TargetBlocked("target does not resolve to a valid deployed service")
    if service in PROTECTED_VMIDS:
        raise TargetBlocked("protected asset is never an allowed PoC target")

    try:
        generated = get_generated(scenario_id)
        project = manager.project_name(scenario_id)
        up_records = [row for row in manager.records(scenario_id, limit=500) if row.get("action") == "up"]
    except Exception as exc:
        raise TargetBlocked("scenario deployment record or generated plan is unavailable") from exc
    if not up_records or up_records[0].get("state") != "running":
        raise TargetBlocked("latest deployment record does not prove a running owned deployment")
    record = up_records[0]
    details = record.get("details") or {}
    if details.get("backend") != "local-docker":
        raise TargetBlocked("PoC runner currently supports only local Docker deployments")
    isolation = details.get("host_isolation")
    if not isinstance(isolation, dict) or isolation.get("isolated") is not True:
        raise TargetBlocked("deployment record does not prove host isolation")

    try:
        document = __import__("yaml").safe_load(generated["compose"])
        services = document.get("services", {})
        service_doc = services.get(service)
        if not isinstance(service_doc, dict):
            raise TargetBlocked("service is absent from this scenario's generated deployment")
        expected_name = f"cr-demo-{scenario_id}-{service}"
        if service_doc.get("container_name") != expected_name:
            raise TargetBlocked("generated service container name does not match scenario ownership")
        container = _docker_json(["inspect", expected_name])
        if not isinstance(container, list) or len(container) != 1:
            raise TargetBlocked("owned target container is not uniquely inspectable")
        info = container[0]
        labels = (info.get("Config") or {}).get("Labels") or {}
        if labels.get("com.docker.compose.project") != project or labels.get("com.docker.compose.service") != service:
            raise TargetBlocked("container labels do not match this scenario deployment")
        state = info.get("State") or {}
        if not state.get("Running"):
            raise TargetBlocked("owned target container is not running")
        networks = (info.get("NetworkSettings") or {}).get("Networks") or {}
        declared = set(service_doc.get("networks") or [])
        if not networks or not declared:
            raise TargetBlocked("target has no declared lab network")
        verified_networks: list[str] = []
        for network_name, network_state in networks.items():
            if network_name == f"{project}-edge" or network_name not in {f"{project}-{n}" for n in declared}:
                continue
            network = _docker_json(["network", "inspect", network_name])
            if not isinstance(network, list) or len(network) != 1:
                continue
            net = network[0]
            options = (net.get("Options") or {})
            if (net.get("Internal") is True and
                    options.get("com.docker.network.bridge.gateway_mode_ipv4") == "isolated" and
                    info.get("Id") in (net.get("Containers") or {})):
                verified_networks.append(network_name)
        if not verified_networks:
            raise TargetBlocked("target is not attached to a verified isolated internal network")
    except TargetBlocked:
        raise
    except Exception as exc:
        raise TargetBlocked("target ownership or network isolation could not be verified") from exc
    return {"scenario_id": scenario_id, "service_ref": service, "container_name": expected_name,
            "container_id": info.get("Id"), "networks": verified_networks, "deployment_record_id": record.get("id")}
