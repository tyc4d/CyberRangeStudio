#!/usr/bin/env python3
"""Run and report the first 100 sorted CTI fixtures through real CyberRange modules."""
from __future__ import annotations
import argparse, json, os, pathlib, re, subprocess, sys, traceback
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[2]
API = ROOT / "apps/api"
PYTHON = pathlib.Path("/home/tyc4d/cr-project/.venv/bin/python")
SCENARIO_RUNNER = ROOT / "reports/overnight/evidence/scenario-eng/run_real.py"
RUNNER_COPY = ROOT / "reports/eval-100/run_real_eval.py"
OUT = ROOT / "reports/eval-100"
DATA = ROOT / ".data-eval100"
CLIENT = None  # one shared discovery MetadataClient, so shared CVE lookups are cached across cases
CUM_STOP_USD = 90.0  # owner allowed up to $100; stop well under it


def read_json(path):
    try: return json.loads(path.read_text(encoding="utf-8"))
    except Exception: return None


def first(*xs):
    return next((x for x in xs if x not in (None, "", [], {})), None)


def flat_cves(*sources):
    """Flatten any mix of str / list / nested-list CVE fields into a unique list of strings."""
    out = []
    def _walk(v):
        if isinstance(v, (list, tuple)):
            for item in v: _walk(item)
        elif isinstance(v, str) and v.strip():
            out.append(v.strip())
    for s in sources: _walk(s)
    seen = {}
    return [seen.setdefault(c, c) for c in out if c not in seen]


def jstr(seq):
    """Join a possibly-messy sequence into 'a, b' with every element coerced to str."""
    return ", ".join(str(x) for x in (seq or []))


def source_meta(case_id):
    idx = read_json(ROOT / "fixtures/cti-corpus/_index.json") or []
    return next((x for x in idx if x.get("id") == case_id), {})


