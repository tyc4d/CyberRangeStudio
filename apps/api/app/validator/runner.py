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
                            "expected": _zh(expected), "observed": _zh(observed)}
    if action_ref is not None:
        item["action_ref"] = action_ref
    return item


_REPORT_TRANSLATIONS = {
    "container state is running": "容器狀態為執行中",
    "container not present in docker compose ps output": "Docker Compose 狀態清單中沒有此容器",
    "no health status": "沒有健康狀態資料",
    "only declared TCP service ports are probed": "僅探測已宣告的 TCP 服務連接埠",
    "source or target container is not running; this path was not probed": "來源或目標容器未執行，因此未探測此路徑",
    "only blocked TCP paths with a declared port are probed": "僅探測已宣告連接埠的封鎖 TCP 路徑",
    "could not determine target container IP; segmentation not proven at the TCP layer": "無法取得目標容器 IP，因此未能以 TCP 證明網路隔離",
    "PostgreSQL container is not running": "PostgreSQL 容器未執行",
    "HTTP behavior was not probed because its path was unavailable": "因路徑不可用，未探測 HTTP 行為",
    "no benign behavior probe exists for the target service": "目標服務沒有適用的無害行為探測",
    "no applicable host-to-service connection is declared": "未宣告適用的主機至服務連線",
    "a mapped benign behavior": "已對應的無害行為",
    "a declared source-to-service probe returns the expected response": "已宣告的來源至服務探測回傳預期結果",
    "Python standard library imports successfully": "Python 標準函式庫可成功載入",
    "pg_isready reports accepting connections": "pg_isready 回報可接受連線",
    "HTTP service returns its expected benign response": "HTTP 服務回傳預期的無害回應",
    "HTTP GET /demo returns cr-demo-demo-ok": "HTTP GET /demo 回傳 cr-demo-demo-ok",
    "HTTP GET / returns status 200 from the pinned web server": "HTTP GET / 從指定版本的網頁伺服器回傳狀態 200",
    "probe command exited with status": "探測指令結束狀態",
    "target name did not resolve; inconclusive": "目標名稱無法解析，結果不具判定性",
    "Scenario IR action": "情境 IR 動作",
    "Only benign service or connectivity prerequisites were verified; the Scenario IR action itself was not executed.": "僅確認無害服務或連線前置條件；情境 IR 動作未執行（not executed）。",
    "No action-specific safe behavior mapping was exercised; the Scenario IR action was not executed.": "未測試該動作專屬的安全行為對應；情境 IR 動作未執行（not executed）。",
    "action-specific behavior is executed and verified": "已執行並驗證該動作專屬行為",
    "unmapped behavior": "未對應的行為",
    "declared TCP path and its benign service behavior pass": "宣告的 TCP 路徑及其無害服務行為皆通過",
    "one TCP connection to declared service": "對宣告服務建立一條 TCP 連線",
    "TCP connection from": "TCP 連線來源",
    "is blocked": "遭封鎖",
    "harmless Python demo behavior; does not reproduce the named component or its vulnerabilities":
        "無害的 Python 示範行為；不會重現指定元件或其弱點",
    "harmless local demo behavior; it does not reproduce the original software or any vulnerability":
        "無害的本機示範行為；不會重現原始軟體或任何弱點",
}


def _zh(value: str) -> str:
    """Localize report prose and keep host filesystem paths out of evidence text."""
    text = str(value)
    for source in sorted(_REPORT_TRANSLATIONS, key=len, reverse=True):
        translation = _REPORT_TRANSLATIONS[source]
        text = text.replace(source, translation)
    text = re.sub(r"(?<![A-Za-z0-9])/(?:home|tmp|var|opt|srv|mnt|root|Users|private|etc|workspace)(?:/[^\s'\"]*)?",
                  "[伺服器端路徑]", text)
    text = text.replace("CONNECTED", "已連線（CONNECTED）").replace("BLOCKED:", "連線遭拒（BLOCKED:）：")
    text = text.replace("UNRESOLVED:", "名稱無法解析（UNRESOLVED）：").replace("NO_HTTP_RESPONSE:", "無 HTTP 回應（NO_HTTP_RESPONSE）：")
    text = text.replace("HTTP_STATUS:", "HTTP 狀態（HTTP_STATUS）：").replace("BODY:", "回應內容（BODY）：")
    text = text.replace("accepting connections", "正在接受連線")
    text = text.replace("python-runtime-ok", "Python 執行環境正常")
    return text


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


