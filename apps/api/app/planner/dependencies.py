"""Deterministic, schema-checked dependency inference from Scenario IR."""
from __future__ import annotations

import copy
import json
import re
from typing import Any

from app.cti.missing import is_communication_description, refresh_missing_items
from app.planner.catalogue import component_by_id, load_components, match_software
from app.planner.reproducibility import annotate_reproducibility

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


# Markers used where the source names no machine; they never denote a host.
_NO_HOST = frozenset({"", "unknown", "unspecified", "none", "null", "n/a"})
_PLACEHOLDER_SERVICE_IDS = frozenset({"service-unspecified"})


def _is_host_ref(raw: Any) -> bool:
    return isinstance(raw, str) and raw.strip().casefold() not in _NO_HOST


def _slug56(value: str) -> str:
    """Same slug module 2 uses in its question ids."""
    return re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()[:56].strip("-") or "item"


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
        if _is_host_ref(action.get("target_host_ref")):
            continue
        text = " ".join(str(action.get(key, "")) for key in ("name", "description")).casefold()
        if not text.strip():
            continue
        # Named hosts in the source text are stronger evidence than a role match.
        explicit = []
        for hid, host in hosts.items():
            names = {hid, hid.replace("_", "-"), str(host.get("name", "")), str(host.get("hostname", ""))}
            if any(_mentions(text, name) for name in names if name):
                explicit.append(hid)
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
        "host_ref": _host_id(host_ref) if _is_host_ref(host_ref) else None,
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


# Words that may follow a product name without making it a different product.
_GENERIC_AFTER_PRODUCT = frozenset({
    "server", "servers", "service", "services", "web", "http", "https", "httpd", "database", "databases", "db",
    "version", "container", "image", "host", "hosts", "instance", "instances", "application", "applications", "app",
    "software", "daemon", "process", "port", "tcp", "udp", "on", "in", "at", "to", "and", "or", "the", "a",
})


def _is_part_of_other_product(text: str, end: int) -> bool:
    """True when the matched alias is only the first word of a longer product name.

    "Apache Struts", "Apache Tomcat" or "Apache Log4j" are not the Apache HTTP Server: a
    capitalised word right after the alias that is not a generic noun names another product.
    """
    following = re.match(r"[ \t]+([A-Za-z][\w-]*)", text[end:])
    if not following:
        return False
    word = following.group(1)
    return word[0].isupper() and word.casefold() not in _GENERIC_AFTER_PRODUCT


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
            if _is_part_of_other_product(text, match.end()):
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
                        if entry.get("name"):
                            host["name"] = str(entry["name"])
                        if entry.get("hostname"):
                            host["hostname"] = str(entry["hostname"])
                        if entry.get("os"):
                            host["os"] = str(entry["os"])
                        if entry.get("os_version") or entry.get("version"):
                            host["os_version"] = str(entry.get("os_version") or entry.get("version"))
                        hosts[hid] = host
                visit(value, str(key))

    visit(target_context)
    for action in actions:
        ref = action.get("target_host_ref")
        if _is_host_ref(ref):
            hid = _host_id(ref)
            hosts.setdefault(hid, {"id": hid, "role": "target", "epistemic_status": "inferred", "source": "program"})
    return hosts


_CLAUSE_SPLIT_RE = re.compile(r"(?<=[.;!?])\s+|\n+")
_PORT_RE = re.compile(r"\b(?:tcp|udp|port)\s*[/ ]?\s*(\d{1,5})\b", re.IGNORECASE)


def _host_name_spans(clause: str, hosts: dict[str, dict[str, Any]]) -> list[tuple[int, str]]:
    """Positions at which the clause names a known host (by id, name or hostname)."""
    spans: list[tuple[int, str]] = []
    for hid, host in hosts.items():
        if _is_attacker_role(str(host.get("role", ""))):
            continue
        names = {hid, hid.replace("_", "-"), str(host.get("name", "")), str(host.get("hostname", ""))}
        for name in names:
            if len(name) < 2:
                continue
            for match in re.finditer(rf"(?<![A-Za-z0-9_-]){re.escape(name)}(?![A-Za-z0-9_-])", clause, re.IGNORECASE):
                spans.append((match.start(), hid))
    return sorted(set(spans))