def process(case_id):
    src = ROOT / "fixtures/cti-corpus" / case_id / "report.md"
    run = OUT / "runs" / case_id
    run.mkdir(parents=True, exist_ok=True)
    case_data = DATA / case_id
    case_data.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({"CR_DATA_DIR": str(case_data), "CR_BUDGET_HARD_CAP_USD": "2",
                "CR_BUDGET_STOP_NEW_USD": "1.8", "PYTHONPATH": str(ROOT / "packages/contracts")})
    cmd = [str(PYTHON), str(RUNNER_COPY), str(src), "markdown", "single_pass", str(run), case_id]
    proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
    (run / "runner.stdout.txt").write_text(proc.stdout, encoding="utf-8")
    (run / "runner.stderr.txt").write_text(proc.stderr, encoding="utf-8")
    ir = read_json(run / "01-ir.json")
    topo = read_json(run / "03-topology.json")
    m6 = None; inv = []; manifest = None; error = None
    if ir is not None:
        sys.path.insert(0, str(API))
        try:
            from app.iac.generator import inspect_plan
            from app.planner.inventory import resolve
            from app.poc.discovery import discover
            _, m6 = inspect_plan(topo if topo is not None else {}, case_id)
            for service in ir.get("services", []):
                cves = flat_cves(service.get("cves"), service.get("cve"))
                related = [a for a in ir.get("actions", []) if a.get("service_ref") == service.get("id")]
                technique = first(*[a.get("mitre_id") or a.get("attack_technique") for a in related])
                resolution = resolve(service.get("product") or service.get("name"), service.get("version"), cves, technique)
                inv.append({"service_id": service.get("id"), "name": service.get("name"), "product": service.get("product"),
                            "version": service.get("version"), "cves": cves, "technique": technique, "resolution": resolution})
            manifest = discover(case_id, ir, client=CLIENT)
            (run / "04-module6.json").write_text(json.dumps(m6, ensure_ascii=False, indent=2), encoding="utf-8")
            (run / "05-inventory.json").write_text(json.dumps(inv, ensure_ascii=False, indent=2), encoding="utf-8")
            (run / "06-poc-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            (run / "postprocess.error.txt").write_text(traceback.format_exc(), encoding="utf-8")
    budget = {}
    ledger = case_data / "llm_ledger.db"
    cache = case_data / "llm_cache.db"
    if ledger.exists():
        import sqlite3
        with sqlite3.connect(ledger) as c:
            try:
                row = c.execute("select coalesce(sum(est_cost_usd),0),count(*),coalesce(sum(cached),0) from ledger").fetchone()
                budget = {"estimated_usd": row[0], "calls": row[1], "cached_calls": row[2]}
            except Exception: pass
    return {"id": case_id, "returncode": proc.returncode, "ir": ir, "topology": topo, "module6": m6,
            "inventory": inv, "manifest": manifest, "postprocess_error": error,
            "runner_stdout": proc.stdout, "runner_stderr": proc.stderr, "budget": budget,
            "cache_db_exists": cache.exists(), "input": str(src.relative_to(ROOT)), "run_dir": str(run.relative_to(ROOT))}


def render_case(result):
    cid=result["id"]; ir=result.get("ir") or {}; topo=result.get("topology") or {}; plan=result.get("module6") or {}
    meta=source_meta(cid); hosts=ir.get("hosts", []); services=ir.get("services", []); actions=ir.get("actions", [])
    inv_by={x.get("service_id"):x for x in result.get("inventory", [])}
    poc_by={}
    for item in (result.get("manifest") or {}).get("items", []): poc_by.setdefault(item.get("action_id"), []).append(item)
    lines=[f"# {cid}: {meta.get('title') or ir.get('title') or '（模型未抽出標題）'}", "",
           f"- Publisher: {first(ir.get('publisher'), meta.get('publisher'), '未提供')}",
           f"- Date: {first(ir.get('date'), meta.get('date'), '未提供')}", f"- Source: {first(ir.get('source_url'), meta.get('url'), '未提供')}",
           f"- Pipeline: {'成功' if result.get('ir') is not None and result.get('returncode') == 0 else '失敗/不完整'}; module 6: {'deployable' if plan.get('deployable') else 'blocked'}",
           f"- LLM ledger: {result.get('budget',{}).get('calls',0)} calls, estimated ${result.get('budget',{}).get('estimated_usd',0):.6f}, cached {result.get('budget',{}).get('cached_calls',0)}", "",
           "## HOSTS", "", "| ID | Role | OS / version | Deployable | Reason |", "|---|---|---|---|---|"]
    comps={x.get("host_id"):x for x in plan.get("components",[])}
    for h in hosts:
        c=comps.get(h.get("id"),{}); yes=bool(c.get("deployable")); reason=c.get("reason") or ("module 6 component resolved" if yes else "; ".join(plan.get("errors",[])[:2]) or "not resolved")
        lines.append(f"| {h.get('id')} | {h.get('role') or h.get('name') or ''} | {h.get('os') or ''} {h.get('os_version') or ''} | {'yes' if yes else 'no'} | {reason} |")
    lines += ["", "## TOPOLOGY", "", f"Networks: {json.dumps(topo.get('networks', []), ensure_ascii=False)}", "",
              f"Connections: {json.dumps(topo.get('connections', []), ensure_ascii=False)}", "",
              f"Zones / segments: {json.dumps(topo.get('zones', topo.get('segments', [])), ensure_ascii=False)}", "",
              f"Deployment components: {json.dumps(plan.get('components', []), ensure_ascii=False)}", "",
              f"Not deployed: {json.dumps(plan.get('not_deployed', []), ensure_ascii=False)}", "",
              "## SERVICES", "", "| Service | Version (basis) | CVE(s) | Inventory | Component / substitute | reproduces_cve | PoC-validatable? | Top online PoC |", "|---|---|---|---|---|---|---|---|"]
    service_status=[]
    for s in services:
        ii=inv_by.get(s.get("id"),{}); res=ii.get("resolution") or {}; acts=[a for a in actions if a.get("service_ref")==s.get("id") or a.get("target_host_ref") in [h.get("id") for h in hosts if s.get("id") in (h.get("service_refs") or [])]]
        pocs=[p for a in acts for p in poc_by.get(a.get("id"),[])]; pocs.sort(key=lambda x:float(x.get("compatibility_score",0)),reverse=True); top=pocs[0] if pocs else None
        tier=res.get("tier", "unavailable"); component=res.get("component_id"); substitute=bool(res.get("is_substitute")); cves=flat_cves(ii.get("cves"))
        has_image=bool(component and tier in {"have","obtainable"}); same_cve=bool(cves and any(c in (res.get("reproduces_cve") or []) for c in cves))
        if has_image and substitute and same_cve: status="substitute"
        elif has_image and not substitute and top: status="deployable"
        elif top: status="online-PoC-only"
        else: status="no"
        service_status.append(status)
        comp=f"{component or 'none'}"+(" (substitute)" if substitute else "")
        lines.append(f"| {s.get('name') or s.get('product') or 'unnamed'} | {s.get('version') or 'unknown'} ({res.get('version_basis') or 'unknown'}) | {jstr(cves) or 'none'} | {tier} | {comp} | {jstr(res.get('reproduces_cve')) or 'none'} | {status} | {top.get('source_url') if top else 'none'} |")
    lines += ["", f"Actions: {len(actions)}; services: {len(services)}; PoC candidates: {len((result.get('manifest') or {}).get('items', []))}.", "",
              "We did not deploy or exploit this case. This is PLAN + DISCOVERY only. A real live exploit was separately proven for Struts S2-045 on the PVE farm (see `reports/overnight/evidence/poc-eng/phase3-struts-s2045-result.json` and `reports/overnight/evidence/cti-research/vulhub/struts2_s2-045.README.md`).", ""]
    if result.get("postprocess_error"): lines += [f"Post-processing error: `{result['postprocess_error']}`", ""]
    return "\n".join(lines), service_status


def main():
    global CLIENT
    # Evaluation-only copy: lift the checked-in runner's lower caps only. A fresh CR_DATA_DIR per
    # report already yields an empty llm_cache.db (0 cached calls), so no cache monkeypatch is needed.
    source = SCENARIO_RUNNER.read_text(encoding="utf-8")
    source = source.replace('os.environ["CR_BUDGET_HARD_CAP_USD"] = "5"\nos.environ["CR_BUDGET_STOP_NEW_USD"] = "4"\n', '')
    RUNNER_COPY.write_text(source, encoding="utf-8")
    sys.path.insert(0, str(API))
    from app.poc.discovery.sources import MetadataClient
    CLIENT = MetadataClient(timeout=6)  # shared across cases: caches NVD/GitHub/Exploit-DB lookups for repeated CVEs
    ap=argparse.ArgumentParser(); ap.add_argument("--limit", type=int, default=100); ap.add_argument("--start", type=int, default=0); args=ap.parse_args()
    fixtures=sorted(p.parent.name for p in (ROOT/"fixtures/cti-corpus").glob("*/report.md"))
    selected=fixtures[args.start:args.start+args.limit]
    results=[]; cum_usd=0.0
    for i,cid in enumerate(selected,1):
        if cum_usd >= CUM_STOP_USD:
            print(f"STOP: cumulative spend ${cum_usd:.4f} reached cap ${CUM_STOP_USD}; {i-1}/{len(selected)} done", flush=True)
            selected=selected[:i-1]; break
        print(f"[{i}/{len(selected)}] {cid}  (cum ${cum_usd:.4f})", flush=True)
        try:
            r=process(cid); results.append(r)
            cum_usd += (r.get("budget") or {}).get("estimated_usd", 0) or 0
            try:
                body,status=render_case(r)
            except Exception as rexc:
                status=[]; body=f"# {cid}\n\nRender error: `{type(rexc).__name__}: {rexc}`\n\n```\n{traceback.format_exc()}\n```\n"
                r["render_error"]=f"{type(rexc).__name__}: {rexc}"
            case_path=OUT/"cases"/(cid+".md"); case_path.parent.mkdir(parents=True,exist_ok=True); case_path.write_text(body,encoding="utf-8")
            (OUT/"runs"/cid/"result.json").write_text(json.dumps({k:v for k,v in r.items() if k not in {"ir","topology"}},ensure_ascii=False,indent=2),encoding="utf-8")
            # Preserve raw IR and topology in their native run files; lightweight index records computed metrics.
            hosts=r.get("ir",{}).get("hosts",[]) if r.get("ir") else []; services=r.get("ir",{}).get("services",[]) if r.get("ir") else []
            tiers=Counter((x.get("resolution") or {}).get("tier","unavailable") for x in r.get("inventory",[]))
            deployable_hosts=sum(1 for c in (r.get("module6") or {}).get("components",[]) if c.get("deployable"))
            metrics={"id":cid,"title":source_meta(cid).get("title"),"returncode":r.get("returncode"),"hosts":len(hosts),"services":len(services),"deployable_hosts":deployable_hosts,"statuses":status,"tiers":dict(tiers),"poc_candidates":len((r.get("manifest") or {}).get("items",[])),"budget":r.get("budget"),"blocked": bool(r.get("ir") is None or r.get("postprocess_error") or r.get("render_error") or not (r.get("module6") or {}).get("deployable"))}
            (OUT/"runs"/cid/"metrics.json").write_text(json.dumps(metrics,ensure_ascii=False,indent=2),encoding="utf-8")
        except Exception as exc:
            # Fault isolation: one bad case must never abort the overnight run.
            print(f"  ! case {cid} failed: {type(exc).__name__}: {exc}", flush=True)
            (OUT/"runs"/cid).mkdir(parents=True,exist_ok=True)
            (OUT/"runs"/cid/"metrics.json").write_text(json.dumps({"id":cid,"error":f"{type(exc).__name__}: {exc}","blocked":True,"statuses":[],"tiers":{},"hosts":0,"services":0,"deployable_hosts":0,"poc_candidates":0,"budget":{}},ensure_ascii=False,indent=2),encoding="utf-8")
            (OUT/"runs"/cid/"case.error.txt").write_text(traceback.format_exc(),encoding="utf-8")
        (OUT/"progress.json").write_text(json.dumps({"completed":i,"requested":len(selected),"ids":selected},indent=2),encoding="utf-8")
    summarize(selected)


def summarize(ids):
    rows=[]
    for cid in ids:
        m=read_json(OUT/"runs"/cid/"metrics.json")
        if m: rows.append(m)
    tier_totals=Counter(); status_totals=Counter(); all_poc=all_svc=deployable_labs=found_cases=blocked=0
    lines=["# Eval-100 Summary", "", "PLAN + DISCOVERY results for the first 100 fixture IDs in lexicographic order. No lab deployment or exploit was run in this evaluation.", "",
           "## Per-report results", "", "| ID | Hosts | Services | Deployable hosts | Any PoC-validatable service | Inventory tier mix |", "|---|---:|---:|---:|---|---|"]
    for m in rows:
        statuses=m["statuses"]; tiers=m["tiers"]
        for k,v in tiers.items(): tier_totals[k]+=v
        for x in statuses: status_totals[x]+=1
        if m["poc_candidates"]: found_cases+=1
        if any(x in {"deployable","substitute"} for x in statuses): deployable_labs+=1
        if any(x in {"deployable","substitute","online-PoC-only"} for x in statuses): all_poc+=1
        all_svc+=len(statuses)
        if m["blocked"]: blocked+=1
        lines.append(f"| [{m['id']}](cases/{m['id']}.md) | {m['hosts']} | {m['services']} | {m['deployable_hosts']} | {'yes' if any(x in {'deployable','substitute','online-PoC-only'} for x in statuses) else 'no'} | {', '.join(f'{k}: {v}' for k,v in sorted(tiers.items())) or 'none'} |")
    lines += ["", "## Totals", "", f"- Reports completed with metrics: {len(rows)} / {len(ids)}.", f"- Reports producing a deployable lab candidate (at least one `deployable` or `substitute` service): {deployable_labs}.", f"- Reports with at least one service by PoC-validatability: deployable {sum(1 for m in rows if 'deployable' in m['statuses'])}; substitute {sum(1 for m in rows if 'substitute' in m['statuses'])}; online-PoC-only {sum(1 for m in rows if 'online-PoC-only' in m['statuses'])}; no {sum(1 for m in rows if not any(x != 'no' for x in m['statuses']))}.", f"- Services with at least one discovered online PoC candidate: {sum(m['poc_candidates'] > 0 for m in rows)} reports with candidates; {sum(m['poc_candidates'] for m in rows)} candidates total. Candidate count is not a validation count.", f"- Inventory tiers across resolved services: {', '.join(f'{k}: {v}' for k,v in sorted(tier_totals.items())) or 'none'}.", f"- Blocked or incomplete cases (pipeline absent, post-processing error, or module 6 non-deployable): {blocked}.", "- Cached LLM calls: 0 expected because each report used a fresh `CR_DATA_DIR`; confirm per-case ledgers in `runs/<id>/metrics.json`.", "", "These are PLAN + DISCOVERY results. An online PoC candidate means metadata was found; it does not mean code was downloaded or run. Only cases with a deployable/substitute candidate could be validated in a lab, and they were not deployed or validated here. A real live exploit was separately proven for Struts S2-045 on the PVE farm: `reports/overnight/evidence/poc-eng/phase3-struts-s2045-result.json`.", "", "## Selected fixture IDs", "", *[f"- {x}" for x in ids], ""]
    (OUT/"SUMMARY.md").write_text("\n".join(lines),encoding="utf-8")

if __name__ == "__main__": main()
