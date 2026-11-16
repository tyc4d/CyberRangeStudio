"""Real Struts payload through scenario deploy + M9 runner on isolated Proxmox only.

The test is deliberately skipped unless the selected backend is Proxmox and its
approved isolated worker template passes the live preflight. Local Docker is never
used as a fallback for vulnerable images.
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
from app.poc.runner import ExecutionRequest, SandboxRunner
from app.poc.runner.payloads import (
    STRUTS_S2045_MARKER,
    STRUTS_S2045_PAYLOAD,
    STRUTS_S2045_PROOF_ID,
    STRUTS_S2045_SHA256,
    STRUTS_S2045_SOURCE,
)


def _pve_skip_reason() -> str | None:
    try:
        if manager.deploy_backend() != "proxmox":
            return "requires CR_DEPLOY_BACKEND=proxmox; local-docker vulnerable targets remain blocked by D6"
        report = manager._proxmox_backend().preflight()
    except Exception as exc:
        return f"Proxmox is unreachable or unavailable: {type(exc).__name__}"
    if not report.get("ok"):
        return f"Proxmox preflight is not ready: {report.get('error') or report.get('state') or 'unknown'}"
    if report.get("mode") != "live":
        return "Proxmox is reachable but runtime mode is not live; no vulnerable deployment will be attempted"
    if not (report.get("checks") or {}).get("template_owned"):
        return "approved isolated Proxmox worker template is absent or failed ownership checks"
    return None


_PVE_SKIP = _pve_skip_reason()
pytestmark = pytest.mark.skipif(_PVE_SKIP is not None, reason=_PVE_SKIP or "Proxmox is ready")

def test_real_struts_s2045_payload_through_product_deployment():
    sid = f"m9-struts-{uuid.uuid4().hex[:8]}"
    ir = {
        "schema_version": "1.0", "id": sid, "name": "M9 Struts S2-045 runner e2e",
        "provenance": {"input_kind": "text", "input_sha256": "0" * 64},
        "actions": [{"id": "a1", "name": "Exploit Struts S2-045 (OGNL RCE)",
                     "target_host_ref": "web", "attack_technique": "T1190",
                     "source": "user", "epistemic_status": "supported"}],
        "relations": [],
        "hosts": [{"id": "web", "role": "target web application", "service_refs": ["svc-struts"],
                   "source": "user", "epistemic_status": "supported"}],
        "services": [{"id": "svc-struts", "name": "struts", "host_ref": "web",
                      "catalogue_component": "vuln-struts2-s2-045", "version": "2.3.30",
                      "port": 8080, "protocol": "tcp", "version_basis": "assumed",
                      "source": "user", "epistemic_status": "supported"}],
        "environment_plan": {
            "hosts": [{"id": "web", "role": "target web application",
                       "image_hint": "vuln-struts2-s2-045", "component_mode": "real",
                       "services": [{"name": "struts", "port": 8080, "protocol": "tcp"}],
                       "networks": ["lab"]}],
            "networks": [{"id": "lab", "internal": True}],
            "connections": [], "verify_blocked": [],
        },
    }
    with tempfile.TemporaryDirectory(prefix="cr-m9-struts-") as tmp:
        data = Path(tmp) / "data"
        data.mkdir()
        with patch.object(config, "DATA_DIR", data), patch.object(store, "_DB", data / "scenarios.db"):
            store.create(ir)
            with TestClient(app) as client:
                generated = client.post(f"/api/iac/{sid}/generate")
                assert generated.status_code == 200, generated.text
                approved = client.post(f"/api/planning/{sid}/topology/approve",
                                       json={"approved": True, "approved_by": "m9-runner-e2e"})
                assert approved.status_code == 200, approved.text
                deployed = client.post(f"/api/deploy/{sid}/up", json={"test_approved": True})
                if deployed.status_code != 200:
                    # PVE worker images are --pull=never; absence of the vulnerable
                    # Struts image in its prepared runtime is an environment skip.
                    pytest.skip("Proxmox worker has no prepared vulnerable Struts image/template: "
                                + deployed.text[:300])
                if deployed.json().get("state") != "running":
                    pytest.skip("Proxmox did not start a live isolated worker: " + deployed.text[:300])
                try:
                    request = ExecutionRequest(
                        action_id="a1", scenario_id=sid, service_ref="web", target_host_ref="web",
                        source_url=STRUTS_S2045_SOURCE, ref={"release": "internal-payload-v1"},
                        sha256=STRUTS_S2045_SHA256, exec_method="http_seq",
                        payload=STRUTS_S2045_PAYLOAD, expected_marker=STRUTS_S2045_MARKER,
                        proof_id=STRUTS_S2045_PROOF_ID, timeout=30,
                    )
                    result = SandboxRunner().execute(request)
                    assert result.status == "PASS", result.failure_reason or result
                    assert result.stages.vuln_behavior is True
                    assert any(e.kind == "exploit_effect" and "54289" in (e.note or "")
                               for e in result.evidence)
                finally:
                    client.post(f"/api/deploy/{sid}/down")
