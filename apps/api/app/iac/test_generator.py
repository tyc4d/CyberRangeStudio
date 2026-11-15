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


EXPOSED_PLAN = {
    "hosts": [
        {"id": "attacker", "role": "attacker", "image_hint": "oss-attacker", "component_mode": "real",
         "networks": ["external"]},
        {"id": "web", "role": "exposed web", "image_hint": "oss-wordpress", "component_mode": "real",
         "services": [{"name": "wordpress", "port": 80, "protocol": "tcp"}], "networks": ["external", "inside"]},
        {"id": "db", "role": "internal database", "image_hint": "oss-mysql", "component_mode": "real",
         "services": [{"name": "mysql", "port": 3306, "protocol": "tcp"}], "networks": ["inside"]},
        {"id": "portal", "role": "exposed web", "image_hint": "vuln-struts2-s2-045", "component_mode": "real",
         "services": [{"name": "struts", "port": 8080, "protocol": "tcp"}], "networks": ["external", "inside"]},
    ],
    "networks": [{"id": "inside", "internal": True}, {"id": "external", "internal": False}],
    "connections": [
        {"from_host": "attacker", "to_host": "web", "port": 80, "protocol": "tcp"},
        {"from_host": "web", "to_host": "db", "port": 3306, "protocol": "tcp"},
        {"from_host": "attacker", "to_host": "portal", "port": 8080, "protocol": "tcp"},
    ],
}


