"""Deterministic tests for the inventory override API; no deployment backend is used."""
import copy
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api"))

from app import store  # noqa: E402
from app.deploy import manager  # noqa: E402
from app.iac import generator  # noqa: E402
from app.iac.generator import PlanError, unconfirmed_inventory_substitutes  # noqa: E402
from app.main import app  # noqa: E402
from app.planner.dependencies import plan_dependencies  # noqa: E402
from app.planner.topology import build_environment_plan, connections_digest  # noqa: E402


SCENARIO_ID = "scn_inventory_override"


def sample_ir():
    return {
        "schema_version": "1.0",
        "id": SCENARIO_ID,
        "name": "Inventory override test",
        "ir_version": 4,
        "provenance": {"input_kind": "text", "input_sha256": "test"},
        "actions": [],
        "relations": [],
        "hosts": [{"id": "h1", "role": "web server", "epistemic_status": "supported", "source": "llm"}],
        "services": [{"id": "svc-httpd", "name": "Apache HTTP Server", "host_ref": "h1",
                       "cve": ["CVE-2024-12345"], "epistemic_status": "supported", "source": "llm"}],
        "missing_items": [],
        "environment_plan": {
            "hosts": [{"id": "h1", "role": "web server", "networks": ["internal"]}],
            "networks": [{"id": "internal", "internal": True}],
            "approval": {"approved": True, "approved_by": "tester", "connections_digest": "old-plan"},
        },
    }


