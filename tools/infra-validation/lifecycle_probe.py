"""Real (non-mocked) lifecycle probe for modules 6-7, run in-process against a throwaway data dir.

Usage (from the worktree root):
  CR_DATA_DIR=$PWD/.data PYTHONPATH=apps/api python tools/infra-validation/lifecycle_probe.py <plan.json> <out.json> [--keep]

It drives the same FastAPI routes the GUI uses (generate -> approve -> up -> status ->
health -> validate -> down -> redeploy -> down) and records every response, plus
`docker compose config` of the generated file and post-teardown leftovers. Nothing is
asserted here; the output is evidence for reports/overnight/INFRA-VALIDATION.md.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from app import store
from app.iac.generator import generated_dir
from app.main import app


def sh(args: list[str], timeout: int = 60) -> dict:
    done = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    return {"cmd": " ".join(args), "rc": done.returncode, "out": done.stdout[-6000:], "err": done.stderr[-3000:]}


def leftovers(project: str) -> dict:
    return {
        "containers": sh(["docker", "ps", "-a", "--filter", f"name={project}", "--format", "{{.Names}} {{.Status}}"])["out"].split("\n"),
        "networks": sh(["docker", "network", "ls", "--filter", f"name={project}", "--format", "{{.Name}}"])["out"].split("\n"),
        "volumes": sh(["docker", "volume", "ls", "--filter", f"name={project}", "--format", "{{.Name}}"])["out"].split("\n"),
    }


def wait_health(client: TestClient, sid: str, seconds: int = 60) -> dict:
    last = {}
    for _ in range(seconds):
        last = client.get(f"/api/deploy/{sid}/health").json()
        if last.get("state") != "starting":
            break
        time.sleep(1)
    return last


def main() -> int:
    plan = json.loads(Path(sys.argv[1]).read_text())
    out_path = Path(sys.argv[2])
    sid = f"infra-eng-{uuid.uuid4().hex[:8]}"
    project = f"cr-demo-{sid}"
    log: dict = {"scenario_id": sid, "steps": []}

    def step(name: str, value) -> None:
        log["steps"].append({"step": name, "at": time.strftime("%H:%M:%S"), "result": value})
        out_path.write_text(json.dumps(log, ensure_ascii=False, indent=2))

    store.create({"schema_version": "1.0", "id": sid, "name": "infra-eng lifecycle probe",
                  "provenance": {"input_kind": "text", "input_sha256": "0" * 64},
                  "actions": plan.pop("_actions", []), "relations": [], "environment_plan": plan})
    with TestClient(app) as client:
        try:
            r = client.post(f"/api/iac/{sid}/generate")
            step("generate", {"status": r.status_code, "body": r.json()})
            if r.status_code != 200:
                return 1
            compose = generated_dir(sid) / "docker-compose.yml"
            env = ["env", "CR_PG_PASSWORD=x"]
            step("docker_compose_config", sh(env + ["docker", "compose", "-f", str(compose), "config", "--quiet"]))
            r = client.post(f"/api/planning/{sid}/topology/approve", json={"approved": True, "approved_by": "infra-eng"})
            step("approve", {"status": r.status_code})
            for round_no in (1, 2):
                t0 = time.time()
                r = client.post(f"/api/deploy/{sid}/up", json={"test_approved": True})
                step(f"up_{round_no}", {"status": r.status_code, "seconds": round(time.time() - t0, 1), "body": r.json()})
                step(f"status_{round_no}", client.get(f"/api/deploy/{sid}/status").json())
                step(f"health_{round_no}", wait_health(client, sid))
                step(f"docker_ps_{round_no}", sh(["docker", "ps", "-a", "--filter", f"name={project}", "--format",
                                                  "{{.Names}}|{{.Image}}|{{.Status}}|{{.Ports}}"]))
                r = client.post(f"/api/validate/{sid}/run")
                step(f"validate_{round_no}", {"status": r.status_code, "body": r.json()})
                if "--keep" in sys.argv and round_no == 1:
                    step("kept", project)
                    return 0
                r = client.post(f"/api/deploy/{sid}/down")
                step(f"down_{round_no}", {"status": r.status_code, "state": r.json().get("state") if r.status_code == 200 else r.json()})
                step(f"leftovers_{round_no}", leftovers(project))
            step("records", client.get(f"/api/deploy/{sid}/records").json())
        finally:
            if "--keep" not in sys.argv:
                sh(["docker", "compose", "-p", project, "down", "-v"], timeout=120)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
