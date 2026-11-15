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

    # A deployable image makes the environment buildable. It makes an action reproducible only
    # when the action is about that software: using it, or exploiting a weakness it carries.
    from app.planner.catalogue import component_by_id
    lowered = text.casefold()

    def concerns(service: dict[str, Any], component: dict[str, Any]) -> bool:
        labels = [str(service.get("name") or ""), str(service.get("matched_text") or ""), *component.get("aliases", [])]
        if any(label and re.search(rf"(?<![a-z0-9]){re.escape(label.casefold())}(?![a-z0-9])", lowered) for label in labels):
            return True
        cves = [*component.get("cves", []), *service.get("cve", [])]
        return any(str(cve).casefold() in lowered for cve in cves)

    disabled = [s for s in services if s.get("lab_enabled") is False and concerns(s, component_by_id(s.get("catalogue_component")) or {})]
    if disabled:
        return "not_reproducible", f"{disabled[0].get('name')} is not enabled in the lab by the user's choice; this step is not reproduced."

    buildable: list[str] = []
    for service in services:
        component_id = service.get("catalogue_component")
        component = component_by_id(component_id)
        if not component or service.get("placement") == "conflict" or service.get("lab_enabled") is False:
            continue
        if not concerns(service, component):
            if component.get("runtime") == "container":
                buildable.append(str(component.get("name", component_id)))
            continue
        if service.get("is_substitute"):
            return "substitute_only", f"Uses {component.get('name', component_id)} as a substitute; only limited service/protocol behavior is represented."
        if component.get("runtime") == "container" and (service.get("version") or component.get("digest")):
            basis = service.get("version_basis")
            caveat = (" The deployed release is assumed, not stated by the source." if basis == "assumed" else
                      " The deployed release differs from the one the source states." if basis == "substituted" else
                      " The deployed release was chosen by the user." if basis == "user_supplied" else "")
            return "reproducible", (f"Pinned catalogue component {component_id} provides the software this step acts on, "
                                    f"so a step-specific check can be run against it; this does not mean the step was executed.{caveat}")
    if buildable:
        return "not_reproducible", (f"The environment can be built ({', '.join(dict.fromkeys(buildable))}), but this step is not about that "
                                    "software and has no step-specific reproduction or validation; it remains untested.")
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
