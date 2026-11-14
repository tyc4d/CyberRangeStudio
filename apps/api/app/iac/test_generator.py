"""Offline checks for the environment-plan to Compose compiler."""
import unittest

import yaml

from cr_contracts import iter_errors

from app.iac.generator import compose_document, inspect_plan


DEMO_PLAN = {
    "hosts": [
        {"id": "demo-api", "role": "demo-api", "image_hint": "demo-api",
         "services": [{"name": "http", "port": 8080, "protocol": "tcp"}], "networks": ["inside"]},
        {"id": "demo-client", "role": "demo-client", "image_hint": "demo-client", "networks": ["inside"]},
    ],
    "networks": [{"id": "inside", "internal": True}],
    "connections": [{"from_host": "demo-client", "to_host": "demo-api", "port": 8080,
                     "protocol": "tcp", "reason": "one harmless demo HTTP request"}],
}

REAL_PLAN = {
    "hosts": [
        {"id": "web", "role": "web", "image_hint": "oss-nginx", "component_mode": "real",
         "services": [{"name": "http", "port": 80, "protocol": "tcp"}], "networks": ["inside"]},
        {"id": "apache", "role": "web", "image_hint": "oss-httpd", "component_mode": "real",
         "services": [{"name": "http", "port": 80, "protocol": "tcp"}], "networks": ["inside"]},
        {"id": "db", "role": "database", "image_hint": "oss-postgres", "component_mode": "real",
         "services": [{"name": "postgres", "port": 5432, "protocol": "tcp"}], "networks": ["inside"]},
        {"id": "attacker", "role": "attacker", "image_hint": "oss-attacker", "component_mode": "real",
         "networks": ["inside"]},
    ],
    "networks": [{"id": "inside", "internal": True}],
    "connections": [],
}


class ComposeGeneratorTests(unittest.TestCase):
    def test_environment_plan_generates_valid_safe_compose(self):
        self.assertEqual(iter_errors("environment-plan", DEMO_PLAN), [])
        _, report = inspect_plan(DEMO_PLAN, "offline-demo")
        self.assertTrue(report["deployable"])

        compose = compose_document(DEMO_PLAN, "offline-demo")
        document = yaml.safe_load(compose)

        self.assertEqual(document["services"]["demo-api"]["image"], "cr-demo-offline-demo-demo-api:local")
        self.assertTrue(document["services"]["demo-client"]["image"].startswith("python@sha256:"))
        self.assertTrue(all(service["container_name"].startswith("cr-demo-") for service in document["services"].values()))
        self.assertTrue(all(service.get("privileged") is not True for service in document["services"].values()))
        self.assertTrue(document["networks"]["inside"]["internal"])
        self.assertEqual(document["services"]["demo-api"]["ports"][0]["host_ip"], "127.0.0.1")
        host_port = int(document["services"]["demo-api"]["ports"][0]["published"])
        self.assertTrue(42000 <= host_port <= 42999)
        self.assertNotIn("password", compose.lower())
        self.assertNotIn("api_key", compose.lower())


    def test_arbitrary_image_hint_is_never_used_as_image(self):
        # Safety: an arbitrary/untrusted image hint must NEVER become the deployed image.
        # The host is mapped to a harmless local stand-in instead and flagged as a substitute.
        arbitrary = "arbitrary-registry/image:latest"
        plan = {**DEMO_PLAN, "hosts": [{**DEMO_PLAN["hosts"][0], "image_hint": arbitrary}, DEMO_PLAN["hosts"][1]]}
        _, report = inspect_plan(plan, "offline-demo")
        host0 = report["components"][0]
        self.assertIn(host0["component"], {"demo-api", "demo-client"})
        self.assertNotIn(arbitrary, str(host0.get("image")))
        self.assertTrue(host0["substitute"])  # benign stand-in, not the named software
        doc = yaml.safe_load(compose_document(plan, "offline-demo"))
        for service in doc["services"].values():
            self.assertNotIn(arbitrary, service.get("image", ""))

    def test_catalogue_images_are_real_versioned_digest_pins_with_hardening(self):
        self.assertEqual(iter_errors("environment-plan", REAL_PLAN), [])
        _, report = inspect_plan(REAL_PLAN, "real-services")
        self.assertTrue(report["deployable"], report["errors"])
        by_host = {component["host_id"]: component for component in report["components"]}
        document = yaml.safe_load(compose_document(REAL_PLAN, "real-services"))

        for host_id, version in (("web", "1.31.8"), ("apache", "2.4.71"), ("db", "16.16"), ("attacker", "3.22")):
            component = by_host[host_id]
            service = document["services"][host_id]
            self.assertEqual(component["component_mode"], "real")
            self.assertEqual(component["version"], version)
            self.assertRegex(component["digest"], r"^sha256:[0-9a-f]{64}$")
            self.assertIn("@" + component["digest"], component["image"])
            self.assertEqual(service["image"], component["image"])
            self.assertTrue(service["read_only"])
            self.assertIn("ALL", service["cap_drop"])
            self.assertIn("no-new-privileges:true", service["security_opt"])
            self.assertIsNot(service.get("privileged"), True)
            for published in service.get("ports", []):
                self.assertEqual(published["host_ip"], "127.0.0.1")
                self.assertTrue(42000 <= int(published["published"]) <= 42999)
        self.assertEqual(document["services"]["db"]["environment"], {"POSTGRES_HOST_AUTH_METHOD": "trust"})
        self.assertTrue(any("/var/lib/postgresql/data" in mount for mount in document["services"]["db"]["tmpfs"]))
        self.assertTrue(all(network["internal"] for network in document["networks"].values()))
        self.assertNotIn("password", str(document).lower())

    def test_mode_selection_and_legacy_inference(self):
        real = {"id": "web", "role": "web", "image_hint": "oss-nginx", "services": [{"name": "http", "port": 80}],
                "networks": ["inside"]}
        substitute = {**real, "component_mode": "substitute"}
        plan = {"hosts": [real], "networks": [{"id": "inside", "internal": True}]}
        _, report = inspect_plan(plan, "mode-test")
        self.assertEqual(report["components"][0]["component_mode"], "real")
        self.assertIn("@sha256:", report["components"][0]["image"])

        substitute_plan = {**plan, "hosts": [substitute]}
        _, substitute_report = inspect_plan(substitute_plan, "mode-test")
        self.assertEqual(substitute_report["components"][0]["component"], "demo-api")
        self.assertEqual(substitute_report["components"][0]["component_mode"], "substitute")
        self.assertTrue(substitute_report["components"][0]["substitute"])
        substitute_doc = yaml.safe_load(compose_document(substitute_plan, "mode-test"))
        self.assertEqual(substitute_doc["services"]["web"]["image"], "cr-demo-mode-test-web:local")

    def test_unknown_explicit_real_component_is_rejected(self):
        plan = {"hosts": [{"id": "unknown", "role": "x", "image_hint": "oss-unknown",
                            "component_mode": "real", "networks": ["inside"]}],
                "networks": [{"id": "inside", "internal": True}]}
        _, report = inspect_plan(plan, "unknown-real")
        self.assertFalse(report["deployable"])
        self.assertTrue(any("safe local image" in error for error in report["errors"]))
