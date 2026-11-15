"""Mainline: the PRODUCT deploy+validate flow reproduces real Log4Shell (CVE-2021-44228)
against vulhub Solr using the in-lab cr-listener (infra-eng platform component).

Deploys vulhub/solr:8.11.0 + the auto-added cr-listener through the API, runs
validation, and asserts the validator's action-specific probe observed a real LDAP
callback from the Solr host (benign request produced none), marking the action
reproduced. Skipped if Docker is unavailable or the lab cannot stand up.
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
def test_log4shell_action_is_reproduced_through_product_flow():
    sid = f"poc-l4s-{uuid.uuid4().hex[:6]}"
    ir = {
        "schema_version": "1.0", "id": sid, "name": "log4shell product validation",
        "provenance": {"input_kind": "text", "input_sha256": "0" * 64},
        "actions": [{"id": "a1", "name": "Exploit Log4Shell JNDI callback", "target_host_ref": "solr",
                     "source": "user", "epistemic_status": "supported"}],
        "relations": [],
        "environment_plan": {
            "hosts": [
                {"id": "attacker", "role": "attacker", "image_hint": "oss-attacker",
                 "component_mode": "real", "networks": ["dmz"]},
                {"id": "solr", "role": "exposed web application", "image_hint": "vuln-log4shell-solr",
                 "component_mode": "real",
                 "services": [{"name": "solr", "port": 8983, "protocol": "tcp"}], "networks": ["dmz"]},
            ],
            "networks": [{"id": "dmz", "internal": True}],
            "connections": [{"from_host": "attacker", "to_host": "solr", "port": 8983, "protocol": "tcp",
                             "reason": "Scenario action(s) a1 require access to solr."}],
            "verify_blocked": [],
        },
    }
    with tempfile.TemporaryDirectory(prefix="cr-poc-l4s-") as tmp:
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
                    report = None
                    for _ in range(12):  # Solr/JVM needs time before the logged lookup fires
                        report = client.post(f"/api/validate/{sid}/run").json()
                        attack = next((c for c in report["checks"]
                                       if c["id"].startswith("attack-") and c["status"] in {"PASS", "FAIL"}), None)
                        if attack and attack["status"] == "PASS":
                            break
                        time.sleep(6)
                finally:
                    client.post(f"/api/deploy/{sid}/down")

    attack = next((c for c in report["checks"] if c["id"].startswith("attack-")), None)
    assert attack is not None, "no action-specific attack check was produced"
    assert attack["status"] == "PASS", f"Log4Shell callback not reproduced: {attack['observed']}"
    action = next(c for c in report["checks"] if c["id"] == "action-a1")
    assert action["status"] == "PASS", action["observed"]
    assert report["levels"]["behavior_repro"] == "PASS", report["levels"]
    assert "a1" in report["fidelity"]["reproduced"]
