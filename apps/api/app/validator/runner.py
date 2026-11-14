"""Harmless, plan-scoped validation checks for a local Compose PoC."""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from cr_contracts import iter_errors

from app import config, store
from app.deploy import manager
from app.iac.generator import PlanError, get_generated, inspect_plan, validate_id


def _db() -> sqlite3.Connection:
    path = config.DATA_DIR / "validation.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute(
        """CREATE TABLE IF NOT EXISTS validation_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scenario_id TEXT NOT NULL,
            run_at TEXT NOT NULL,
            report_json TEXT NOT NULL
        )"""
    )
    db.execute("CREATE INDEX IF NOT EXISTS validation_reports_scenario_idx ON validation_reports(scenario_id, id)")
    return db


def get_latest_report(scenario_id: str) -> dict[str, Any] | None:
    scenario_id = validate_id(scenario_id)
    with _db() as db:
        row = db.execute(
            "SELECT report_json FROM validation_reports WHERE scenario_id=? ORDER BY id DESC LIMIT 1",
            (scenario_id,),
        ).fetchone()
    return json.loads(row["report_json"]) if row else None


def _status(returncode: int, not_tested: bool = False) -> str:
    if not_tested:
        return "NOT_TESTED"
    return "PASS" if returncode == 0 else "FAIL"


def _aggregate(checks: list[dict[str, Any]]) -> str:
    """Conservatively summarize checks: a missing or failed check cannot pass."""
    if not checks:
        return "NOT_TESTED"
    statuses = [check["status"] for check in checks]
    if all(status == "PASS" for status in statuses):
        return "PASS"
    if all(status == "NOT_TESTED" for status in statuses):
        return "NOT_TESTED"
    if "FAIL" in statuses:
        return "FAIL"
    return "PARTIAL"


def _check(check_id: str, name: str, category: str, status: str, expected: str, observed: str,
           action_ref: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"id": check_id, "name": name, "category": category, "status": status,
                            "expected": expected, "observed": observed}
    if action_ref is not None:
        item["action_ref"] = action_ref
    return item


def _tcp_probe_script(target: str, port: int) -> str:
    return (
        "import socket\n"
        f"target={target!r}\nport={port}\n"
        "try:\n"
        " s=socket.create_connection((target,port),timeout=3); s.close(); print('CONNECTED')\n"
        "except socket.gaierror as exc:\n"
        # Name did not resolve: inconclusive. This is NOT proof that a path is blocked —
        # a wrong/unresolvable name must never count as a passing segmentation check.
        " print('UNRESOLVED:'+str(exc))\n"
        "except OSError as exc:\n"
        " print('BLOCKED:'+type(exc).__name__+':'+str(exc))"
    )


def _http_probe_script(target: str, port: int, path: str) -> str:
    return (
        "import urllib.error,urllib.request\n"
        f"url='http://{target}:{port}{path}'\n"
        "try:\n"
        " response=urllib.request.urlopen(url,timeout=3)\n"
        "except urllib.error.HTTPError as exc:\n"
        " response=exc\n"
        "except Exception as exc:\n"
        " print('NO_HTTP_RESPONSE:'+type(exc).__name__+':'+str(exc)); raise SystemExit(0)\n"
        "print('HTTP_STATUS:'+str(response.code))\n"
        "print('BODY:'+response.read().decode('utf-8','replace'))"
    )


def _version_command(component_id: str) -> list[str] | None:
    return {
        "oss-nginx": ["nginx", "-v"],
        "oss-httpd": ["httpd", "-v"],
        "oss-postgres": ["postgres", "--version"],
        "oss-attacker": ["cat", "/etc/alpine-release"],
    }.get(component_id)


def _version_matches(expected: str, observed: str, component_id: str) -> bool:
    if component_id == "oss-attacker":
        return observed.strip().startswith(expected)
    return expected in observed