class ExposureAndDependencyTests(unittest.TestCase):
    def setUp(self):
        _, self.report = inspect_plan(EXPOSED_PLAN, "exposure")
        self.assertTrue(self.report["deployable"], self.report["errors"])
        self.document = yaml.safe_load(compose_document(EXPOSED_PLAN, "exposure"))
        self.by_host = {c["host_id"]: c for c in self.report["components"]}

    def test_only_hosts_on_a_non_internal_plan_network_are_published(self):
        services = self.document["services"]
        self.assertEqual(self.report["host_port_mappings"],
                         [{"host_id": "web", "container_port": 80, "host_port": 42000, "env": "CR_HOSTPORT_0",
                           "via": "cr-gateway"}])
        # The published port terminates on the forwarder; the lab service itself is never
        # attached to a bridge with a route to the host or the outside.
        gateway = services["cr-gateway"]
        self.assertEqual(gateway["ports"], [{"target": 20000, "published": "${CR_HOSTPORT_0:-42000}",
                                             "host_ip": "${CR_BIND_IP:-127.0.0.1}", "protocol": "tcp"}])
        self.assertEqual(gateway["command"][-1], "20000=web:80")
        self.assertEqual(gateway["networks"], ["edge", "external"])
        self.assertNotIn("ports", services["web"])
        self.assertNotIn("edge", services["web"]["networks"])
        self.assertEqual([name for name, service in services.items() if "edge" in service["networks"]],
                         ["cr-gateway"])
        # internal database: no host port, no edge network, so no route out of the lab
        self.assertNotIn("ports", services["db"])
        self.assertEqual(services["db"]["networks"], ["inside"])
        self.assertEqual(self.by_host["db"]["exposure"], "internal_only")

    def test_vulnerable_exercise_image_is_never_published_even_when_exposed_in_the_plan(self):
        portal = self.document["services"]["portal"]
        self.assertNotIn("ports", portal)
        self.assertNotIn("edge", portal["networks"])
        self.assertEqual(self.by_host["portal"]["exposure"], "isolated_only")
        self.assertTrue(self.by_host["portal"]["vulnerable"])
        self.assertEqual(self.by_host["portal"]["cves"], ["CVE-2017-5638"])
        self.assertFalse(self.by_host["portal"]["published"])

    def test_edge_network_cannot_carry_traffic_between_hosts_or_outbound(self):
        edge = self.document["networks"]["edge"]
        self.assertFalse(edge["internal"])
        self.assertEqual(edge["driver_opts"], {"com.docker.network.bridge.enable_icc": "false",
                                               "com.docker.network.bridge.enable_ip_masquerade": "false"})
        for network_id, network in self.document["networks"].items():
            if network_id != "edge":
                self.assertTrue(network["internal"])
                # no host-side bridge address: lab containers cannot reach host services
                self.assertEqual(network["driver_opts"], {"com.docker.network.bridge.gateway_mode_ipv4": "isolated"})

    def test_forwarder_listens_only_on_its_edge_address(self):
        from app.iac.generator import _GATEWAY_FORWARDER
        compile(_GATEWAY_FORWARDER, "forwarder", "exec")  # valid Python
        self.assertNotIn("0.0.0.0", _GATEWAY_FORWARDER)
        self.assertIn("start_server(handle,BIND,lp)", _GATEWAY_FORWARDER)
        self.assertIn("refusing to listen", _GATEWAY_FORWARDER)   # no edge interface -> does not start
        self.assertIn("if any(peer in n for n in LAB)", _GATEWAY_FORWARDER)  # lab-subnet peers are dropped
        gateway = self.document["services"]["cr-gateway"]
        self.assertEqual(gateway["command"][2], _GATEWAY_FORWARDER)
        self.assertEqual(gateway["healthcheck"]["test"][-2:], ["--check", "20000"])

    def test_gateway_is_a_reserved_host_id(self):
        plan = {**EXPOSED_PLAN, "hosts": [*EXPOSED_PLAN["hosts"],
                                          {"id": "cr-gateway", "role": "x", "image_hint": "oss-attacker",
                                           "component_mode": "real", "networks": ["inside"]}]}
        _, report = inspect_plan(plan, "exposure")
        self.assertFalse(report["deployable"])

    def test_edge_is_a_reserved_network_id(self):
        plan = {**EXPOSED_PLAN, "networks": [*EXPOSED_PLAN["networks"], {"id": "edge", "internal": True}]}
        _, report = inspect_plan(plan, "exposure")
        self.assertFalse(report["deployable"])

    def test_connections_become_start_order_and_database_wiring(self):
        services = self.document["services"]
        self.assertEqual(services["web"]["depends_on"], {"db": {"condition": "service_healthy"}})
        self.assertEqual(services["web"]["environment"]["WORDPRESS_DB_HOST"], "db:3306")
        self.assertEqual(services["web"]["environment"]["WORDPRESS_DB_PASSWORD"],
                         "${CR_DB_PASSWORD:?set at deploy time}")
        self.assertEqual(self.by_host["web"]["wired_to"], [{"host": "db", "port": 3306, "software": "mysql"}])
        self.assertIn("healthcheck", services["db"])
        self.assertIn("healthcheck", services["web"])

    def test_application_without_its_database_connection_is_not_deployable(self):
        plan = {**EXPOSED_PLAN, "connections": [EXPOSED_PLAN["connections"][0]]}
        _, report = inspect_plan(plan, "exposure")
        self.assertFalse(report["deployable"])
        self.assertTrue(any("needs a declared connection" in error for error in report["errors"]))

    def test_connection_cycle_does_not_produce_a_dependency_cycle(self):
        plan = {
            "hosts": [{"id": name, "role": "web", "image_hint": "oss-nginx", "component_mode": "real",
                       "services": [{"name": "http", "port": 80}], "networks": ["inside"]} for name in ("a", "b")],
            "networks": [{"id": "inside", "internal": True}],
            "connections": [{"from_host": "a", "to_host": "b", "port": 80}, {"from_host": "b", "to_host": "a", "port": 80}],
        }
        services = yaml.safe_load(compose_document(plan, "cycle"))["services"]
        self.assertEqual(services["a"]["depends_on"], {"b": {"condition": "service_healthy"}})
        self.assertNotIn("depends_on", services["b"])

    def test_every_service_has_resource_limits_and_every_real_image_is_digest_pinned(self):
        for service in self.document["services"].values():
            self.assertTrue(service["mem_limit"] and service["cpus"] and service["pids_limit"])
            self.assertRegex(service["image"], r"@sha256:[0-9a-f]{64}$")

    def test_safety_check_rejects_unpinned_images_extra_capabilities_and_mounts(self):
        from app.iac.generator import _assert_compose_safe, PlanError
        good = compose_document(EXPOSED_PLAN, "exposure")
        _assert_compose_safe(good, "exposure")
        for mutate in (
            lambda d: d["services"]["db"].__setitem__("image", "mysql:8.0.46"),
            lambda d: d["services"]["db"].__setitem__("cap_add", ["NET_ADMIN"]),
            lambda d: d["services"]["db"].__setitem__("volumes", ["/:/host"]),
            lambda d: d["services"]["db"].pop("mem_limit"),
            lambda d: d["networks"]["edge"].pop("driver_opts"),
            lambda d: d["networks"]["inside"].__setitem__("internal", False),
            lambda d: d["services"]["cr-gateway"]["ports"][0].__setitem__("published", "8080"),
            lambda d: d["services"]["cr-gateway"]["ports"][0].__setitem__("host_ip", "0.0.0.0"),
            lambda d: d["services"]["cr-gateway"].__setitem__("image", "python:3"),
            lambda d: d["services"]["web"]["networks"].append("edge"),
            lambda d: d["services"]["portal"].__setitem__("ports", [{"target": 8080, "published": "${CR_HOSTPORT_1:-42001}",
                                                                     "host_ip": "${CR_BIND_IP:-127.0.0.1}"}]),
            lambda d: d["networks"]["inside"].pop("driver_opts"),
            lambda d: d["services"]["db"]["environment"].__setitem__("MYSQL_ROOT_PASSWORD", "hunter2"),
        ):
            document = yaml.safe_load(good)
            mutate(document)
            with self.assertRaises(PlanError):
                _assert_compose_safe(yaml.safe_dump(document), "exposure")


