import json, sys, tempfile, time, uuid
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import config, store
from app.main import app
sid = f"review-poc-{uuid.uuid4().hex[:6]}"
ir = {"schema_version": "1.0", "id": sid, "name": "reviewer real run",
 "provenance": {"input_kind": "text", "input_sha256": "0"*64},
 "actions": [{"id": f"a{i}", "name": f"step {i}", "source": "user", "epistemic_status": "supported"} for i in range(1,5)], "relations": [],
 "environment_plan": {
  "hosts": [
   {"id": "attacker", "role": "attacker", "image_hint": "demo-client", "networks": ["outer"]},
   {"id": "web", "role": "web", "image_hint": "demo-api", "services": [{"name":"http","port":8080,"protocol":"tcp"}], "networks": ["outer"]},
   {"id": "web2", "role": "web", "image_hint": "demo-api", "services": [{"name":"http","port":8080,"protocol":"tcp"}], "networks": ["inner"]},
  ],
  "networks": [{"id": "outer", "internal": True}, {"id": "inner", "internal": True}],
  "connections": [{"from_host": "attacker", "to_host": "web", "port": 8080, "protocol": "tcp",
     "reason": "Scenario action(s) a1, a2, a3, a4 require access to web server (substitute)."}],
  "verify_blocked": [
   {"from_host": "attacker", "to_host": "web2", "port": 8080, "protocol": "tcp", "reason": "truly segmented"},
   {"from_host": "attacker", "to_host": "web", "port": 9999, "protocol": "tcp", "reason": "same net, closed port"}],
 }}
with tempfile.TemporaryDirectory(prefix="cr-review-") as t:
    d = Path(t)/"data"; d.mkdir()
    with patch.object(config, "DATA_DIR", d), patch.object(store, "_DB", d/"scenarios.db"):
        store.create(ir)
        with TestClient(app) as c:
            try:
                r = c.post(f"/api/iac/{sid}/generate"); assert r.status_code == 200, r.text
                r = c.post(f"/api/planning/{sid}/topology/approve", json={"approved": True, "approved_by": "reviewer"}); assert r.status_code == 200, r.text
                r = c.post(f"/api/deploy/{sid}/up", json={"test_approved": True}); assert r.status_code == 200, r.text
                for _ in range(30):
                    if c.get(f"/api/deploy/{sid}/health").json().get("state") != "starting": break
                    time.sleep(0.5)
                rep = c.post(f"/api/validate/{sid}/run").json()
                json.dump(rep, open(sys.argv[1], "w"), ensure_ascii=False, indent=1)
                print(rep.get("levels"))
                for ch in rep.get("checks", []):
                    print(ch["id"], ch["status"], "|", ch.get("action_ref"), "|", ch["observed"][:150])
            finally:
                print("down:", c.post(f"/api/deploy/{sid}/down").status_code)