def _mentions_bound_to_hosts(text: str, hosts: dict[str, dict[str, Any]], fallback_host: Any = None):
    """Software mentions in free text, each bound to the host its own clause names.

    "from web, connect to PostgreSQL on db" puts PostgreSQL on db even though the step runs
    from web. Binding order: the host named next after the mention in the same clause; the
    only host the clause names; otherwise the single host whose role fits the component;
    and only then the host the whole text is about (``fallback_host``).
    """
    for clause in _CLAUSE_SPLIT_RE.split(text):
        if not clause.strip():
            continue
        spans = _host_name_spans(clause, hosts)
        named = list(dict.fromkeys(hid for _, hid in spans))
        for candidate in _candidate_from_mentions(clause):
            position = clause.casefold().find(candidate["name"].casefold())
            following = next((hid for start, hid in spans if start > position), None)
            host = following or (named[0] if len(named) == 1 else None)
            explicit = host is not None
            if host is None:
                component, _ = match_software(candidate["name"])
                keywords = (component or {}).get("role_keywords", [])
                fitting = [hid for hid, entry in hosts.items()
                           if not _is_attacker_role(str(entry.get("role", "")))
                           and any(_mentions(str(entry.get("role", "")), keyword) for keyword in keywords)]
                host = fitting[0] if len(fitting) == 1 else None
            if host is None and _is_host_ref(fallback_host):
                host = _host_id(fallback_host)
            candidate["host_ref"] = host
            candidate["host_explicit"] = explicit
            candidate["from_mention"] = True
            port = _PORT_RE.search(clause, max(position, 0))
            if port and 1 <= int(port.group(1)) <= 65535:
                candidate["port"] = int(port.group(1))
            yield candidate


def _stated_host_ports(ir: dict[str, Any], hosts: dict[str, dict[str, Any]]) -> dict[str, int]:
    """Ports the verified source text states next to a host name, one unambiguous port per host.

    Reads the verified quotes cited by actions, hosts and services. A port is attributed to the
    host named closest before it in the same clause; a host with two different stated ports is
    left out, because the text does not say which one a given service uses.
    """
    verified = {str(item.get("id")): str(item.get("quote") or "") for item in ir.get("evidence", []) or []
                if isinstance(item, dict) and item.get("quote_verified") is True}
    texts: list[str] = []
    for collection in ("actions", "hosts", "services"):
        for entity in ir.get(collection, []) or []:
            if isinstance(entity, dict):
                texts.extend(verified[str(ref)] for ref in entity.get("evidence_refs", []) or [] if str(ref) in verified)
    found: dict[str, set[int]] = {}
    for text in dict.fromkeys(texts):
        for clause in _CLAUSE_SPLIT_RE.split(text):
            spans = _host_name_spans(clause, hosts)
            for match in _PORT_RE.finditer(clause):
                port = int(match.group(1))
                before = [hid for start, hid in spans if start < match.start()]
                if before and 1 <= port <= 65535:
                    found.setdefault(before[-1], set()).add(port)
    return {hid: next(iter(ports)) for hid, ports in found.items() if len(ports) == 1}


_LIMITATION_RE = re.compile(
    r"不等於|不是|並非|無法|不能|不可|僅可|只能|只可|不代表|不重現|未重現|≠|"
    r"\b(?:not|cannot|can't|doesn't|don't|won't|never|only|instead\s+of|rather\s+than|without|unlike|except)\b",
    re.IGNORECASE)


