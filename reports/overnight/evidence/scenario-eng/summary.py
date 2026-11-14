"""One-screen comparison summary of an evidence run directory."""
import json, sys, pathlib, collections
for d in sys.argv[1:]:
    d = pathlib.Path(d)
    ir = json.loads((d / "01-ir.json").read_text()); dep = json.loads((d / "02-dependencies.json").read_text())
    t = json.loads((d / "03-topology.json").read_text()); ev = {e["id"]: e for e in ir["evidence"]}
    print(f"\n#### {d.name}")
    print(" actions:", len(ir["actions"]), collections.Counter(a["epistemic_status"] for a in ir["actions"]).most_common(),
          "| excluded non-attacker:", len(ir["quality"].get("excluded_non_attacker_actions", [])))
    print(" relations:", collections.Counter((r["kind"], r["epistemic_status"]) for r in ir["relations"]).most_common())
    for r in ir["relations"]:
        q = " / ".join(ev[x]["quote"][:70] for x in r["evidence_refs"]) or r.get("rationale", "")[:70]
        print(f"   {r['from_action']}->{r['to_action']} {r['kind'][:4]} {r['epistemic_status'][:5]} | {q}")
    print(" hosts:", [(h["id"], h.get("name") or h["role"][:40], h["epistemic_status"]) for h in ir["hosts"]])
    print(" action hosts:", [(a["id"], a.get("source_host_ref", ""), a["target_host_ref"]) for a in ir["actions"]])
    print(" services(IR):", [(s["id"], s["name"], s.get("host_ref"), s.get("version"), s.get("port"), s.get("cve")) for s in ir["services"]])
    print(" services(planned):", [(s["id"], s["name"], s.get("host_ref"), s.get("catalogue_component") or ("no_component" if s.get("no_component") else None), s.get("version"), s.get("port")) for s in dep["services"]])
    print(" artifacts:", [a.get("name") for a in ir["artifacts"]])
    print(" techniques:", [(a["id"], a.get("attack_technique"), a.get("attack_tactic")) for a in ir["actions"] if a.get("attack_technique")])
    print(" indicators:", [(i["type"], i["value"]) for i in ir["indicators"]])
    print(" open questions:", [m["id"] for m in dep["missing_items"] if m["status"] == "open"])
    print(" env hosts:", [(h["id"], h["networks"], h.get("exposure_basis"), h.get("image_hint"), h.get("runtime"), h.get("component_mode"), h.get("deployable")) for h in t["hosts"]])
    print(" connections:", [(c["from_host"], c["to_host"], c["port"]) for c in t.get("connections", [])],
          "| must-block:", [(c["from_host"], c["to_host"], c["port"]) for c in t.get("verify_blocked", [])])
