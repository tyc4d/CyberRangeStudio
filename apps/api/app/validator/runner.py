"""Harmless, plan-scoped validation checks for a local Compose PoC."""
from __future__ import annotations

import json
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
    if action_ref:
        item["action_ref"] = action_ref
    return item


def _probe(target: str, port: int, path: str | None = None) -> list[str]:
    if path:
        script = (
            "import urllib.request; "
            f"r=urllib.request.urlopen('http://{target}:{port}{path}', timeout=3); "
            "body=r.read().decode('utf-8'); print(body)"
        )
    else:
        script = (
            "import socket; "
            f"s=socket.create_connection(('{target}', {port}), timeout=3); "
            "s.close(); print('tcp-connect-ok')"
        )
    return ["python", "-c", script]


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

    checks: list[dict[str, Any]] = list(service_checks)
    dependency_checks: list[dict[str, Any]] = []
    for host in hosts:
        host_id = host["id"]
        if not container_by_service.get(host_id) or container_by_service[host_id].get("state") != "running":
            result = {"returncode": 127 if docker_unavailable else 125, "stdout": "", "stderr": "service is not running"}
        else:
            result = manager.exec_in_service(
                scenario_id, host_id,
                ["python", "-c", "import json,http.server,socket,urllib.request; print('python-runtime-ok')"], timeout=10,
            )
        not_tested = result["returncode"] == 127 and docker_unavailable
        check = _check(f"dependency-{host_id}", f"{host_id} has the Python runtime", "dependency_present",
                       _status(result["returncode"], not_tested), "Python standard library imports successfully",
                       result["stdout"].strip() or result["stderr"].strip())
        check["evidence"] = evidence_path
        checks.append(check)
        dependency_checks.append(check)

    connectivity_checks: list[dict[str, Any]] = []
    behavior_checks: list[dict[str, Any]] = []
    chain_checks: list[dict[str, Any]] = []
    for index, connection in enumerate(plan_connections, start=1):
        source, target = connection["from_host"], connection["to_host"]
        port = connection.get("port")
        protocol = connection.get("protocol", "tcp")
        if protocol != "tcp" or port is None:
            status, observed = "NOT_TESTED", "only declared TCP service ports are probed"
        elif not container_by_service.get(source) or container_by_service[source].get("state") != "running" or not container_by_service.get(target) or container_by_service[target].get("state") != "running":
            status = "NOT_TESTED" if docker_unavailable else "FAIL"
            observed = "source or target container is not running"
        else:
            result = manager.exec_in_service(scenario_id, source, _probe(target, int(port)), timeout=10)
            status = _status(result["returncode"], result["returncode"] == 127 and docker_unavailable)
            observed = result["stdout"].strip() or result["stderr"].strip()
        check = _check(f"connectivity-{index}", f"{source} reaches {target}:{port}", "connectivity", status,
                       f"one TCP connection to declared service {target}:{port}", observed)
        check["evidence"] = evidence_path
        checks.append(check)
        connectivity_checks.append(check)

        if component_by_id.get(target) == "demo-api":
            if status != "PASS":
                behavior_status, behavior_observed = ("NOT_TESTED" if status == "NOT_TESTED" else "FAIL"), "connectivity prerequisite did not pass"
                chain_status, chain_observed = "NOT_TESTED", "connectivity prerequisite did not pass"
            else:
                behavior_result = manager.exec_in_service(scenario_id, source, _probe(target, int(port), "/demo"), timeout=10)
                expected_body = "cr-demo-demo-ok"
                behavior_ok = behavior_result["returncode"] == 0 and expected_body in behavior_result["stdout"]
                behavior_status = "PASS" if behavior_ok else "FAIL"
                behavior_observed = behavior_result["stdout"].strip() or behavior_result["stderr"].strip()
                chain_result = behavior_result
                chain_status = "PASS" if behavior_ok else "FAIL"
                chain_observed = f"step 1 connectivity PASS; step 2 harmless GET /demo: {behavior_observed}"
            behavior = _check(f"behavior-{index}", f"{target} returns the benign demo response", "behavior",
                              behavior_status, "HTTP GET /demo returns cr-demo-demo-ok", behavior_observed)
            behavior["evidence"] = evidence_path
            checks.append(behavior)
            behavior_checks.append(behavior)
            chain = _check(f"chain-{index}", f"{source} completes the declared demo chain to {target}", "chain",
                           chain_status, "TCP connect followed by one benign GET /demo", chain_observed)
            chain["evidence"] = evidence_path
            checks.append(chain)
            chain_checks.append(chain)
        else:
            chain = _check(f"chain-{index}", f"declared path {source} to {target}", "chain", "NOT_TESTED",
                           "a mapped harmless demonstration behavior", "no benign behavior mapping exists for the target component")
            chain["evidence"] = evidence_path
            checks.append(chain)
            chain_checks.append(chain)

    demo_targets = {c["host_id"] for c in component_report["components"] if c["component"] == "demo-api"}
    connected_demo_targets = {connection["to_host"] for connection in plan_connections
                              if component_by_id.get(connection["to_host"]) == "demo-api" and connection.get("port") is not None}
    for demo_target in sorted(demo_targets - connected_demo_targets):
        check = _check(f"behavior-{demo_target}", f"{demo_target} benign behavior", "behavior", "NOT_TESTED",
                       "a declared TCP connection from another host followed by GET /demo",
                       "no applicable host-to-service connection is declared")
        check["evidence"] = evidence_path
        checks.append(check)
        behavior_checks.append(check)

    substitutes = []
    for component in component_report["components"]:
        if component.get("substitute"):
            substitutes.append({"service_ref": component["host_id"], "real": component.get("image_hint") or component["component"],
                                "substitute": component["component"],
                                "difference": "harmless pinned Python demo image; it does not reproduce the original software or any vulnerability"})
    report = {
        "scenario_id": scenario_id,
        "deployment_id": manager.project_name(scenario_id),
        "run_at": run_at,
        "levels": {
            "env_build": _aggregate(service_checks),
            "behavior_repro": _aggregate(behavior_checks),
            "full_chain": _aggregate(chain_checks),
        },
        "checks": checks,
        "fidelity": {
            "reproduced": [], "partial": [], "not_reproduced": [],
            "not_tested": [action.get("id") for action in ir.get("actions", []) if isinstance(action, dict) and action.get("id")],
            "substitutes_used": substitutes,
            "summary": "Checks are limited to service state, declared TCP paths, Python runtime imports, and a harmless local HTTP demo response.",
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

