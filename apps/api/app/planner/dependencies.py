"""Deterministic, schema-checked dependency inference from Scenario IR."""
from __future__ import annotations

import copy
import json
import re
from typing import Any

from app.planner.catalogue import component_by_id, load_components, match_software

_CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,}\b", re.IGNORECASE)
_VERSION_RE = re.compile(r"^\s*(?:[:/@= ]\s*)?(?:version\s*)?[vV]?(\d+(?:\.\d+){1,3}(?:[-+][A-Za-z0-9.]+)?)\b", re.IGNORECASE)
_UNSUPPORTED_NAMES = [
    "Microsoft SQL Server", "SQL Server", "Oracle Database", "Microsoft Exchange Server",
    "Exchange Server", "Apache Tomcat", "Tomcat", "MySQL", "MariaDB", "Redis", "OpenSSH",
]
_SOFTWARE_KEYS = {"service", "services", "software", "products", "applications", "dependencies", "components"}
_ROLE_STOPWORDS = {"attacker", "exposed", "external", "internet", "public", "internal", "dmz",
                   "host", "server", "target", "victim", "machine", "the", "an", "a"}


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug[:36] or "item"


def _host_id(raw: Any) -> str:
    value = str(raw or "target").strip()
    return _slug(value).replace("-", "_")


def _mentions(text: str, phrase: str) -> bool:
    phrase = phrase.strip()
    return bool(phrase and re.search(rf"(?<![a-z0-9]){re.escape(phrase.casefold())}(?![a-z0-9])", text.casefold()))


def _is_attacker_role(role: str) -> bool:
    return (_mentions(role, "attacker") or _mentions(role, "red team") or _mentions(role, "red-team")
            or _mentions(role, "operator"))


def _role_terms(role: str) -> set[str]:
    role_text = role.casefold()
    terms = {keyword.casefold() for component in load_components()
             if component.get("id") != "oss-attacker"
             for keyword in component.get("role_keywords", [])
             if _mentions(role_text, keyword)}
    terms.update(token for token in re.findall(r"[a-z0-9]+", role_text) if token not in _ROLE_STOPWORDS)
    return terms


def _infer_action_host_refs(actions: list[dict[str, Any]], hosts: dict[str, dict[str, Any]]) -> None:
    for action in actions:
        if action.get("target_host_ref"):
            continue
        text = " ".join(str(action.get(key, "")) for key in ("name", "description")).casefold()
        if not text.strip():
            continue
        explicit = [hid for hid in hosts if _mentions(text, hid.replace("_", "-")) or _mentions(text, hid)]
        if len(explicit) == 1:
            selected = explicit[0]
        else:
            matches = [hid for hid, host in hosts.items()
                       if not _is_attacker_role(str(host.get("role", "")))
                       and any(_mentions(text, term) for term in _role_terms(str(host.get("role", ""))))]
            if len(matches) != 1:
                continue
            selected = matches[0]
        action["target_host_ref"] = selected
        action["target_host_ref_source"] = "program"
        action["target_host_ref_epistemic_status"] = "inferred"


def _cves(value: Any) -> list[str]:
    if isinstance(value, list):
        found = [str(item).upper() for item in value if _CVE_RE.fullmatch(str(item))]
    else:
        found = [item.upper() for item in _CVE_RE.findall(str(value or ""))]
    return list(dict.fromkeys(found))


def _candidate(name: str, text: str = "", *, version: Any = None, cves: Any = None,
               host_ref: Any = None, explicit_port: Any = None) -> dict[str, Any]:
    if not version:
        match = _VERSION_RE.search(text[:len(name) + 48])
        version = match.group(1) if match else None
    try:
        port = int(explicit_port) if explicit_port is not None else None
    except (TypeError, ValueError):
        port = None
    return {
        "name": str(name).strip(),
        "version": str(version).strip() if version else None,
        "cve": _cves(cves if cves is not None else text),
        "host_ref": _host_id(host_ref) if host_ref else None,
        "port": port if port and 1 <= port <= 65535 else None,
    }


