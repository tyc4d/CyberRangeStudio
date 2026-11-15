"""Deterministic least-access topology builder for a Scenario IR."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any

from cr_contracts import iter_errors

from app.cti.missing import is_attacker_role
from app.planner.catalogue import component_by_id


def connections_digest(plan: dict[str, Any]) -> str:
    """Stable sha256 over a plan's connections, used to bind human approval to an exact ruleset."""
    connections = plan.get("connections", []) if isinstance(plan, dict) else []
    canonical = sorted(
        json.dumps(
            {"from_host": c.get("from_host"), "to_host": c.get("to_host"),
             "port": c.get("port"), "protocol": c.get("protocol", "tcp")},
            sort_keys=True,
        )
        for c in connections
    )
    return hashlib.sha256("\n".join(canonical).encode("utf-8")).hexdigest()


def _host_id(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "target").casefold()).strip("_") or "target"


def _is_attacker(host: dict[str, Any]) -> bool:
    return is_attacker_role(host.get("role", ""))


def _role_contains(role: str, term: str) -> bool:
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(term.casefold())}(?![a-z0-9])", role.casefold()))


_EXPOSED_TERMS = ("exposed", "external", "internet", "internet-facing", "public", "public-facing", "web", "dmz", "對外")
_INTERNAL_TERMS = ("internal", "內部", "內網", "management", "isolated", "隔離")
_NO_HOST = frozenset({"", "unknown", "unspecified", "none", "null", "n/a"})
# Techniques whose target is, by definition, where the intrusion enters from outside.
_ENTRY_TECHNIQUES = ("T1190", "T1133", "T1189", "T1566", "T1195", "T1199")


def _stated_exposure(host: dict[str, Any]) -> bool | None:
    """Exposure the IR states for this host: placement first (it may be a user answer), then role."""
    for text in (str(host.get("network_placement", "")), str(host.get("role", ""))):
        if not text.strip():
            continue
        if any(_role_contains(text, term) or (not term.isascii() and term in text) for term in _INTERNAL_TERMS):
            return False
        if any(_role_contains(text, term) or (not term.isascii() and term in text) for term in _EXPOSED_TERMS):
            return True
    return None


def _is_exposed(host: dict[str, Any]) -> bool:
    if _is_attacker(host):
        return True
    if host.get("_inferred_entry"):
        return True
    return _stated_exposure(host) is True


def _entry_host_ids(ir: dict[str, Any], candidates: set[str]) -> tuple[list[str], str]:
    """Hosts the attack must enter through when the IR states no exposure for any host.

    Preference: targets of initial-access actions; otherwise the target of the earliest
    action that names a host. Returned with the basis so the plan can say it is inferred.
    """
    actions = [action for action in ir.get("actions", []) if isinstance(action, dict)]

    def target(action: dict[str, Any]) -> str | None:
        ref = action.get("target_host_ref")
        if not isinstance(ref, str) or ref.strip().casefold() in _NO_HOST:
            return None
        hid = _host_id(ref)
        return hid if hid in candidates else None

    initial = []
    for action in actions:
        tactic = str(action.get("attack_tactic") or action.get("tactic_id") or "").casefold()
        technique = str(action.get("attack_technique") or action.get("technique_id") or "").upper()
        if tactic in {"initial-access", "ta0001"} or technique.startswith(_ENTRY_TECHNIQUES):
            if target(action):
                initial.append((target(action), str(action.get("id"))))
    if initial:
        ids = list(dict.fromkeys(hid for hid, _ in initial))
        return ids, "initial-access action(s) " + ", ".join(aid for _, aid in initial)
    has_predecessor = {relation.get("to_action") for relation in ir.get("relations", []) if isinstance(relation, dict)}
    ordered = [a for a in actions if a.get("id") not in has_predecessor] + [a for a in actions if a.get("id") in has_predecessor]
    for action in ordered:
        if target(action):
            return [target(action)], f"earliest action with a named target ({action.get('id')})"
    return [], ""


