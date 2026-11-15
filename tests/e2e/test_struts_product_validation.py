"""Mainline: the PRODUCT deploy+validate flow runs an action-specific attack probe
against the real Struts S2-045 image and marks the behavior reproduced (AR2-04).

Deploys vulhub/struts2:2.3.30 through the API (generate -> approve -> up), runs
validation, and asserts:
  - the validator executed the OGNL arithmetic probe (vulhub=54289),
  - the scenario action is PASS (reproduced), behavior_repro is PASS,
  - a benign liveness HTTP 200 alone never produced that verdict.
Skipped if Docker is unavailable or the lab cannot stand up (transient infra).
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import config, store
from app.deploy import manager
from app.main import app


def _docker_ready() -> bool:
    docker, error = manager._docker_context_preflight()
    if error or not docker:
        return False
    return manager._run([docker, "info"], timeout=20)["returncode"] == 0


@pytest.mark.skipif(not _docker_ready(), reason="Docker/compose not available")
def test_struts_s2045_action_is_reproduced_through_product_flow():
    sid = f"poc-struts-{uuid.uuid4().hex[:6]}"
    ir = {
        "schema_version": "1.0", "id": sid, "name": "struts s2-045 product validation",
        "provenance": {"input_kind": "text", "input_sha256": "0" * 64},
        "actions": [{"id": "a1", "name": "Exploit Struts S2-045 (OGNL RCE)", "target_host_ref": "web",
                     "source": "user", "epistemic_status": "supported"}],
        "relations": [],
        "environment_plan": {
            "hosts": [
                {"id": "attacker", "role": "attacker", "image_hint": "oss-attacker",
                 "component_mode": "real", "networks": ["dmz"]},
                {"id": "web", "role": "exposed web application", "image_hint": "vuln-struts2-s2-045",
                 "component_mode": "real",
                 "services": [{"name": "struts", "port": 8080, "protocol": "tcp"}], "networks": ["dmz"]},
            ],
            "networks": [{"id": "dmz", "internal": True}],
            "connections": [{"from_host": "attacker", "to_host": "web", "port": 8080, "protocol": "tcp",
                             "reason": "Scenario action(s) a1 require access to struts."}],
            "verify_blocked": [],
        },
    }
    with tempfile.TemporaryDirectory(prefix="cr-poc-struts-") as tmp:
        data = Path(tmp) / "data"
        data.mkdir()
        with patch.object(config, "DATA_DIR", data), patch.object(store, "_DB", data / "scenarios.db"):
            store.create(ir)
            with TestClient(app) as client:
                assert client.post(f"/api/iac/{sid}/generate").status_code == 200
                assert client.post(f"/api/planning/{sid}/topology/approve",
                                   json={"approved": True, "approved_by": "poc-eng"}).status_code == 200
                up = client.post(f"/api/deploy/{sid}/up", json={"test_approved": True})
                if up.status_code != 200:
                    pytest.skip(f"lab could not stand up (transient infra): {up.text[:200]}")
                try:
                    # Struts/Tomcat needs a moment to serve; poll validation briefly.
                    report = None
                    for _ in range(10):
                        report = client.post(f"/api/validate/{sid}/run").json()
                        attack = next((c for c in report["checks"]
                                       if c["id"].startswith("attack-") and c["status"] in {"PASS", "FAIL"}), None)
                        if attack:
                            break
                        import time
                        time.sleep(5)
                finally:
                    client.post(f"/api/deploy/{sid}/down")

    attack = next((c for c in report["checks"] if c["id"].startswith("attack-")), None)
    assert attack is not None, "no action-specific attack check was produced"
    assert attack["status"] == "PASS", f"OGNL probe did not reproduce: {attack['observed']}"
    assert "54289" in attack["observed"], attack["observed"]
    action = next(c for c in report["checks"] if c["id"] == "action-a1")
    assert action["status"] == "PASS", action["observed"]
    assert report["levels"]["behavior_repro"] == "PASS", report["levels"]
    assert "a1" in report["fidelity"]["reproduced"]