class CatalogueIntegrityTests(unittest.TestCase):
    def test_container_components_are_pinned_and_vulnerable_ones_are_isolated(self):
        from app.planner.catalogue import load_components
        for entry in load_components():
            if entry.get("runtime") != "container":
                continue
            self.assertRegex(entry["digest"], r"^sha256:[0-9a-f]{64}$", entry["id"])
            self.assertEqual(entry["pinned_image"], f"{entry['image']}@{entry['digest']}", entry["id"])
            self.assertNotIn(":latest", entry["image"])
            self.assertIn(entry["version"], entry["image"], entry["id"])
            if entry.get("vulnerable"):
                self.assertEqual(entry.get("exposure"), "isolated_only", entry["id"])
                self.assertTrue(entry.get("cves"), entry["id"])


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
        # A host that sits only on internal networks is never published to the host.
        self.assertNotIn("ports", document["services"]["demo-api"])
        self.assertNotIn("edge", document["networks"])
        self.assertNotIn("password", compose.lower())
        self.assertNotIn("api_key", compose.lower())


    def test_arbitrary_image_hint_is_never_used_as_image(self):
        # Safety + honesty: an arbitrary/untrusted image hint must NEVER become the deployed
        # image, and must NOT be silently turned into a demo stand-in that would imply a real
        # reproduction. Unknown software stays "unsupported" with no image.
        arbitrary = "arbitrary-registry/image:latest"
        plan = {**DEMO_PLAN, "hosts": [{**DEMO_PLAN["hosts"][0], "image_hint": arbitrary}, DEMO_PLAN["hosts"][1]]}
        _, report = inspect_plan(plan, "offline-demo")
        host0 = report["components"][0]
        self.assertEqual(host0["component"], "unsupported")  # honest: not reproduced, not a demo substitute
        self.assertFalse(host0["substitute"])
        self.assertIsNone(host0.get("image"))
        self.assertNotIn(arbitrary, str(host0.get("image")))
        # An unsupported host makes the whole plan non-deployable instead of silently deploying
        # a benign stand-in that would imply the arbitrary software was reproduced.
        self.assertFalse(report["deployable"])

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
            self.assertNotIn("ports", service)  # REAL_PLAN only has an internal network
            for limit in ("mem_limit", "cpus", "pids_limit"):
                self.assertTrue(service[limit])
        self.assertEqual(document["services"]["db"]["environment"], {
            "POSTGRES_PASSWORD": "${CR_PG_PASSWORD:?set at deploy time}",
            "POSTGRES_HOST_AUTH_METHOD": "${CR_PG_AUTH_METHOD:-trust}",
        })
        self.assertTrue(any("/var/lib/postgresql/data" in mount for mount in document["services"]["db"]["tmpfs"]))
        self.assertNotIn("edge", document["networks"])
        self.assertTrue(document["networks"]["inside"]["internal"])
        self.assertEqual(document["services"]["db"]["environment"]["POSTGRES_PASSWORD"],
                         "${CR_PG_PASSWORD:?set at deploy time}")

    def test_postgres_literal_credentials_and_unsafe_bind_values_are_rejected(self):
        from app.iac.generator import _assert_compose_safe, PlanError

        compose = compose_document(REAL_PLAN, "safe-check")
        self.assertNotIn("secret123", compose)
        unsafe = compose.replace("${CR_PG_PASSWORD:?set at deploy time}", "literal-secret")
        with self.assertRaises(PlanError):
            _assert_compose_safe(unsafe, "safe-check")

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