def _host_ref_eq(target_ref: Any, host_id: Any) -> bool:
    """Loose equality between an action's target_host_ref and a connection host id."""
    if not isinstance(target_ref, str) or not isinstance(host_id, str):
        return False
    a, b = target_ref.strip(), host_id.strip()
    if not a or not b:
        return False
    # Tolerate a "host:"/prefix form while still requiring the id to match.
    return a == b or a.split(":")[-1] == b or b.split(":")[-1] == a


def _explicit_action_refs(connection: dict[str, Any], actions: list[dict[str, Any]]) -> list[str]:
    """Actions for which this connection is a *proven connectivity prerequisite*.

    Two conditions, BOTH required (R3 / reviewer P1):
      1. the action id is explicitly named in the connection's reason, AND
      2. the action's target_host_ref resolves to the connection's to_host.

    Condition 1 alone is not enough: the real planner writes one reason that lists
    EVERY action needing a given host (e.g. "Scenario action(s) a1, a2, a3, a4
    require access to ..."), so id-in-reason matches all of them. Condition 2 ties
    a path to the action that actually targets that host. An action with no
    target_host_ref cannot be attributed to any single path, so it matches no
    connection here and is reported NOT_TESTED rather than an over-claimed PARTIAL.
    """
    reason = str(connection.get("reason", ""))
    to_host = connection.get("to_host")
    refs: list[str] = []
    for action in actions:
        action_id = action.get("id")
        if not isinstance(action_id, str):
            continue
        id_named = re.search(rf"(?<![A-Za-z0-9_-]){re.escape(action_id)}(?![A-Za-z0-9_-])", reason)
        if id_named and _host_ref_eq(action.get("target_host_ref"), to_host):
            refs.append(action_id)
    return refs


def _action_refs_for_connection(connection: dict[str, Any], actions: list[dict[str, Any]]) -> list[str]:
    """Broader labeling: explicit id reference, else a shared target host.

    This only drives a display `action_ref` on connectivity/chain checks; it must
    never be used to decide an action's reproduction status (use the explicit form).
    """
    refs = list(_explicit_action_refs(connection, actions))
    for action in actions:
        action_id = action.get("id")
        if isinstance(action_id, str) and action_id not in refs \
                and action.get("target_host_ref") == connection.get("to_host"):
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


def _segmentation_status(result: dict[str, Any]) -> tuple[str, str]:
    """Judge a "must be blocked" probe.

    Segmentation is proven only by genuine network unreachability (no route between
    the isolated networks): ENETUNREACH / EHOSTUNREACH / a timeout. A *refused*
    connection (ConnectionRefusedError) means the host WAS reachable and only the
    port was closed — that is evidence the two endpoints share a network, not that
    they are segmented, so it must never pass a segmentation check (R6).
    """
    observed = _result_output(result)
    if "CONNECTED" in observed:
        return "FAIL", observed
    if "UNRESOLVED:" in observed:
        return "NOT_TESTED", observed + " (target name did not resolve; inconclusive)"
    if "BLOCKED:" in observed:
        unreachable = any(token in observed for token in (
            "Network is unreachable", "No route to host", "ENETUNREACH", "EHOSTUNREACH",
            "timed out", "TimeoutError"))
        if unreachable:
            return "PASS", observed
        if "ConnectionRefusedError" in observed or "Connection refused" in observed:
            return "NOT_TESTED", observed + (
                " (connection was refused, not unreachable: the host is on a shared "
                "network with only the port closed; segmentation is not proven)")
        # Some other OSError: reachable-but-blocked is ambiguous, do not claim PASS.
        return "NOT_TESTED", observed + " (blocked by a non-routing error; segmentation not proven)"
    return "NOT_TESTED", observed


