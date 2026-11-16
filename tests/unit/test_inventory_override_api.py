"""Deterministic tests for the inventory override API; no deployment backend is used."""
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api"))

from app import store  # noqa: E402
from app.main import app  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
