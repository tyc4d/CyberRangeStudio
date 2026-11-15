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
    """An exploitation step — by ATT&CK technique OR by the action's own wording.

    A report often names the exploit in the action text without a technique id, so the
    classifier's exploit-word detection is reused (exploit*/vulnerab*/injection/zero-day).
    """
    tech = str(action.get("attack_technique") or "").upper()
    if tech.startswith(_EXPLOIT_TECHNIQUES):
        return True
    from app.planner.reproducibility import _EXPLOIT_WORDS

    text = " ".join(str(action.get(k, "")) for k in ("name", "description"))
    return bool(_EXPLOIT_WORDS.search(text))


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
    host = next((h for h in ir.get("hosts", []) or []
                 if isinstance(h, dict) and h.get("id") == host_ref), None)
    ref_ids = {str(r) for r in ((host or {}).get("service_refs") or [])}
    # canonical resolution: the target host's service_refs, OR a service whose host_ref matches
    scoped = [s for s in services
              if not host_ref or s.get("host_ref") == host_ref or str(s.get("id")) in ref_ids]
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

    is_exploit = _is_exploitation(action)
    has_verifier = _proof_for_service(service) is not None

    if repro in ("not_reproducible", "needs_vm"):
        item["strategy"] = "not_executable"
        item["poc_required"] = False
        item["not_executable_reason"] = reason
        item["expected_evidence"] = "None executable in this environment — " + reason
        item["preconditions"] = []
    elif repro == "substitute_only":
        # A substitute shows limited benign behaviour; a config_check on it is the honest
        # outcome (never claimed as a real exploit). This is a distinct accepted category.
        item["strategy"] = "config_check"
        item["poc_required"] = False
        item["expected_evidence"] = (
            "Benign configuration/behaviour of the substitute service matches expected "
            "(limited fidelity; not a real exploit): " + reason
        )
        item["preconditions"] = ["substitute service deployed and reachable on the isolated network"]
    elif is_exploit and not has_verifier:
        # Reproducible real target, but no vetted SHA-pinned verifier, so a real exploit
        # cannot be run and proved. Honest: not_executable, never a silent skip that later
        # reads as success. (owner: no manufactured PASS.)
        item["strategy"] = "not_executable"
        item["poc_required"] = False
        item["not_executable_reason"] = (
            "No vetted, SHA-pinned PoC verifier is registered for this service, so a real "
            "payload cannot be executed and proved in this environment."
        )
        item["expected_evidence"] = "None executable — " + item["not_executable_reason"]
        item["preconditions"] = []
    elif is_exploit:  # reproducible + a vetted verifier exists
        item["strategy"] = "poc_exec"
        item["poc_required"] = True
        svc_name = service.get("name") if service else (item.get("service_ref") or "target service")
        item["expected_evidence"] = (
            f"Concrete exploit effect proving the vulnerability on {svc_name} "
            "(e.g. echoed command output, in-lab callback, file written, shell output). "
            "A 200/health/LLM opinion is NOT sufficient."
        )
        item["preconditions"] = ["target host deployed by this scenario and ownership-verified",
                                 "target service reachable on the isolated network",
                                 "a compatible PoC pinned by commit sha"]
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


# --- orchestration wiring (Lead integration glue; subpackage logic is owned) -------
def _load_ir(scenario_id: str) -> dict[str, Any]:
    ir = store.get(scenario_id)
    if not isinstance(ir, dict):
        raise KeyError(scenario_id)
    return ir


def _service_by_id(ir: dict[str, Any], service_ref: str | None) -> dict[str, Any] | None:
    if not service_ref:
        return None
    for s in ir.get("services", []) or []:
        if isinstance(s, dict) and s.get("id") == service_ref:
            return s
    return None


def _proof_for_service(service: dict[str, Any] | None) -> str | None:
    """Map a deployed service to a runner-owned, SHA-pinned exploit verifier.

    Returns a proof_id only for a service we have a *vetted* evidence verifier for.
    No match -> None -> the action is not executed (never a fabricated/blind run).
    """
    if not isinstance(service, dict):
        return None
    from app.poc.runner import payloads

    component = str(service.get("catalogue_component") or "")
    cves = [str(c).upper() for c in (service.get("cve") or []) if c]
    if component == "vuln-struts2-s2-045" or "CVE-2017-5638" in cves:
        return payloads.STRUTS_S2045_PROOF_ID
    return None


def discover(scenario_id: str) -> dict[str, Any]:  # m9-discovery
    ir = _load_ir(scenario_id)
    from app.poc import discovery
    from app.poc import store as poc_store

    manifest = discovery.discover(scenario_id, ir)
    poc_store.save_manifest(scenario_id, manifest)  # persist so export sees it (#12)
    return manifest


