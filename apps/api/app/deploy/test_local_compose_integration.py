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

                # Deployment is refused until the topology is human-approved.
                self.assertEqual(
                    client.post(f"/api/deploy/{scenario_id}/up", json={"test_approved": True}).status_code, 409)
                approve = client.post(f"/api/planning/{scenario_id}/topology/approve",
                                      json={"approved": True, "approved_by": "integration-test"})
                self.assertEqual(approve.status_code, 200, approve.text)

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
                # This scenario declares no attack actions (actions: []), so the full
                # attack chain cannot be claimed reproduced: env/behavior plumbing must
                # not be promoted to a full_chain PASS (see validator R1 fix).
                self.assertEqual(report["levels"],
                                 {"env_build": "PASS", "behavior_repro": "PASS", "full_chain": "NOT_TESTED"})
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
                # Only state-changing actions are audited; status/health are read-only polls (not logged).
                self.assertTrue({"up", "down"}.issubset(actions))
                self.assertNotIn("status", actions)
                self.assertNotIn("health", actions)
            finally:
                if deployed:
                    client.post(f"/api/deploy/{scenario_id}/down")
                if output_dir.exists() and not output_dir.is_symlink():
                    shutil.rmtree(output_dir)


class PinnedImagePreparationTests(unittest.TestCase):
    def test_compose_up_pulls_curated_digest_images_before_start(self):
        calls = []
        pinned = "nginx:1.31.8@sha256:165ddde8751e75a1c907d24ef10d9f6deb08b57e0fe56caf67512486aff76d82"

        def fake_run(args, timeout=60, **kwargs):
            calls.append(args)
            return {"returncode": 0, "stdout": "", "stderr": ""}

        with patch.object(manager, "_docker_context_preflight", return_value=("docker", None)), \
                patch.object(manager, "_compose_prefix", return_value=(
                    ["docker", "compose", "-p", "cr-demo-image-test"], None)), \
                patch.object(manager, "_real_image_refs", return_value=([pinned], None)), \
                patch.object(manager, "_run", side_effect=fake_run):
            result = manager._compose_command("image-test", "up", ["-d", "--pull", "never"])

        self.assertEqual(result["returncode"], 0)
        pull_index = next(index for index, args in enumerate(calls) if args[:3] == ["docker", "pull", pinned])
        up_index = next(index for index, args in enumerate(calls) if "up" in args)
        self.assertLess(pull_index, up_index)

    def test_real_image_pull_failure_stops_before_compose_up(self):
        calls = []
        pinned = "postgres:16.16-alpine3.23@sha256:48340c4811085e083751cab526e533662da19585c1e6942a28b9c48ce7fcb8b2"

        def fake_run(args, timeout=60, **kwargs):
            calls.append(args)
            if args[:3] == ["docker", "pull", pinned]:
                return {"returncode": 1, "stdout": "", "stderr": "pull denied"}
            return {"returncode": 0, "stdout": "", "stderr": ""}

        with patch.object(manager, "_docker_context_preflight", return_value=("docker", None)), \
                patch.object(manager, "_compose_prefix", return_value=(
                    ["docker", "compose", "-p", "cr-demo-image-test"], None)), \
                patch.object(manager, "_real_image_refs", return_value=([pinned], None)), \
                patch.object(manager, "_run", side_effect=fake_run):
            result = manager._compose_command("image-test", "up", ["-d", "--pull", "never"])

        self.assertEqual(result["returncode"], 1)
        self.assertIn("could not pull pinned catalogue image", result["stderr"])
        self.assertFalse(any("up" in args for args in calls))

    def test_lan_up_injects_password_and_bind_ip_only_at_runtime(self):
        calls = []
        password = "generated-test-password"

        def fake_run(args, timeout=60, env_overrides=None):
            calls.append((args, env_overrides or {}))
            return {"returncode": 0, "stdout": "", "stderr": ""}

        with patch.object(manager, "_docker_context_preflight", return_value=("docker", None)), \
                patch.object(manager, "_compose_prefix", return_value=(
                    ["docker", "compose", "-p", "cr-demo-lan-test"], None)), \
                patch.object(manager, "_real_image_refs", return_value=([], None)), \
                patch.object(manager, "_run", side_effect=fake_run), \
                patch("app.deploy.manager.secrets.token_urlsafe", return_value=password), \
                patch.object(manager, "record", side_effect=lambda scenario, action, state, details: {
                    "details": details, "action": action, "state": state,
                }), \
                patch.object(manager, "live_containers", return_value={"state": "running", "containers": []}):
            result = manager.do_up("lan-test", "lan", "192.168.1.23")

        self.assertEqual(result["db_password"], password)
        self.assertEqual(result["lan_host"], "192.168.1.23")
        self.assertTrue(result["deployment_record"]["details"]["password_set"])
        self.assertNotIn(password, str(result["deployment_record"]))
        envs = [env for _, env in calls]
        compose_envs = [env for env in envs if "CR_BIND_IP" in env]
        self.assertEqual(len(compose_envs), 2)  # compose config and compose up
        self.assertTrue(all(env.get("CR_BIND_IP") == "192.168.1.23" for env in compose_envs))
        self.assertTrue(all(env.get("CR_PG_PASSWORD") == password for env in compose_envs))

    def test_lan_requires_specific_detected_ipv4(self):
        with patch.object(manager, "detect_lan_ipv4", side_effect=manager.PlanError(["no address"])):
            with self.assertRaises(manager.PlanError):
                manager.do_up("lan-test", "lan")