def _action_refs_for_connection(connection: dict[str, Any], actions: list[dict[str, Any]]) -> list[str]:
    reason = str(connection.get("reason", ""))
    refs: list[str] = []
    for action in actions:
        action_id = action.get("id")
        if not isinstance(action_id, str):
            continue
        id_in_reason = re.search(rf"(?<![A-Za-z0-9_-]){re.escape(action_id)}(?![A-Za-z0-9_-])", reason)
        if id_in_reason or action.get("target_host_ref") == connection.get("to_host"):
            refs.append(action_id)
    return refs


def _result_output(result: dict[str, Any]) -> str:
    return (result.get("stdout", "").strip() or result.get("stderr", "").strip()
            or f"probe command exited with status {result.get('returncode', 'unknown')}")


def _probe_status(result: dict[str, Any], should_connect: bool, docker_unavailable: bool = False) -> tuple[str, str]:
    observed = _result_output(result)
    if "CONNECTED" in observed:
        return ("PASS" if should_connect else "FAIL"), observed
    if "UNRESOLVED:" in observed:
        # A name-resolution failure proves nothing about the network path; never a PASS.
        return "NOT_TESTED", observed + " (target name did not resolve; inconclusive)"
    if "BLOCKED:" in observed:
        return ("FAIL" if should_connect else "PASS"), observed
    if docker_unavailable or result.get("returncode") in {2, 125, 127}:
        return "NOT_TESTED", observed
    return "NOT_TESTED", observed


