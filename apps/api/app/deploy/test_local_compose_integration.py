"""Two-container local integration test; safely skips without the pinned local Docker image."""
from __future__ import annotations

import shutil
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import config, store
from app.deploy import manager
from app.iac.generator import generated_dir
from app.main import app


_BASE_IMAGE = "python@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704"


def _docker_ready_or_skip() -> None:
    docker, error = manager._docker_context_preflight()
    if error or not docker:
        raise unittest.SkipTest(error or "Docker is unavailable")
    image = manager._run([docker, "image", "inspect", _BASE_IMAGE], timeout=15)
    if image["returncode"] != 0:
        raise unittest.SkipTest(f"pinned demo image is not cached locally: {_BASE_IMAGE}")


class LocalComposeIntegrationTests(unittest.TestCase):
    def test_two_container_up_status_validate_down(self):
        _docker_ready_or_skip()
        scenario_id = f"infra-test-{uuid.uuid4().hex[:8]}"
        with tempfile.TemporaryDirectory(prefix="cr-demo-test-") as temporary:
            data_dir = Path(temporary) / "data"
            data_dir.mkdir()
            with patch.object(config, "DATA_DIR", data_dir), patch.object(store, "_DB", data_dir / "scenarios.db"):
                self._exercise(scenario_id)

    def _exercise(self, scenario_id: str):
        store.create({
        "schema_version": "1.0", "id": scenario_id, "name": "Local harmless integration example",
        "provenance": {"input_kind": "text", "input_sha256": "0" * 64}, "actions": [], "relations": [],
        "environment_plan": {
            "hosts": [
                {"id": "demo-api", "role": "demo-api", "image_hint": "demo-api",
                 "services": [{"name": "http", "port": 8080, "protocol": "tcp"}], "networks": ["inside"]},
                {"id": "demo-client", "role": "demo-client", "image_hint": "demo-client", "networks": ["inside"]},
            ],
            "networks": [{"id": "inside", "internal": True}],
            "connections": [{"from_host": "demo-client", "to_host": "demo-api", "port": 8080,
                             "protocol": "tcp", "reason": "one harmless demo HTTP request"}],
        },
        })

        output_dir = generated_dir(scenario_id, create=False)
        deployed = False
        with TestClient(app) as client:
            try:
                generated = client.post(f"/api/iac/{scenario_id}/generate")
                self.assertEqual(generated.status_code, 200, generated.text)
                self.assertEqual(client.get(f"/api/iac/{scenario_id}").json(), generated.json())
                self.assertEqual(client.post(f"/api/deploy/{scenario_id}/up", json={}).status_code, 400)

                up = client.post(f"/api/deploy/{scenario_id}/up", json={"test_approved": True})
                self.assertEqual(up.status_code, 200, up.text)
                deployed = True

                status = client.get(f"/api/deploy/{scenario_id}/status")
                self.assertEqual(status.status_code, 200)
                self.assertEqual(status.json()["state"], "running")
                self.assertEqual({c["service"] for c in status.json()["containers"]}, {"demo-api", "demo-client"})

                health = None
                for _ in range(20):
                    health = client.get(f"/api/deploy/{scenario_id}/health")
                    if health.json().get("state") != "starting":
                        break
                    time.sleep(0.5)
                self.assertIsNotNone(health)
                self.assertEqual(health.json()["state"], "healthy", health.text)

                validation = client.post(f"/api/validate/{scenario_id}/run")
                self.assertEqual(validation.status_code, 200, validation.text)
                report = validation.json()
                self.assertEqual(report["levels"], {"env_build": "PASS", "behavior_repro": "PASS", "full_chain": "PASS"})
                self.assertTrue(all(check["status"] == "PASS" for check in report["checks"]))
                latest = client.get(f"/api/validate/{scenario_id}/report")
                self.assertEqual(latest.status_code, 200)
                self.assertEqual(latest.json(), report)

                down = client.post(f"/api/deploy/{scenario_id}/down")
                self.assertEqual(down.status_code, 200, down.text)
                self.assertTrue(down.json()["ok"])
                deployed = False
                status_after = client.get(f"/api/deploy/{scenario_id}/status")
                self.assertEqual(status_after.status_code, 200)
                self.assertEqual(status_after.json()["state"], "not_created")
                actions = {record["action"] for record in client.get(f"/api/deploy/{scenario_id}/records").json()["records"]}
                self.assertTrue({"up", "status", "health", "down"}.issubset(actions))
            finally:
                if deployed:
                    client.post(f"/api/deploy/{scenario_id}/down")
                if output_dir.exists() and not output_dir.is_symlink():
                    shutil.rmtree(output_dir)
