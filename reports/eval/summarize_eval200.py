#!/usr/bin/env python3
"""eval-200 metrics, computed only from files (no LLM). Inputs: fixtures/cti-corpus/manifest.csv,
fixtures/cti-corpus/<id>/source.pdf.txt, reports/eval/runs-200/<id>/*, reports/eval/attack-enterprise-20.1-ids.json.
Outputs: reports/eval/eval-200-runs.csv (one row per run), eval-200-steps.csv (one row per IR step),
eval-200-aggregate.csv (metric,value,denominator), and prints the aggregate (used in eval-200-summary.md).

Rules
- run outcome: crashed = meta.status != "ok" (non-zero exit, no 03-topology.json, or module-6 error) or no meta.json;
  system-blocked = not crashed and >= 1 missing item in 02-dependencies.json with status "open" and severity "blocker";
  finished = not crashed and not system-blocked.
- dependency edges = len(relations) in 02-dependencies.json.
- quote grounding: for each step (IR action), each evidence quote it cites (evidence_refs -> evidence[].quote) is
  checked against source.pdf.txt after norm(): curly quotes -> straight, en/em dash -> "-", "[.]" -> ".",
  line-break hyphenation "-\\n" removed, then ALL whitespace and all "-" removed, lower-cased.
  A quote with "..." / "…" counts as found when every part longer than 8 characters is found.
- ATT&CK: each non-empty step attack_technique is valid if it is an active (not revoked/deprecated) technique id
  in the pinned MITRE ATT&CK Enterprise v20.1 STIX file; also reported: whether the id string occurs in source.pdf.txt.
"""
import collections, csv, html, json, pathlib, re, statistics, subprocess
ROOT = pathlib.Path(__file__).resolve().parents[2]
C = ROOT / "fixtures/cti-corpus"; R = ROOT / "reports/eval/runs-200"; E = ROOT / "reports/eval"
AT = json.loads((E / "attack-enterprise-20.1-ids.json").read_text())
ACTIVE, OLD = set(AT["active"]), set(AT["revoked_or_deprecated"])
def norm(s):
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-").replace("[.]", ".")
    s = re.sub(r"-\s*\n\s*", "", s); s = re.sub(r"\s+", "", s); s = s.replace("-", "")
    return s.lower()
def found(q, src):
    parts = [p for p in re.split(r"…|\.\.\.", q) if len(p.strip()) > 8] or [q]
    return all(norm(p) in src for p in parts)
def load(p):
    try: return json.loads(p.read_text())
    except Exception: return None
def pct(a, b): return f"{a}/{b} ({100*a/b:.1f}%)" if b else f"{a}/0"
def q(xs, p):  # p90 = sorted(xs)[round(0.9 * (n - 1))] (nearest index, Python round)
    xs = sorted(xs); return xs[min(len(xs) - 1, int(round(p * (len(xs) - 1))))] if xs else None
man = list(csv.DictReader(open(C / "manifest.csv")))
runs, steps = [], []
nf2 = [0]
qrec = []
TAG = re.compile(r"\s*\[(?:T\d{4}(?:\.\d{3})?|TA\d{4})\]")
TAGS_ANY = re.compile(r"\s*\[(?:T|TA)\d{4}[^\]]{0,80}\]")
_units = {}
def units_text(d):
    if d not in _units:
        u = load(d / "00-units.json") or []; _units[d] = [x["text"] for x in u]
    return _units[d]
def cause(qt, raw, src2, d):
    """Why a quote the product marks verified is not found verbatim in source.pdf.txt (first rule that applies)."""
    if found(qt, norm(TAG.sub("", raw))): return "1 source has a single [T####]/[TA####] tag inside the quoted span"
    if found(qt, norm(TAGS_ANY.sub("", raw))): return "2 source has a multi-id ATT&CK tag ([T1560, T1039]) inside the span"
    if found(qt.rstrip(" .") , norm(TAGS_ANY.sub("", raw))) and qt.rstrip().endswith("."): return "3 quote cut mid-sentence, period added"
    if found(qt, src2): return "4 found in non-layout (reading-order) text"
    if any(found(qt, norm(TAGS_ANY.sub("", u))) for u in units_text(d)): return "5 found only in a parser-added unit (ATT&CK table row)"
    if found(qt, norm(html.unescape(TAGS_ANY.sub("", raw)))): return "6 source has a literal HTML entity (&gt;) plus an ATT&CK tag in the span"
    if re.search(r"…|\.\.\.", qt): return "7 ellipsis quote with a changed word between fragments"
    return "8 other (accepted by the strong threshold)"
