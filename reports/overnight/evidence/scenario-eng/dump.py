"""Compact human-readable dump of an evidence run directory (IR, deps, topology)."""
import json, sys, pathlib
d = pathlib.Path(sys.argv[1])
ir = json.loads((d / "01-ir.json").read_text())
ev = {e["id"]: e for e in ir["evidence"]}
def refs(x):
    return " | ".join(f"[{ev[r]['locator']['ref']}:{ev[r]['quote_match']}] {ev[r]['quote'][:110]!r}" for r in x.get("evidence_refs", []))
print("== ACTIONS")
for a in ir["actions"]:
    print(f"{a['id']} [{a['epistemic_status']}] {a['name']} | host={a.get('target_host_ref')} | {a.get('attack_technique','-')}/{a.get('attack_tactic','-')}\n     {refs(a)}")
print("== RELATIONS")
for r in ir["relations"]:
    print(f"{r['id']} {r['from_action']}->{r['to_action']} {r['kind']} [{r['epistemic_status']}] {r.get('rationale','')[:80]}\n     {refs(r)}")
print("== HOSTS"); [print(" ", {k: v for k, v in h.items() if k != 'evidence_refs'}, refs(h)) for h in ir["hosts"]]
print("== SERVICES"); [print(" ", {k: v for k, v in s.items() if k != 'evidence_refs'}, refs(s)) for s in ir["services"]]
print("== ARTIFACTS"); [print(" ", {k: v for k, v in s.items() if k != 'evidence_refs'}) for s in ir["artifacts"]]
print("== INDICATORS", [(i["type"], i["value"]) for i in ir["indicators"]])
print("== COMMANDS", [c["command"][:80] for c in ir["commands"]])
print("== MISSING"); [print(" ", m["id"], "|", m["field"], "|", m["question"][:100]) for m in ir["missing_items"]]
if (d / "02-dependencies.json").exists():
    dep = json.loads((d / "02-dependencies.json").read_text())
    print("== DEP HOSTS"); [print(" ", {k: v for k, v in h.items() if k != 'evidence_refs'}) for h in dep["hosts"]]
    print("== DEP SERVICES"); [print(" ", {k: v for k, v in s.items() if k != 'evidence_refs'}) for s in dep["services"]]
    print("== DEP MISSING(planner)"); [print(" ", m["id"], m["status"], "|", m["field"]) for m in dep["missing_items"] if m["id"].startswith("planner_")]
    print("== DEP action hosts", [(a["id"], a.get("target_host_ref")) for a in dep["actions"]])
    print("== reproducibility", json.dumps(dep.get("reproducibility"), ensure_ascii=False)[:600])
if (d / "03-topology.json").exists():
    print("== TOPOLOGY"); print(json.dumps(json.loads((d / "03-topology.json").read_text()), ensure_ascii=False)[:2500])