class NetworkAddressSelectionTests(unittest.TestCase):
    """container_ipv4 must describe plan networks, never the publishing-only edge bridge."""

    NETWORKS = {
        "cr-demo-seg-edge": {"IPAddress": "192.168.48.2"},
        "cr-demo-seg-outer": {"IPAddress": "172.26.0.2"},
        "cr-demo-seg-inner": {"IPAddress": "172.27.0.2"},
    }

    def _inspect(self, by_container):
        def fake_run(args, timeout=60, **kwargs):
            import json as _json
            return {"returncode": 0, "stdout": _json.dumps(by_container[args[-1]]), "stderr": ""}
        return fake_run

    def test_edge_address_is_never_returned(self):
        only_edge_first = {"cr-demo-seg-web": self.NETWORKS}
        with patch.object(manager, "_docker_context_preflight", return_value=("docker", None)), \
                patch.object(manager, "_run", side_effect=self._inspect(only_edge_first)):
            addresses = manager.container_ipv4_addresses("seg", "web")
            self.assertEqual(addresses, [{"network": "inner", "ip": "172.27.0.2"},
                                         {"network": "outer", "ip": "172.26.0.2"}])
            self.assertNotEqual(manager.container_ipv4("seg", "web"), "192.168.48.2")

    def test_address_on_the_network_shared_with_the_source_is_preferred(self):
        containers = {"cr-demo-seg-web": self.NETWORKS,
                      "cr-demo-seg-attacker": {"cr-demo-seg-outer": {"IPAddress": "172.26.0.9"}}}
        with patch.object(manager, "_docker_context_preflight", return_value=("docker", None)), \
                patch.object(manager, "_run", side_effect=self._inspect(containers)):
            self.assertEqual(manager.container_ipv4("seg", "web", from_service="attacker"), "172.26.0.2")

    def test_host_with_only_an_edge_address_has_no_plan_address(self):
        containers = {"cr-demo-seg-web": {"cr-demo-seg-edge": {"IPAddress": "192.168.48.2"}}}
        with patch.object(manager, "_docker_context_preflight", return_value=("docker", None)), \
                patch.object(manager, "_run", side_effect=self._inspect(containers)):
            self.assertIsNone(manager.container_ipv4("seg", "web"))