SCR = ROOT / ".data-eval200/_rawtext"; SCR.mkdir(parents=True, exist_ok=True)
agree_tot = [0, 0, 0]  # quotes, our-check == product quote_verified, product says verified
for m in man:
    rid = m["id"]; d = R / rid
    if not d.exists(): continue
    meta = load(d / "meta.json"); ir = load(d / "01-ir.json"); dep = load(d / "02-dependencies.json")
    topo = load(d / "03-topology.json"); iac = load(d / "04-iac-report.json")
    src = norm((C / rid / "source.pdf.txt").read_text(errors="replace")); raw = (C / rid / "source.pdf.txt").read_text(errors="replace")
    rawp = SCR / f"{rid}.raw.txt"   # secondary check only: pdftotext WITHOUT -layout (reading order), regenerated here
    if not rawp.exists(): subprocess.run(["pdftotext", str(C / rid / "source.pdf"), str(rawp)], capture_output=True)
    src2 = norm(rawp.read_text(errors="replace")) if rawp.exists() else ""
    crashed = meta is None or meta.get("status") != "ok"
    miss = (dep or {}).get("missing_items", [])
    blk = [x for x in miss if x.get("status") == "open" and x.get("severity") == "blocker"]
    outcome = "crashed" if crashed else ("system-blocked" if blk else "finished")
    ev = {e["id"]: e for e in (ir or {}).get("evidence", [])}
    rep = {a["id"]: a.get("reproducibility") for a in (dep or {}).get("actions", [])}
    nq = nf = nt = nv = nold = nins = 0
    for a in (ir or {}).get("actions", []):
        qs = [ev[r]["quote"] for r in a.get("evidence_refs", []) if r in ev and ev[r].get("quote")]
        f = [found(x, src) for x in qs]
        refs = [r for r in a.get("evidence_refs", []) if r in ev and ev[r].get("quote")]
        pv = [bool(ev[r].get("quote_verified")) for r in refs]
        for r, ok1, v in zip(refs, f, pv):
            qrec.append({"id": rid, "step": a["id"], "evidence": r, "quote": ev[r]["quote"], "found_primary": ok1,
                         "product_verified": v, "product_match": ev[r].get("quote_match"), "product_score": ev[r].get("match_score"),
                         "cause": "" if ok1 or not v else cause(ev[r]["quote"], raw, src2, d)})
        agree_tot[0] += len(pv); agree_tot[1] += sum(x == y for x, y in zip(f, pv)); agree_tot[2] += sum(pv)
        t = (a.get("attack_technique") or "").strip().upper()
        valid = (t in ACTIVE) if t else None
        steps.append({"id": rid, "step": a["id"], "n_quotes": len(qs), "n_quotes_found": sum(f),
                      "attack_technique": t, "attack_valid_v20_1": valid, "attack_revoked_or_deprecated": (t in OLD) if t else None,
                      "attack_id_in_source": (re.search(rf"(?<![A-Za-z0-9.]){re.escape(t)}(?![0-9]|\.\d)", raw) is not None) if t else None,
                      "reproducibility": rep.get(a["id"], "")})
        nq += len(qs); nf += sum(f); nf2[0] += sum(found(x, src2) or ok1 for x, ok1 in zip(qs, f))
        if t: nt += 1; nv += bool(valid); nold += t in OLD; nins += steps[-1]["attack_id_in_source"]
    rc = collections.Counter(rep.values())
    runs.append({"id": rid, "category": m["category"], "pages": m["pages"], "chars": m["chars"], "overlap_hand_keyed": m["overlap_hand_keyed"],
                 "outcome": outcome, "errors": "; ".join((meta or {}).get("errors", []))[:200], "retries": len((meta or {}).get("retries", [])),
                 "steps": len(ir["actions"]) if ir else "", "hosts_ir": len(ir["hosts"]) if ir else "",
                 "hosts_env_plan": len(topo["hosts"]) if topo else "", "dependency_edges": len(dep["relations"]) if dep else "",
                 "missing_ir": len(ir["missing_items"]) if ir else "", "missing_after_mod4": len(miss) if dep else "",
                 "open_blocker_items": len(blk) if dep else "",
                 "quotes": nq, "quotes_found": nf, "attack_ids": nt, "attack_valid": nv, "attack_revoked_or_deprecated": nold, "attack_in_source": nins,
                 **{f"rep_{k}": rc.get(k, 0) for k in ("reproducible", "substitute", "needs_vm", "not_reproducible")},
                 "rep_other": sum(v for k, v in rc.items() if k not in ("reproducible", "substitute", "needs_vm", "not_reproducible")),
                 "fidelity": (dep or {}).get("fidelity", ""),
                 "iac_deployable": "" if iac is None else ("yes" if iac.get("deployable") else "no"),
                 "iac_blockers": " ".join(sorted(b.get("code", "?") for b in (iac or {}).get("blockers", []))),
                 "llm_calls": len((meta or {}).get("llm_calls", [])), "llm_cached_calls": (meta or {}).get("llm_cached_calls", ""),
                 "llm_cost_usd": (meta or {}).get("llm_cost_usd", ""), "llm_cost_incl_failed_attempt_usd": (meta or {}).get("llm_cost_incl_failed_attempt_usd", ""),
                 "wall_s": (meta or {}).get("duration_s", "")})