def _probe_blocked_all_addresses(scenario_id: str, source: str, target: str, port: int) -> tuple[str, str]:
    """Prove a "must be blocked" path against ALL of the target's plan addresses.

    Segmentation means the source can reach the target on NO network. A single-IP
    probe is insufficient for a multi-homed target, so every non-edge plan-network
    address is probed and the worst (least-segmented) outcome wins (reviewer F1).
    """
    addresses = manager.container_ipv4_addresses(scenario_id, target)
    if not addresses:
        return "NOT_TESTED", "could not determine target container IP; segmentation not proven at the TCP layer"
    per_net: list[str] = []
    statuses: list[str] = []
    for item in addresses:
        ip = item["ip"]
        result = manager.probe_in_service(scenario_id, source, _tcp_probe_script(ip, port), timeout=10)
        st, obs = _segmentation_status(result)
        statuses.append(st)
        per_net.append(f"{item['network']}={ip}:{port} -> {st}: {obs}")
    if "FAIL" in statuses:
        status = "FAIL"
    elif "NOT_TESTED" in statuses:
        status = "NOT_TESTED"
    elif statuses and all(st == "PASS" for st in statuses):
        status = "PASS"
    else:
        status = "NOT_TESTED"
    observed = (f"probed {target} on {len(addresses)} plan network(s) from {source}; " + " | ".join(per_net))
    return status, observed


