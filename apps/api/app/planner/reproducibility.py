"""Conservative per-action fidelity classification for scenario planning."""
from __future__ import annotations

import re
from typing import Any

_WINDOWS = re.compile(r"\b(windows|iis|internet information services|active directory|\bad\b|gpo|group policy|winrm|registry)\b", re.I)
_AD = re.compile(r"\b(active directory|\bad ds\b|domain controller|kerberos|gpo|group policy|domain join)\b", re.I)
_HORIZON = re.compile(r"\b(vmware horizon|horizon (?:connection|agent|desktop|pool))\b", re.I)
_LOG4J = re.compile(r"\b(log4j|log4shell|cve-2021-44228)\b", re.I)
_VERSION = re.compile(r"\b(?:windows server|windows|log4j|horizon)\s*(?:version\s*)?([0-9]+(?:\.[0-9A-Za-z_-]+){0,3})\b", re.I)

def _all_text(action: dict[str, Any]) -> str:
    return " ".join(str(action.get(key, "")) for key in ("name", "description", "attack_technique", "attack_tactic"))

def classify_action(action: dict[str, Any], ir: dict[str, Any]) -> tuple[str, str]:
    """Return (reproducibility, reason) without claiming an attack was executed."""
    text = _all_text(action)
    versions = _VERSION.findall(text)
    hosts = {str(h.get("id")): h for h in ir.get("hosts", []) if isinstance(h, dict)}
    target = hosts.get(str(action.get("target_host_ref")), {})
    context = " ".join(str(target.get(k, "")) for k in ("os", "os_version", "name", "role"))
    services = [s for s in ir.get("services", []) if isinstance(s, dict)
                and (not action.get("target_host_ref") or s.get("host_ref") == action.get("target_host_ref"))]
    service_text = " ".join(" ".join(str(s.get(k, "")) for k in ("name", "version", "catalogue_component")) for s in services)
    combined = " ".join((text, context, service_text))

    if _HORIZON.search(combined):
        return "not_reproducible", "Catalogue has no Horizon/vSphere backend; ordinary VMs cannot substitute. Supply Horizon/vSphere versions, licensed test platform and connector details."
    if _AD.search(combined):
        if not re.search(r"\b(?:20\d\d|201[2-9]|202[0-9])\b", combined):
            return "needs_vm", "Requires an isolated, versioned Windows AD DC/member fixture; OS/AD versions and topology are missing. No version is assumed."
        return "needs_vm", "Requires an isolated Windows AD DC/member VM fixture and native health checks; this deployment environment has no VM backend/image configured."
    if _LOG4J.search(combined):
        if not versions or not re.search(r"\b(?:log4j\s*(?:2\.)?\d|2\.[0-9]+\.[0-9]+)\b", combined, re.I):
            return "not_reproducible", "No application fixture or explicit Log4j/JVM version is identified. Supply app, Log4j and JVM versions, configuration, and harmless validation step."
        return "needs_vm", "A pinned isolated vulnerable application fixture and harmless validator are not present in the catalogue/runtime."
    if _WINDOWS.search(combined):
        if not versions and not target.get("os_version"):
            return "needs_vm", "Requires Windows VM; Windows release and validated image are missing. Supply the release and lawful image reference; no version is assumed."
        return "needs_vm", "Requires Windows VM and native readiness/behavior checks; the local VM runtime and validated guest image are not configured."

    # Catalogue service matches are exact only when version and runtime/image are pinned.
    for service in services:
        component_id = service.get("catalogue_component")
        from app.planner.catalogue import component_by_id
        component = component_by_id(component_id)
        if not component:
            continue
        if service.get("is_substitute"):
            return "substitute_only", f"Uses {component.get('name', component_id)} as a substitute; only limited service/protocol behavior is represented."
        if component.get("runtime") == "container" and (service.get("version") or component.get("digest")):
            return "reproducible", f"Pinned catalogue component {component_id} is available for this service-level check; this does not mean the attack action is executed."
    if services:
        return "not_reproducible", "No pinned catalogue component and safe step-specific validation mapping is available. Supply the exact component/version and expected harmless evidence."
    return "not_reproducible", "Catalogue has no exact component/version and safe validation mapping for this action; provide the target software, version, and expected evidence."

def annotate_reproducibility(ir: dict[str, Any]) -> dict[str, Any]:
    actions = ir.get("actions", [])
    order = {"reproducible": 0, "substitute_only": 1, "needs_vm": 2, "not_reproducible": 3}
    for action in actions:
        status, reason = classify_action(action, ir)
        action["reproducibility"] = status
        action["reproducibility_reason"] = reason
    required = [action.get("reproducibility") for action in actions if action.get("required", True)]
    ir["fidelity"] = max(required, key=lambda value: order.get(value, 3)) if required else "not_reproducible"
    return ir
