"""Real-Docker regression test for segmentation judgement (reviewer P2 / R6).

Deploys a three-host plan where:
  - attacker and web share the `outer` network (reachable), web listens on 8080
    but NOT on 9999;
  - web2 is on a separate `inner` network (genuinely segmented from attacker).

Correct, honest outcomes the validator must produce:
  - attacker -> web2:8080  => segmentation PASS   (network truly unreachable)
  - attacker -> web:9999   => segmentation NOT_TESTED (port refused on a SHARED
    network is not proof of segmentation)

Before infra-eng fixed `manager.container_ipv4` to prefer an address on a network
the source shares, the web:9999 probe hit web's publish-only `edge` address and
came back "network unreachable", which the validator mis-scored as PASS. This test
fails in that state and passes once the shared-network address is probed, so it
guards the fix against regression.

Skipped (not failed) when Docker/compose is unavailable or the environment cannot
stand the lab up (e.g. a host-port collision with another lab on this shared host),
so transient infra noise never masquerades as a validator defect.
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


def _find(checks, needle):
    return next(c for c in checks if needle in c["name"] and c["category"] == "segmentation")


@pytest.mark.skipif(not _docker_ready(), reason="Docker/compose not available")
def test_same_network_closed_port_is_not_scored_as_segmentation():
    sid = f"poc-seg-{uuid.uuid4().hex[:6]}"
    ir = {
        "schema_version": "1.0", "id": sid, "name": "segmentation real test",
        "provenance": {"input_kind": "text", "input_sha256": "0" * 64},
        "actions": [{"id": "a1", "name": "reach web", "target_host_ref": "web",
                     "source": "user", "epistemic_status": "supported"}], "relations": [],
        "environment_plan": {
            "hosts": [
                {"id": "attacker", "role": "attacker", "image_hint": "demo-client", "networks": ["outer"]},
                {"id": "web", "role": "web", "image_hint": "demo-api",
                 "services": [{"name": "http", "port": 8080, "protocol": "tcp"}], "networks": ["outer"]},
                {"id": "web2", "role": "web", "image_hint": "demo-api",
                 "services": [{"name": "http", "port": 8080, "protocol": "tcp"}], "networks": ["inner"]},
            ],
            "networks": [{"id": "outer", "internal": True}, {"id": "inner", "internal": True}],
            "connections": [{"from_host": "attacker", "to_host": "web", "port": 8080, "protocol": "tcp",
                             "reason": "Scenario action(s) a1 require access to web."}],
            "verify_blocked": [
                {"from_host": "attacker", "to_host": "web2", "port": 8080, "protocol": "tcp",
                 "reason": "different network, truly segmented"},
                {"from_host": "attacker", "to_host": "web", "port": 9999, "protocol": "tcp",
                 "reason": "same network, closed port"},
            ],
        },
    }
    with tempfile.TemporaryDirectory(prefix="cr-poc-seg-") as tmp:
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

    checks = report["checks"]
    segmented = _find(checks, "web2:8080")
    closed_port = _find(checks, "web:9999")
    # Genuinely segmented path: unreachable -> PASS.
    assert segmented["status"] == "PASS", segmented["observed"]
    # Same-network closed port: refused -> NOT a segmentation PASS.
    assert closed_port["status"] == "NOT_TESTED", closed_port["observed"]
    assert "refus" in closed_port["observed"].lower() or "Connection refused" in closed_port["observed"]


@pytest.mark.skipif(not _docker_ready(), reason="Docker/compose not available")
def test_multihomed_target_is_not_falsely_segmented():
    """Reviewer F1: a target reachable on ONE of its networks must not PASS as blocked.

    `pivot` is multi-homed on `outer` (shared with attacker) and `inner`. The attacker
    can reach it on `outer`, so a verify_blocked attacker->pivot must be FAIL, even
    though pivot also has an `inner` address the attacker cannot reach. Probing only
    one of pivot's addresses could have mis-scored this as a segmentation PASS.
    """
    sid = f"poc-mh-{uuid.uuid4().hex[:6]}"
    ir = {
        "schema_version": "1.0", "id": sid, "name": "multihomed segmentation test",
        "provenance": {"input_kind": "text", "input_sha256": "0" * 64},
        "actions": [{"id": "a1", "name": "reach pivot", "target_host_ref": "pivot",
                     "source": "user", "epistemic_status": "supported"}], "relations": [],
        "environment_plan": {
            "hosts": [
                {"id": "attacker", "role": "attacker", "image_hint": "demo-client", "networks": ["outer"]},
                {"id": "pivot", "role": "web", "image_hint": "demo-api",
                 "services": [{"name": "http", "port": 8080, "protocol": "tcp"}],
                 "networks": ["outer", "inner"]},
            ],
            "networks": [{"id": "outer", "internal": True}, {"id": "inner", "internal": True}],
            "connections": [{"from_host": "attacker", "to_host": "pivot", "port": 8080, "protocol": "tcp",
                             "reason": "Scenario action(s) a1 require access to pivot."}],
            # Claim (falsely) that attacker cannot reach pivot. It can, on `outer`.
            "verify_blocked": [{"from_host": "attacker", "to_host": "pivot", "port": 8080, "protocol": "tcp",
                                "reason": "asserted blocked, but actually reachable on outer"}],
        },
    }
    with tempfile.TemporaryDirectory(prefix="cr-poc-mh-") as tmp:
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

    blocked = _find(report["checks"], "pivot:8080")
    # Reachable on outer -> must be FAIL, never a false segmentation PASS.
    assert blocked["status"] == "FAIL", blocked["observed"]