class FailedDeploymentTests(unittest.TestCase):
    def _run_up(self, up_results):
        calls = []
        results = iter(up_results)

        def fake_compose(scenario_id, operation, extra=None, timeout=60, **kwargs):
            calls.append((operation, kwargs.get("host_ports")))
            if operation == "up":
                return next(results)
            return {"returncode": 0, "stdout": "", "stderr": ""}

        states = {"n": 0}

        def fake_live(scenario_id):
            # running only after an `up` that succeeded; empty after cleanup
            last_up_ok = calls and calls[-1][0] == "up" and up_results[sum(1 for c in calls if c[0] == "up") - 1]["returncode"] == 0
            containers = [{"service": "web", "name": "cr-demo-fail-web", "state": "running", "health": "healthy"}] if last_up_ok else (
                [] if calls and calls[-1][0] == "down" else
                [{"service": "web", "name": "cr-demo-fail-web", "state": "created", "health": "", "status": "Created"}])
            return {"scenario_id": scenario_id, "project_name": "cr-demo-fail",
                    "state": "running" if last_up_ok else "not_created" if not containers else "stopped",
                    "containers": containers, "error": None}

        ports = iter([{"CR_HOSTPORT_0": "42000"}, {"CR_HOSTPORT_0": "42001"}, {"CR_HOSTPORT_0": "42002"}])
        with patch.object(manager, "_compose_command", side_effect=fake_compose), \
                patch.object(manager, "live_containers", side_effect=fake_live), \
                patch.object(manager, "allocate_host_ports", side_effect=lambda *a, **k: next(ports)), \
                patch.object(manager, "_docker_context_preflight", return_value=("docker", None)), \
                patch.object(manager, "_run", return_value={"returncode": 0, "stdout": "boom", "stderr": ""}), \
                patch.object(manager, "record", side_effect=lambda s, a, st, d: {"state": st, "details": d}):
            return manager.do_up("fail"), calls

    def test_failed_up_collects_diagnostics_and_removes_what_it_created(self):
        failure = {"returncode": 1, "stdout": "", "stderr": "Container cr-demo-fail-web Created\ndependency failed to start"}
        result, calls = self._run_up([failure])
        self.assertFalse(result["ok"])
        self.assertEqual(result["state"], "error")
        self.assertEqual([c[0] for c in calls], ["up", "down"])
        self.assertTrue(result["cleanup"]["clean"])
        self.assertEqual(result["diagnostics"]["containers"][0]["log_tail"], "boom")
        self.assertEqual(result["deployment_record"]["state"], "failed")

    def test_host_port_clash_is_retried_on_a_different_port(self):
        clash = {"returncode": 1, "stdout": "", "stderr": "Container x Created\nBind for 127.0.0.1:42000 failed: port is already allocated"}
        ok = {"returncode": 0, "stdout": "", "stderr": ""}
        result, calls = self._run_up([clash, ok])
        self.assertTrue(result["ok"])
        self.assertEqual([c for c in calls if c[0] == "up"],
                         [("up", {"CR_HOSTPORT_0": "42000"}), ("up", {"CR_HOSTPORT_0": "42001"})])
        self.assertEqual(len(result["attempts"]), 2)


class HostPortAllocationTests(unittest.TestCase):
    def test_busy_port_is_skipped_and_ports_stay_in_range(self):
        import socket
        busy = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        busy.bind(("127.0.0.1", 0))
        try:
            self.assertFalse(manager._port_is_free("127.0.0.1", busy.getsockname()[1]))
        finally:
            busy.close()
        report = {"report": {"host_port_mappings": [{"env": "CR_HOSTPORT_0"}, {"env": "CR_HOSTPORT_1"}]}}
        with patch.object(manager, "get_generated", return_value=report):
            assigned = manager.allocate_host_ports("ports", "127.0.0.1")
        self.assertEqual(set(assigned), {"CR_HOSTPORT_0", "CR_HOSTPORT_1"})
        values = [int(v) for v in assigned.values()]
        self.assertEqual(len(set(values)), 2)
        self.assertTrue(all(42000 <= v <= 42999 for v in values))
