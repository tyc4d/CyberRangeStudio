"""Offline checks for level aggregation, action fidelity, and segmentation evidence."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import config
from app.validator import runner


IR = {
    "schema_version": "1.0",
    "id": "runner-test",
    "name": "validator unit test",
    "provenance": {"input_kind": "text", "input_sha256": "0" * 64},
    "actions": [
        {"id": "a1", "name": "Reach the web service", "target_host_ref": "web"},
        {"id": "a2", "name": "Access the database", "target_host_ref": "db"},
    ],
    "relations": [],
    "environment_plan": {
        "hosts": [
            {"id": "attacker", "role": "attacker", "image_hint": "demo-client", "component_mode": "substitute",
             "networks": ["external"]},
            {"id": "web", "role": "web", "image_hint": "demo-api", "component_mode": "substitute",
             "services": [{"name": "http", "port": 8080, "protocol": "tcp"}],
             "networks": ["external", "internal"]},
            {"id": "db", "role": "database", "image_hint": "oss-postgres", "component_mode": "real",
             "services": [{"name": "postgres", "port": 5432, "protocol": "tcp"}],
             "networks": ["internal"]},
        ],
        "networks": [
            {"id": "external", "internal": True},
            {"id": "internal", "internal": True},
        ],
        "connections": [
            {"from_host": "attacker", "to_host": "web", "port": 8080, "protocol": "tcp",
             "reason": "Scenario action(s) a1 require access to web."},
        ],
        "verify_blocked": [
            {"from_host": "attacker", "to_host": "db", "port": 5432, "protocol": "tcp",
             "reason": "attacker must not connect directly to the database"},
        ],
    },
}


def _compose_ps_result():
    return {
        "returncode": 0,
        "stdout": (
            '[{"Service":"attacker","Name":"cr-demo-runner-test-attacker","State":"running"},'
            '{"Service":"web","Name":"cr-demo-runner-test-web","State":"running"},'
            '{"Service":"db","Name":"cr-demo-runner-test-db","State":"running"}]'
        ),
        "stderr": "",
    }


class ValidationRunnerTests(unittest.TestCase):
    def _run_report(self, blocked_marker: str = "BLOCKED:ConnectionRefusedError:blocked",
                    target_ip: str | None = "172.20.0.5"):
        temporary = tempfile.TemporaryDirectory(prefix="cr-validator-unit-")
        self.addCleanup(temporary.cleanup)
        data_dir = Path(temporary.name)
        probe_results = [
            {"returncode": 0, "stdout": "CONNECTED", "stderr": ""},
            {"returncode": 0, "stdout": "HTTP_STATUS:200\nBODY:cr-demo-demo-ok", "stderr": ""},
            {"returncode": 0, "stdout": blocked_marker, "stderr": ""},
        ]

        def exec_result(_scenario_id, service_id, command, timeout=10):
            if service_id == "db":
                return {"returncode": 0, "stdout": "postgres (PostgreSQL) 16.16", "stderr": ""}
            return {"returncode": 0, "stdout": "python-runtime-ok", "stderr": ""}

        with patch.object(config, "DATA_DIR", data_dir), \
                patch.object(runner.store, "get", return_value=IR), \
                patch.object(runner, "get_generated", return_value={"compose": "stub"}), \
                patch.object(runner.manager, "compose_ps_result", return_value=_compose_ps_result()), \
                patch.object(runner.manager, "probe_in_service", side_effect=probe_results), \
                patch.object(runner.manager, "container_ipv4", return_value=target_ip), \
                patch.object(runner.manager, "exec_in_service", side_effect=exec_result):
            return runner.run("runner-test")

    def test_full_chain_cannot_pass_when_attack_actions_are_only_partially_observed(self):
        report = self._run_report()
        self.assertEqual(report["levels"]["env_build"], "PASS")
        self.assertEqual(report["levels"]["full_chain"], "PARTIAL")
        self.assertEqual(report["fidelity"]["partial"], ["a1"])
        self.assertEqual(report["fidelity"]["not_tested"], ["a2"])
        action_checks = {check["action_ref"]: check for check in report["checks"] if check.get("action_ref")
                         and check["id"].startswith("action-")}
        self.assertEqual(action_checks["a1"]["status"], "PARTIAL")
        self.assertEqual(action_checks["a2"]["status"], "NOT_TESTED")
        self.assertIn("not executed", action_checks["a1"]["observed"])
        self.assertTrue(all("action_ref" in check for check in action_checks.values()))
        self.assertIn("every Scenario IR action", report["level_criteria"]["full_chain"])

    def test_blocked_probe_passes_only_when_the_tcp_path_is_unreachable(self):
        blocked_report = self._run_report()
        blocked = next(check for check in blocked_report["checks"] if check["category"] == "segmentation")
        self.assertEqual(blocked["status"], "PASS")
        self.assertIn("BLOCKED:", blocked["observed"])

        reachable_report = self._run_report("CONNECTED")
        reachable = next(check for check in reachable_report["checks"] if check["category"] == "segmentation")
        self.assertEqual(reachable["status"], "FAIL")
        self.assertIn("CONNECTED", reachable["observed"])

    def test_name_resolution_failure_is_not_counted_as_blocked(self):
        # A DNS/gaierror failure proves nothing about the network path: must be NOT_TESTED, never PASS.
        report = self._run_report("UNRESOLVED:[Errno -3] Temporary failure in name resolution")
        blocked = next(check for check in report["checks"] if check["category"] == "segmentation")
        self.assertEqual(blocked["status"], "NOT_TESTED")

    def test_segmentation_is_not_tested_without_a_target_ip(self):
        # If the target container IP cannot be determined, segmentation is not proven at the TCP layer.
        report = self._run_report(target_ip=None)
        blocked = next(check for check in report["checks"] if check["category"] == "segmentation")
        self.assertEqual(blocked["status"], "NOT_TESTED")


if __name__ == "__main__":
    unittest.main()