def _substitute_port(service: dict[str, Any]) -> tuple[int, str] | None:
    """Where a substitute actually listens when it cannot serve the original service's port.

    A stand-in image only listens on its own ports. Declaring the original port (say 443 for
    a product replaced by nginx) would describe a deployment that cannot exist.
    """
    component = component_by_id(service.get("catalogue_component"))
    if not service.get("is_substitute") or not component or not component.get("default_ports"):
        return None
    try:
        stated = int(service.get("port"))
    except (TypeError, ValueError):
        return None
    protocol = str(service.get("protocol", "tcp")).casefold()
    if any(int(entry["port"]) == stated and str(entry.get("protocol", "tcp")) == protocol
           for entry in component["default_ports"]):
        return None
    entry = component["default_ports"][0]
    return int(entry["port"]), str(entry.get("protocol", "tcp"))


def _port_for(service: dict[str, Any]) -> tuple[int, str] | None:
    replaced = _substitute_port(service)
    if replaced:
        return replaced
    try:
        port = int(service.get("port"))
        if 1 <= port <= 65535:
            protocol = str(service.get("protocol", "tcp")).casefold()
            return port, protocol if protocol in {"tcp", "udp"} else "tcp"
    except (TypeError, ValueError):
        pass
    component = component_by_id(service.get("catalogue_component"))
    if component and component.get("default_ports"):
        entry = component["default_ports"][0]
        return int(entry["port"]), str(entry.get("protocol", "tcp"))
    name = str(service.get("name", "")).casefold()
    known_ports = {"http": (80, "tcp"), "https": (443, "tcp"), "ssh": (22, "tcp"),
                   "mysql": (3306, "tcp"), "postgres": (5432, "tcp"),
                   "postgresql": (5432, "tcp"), "redis": (6379, "tcp"), "dns": (53, "udp"),
                   "smb": (445, "tcp"),
                   # IANA-registered defaults for protocol services a report names without a port.
                   "rdp": (3389, "tcp"), "remote desktop": (3389, "tcp"), "ldap": (389, "tcp"),
                   "winrm": (5985, "tcp"), "mssql": (1433, "tcp"), "ftp": (21, "tcp"),
                   "smtp": (25, "tcp"), "telnet": (23, "tcp"), "vnc": (5900, "tcp"), "kerberos": (88, "tcp")}
    for label, result in known_ports.items():
        # Whole words only: "rdp" must not match inside "wordpress".
        if re.search(rf"(?<![a-z0-9]){re.escape(label)}(?![a-z0-9])", name):
            return result
    return None


def _service_matches_action(service: dict[str, Any], action: dict[str, Any]) -> bool:
    text = " ".join(str(action.get(key, "")) for key in ("name", "description")).casefold()
    if not text:
        return False
    if any(str(cve).casefold() in text for cve in service.get("cve", [])):
        return True
    labels = [str(service.get("name", ""))]
    component = component_by_id(service.get("catalogue_component"))
    if component:
        labels.extend(component.get("aliases", []))
        for substitute in component.get("substitutes_for", []):
            labels.extend(substitute.get("names", []))
    return any(label and re.search(rf"(?<![\w]){re.escape(label.casefold())}(?![\w])", text)
               for label in labels)


