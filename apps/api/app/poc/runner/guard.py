"""Fail-closed ownership and isolation check for PoC targets."""
from __future__ import annotations

import json
import re
from typing import Any

import yaml

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


def _pve_docker_json(scenario_id: str, args: list[str]) -> Any:
    result = manager._pve_guest_exec(scenario_id, ["/usr/bin/docker", *args], 15,
                                     require_isolation=True)
    if result.get("returncode") != 0:
        raise TargetBlocked("Proxmox container ownership inspection failed")
    try:
        return json.loads(result.get("stdout", ""))
    except (TypeError, json.JSONDecodeError) as exc:
        raise TargetBlocked("Proxmox returned invalid container metadata") from exc


def _owned_container(service: str, service_doc: dict, project: str, expected_name: str,
                     inspect: Any) -> dict[str, Any]:
    container = inspect(["inspect", expected_name])
    if not isinstance(container, list) or len(container) != 1:
        raise TargetBlocked("owned target container is not uniquely inspectable")
    info = container[0]
    labels = (info.get("Config") or {}).get("Labels") or {}
    if labels.get("com.docker.compose.project") != project or labels.get("com.docker.compose.service") != service:
        raise TargetBlocked("container labels do not match this scenario deployment")
    if not (info.get("State") or {}).get("Running"):
        raise TargetBlocked("owned target container is not running")
    networks = (info.get("NetworkSettings") or {}).get("Networks") or {}
    declared = set(service_doc.get("networks") or [])
    if not networks or not declared:
        raise TargetBlocked("target has no declared lab network")
    approved = {f"{project}-{name}" for name in declared if name != "edge"}
    for name in networks:
        if name not in approved:
            raise TargetBlocked("target is attached to an additional non-lab network")
        network = inspect(["network", "inspect", name])
        if not isinstance(network, list) or len(network) != 1:
            raise TargetBlocked("attached lab network is not uniquely inspectable")
        net = network[0]
        options = net.get("Options") or {}
        if not (net.get("Internal") is True
                and options.get("com.docker.network.bridge.gateway_mode_ipv4") == "isolated"
                and info.get("Id") in (net.get("Containers") or {})):
            raise TargetBlocked("an attached network lacks verified internal isolation")
    return {"container_id": info.get("Id"), "networks": list(networks)}


def assert_target_owned(scenario_id: str, target: str | dict[str, Any]) -> dict[str, Any]:
    """Return verified target metadata or raise before payload construction/execution.

    ``target`` is normally a generated Compose service id. An optional ``vmid``
    must match the active owned PVE worker; protected assets are always refused.
    """
    try:
        scenario_id = validate_id(scenario_id)
    except (PlanError, TypeError) as exc:
        raise TargetBlocked("invalid scenario id") from exc
    data = target if isinstance(target, dict) else {"service_ref": target}
    vmid = str(data.get("vmid", ""))
    if vmid in PROTECTED_VMIDS:
        raise TargetBlocked("protected VMID is never an allowed PoC target")
    service = data.get("service_ref") or data.get("service_id") or data.get("target_host_ref")
    if not isinstance(service, str) or not _SERVICE_ID.fullmatch(service):
        raise TargetBlocked("target does not resolve to a valid deployed service")
    if service in PROTECTED_VMIDS:
        raise TargetBlocked("protected asset is never an allowed PoC target")

    try:
        generated = get_generated(scenario_id)
        document = yaml.safe_load(generated["compose"])
        services = document.get("services", {})
        service_doc = services.get(service)
        if not isinstance(service_doc, dict):
            raise TargetBlocked("service is absent from this scenario's generated deployment")
        expected_name = f"cr-demo-{scenario_id}-{service}"
        if service_doc.get("container_name") != expected_name:
            raise TargetBlocked("generated service container name does not match scenario ownership")
        project = manager.project_name(scenario_id)
        backend = manager.deploy_backend()
        if backend == "proxmox":
            deployment = manager._active_proxmox_deployment(scenario_id)
            if not deployment or deployment.get("orphan"):
                raise TargetBlocked("no active, healthy scenario-owned Proxmox worker deployment")
            vmid = int(deployment.get("vmid", 0))
            if vmid in {int(value) for value in PROTECTED_VMIDS} or not 900100 <= vmid <= 900999:
                raise TargetBlocked("Proxmox worker VMID is protected or outside the owned cr-range")
            if data.get("vmid") is not None and str(data.get("vmid")) != str(vmid):
                raise TargetBlocked("requested VMID does not match this scenario's deployment record")
            details = deployment.get("details") or {}
            isolation = details.get("isolation")
            if not manager._pve_isolation_confirmed(isolation):
                raise TargetBlocked("Proxmox deployment lacks confirmed isolation evidence")
            status = manager.compose_ps_result(scenario_id)
            if status.get("returncode") != 0 or status.get("vm_state") != "running":
                raise TargetBlocked("owned Proxmox worker is not verifiably running")
            containers = manager._parse_compose_ps(status.get("stdout", ""))
            if not any(row.get("name") == expected_name and row.get("state") == "running" for row in containers):
                raise TargetBlocked("target service container is not running in the owned Proxmox worker")
            container = _owned_container(service, service_doc, project, expected_name,
                                         lambda args: _pve_docker_json(scenario_id, args))
            owned = {"scenario_id": scenario_id, "service_ref": service, "container_name": expected_name,
                     "vmid": vmid, "host_id": deployment.get("host_id"), **container}
            if type(deployment.get("id")) is int and deployment["id"] > 0:
                owned["deployment_record_id"] = deployment["id"]
            return owned

        if vmid:
            raise TargetBlocked("VM targets are unsupported by the selected local Docker backend")

        up_records = [row for row in manager.records(scenario_id, limit=500) if row.get("action") == "up"]
        if not up_records or up_records[0].get("state") != "running":
            raise TargetBlocked("latest deployment record does not prove a running owned deployment")
        record = up_records[0]
        details = record.get("details") or {}
        if details.get("backend") != "local-docker":
            raise TargetBlocked("deployment record backend does not match selected runtime")
        isolation = details.get("host_isolation")
        if not isinstance(isolation, dict) or isolation.get("isolated") is not True:
            raise TargetBlocked("deployment record does not prove host isolation")
        container = _owned_container(service, service_doc, project, expected_name, _docker_json)
    except TargetBlocked:
        raise
    except Exception as exc:
        raise TargetBlocked("target ownership or network isolation could not be verified") from exc
    owned = {"scenario_id": scenario_id, "service_ref": service, "container_name": expected_name, **container}
    if type(record.get("id")) is int and record["id"] > 0:
        owned["deployment_record_id"] = record["id"]
    return owned