def _compose_service_ref(ir: dict[str, Any], item: dict[str, Any]) -> str:
    """Map the IR service to the ACTUAL compose/environment host id the target uses.

    The runner/guard target a deployed compose service, which the IaC generator keys by the
    environment-plan host id — NOT the IR service id. Passing the raw IR service id makes the
    guard reject a service that does not exist (#8).
    """
    ep = ir.get("environment_plan") or {}
    hosts = [h for h in (ep.get("hosts") or []) if isinstance(h, dict)]
    host_ids = {h.get("id") for h in hosts}
    svc = _service_by_id(ir, item.get("service_ref"))
    host_ref = (svc or {}).get("host_ref") or item.get("target_host_ref")
    if host_ref in host_ids:
        return str(host_ref)
    if len(hosts) == 1:
        return str(hosts[0].get("id"))
    return str(item.get("service_ref") or host_ref or "")


def _topo_order(ids: list[str], preds: dict[str, list[str]]) -> list[str]:
    idset = set(ids)
    ordered: list[str] = []
    seen: set[str] = set()

    def visit(a: str, stack: frozenset[str]) -> None:
        if a in seen or a not in idset or a in stack:
            return
        for p in preds.get(a, []):
            if p in idset:
                visit(p, stack | {a})
        if a not in seen:
            seen.add(a)
            ordered.append(a)

    for a in ids:
        visit(a, frozenset())
    return ordered


def execute(scenario_id: str, action_ids: list[str] | None = None) -> list[dict[str, Any]]:  # m9-runner
    """Run real payloads for poc_exec items that have a vetted verifier, in dependency order.

    An action with no registered runner-owned verifier is NOT executed (the plan already marks
    it not_executable; never fabricated as a PASS). A dependent whose executed predecessor did
    not PASS is BLOCKED, not run (#7). Ownership/isolation/D6 are enforced inside run_job.
    """
    ir = _load_ir(scenario_id)
    plan_obj = plan(scenario_id)
    from app.poc.runner import payloads
    from app.poc.runner.models import ExecutionRequest
    from app.poc.runner.runner import run_job

    wanted = set(action_ids) if action_ids else None
    preds = {it.get("action_id"): list(it.get("required_predecessors") or [])
             for it in plan_obj.get("items", [])}
    reqs: dict[str, ExecutionRequest] = {}
    order: list[str] = []
    for item in plan_obj.get("items", []):
        aid = item.get("action_id")
        if item.get("strategy") != "poc_exec":
            continue
        if wanted is not None and aid not in wanted:
            continue
        service = _service_by_id(ir, item.get("service_ref"))
        proof_id = _proof_for_service(service)
        if not proof_id:
            continue  # no vetted verifier -> never fabricated
        proof = payloads.KNOWN_POC_PROOFS[proof_id]
        reqs[str(aid)] = ExecutionRequest(
            action_id=str(aid), scenario_id=scenario_id,
            service_ref=_compose_service_ref(ir, item),
            target_host_ref=item.get("target_host_ref"),
            source_url=proof["source_url"], ref={}, sha256=proof["sha256"],
            exec_method=proof["exec_method"], payload=proof["payload"],
            expected_marker=proof["expected_marker"], proof_id=proof_id,
            # ALL declared predecessors, incl. ones absent from this batch (deselected /
            # not_executable / substitute) — run_job gates them within one job and marks an
            # unmet dependent BLOCKED. (R2-02/R2-04)
            required_predecessors=tuple(preds.get(str(aid), [])),
        )
        order.append(str(aid))
    if not reqs:
        return []

    # ONE job for the whole batch (shared job_id): run_job runs in dependency order, gates
    # predecessors, BLOCKs unmet dependents, persists every result, and cancel covers all
    # not-yet-started actions. Chain selects this single job and keeps every valid result.
    ordered = [reqs[aid] for aid in _topo_order(order, preds)]
    return run_job(scenario_id, ordered)


def _executions(scenario_id: str) -> list[dict[str, Any]]:
    from app.poc import store as poc_store
    return poc_store.get_runs(scenario_id)


def chain(scenario_id: str) -> dict[str, Any]:  # m9-chain
    ir = _load_ir(scenario_id)
    from app.poc import chain as chain_mod
    from app.poc import store as poc_store

    result = chain_mod.validate_chain(scenario_id, ir, plan(scenario_id), _executions(scenario_id))
    poc_store.save_chain(scenario_id, result)  # persist so export sees it (#12)
    return result


def report(scenario_id: str) -> dict[str, Any]:  # m9-chain
    ir = _load_ir(scenario_id)
    from app.poc import chain as chain_mod
    plan_obj = plan(scenario_id)
    executions = _executions(scenario_id)
    chain_obj = chain_mod.validate_chain(scenario_id, ir, plan_obj, executions)
    validation_report = None
    try:
        from app.validator import runner as v_runner
        validation_report = v_runner.get_latest_report(scenario_id)
    except Exception:
        validation_report = None
    return chain_mod.build_fidelity_report(
        scenario_id, ir, plan_obj, executions, chain_obj, validation_report=validation_report)


def export(scenario_id: str, fmt: str | None = "full") -> dict[str, Any]:  # m9-export
    _load_ir(scenario_id)  # 404 if unknown
    from app.poc import export as export_mod
    return export_mod.export(scenario_id, fmt)
