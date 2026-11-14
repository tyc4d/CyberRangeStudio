"""Scenario IR <-> dependencies <-> environment plan must describe the same hosts and services."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api"))

from app.planner.dependencies import plan_dependencies  # noqa: E402
from app.planner.topology import build_environment_plan  # noqa: E402
from cr_contracts import iter_errors  # noqa: E402


def base_ir(**overrides):
    ir = {
        "schema_version": "1.0", "id": "scn_t", "name": "t",
        "provenance": {"input_kind": "text", "input_sha256": "0"},
        "actions": [], "relations": [], "hosts": [], "services": [], "missing_items": [], "evidence": [],
    }
    ir.update(overrides)
    return ir


def action(aid, name, host="unknown", **extra):
    return {"id": aid, "name": name, "target_host_ref": host, "epistemic_status": "supported", "source": "llm",
            "evidence_refs": [], **extra}


class HostIdentity(unittest.TestCase):
    def test_placeholder_host_and_unknown_refs_do_not_multiply_hosts(self):
        ir = base_ir(
            actions=[action("a1", "Exploit CVE-2023-34362 in Progress MOVEit Transfer")],
            hosts=[{"id": "host-target", "role": "target", "epistemic_status": "insufficient", "source": "program"}],
            services=[{"id": "service-unspecified", "name": "Unspecified service (absent)",
                       "epistemic_status": "absent", "source": "program"}],
        )
        planned = plan_dependencies(ir)
        self.assertEqual([host["id"] for host in planned["hosts"]], ["host-target"])
        self.assertEqual(planned["actions"][0]["target_host_ref"], "unknown")
        plan = build_environment_plan(planned)
        self.assertEqual(sorted(host["id"] for host in plan["hosts"]), ["attacker", "host_target"])

    def test_hyphenated_ids_keep_every_reference_resolvable(self):
        ir = base_ir(
            actions=[action("a1", "Exploit the nginx web server", "victim-web")],
            hosts=[{"id": "victim-web", "role": "exposed web server", "epistemic_status": "supported", "source": "llm"}],
        )
        planned = plan_dependencies(ir)
        host_ids = {host["id"] for host in planned["hosts"]}
        self.assertEqual(host_ids, {"victim-web"})
        for service in planned["services"]:
            if "host_ref" in service:
                self.assertIn(service["host_ref"], host_ids)
        for host in planned["hosts"]:
            for ref in host.get("service_refs", []):
                self.assertIn(ref, {service["id"] for service in planned["services"]})
        self.assertEqual(iter_errors("scenario-ir", planned), [])


class RecordedServices(unittest.TestCase):
    def ir(self):
        return base_ir(
            actions=[action("a1", "SQL injection against the file transfer application", "h1", attack_technique="T1190")],
            hosts=[{"id": "h1", "role": "file transfer server", "epistemic_status": "supported", "source": "llm"}],
            services=[{"id": "s1", "name": "Progress MOVEit Transfer", "host_ref": "h1", "cve": ["CVE-2023-34362"],
                       "epistemic_status": "supported", "source": "llm", "evidence_refs": []}],
        )

    def test_analysis_service_without_catalogue_component_is_reported_not_ignored(self):
        planned = plan_dependencies(self.ir())
        service = next(item for item in planned["services"] if item["id"] == "s1")
        self.assertTrue(service["no_component"])
        self.assertEqual(service["source"], "llm")
        fields = [item["field"] for item in planned["missing_items"] if item["id"].startswith("planner_dep_")]
        self.assertTrue(any("Progress MOVEit Transfer" in field for field in fields), fields)
        # The CVE is attached to a known service, so no orphan "affected software for CVE" question.
        self.assertFalse(any("affected software" in field for field in fields), fields)

    def test_analysis_service_with_catalogue_match_keeps_its_identity(self):
        ir = self.ir()
        ir["services"][0].update({"name": "nginx", "cve": [], "port": 8080})
        planned = plan_dependencies(ir)
        self.assertEqual([item["id"] for item in planned["services"]], ["s1"])
        service = planned["services"][0]
        self.assertEqual((service["catalogue_component"], service["source"], service["port"]), ("oss-nginx", "llm", 8080))
        plan = build_environment_plan(planned)
        h1 = next(host for host in plan["hosts"] if host["id"] == "h1")
        self.assertEqual(h1["services"], [{"name": "nginx", "port": 8080, "protocol": "tcp"}])

    def test_placeholder_service_is_dropped_once_real_services_exist(self):
        ir = self.ir()
        ir["services"].append({"id": "service-unspecified", "name": "Unspecified service (absent)",
                               "epistemic_status": "absent", "source": "program"})
        planned = plan_dependencies(ir)
        self.assertNotIn("service-unspecified", [item["id"] for item in planned["services"]])


class MentionNaming(unittest.TestCase):
    def test_vulnerability_nickname_and_role_are_not_used_as_software_names(self):
        ir = base_ir(
            actions=[action("a1", "Exploit Log4Shell on the server", "h1"),
                     action("a2", "Move laterally to the domain controller", "h2")],
            hosts=[{"id": "h1", "role": "application server", "epistemic_status": "supported", "source": "llm"},
                   {"id": "h2", "role": "directory host", "epistemic_status": "supported", "source": "llm"}],
        )
        planned = plan_dependencies(ir)
        names = {item["name"] for item in planned["services"]}
        self.assertNotIn("Log4Shell", names)
        self.assertNotIn("domain controller", names)
        matched = {item.get("matched_text") for item in planned["services"]}
        self.assertTrue({"Log4Shell", "domain controller"} <= matched)
        fields = " ".join(item["field"] for item in planned["missing_items"])
        self.assertNotIn("version for Log4Shell", fields)
        self.assertNotIn("version for domain controller", fields)


class UserDecisionsSurviveReplanning(unittest.TestCase):
    def test_resolved_planner_question_is_kept(self):
        ir = base_ir(
            actions=[action("a1", "Exploit the nginx web server", "h1")],
            hosts=[{"id": "h1", "role": "web server", "epistemic_status": "supported", "source": "llm"}],
        )
        first = plan_dependencies(ir)
        question = next(item for item in first["missing_items"] if item["id"].startswith("planner_dep_version"))
        question.update({"status": "accepted_unknown", "resolution": "Not stated; leave unknown.", "resolution_source": "user"})
        second = plan_dependencies(first)
        again = next(item for item in second["missing_items"] if item["id"] == question["id"])
        self.assertEqual((again["status"], again["resolution_source"]), ("accepted_unknown", "user"))
        self.assertEqual(len([i for i in second["missing_items"] if i["id"] == question["id"]]), 1)


class EntryPoint(unittest.TestCase):
    def hosts(self):
        return [{"id": "h1", "role": "application server", "epistemic_status": "supported", "source": "llm"},
                {"id": "h2", "role": "file server", "epistemic_status": "supported", "source": "llm"}]

    def services(self):
        return [{"id": "s1", "name": "nginx", "host_ref": "h1", "catalogue_component": "oss-nginx", "source": "llm"}]

    def test_initial_access_target_is_reachable_and_labelled_inferred(self):
        ir = base_ir(actions=[action("a1", "Exploit nginx", "h1", attack_technique="T1190"),
                              action("a2", "Copy files", "h2")], hosts=self.hosts(), services=self.services())
        plan = build_environment_plan(ir)
        hosts = {host["id"]: host for host in plan["hosts"]}
        self.assertIn("external", hosts["h1"]["networks"])
        self.assertEqual(hosts["h1"]["exposure_basis"], "inferred_entry_point")
        self.assertNotIn("external", hosts["h2"]["networks"])
        self.assertEqual([(c["from_host"], c["to_host"], c["port"]) for c in plan["connections"]], [("attacker", "h1", 80)])
        self.assertTrue(any("inferred entry point" in note for note in plan["notes"]))

    def test_stated_exposure_is_not_overridden_by_inference(self):
        hosts = self.hosts()
        hosts[1]["role"] = "internet-facing file server"
        ir = base_ir(actions=[action("a1", "Exploit nginx", "h1", attack_technique="T1190")], hosts=hosts,
                     services=self.services())
        hosts_out = {host["id"]: host for host in build_environment_plan(ir)["hosts"]}
        self.assertNotIn("external", hosts_out["h1"]["networks"])
        self.assertEqual(hosts_out["h2"]["exposure_basis"], "stated")

    def test_user_supplied_internal_placement_wins(self):
        hosts = self.hosts()
        hosts[0]["network_placement"] = "internal management segment"
        ir = base_ir(actions=[action("a1", "Exploit nginx", "h1", attack_technique="T1190")], hosts=hosts,
                     services=self.services())
        plan = build_environment_plan(ir)
        self.assertNotIn("external", next(h for h in plan["hosts"] if h["id"] == "h1")["networks"])
        self.assertEqual(plan["connections"], [])

    def test_temporal_order_alone_opens_no_host_to_host_path(self):
        ir = base_ir(actions=[action("a1", "Exploit nginx", "h1", attack_technique="T1190"), action("a2", "Copy files", "h2")],
                     relations=[{"id": "r1", "from_action": "a1", "to_action": "a2", "kind": "temporal",
                                 "epistemic_status": "supported", "source": "llm"}],
                     hosts=self.hosts(), services=self.services())
        plan = build_environment_plan(ir)
        self.assertFalse(any(c["from_host"] == "h1" for c in plan["connections"]))


class HostBindingFromText(unittest.TestCase):
    """Replays the admin QA case: software named in a step belongs to the host its clause names."""

    def ir(self, **extra):
        return base_ir(
            actions=[action("a1", "the attacker sends an HTTP GET request to NGINX on host `web` TCP/80", "h1"),
                     action("a3", "from `web`, the operator connects to PostgreSQL on `db` TCP/5432", "h1",
                            source_host_ref="h1")],
            hosts=[{"id": "h1", "name": "web", "role": "front end", "epistemic_status": "supported", "source": "llm"},
                   {"id": "h2", "name": "db", "role": "records store", "epistemic_status": "supported", "source": "llm"}],
            **extra)

    def test_product_is_placed_on_the_host_named_in_its_clause_not_the_step_host(self):
        planned = plan_dependencies(self.ir())
        placed = {service["catalogue_component"]: (service["host_ref"], service.get("port")) for service in planned["services"]}
        self.assertEqual(placed, {"oss-nginx": ("h1", 80), "oss-postgres": ("h2", 5432)})

    def test_stated_cross_host_step_opens_exactly_that_path(self):
        ir = self.ir()
        ir["actions"][1]["target_host_ref"] = "h2"
        plan = build_environment_plan(plan_dependencies(ir))
        paths = {(c["from_host"], c["to_host"], c["port"]) for c in plan["connections"]}
        self.assertEqual(paths, {("attacker", "h1", 80), ("h1", "h2", 5432)})
        self.assertEqual([(b["from_host"], b["to_host"], b["port"]) for b in plan["verify_blocked"]], [("attacker", "h2", 5432)])

    def test_inferred_step_does_not_open_a_cross_host_path(self):
        ir = self.ir()
        ir["actions"][1].update({"target_host_ref": "h2", "epistemic_status": "inferred"})
        plan = build_environment_plan(plan_dependencies(ir))
        self.assertNotIn(("h1", "h2", 5432), {(c["from_host"], c["to_host"], c["port"]) for c in plan["connections"]})

    def test_free_text_supplement_maps_services_to_hosts_as_user_statements(self):
        ir = base_ir(
            actions=[action("a1", "Exploit a publicly disclosed CVE in the web service", "victim-web", attack_technique="T1190")],
            hosts=[{"id": "victim-web", "role": "exposed web server", "epistemic_status": "supported", "source": "llm"},
                   {"id": "db", "role": "internal database host", "epistemic_status": "supported", "source": "llm"}],
            supplements=[{"id": "supplement-1", "source": "user", "text":
                          "map service svc-http-80 to host victim_web (victim-web), using catalogue component oss-nginx, "
                          "nginx 1.31.8 on TCP/80; map svc-db-5432 to host db using catalogue component oss-postgres, "
                          "PostgreSQL 16.16 on TCP/5432. Deny attacker to db."}])
        planned = plan_dependencies(ir)
        self.assertEqual({host["id"] for host in planned["hosts"]}, {"victim-web", "db"})
        by_component = {service["catalogue_component"]: service for service in planned["services"]}
        nginx, postgres = by_component["oss-nginx"], by_component["oss-postgres"]
        self.assertEqual((nginx["host_ref"], nginx["version"], nginx["port"], nginx["source"]), ("victim-web", "1.31.8", 80, "user"))
        self.assertEqual((postgres["host_ref"], postgres["version"], postgres["port"]), ("db", "16.16", 5432))
        self.assertEqual(nginx["supplement_ref"], "supplement-1")
        # Planning twice gives the same services: nothing stale, nothing duplicated.
        again = plan_dependencies(planned)
        self.assertEqual(sorted(s["id"] for s in again["services"]), sorted(s["id"] for s in planned["services"]))
        self.assertEqual({host["id"] for host in again["hosts"]}, {"victim-web", "db"})

    def test_version_stated_in_a_verified_host_quote_fills_the_recorded_service(self):
        ir = base_ir(
            actions=[action("a1", "Request the site", "h1")],
            hosts=[{"id": "h1", "name": "web", "role": "front end", "epistemic_status": "supported", "source": "llm",
                    "evidence_refs": ["e1"]}],
            services=[{"id": "s1", "name": "nginx", "host_ref": "h1", "epistemic_status": "supported", "source": "llm"}],
            evidence=[{"id": "e1", "quote": "The host `web` runs nginx version 1.31.8 on TCP/80.",
                       "locator": {"kind": "paragraph", "ref": "1"}, "quote_verified": True}],
            missing_items=[{"id": "missing-service-s1-version", "field": "nginx — 版本", "category": "version",
                            "reason": "r", "status": "open"}])
        planned = plan_dependencies(ir)
        service = planned["services"][0]
        self.assertEqual((service["id"], service["version"], service["port"]), ("s1", "1.31.8", 80))
        self.assertEqual(service["field_sources"], {"version": "source_quote", "port": "source_quote"})
        self.assertNotIn("missing-service-s1-version", [item["id"] for item in planned["missing_items"]])

    def test_stale_planner_service_is_not_carried_into_the_next_plan(self):
        ir = self.ir()
        first = plan_dependencies(ir)
        first["actions"][1]["name"] = "from `web`, the operator enumerates the internal network"
        second = plan_dependencies(first)
        self.assertEqual({service["catalogue_component"] for service in second["services"]}, {"oss-nginx"})


class UnsupportedComponents(unittest.TestCase):
    def test_undeployable_platform_is_not_presented_as_real_or_substitute(self):
        ir = base_ir(actions=[action("a1", "Exploit VMware Horizon", "h1", attack_technique="T1190")],
                     hosts=[{"id": "h1", "role": "VMware Horizon server", "epistemic_status": "supported", "source": "llm"}])
        plan = build_environment_plan(plan_dependencies(copy.deepcopy(ir)))
        h1 = next(host for host in plan["hosts"] if host["id"] == "h1")
        self.assertEqual(h1["runtime"], "external_platform")
        self.assertIs(h1["deployable"], False)
        self.assertNotIn("component_mode", h1)
        self.assertEqual(iter_errors("environment-plan", plan), [])


if __name__ == "__main__":
    unittest.main()