def wcsv(name, rows):
    with open(E / name, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
wcsv("eval-200-runs.csv", runs); wcsv("eval-200-steps.csv", steps)
N = len(runs); oc = collections.Counter(r["outcome"] for r in runs)
ok = [r for r in runs if r["outcome"] != "crashed"]
agg = []
def A(k, v, den=""): agg.append({"metric": k, "value": v, "denominator": den})
A("reports in manifest", len(man)); A("runs", N)
for k in ("finished", "system-blocked", "crashed"): A(f"outcome {k}", oc.get(k, 0), N)
A("runs with a retry (transient error)", sum(r["retries"] for r in runs), N)
A("LLM cached calls (all runs)", sum(int(r["llm_cached_calls"] or 0) for r in runs), sum(r["llm_calls"] for r in runs))
for k in ("steps", "hosts_ir", "hosts_env_plan", "dependency_edges", "missing_ir", "missing_after_mod4", "open_blocker_items"):
    xs = [r[k] for r in ok if r[k] != ""]
    if xs: A(f"{k}: total / median / p90 / min / max (non-crashed runs)", f"{sum(xs)} / {statistics.median(xs)} / {q(xs, .9)} / {min(xs)} / {max(xs)}", len(xs))
A("runs with 0 steps", sum(1 for r in ok if r["steps"] == 0), len(ok))
tq = sum(r["quotes"] for r in runs); tf = sum(r["quotes_found"] for r in runs)
A("step quotes found verbatim in source.pdf.txt (normalised)", pct(tf, tq), tq)
A("secondary: step quotes found in source.pdf.txt OR in non-layout pdftotext of source.pdf", pct(nf2[0], tq), tq)
A("step quotes the product itself marks quote_verified=true", pct(agree_tot[2], agree_tot[0]), agree_tot[0])
A("agreement: our verbatim check vs product quote_verified", pct(agree_tot[1], agree_tot[0]), agree_tot[0])
A("steps with >= 1 quote", pct(sum(1 for s in steps if s["n_quotes"]), len(steps)), len(steps))
A("steps whose quotes are ALL found", pct(sum(1 for s in steps if s["n_quotes"] and s["n_quotes_found"] == s["n_quotes"]), sum(1 for s in steps if s["n_quotes"])))
pr = [r["quotes_found"] / r["quotes"] for r in runs if r["quotes"]]
if pr: A("per-run quote-found share: median / min", f"{statistics.median(pr):.3f} / {min(pr):.3f}", len(pr))
ta = sum(r["attack_ids"] for r in runs)
A("steps with an ATT&CK id", pct(ta, len(steps)), len(steps))
A("ATT&CK ids valid (active in Enterprise v20.1)", pct(sum(r["attack_valid"] for r in runs), ta), ta)
A("ATT&CK ids revoked/deprecated in v20.1", pct(sum(r["attack_revoked_or_deprecated"] for r in runs), ta), ta)
A("ATT&CK ids whose id string appears in source.pdf.txt", pct(sum(r["attack_in_source"] for r in runs), ta), ta)
rc = collections.Counter(s["reproducibility"] or "(none)" for s in steps)
for k, v in rc.most_common(): A(f"step reproducibility = {k}", pct(v, len(steps)), len(steps))
fc = collections.Counter(r["fidelity"] or "(none)" for r in ok)
for k, v in fc.most_common(): A(f"run fidelity = {k}", v, len(ok))
ic = collections.Counter(r["iac_deployable"] or "(no report)" for r in runs)
for k, v in sorted(ic.items()): A(f"module-6 deployable = {k}", v, N)
bc = collections.Counter(c for r in runs for c in r["iac_blockers"].split())
for k, v in bc.most_common(): A(f"module-6 blocker code {k} (runs)", sum(1 for r in runs if k in r["iac_blockers"].split()), N)
cost = [float(r["llm_cost_incl_failed_attempt_usd"]) for r in runs if r["llm_cost_incl_failed_attempt_usd"] != ""]
wall = [float(r["wall_s"]) for r in runs if r["wall_s"] != ""]
if cost: A("eligible-set LLM cost USD per report: median / p90 / max / total", f"{statistics.median(cost):.4f} / {q(cost,.9):.4f} / {max(cost):.4f} / {sum(cost):.4f}", len(cost))
if wall: A("modules 1/2/4/5 subprocess time s per report (run_real.py only; excludes module 6): median / p90 / max / sum", f"{statistics.median(wall):.1f} / {q(wall,.9):.1f} / {max(wall):.1f} / {sum(wall):.1f}", len(wall))
for cat in sorted({r["category"] for r in runs}):
    rr = [r for r in runs if r["category"] == cat]
    A(f"category {cat}: runs / finished / blocked / crashed / deployable", f"{len(rr)} / {sum(r['outcome']=='finished' for r in rr)} / {sum(r['outcome']=='system-blocked' for r in rr)} / {sum(r['outcome']=='crashed' for r in rr)} / {sum(r['iac_deployable']=='yes' for r in rr)}")
wcsv("eval-200-aggregate.csv", agg)
for a in agg: print(f"| {a['metric']} | {a['value']} | {a['denominator']} |")

# ---- quote tables (from qrec) ----
with open(E / "eval-200-quotes.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(qrec[0])); w.writeheader(); w.writerows(qrec)
t = collections.Counter((x["found_primary"], x["product_verified"]) for x in qrec)
print("\n2x2 (primary found, product verified):", dict(t))
for k, v in sorted(collections.Counter(x["cause"] for x in qrec if x["cause"]).items()): print("cause", v, k)
# ---- input check: report.md body == body the run used ----
def body(tx): return tx.split("\n\n", 2)[2] if tx.startswith("# ") else tx
def body_after_header(tx):
    i = tx.find("\n\n", tx.find("> - Text:")); return tx[i + 2:]
same = sum(body_after_header((C / r["id"] / "report.md").read_text()) == body_after_header((R / r["id"] / "00-input.txt").read_text()) for r in runs)
print("report.md body identical to run input body:", same, "/", len(runs))
# ---- actual spend of the whole batch (all run dirs on disk, incl. excluded items) and ledger export ----
import sqlite3
allm = {m.parent.name: load(m) for m in R.glob("*/meta.json")}
elig = {r["id"] for r in runs}
print("actual spend all runs:", len(allm), round(sum(m.get("llm_cost_incl_failed_attempt_usd", 0) for m in allm.values()), 4),
      "| eligible:", len(elig), round(sum(allm[i].get("llm_cost_incl_failed_attempt_usd", 0) for i in elig), 4),
      "| excluded:", len(allm) - len(elig), round(sum(m.get("llm_cost_incl_failed_attempt_usd", 0) for k, m in allm.items() if k not in elig), 4))
led = []
for dd in sorted((ROOT / ".data-eval200").glob("*/llm_ledger.db")):
    with sqlite3.connect(dd) as c:
        for row in c.execute("SELECT ts, purpose, model, input_tokens, output_tokens, est_cost_usd, cached FROM ledger"):
            led.append({"run_id": dd.parent.name, "eligible": dd.parent.name in elig, **dict(zip(["ts", "purpose", "model", "input_tokens", "output_tokens", "est_cost_usd", "cached"], row))})
if led:
    with open(E / "eval-200-ledger.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(led[0])); w.writeheader(); w.writerows(led)
    print("ledger rows", len(led), "cost", round(sum(x["est_cost_usd"] for x in led), 4), "cached", sum(x["cached"] for x in led))