def _assertive_clauses(text: str) -> str:
    """The part of a free-text supplement that states what the lab has.

    A clause saying what something is *not*, or is *only* a stand-in for ("Solr can only stand
    in for the entry point, it is not Horizon"), explains a limitation. Reading product names
    out of it would turn the user's caveat into services that the user never asked for.
    """
    # Sentence-level pieces only: "map X to host web, nginx 1.31.8 on TCP/80" must stay together
    # so the product keeps the host named earlier in the same sentence.
    return "\n".join(clause for clause in re.split(r"(?<=[.;!?])\s+|(?<=[。；！？])\s*|\n+", text)
                     if clause.strip() and not _LIMITATION_RE.search(clause))


def _is_os_image(component: dict[str, Any] | None) -> bool:
    """A catalogue entry that is an operating-system image rather than an application."""
    return bool(component) and component.get("runtime") == "vm" and "os_release" in component


def _answered_item(ir: dict[str, Any], supplement: dict[str, Any]) -> dict[str, Any] | None:
    return next((entry for entry in ir.get("missing_items", []) or []
                 if isinstance(entry, dict) and entry.get("id") == supplement.get("targets_missing_item")), None)


def _apply_chosen_substitutes(ir: dict[str, Any]) -> None:
    """Put a substitute the user chose for an unsupported service onto that service itself.

    The question "no catalogue component for X" carries ``service_ref``. When the user's answer
    names exactly one catalogue product, service X keeps its id, host, port and evidence and is
    deployed as that product, marked as a user-chosen substitute. Without this the choice
    became a second, host-less service and nothing was deployable.
    """
    services = {service.get("id"): service for service in ir.get("services", []) or [] if isinstance(service, dict)}
    for supplement in ir.get("supplements", []) or []:
        if not isinstance(supplement, dict) or not isinstance(supplement.get("text"), str):
            continue
        item = _answered_item(ir, supplement)
        service = services.get((item or {}).get("service_ref"))
        if service is None or item.get("status") not in {"substitute_chosen", "user_supplied"}:
            continue
        chosen = {}
        for mention in _candidate_from_mentions(supplement["text"]):
            component, _ = match_software(mention["name"])
            if component is not None and component.get("runtime") == "container":
                chosen[component["id"]] = component
        if len(chosen) != 1:
            continue  # no product named, or several: nothing unambiguous to apply
        component = next(iter(chosen.values()))
        service.pop("no_component", None)
        service.update({"catalogue_component": component["id"], "is_substitute": True,
                        "substitute_basis": "user_chosen", "substitute_supplement_ref": str(supplement.get("id") or "")})
        service.setdefault("field_sources", {})["catalogue_component"] = "user"


def _answered_host(ir: dict[str, Any], supplement: dict[str, Any]) -> str | None:
    """The host a supplement is about when it answers a question scoped to a host or its service."""
    item = _answered_item(ir, supplement)
    if item and item.get("service_ref"):
        service = next((entry for entry in ir.get("services", []) or [] if entry.get("id") == item["service_ref"]), None)
        return service.get("host_ref") if service else None
    where = (item or {}).get("applied_to") or (item or {}).get("target")
    if not isinstance(where, dict):
        return None
    if where.get("collection") == "hosts":
        return str(where.get("id"))
    if where.get("collection") == "services":
        service = next((entry for entry in ir.get("services", []) or [] if entry.get("id") == where.get("id")), None)
        return service.get("host_ref") if service else None
    return None


def _is_recorded_service(service: dict[str, Any]) -> bool:
    """A service stated by the analysis or the user (not a placeholder, not module-4 output)."""
    return (bool(str(service.get("name") or "").strip())
            and service.get("id") not in _PLACEHOLDER_SERVICE_IDS
            # a description of traffic ("encrypted communication channels") is not software to plan
            and not is_communication_description(service.get("name"))
            and service.get("source") != "program"
            # services derived from a supplement are rebuilt from that supplement on every run
            and not service.get("supplement_ref"))