class InventoryOverrideApiTests(unittest.TestCase):
    def setUp(self):
        self.saved = sample_ir()

    def patched_client(self):
        def get(scenario_id):
            return copy.deepcopy(self.saved) if scenario_id == SCENARIO_ID else None

        def update(scenario_id, ir, note="update", bump_version=False):
            updated = copy.deepcopy(ir)
            updated["ir_version"] = self.saved["ir_version"] + (1 if bump_version else 0)
            self.saved = updated
            return copy.deepcopy(updated)

        return patch.object(store, "get", side_effect=get), patch.object(store, "update", side_effect=update)

    def replacement_scenario(self):
        ir = sample_ir()
        ir["actions"] = [{"id": "a1", "name": "Exploit VMware Horizon portal", "target_host_ref": "h1",
                           "attack_technique": "T1190", "epistemic_status": "supported", "source": "llm",
                           "evidence_refs": []}]
        ir["services"] = [{
            "id": "svc-horizon", "name": "VMware Horizon", "host_ref": "h1",
            "catalogue_component": "vuln-log4shell-solr", "is_substitute": True,
            "substitute_of": "VMware Horizon", "substitute_basis": "user_chosen",
            "version_basis": "substituted", "reproduces_cve": [],
            "source": "llm", "epistemic_status": "supported",
            # The user has requested Struts, but dependencies have not yet applied it.
            "inventory_override": {"action": "replace", "component_id": "vuln-struts2-s2-045",
                                   "at": "2026-11-16T00:00:00+00:00"},
        }]
        ir["indicators"] = [{"id": "i1", "type": "cve", "value": "CVE-2021-44228"}]
        ir["missing_items"] = [{"id": "m1", "field": "affected software for CVE-2021-44228",
                                "category": "software", "reason": "The CVE is not linked to a source service.",
                                "status": "open"}]
        plan = build_environment_plan(ir)
        plan["approval"] = {"approved": True, "approved_by": "tester",
                             "connections_digest": connections_digest(plan)}
        ir["environment_plan"] = plan
        return ir

    def planned_replacement_scenario(self):
        planned = plan_dependencies(self.replacement_scenario())
        plan = build_environment_plan(planned)
        plan["approval"] = {"approved": True, "approved_by": "tester",
                             "connections_digest": connections_digest(plan)}
        planned["environment_plan"] = plan
        return planned

    def stale_replacement_scenario(self):
        """An old Solr topology with a newer Struts request that dependencies have not applied."""
        ir = self.replacement_scenario()
        ir["services"][0].pop("inventory_override", None)
        plan = build_environment_plan(ir)
        plan["approval"] = {"approved": True, "approved_by": "tester",
                             "connections_digest": connections_digest(plan)}
        ir["environment_plan"] = plan
        return ir

    def test_replace_is_returned_and_invalidates_existing_approval(self):
        get_patch, update_patch = self.patched_client()
        with get_patch, update_patch:
            client = TestClient(app)
            response = client.post(f"/api/planning/{SCENARIO_ID}/inventory/override", json={
                "ref_id": "svc-httpd", "action": "replace", "component_id": "vuln-struts2-s2-045",
            })

            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
            service = body["scenario"]["services"][0]
            self.assertEqual(body["scenario"]["ir_version"], 5)
            self.assertFalse(body["scenario"]["environment_plan"]["approval"]["approved"])
            self.assertEqual(service["cve"], ["CVE-2024-12345"])
            self.assertEqual(service["inventory_override"]["action"], "replace")
            item = next(row for row in body["items"] if row["ref_id"] == "svc-httpd")
            self.assertEqual(item["auto_resolution"]["component_id"], "oss-httpd")
            self.assertEqual(item["resolution"]["component_id"], "vuln-struts2-s2-045")
            self.assertTrue(item["resolution"]["is_substitute"])
            self.assertEqual(item["resolution"]["reproduces_cve"], [])

            replanned = client.post(f"/api/planning/{SCENARIO_ID}/dependencies")
            self.assertEqual(replanned.status_code, 200, replanned.text)
            planned_service = next(s for s in replanned.json()["services"] if s["id"] == "svc-httpd")
            self.assertEqual(planned_service["catalogue_component"], "vuln-struts2-s2-045")
            self.assertEqual(planned_service["cve"], ["CVE-2024-12345"])
            self.assertEqual(planned_service["reproduces_cve"], [])

    def test_accept_keeps_the_automatic_substitute_flagged(self):
        self.saved["services"] = [{"id": "svc-horizon", "name": "VMware Horizon", "host_ref": "h1",
                                    "cve": ["CVE-2021-44228"], "epistemic_status": "supported", "source": "llm"}]
        get_patch, update_patch = self.patched_client()
        with get_patch, update_patch:
            response = TestClient(app).post(f"/api/planning/{SCENARIO_ID}/inventory/override", json={
                "ref_id": "svc-horizon", "action": "accept",
            })
        self.assertEqual(response.status_code, 200, response.text)
        item = response.json()["items"][0]
        self.assertEqual(item["resolution"]["component_id"], "vuln-log4shell-solr")
        self.assertTrue(item["resolution"]["is_substitute"])
        self.assertIsNone(item["auto_resolution"])

    def test_recommendation_is_separate_from_adopted_override(self):
        self.saved["services"] = [{"id": "svc-horizon", "name": "VMware Horizon", "host_ref": "h1",
                                    "cve": ["CVE-2021-44228"], "epistemic_status": "supported", "source": "llm"}]
        get_patch, update_patch = self.patched_client()
        with get_patch, update_patch:
            client = TestClient(app)
            recommendation = client.get(f"/api/planning/{SCENARIO_ID}/inventory")
            self.assertEqual(recommendation.status_code, 200, recommendation.text)
            item = recommendation.json()["items"][0]
            self.assertTrue(item["pending_confirmation"])
            self.assertIsNone(item["override"])
            self.assertEqual(item["resolution"]["component_id"], "vuln-log4shell-solr")

            not_applied = client.post(f"/api/planning/{SCENARIO_ID}/dependencies")
            self.assertEqual(not_applied.status_code, 200, not_applied.text)
            service = next(s for s in not_applied.json()["services"] if s["id"] == "svc-horizon")
            self.assertNotIn("catalogue_component", service)
            self.assertTrue(service["not_reproducible"])

            adopted = client.post(f"/api/planning/{SCENARIO_ID}/inventory/override", json={
                "ref_id": "svc-horizon", "action": "accept",
            })
            self.assertEqual(adopted.status_code, 200, adopted.text)
            adopted_item = adopted.json()["items"][0]
            self.assertFalse(adopted_item["pending_confirmation"])
            self.assertEqual(adopted_item["override"]["action"], "accept")

            planned = client.post(f"/api/planning/{SCENARIO_ID}/dependencies")
            self.assertEqual(planned.status_code, 200, planned.text)
            service = next(s for s in planned.json()["services"] if s["id"] == "svc-horizon")
            self.assertEqual(service["catalogue_component"], "vuln-log4shell-solr")

            cleared = client.post(f"/api/planning/{SCENARIO_ID}/inventory/override", json={
                "ref_id": "svc-horizon", "action": "clear",
            })
            self.assertEqual(cleared.status_code, 200, cleared.text)
            unadopted = client.post(f"/api/planning/{SCENARIO_ID}/dependencies")
            self.assertEqual(unadopted.status_code, 200, unadopted.text)
            service = next(s for s in unadopted.json()["services"] if s["id"] == "svc-horizon")
            self.assertNotIn("catalogue_component", service)
            self.assertTrue(service["not_reproducible"])

    def test_unknown_refs_invalid_payloads_and_host_os_overrides_are_rejected(self):
        get_patch, update_patch = self.patched_client()
        with get_patch, update_patch:
            client = TestClient(app)
            unknown = client.post(f"/api/planning/{SCENARIO_ID}/inventory/override", json={
                "ref_id": "missing", "action": "clear",
            })
            self.assertEqual(unknown.status_code, 404)
            self.assertIn("not found", unknown.json()["detail"])

            invalid_action = client.post(f"/api/planning/{SCENARIO_ID}/inventory/override", json={
                "ref_id": "svc-httpd", "action": "guess",
            })
            self.assertEqual(invalid_action.status_code, 422)

            extra_field = client.post(f"/api/planning/{SCENARIO_ID}/inventory/override", json={
                "ref_id": "svc-httpd", "action": "clear", "unexpected": "value",
            })
            self.assertEqual(extra_field.status_code, 422)

            blank_ref = client.post(f"/api/planning/{SCENARIO_ID}/inventory/override", json={
                "ref_id": "   ", "action": "clear",
            })
            self.assertEqual(blank_ref.status_code, 422)

            missing_component = client.post(f"/api/planning/{SCENARIO_ID}/inventory/override", json={
                "ref_id": "svc-httpd", "action": "replace",
            })
            self.assertEqual(missing_component.status_code, 422)

            unavailable = client.post(f"/api/planning/{SCENARIO_ID}/inventory/override", json={
                "ref_id": "svc-httpd", "action": "replace", "component_id": "unsupported-horizon",
            })
            self.assertEqual(unavailable.status_code, 422)

            invalid_version = client.post(f"/api/planning/{SCENARIO_ID}/inventory/override", json={
                "ref_id": "svc-httpd", "action": "version", "version": "not-a-release",
            })
            self.assertEqual(invalid_version.status_code, 422)

            host = client.post(f"/api/planning/{SCENARIO_ID}/inventory/override", json={
                "ref_id": "h1", "action": "replace", "component_id": "os-ubuntu-24.04",
            })
            self.assertEqual(host.status_code, 422)
            self.assertIn("not supported", host.json()["detail"])

    def test_clear_drops_override_and_unknown_scenario_has_detail(self):
        self.saved["services"][0]["inventory_override"] = {
            "action": "replace", "component_id": "vuln-struts2-s2-045", "at": "2026-11-16T00:00:00+00:00",
        }
        get_patch, update_patch = self.patched_client()
        with get_patch, update_patch:
            client = TestClient(app)
            cleared = client.post(f"/api/planning/{SCENARIO_ID}/inventory/override", json={
                "ref_id": "svc-httpd", "action": "clear",
            })
            self.assertEqual(cleared.status_code, 200, cleared.text)
            scenario = cleared.json()["scenario"]
            self.assertEqual(scenario["ir_version"], 5)
            self.assertNotIn("inventory_override", scenario["services"][0])
            self.assertFalse(scenario["environment_plan"]["approval"]["approved"])

            missing = client.get("/api/planning/scn_unknown/inventory")
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["detail"], "Scenario not found")

    def test_version_override_is_user_supplied_and_does_not_change_source_version(self):
        self.saved["services"] = [{"id": "svc-nginx", "name": "NGINX", "host_ref": "h1",
                                    "epistemic_status": "supported", "source": "llm"}]
        get_patch, update_patch = self.patched_client()
        with get_patch, update_patch:
            client = TestClient(app)
            response = client.post(f"/api/planning/{SCENARIO_ID}/inventory/override", json={
                "ref_id": "svc-nginx", "action": "version", "version": "1.31.8",
            })
            self.assertEqual(response.status_code, 200, response.text)
            item = response.json()["items"][0]
            self.assertEqual(item["resolution"]["component_id"], "oss-nginx")
            self.assertEqual(item["resolution"]["version_basis"], "user_supplied")
            self.assertEqual(item["override"]["version"], "1.31.8")
            self.assertIsNotNone(item["auto_resolution"])

            planned = client.post(f"/api/planning/{SCENARIO_ID}/dependencies")
            self.assertEqual(planned.status_code, 200, planned.text)
            service = next(s for s in planned.json()["services"] if s["id"] == "svc-nginx")
            self.assertNotIn("version", service)
            self.assertEqual(service["deployed_version"], "1.31.8")
            self.assertEqual(service["version_basis"], "user_supplied")
            self.assertFalse(any(item["field"] == "version for NGINX" for item in planned.json()["missing_items"]))

    def test_program_service_choice_survives_api_replan_and_clear_restores_auto(self):
        ir = sample_ir()
        ir["actions"] = [{"id": "a1", "name": "Exploit Apache HTTP Server on the portal",
                           "target_host_ref": "h1", "attack_technique": "T1190",
                           "epistemic_status": "supported", "source": "llm", "evidence_refs": []}]
        ir["services"] = []
        ir["indicators"] = [{"id": "i1", "type": "cve", "value": "CVE-2024-12345"}]
        ir["missing_items"] = [{"id": "m1", "field": "affected software for CVE-2024-12345",
                                "category": "software", "reason": "The CVE is not linked to a source service.",
                                "status": "open"}]
        self.saved = plan_dependencies(ir)
        self.assertEqual(self.saved["services"][0]["source"], "program")
        self.assertEqual(self.saved["services"][0]["cve"], [])
        service_id = self.saved["services"][0]["id"]
        get_patch, update_patch = self.patched_client()

        with get_patch, update_patch:
            client = TestClient(app)
            selected = client.post(f"/api/planning/{SCENARIO_ID}/inventory/override", json={
                "ref_id": service_id, "action": "replace", "component_id": "vuln-struts2-s2-045",
            })
            self.assertEqual(selected.status_code, 200, selected.text)
            self.assertEqual(selected.json()["scenario"]["ir_version"], 5)
            self.assertFalse(selected.json()["scenario"]["environment_plan"]["approval"]["approved"])
            replanned = client.post(f"/api/planning/{SCENARIO_ID}/dependencies")
            self.assertEqual(replanned.status_code, 200, replanned.text)
            chosen = next(item for item in replanned.json()["services"] if item["id"] == service_id)
            self.assertEqual(chosen["source"], "program")
            self.assertEqual(chosen["catalogue_component"], "vuln-struts2-s2-045")
            self.assertEqual(chosen["inventory_override"]["action"], "replace")
            self.assertEqual(chosen["cve"], [])
            self.assertEqual(chosen["reproduces_cve"], [])
            self.assertEqual(replanned.json()["indicators"], ir["indicators"])
            self.assertEqual(next(item for item in replanned.json()["missing_items"] if item["id"] == "m1")["status"], "open")

            cleared = client.post(f"/api/planning/{SCENARIO_ID}/inventory/override", json={
                "ref_id": service_id, "action": "clear",
            })
            self.assertEqual(cleared.status_code, 200, cleared.text)
            self.assertEqual(cleared.json()["scenario"]["ir_version"], 6)
            self.assertFalse(cleared.json()["scenario"]["environment_plan"]["approval"]["approved"])
            restored = client.post(f"/api/planning/{SCENARIO_ID}/dependencies")
            self.assertEqual(restored.status_code, 200, restored.text)
            automatic = next(item for item in restored.json()["services"] if item["id"] == service_id)
            self.assertEqual(automatic["catalogue_component"], "oss-httpd")
            self.assertFalse(automatic["is_substitute"])
            self.assertEqual(automatic["cve"], [])
            self.assertEqual(restored.json()["indicators"], ir["indicators"])
            self.assertEqual(next(item for item in restored.json()["missing_items"] if item["id"] == "m1")["status"], "open")

    def test_unconfirmed_legacy_substitute_is_blocked_from_iac_and_deploy(self):
        self.saved["services"] = [{
            "id": "svc-legacy", "name": "VMware Horizon", "host_ref": "h1",
            "catalogue_component": "vuln-log4shell-solr", "is_substitute": True,
            "substitute_of": "VMware Horizon", "cve": ["CVE-2021-44228"],
            "source": "program", "epistemic_status": "inferred",
        }]
        plan = self.saved["environment_plan"]
        plan["approval"]["connections_digest"] = connections_digest(plan)
        get_patch, update_patch = self.patched_client()

        with get_patch, update_patch, patch.object(manager, "record") as record, \
                patch.object(manager, "do_up") as do_up:
            client = TestClient(app)
            generated = client.post(f"/api/iac/{SCENARIO_ID}/generate")
            self.assertEqual(generated.status_code, 422, generated.text)
            self.assertIn("accept or replace", str(generated.json()["detail"]))

            with TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
                (root / "report.json").write_text("{}\n", encoding="utf-8")
                with patch.object(generator, "generated_dir", return_value=root):
                    old_bundle = client.get(f"/api/iac/{SCENARIO_ID}")
                    self.assertEqual(old_bundle.status_code, 409, old_bundle.text)
                    self.assertIn("inventory", str(old_bundle.json()["detail"]).casefold())
                    with self.assertRaises(PlanError):
                        generator.get_generated(SCENARIO_ID)

            deployed = client.post(f"/api/deploy/{SCENARIO_ID}/up", json={"test_approved": True})
            self.assertEqual(deployed.status_code, 409, deployed.text)
            self.assertEqual(deployed.json()["detail"]["code"], "inventory_confirmation_required")
            self.assertIn("accept or replace", deployed.json()["detail"]["message"])
            do_up.assert_not_called()
            self.assertTrue(any(call.args[1:3] == ("up", "rejected") for call in record.call_args_list))

    def test_legacy_substitute_is_allowed_when_existing_user_choice_is_recorded(self):
        base = {"id": "s1", "name": "VMware Horizon", "substitute_of": "VMware Horizon",
                "catalogue_component": "vuln-log4shell-solr", "is_substitute": True}
        self.assertEqual(unconfirmed_inventory_substitutes({"services": [{
            **base, "inventory_override": {"action": "accept", "at": "2026-11-16T00:00:00+00:00"},
        }]}), [])
        self.assertEqual(unconfirmed_inventory_substitutes({"services": [{
            **base, "field_sources": {"catalogue_component": "user"},
        }]}), [])
        self.assertEqual(unconfirmed_inventory_substitutes({"services": [{
            **base, "substitute_basis": "user_chosen",
        }]}), [])
        self.assertEqual(len(unconfirmed_inventory_substitutes({"services": [{
            "id": "s2", "name": "VMware Horizon", "catalogue_component": "vuln-log4shell-solr",
            "is_substitute": True,
        }]})), 1)

    def test_manager_core_blocks_legacy_substitute_before_backend_selection(self):
        legacy = sample_ir()
        legacy["services"] = [{"id": "svc-legacy", "name": "VMware Horizon",
                               "catalogue_component": "vuln-log4shell-solr", "is_substitute": True,
                               "substitute_of": "VMware Horizon", "source": "program"}]
        with patch.object(store, "get", return_value=legacy), \
                patch.object(manager, "deploy_backend") as select_backend:
            with self.assertRaises(PlanError) as raised:
                manager.do_up(SCENARIO_ID)
        self.assertIn("accept or replace", str(raised.exception))
        select_backend.assert_not_called()

    def test_replacement_must_match_dependency_and_topology_before_iac_or_deploy(self):
        self.saved = self.stale_replacement_scenario()
        core_do_up = manager.do_up
        get_patch, update_patch = self.patched_client()
        with get_patch, update_patch, TemporaryDirectory() as directory, \
                patch.object(generator, "generated_dir", return_value=Path(directory)), \
                patch.object(manager, "record") as record, patch.object(manager, "do_up") as do_up:
            client = TestClient(app)
            # A previously generated Solr bundle exists before the user asks for Struts.
            old_bundle = client.post(f"/api/iac/{SCENARIO_ID}/generate")
            self.assertEqual(old_bundle.status_code, 200, old_bundle.text)
            self.assertIn("vulhub/solr:", old_bundle.json()["compose"])

            selected = client.post(f"/api/planning/{SCENARIO_ID}/inventory/override", json={
                "ref_id": "svc-horizon", "action": "replace", "component_id": "vuln-struts2-s2-045",
            })
            self.assertEqual(selected.status_code, 200, selected.text)
            self.assertFalse(selected.json()["scenario"]["environment_plan"]["approval"]["approved"])

            # Topology alone still carries Solr, even though the user's requested replacement is Struts.
            topology = client.post(f"/api/planning/{SCENARIO_ID}/topology")
            self.assertEqual(topology.status_code, 200, topology.text)
            self.assertEqual(topology.json()["environment_plan"]["hosts"][0]["image_hint"],
                             "vuln-log4shell-solr")
            approval = client.post(f"/api/planning/{SCENARIO_ID}/topology/approve", json={"approved": True})
            self.assertEqual(approval.status_code, 200, approval.text)

            generated = client.post(f"/api/iac/{SCENARIO_ID}/generate")
            self.assertEqual(generated.status_code, 422, generated.text)
            mismatch = next(item for item in generated.json()["detail"]["report"]["blockers"]
                            if item["code"] == "inventory_plan_mismatch")
            self.assertEqual(mismatch["selected_component"], "vuln-struts2-s2-045")
            self.assertEqual(mismatch["plan_component"], "vuln-log4shell-solr")

            stale_bundle = client.get(f"/api/iac/{SCENARIO_ID}")
            self.assertEqual(stale_bundle.status_code, 409, stale_bundle.text)
            with self.assertRaises(PlanError):
                generator.get_generated(SCENARIO_ID)

            rejected = client.post(f"/api/deploy/{SCENARIO_ID}/up", json={"test_approved": True})
            self.assertEqual(rejected.status_code, 409, rejected.text)
            self.assertEqual(rejected.json()["detail"]["code"], "inventory_plan_mismatch")
            do_up.assert_not_called()

            # The core manager guard runs before it selects any backend.
            with patch.object(manager, "deploy_backend") as select_backend:
                with self.assertRaises(PlanError):
                    core_do_up(SCENARIO_ID)
                select_backend.assert_not_called()

            # Replanning dependencies first updates the selected component; topology then
            # records that same image, and only then can IaC and the deploy route proceed.
            replanned = client.post(f"/api/planning/{SCENARIO_ID}/dependencies")
            self.assertEqual(replanned.status_code, 200, replanned.text)
            service = next(item for item in replanned.json()["services"] if item["id"] == "svc-horizon")
            self.assertEqual(service["catalogue_component"], "vuln-struts2-s2-045")
            self.assertEqual(service["cve"], [])
            self.assertEqual(replanned.json()["indicators"], self.stale_replacement_scenario()["indicators"])
            self.assertEqual(next(item for item in replanned.json()["missing_items"]
                                  if item["id"] == "m1")["status"], "open")

            topology = client.post(f"/api/planning/{SCENARIO_ID}/topology")
            self.assertEqual(topology.status_code, 200, topology.text)
            host = next(item for item in topology.json()["environment_plan"]["hosts"] if item["id"] == "h1")
            self.assertEqual(host["image_hint"], "vuln-struts2-s2-045")
            approval = client.post(f"/api/planning/{SCENARIO_ID}/topology/approve", json={"approved": True})
            self.assertEqual(approval.status_code, 200, approval.text)

            generated = client.post(f"/api/iac/{SCENARIO_ID}/generate")
            self.assertEqual(generated.status_code, 200, generated.text)
            self.assertIn("vulhub/struts2:", generated.json()["compose"])
            self.assertEqual(client.get(f"/api/iac/{SCENARIO_ID}").status_code, 200)

            do_up.return_value = {"ok": True, "state": "running"}
            deployed = client.post(f"/api/deploy/{SCENARIO_ID}/up", json={"test_approved": True})
            self.assertEqual(deployed.status_code, 200, deployed.text)
            do_up.assert_called_once_with(SCENARIO_ID, "internal", None)
            self.assertTrue(any(call.args[1:3] == ("up", "rejected") for call in record.call_args_list))

    def test_removed_service_blocks_old_generated_topology_and_deploy(self):
        self.saved = self.planned_replacement_scenario()
        core_do_up = manager.do_up
        get_patch, update_patch = self.patched_client()
        with get_patch, update_patch, TemporaryDirectory() as directory, \
                patch.object(generator, "generated_dir", return_value=Path(directory)), \
                patch.object(manager, "record"), patch.object(manager, "do_up") as do_up:
            client = TestClient(app)
            generated = client.post(f"/api/iac/{SCENARIO_ID}/generate")
            self.assertEqual(generated.status_code, 200, generated.text)
            self.assertIn("vulhub/struts2:", generated.json()["compose"])

            edited = client.put(f"/api/scenario/{SCENARIO_ID}", json={"ir": {"services": []}})
            self.assertEqual(edited.status_code, 200, edited.text)
            self.assertEqual(edited.json()["services"], [])
            self.assertEqual(edited.json()["environment_plan"]["hosts"][0]["image_hint"],
                             "vuln-struts2-s2-045")

            generated = client.post(f"/api/iac/{SCENARIO_ID}/generate")
            self.assertEqual(generated.status_code, 422, generated.text)
            self.assertTrue(any(item["host_id"] == "h1"
                                for item in generated.json()["detail"]["report"]["blockers"]))
            stale_bundle = client.get(f"/api/iac/{SCENARIO_ID}")
            self.assertEqual(stale_bundle.status_code, 409, stale_bundle.text)
            self.assertIn("no current source service", str(stale_bundle.json()["detail"]).casefold())

            rejected = client.post(f"/api/deploy/{SCENARIO_ID}/up", json={"test_approved": True})
            self.assertEqual(rejected.status_code, 409, rejected.text)
            self.assertEqual(rejected.json()["detail"]["code"], "inventory_plan_mismatch")
            do_up.assert_not_called()
            with patch.object(manager, "deploy_backend") as select_backend:
                with self.assertRaises(PlanError):
                    core_do_up(SCENARIO_ID)
                select_backend.assert_not_called()

    def test_manager_accepts_aligned_substitute_without_live_backend(self):
        self.saved = self.planned_replacement_scenario()
        compose = "services:\n  target:\n    image: vuln-struts2-s2-045\n"

        backend = Mock()
        backend.up.return_value = {"ok": True, "state": "running", "vmid": 900123, "containers": []}
        isolation = {"checked": True, "isolated": True, "evidence": {"test": "in-memory"}}
        with patch.object(store, "get", side_effect=lambda scenario_id: copy.deepcopy(self.saved)), \
                patch.object(manager, "deploy_backend", return_value="proxmox"), \
                patch.object(manager, "_backend_conflict", return_value=None), \
                patch.object(manager, "get_generated", return_value={"compose": compose}), \
                patch.object(manager, "_active_proxmox_deployment", return_value=None), \
                patch.object(manager, "_proxmox_backend", return_value=backend), \
                patch.object(manager, "_proxmox_isolation_report", return_value=isolation), \
                patch.object(manager, "record", return_value={"id": "in-memory"}):
            result = manager.do_up(SCENARIO_ID)

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["backend"], "proxmox")
        backend.up.assert_called_once_with(SCENARIO_ID, compose, host_id="worker", attach_lab_network=False,
                                           compose_sha256=unittest.mock.ANY)


if __name__ == "__main__":
    unittest.main()