class BlockerAndGroupingTests(unittest.TestCase):
    """Refusals must say which host/service/port is wrong and what the user can change."""

    def _plan(self, services, image="vuln-struts2-s2-045"):
        return {"hosts": [{"id": "h1", "role": "portal", "image_hint": image, "component_mode": "real",
                           "services": services, "networks": ["inside"]},
                          {"id": "h2", "role": "db", "image_hint": "oss-postgres", "component_mode": "real",
                           "services": [{"name": "postgres", "port": 5432}], "networks": ["inside"]}],
                "networks": [{"id": "inside", "internal": True}],
                "connections": [{"from_host": "h1", "to_host": "h2", "port": 5432}]}

    def test_port_not_served_by_the_host_image_is_explained_with_a_fix(self):
        plan = self._plan([{"name": "Apache Struts", "port": 8080}, {"name": "encrypted channel", "port": 80}])
        _, report = inspect_plan(plan, "blk")
        self.assertFalse(report["deployable"])
        blocker = next(b for b in report["blockers"] if b["code"] == "port_not_served_by_image")
        self.assertEqual((blocker["host"], blocker["service"], blocker["port"]), ("h1", "encrypted channel", 80))
        self.assertEqual(blocker["supported_ports"], [8080])
        self.assertIn("h1", blocker["message"])
        self.assertIn("encrypted channel", blocker["message"])
        self.assertIn("8080", blocker["fix"])
        # the short English string older clients match on is still there
        self.assertIn("host h1 declares port 80, unsupported by vuln-struts2-s2-045", report["errors"])
        by_host = {c["host_id"]: c for c in report["components"]}
        self.assertFalse(by_host["h1"]["deployable"])   # not "deployable: yes" next to a failed generation
        self.assertEqual(by_host["h1"]["blockers"], ["port_not_served_by_image"])
        self.assertTrue(by_host["h2"]["deployable"])     # the host that is fine stays fine

    def test_every_error_has_a_blocker_with_message_and_fix(self):
        plan = {"hosts": [{"id": "a", "role": "x", "image_hint": "oss-nginx", "component_mode": "real",
                           "services": [{"name": "dns", "port": 53, "protocol": "udp"}], "networks": ["n1"]},
                          {"id": "b", "role": "y", "image_hint": "not-in-catalogue", "component_mode": "real",
                           "networks": ["n2"]}],
                "networks": [{"id": "n1", "internal": True}, {"id": "n2", "internal": True}],
                "connections": [{"from_host": "a", "to_host": "b", "port": 9}]}
        _, report = inspect_plan(plan, "blk")
        self.assertEqual({b["error"] for b in report["blockers"]}, set(report["errors"]))
        for blocker in report["blockers"]:
            self.assertTrue(blocker["message"] and blocker["fix"], blocker)
        codes = {b["code"] for b in report["blockers"]}
        self.assertLessEqual({"non_tcp_service", "no_image_for_host", "connection_no_shared_network"}, codes)

    def test_services_on_the_same_port_are_one_endpoint(self):
        # the product and the protocol it speaks, both on 80: one check, one published port
        plan = {"hosts": [{"id": "h1", "role": "exposed web", "image_hint": "oss-nginx", "component_mode": "real",
                           "services": [{"name": "MOVEit Transfer", "port": 80}, {"name": "nginx", "port": 80}],
                           "networks": ["external"]}],
                "networks": [{"id": "external", "internal": False}]}
        _, report = inspect_plan(plan, "grp")
        self.assertTrue(report["deployable"], report["errors"])
        self.assertEqual(len(report["host_port_mappings"]), 1)
        self.assertEqual(report["components"][0]["service_ports"],
                         [{"port": 80, "protocol": "tcp", "names": ["MOVEit Transfer", "nginx"]}])
        gateway = yaml.safe_load(compose_document(plan, "grp"))["services"]["cr-gateway"]
        self.assertEqual(len(gateway["ports"]), 1)
        self.assertEqual([arg for arg in gateway["command"] if "=h1:" in arg], ["20000=h1:80"])

    def test_network_report_separates_plan_role_from_what_docker_enforces(self):
        _, report = inspect_plan(EXPOSED_PLAN, "exposure")
        by_id = {n["id"]: n for n in report["networks"]}
        self.assertTrue(by_id["external"]["internal"])            # enforced: always isolated
        self.assertFalse(by_id["external"]["plan_internal"])      # plan: this is the exposed side
        self.assertEqual(by_id["external"]["role"], "exposed_segment")
        self.assertTrue(by_id["external"]["published_to_host"])
        self.assertEqual(by_id["inside"]["role"], "internal_segment")
        self.assertFalse(by_id["inside"]["published_to_host"])
        self.assertTrue(all(n["description"] for n in report["networks"]))
