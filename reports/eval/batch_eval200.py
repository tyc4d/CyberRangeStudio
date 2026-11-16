#!/usr/bin/env python3
"""eval-200 batch driver: runs run_eval200.py for ids from the manifest with <= N parallel workers.
Skips ids that already have runs-200/<id>/meta.json. Stops launching new runs once the summed
llm_cost_incl_failed_attempt_usd of all finished runs reaches STOP_USD (default 19.0; hard cap $20).
Usage: batch_eval200.py <N-parallel> [--limit K] [--ids id1,id2]"""
import concurrent.futures as cf, csv, json, pathlib, subprocess, sys, threading
ROOT = pathlib.Path(__file__).resolve().parents[2]
P = "/home/tyc4d/cr-project/.venv/bin/python"
STOP_USD = 19.0
n = int(sys.argv[1]); args = sys.argv[2:]
ids = [r["id"] for r in csv.DictReader(open(ROOT / "fixtures/cti-corpus/manifest.csv"))]
if "--ids" in args: ids = args[args.index("--ids") + 1].split(",")
if "--limit" in args: ids = ids[:int(args[args.index("--limit") + 1])]
R = ROOT / "reports/eval/runs-200"
def spent():
    return sum(json.loads(m.read_text()).get("llm_cost_incl_failed_attempt_usd", 0) for m in R.glob("*/meta.json"))
lock = threading.Lock()
def one(i):
    with lock:
        s = spent()
        if s >= STOP_USD:
            print("SKIP (budget stop)", i, round(s, 4), flush=True); return
    if (R / i / "meta.json").exists(): return
    r = subprocess.run([P, "reports/eval/run_eval200.py", i], cwd=ROOT, capture_output=True, text=True)
    print(r.stdout.strip() or f"{i} runner-exit {r.returncode} {r.stderr.strip()[-300:]}", flush=True)
with cf.ThreadPoolExecutor(n) as ex: list(ex.map(one, ids))
print("TOTAL spent", round(spent(), 4), flush=True)
