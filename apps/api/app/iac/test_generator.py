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
