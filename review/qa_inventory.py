"""Independent, offline Inventory QA. Prints evidence; never calls an LLM or deploys.

Run from the worktree root:
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=packages/contracts \
  /home/tyc4d/cr-project/.venv/bin/python review/qa_inventory.py

An invariant FAIL is an observed product gap, not a harness crash.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api"))

from app.cti.analysis import _build_ir
from app.cti.missing import calculate_missing_items
from app.cti.parser import parse_source
from app.planner.catalogue import load_components
from app.planner.dependencies import plan_dependencies
from app.planner.inventory import inventory_summary, resolve
from app.planner.topology import build_environment_plan

RESULTS = {}


def check(name, passed, evidence):
    RESULTS[name] = {"result": "PASS" if passed else "FAIL", "evidence": evidence}


def ir(services, *, action=None, role="web server", host_extra=None):
    host = {"id": "h1", "role": role, "source": "llm", "epistemic_status": "supported"}
    host.update(host_extra or {})
    return {"schema_version": "1.0", "id": "scn_qa", "name": "offline QA",
            "provenance": {"input_kind": "text", "input_sha256": "0" * 64},
            "hosts": [host], "services": [
                {"id": f"s{i}", "host_ref": "h1", "source": "llm", "epistemic_status": "supported", **s}
                for i, s in enumerate(services, 1)],
            "actions": [action] if action else [], "relations": [], "evidence": [],
            "target_context": {"host_refs": ["h1"]}, "missing_items": []}


def build(source, services):
    units, parsed = parse_source("text", source)
    model = {"actions": [], "relations": [], "target_context": {"hosts": [], "services": services}}
    return _build_ir(copy.deepcopy(model), input_kind="text", content=source, source_name="offline QA",
                     units=units, parsed_source=parsed, method="single_pass", name="offline QA")


def summarize(planned):
    service_keys = ("id", "name", "host_ref", "catalogue_component", "is_substitute", "substitute_of",
                    "version", "deployed_version", "version_basis", "cve", "reproduces_cve", "tier",
                    "epistemic_status", "field_sources", "no_component", "not_reproducible", "placement")
    return {"hosts": planned["hosts"],
            "services": [{k: s[k] for k in service_keys if k in s} for s in planned["services"]],
            "actions": [{k: a[k] for k in ("id", "name", "target_host_ref", "reproducibility",
                        "reproducibility_reason") if k in a} for a in planned["actions"]],
            "version_items": [m for m in planned["missing_items"] if m.get("category") == "version"],
            "environment_hosts": build_environment_plan(planned)["hosts"]}


def main():
    for product, version, cves, expected in [
        ("VMware Horizon", None, ["CVE-2021-44228"], ("have", "vuln-log4shell-solr", True, "substituted", False)),
        ("Log4j", None, ["CVE-2021-44228"], ("have", "vuln-log4shell-solr", True, "substituted", False)),
        ("Log4Shell", None, None, ("have", "vuln-log4shell-solr", True, "substituted", False)),
        ("VMware Horizon", "8.3", None, ("unavailable", None, False, "stated", False)),
        ("Active Directory", None, None, ("unavailable", None, False, "assumed", False)),
        ("Citrix ADC", None, None, ("unavailable", None, False, "assumed", False)),
        ("nginx", "1.31.8", None, ("have", "oss-nginx", False, "stated", False)),
        ("nginx", "1.24", None, ("have", "oss-nginx", False, "substituted", False)),
        ("Windows Server", None, None, ("obtainable", None, False, "assumed", True)),
        ("Windows Server", "2019", None, ("obtainable", "os-windows-server-2019-eval", False, "stated", False)),
        ("Windows Server", "2008 R2", None, ("unavailable", None, False, "stated", False)),
    ]:
        resolved = resolve(product, version, cves)
        actual = tuple(resolved[k] for k in ("tier", "component_id", "is_substitute", "version_basis", "needs_question"))
        check(f"resolver:{product}:{version}:{cves}", actual == expected, resolved)

    # Check every declared alias / OS name against the inventory itself, including flags.
    alias_failures = []
    alias_count = 0
    for component in load_components():
        for alias in component.get("aliases", []) + component.get("os_names", []):
            alias_count += 1
            r = resolve(alias, component.get("version"))
            if r["component_id"] not in (None, component["id"]) and not r["is_substitute"]:
                alias_failures.append({"alias": alias, "declared": component["id"], "actual": r})
            if component["tier"] == "unavailable" and r["component_id"] and not r["is_substitute"]:
                alias_failures.append({"unavailable": alias, "actual": r})
    check("resolver:all-declared-aliases-no-wrong-unflagged-product", not alias_failures,
          {"count": alias_count, "failures": alias_failures})
    negatives = ["Redis Enterprise", "nginx Unit", "Apache Kafka", "Microsoft SQL Server", "VMware ESXi",
                 "PostgreSQL extension", "Windows Server Backup", "Unknown Vendor App"]
    wrong = {name: resolve(name) for name in negatives if resolve(name)["component_id"]}
    check("resolver:nearby-product-negatives", not wrong, {"tested": negatives, "wrong": wrong})

    action = {"id": "a1", "name": "Exploit Log4Shell CVE-2021-44228 in VMware Horizon", "target_host_ref": "h1",
              "attack_technique": "T1190", "source": "llm", "epistemic_status": "supported"}
    owner = ir([{"name": "VMware Horizon", "cve": ["CVE-2021-44228"]},
                {"name": "Log4j", "cve": ["CVE-2021-44228"]}], action=action, role="VMware Horizon server")
    owner["missing_items"] = calculate_missing_items(owner)
    check("owner:analysis-stage-no-Horizon-Log4j-version-question", not any(
        m.get("question") and m.get("category") == "version" and
        any(t in str(m.get("field", "")).lower() for t in ("log4", "horizon"))
        and "作業系統" not in str(m.get("field", "")) for m in owner["missing_items"]),
        [m for m in owner["missing_items"] if m.get("category") == "version"])
    planned = plan_dependencies(owner)
    check("owner:substitute-survives-dependency-topology", any(
        s.get("catalogue_component") == "vuln-log4shell-solr" and s.get("is_substitute") is True
        and s.get("version_basis") == "substituted" for s in planned["services"]), summarize(planned))
    check("owner:Horizon-original-external-not-reproducible", any(
        h.get("runtime") == "external_platform" and h.get("not_reproducible") is True
        for h in planned["hosts"]), planned["hosts"])

    gateway = plan_dependencies(ir([{"name": "Example Gateway", "cve": ["CVE-2021-44228"]}]))
    sub = next(s for s in gateway["services"] if s["id"] == "s1")
    check("honesty:nonlegacy-substitute-remains-flagged", sub.get("is_substitute") is True
          and sub.get("substitute_of") == "Example Gateway" and sub.get("version_basis") == "substituted"
          and sub.get("catalogue_component") == "vuln-log4shell-solr", summarize(gateway))

    overridden = copy.deepcopy(gateway)
    overridden["services"][0].update({"catalogue_component": "oss-httpd", "substitute_basis": "user_chosen",
                                      "field_sources": {"catalogue_component": "user"}})
    replanned = plan_dependencies(overridden)
    check("honesty:explicit-user-component-choice-survives-replan", next(
        s for s in replanned["services"] if s["id"] == "s1").get("catalogue_component") == "oss-httpd",
        {"user_choice": overridden["services"][0], "after": summarize(replanned)})

    source = ("Apache Struts was exploited using CVE-2017-5638.\n\n"
              "Separately, PostgreSQL stored application data without being exploited.")
    analyzed = build(source, [{"id": "s1", "name": "Apache Struts", "evidence": [source.split("\n\n")[0]]},
                             {"id": "s2", "name": "PostgreSQL", "evidence": [source.split("\n\n")[1]]}])
    pg = next(s for s in analyzed["services"] if s["id"] == "s2")
    check("analysis:CVE-does-not-leak-to-unrelated-product", not pg.get("cve"),
          {"source": source, "services": analyzed["services"],
           "planned": summarize(plan_dependencies(analyzed))})

    # Catalogue reproduction capability must not be silently promoted to source fact.
    no_cve_source = "The public-facing Apache Struts application was exploited."
    analyzed = build(no_cve_source, [{"id": "s1", "name": "Apache Struts", "evidence": [no_cve_source]}])
    planned = plan_dependencies(analyzed)
    check("honesty:no-new-source-CVE-from-catalogue", not any(s.get("cve") for s in planned["services"]),
          {"source": no_cve_source, "before": analyzed["services"], "after": summarize(planned)})

    raw_unknown = ir([{"name": "Citrix ADC"}], action={"id": "a1", "name": "Exploit Citrix ADC",
                      "target_host_ref": "h1", "attack_technique": "T1190"})
    questions = calculate_missing_items(raw_unknown)
    check("missing:unavailable-raw-IR-no-moot-version-question", not any(
        m.get("category") == "version" and "Citrix ADC" in str(m.get("field")) and m.get("question")
        for m in questions), [m for m in questions if m.get("category") == "version"])
    raw_horizon = ir([{"name": "VMware Horizon"}], action={"id": "a1", "name": "Exploit VMware Horizon",
                     "target_host_ref": "h1", "attack_technique": "T1190"}, role="VMware Horizon server")
    questions = calculate_missing_items(raw_horizon)
    check("missing:known-unavailable-Horizon-no-moot-version-question", not any(
        m.get("id") == "missing-service-s1-version" and m.get("question") for m in questions),
        [m for m in questions if m.get("id") == "missing-service-s1-version"])

    ambiguous = ir([{"name": "Windows Server"}], action={"id": "a1", "name": "Exploit Windows Server",
                   "target_host_ref": "h1", "attack_technique": "T1210"}, role="server",
                   host_extra={"os": "Windows Server", "os_version": "unknown"})
    before = calculate_missing_items(ambiguous)
    ambiguous["missing_items"] = before
    planned = plan_dependencies(ambiguous)
    check("missing:genuine-ambiguity-survives-planning", any(
        m.get("question") and len([s for s in m.get("suggestions", []) if "Evaluation" in s]) >= 3
        for m in planned["missing_items"]),
        {"before": [m for m in before if m.get("category") == "version"], "after": summarize(planned)})
    by_id = {c["id"]: c for c in load_components()}
    incorrect_tiers = [{"service": s, "catalogue_tier": by_id[s["catalogue_component"]]["tier"]}
                       for s in planned["services"] if s.get("catalogue_component") in by_id
                       and s.get("tier") != by_id[s["catalogue_component"]]["tier"]]
    check("honesty:planner-tier-matches-catalogue", not incorrect_tiers, incorrect_tiers)

    nginx = plan_dependencies(ir([{"name": "nginx"}]))
    polish = [m for m in nginx["missing_items"] if m.get("category") == "version"]
    check("polish:nginx-duplicate-only-cosmetic", len(polish) == 2 and all(not m.get("question") for m in polish), polish)

    # Replay checked-in recorded extraction directly through the deterministic builder.
    sample = ROOT / "fixtures/sample-scenarios/cisa-aa22-320a.md"
    recorded = ROOT / "tests/fixtures/recorded/cisa-aa22-320a.single_pass.llm.json"
    units, parsed = parse_source("markdown", sample.read_text())
    replay = _build_ir(json.loads(recorded.read_text()), input_kind="markdown", content=sample.read_text(),
                       source_name=sample.name, units=units, parsed_source=parsed, method="single_pass", name="QA replay")
    replay["id"] = "scn_qa_replay"
    planned = plan_dependencies(replay)
    check("owner:recorded-CISA-substitute-deployable-in-plan", any(
        h.get("image_hint") == "vuln-log4shell-solr" and h.get("deployable") is not False
        for h in build_environment_plan(planned)["hosts"]), summarize(planned))

    check("pre-LLM:summary-includes-tiers-and-CVE-map", all(x in inventory_summary() for x in
          ("- have:", "- obtainable:", "- unavailable:", "CVE-2021-44228 -> vuln-log4shell-solr")), inventory_summary())
    print(json.dumps({"summary": {"passed": sum(v["result"] == "PASS" for v in RESULTS.values()),
                                 "failed": sum(v["result"] == "FAIL" for v in RESULTS.values())},
                      "checks": RESULTS}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
