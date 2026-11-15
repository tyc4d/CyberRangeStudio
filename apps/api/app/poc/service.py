"""Module 9 orchestration.

Only ``plan()`` is implemented here (it is the dependency for every other worker).
``discover``/``execute``/``chain``/``report``/``export`` are owned by m9-discovery,
m9-runner, m9-chain and m9-export respectively and raise NotImplementedError until filled.

plan() turns the Scenario IR into a ValidationPlan using the existing, conservative
planner.reproducibility.classify_action — it never claims execution and never upgrades a
non-reproducible action to an executable one. Mapping (CONTRACT §Data shapes):

    reproducible + exploitation step -> poc_exec     (real payload required)
    reproducible + non-exploit step  -> config_check (benign state/behaviour check)
    substitute_only                  -> config_check (substitute shows only limited behaviour)
    needs_vm                         -> not_executable (VM image we lack)
    not_reproducible                 -> not_executable

not_executable items carry the classifier's reason and, per the owner's standing ruling,
NEVER later become PASS.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app import store
from app.planner.reproducibility import classify_action

# Attack techniques that denote an exploitation step (shared with the planner).
_EXPLOIT_TECHNIQUES = ("T1190", "T1203", "T1210", "T1068", "T1212", "T1211")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_exploitation(action: dict[str, Any]) -> bool:
    tech = str(action.get("attack_technique") or "").upper()
    return tech.startswith(_EXPLOIT_TECHNIQUES)


def _predecessors(action_id: str, ir: dict[str, Any]) -> list[str]:
    """Actions this one depends on: dependency relations ending at action_id.

    Only `dependency` relations count as required predecessors; `temporal` is mere
    observed order and must not be treated as a hard dependency (planner's rule).
    """
    preds: list[str] = []
    for rel in ir.get("relations", []) or []:
        if not isinstance(rel, dict):
            continue
        if rel.get("kind") == "dependency" and rel.get("to_action") == action_id:
            frm = rel.get("from_action")
            if frm and frm not in preds:
                preds.append(str(frm))
    return preds


def _service_for(action: dict[str, Any], ir: dict[str, Any]) -> dict[str, Any] | None:
    host_ref = action.get("target_host_ref")
    services = [s for s in ir.get("services", []) or [] if isinstance(s, dict)]
    scoped = [s for s in services if not host_ref or s.get("host_ref") == host_ref]
    if not scoped:
        return None
    # Prefer a service that carries a CVE / is a substitute marker, else the first.
    for s in scoped:
        if s.get("cve"):
            return s
    return scoped[0]


def _build_item(action: dict[str, Any], ir: dict[str, Any]) -> dict[str, Any]:
    repro, reason = classify_action(action, ir)
    service = _service_for(action, ir)
    cve_list = service.get("cve") if service else None
    cve = cve_list[0] if isinstance(cve_list, list) and cve_list else None

    item: dict[str, Any] = {
        "action_id": str(action.get("id")),
        "required_predecessors": _predecessors(str(action.get("id")), ir),
        "preconditions": [],
    }
    if action.get("attack_technique"):
        item["attack_technique"] = str(action.get("attack_technique"))
    if action.get("target_host_ref"):
        item["target_host_ref"] = str(action.get("target_host_ref"))
    if service and service.get("id"):
        item["service_ref"] = str(service.get("id"))
    if cve:
        item["cve"] = cve

    if repro in ("not_reproducible", "needs_vm"):
        item["strategy"] = "not_executable"
        item["poc_required"] = False
        item["not_executable_reason"] = reason
        item["expected_evidence"] = (
            "None executable in this environment — " + reason
        )
        item["preconditions"] = []
    elif repro == "substitute_only":
        item["strategy"] = "config_check"
        item["poc_required"] = False
        item["expected_evidence"] = (
            "Benign configuration/behaviour of the substitute service matches expected "
            "(limited fidelity; not a real exploit): " + reason
        )
        item["preconditions"] = ["substitute service deployed and reachable on the isolated network"]
    else:  # reproducible
        if _is_exploitation(action):
            item["strategy"] = "poc_exec"
            item["poc_required"] = True
            svc_name = service.get("name") if service else (item.get("service_ref") or "target service")
            item["expected_evidence"] = (
                f"Concrete exploit effect proving the vulnerability on {svc_name} "
                "(e.g. echoed command output, in-lab callback, file written, shell output). "
                "A 200/health/LLM opinion is NOT sufficient."
            )
            pre = ["target host deployed by this scenario and ownership-verified",
                   "target service reachable on the isolated network",
                   "a compatible PoC pinned by commit sha"]
            item["preconditions"] = pre
        else:
            item["strategy"] = "config_check"
            item["poc_required"] = False
            item["expected_evidence"] = (
                "Benign step-specific check against the pinned component confirms the "
                "expected state/behaviour (not an exploit): " + reason
            )
            item["preconditions"] = ["target service deployed and reachable on the isolated network"]

    return item


def plan(scenario_id: str) -> dict[str, Any]:
    """Build and persist a ValidationPlan for a stored scenario. Real logic, no stub.

    Raises KeyError if the scenario is unknown.
    """
    ir = store.get(scenario_id)
    if not isinstance(ir, dict):
        raise KeyError(scenario_id)
    actions = [a for a in ir.get("actions", []) or [] if isinstance(a, dict) and a.get("id")]
    items = [_build_item(a, ir) for a in actions]
    plan_obj = {
        "scenario_id": scenario_id,
        "generated_at": _now(),
        "items": items,
    }
    # Persist for the GUI/other stages; import locally to avoid a hard import cycle at module load.
    from app.poc import store as poc_store

    poc_store.save_plan(scenario_id, plan_obj)
    return plan_obj


# --- stubs owned by other workers ------------------------------------------
def discover(scenario_id: str) -> dict[str, Any]:  # m9-discovery
    raise NotImplementedError("poc.discovery owns discover()")


def execute(scenario_id: str, action_ids: list[str] | None = None) -> list[dict[str, Any]]:  # m9-runner
    raise NotImplementedError("poc.runner owns execute()")


def chain(scenario_id: str) -> dict[str, Any]:  # m9-chain
    raise NotImplementedError("poc.chain owns chain()")


def report(scenario_id: str) -> dict[str, Any]:  # m9-chain
    raise NotImplementedError("poc.chain owns report()")


def export(scenario_id: str) -> dict[str, Any]:  # m9-export
    raise NotImplementedError("poc.export owns export()")