def _record_candidates(node: Any, host_ref: str | None = None, key: str | None = None):
    if isinstance(node, list):
        for item in node:
            yield from _record_candidates(item, host_ref, key)
        return
    if not isinstance(node, dict):
        if isinstance(node, str) and key in _SOFTWARE_KEYS:
            mentions = list(_candidate_from_mentions(node, host_ref))
            yield from (mentions or [_candidate(node, node, host_ref=host_ref)])
        return

    local_host = host_ref
    is_host_record = key == "hosts" or ("role" in node and any(k in node for k in ("id", "name", "host_ref")))
    if is_host_record:
        local_host = _host_id(node.get("id") or node.get("host_ref") or node.get("name"))

    lowered = {str(k).casefold(): v for k, v in node.items()}
    if not is_host_record and "name" in lowered and (key in _SOFTWARE_KEYS or any(k in lowered for k in ("version", "cve", "port", "software"))):
        name = lowered.get("name") or lowered.get("software")
        if isinstance(name, str) and name.strip():
            yield _candidate(name, json.dumps(node, ensure_ascii=False), version=lowered.get("version"),
                             cves=lowered.get("cve") or lowered.get("cves"),
                             host_ref=lowered.get("host_ref") or lowered.get("host") or local_host,
                             explicit_port=lowered.get("port"))
    for child_key, value in node.items():
        normalized_key = str(child_key).casefold()
        if normalized_key in _SOFTWARE_KEYS:
            yield from _record_candidates(value, local_host, normalized_key)
        elif normalized_key == "hosts":
            yield from _record_candidates(value, local_host, normalized_key)
        elif isinstance(value, (dict, list)):
            yield from _record_candidates(value, local_host, normalized_key)
        elif isinstance(value, str) and normalized_key in {"web_server", "database", "application", "product"}:
            mentions = list(_candidate_from_mentions(value, local_host))
            yield from (mentions or [_candidate(value, value, host_ref=local_host)])


def _context_text_candidates(node: Any, host_ref: str | None = None, key: str | None = None):
    metadata_keys = {"id", "name", "role", "type", "os", "os_version", "version", "cve", "cves",
                     "port", "host_ref", "service_refs", "epistemic_status", "source"}
    if isinstance(node, dict):
        local_host = host_ref
        if "role" in node and any(k in node for k in ("id", "name", "host_ref")):
            local_host = _host_id(node.get("id") or node.get("host_ref") or node.get("name"))
        for child_key, value in node.items():
            normalized_key = str(child_key).casefold()
            if normalized_key in metadata_keys:
                continue
            yield from _context_text_candidates(value, local_host, normalized_key)
    elif isinstance(node, list):
        for value in node:
            yield from _context_text_candidates(value, host_ref, key)
    elif isinstance(node, str):
        yield from _candidate_from_mentions(node, host_ref)


def _candidate_from_mentions(text: str, host_ref: str | None = None):
    aliases: list[str] = []
    for item in load_components():
        aliases.extend(item.get("aliases", []))
        for substitute in item.get("substitutes_for", []):
            aliases.extend(substitute.get("names", []))
    aliases.extend(_UNSUPPORTED_NAMES)
    # Longest-first avoids interpreting "Apache Tomcat" as the Apache HTTP Server.
    occupied: list[tuple[int, int]] = []
    for alias in sorted(set(aliases), key=len, reverse=True):
        for match in re.finditer(rf"(?<![\w]){re.escape(alias)}(?![\w])", text, flags=re.IGNORECASE):
            if any(match.start() < end and start < match.end() for start, end in occupied):
                continue
            if alias.casefold() == "apache" and re.match(r"\s+tomcat\b", text[match.end():], re.IGNORECASE):
                continue
            occupied.append((match.start(), match.end()))
            name = text[match.start():match.end()]
            yield _candidate(name, text[match.end():match.end() + 48], host_ref=host_ref)


