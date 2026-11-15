"""Real check of the round-2 deployment findings, driven through the same API routes as the GUI.

  CR_DATA_DIR=$PWD/.data PYTHONPATH=apps/api python tools/infra-validation/repeat_up_probe.py <plan.json>

1. a scenario with no generated IaC reports "not_created", not "error";
2. preflight shows isolation + capacity before deploying;
3. `up` twice: the second call must keep every container ID and the published port;
4. after the plan changes (IaC stale) status still shows the running containers and
   `down` still removes them.
"""
from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from app import store
from app.main import app

plan = json.loads(Path(sys.argv[1]).read_text())
plan.pop("_actions", None)
sid = f"infra-eng-{uuid.uuid4().hex[:8]}"
project = f"cr-demo-{sid}"


def ids() -> dict:
    out = subprocess.run(["docker", "ps", "--filter", f"name={project}-", "--format", "{{.Names}} {{.ID}} {{.Ports}}"],
                         capture_output=True, text=True).stdout
    return {line.split()[0].replace(project + "-", ""): " ".join(line.split()[1:]) for line in out.splitlines()}


def show(label, value):
    print(f"## {label}\n   {json.dumps(value, ensure_ascii=False, default=str)[:1500]}")


store.create({"schema_version": "1.0", "id": sid, "name": "infra-eng repeat-up probe",
              "provenance": {"input_kind": "text", "input_sha256": "0" * 64},
              "actions": [], "relations": [], "environment_plan": plan})
with TestClient(app) as client:
    try:
        status = client.get(f"/api/deploy/{sid}/status").json()
        health = client.get(f"/api/deploy/{sid}/health").json()
        show("1. before any IaC exists: status / health", {"status.state": status["state"], "status.iac": status["iac"],
                                                          "status.error": status["error"], "health.state": health["state"]})
        assert client.post(f"/api/iac/{sid}/generate").status_code == 200
        client.post(f"/api/planning/{sid}/topology/approve", json={"approved": True, "approved_by": "infra-eng"})
        pre = client.get(f"/api/deploy/{sid}/preflight").json()
        show("2. preflight before deploying", {"iac": pre["iac"], "current_state": pre["current_state"],
                                               "isolation.ok": pre["isolation"]["ok"],
                                               "isolation.vulnerable_hosts": pre["isolation"]["vulnerable_hosts"],
                                               "capacity": pre["capacity"]})
        first = client.post(f"/api/deploy/{sid}/up", json={"test_approved": True}).json()
        first_ids = ids()
        show("3a. first up", {"ok": first["ok"], "already_running": first["already_running"],
                              "published_ports": first["published_ports"], "containers": first_ids})
        second = client.post(f"/api/deploy/{sid}/up", json={"test_approved": True}).json()
        second_ids = ids()
        show("3b. second up while running", {"ok": second["ok"], "already_running": second["already_running"],
                                             "message": second.get("message"),
                                             "published_ports": second["published_ports"], "containers": second_ids})
        show("3c. container IDs and ports identical after the second up", first_ids == second_ids)
        show("3d. status now reports the same ports", client.get(f"/api/deploy/{sid}/status").json()["published_ports"])

        # the plan changes after deployment: the generated file no longer matches it
        ir = store.get(sid)
        ir["environment_plan"]["hosts"][0]["role"] += " (edited)"
        ir["environment_plan"].setdefault("notes", []).append("edited after deployment")
        ir["environment_plan"]["connections"] = ir["environment_plan"].get("connections", [])[:-1]
        store.save(ir) if hasattr(store, "save") else store.update(sid, ir)
        stale = client.get(f"/api/deploy/{sid}/status").json()
        show("4a. plan edited after deployment: status still sees the running containers",
             {"iac": stale["iac"], "state": stale["state"], "containers": len(stale["containers"])})
        down = client.post(f"/api/deploy/{sid}/down")
        show("4b. down with a stale IaC", {"http": down.status_code, "state": down.json().get("state"),
                                          "removed_local_images": down.json()["deployment_record"]["details"].get("removed_local_images")})
        show("4c. docker afterwards", {"containers": ids(), "networks": subprocess.run(
            ["docker", "network", "ls", "--filter", f"name={project}", "--format", "{{.Name}}"],
            capture_output=True, text=True).stdout.split()})
        show("audit records", [(r["action"], r["state"], bool(r["details"].get("already_running")))
                               for r in client.get(f"/api/deploy/{sid}/records").json()["records"]])
    finally:
        subprocess.run(["docker", "compose", "-p", project, "down", "-v"], capture_output=True)