def _required_services(services: list[dict[str, Any]], actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matched = [service for service in services
               if any(_service_matches_action(service, action) for action in actions)]
    if matched:
        return matched
    return services if len(services) == 1 else []


def build_environment_plan(ir: dict[str, Any]) -> dict[str, Any]:
    hosts = [copy.deepcopy(host) for host in ir.get("hosts", []) if host.get("id")]
    seen = {_host_id(host["id"]) for host in hosts}
    hosts_by_id = {_host_id(host["id"]): host for host in hosts}
    target_hosts = [host for host in hosts if not _is_attacker(host)]
    if not target_hosts:
        target = {"id": "target", "role": "target", "service_refs": []}
        hosts.append(target)
        hosts_by_id["target"] = target
        target_hosts = [target]

    attacker_hosts = [host for host in hosts if _is_attacker(host)]
    notes: list[str] = []
    if not attacker_hosts and ir.get("actions"):
        attacker_id = "attacker"
        serial = 2
        while attacker_id in seen:
            attacker_id = f"attacker_{serial}"
            serial += 1
        attacker = {"id": attacker_id, "role": "attacker", "service_refs": []}
        hosts.append(attacker)
        hosts_by_id[attacker_id] = attacker
        attacker_hosts = [attacker]
        notes.append("An attacker host was added as a lab scaffold because the IR did not define one.")

    services = [item for item in ir.get("services", []) if item.get("id")]
    target_ids = {_host_id(host["id"]) for host in target_hosts}

    # Without any reachable target the attacker has no way in and the chain cannot start.
    # If the IR states no exposure, expose only the entry host and say that this is inferred.
    if ir.get("actions") and not any(_stated_exposure(host) is True for host in target_hosts):
        undecided = {hid for hid in target_ids if _stated_exposure(hosts_by_id[hid]) is None}
        entry_ids, basis = _entry_host_ids(ir, undecided)
        for hid in entry_ids:
            hosts_by_id[hid]["_inferred_entry"] = True
            notes.append(f"Host {hid} was placed on the external network as the inferred entry point "
                         f"(basis: {basis}); the source does not state its network placement. Confirm or correct it.")
        if not entry_ids:
            notes.append("No target host is stated or inferable as reachable from outside; the attacker has no path "
                         "to any target until a host's network placement is supplied.")
    assigned: dict[str, list[dict[str, Any]]] = {hid: [] for hid in target_ids}
    unassigned: list[str] = []
    for service in services:
        refs = [hid for hid, host in hosts_by_id.items()
                if service.get("id") in host.get("service_refs", []) or _host_id(service.get("host_ref")) == hid]
        if not refs and len(target_ids) == 1:
            refs = list(target_ids)
        for hid in refs:
            if hid in assigned:
                assigned[hid].append(service)
        if not refs:
            unassigned.append(service["id"])

    environment_hosts: list[dict[str, Any]] = []
    _emitted: set[str] = set()
    for host in hosts:
        hid = _host_id(host["id"])
        if hid in _emitted:
            # Upstream may carry two host records that normalize to the same id
            # (e.g. "victim-web" and "victim_web"); emit each host once.
            continue
        _emitted.add(hid)
        entries = []
        switched_off = [service for service in assigned.get(hid, []) if service.get("lab_enabled") is False]
        if switched_off:
            # The user answered that the lab will not run these; no port, no path, not reproduced.
            assigned[hid] = [service for service in assigned[hid] if service.get("lab_enabled") is not False]
            notes.append(f"Host {hid}: not enabled in the lab by the user's choice: "
                         + ", ".join(str(service.get("name")) for service in switched_off)
                         + ". Steps that rely on them are not reproduced.")
        unplaced = [service for service in assigned.get(hid, []) if service.get("placement") == "conflict"]
        if unplaced:
            # Module 4 found that these cannot share this host's single image.
            assigned[hid] = [service for service in assigned[hid] if service.get("placement") != "conflict"]
            notes.append(f"Host {hid} deploys one component; not deployed there: "
                         + ", ".join(f"{service.get('name')} ({service.get('catalogue_component')})" for service in unplaced)
                         + ". Move them to another host or remove them.")
        if hid in assigned:
            for service in assigned[hid]:
                port_proto = _port_for(service)
                if not port_proto:
                    notes.append(f"No port is known for service {service.get('name')} ({service.get('id')}); it remains unreachable by default.")
                    continue
                port, protocol = port_proto
                entry: dict[str, Any] = {"name": str(service.get("name", service["id"])), "port": port, "protocol": protocol}
                if _substitute_port(service):
                    component = component_by_id(service.get("catalogue_component")) or {}
                    entry.update({"stated_port": int(service["port"]), "port_basis": "substitute_default"})
                    notes.append(
                        f"Service {service.get('name')} on host {hid} is stated on port {service['port']}, but its substitute "
                        f"{component.get('name', service.get('catalogue_component'))} only listens on {port}. The lab uses "
                        f"{port}; this port is a substitution, not a fact from the source.")
                else:
                    component = component_by_id(service.get("catalogue_component"))
                    supported = {int(p["port"]) for p in (component or {}).get("default_ports", [])}
                    if component and component.get("image") and supported and port not in supported:
                        notes.append(
                            f"Service {service.get('name')} on host {hid} uses port {port}, which "
                            f"{component.get('name', component['id'])} does not listen on ({sorted(supported)}). "
                            "IaC generation will refuse this until the port or the component is changed.")
                entries.append(entry)
        network_refs = [] if _is_attacker(host) else ["scenario-internal"]
        if _is_exposed(host):
            network_refs.append("external")
        env_host: dict[str, Any] = {
            "id": hid,
            "role": str(host.get("role", "host")),
            "networks": network_refs,
            "services": entries,
        }
        if unplaced:
            env_host["unplaced_services"] = [
                {"name": str(service.get("name", service["id"])), "component": service.get("catalogue_component"),
                 "reason": "host already uses another component"} for service in unplaced]
        if host.get("_inferred_entry"):
            env_host["exposure_basis"] = "inferred_entry_point"
        elif not _is_attacker(host) and _stated_exposure(host) is not None:
            env_host["exposure_basis"] = "stated"
        component_ids = list(dict.fromkeys(service.get("catalogue_component") for service in assigned.get(hid, [])
                                           if service.get("catalogue_component")))
        if len(component_ids) > 1:
            notes.append(f"Host {hid} has services from multiple catalogue components; the plan schema has one image_hint, so inspect its image selection.")
        if _is_attacker(host):
            env_host["image_hint"] = "oss-attacker"
            env_host["component_mode"] = "real"
        else:
            for service in assigned.get(hid, []):
                if service.get("catalogue_component"):
                    env_host["image_hint"] = service["catalogue_component"]
                    if service.get("is_substitute"):
                        # The image is real software, but it stands in for what the source names.
                        env_host["substitute_for"] = str(service.get("name") or service.get("id"))
                        env_host["substitute_basis"] = str(service.get("substitute_basis") or "catalogue_substitute")
                    if service.get("version_basis") in {"assumed", "substituted"}:
                        # Real software, but not a release the source establishes.
                        env_host["version_basis"] = service["version_basis"]
                        env_host["deployed_version"] = service.get("deployed_version")
                    break
            # A host whose service maps to a real catalogue component is deployed as the
            # real open-source software; otherwise it falls back to a benign substitute.
            component = component_by_id(env_host.get("image_hint"))
            if component and component.get("runtime") not in (None, "container", "vm"):
                # The catalogue knows this software but cannot deploy it. Say so instead of
                # presenting it as a real or substitute component.
                env_host["runtime"] = str(component.get("runtime") or "unsupported")
                env_host["deployable"] = False
                notes.append(f"Host {hid} needs {component.get('name', component['id'])}, which the catalogue cannot "
                             f"deploy ({component.get('fidelity') or 'no deployable fixture'}). It is not replaced by a stand-in.")
            elif component and component.get("runtime") == "vm":
                env_host["runtime"] = "vm"
                spec = component.get("vm_spec", {})
                env_host["guest"] = {
                    "os_family": component.get("os_family"), "os_release": component.get("os_release"),
                    "image_ref": component.get("image_ref"), "image_digest": component.get("image_digest"),
                    "cpu": spec.get("cpu"), "memory_mib": spec.get("memory_mib"), "disk_gib": spec.get("disk_gib"),
                }
                if component.get("deployable") is False:
                    # A VM the catalogue cannot build yet is neither "real" nor a substitute.
                    env_host["deployable"] = False
                    notes.append(f"Host {hid} needs {component.get('name', component['id'])} as a VM, which is not "
                                 f"deployable yet ({component.get('fidelity') or 'no validated image'}).")
                else:
                    env_host["component_mode"] = "real"
            else:
                env_host["runtime"] = "container"
                env_host["component_mode"] = "real" if component and component.get("image") else "substitute"
        environment_hosts.append(env_host)

    if unassigned:
        notes.append("Services without a resolved host association were left out of host service lists: " + ", ".join(unassigned) + ".")

    connections: list[dict[str, Any]] = []
    rules: list[dict[str, Any]] = [{"from": "*", "to": "*", "action": "deny"}]
    action_by_id = {action.get("id"): action for action in ir.get("actions", [])}
    attacker_id = _host_id(attacker_hosts[0]["id"]) if attacker_hosts else None

    def add_connection(source_id: str, dest_id: str, port_proto: tuple[int, str] | None, reason: str) -> None:
        if source_id == dest_id:
            return
        connection: dict[str, Any] = {"from_host": source_id, "to_host": dest_id, "reason": reason}
        rule: dict[str, Any] = {"from": source_id, "to": dest_id, "action": "allow"}
        if port_proto:
            port, protocol = port_proto
            connection.update({"port": port, "protocol": protocol})
            rule["port"] = port
        else:
            notes.append(f"Connection {source_id} to {dest_id} has no known destination port and was not allowed.")
            return
        identity = (connection["from_host"], connection["to_host"], connection["port"], connection["protocol"])
        if any((item.get("from_host"), item.get("to_host"), item.get("port"), item.get("protocol")) == identity for item in connections):
            return
        connections.append(connection)
        rules.append(rule)

    # Permit the lab attacker to reach only mapped target service ports.
    if attacker_id:
        targeted_refs = {_host_id(action.get("target_host_ref")) for action in ir.get("actions", []) if action.get("target_host_ref")}
        exposed_targets = {hid for hid in target_ids if _is_exposed(hosts_by_id[hid])}
        reachable_targets = [hid for hid in exposed_targets if not targeted_refs or hid in targeted_refs]
        for hid in reachable_targets:
            related_actions = [action for action in ir.get("actions", [])
                               if not action.get("target_host_ref") or _host_id(action.get("target_host_ref")) == hid]
            action_label = ", ".join(str(action.get("id")) for action in related_actions) or "scenario service dependency"
            required_services = _required_services(assigned.get(hid, []), related_actions)
            if assigned.get(hid) and not required_services:
                notes.append(f"Actions for host {hid} do not identify one of its multiple services; no inbound service port was opened.")
            for service in required_services:
                port_proto = _port_for(service)
                if port_proto:
                    add_connection(attacker_id, hid, port_proto,
                                   f"Scenario action(s) {action_label} require access to {service.get('name')}.")

    # An action the source (or the user) states is launched from one host against another
    # needs that path. This is a stated fact about one step, not an inference from ordering.
    for action in ir.get("actions", []):
        origin, destination = action.get("source_host_ref"), action.get("target_host_ref")
        if not origin or not destination:
            continue
        if action.get("epistemic_status") != "supported" and action.get("source") != "user":
            continue
        source_id, dest_id = _host_id(origin), _host_id(destination)
        if source_id == dest_id or source_id not in hosts_by_id or dest_id not in hosts_by_id:
            continue
        stated_services = _required_services(assigned.get(dest_id, []), [action])
        ports = [entry for entry in (_port_for(service) for service in stated_services) if entry]
        if not ports:
            notes.append(f"Action {action.get('id')} is stated to run from {source_id} against {dest_id}, but no "
                         "destination service port is identified; the path stays denied.")
        for port_proto in ports:
            add_connection(source_id, dest_id, port_proto,
                           f"Action {action.get('id')} is stated to run from {source_id} against {dest_id}.")

    # Only explicit, confirmed dependency edges may add host-to-host paths. Temporal order alone never opens a connection.
    for relation in ir.get("relations", []):
        if relation.get("kind") != "dependency" or relation.get("confirmed", False) is not True:
            continue
        first = action_by_id.get(relation.get("from_action"), {})
        second = action_by_id.get(relation.get("to_action"), {})
        source_id = _host_id(first.get("target_host_ref")) if first.get("target_host_ref") else None
        dest_id = _host_id(second.get("target_host_ref")) if second.get("target_host_ref") else None
        if not source_id or not dest_id or source_id == dest_id:
            continue
        rationale = relation.get("rationale") or f"{first.get('id')} -> {second.get('id')}"
        reason = f"Confirmed dependency {relation.get('id')}: {rationale}"
        destination_services = _required_services(assigned.get(dest_id, []), [second])
        ports = [_port_for(service) for service in destination_services]
        ports = [entry for entry in ports if entry]
        if ports:
            for port_proto in ports:
                add_connection(source_id, dest_id, port_proto, reason)
        else:
            # An ambiguous destination service or missing port remains denied.
            notes.append(f"Confirmed dependency {relation.get('id')} has no uniquely identified destination service port; default deny remains in effect.")

    network_plan = [{"id": "scenario-internal", "segment": "scenario", "internal": True}]
    if any("external" in host["networks"] for host in environment_hosts):
        network_plan.append({"id": "external", "segment": "external", "internal": False})

    # Segmentation expectations: an attacker-origin host must NOT reach an internal-only
    # host's service port unless a connection was explicitly opened above. Module 8 probes
    # each of these and fails the report if any connects.
    verify_blocked: list[dict[str, Any]] = []
    allowed = {(c["from_host"], c["to_host"], c.get("port")) for c in connections}
    hosts_by_eid = {h["id"]: h for h in environment_hosts}
    for source in environment_hosts:
        if "external" not in source.get("networks", []) and not _is_attacker({"role": source.get("role", "")}):
            continue
        for dest in environment_hosts:
            if dest["id"] == source["id"]:
                continue
            if "external" in dest.get("networks", []):
                continue  # dest is itself exposed; segmentation is about internal-only hosts
            # Only assert a block where network isolation actually enforces it: hosts that
            # share a network are mutually reachable on every port (Docker does not filter
            # per-port between containers on the same network), so claiming such a pair is
            # "blocked" would be false. The connection/access rules are declarative intent;
            # real same-network micro-segmentation is a documented limitation, not verified here.
            if set(source.get("networks", [])) & set(dest.get("networks", [])):
                continue
            for svc in dest.get("services", []):
                port = svc.get("port")
                if (source["id"], dest["id"], port) in allowed:
                    continue
                verify_blocked.append({
                    "from_host": source["id"], "to_host": dest["id"], "port": port,
                    "protocol": svc.get("protocol", "tcp"),
                    "reason": f"{source['id']} shares no network with internal service {dest['id']}:{port} and must not reach it.",
                })

    plan: dict[str, Any] = {
        "hosts": environment_hosts,
        "networks": network_plan,
        "connections": connections,
        "access_rules": rules,
        "approval": {"approved": False},
    }
    if verify_blocked:
        plan["verify_blocked"] = verify_blocked
    if notes:
        plan["notes"] = list(dict.fromkeys(notes))

    environment_errors = iter_errors("environment-plan", plan)
    if environment_errors:
        raise ValueError(f"Generated environment_plan failed validation: {environment_errors}")
    return plan


def attach_environment_plan(ir: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(ir)
    plan = build_environment_plan(result)
    result["environment_plan"] = plan
    errors = iter_errors("scenario-ir", result)
    if errors:
        raise ValueError(f"Scenario IR with environment_plan failed validation: {errors}")
    return result