def _match_component(name: str) -> tuple[dict[str, Any] | None, bool]:
    """Catalogue match for a recorded name, also when the product is only part of it.

    "VMware Horizon server" is VMware Horizon; a name that mentions two different catalogue
    products is ambiguous and stays unmatched.
    """
    component, is_substitute = match_software(name)
    if component is not None:
        return component, is_substitute
    found = {}
    remainder = name
    for mention in _candidate_from_mentions(name):
        matched, substitute = match_software(mention["name"])
        if matched is not None:
            found[matched["id"]] = (matched, substitute)
            remainder = re.sub(re.escape(mention["name"]), " ", remainder, flags=re.IGNORECASE)
    # Whatever the name says beyond the product must be generic ("server", "service"); any
    # other word means it names something else that merely contains a known product word.
    extra = [word for word in re.findall(r"[A-Za-z][\w-]*", remainder)
             if word.casefold() not in _GENERIC_AFTER_PRODUCT and word.casefold() not in {"unpatched", "vulnerable", "exposed"}]
    return next(iter(found.values())) if len(found) == 1 and not extra else (None, False)


def _generic_function_component(name: str) -> dict[str, Any] | None:
    """Catalogue stand-in for a service the source names only by its function.

    "web service" or "database server" names no product, so a clearly labelled substitute
    for that function can stand in. Any other word in the name ("Confluence web application")
    means a specific product was named, and it must not be swapped for a generic stand-in.
    """
    lowered = name.casefold()
    for component in load_components():
        if component.get("id") == "oss-attacker" or component.get("runtime") != "container" or not component.get("default_ports"):
            continue
        keywords = sorted((k.casefold() for k in component.get("role_keywords", [])), key=len, reverse=True)
        if not any(_mentions(lowered, keyword) for keyword in keywords):
            continue
        rest = lowered
        for keyword in keywords:
            rest = re.sub(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", " ", rest)
        if all(word in _GENERIC_AFTER_PRODUCT for word in re.findall(r"[a-z][\w-]*", rest)):
            return component
    return None


def _display_name(candidate: dict[str, Any], component: dict[str, Any]) -> str:
    """Name a service found by a text mention after the product, not after the matched words.

    An alias can be a vulnerability nickname or a host role ("Log4Shell", "domain controller");
    those are clues to a product, not names of software.
    """
    name = candidate["name"]
    if not candidate.get("from_mention"):
        return name
    product = re.sub(r"\s*\([^)]*\)\s*$", "", str(component.get("name") or "")).strip()
    known_names = {str(component.get("software", "")).casefold(), product.casefold()}
    if not product or name.casefold() in known_names or product.casefold() in name.casefold() or name.casefold() in product.casefold():
        return name
    return product


def _collect_candidates(ir: dict[str, Any], hosts: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    context = ir.get("target_context", {})
    candidates = list(_record_candidates(context))
    actions = ir.get("actions", [])
    for action in actions:
        text = " ".join(str(action.get(key, "")) for key in ("name", "description"))
        candidates.extend(_mentions_bound_to_hosts(text, hosts, action.get("target_host_ref")))
    # Verified source quotes cited for a host or service often carry the version and port the
    # structured record lacks ("runs nginx version 1.31.8 on TCP/80"); read them, bound to that host.
    verified = {str(item.get("id")): str(item.get("quote") or "") for item in ir.get("evidence", []) or []
                if isinstance(item, dict) and item.get("quote_verified") is True}
    for collection, host_key in (("hosts", "id"), ("services", "host_ref")):
        for entity in ir.get(collection, []) or []:
            if not isinstance(entity, dict) or entity.get("source") == "program":
                continue
            for ref in entity.get("evidence_refs", []) or []:
                if verified.get(str(ref)):
                    candidates.extend(_mentions_bound_to_hosts(verified[str(ref)], hosts, entity.get(host_key)))
    # A free-text supplement is the user's statement about the lab; software and host
    # associations it names are planned like any other, and marked as the user's.
    for supplement in ir.get("supplements", []) or []:
        if not isinstance(supplement, dict) or not isinstance(supplement.get("text"), str):
            continue
        item = _answered_item(ir, supplement)
        applied_as_substitute = any(service.get("substitute_supplement_ref") == supplement.get("id")
                                    for service in ir.get("services", []) or [] if isinstance(service, dict))
        if (item and item.get("service_ref")) or applied_as_substitute:
            continue  # a substitute chosen for one service is applied to that service, not added as another
        where = (item or {}).get("applied_to") or (item or {}).get("target") or {}
        answers_os = isinstance(where, dict) and where.get("field") in {"os", "os_version"}
        for mention in _mentions_bound_to_hosts(_assertive_clauses(supplement["text"]), hosts, _answered_host(ir, supplement)):
            if answers_os and _is_os_image(match_software(mention["name"])[0]):
                # "Windows Server 2019" answering an OS question is the host's OS (already written
                # to the host record), not a file-sharing service to expose on that host.
                continue
            mention["from_supplement"] = str(supplement.get("id") or "supplement")
            # A release the user names is what the lab will run, never what the source stated.
            mention["lab_version"], mention["version"] = mention.get("version"), None
            mention["host_explicit"] = bool(mention.get("host_explicit") or (item and mention.get("host_ref")))
            candidates.append(mention)

    candidates.extend(_context_text_candidates(context))
    # Every service the analysis or the user recorded is a dependency to plan for, whether
    # or not the catalogue knows it; ignoring them would hide unsupported software.
    recorded = [_candidate(service.get("name", ""), service.get("name", ""),
                           version=service.get("version"), cves=service.get("cve", []),
                           host_ref=service.get("host_ref"), explicit_port=service.get("port"))
                for service in ir.get("services", []) if _is_recorded_service(service)]
    # Recorded services go first so a text mention of the same product merges into them.
    candidates = recorded + candidates

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
        component, _ = _match_component(name)
        normalized_name = component["id"] if component else name.casefold()
        same_product = [item for item in unique
                        if (_match_component(item["name"])[0] or {}).get("id", item["name"].casefold()) == normalized_name]
        matches = [item for item in same_product if item.get("host_ref") == candidate.get("host_ref")]
        if not matches and candidate.get("from_mention") and not candidate.get("host_explicit") and len(same_product) == 1:
            # The text does not say where this product runs; it is the one already known.
            matches = same_product
        if not matches and candidate.get("from_supplement") and not candidate.get("host_explicit"):
            # A free-text remark that names a product without saying which host runs it adds no
            # service: there is nowhere to put it, and it may only be commentary.
            continue
        elif not matches and candidate.get("host_explicit"):
            # The text pins the product to a host: correct an earlier guess for the same product.
            guesses = [item for item in same_product if item.get("from_mention") and not item.get("host_explicit")]
            if len(guesses) == 1:
                guesses[0]["host_ref"] = candidate["host_ref"]
                guesses[0]["host_explicit"] = True
                matches = guesses
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
            if candidate.get("from_supplement"):
                target.setdefault("from_supplement", candidate["from_supplement"])
                if candidate.get("lab_version"):
                    target["lab_version"] = candidate["lab_version"]
    return unique


def plan_dependencies(ir: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with program-derived hosts/services and explicit unresolved dependencies."""
    result = copy.deepcopy(ir)
    _apply_chosen_substitutes(result)
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

    # Internally hosts are keyed by a normalised id; the IR's own host ids are the ones
    # every other reference uses, so map back before anything is written to the result.
    canonical = {_host_id(host["id"]): host["id"] for host in result.get("hosts", []) if host.get("id")}
    hosts = {canonical.get(hid, hid): {**host, "id": canonical.get(hid, hid)} for hid, host in hosts.items()}
    for candidate in candidates:
        if candidate.get("host_ref"):
            candidate["host_ref"] = canonical.get(candidate["host_ref"], candidate["host_ref"])
    for action in actions:
        if action.get("target_host_ref_source") == "program":
            action["target_host_ref"] = canonical.get(action["target_host_ref"], action["target_host_ref"])

    original_services = copy.deepcopy(result.get("services", []))
    existing_user_services = [item for item in original_services if _is_recorded_service(item)]
    services: list[dict[str, Any]] = []
    generated_host_refs: dict[str, list[str]] = {}
    previous_planner_items = {str(item.get("id")): item for item in result.get("missing_items", [])
                              if str(item.get("id", "")).startswith("planner_dep_")}
    missing = [item for item in result.get("missing_items", []) if not str(item.get("id", "")).startswith("planner_dep_")]
    seen_missing: set[str] = set()
    analysis_question_ids = " ".join(str(item.get("id")) for item in missing)

    def version_already_asked(name: str, service_id: str | None = None) -> bool:
        """Module 2 may already ask this product's version; one question is enough."""
        if service_id and f"missing-service-{_slug56(service_id)}-version" in analysis_question_ids:
            return True
        return f"missing-product-{_slug56(name)}-version" in analysis_question_ids

    def add_missing(key: str, field: str, reason: str, *, category: str = "software", status: str = "open",
                    resolution: str | None = None, severity: str = "major", service_ref: str | None = None) -> None:
        ident = "planner_dep_" + _slug(key)
        if ident in seen_missing:
            return
        seen_missing.add(ident)
        entry: dict[str, Any] = {
            "id": ident, "field": field, "category": category, "reason": reason,
            "severity": severity, "status": status,
        }
        if resolution:
            entry["resolution"] = resolution
        if service_ref:
            entry["service_ref"] = service_ref  # the service a chosen substitute is applied to
        earlier = previous_planner_items.get(ident)
        if earlier and earlier.get("resolution_source") == "user":
            # Re-planning must not discard a decision the user already made on this question.
            for key in ("status", "resolution", "resolution_source", "applied_to", "write_back"):
                if key in earlier:
                    entry[key] = earlier[key]
        missing.append(entry)

    used_ids: set[str] = set()
    used_user_ids: set[str] = set()
    for candidate in candidates:
        name = candidate["name"]
        component, is_substitute = _match_component(name)
        existing_user = next((item for item in existing_user_services
                              if item.get("name", "").casefold() == name.casefold()
                              and (not item.get("version") or not candidate.get("version")
                                   or item.get("version") == candidate.get("version"))), None)
        if component is None and existing_user:
            component = component_by_id(existing_user.get("catalogue_component"))
            is_substitute = bool(existing_user.get("is_substitute", False))
        function_substitute = False
        if component is None and existing_user and not candidate.get("from_mention"):
            component = _generic_function_component(name)
            is_substitute = function_substitute = component is not None
        if component is None:
            # Preserve analysis-stage facts even when they have no catalogue mapping.
            original = next((item for item in original_services
                             if item.get("name", "").casefold() == name.casefold()), None)
            if original:
                retained = copy.deepcopy(original)
                retained["no_component"] = True
                retained["is_substitute"] = False
                if retained not in services:
                    services.append(retained)
                    if retained.get("host_ref"):
                        # Still this host's service, even without a catalogue component.
                        generated_host_refs.setdefault(retained["host_ref"], []).append(retained["id"])
            add_missing(f"software-{name}-{candidate.get('version') or ''}",
                        f"software dependency: {name}" + (f" {candidate['version']}" if candidate.get("version") else ""),
                        "The dependency was identified in the actions or target context, but no compatible open-source catalogue component is available.",
                        service_ref=original.get("id") if original else None)
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
                if candidate.get("lab_version"):
                    # What the user says the lab runs; the service's own `version` stays the source's.
                    service["lab_version"] = candidate["lab_version"]
                    service.setdefault("field_sources", {})["lab_version"] = "user"
                for key in ("version", "port"):
                    if candidate.get(key) and service.get(key) != candidate[key]:
                        # Filled from a supplement or a verified source quote, not by the analysis record.
                        service[key] = candidate[key]
                        service.setdefault("field_sources", {})[key] = (
                            "user" if candidate.get("from_supplement") else "source_quote")
                services.append(service)
                used_user_ids.add(service_id)
                used_ids.add(service_id)
            else:
                for service in services:
                    if service.get("id") == service_id:
                        service["cve"] = list(dict.fromkeys([*service.get("cve", []), *candidate.get("cve", [])]))
            if function_substitute:
                add_missing(
                    f"role-substitute-{candidate.get('host_ref') or 'unassigned'}-{component['id']}",
                    f"Exact software and version for {name}" + (f" on host {candidate['host_ref']}" if candidate.get("host_ref") else ""),
                    f"The source names only the function ({name}), not the product or version that provided it.",
                    status="substitute_chosen",
                    resolution=f"Used {component['name']} ({component['id']}) as a function-based substitute. This is not asserted to be the original software or a full recreation.",
                )
            elif is_substitute:
                substitute_info = next((entry for entry in component.get("substitutes_for", [])
                                        if name.casefold() in {n.casefold() for n in entry.get("names", [])}), {})
                explanation = substitute_info.get("reason") or "This component is a functional substitute and does not fully reproduce the original software."
                add_missing(f"substitute-{name}", f"exact software fidelity: {name}", explanation,
                            status="substitute_chosen", resolution=f"Using {component['name']} ({component['id']}) as a substitute. It is not a full recreation of {name}.")
            if (not function_substitute and not candidate.get("version") and not existing_user.get("version")
                    and not version_already_asked(name, service_id)):
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
        display_name = _display_name(candidate, component)
        service: dict[str, Any] = {
            "id": service_id,
            "name": display_name,
            **({"matched_text": name} if display_name != name else {}),
            "cve": candidate.get("cve", []),
            "catalogue_component": component["id"],
            "is_substitute": bool(is_substitute),
            "epistemic_status": "inferred",
            "source": "program",
        }
        if candidate.get("from_supplement"):
            # Stated by the user in a supplement, not derived by the planner.
            # "absent": the source does not provide it; the user did (USER_SUPPLIED).
            service.update({"source": "user", "epistemic_status": "absent", "provenance_class": "USER_SUPPLIED",
                            "supplement_ref": candidate["from_supplement"]})
            if candidate.get("lab_version"):
                service["lab_version"] = candidate["lab_version"]
                service.setdefault("field_sources", {})["lab_version"] = "user"
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
        if not candidate.get("version") and not version_already_asked(display_name):
            add_missing(f"version-{name}-{host_ref or 'unassigned'}", f"version for {display_name}",
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

    # The catalogue pins one release per component. Say whether that release is what the source
    # (or the user) stated, or only what the lab happens to have.
    for service in services:
        component = component_by_id(service.get("catalogue_component"))
        pinned = str((component or {}).get("version") or "").strip()
        if not pinned or service.get("is_substitute") or not component.get("image"):
            continue
        stated = str(service.get("version") or "").strip()
        same = lambda value: bool(value) and (value == pinned or pinned.startswith(value + ".") or value.startswith(pinned + "."))
        if same(stated):
            by_user = (service.get("field_sources") or {}).get("version") == "user" or service.get("source") == "user"
            service["version_basis"] = "user_supplied" if by_user else "stated"
            continue
        if not stated and same(str(service.get("lab_version") or "").strip()):
            # The user picked this release for the lab; the source still states none.
            service["version_basis"] = "user_supplied"
            service["deployed_version"] = pinned
            continue
        service["version_basis"] = "substituted" if stated else "assumed"
        service["deployed_version"] = pinned
        add_missing(
            f"deployed-version-{service.get('id')}", f"deployed version of {service.get('name')}",
            (f"The source states version {stated}; the catalogue only provides {pinned}." if stated else
             f"The source does not state a version; the catalogue provides {pinned}."),
            category="version", status="substitute_chosen",
            resolution=(f"Deploying {component['name']} {pinned}. This release is "
                        + ("a substitute for the stated one" if stated else "an assumption, not a fact from the source")
                        + "; results do not show that the original system ran it."))

    # A port the source states for a host ("to victim-web over TCP/80") belongs to that host's
    # service when the host has exactly one service still lacking a port.
    for hid, port in _stated_host_ports(result, hosts).items():
        portless = [service for service in services if service.get("host_ref") == hid and not service.get("port")
                    and service.get("id") not in _PLACEHOLDER_SERVICE_IDS]
        taken = {service.get("port") for service in services if service.get("host_ref") == hid}
        if len(portless) == 1 and port not in taken:
            portless[0]["port"] = port
            portless[0].setdefault("field_sources", {})["port"] = "source_quote"

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
    # Planning may add catalogue services, but may never erase analysis entities.
    present = {item.get("id") for item in services}
    for original in original_services:
        if original.get("source") == "program" and str(original.get("id", "")).startswith("svc-"):
            continue  # module-4 output of an earlier run; it is rebuilt above, not carried over
        if original.get("supplement_ref") and str(original.get("id", "")).startswith("svc-"):
            continue
        if original.get("id") not in present:
            services.append(copy.deepcopy(original))
            present.add(original.get("id"))
    # One host is one image. When its services map to different catalogue components only one
    # can be deployed there; say which, and raise it here rather than letting IaC fail later.
    by_host: dict[str, list[dict[str, Any]]] = {}
    for service in services:
        service.pop("placement", None)
        service.pop("placement_reason", None)
        component = component_by_id(service.get("catalogue_component"))
        if service.get("host_ref") and component and component.get("runtime") in (None, "container", "vm"):
            by_host.setdefault(service["host_ref"], []).append(service)
    for hid, hosted in by_host.items():
        components = list(dict.fromkeys(service["catalogue_component"] for service in hosted))
        if len(components) < 2:
            continue
        # Software the source names outranks a stand-in; otherwise the first one found.
        primary = next((service for service in hosted if not service.get("is_substitute")), hosted[0])
        kept = primary["catalogue_component"]
        others = [service for service in hosted if service["catalogue_component"] != kept]
        for service in others:
            service["placement"] = "conflict"
            service["placement_reason"] = (
                f"主機 {hid} 已由 {primary.get('name')}（{kept}）決定映像；一台主機只能部署一個元件，"
                f"{service.get('name')}（{service['catalogue_component']}）不會被部署在這台主機上。")
        add_missing(
            f"host-component-conflict-{hid}", f"主機 {hid} 的元件衝突", category="dependency", severity="blocker",
            reason=(f"主機 {hid} 的服務對應到多個元件（{', '.join(components)}），但一台主機只能部署一個映像。"
                    f"目前只會部署 {primary.get('name')}（{kept}）；"
                    f"{', '.join(str(service.get('name')) for service in others)} 不會被部署。"
                    "請把它們移到另一台主機、改成同一個元件，或確認不部署。"))

    if actions and not any(item.get("id") not in _PLACEHOLDER_SERVICE_IDS for item in services):
        # Nothing to build: say so as a blocker instead of letting an empty plan look deployable.
        add_missing("no-target-software", "目標軟體／服務",
                    "來源與補件都沒有指出任何目標軟體、服務或弱點，無法規劃可重現的環境。請補上受害系統的產品與版本，或確認此情境不部署。",
                    severity="blocker")
    # The "no service known yet" placeholder has done its job once real services exist.
    if any(item.get("id") not in _PLACEHOLDER_SERVICE_IDS for item in services):
        services = [item for item in services if item.get("id") not in _PLACEHOLDER_SERVICE_IDS]
    result["services"] = services
    regenerated = {str(item.get("id")) for item in missing}
    for ident, earlier in previous_planner_items.items():
        if ident not in regenerated and earlier.get("resolution_source") == "user":
            # The question no longer arises because the user answered it; keep it so the
            # supplement that answered it still points at something.
            missing.append({**earlier, "superseded": True})
    result["missing_items"] = missing
    # Planning may have filled in what an analysis-stage question asked (a version read from
    # a quote or a supplement); recompute those questions so they do not stay open.
    result["missing_items"] = refresh_missing_items(result, add_new=False)
    return annotate_reproducibility(result)
