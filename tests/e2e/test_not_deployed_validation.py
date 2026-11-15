"""The validator must honestly reflect a plan host the environment did not deploy
(infra-eng not_deployed_hosts): its service and any action targeting it are
NOT_TESTED-not-deployed, env_build is not a clean PASS, full_chain cannot PASS.
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
def test_not_deployed_host_is_reported_not_tested():
    sid = f"poc-nd-{uuid.uuid4().hex[:6]}"
    reason = "報告只說資料存放在資料庫，沒有指出資料庫產品；沒有可部署的服務"
    ir = {
        "schema_version": "1.0", "id": sid, "name": "not-deployed host validation",
        "provenance": {"input_kind": "text", "input_sha256": "0" * 64},
        "actions": [
            {"id": "a1", "name": "reach web", "target_host_ref": "web", "source": "user", "epistemic_status": "supported"},
            {"id": "a2", "name": "query the database", "target_host_ref": "db", "source": "user", "epistemic_status": "supported"},
        ],
        "relations": [],
        "environment_plan": {
            "hosts": [
                {"id": "attacker", "role": "attacker", "image_hint": "oss-attacker",
                 "component_mode": "real", "networks": ["dmz"]},
                {"id": "web", "role": "web", "image_hint": "demo-api", "component_mode": "substitute",
                 "services": [{"name": "http", "port": 8080, "protocol": "tcp"}], "networks": ["dmz"]},
                {"id": "db", "role": "database", "deployable": False, "not_deployed_reason": reason,
                 "services": [{"name": "sql", "port": 5432, "protocol": "tcp"}], "networks": ["dmz"]},
            ],
            "networks": [{"id": "dmz", "internal": True}],
            "connections": [
                {"from_host": "attacker", "to_host": "web", "port": 8080, "protocol": "tcp",
                 "reason": "Scenario action(s) a1 require access to web."},
                {"from_host": "attacker", "to_host": "db", "port": 5432, "protocol": "tcp",
                 "reason": "Scenario action(s) a2 require access to db."},
            ],
            "verify_blocked": [],
        },
    }
    with tempfile.TemporaryDirectory(prefix="cr-poc-nd-") as tmp:
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
                    report = client.post(f"/api/validate/{sid}/run").json()
                finally:
                    client.post(f"/api/deploy/{sid}/down")

    # The not-deployed host is reported with its reason.
    nd_ids = {item["host_id"] for item in report["not_deployed"]}
    assert "db" in nd_ids, report["not_deployed"]
    assert report["deployed_host_ids"] and "db" not in report["deployed_host_ids"]

    checks = {c["id"]: c for c in report["checks"]}
    assert checks["service-up-db"]["status"] == "NOT_TESTED"
    assert "未部署" in checks["service-up-db"]["observed"]

    # env_build must not be a clean PASS while a host is missing.
    assert report["levels"]["env_build"] == "PARTIAL", report["levels"]

    # The action targeting the not-deployed host is NOT_TESTED with the reason.
    action_db = checks["action-a2"]
    assert action_db["status"] == "NOT_TESTED"
    assert "未部署" in action_db["observed"]

    # full_chain cannot be PASS when behaviors are unverified.
    assert report["levels"]["full_chain"] != "PASS", report["levels"]