def _collect_hosts(target_context: Any, actions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    hosts: dict[str, dict[str, Any]] = {}

    def visit(node: Any, parent_key: str = "") -> None:
        if isinstance(node, list):
            for item in node:
                visit(item, parent_key)
        elif isinstance(node, dict):
            for key, value in node.items():
                if str(key).casefold() == "hosts" and isinstance(value, list):
                    for entry in value:
                        if not isinstance(entry, dict):
                            continue
                        raw_id = entry.get("id") or entry.get("host_ref") or entry.get("name") or f"target-{len(hosts) + 1}"
                        hid = _host_id(raw_id)
                        host = {"id": hid, "role": str(entry.get("role") or entry.get("type") or "target"),
                                "epistemic_status": "inferred", "source": "program"}
                        if entry.get("os"):
                            host["os"] = str(entry["os"])
                        if entry.get("os_version") or entry.get("version"):
                            host["os_version"] = str(entry.get("os_version") or entry.get("version"))
                        hosts[hid] = host
                visit(value, str(key))

    visit(target_context)
    for action in actions:
        ref = action.get("target_host_ref")
        if ref:
            hid = _host_id(ref)
            hosts.setdefault(hid, {"id": hid, "role": "target", "epistemic_status": "inferred", "source": "program"})
    return hosts


def _collect_candidates(ir: dict[str, Any], hosts: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    context = ir.get("target_context", {})
    candidates = list(_record_candidates(context))
    actions = ir.get("actions", [])
    for action in actions:
        text = " ".join(str(action.get(key, "")) for key in ("name", "description"))
        candidates.extend(_candidate_from_mentions(text, action.get("target_host_ref")))

    candidates.extend(_context_text_candidates(context))
    for service in ir.get("services", []):
        if service.get("source") == "user":
            candidates.append(_candidate(service.get("name", ""), service.get("name", ""),
                                         version=service.get("version"), cves=service.get("cve", []),
                                         host_ref=service.get("host_ref"), explicit_port=service.get("port")))

    # Bind an unscoped service to the only known target when the IR has one.
    target_hosts = [hid for hid, host in hosts.items() if "attacker" not in host.get("role", "").casefold()]
    if candidates and not target_hosts:
        hosts.setdefault("target", {"id": "target", "role": "target", "epistemic_status": "inferred", "source": "program"})
        target_hosts = ["target"]
    for candidate in candidates:
        if candidate["host_ref"] and candidate["host_ref"] not in hosts:
            hid = candidate["host_ref"]
            hosts[hid] = {"id": hid, "role": "target", "epistemic_status": "inferred", "source": "program"}
        elif not candidate["host_ref"] and len(target_hosts) == 1:
            candidate["host_ref"] = target_hosts[0]

    unique: list[dict[str, Any]] = []
    for candidate in candidates:
        name = candidate["name"].strip()
        if not name:
            continue
        component, _ = match_software(name)
        normalized_name = component["id"] if component else name.casefold()
        matches = [item for item in unique
                   if (match_software(item["name"])[0] or {}).get("id", item["name"].casefold()) == normalized_name
                   and item.get("host_ref") == candidate.get("host_ref")]
        same_version = next((item for item in matches
                             if (item.get("version") or None) == (candidate.get("version") or None)
                             and (item.get("port") is None or candidate.get("port") is None
                                  or item.get("port") == candidate.get("port"))), None)
        target = same_version
        if target is None and not candidate.get("version"):
            target = next((item for item in matches if item.get("version")), None)
        if target is None and candidate.get("version"):
            unversioned = next((item for item in matches if not item.get("version")), None)
            if unversioned:
                target = unversioned
                target["version"] = candidate["version"]
        if target is None:
            unique.append(candidate)
        else:
            target["cve"] = list(dict.fromkeys([*target.get("cve", []), *candidate.get("cve", [])]))
            target["port"] = target.get("port") or candidate.get("port")
    return unique


def plan_dependencies(ir: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with program-derived hosts/services and explicit unresolved dependencies."""
    result = copy.deepcopy(ir)
    actions = result.get("actions", [])
    hosts = _collect_hosts(result.get("target_context", {}), actions)
    for existing_host in result.get("hosts", []):
        raw_id = existing_host.get("id")
        if not raw_id:
            continue
        hid = _host_id(raw_id)
        if hid not in hosts:
            hosts[hid] = {**copy.deepcopy(existing_host), "id": hid}
        else:
            for key, value in existing_host.items():
                if key != "id":
                    hosts[hid].setdefault(key, copy.deepcopy(value))
    _infer_action_host_refs(actions, hosts)
    candidates = _collect_candidates(result, hosts)

    existing_user_services = [item for item in result.get("services", []) if item.get("source") == "user"]
    services: list[dict[str, Any]] = []
    generated_host_refs: dict[str, list[str]] = {}
    missing = [item for item in result.get("missing_items", []) if not str(item.get("id", "")).startswith("planner_dep_")]
    seen_missing: set[str] = set()

    def add_missing(key: str, field: str, reason: str, *, category: str = "software", status: str = "open",
                    resolution: str | None = None) -> None:
        ident = "planner_dep_" + _slug(key)
        if ident in seen_missing:
            return
        seen_missing.add(ident)
        entry: dict[str, Any] = {
            "id": ident, "field": field, "category": category, "reason": reason,
            "severity": "major", "status": status,
        }
        if resolution:
            entry["resolution"] = resolution
        missing.append(entry)

    used_ids: set[str] = set()
    used_user_ids: set[str] = set()
    for candidate in candidates:
        name = candidate["name"]
        component, is_substitute = match_software(name)
        existing_user = next((item for item in existing_user_services
                              if item.get("name", "").casefold() == name.casefold()
                              and (not item.get("version") or not candidate.get("version")
                                   or item.get("version") == candidate.get("version"))), None)
        if component is None and existing_user:
            component = component_by_id(existing_user.get("catalogue_component"))
            is_substitute = bool(existing_user.get("is_substitute", False))
        if component is None:
            add_missing(f"software-{name}-{candidate.get('version', '')}",
                        f"software dependency: {name}" + (f" {candidate['version']}" if candidate.get("version") else ""),
                        "The dependency was identified in the actions or target context, but no compatible open-source catalogue component is available.")
            continue

        if existing_user:
            service_id = existing_user.get("id")
            if service_id not in used_user_ids:
                service = copy.deepcopy(existing_user)
                service["catalogue_component"] = component["id"]
                service["is_substitute"] = bool(is_substitute)
                service.setdefault("epistemic_status", "inferred")
                service.setdefault("source", "user")
                service["cve"] = list(dict.fromkeys([*service.get("cve", []), *candidate.get("cve", [])]))
                if candidate.get("version"):
                    service["version"] = candidate["version"]
                if candidate.get("port"):
                    service["port"] = candidate["port"]
                services.append(service)
                used_user_ids.add(service_id)
                used_ids.add(service_id)
            else:
                for service in services:
                    if service.get("id") == service_id:
                        service["cve"] = list(dict.fromkeys([*service.get("cve", []), *candidate.get("cve", [])]))
            if is_substitute:
                substitute_info = next((entry for entry in component.get("substitutes_for", [])
                                        if name.casefold() in {n.casefold() for n in entry.get("names", [])}), {})
                explanation = substitute_info.get("reason") or "This component is a functional substitute and does not fully reproduce the original software."
                add_missing(f"substitute-{name}", f"exact software fidelity: {name}", explanation,
                            status="substitute_chosen", resolution=f"Using {component['name']} ({component['id']}) as a substitute. It is not a full recreation of {name}.")
            if not candidate.get("version") and not existing_user.get("version"):
                add_missing(f"version-{name}-{candidate.get('host_ref') or 'unassigned'}",
                            f"version for {name}",
                            "A software dependency was identified, but its version was not stated in the actions or target context.",
                            category="version")
            if candidate.get("host_ref"):
                generated_host_refs.setdefault(candidate["host_ref"], []).append(service_id)
            continue

        host_ref = candidate.get("host_ref")
        suffix = f"-{host_ref}" if host_ref else ""
        service_id = f"svc-{component['id']}{suffix}"
        if candidate.get("version"):
            service_id += "-" + _slug(candidate["version"])
        base_id, serial = service_id, 2
        while service_id in used_ids:
            service_id = f"{base_id}-{serial}"
            serial += 1
        used_ids.add(service_id)
        service: dict[str, Any] = {
            "id": service_id,
            "name": name,
            "cve": candidate.get("cve", []),
            "catalogue_component": component["id"],
            "is_substitute": bool(is_substitute),
            "epistemic_status": "inferred",
            "source": "program",
        }
        if candidate.get("version"):
            service["version"] = candidate["version"]
        if candidate.get("port"):
            service["port"] = candidate["port"]
        if host_ref:
            service["host_ref"] = host_ref
        if is_substitute:
            substitute_info = next((entry for entry in component.get("substitutes_for", [])
                                    if name.casefold() in {n.casefold() for n in entry.get("names", [])}), {})
            explanation = substitute_info.get("reason") or "This component is a functional substitute and does not fully reproduce the original software."
            add_missing(f"substitute-{name}",
                        f"exact software fidelity: {name}", explanation,
                        status="substitute_chosen", resolution=f"Using {component['name']} ({component['id']}) as a substitute. It is not a full recreation of {name}.")
        if not candidate.get("version"):
            add_missing(f"version-{name}-{host_ref or 'unassigned'}", f"version for {name}",
                        "A software dependency was identified, but its version was not stated in the actions or target context.",
                        category="version")
        services.append(service)
        if host_ref:
            generated_host_refs.setdefault(host_ref, []).append(service_id)

    # A role can seed a clearly labelled substitute when the report names a host
    # function but no service. This fills a deployable lab role without guessing
    # which real product or version was present.
    for hid, host in hosts.items():
        role = str(host.get("role", ""))
        if _is_attacker_role(role):
            continue
        host_refs = set(host.get("service_refs", [])) | set(generated_host_refs.get(hid, []))
        if any(service.get("id") in host_refs or service.get("host_ref") == hid for service in services):
            continue
        matched = [component for component in load_components()
                   if component.get("id") != "oss-attacker"
                   and any(_mentions(role, keyword) for keyword in component.get("role_keywords", []))]
        if not matched:
            continue
        component = matched[0]
        ports = component.get("default_ports", [])
        if not ports:
            continue
        if component["id"] in {"oss-nginx", "oss-httpd"}:
            service_name = "web server (substitute)"
        elif component["id"] == "oss-postgres":
            service_name = "database (substitute)"
        else:
            service_name = f"{component.get('software', component['name'])} (substitute)"
        service_id = f"svc-role-{component['id']}-{hid}"
        serial = 2
        base_id = service_id
        while service_id in used_ids:
            service_id = f"{base_id}-{serial}"
            serial += 1
        used_ids.add(service_id)
        port = ports[0]
        services.append({
            "id": service_id,
            "name": service_name,
            "host_ref": hid,
            "port": port["port"],
            "protocol": port.get("protocol", "tcp"),
            "catalogue_component": component["id"],
            "is_substitute": True,
            "epistemic_status": "inferred",
            "source": "program",
        })
        generated_host_refs.setdefault(hid, []).append(service_id)
        add_missing(
            f"role-substitute-{hid}-{component['id']}",
            f"Exact software and version for host {hid} (role: {role})",
            f"The host role indicates a generic {service_name.removesuffix(' (substitute)')} function, but the report does not identify its exact software or version.",
            status="substitute_chosen",
            resolution=f"Used {component['name']} ({component['id']}) as a role-based substitute. This is not asserted to be the original software or a full recreation.",
        )

    for action in actions:
        text = " ".join(str(action.get(key, "")) for key in ("name", "description"))
        cves = _cves(text)
        if cves and not any(cve in service.get("cve", []) for service in services for cve in cves):
            for cve in cves:
                add_missing(f"cve-{cve}", f"affected software for {cve}",
                            "The action names a vulnerability but does not identify a software dependency that can be mapped reliably.")

    # Keep user-defined hosts intact; remove only links to module-4 generated services from the prior run.
    old_hosts = result.get("hosts", [])
    by_id: dict[str, dict[str, Any]] = {host.get("id"): copy.deepcopy(host) for host in old_hosts if host.get("id")}
    old_generated_ids = {item.get("id") for item in result.get("services", []) if item.get("source") == "program"}
    for hid, generated in hosts.items():
        if hid not in by_id:
            by_id[hid] = generated
        else:
            existing = by_id[hid]
            if generated.get("os") and not existing.get("os"):
                existing["os"] = generated["os"]
            if generated.get("os_version") and not existing.get("os_version"):
                existing["os_version"] = generated["os_version"]
    for hid, host in by_id.items():
        current_refs = list(host.get("service_refs", []))
        current_refs = [ref for ref in current_refs if ref not in old_generated_ids]
        host["service_refs"] = list(dict.fromkeys([*current_refs, *generated_host_refs.get(hid, [])]))
    result["hosts"] = list(by_id.values())
    result["services"] = services
    result["missing_items"] = missing
    return result
