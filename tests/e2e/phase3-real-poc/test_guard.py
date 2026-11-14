"""Tests for the Phase 3 isolation guard and the double-gate. No real exploit runs.

These never set CR_PHASE3_AUTHORIZED against a live host and never deploy a
vulnerable image. The mocked tests prove the gate logic; the docker-gated test
only stands up the harmless probe (via guard) and checks an invariant that holds
both before and after the host-isolation fix.
"""
from __future__ import annotations

import importlib
import pathlib
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import guard  # noqa: E402
import poc_common as pc  # noqa: E402


def _docker_ready() -> bool:
    return guard._run(["docker", "info"], timeout=20).returncode == 0


def test_require_isolation_raises_when_host_reachable():
    fake = {"isolated": False, "error": None,
            "detail": {"host_ports_reached": [22], "internet_reached": []}}
    with patch.object(guard, "confirm_isolated", return_value=fake):
        with pytest.raises(guard.IsolationNotConfirmed):
            guard.require_isolation()


def test_require_isolation_returns_when_isolated():
    fake = {"isolated": True, "error": None,
            "detail": {"host_ports_reached": [], "internet_reached": []}}
    with patch.object(guard, "confirm_isolated", return_value=fake):
        assert guard.require_isolation()["isolated"] is True


def test_require_isolation_raises_on_guard_error():
    fake = {"isolated": False, "error": "docker unavailable", "detail": None}
    with patch.object(guard, "confirm_isolated", return_value=fake):
        with pytest.raises(guard.IsolationNotConfirmed):
            guard.require_isolation()


def test_preflight_blocks_without_authorization(monkeypatch):
    monkeypatch.delenv("CR_PHASE3_AUTHORIZED", raising=False)
    out = pc.preflight("struts-s2-045")
    assert out is not None and out["status"] == "NOT_TESTED"
    assert "AUTHORIZED" in out["reason"]


def test_preflight_blocks_when_guard_refuses(monkeypatch):
    # Even authorized, a non-isolated host must block with NOT_TESTED, no deploy.
    monkeypatch.setenv("CR_PHASE3_AUTHORIZED", "1")
    with patch.object(pc.guard, "require_isolation",
                      side_effect=guard.IsolationNotConfirmed("host reachable")):
        out = pc.preflight("log4shell-solr")
    assert out is not None and out["status"] == "NOT_TESTED"
    assert "guard refused" in out["reason"]


@pytest.mark.skipif(not _docker_ready(), reason="Docker not available")
def test_guard_verdict_is_consistent_and_wellformed():
    # Stands up only the harmless probe. Invariant holds before AND after the infra
    # fix: require_isolation() raises iff confirm_isolated() reports not isolated.
    verdict = guard.confirm_isolated("phase3-selftest")
    assert "isolated" in verdict
    if verdict.get("error"):
        pytest.skip(f"guard could not run probe: {verdict['error']}")
    assert isinstance(verdict["detail"]["host_ports_reached"], list)
    if verdict["isolated"]:
        assert guard.require_isolation()["isolated"] is True
    else:
        with pytest.raises(guard.IsolationNotConfirmed):
            guard.require_isolation()
