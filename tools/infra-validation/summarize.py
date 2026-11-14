"""Print a compact summary of a lifecycle_probe.py evidence file."""
import json
import sys

d = json.load(open(sys.argv[1]))
print("scenario", d["scenario_id"])
for s in d["steps"]:
    r, n = s["result"], s["step"]
    if n.startswith("validate"):
        b = r["body"]
        print(n, r["status"], b.get("levels") or json.dumps(b, ensure_ascii=False)[:300])
        for c in b.get("checks", []):
            print("   ", c["id"], c["status"], "|", c["observed"].replace("\n", " ")[:110])
    elif n.startswith("up"):
        b = r["body"]
        b = b.get("detail") or b
        print(n, r["status"], f"{r['seconds']}s", "attempts=", b.get("attempts"),
              [(c["service"], c["state"], c["health"], [p["host_port"] for p in c.get("ports", [])]) for c in b.get("containers") or []])
        if r["status"] != 200:
            print("   error:", str(b.get("error"))[-600:])
            print("   diagnostics:", json.dumps(b.get("diagnostics"), ensure_ascii=False)[:3000])
            print("   cleanup:", b.get("cleanup"))
    elif n == "generate":
        rep = r["body"].get("report") if r["status"] == 200 else None
        if rep:
            print(n, 200, "ports=", rep.get("host_port_mappings"))
            for c in rep["components"]:
                print("   ", c["host_id"], c["component"], c.get("exposure"), "published=", c.get("published"),
                      "hc=", c.get("healthcheck"), c.get("limits"), "wired=", c.get("wired_to"))
        else:
            print(n, r["status"], json.dumps(r["body"], ensure_ascii=False)[:1500])
    elif n == "records":
        print(n, [(x["action"], x["state"]) for x in r["records"]])
    elif n.startswith(("status", "health")):
        print(n, r.get("state"))
    else:
        print(n, json.dumps(r, ensure_ascii=False)[:300])
