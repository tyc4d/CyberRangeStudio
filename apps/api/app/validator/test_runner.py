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
    def _run_report(self, blocked_marker: str = "BLOCKED:OSError:[Errno 101] Network is unreachable",
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
                patch.object(runner.manager, "container_ipv4_addresses",
                             return_value=([{"network": "internal", "ip": target_ip}] if target_ip else [])), \
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

    def test_refused_connection_is_not_a_segmentation_pass(self):
        # ConnectionRefused means the host was reachable and only the port was closed:
        # the two endpoints share a network, so segmentation is NOT proven (R6).
        report = self._run_report("BLOCKED:ConnectionRefusedError:[Errno 111] Connection refused")
        blocked = next(check for check in report["checks"] if check["category"] == "segmentation")
        self.assertEqual(blocked["status"], "NOT_TESTED")
        self.assertIn("refused", blocked["observed"].lower())

    def test_full_chain_is_never_pass_without_declared_attack_actions(self):
        # R1: an environment with zero attack actions must not inherit a full_chain
        # PASS from plumbing (TCP reachable + HTTP 200). No chain -> NOT_TESTED.
        ir = {
            "schema_version": "1.0", "id": "no-actions", "name": "no actions",
            "provenance": {"input_kind": "text", "input_sha256": "0" * 64},
            "actions": [], "relations": [],
            "environment_plan": {
                "hosts": [
                    {"id": "attacker", "role": "attacker", "image_hint": "demo-client",
                     "component_mode": "substitute", "networks": ["external"]},
                    {"id": "web", "role": "web", "image_hint": "demo-api", "component_mode": "substitute",
                     "services": [{"name": "http", "port": 8080, "protocol": "tcp"}],
                     "networks": ["external"]},
                ],
                "networks": [{"id": "external", "internal": True}],
                "connections": [
                    {"from_host": "attacker", "to_host": "web", "port": 8080, "protocol": "tcp",
                     "reason": "reach web"},
                ],
                "verify_blocked": [],
            },
        }
        ps = {"returncode": 0, "stdout": (
            '[{"Service":"attacker","Name":"cr-demo-no-actions-attacker","State":"running"},'
            '{"Service":"web","Name":"cr-demo-no-actions-web","State":"running"}]'), "stderr": ""}
        probe_results = [
            {"returncode": 0, "stdout": "CONNECTED", "stderr": ""},
            {"returncode": 0, "stdout": "HTTP_STATUS:200\nBODY:cr-demo-demo-ok", "stderr": ""},
        ]
        temporary = tempfile.TemporaryDirectory(prefix="cr-validator-unit-")
        self.addCleanup(temporary.cleanup)
        with patch.object(config, "DATA_DIR", Path(temporary.name)), \
                patch.object(runner.store, "get", return_value=ir), \
                patch.object(runner, "get_generated", return_value={"compose": "stub"}), \
                patch.object(runner.manager, "compose_ps_result", return_value=ps), \
                patch.object(runner.manager, "probe_in_service", side_effect=probe_results), \
                patch.object(runner.manager, "container_ipv4_addresses",
                             return_value=[{"network": "internal", "ip": "172.20.0.9"}]), \
                patch.object(runner.manager, "exec_in_service",
                             return_value={"returncode": 0, "stdout": "python-runtime-ok", "stderr": ""}):
            report = runner.run("no-actions")
        self.assertEqual(report["levels"]["env_build"], "PASS")
        self.assertEqual(report["levels"]["full_chain"], "NOT_TESTED")
        self.assertNotEqual(report["levels"]["full_chain"], "PASS")

    def test_unhealthy_container_fails_env_build(self):
        # R7: a running-but-unhealthy container is not a stood-up service.
        temporary = tempfile.TemporaryDirectory(prefix="cr-validator-unit-")
        self.addCleanup(temporary.cleanup)
        ps = {"returncode": 0, "stdout": (
            '[{"Service":"attacker","Name":"cr-demo-runner-test-attacker","State":"running"},'
            '{"Service":"web","Name":"cr-demo-runner-test-web","State":"running","Health":"unhealthy"},'
            '{"Service":"db","Name":"cr-demo-runner-test-db","State":"running"}]'), "stderr": ""}
        probe_results = [
            {"returncode": 0, "stdout": "CONNECTED", "stderr": ""},
            {"returncode": 0, "stdout": "HTTP_STATUS:200\nBODY:cr-demo-demo-ok", "stderr": ""},
            {"returncode": 0, "stdout": "BLOCKED:OSError:[Errno 101] Network is unreachable", "stderr": ""},
        ]

        def exec_result(_sid, service_id, command, timeout=10):
            if service_id == "db":
                return {"returncode": 0, "stdout": "postgres (PostgreSQL) 16.16", "stderr": ""}
            return {"returncode": 0, "stdout": "python-runtime-ok", "stderr": ""}

        with patch.object(config, "DATA_DIR", Path(temporary.name)), \
                patch.object(runner.store, "get", return_value=IR), \
                patch.object(runner, "get_generated", return_value={"compose": "stub"}), \
                patch.object(runner.manager, "compose_ps_result", return_value=ps), \
                patch.object(runner.manager, "probe_in_service", side_effect=probe_results), \
                patch.object(runner.manager, "container_ipv4_addresses",
                             return_value=[{"network": "internal", "ip": "172.20.0.5"}]), \
                patch.object(runner.manager, "exec_in_service", side_effect=exec_result):
            report = runner.run("runner-test")
        web_up = next(c for c in report["checks"] if c["id"] == "service-up-web")
        self.assertEqual(web_up["status"], "FAIL")
        self.assertEqual(report["levels"]["env_build"], "FAIL")

    def test_action_without_explicit_mapping_is_not_tested_not_partial(self):
        # R3: an action is PARTIAL only when a connection names its id AND the action
        # targets that connection's host. a1 targets web and is named -> PARTIAL.
        # a2 targets db, not named on the attacker->web path -> NOT_TESTED.
        report = self._run_report()
        action_checks = {c["action_ref"]: c for c in report["checks"]
                         if c["id"].startswith("action-")}
        self.assertEqual(action_checks["a1"]["status"], "PARTIAL")
        self.assertEqual(action_checks["a2"]["status"], "NOT_TESTED")

    def test_real_planner_reason_with_targetless_actions_is_not_tested(self):
        # Reviewer P1: the real planner writes ONE reason listing every action id for
        # a host, and these scenario actions have no target_host_ref. id-in-reason
        # alone would mark all four PARTIAL; requiring a target match makes them all
        # NOT_TESTED, which is honest -- only the attacker->web TCP path was proven.
        connection = {"from_host": "attacker", "to_host": "web", "port": 8080, "protocol": "tcp",
                      "reason": "Scenario action(s) a1, a2, a3, a4 require access to web server (substitute)."}
        actions = [{"id": f"a{i}", "name": f"step {i}", "target_host_ref": None} for i in range(1, 5)]
        self.assertEqual(runner._explicit_action_refs(connection, actions), [])

    def test_explicit_mapping_requires_matching_target_host(self):
        # When an action both is named and targets the connection's host, it maps.
        connection = {"from_host": "attacker", "to_host": "web", "port": 80, "protocol": "tcp",
                      "reason": "Scenario action(s) a1, a2 require access to web."}
        actions = [{"id": "a1", "target_host_ref": "web"}, {"id": "a2", "target_host_ref": "db"}]
        self.assertEqual(runner._explicit_action_refs(connection, actions), ["a1"])

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
