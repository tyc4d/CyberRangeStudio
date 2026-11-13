"""Minimum context requirements used to calculate missing IR fields."""
from __future__ import annotations

from typing import Any


# Keep this checklist small and explicit. A missing value stays unknown until a
# source or user supplies it; this module never guesses a real-world detail.
MINIMUM_REQUIRED_FIELDS = (
    ("target host identity", "host", "Identify the affected host or its role."),
    ("target host operating system", "host", "The target operating system is needed to choose a faithful environment."),
    ("target host OS version", "version", "The OS version can affect behavior and deployment fidelity."),
    ("target network placement", "network", "Network placement is needed to model reachability."),
    ("target service name", "software", "At least one affected service or application must be identified."),
    ("target service version", "version", "The exact service version is needed for a reproducible setup."),
    ("attacker access precondition", "precondition", "The initial access condition is needed to understand the scenario start."),
)


def calculate_missing_items(ir: dict[str, Any]) -> list[dict[str, Any]]:
    """Return open items for checklist fields not supported by current IR data."""
    hosts = ir.get("hosts") or []
    services = ir.get("services") or []
    actions = ir.get("actions") or []
    has_host_identity = any(
        (host.get("role") not in {None, "", "target", "unidentified target"} and _supported(host))
        or (_verified_value(host, "name") or _verified_value(host, "hostname"))
        for host in hosts
    )
    has_host_os = any(_verified_value(host, "os") for host in hosts)
    has_host_os_version = any(_verified_value(host, "os_version") for host in hosts)
    has_network = any(_verified_value(host, "network_placement") or _verified_value(host, "network") for host in hosts)
    has_service_name = any(_verified_value(service, "name") and service.get("epistemic_status") != "absent" for service in services)
    has_service_version = any(_verified_value(service, "version") for service in services)
    has_precondition = any(_verified_value(action, "precondition") or _verified_value(action, "initial_access") for action in actions)

    present = (
        has_host_identity, has_host_os, has_host_os_version, has_network,
        has_service_name, has_service_version, has_precondition,
    )
    items: list[dict[str, Any]] = []
    for index, ((field, category, reason), exists) in enumerate(zip(MINIMUM_REQUIRED_FIELDS, present), start=1):
        if exists:
            continue
        items.append({
            "id": f"missing-{index}",
            "field": field,
            "category": category,
            "reason": reason,
            "severity": "major" if index in {1, 2, 5, 7} else "minor",
            "status": "open",
        })
    return items


def _known(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value.strip().lower() not in {"unknown", "unspecified", "absent", "n/a"}


def _supported(item: dict[str, Any]) -> bool:
    return item.get("epistemic_status") == "supported" or item.get("source") == "user"


def _verified_value(item: dict[str, Any], field: str) -> bool:
    return _known(item.get(field)) and _supported(item)

