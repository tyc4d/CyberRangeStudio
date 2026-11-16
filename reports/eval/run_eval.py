"""Eval runner (no product code changes). For one report x run:
1) runs the earlier entry point reports/overnight/evidence/scenario-eng/run_real.py unchanged
   (modules 1,2,4,5; markdown, single_pass) in a subprocess with a FRESH CR_DATA_DIR
   (.data-eval/run-<n>/<report-id>) so no LLM cache is shared between runs;
2) runs the IaC check (module 6, app.iac.generator.inspect_plan + compose_document; pure, no files
   written outside the out dir, no deployment) on 03-topology.json;
3) writes meta.json: status, duration, LLM cost/tokens from that data dir's ledger, errors.
Usage: run_eval.py <report-id> <run-n>
"""
import json, os, pathlib, sqlite3, subprocess, sys, time

ROOT = pathlib.Path(__file__).resolve().parents[2]
P = "/home/tyc4d/cr-project/.venv/bin/python"
rid, n = sys.argv[1], int(sys.argv[2])
src = ROOT / "fixtures/cti-candidates" / rid / "report.md"
out = ROOT / "reports/eval/runs" / rid / f"run-{n}"
data = ROOT / ".data-eval" / f"run-{n}" / rid
out.mkdir(parents=True, exist_ok=True); data.mkdir(parents=True, exist_ok=True)
assert not (data / "llm_cache.db").exists(), "data dir not fresh"
env = {**os.environ, "CR_DATA_DIR": str(data)}
cmd = [P, "reports/overnight/evidence/scenario-eng/run_real.py", str(src.relative_to(ROOT)), "markdown", "single_pass", str(out.relative_to(ROOT)), rid]
t0 = time.time()
proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
dur = round(time.time() - t0, 1)
(out / "run.log").write_text(f"$ CR_DATA_DIR={data.relative_to(ROOT)} {' '.join(cmd)}\nexit={proc.returncode}\n--- stdout\n{proc.stdout}\n--- stderr\n{proc.stderr}")
meta = {"report_id": rid, "run": n, "command": " ".join(cmd), "data_dir": str(data.relative_to(ROOT)),
        "exit_code": proc.returncode, "duration_s": dur, "errors": []}
if proc.returncode != 0:
    meta["errors"].append(proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else f"exit {proc.returncode}")
# LLM ledger of this fresh data dir = this run's spend
led = data / "llm_ledger.db"
if led.exists():
    with sqlite3.connect(led) as c:
        rows = c.execute("SELECT purpose, model, input_tokens, output_tokens, est_cost_usd, cached FROM ledger").fetchall()
    meta["llm_calls"] = [dict(zip(["purpose", "model", "input_tokens", "output_tokens", "est_cost_usd", "cached"], r)) for r in rows]
    meta["llm_cost_usd"] = round(sum(r[4] or 0 for r in rows), 6)
    meta["llm_cached_calls"] = sum(1 for r in rows if r[5])
else:
    meta["llm_calls"], meta["llm_cost_usd"], meta["llm_cached_calls"] = [], 0.0, 0
# Module 6: IaC check on the planned environment
topo = out / "03-topology.json"
if topo.exists():
    code = r'''
import json, sys
sys.path.insert(0, "apps/api")
from app.iac.generator import inspect_plan, compose_document
plan = json.load(open(sys.argv[1]))
_, report = inspect_plan(plan, "evidence")
json.dump(report, open(sys.argv[2] + "/04-iac-report.json", "w"), ensure_ascii=False, indent=1)
if report.get("deployable"):
    open(sys.argv[2] + "/04-docker-compose.yml", "w").write(compose_document(plan, "evidence"))
'''
    p2 = subprocess.run([P, "-c", code, str(topo), str(out)], cwd=ROOT, env=env, capture_output=True, text=True)
    if p2.returncode != 0:
        meta["errors"].append("iac: " + (p2.stderr.strip().splitlines() or ["?"])[-1])
        (out / "04-iac-error.txt").write_text(p2.stderr)
meta["status"] = "ok" if not meta["errors"] and (out / "03-topology.json").exists() else "error"
(out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
print(rid, n, meta["status"], meta["duration_s"], meta["llm_cost_usd"], meta["errors"])
