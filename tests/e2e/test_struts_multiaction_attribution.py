"""Honesty: one Struts probe must reproduce ONLY the exploitation action (T1190),
not every action that happens to target the same host (frontend-eng finding).

Deploys vulhub Struts with four actions all targeting the web host — scan (T1595),
discovery (T1046), exploit (T1190), defense-evasion (T1070) — and asserts that only
the T1190 action is reproduced; the others are NOT_TESTED ("indirectly covered, not
individually verified") and excluded from fidelity.reproduced, and full_chain is not
PASS while behaviors remain unverified.
"""
from __future__ import annotations

import tempfile
import time
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
def test_only_the_exploit_action_is_reproduced():
    sid = f"poc-sm-{uuid.uuid4().hex[:6]}"

    def act(i, name, tech):
        return {"id": f"a{i}", "name": name, "target_host_ref": "web",
                "attack_technique": tech, "source": "user", "epistemic_status": "supported"}

    ir = {
        "schema_version": "1.0", "id": sid, "name": "struts multi-action attribution",
        "provenance": {"input_kind": "text", "input_sha256": "0" * 64},
        "actions": [
            act(1, "Scan the web server", "T1595"),
            act(2, "Discover the vulnerable endpoint", "T1046"),
            act(3, "Gain access via Struts S2-045", "T1190"),
            act(4, "Hide activity / clear traces", "T1070"),
        ],
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
            # One lumped connection naming every action, like the real planner produces.
            "connections": [{"from_host": "attacker", "to_host": "web", "port": 8080, "protocol": "tcp",
                             "reason": "Scenario action(s) a1, a2, a3, a4 require access to struts."}],
            "verify_blocked": [],
        },
    }
    with tempfile.TemporaryDirectory(prefix="cr-poc-sm-") as tmp:
        data = Path(tmp) / "data"
        data.mkdir()
        with patch.object(config, "DATA_DIR", data), patch.object(store, "_DB", data / "scenarios.db"):
            store.create(ir)
            with TestClient(app) as client:
                assert client.post(f"/api/iac/{sid}/generate").status_code == 200
                assert client.post(f"/api/planning/{sid}/topology/approve",
                                   json={"approved": True, "approved_by": "poc-eng"}).status_code == 200
                up = None
                for _ in range(3):
                    up = client.post(f"/api/deploy/{sid}/up", json={"test_approved": True})
                    if up.status_code == 200:
                        break
                    time.sleep(15)
                if up.status_code != 200:
                    pytest.skip(f"lab could not stand up (transient infra): {up.text[:200]}")
                try:
                    report = None
                    deadline = time.time() + 180
                    while time.time() < deadline:
                        report = client.post(f"/api/validate/{sid}/run").json()
                        a3 = next((c for c in report["checks"] if c["id"] == "action-a3"), None)
                        if a3 and a3["status"] == "PASS":
                            break
                        time.sleep(6)
                finally:
                    client.post(f"/api/deploy/{sid}/down")

    checks = {c["id"]: c for c in report["checks"]}
    assert checks["action-a3"]["status"] == "PASS", checks["action-a3"]["observed"]
    for other in ("a1", "a2", "a4"):
        assert checks[f"action-{other}"]["status"] == "NOT_TESTED", checks[f"action-{other}"]
        assert "間接涵蓋" in checks[f"action-{other}"]["observed"]
    assert report["fidelity"]["reproduced"] == ["a3"], report["fidelity"]["reproduced"]
    for other in ("a1", "a2", "a4"):
        assert other in report["fidelity"]["not_tested"]
    assert report["levels"]["full_chain"] != "PASS", report["levels"]