def _build_substitutes(components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build fidelity.substitutes_used, naming the ORIGINAL software the source meant.

    Module 5 (scenario-eng) records `substitute_for` on a host when a real catalogue
    image stands in for other software the source named (e.g. nginx for IIS). The
    report must show "以 <substitute> 頂替 <real>" with that original name as `real`,
    not the stand-in's own image id. Falls back to image_hint/component when no
    original is recorded (the plain harmless-demo substitute case).
    """
    out: list[dict[str, Any]] = []
    for component in components:
        if not (component.get("substitute") or component.get("substitute_for")):
            continue
        real = component.get("substitute_for") or component.get("image_hint") or component["component"]
        difference = component.get("fidelity_difference") or (
            f"以 {component['component']} 頂替 {real}；不會重現原始軟體或其弱點"
            if component.get("substitute_for") else
            "harmless local demo behavior; it does not reproduce the original software or any vulnerability")
        entry = {
            "service_ref": component["host_id"],
            "real": real,
            "substitute": component["component"],
            "difference": difference,
        }
        if component.get("substitute_basis"):
            entry["difference"] = f"{difference}（依據：{component['substitute_basis']}）"
        out.append(entry)
    return out


def _vm_guest_readonly(scenario_id: str, host_id: str) -> dict[str, Any]:
    """Read Windows identity/version through the libvirt guest agent, never run actions."""
    state = manager.vm_status(scenario_id, host_id)
    if state.get("state") != "running":
        return {"returncode": 2, "stdout": "", "stderr": f"VM hypervisor state={state.get('state')}"}
    virsh = __import__("shutil").which("virsh")
    if not virsh:
        return {"returncode": 127, "stdout": "", "stderr": "virsh executable is not installed"}
    # Guest-exec invokes only fixed read-only PowerShell commands. Credentials are
    # intentionally not accepted or included in command arguments/audit data.
    command = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
               "$os=Get-CimInstance Win32_OperatingSystem; $cs=Get-CimInstance Win32_ComputerSystem; "
               "[pscustomobject]@{Version=$os.Version;Caption=$os.Caption;Hostname=$cs.Name}|ConvertTo-Json -Compress"]
    result = manager._vm_run([virsh, "-c", manager.VM_URI, "qemu-agent-command",
                              manager._vm_identity(scenario_id, host_id),
                              json.dumps({"execute": "guest-exec", "arguments": {
                                  "path": command[0], "arg": command[1:], "capture-output": True}})], timeout=15)
    return result


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
    evidence_path = f"validation-runs/{scenario_id}/{run_id}.json"

    vm_hosts = [host for host in plan.get("hosts", []) if host.get("runtime") == "vm"]
    ps = manager.compose_ps_result(scenario_id) if not vm_hosts else {"returncode": 0, "stdout": "", "stderr": ""}
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
        if host.get("runtime") == "vm":
            state = manager.vm_status(scenario_id, host_id)
            running = state.get("state") == "running"
            status = "PASS" if running else "NOT_TESTED" if state.get("state") in {"unavailable", "absent", "unverified"} else "FAIL"
            observed = f"VM hypervisor state={state.get('state')}"
            check = _check(f"service-up-{host_id}", f"{host_id} VM 執行狀態", "service_up", status,
                           "hypervisor reports VM running", observed)
            check["evidence"] = evidence_path
            service_checks.append(check)
            checks.append(check)
            continue
        container = container_by_service.get(host_id)
        running = bool(container and container.get("state") == "running")
        health = (container.get("health") or "").strip().lower() if container else ""
        if not running:
            status = "NOT_TESTED" if docker_unavailable else "FAIL"
        elif health == "unhealthy":
            # Running but failing its own healthcheck is not a stood-up service (R7).
            status = "FAIL"
        elif health == "starting":
            # Not yet ready; do not claim the environment is built.
            status = "NOT_TESTED"
        else:
            status = "PASS"
        observed = (f"容器狀態={container.get('state')}，健康狀態={container.get('health') or '沒有健康狀態資料'}"
                    if container else "Docker Compose 狀態清單中沒有此容器")
        check = _check(f"service-up-{host_id}", f"{host_id} 服務執行狀態", "service_up", status,
                       "container state is running", observed)
        check["evidence"] = evidence_path
        service_checks.append(check)
        checks.append(check)

    for host in hosts:
        host_id = host["id"]
        if host.get("runtime") == "vm":
            state = manager.vm_status(scenario_id, host_id)
            if state.get("state") != "running":
                check = _check(f"os-{host_id}", f"{host_id} Windows 版本與主機名稱", "os_identity", "NOT_TESTED",
                               "read-only Windows version and hostname", f"VM state={state.get('state')}")
            else:
                result = _vm_guest_readonly(scenario_id, host_id)
                observed = _result_output(result)
                status = "PASS" if result.get("returncode") == 0 and "Hostname" in observed and "Version" in observed else "NOT_TESTED"
                check = _check(f"os-{host_id}", f"{host_id} Windows 版本與主機名稱", "os_identity", status,
                               "read-only Windows version and hostname", observed)
            check["evidence"] = evidence_path
            checks.append(check)
            continue
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
            check = _check(f"dependency-{host_id}", f"{host_id} 具備 Python 執行環境", "dependency_present",
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
                check = _check(f"version-{host_id}", f"{host_id} 執行指定版本 {expected_version}",
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
        source_host = next((h for h in hosts if h["id"] == source), {})
        target_host = next((h for h in hosts if h["id"] == target), {})
        source_vm = source_host.get("runtime") == "vm"
        target_vm = target_host.get("runtime") == "vm"
        source_running = (manager.vm_status(scenario_id, source).get("state") == "running" if source_vm else
                          bool(container_by_service.get(source) and container_by_service[source].get("state") == "running"))
        target_running = (manager.vm_status(scenario_id, target).get("state") == "running" if target_vm else
                          bool(container_by_service.get(target) and container_by_service[target].get("state") == "running"))
        if protocol != "tcp" or port is None:
            connectivity_status, connectivity_observed = "NOT_TESTED", "only declared TCP service ports are probed"
        elif not source_running or not target_running:
            connectivity_status = "NOT_TESTED" if docker_unavailable else "NOT_TESTED"
            connectivity_observed = "source or target container is not running; this path was not probed"
        elif source_vm or target_vm:
            # Host-only addressing is not currently persisted by the VM adapter.
            # Do not substitute the validator host or claim an unexecuted probe.
            connectivity_status, connectivity_observed = "NOT_TESTED", "VM TCP probe requires configured isolated guest addressing"
        else:
            result = manager.probe_in_service(scenario_id, source, _tcp_probe_script(target, int(port)), timeout=10)
            connectivity_status, connectivity_observed = _probe_status(result, should_connect=True,
                                                                         docker_unavailable=docker_unavailable)
        connectivity = _check(f"connectivity-{index}", f"{source} 可連線至 {target}:{port}", "connectivity",
                              connectivity_status, f"one TCP connection to declared service {target}:{port}",
                              connectivity_observed, action_ref)
        connectivity["evidence"] = evidence_path
        checks.append(connectivity)
        connectivity_checks.append(connectivity)
        connectivity_by_index[index] = connectivity

        resolved_target = component_by_id[target]
        target_component = resolved_target.get("catalogue", {}).get("id") if resolved_target.get("catalogue") else None
        if target_vm:
            behavior = _check(f"behavior-{index}", f"{target} 服務行為", "behavior", "NOT_TESTED",
                              "mapped safe behavior probe", "Windows service behavior mapping is not configured", action_ref)
            behavior["evidence"] = evidence_path
            checks.append(behavior)
            behavior_checks.append(behavior)
            behavior_by_index[index] = behavior
        elif target_component in {"oss-nginx", "oss-httpd", "oss-postgres"} or resolved_target["runtime_component"] == "demo-api":
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
            behavior = _check(f"behavior-{index}", f"{target} 回傳無害服務回應", "behavior",
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
        chain = _check(f"chain-{index}", f"{source} 完成至 {target} 的宣告路徑", "chain",
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
            check = _check(f"behavior-{host_id}", f"{host_id} 無害服務行為", "behavior", "NOT_TESTED",
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
            #
            # A multi-homed target has one IP per plan network. Probing a single IP can
            # false-PASS: the source may be unable to reach the probed address yet able to
            # reach the target on another network (reviewer F1). So probe EVERY non-edge
            # plan-network address of the target and aggregate conservatively:
            #   reachable on any network  -> FAIL      (not segmented)
            #   refused on any network    -> NOT_TESTED (host reachable, port closed; not proven)
            #   unreachable on all        -> PASS       (genuinely segmented everywhere)
            status, observed = _probe_blocked_all_addresses(scenario_id, source, target, int(port))
        check = _check(f"segmentation-{index}", f"{source} 無法連線至 {target}:{port}", "segmentation", status,
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
                           if action_id in _explicit_action_refs(connection, actions)]
        related_connectivity = [connectivity_by_index[index] for index in related_indexes if index in connectivity_by_index]
        proven_prerequisite = any(check["status"] == "PASS" for check in related_connectivity)
        status = "PARTIAL" if proven_prerequisite else "NOT_TESTED"
        observed = ("Only benign service or connectivity prerequisites were verified; the Scenario IR action itself was not executed."
                    if proven_prerequisite else
                    "No action-specific safe behavior mapping was exercised; the Scenario IR action was not executed.")
        action_check = _check(f"action-{action_id}", f"情境動作 {action_id}：{action.get('name', action_id)}",
                              "chain", status, "action-specific behavior is executed and verified", observed, action_id)
        action_check["evidence"] = evidence_path
        checks.append(action_check)
        action_step_checks.append(action_check)
        action_step_status[action_id] = status

    env_build = _aggregate(service_checks)
    behavior_repro = _aggregate(behavior_checks)
    # This benign validator never executes an attack action, so a "full chain"
    # verdict is driven by attack-step evidence (action_step_checks), which can be
    # at most PARTIAL. Declared TCP "chain" checks are plumbing (connectivity +
    # health) and may only pull the verdict DOWN, never prop it up to PASS.
    # When the scenario declares no attack actions, there is no chain to reproduce,
    # so full_chain is NOT_TESTED rather than inheriting a PASS from plumbing (R1).
    if actions:
        full_chain = _aggregate([{"status": env_build}, {"status": behavior_repro},
                                 *declared_chain_checks, *action_step_checks])
    elif declared_chain_checks and any(c["status"] == "FAIL" for c in declared_chain_checks):
        full_chain = "FAIL"
    else:
        full_chain = "NOT_TESTED"
    # Structural guarantee: without executed attack steps a full chain can never be
    # claimed reproduced. Keep this even if the aggregate logic changes later.
    if full_chain == "PASS":
        full_chain = "PARTIAL"

    substitutes = _build_substitutes(component_report["components"])

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
            "env_build": "僅當每個主機的 service_up 檢查皆為 PASS 時才判定 PASS。",
            "behavior_repro": "彙總各項獨立執行的無害服務行為檢查。",
            "full_chain": (
                "取 env_build、behavior_repro、每條宣告路徑及每個情境 IR 動作（every Scenario IR action）中的最低狀態。"
                "只有存在安全連線或服務證據時，動作才標為 PARTIAL；此驗證器不會執行攻擊動作。"
                "任何必要步驟為 NOT_TESTED 或 FAIL 時，整體不可判定為 PASS。"
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
                "佐證涵蓋容器狀態、指定元件版本、允許與封鎖的 TCP 路徑及無害服務回應。"
                "沒有動作專屬佐證時，不會宣稱已重現情境動作。"
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
