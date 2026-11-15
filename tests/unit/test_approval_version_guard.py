"""Approval version normalization and API guard contract; no deployment backend is started."""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api"))

from app.planner.approval import topology_approval_state  # noqa: E402
from app.planner.topology import build_environment_plan, connections_digest  # noqa: E402
from app.main import app  # noqa: E402
from app.routers import deploy, planning  # noqa: E402


def make_ir(*, current: int = 4, plan_version: int | None = 4,
            approval_version: int | None = 4, approved: bool = True) -> dict:
    plan = {"connections": [{"from_host": "attacker", "to_host": "web", "port": 8080, "protocol": "tcp"}],
            "approval": {"approved": approved}}
    if plan_version is not None:
        plan["based_on_ir_version"] = plan_version
    if approved:
        if approval_version is not None:
            plan["approval"]["approved_ir_version"] = approval_version
        plan["approval"]["connections_digest"] = connections_digest(plan)
    return {"id": "scn_test", "ir_version": current, "environment_plan": plan}


class ApprovalVersionState(unittest.TestCase):
    def test_generated_plan_records_its_source_ir_version(self):
        plan = build_environment_plan({"ir_version": 9, "hosts": [], "services": [], "actions": [], "relations": []})
        self.assertEqual(plan["based_on_ir_version"], 9)

    def test_current_canonical_versions_are_deployable(self):
        state = topology_approval_state(make_ir())
        self.assertTrue(state["deployable"])
        self.assertFalse(state["stale"])
        self.assertEqual((state["plan_ir_version"], state["approved_ir_version"]), (4, 4))

    def test_legacy_aliases_are_normalized(self):
        ir = make_ir(plan_version=None, approval_version=None)
        ir["environment_plan"]["ir_version"] = 4
        ir["environment_plan"]["approval"].update(based_on_ir_version=4, ir_version=4)
        state = topology_approval_state(ir)
        self.assertTrue(state["deployable"])
        self.assertEqual((state["plan_ir_version"], state["approved_ir_version"]), (4, 4))

    def test_unversioned_legacy_approval_is_allowed_only_with_matching_digest(self):
        ir = make_ir(plan_version=None, approval_version=None)
        state = topology_approval_state(ir)
        self.assertTrue(state["deployable"])
        self.assertFalse(state["versioned"])
        ir["environment_plan"]["connections"].append({"from_host": "web", "to_host": "db", "port": 5432})
        stale = topology_approval_state(ir)
        self.assertTrue(stale["stale"])
        self.assertEqual(stale["code"], "topology_changed")

    def test_any_recorded_version_behind_current_is_stale(self):
        for ir in (
            make_ir(plan_version=3, approval_version=3),
            make_ir(plan_version=4, approval_version=3),
            make_ir(plan_version=3, approval_version=4),
        ):
            with self.subTest(ir=ir):
                state = topology_approval_state(ir)
                self.assertTrue(state["stale"])
                self.assertFalse(state["deployable"])
                self.assertEqual(state["code"], "scenario_changed")

    def test_conflicting_aliases_and_invalid_values_fail_closed(self):
        ir = make_ir()
        ir["environment_plan"]["ir_version"] = 3
        self.assertTrue(topology_approval_state(ir)["stale"])

        ir = make_ir()
        ir["environment_plan"]["approval"]["based_on_ir_version"] = 3
        self.assertTrue(topology_approval_state(ir)["stale"])

        ir = make_ir()
        ir["environment_plan"]["approval"]["ir_version"] = True
        state = topology_approval_state(ir)
        self.assertTrue(state["stale"])
        self.assertEqual(state["code"], "approval_metadata_invalid")

    def test_missing_current_version_fails_closed_for_approved_plan(self):
        ir = make_ir()
        del ir["ir_version"]
        state = topology_approval_state(ir)
        self.assertTrue(state["stale"])
        self.assertFalse(state["deployable"])


class ApprovalApiContract(unittest.TestCase):
    def test_approval_records_current_ir_version_and_returns_shared_state(self):
        ir = make_ir(plan_version=None, approval_version=None, approved=False)
        state = {"scn_test": copy.deepcopy(ir)}

        def update(_sid, updated, note=None, bump_version=False):
            state[_sid] = copy.deepcopy(updated)
            return copy.deepcopy(updated)

        with patch.object(planning.store, "get", side_effect=lambda sid: copy.deepcopy(state.get(sid))), \
             patch.object(planning, "_validated_update", side_effect=update):
            response = planning.approve_topology("scn_test", planning.ApprovalRequest())

        self.assertEqual(response["based_on_ir_version"], 4)
        self.assertEqual(response["approval"]["approved_ir_version"], 4)
        self.assertEqual(response["approval"]["based_on_ir_version"], 4)
        self.assertTrue(response["approval_state"]["deployable"])

    def test_approval_refuses_an_outdated_recorded_plan_without_saving(self):
        ir = make_ir(current=4, plan_version=3, approval_version=None, approved=False)
        with patch.object(planning.store, "get", return_value=copy.deepcopy(ir)), \
             patch.object(planning, "_validated_update") as update:
            with self.assertRaises(HTTPException) as raised:
                planning.approve_topology("scn_test", planning.ApprovalRequest())
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail["code"], "approval_stale")
        update.assert_not_called()

    def test_deploy_rejects_stale_version_before_manager_do_up(self):
        ir = make_ir(current=4, plan_version=3, approval_version=3)
        with patch.object(deploy.store, "get", return_value=ir), \
             patch.object(deploy.manager, "record"), \
             patch.object(deploy.manager, "do_up", side_effect=AssertionError("do_up must not run")) as do_up:
            response = TestClient(app).post("/api/deploy/scn_test/up", json={"test_approved": True})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "approval_stale")
        do_up.assert_not_called()

    def test_digest_mismatch_uses_the_same_stale_http_contract(self):
        ir = make_ir()
        ir["environment_plan"]["connections"][0]["port"] = 9443
        with patch.object(deploy.store, "get", return_value=ir), \
             patch.object(deploy.manager, "record"), \
             patch.object(deploy.manager, "do_up", side_effect=AssertionError("do_up must not run")) as do_up:
            response = TestClient(app).post("/api/deploy/scn_test/up", json={"test_approved": True})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "approval_stale")
        do_up.assert_not_called()

    def test_status_preflight_and_planning_return_the_same_approval_state(self):
        ir = make_ir(current=4, plan_version=3, approval_version=3)
        with patch.object(deploy.store, "get", return_value=ir), \
             patch.object(deploy.manager, "do_status", return_value={"state": "stopped"}), \
             patch.object(deploy.manager, "deploy_preflight", return_value={"ok": True}), \
             patch.object(planning.store, "get", return_value=ir), \
             patch.object(planning, "iter_errors", return_value=[]):
            client = TestClient(app)
            status = client.get("/api/deploy/scn_test/status").json()
            preflight = client.get("/api/deploy/scn_test/preflight").json()
            topology = client.get("/api/planning/scn_test/topology").json()

        expected = topology_approval_state(ir)
        self.assertEqual(status["approval"], expected)
        self.assertEqual(preflight["approval"], expected)
        self.assertEqual(topology["approval_state"], expected)


if __name__ == "__main__":
    unittest.main()