def run(scenario_id: str) -> dict[str, Any]:
    scenario_id = validate_id(scenario_id)
    ir = store.get(scenario_id)
    if ir is None:
        raise KeyError(scenario_id)
    try:
        get_generated(scenario_id)
    except FileNotFoundError as exc:
        raise PlanError(["generate IaC before validating the environment"]) from exc
    plan = ir.get("environment_plan")
    normalized, component_report = inspect_plan(plan, scenario_id)
    if not component_report["deployable"]:
        raise PlanError(component_report["errors"], component_report)
    hosts = normalized["hosts"]
    component_by_id = normalized["components"]
    plan_connections = plan.get("connections", [])
    actions = [action for action in ir.get("actions", []) if isinstance(action, dict) and action.get("id")]
    run_at = datetime.now(timezone.utc).isoformat()
    run_id = uuid.uuid4().hex
    artifact_dir = config.DATA_DIR / "validation-runs" / scenario_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / f"{run_id}.json"
    evidence_path = str(artifact_path)

    ps = manager.compose_ps_result(scenario_id)
    containers = manager._parse_compose_ps(ps["stdout"]) if ps["returncode"] == 0 else []
    container_by_service = {container.get("service"): container for container in containers}
    for host in hosts:
        host_id = host["id"]
        container_by_service.setdefault(
            host_id,
            next((c for c in containers if c.get("name") == f"cr-demo-{scenario_id}-{host_id}"), None),
        )
    docker_unavailable = ps["returncode"] == 127

    service_checks: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    for host in hosts:
        host_id = host["id"]
        container = container_by_service.get(host_id)
        running = bool(container and container.get("state") == "running")
        status = "PASS" if running else ("NOT_TESTED" if docker_unavailable else "FAIL")
        observed = (f"state={container.get('state')}, health={container.get('health') or 'no health status'}"
                    if container else (ps["stderr"] or "container not present in docker compose ps output"))
        check = _check(f"service-up-{host_id}", f"{host_id} is running", "service_up", status,
                       "container state is running", observed)
        check["evidence"] = evidence_path
        service_checks.append(check)
        checks.append(check)

    for host in hosts:
        host_id = host["id"]
        if not container_by_service.get(host_id) or container_by_service[host_id].get("state") != "running":
            continue
        resolved = component_by_id[host_id]
        component_id = resolved.get("catalogue", {}).get("id") if resolved.get("catalogue") else None
        if resolved["runtime_component"] in {"demo-api", "demo-client"}:
            result = manager.exec_in_service(
                scenario_id, host_id,
                ["python", "-c", "import json,http.server,socket,urllib.request; print('python-runtime-ok')"], timeout=10,
            )
            observed = _result_output(result)
            status = "PASS" if result["returncode"] == 0 and "python-runtime-ok" in observed else "FAIL"
            check = _check(f"dependency-{host_id}", f"{host_id} has the Python runtime", "dependency_present",
                           status, "Python standard library imports successfully", observed)
            check["evidence"] = evidence_path
            checks.append(check)
        else:
            command = _version_command(component_id or "")
            expected_version = str(resolved.get("version") or "")
            if command and expected_version:
                result = manager.exec_in_service(scenario_id, host_id, command, timeout=10)
                observed = _result_output(result)
                status = ("PASS" if result["returncode"] == 0 and
                          _version_matches(expected_version, observed, component_id or "") else "FAIL")
                check = _check(f"version-{host_id}", f"{host_id} runs the pinned {expected_version} version",
                               "version", status, expected_version, observed)
                check["evidence"] = evidence_path
                checks.append(check)

    connectivity_by_index: dict[int, dict[str, Any]] = {}
    behavior_by_index: dict[int, dict[str, Any]] = {}
    connectivity_checks: list[dict[str, Any]] = []
    behavior_checks: list[dict[str, Any]] = []
    declared_chain_checks: list[dict[str, Any]] = []
    for index, connection in enumerate(plan_connections, start=1):
        source, target = connection["from_host"], connection["to_host"]
        port = connection.get("port")
        protocol = connection.get("protocol", "tcp")
        action_refs = _action_refs_for_connection(connection, actions)
        action_ref = action_refs[0] if action_refs else None
        source_running = bool(container_by_service.get(source) and container_by_service[source].get("state") == "running")
        target_running = bool(container_by_service.get(target) and container_by_service[target].get("state") == "running")
        if protocol != "tcp" or port is None:
            connectivity_status, connectivity_observed = "NOT_TESTED", "only declared TCP service ports are probed"
        elif not source_running or not target_running:
            connectivity_status = "NOT_TESTED" if docker_unavailable else "NOT_TESTED"
            connectivity_observed = "source or target container is not running; this path was not probed"
        else:
            result = manager.probe_in_service(scenario_id, source, _tcp_probe_script(target, int(port)), timeout=10)
            connectivity_status, connectivity_observed = _probe_status(result, should_connect=True,
                                                                         docker_unavailable=docker_unavailable)
        connectivity = _check(f"connectivity-{index}", f"{source} reaches {target}:{port}", "connectivity",
                              connectivity_status, f"one TCP connection to declared service {target}:{port}",
                              connectivity_observed, action_ref)
        connectivity["evidence"] = evidence_path
        checks.append(connectivity)
        connectivity_checks.append(connectivity)
        connectivity_by_index[index] = connectivity

        resolved_target = component_by_id[target]
        target_component = resolved_target.get("catalogue", {}).get("id") if resolved_target.get("catalogue") else None
        if target_component in {"oss-nginx", "oss-httpd", "oss-postgres"} or resolved_target["runtime_component"] == "demo-api":
            if target_component == "oss-postgres":
                if target_running:
                    behavior_result = manager.exec_in_service(
                        scenario_id, target,
                        ["pg_isready", "-h", "127.0.0.1", "-p", str(int(port or 5432)), "-U", "postgres", "-d", "postgres"],
                        timeout=10,
                    )
                    behavior_observed = _result_output(behavior_result)
                    behavior_status = ("PASS" if behavior_result["returncode"] == 0 and
                                       "accepting connections" in behavior_observed else "FAIL")
                else:
                    behavior_status, behavior_observed = "NOT_TESTED", "PostgreSQL container is not running"
                expected_behavior = "pg_isready reports accepting connections"
            else:
                behavior_path = "/demo" if resolved_target["runtime_component"] == "demo-api" else "/"
                if source_running and target_running and connectivity_status == "PASS":
                    behavior_result = manager.probe_in_service(
                        scenario_id, source, _http_probe_script(target, int(port), behavior_path), timeout=10,
                    )
                    behavior_observed = _result_output(behavior_result)
                    if behavior_path == "/demo":
                        behavior_ok = (behavior_result["returncode"] == 0 and "HTTP_STATUS:200" in behavior_observed
                                       and "cr-demo-demo-ok" in behavior_observed)
                        expected_behavior = "HTTP GET /demo returns cr-demo-demo-ok"
                    else:
                        behavior_ok = behavior_result["returncode"] == 0 and "HTTP_STATUS:200" in behavior_observed
                        expected_behavior = "HTTP GET / returns status 200 from the pinned web server"
                    behavior_status = "PASS" if behavior_ok else "FAIL"
                else:
                    behavior_status, behavior_observed = "NOT_TESTED", "HTTP behavior was not probed because its path was unavailable"
                    expected_behavior = "HTTP service returns its expected benign response"
            behavior = _check(f"behavior-{index}", f"{target} returns a benign service response", "behavior",
                              behavior_status, expected_behavior, behavior_observed, action_ref)
            behavior["evidence"] = evidence_path
            checks.append(behavior)
            behavior_checks.append(behavior)
            behavior_by_index[index] = behavior

        chain_inputs = [connectivity]
        if index in behavior_by_index:
            chain_inputs.append(behavior_by_index[index])
        else:
            chain_inputs.append(_check(f"chain-unmapped-{index}", "unmapped behavior", "chain", "NOT_TESTED",
                                       "a mapped benign behavior", "no benign behavior probe exists for the target service"))
        chain_status = _aggregate(chain_inputs)
        chain = _check(f"chain-{index}", f"{source} completes the declared path to {target}", "chain",
                       chain_status, "declared TCP path and its benign service behavior pass",
                       "; ".join(check["observed"] for check in chain_inputs), action_ref)
        chain["evidence"] = evidence_path
        checks.append(chain)
        declared_chain_checks.append(chain)

    # A benign service check without an inbound connection is visible as not tested,
    # rather than disappearing from the behavior aggregate.
    connected_targets = {connection["to_host"] for connection in plan_connections if connection.get("port") is not None}
    for component in component_report["components"]:
        host_id = component["host_id"]
        runtime_component = component_by_id[host_id]["runtime_component"]
        component_id = component_by_id[host_id].get("catalogue", {}).get("id") if component_by_id[host_id].get("catalogue") else None
        has_benign_behavior = runtime_component == "demo-api" or component_id in {"oss-nginx", "oss-httpd", "oss-postgres"}
        if has_benign_behavior and host_id not in connected_targets:
            check = _check(f"behavior-{host_id}", f"{host_id} benign service behavior", "behavior", "NOT_TESTED",
                           "a declared source-to-service probe returns the expected response",
                           "no applicable host-to-service connection is declared")
            check["evidence"] = evidence_path
            checks.append(check)
            behavior_checks.append(check)

    blocked_checks: list[dict[str, Any]] = []
    for index, blocked in enumerate(plan.get("verify_blocked", []), start=1):
        source, target = blocked.get("from_host"), blocked.get("to_host")
        port = blocked.get("port")
        protocol = blocked.get("protocol", "tcp")
        source_running = bool(container_by_service.get(source) and container_by_service[source].get("state") == "running")
        target_running = bool(container_by_service.get(target) and container_by_service[target].get("state") == "running")
        if protocol != "tcp" or port is None:
            status, observed = "NOT_TESTED", "only blocked TCP paths with a declared port are probed"
        elif not source_running or not target_running:
            status, observed = "NOT_TESTED", "source or target container is not running; this path was not probed"
        else:
            # Probe the target IP, not its name: a blocked path must be proven by a real
            # TCP refusal/unreachable to the address, not by the name failing to resolve
            # (which also happens whenever there is simply no shared network).
            target_ip = manager.container_ipv4(scenario_id, target)
            if not target_ip:
                status, observed = "NOT_TESTED", (
                    "could not determine target container IP; segmentation not proven at the TCP layer")
            else:
                result = manager.probe_in_service(scenario_id, source, _tcp_probe_script(target_ip, int(port)), timeout=10)
                status, observed = _probe_status(result, should_connect=False, docker_unavailable=docker_unavailable)
                observed = f"probed {target}={target_ip}:{port} from {source}; {observed}"
        check = _check(f"segmentation-{index}", f"{source} cannot reach {target}:{port}", "segmentation", status,
                       f"TCP connection from {source} to {target}:{port} is blocked", observed)
        check["evidence"] = evidence_path
        checks.append(check)
        blocked_checks.append(check)

    # No attack is executed by this harmless validator. A mapped path provides only
    # partial evidence for its action; without that prerequisite the action is untested.
    action_step_checks: list[dict[str, Any]] = []
    action_step_status: dict[str, str] = {}
    for action in actions:
        action_id = action["id"]
        related_indexes = [index for index, connection in enumerate(plan_connections, start=1)
                           if action_id in _action_refs_for_connection(connection, actions)]
        related_connectivity = [connectivity_by_index[index] for index in related_indexes if index in connectivity_by_index]
        proven_prerequisite = any(check["status"] == "PASS" for check in related_connectivity)
        status = "PARTIAL" if proven_prerequisite else "NOT_TESTED"
        observed = ("Only benign service or connectivity prerequisites were verified; the Scenario IR action itself was not executed."
                    if proven_prerequisite else
                    "No action-specific safe behavior mapping was exercised; the Scenario IR action was not executed.")
        action_check = _check(f"action-{action_id}", f"Scenario action {action_id}: {action.get('name', action_id)}",
                              "chain", status, "action-specific behavior is executed and verified", observed, action_id)
        action_check["evidence"] = evidence_path
        checks.append(action_check)
        action_step_checks.append(action_check)
        action_step_status[action_id] = status

    env_build = _aggregate(service_checks)
    behavior_repro = _aggregate(behavior_checks)
    required_steps = [*declared_chain_checks, *action_step_checks] if actions else declared_chain_checks
    full_chain = _aggregate([{"status": env_build}, {"status": behavior_repro}, *required_steps])

    substitutes = []
    for component in component_report["components"]:
        if component.get("substitute"):
            substitutes.append({
                "service_ref": component["host_id"],
                "real": component.get("image_hint") or component["component"],
                "substitute": component["component"],
                "difference": component.get("fidelity_difference") or
                "harmless local demo behavior; it does not reproduce the original software or any vulnerability",
            })

    reproduced = [action_id for action_id, status in action_step_status.items() if status == "PASS"]
    partial = [action_id for action_id, status in action_step_status.items() if status == "PARTIAL"]
    not_reproduced = [action_id for action_id, status in action_step_status.items() if status == "FAIL"]
    not_tested = [action_id for action_id, status in action_step_status.items() if status == "NOT_TESTED"]
    report = {
        "scenario_id": scenario_id,
        "deployment_id": manager.project_name(scenario_id),
        "run_at": run_at,
        "levels": {"env_build": env_build, "behavior_repro": behavior_repro, "full_chain": full_chain},
        "level_criteria": {
            "env_build": "PASS only when every host has a service_up check with status PASS.",
            "behavior_repro": "Aggregate of the independently executed benign service behavior checks.",
            "full_chain": (
                "Weakest of env_build, behavior_repro, every declared path chain, and every Scenario IR action. "
                "An action is only PARTIAL when safe connectivity or service evidence exists; this validator does not "
                "execute attack actions. Any required NOT_TESTED or FAIL step prevents PASS."
            ),
        },
        "checks": checks,
        "fidelity": {
            "reproduced": reproduced,
            "partial": partial,
            "not_reproduced": not_reproduced,
            "not_tested": not_tested,
            "substitutes_used": substitutes,
            "summary": (
                "Evidence covers container state, pinned component versions, allowed and blocked TCP paths, and "
                "benign service responses. Scenario actions are never claimed as reproduced without action-specific evidence."
            ),
        },
    }
    schema_errors = iter_errors("validation-report", report)
    if schema_errors:
        raise RuntimeError("generated ValidationReport failed schema validation: " + "; ".join(schema_errors))
    artifact_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with _db() as db:
        db.execute("INSERT INTO validation_reports(scenario_id,run_at,report_json) VALUES(?,?,?)",
                   (scenario_id, run_at, json.dumps(report, ensure_ascii=False)))
    return report
