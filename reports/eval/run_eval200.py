#!/usr/bin/env python3
"""eval-200 runner for ONE corpus report (no product code changes; same entry point and settings as run_eval.py).
1) reports/overnight/evidence/scenario-eng/run_real.py <report.md> markdown single_pass <out> <id>, unchanged,
   in a subprocess with a NEW CR_DATA_DIR (.data-eval200/<id>[-retry]); asserts no llm_cache.db exists before.
2) module-6 check: app.iac.generator.inspect_plan + compose_document on 03-topology.json (in memory, no deploy).
3) meta.json: status, duration, LLM calls/cost/cached from that data dir's ledger, errors, retry log.
One retry, only when the failure text looks like a transient network/API error (TRANSIENT regex); logged in meta.
Usage: run_eval200.py <corpus-id>"""
import json, os, pathlib, re, shutil, sqlite3, subprocess, sys, time
ROOT = pathlib.Path(__file__).resolve().parents[2]
P = "/home/tyc4d/cr-project/.venv/bin/python"
TRANSIENT = re.compile(r"APIConnectionError|APITimeoutError|ConnectionError|ReadTimeout|Timeout|RateLimitError|"
                       r"InternalServerError|ServiceUnavailable|Bad Gateway|\b50[0234]\b|429|Connection reset|"
                       r"Temporary failure in name resolution", re.I)
rid = sys.argv[1]
src = ROOT / "fixtures/cti-corpus" / rid / "report.md"
out = ROOT / "reports/eval/runs-200" / rid

def ledger(data):
    led = data / "llm_ledger.db"
    if not led.exists(): return []
    with sqlite3.connect(led) as c:
        rows = c.execute("SELECT purpose, model, input_tokens, output_tokens, est_cost_usd, cached FROM ledger").fetchall()
    return [dict(zip(["purpose", "model", "input_tokens", "output_tokens", "est_cost_usd", "cached"], r)) for r in rows]

def attempt(tag):
    data = ROOT / ".data-eval200" / (rid + tag)
    if data.exists(): shutil.rmtree(data)
    data.mkdir(parents=True)
    assert not (data / "llm_cache.db").exists(), "data dir not fresh"
    if out.exists(): shutil.rmtree(out)
    out.mkdir(parents=True)
    env = {**os.environ, "CR_DATA_DIR": str(data)}
    cmd = [P, "reports/overnight/evidence/scenario-eng/run_real.py", str(src.relative_to(ROOT)), "markdown", "single_pass", str(out.relative_to(ROOT)), rid]
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
    dur = round(time.time() - t0, 1)
    (out / "run.log").write_text(f"$ CR_DATA_DIR={data.relative_to(ROOT)} {' '.join(cmd)}\nexit={proc.returncode}\n--- stdout\n{proc.stdout}\n--- stderr\n{proc.stderr}")
    return data, env, cmd, proc, dur

data, env, cmd, proc, dur = attempt("")
retries = []
first_spend = ledger(data)
if proc.returncode != 0 and TRANSIENT.search(proc.stderr[-3000:] or ""):
    last = (proc.stderr.strip().splitlines() or ["?"])[-1]
    retries.append({"reason": last[:300], "first_duration_s": dur, "first_llm_cost_usd": round(sum(r["est_cost_usd"] or 0 for r in first_spend), 6),
                    "first_data_dir": str(data.relative_to(ROOT))})
    shutil.copy(out / "run.log", ROOT / "reports/eval" / f"retry-{rid}.first-attempt.log")
    data, env, cmd, proc, dur = attempt("-retry")
meta = {"report_id": rid, "command": " ".join(cmd), "data_dir": str(data.relative_to(ROOT)), "exit_code": proc.returncode,
        "duration_s": dur, "errors": [], "retries": retries}
if proc.returncode != 0:
    meta["errors"].append(proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else f"exit {proc.returncode}")
calls = ledger(data)
meta["llm_calls"] = calls
meta["llm_cost_usd"] = round(sum(r["est_cost_usd"] or 0 for r in calls), 6)
meta["llm_cached_calls"] = sum(1 for r in calls if r["cached"])
meta["llm_cost_incl_failed_attempt_usd"] = round(meta["llm_cost_usd"] + sum(r["first_llm_cost_usd"] for r in retries), 6)
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
meta["status"] = "ok" if not meta["errors"] and topo.exists() else "error"
(out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
print(rid, meta["status"], meta["duration_s"], meta["llm_cost_usd"], meta["errors"], flush=True)
