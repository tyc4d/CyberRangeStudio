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


class StrutsAliasNormalization(unittest.TestCase):
    def test_component_suffix_and_action_alias_resolve_to_the_original_service(self):
        planned = plan_dependencies(base_ir(
            actions=[action("a1", "exploited Apache Struts on the portal", "h1", attack_technique="T1190")],
            hosts=[{"id": "h1", "role": "portal server", "epistemic_status": "supported", "source": "llm"}],
            services=[{"id": "s1", "name": "Apache Struts component", "host_ref": "h1",
                       "epistemic_status": "supported", "source": "llm"}]))
        self.assertEqual([service["id"] for service in planned["services"]], ["s1"])
        service = planned["services"][0]
        self.assertEqual(service["name"], "Apache Struts component")  # retain the source wording
        self.assertEqual(service["catalogue_component"], "vuln-struts2-s2-045")
        self.assertFalse(service.get("no_component", False))
        self.assertNotIn("version", service)  # no source version is manufactured
        self.assertEqual(service["version_basis"], "assumed")
        self.assertEqual(next(host for host in planned["hosts"] if host["id"] == "h1")["service_refs"], ["s1"])

        host = next(host for host in build_environment_plan(planned)["hosts"] if host["id"] == "h1")
        self.assertEqual(host["image_hint"], "vuln-struts2-s2-045")
        self.assertEqual(host["services"], [{"name": "Apache Struts component", "port": 8080, "protocol": "tcp"}])

    def test_literal_cve_indicator_without_product_evidence_stays_unmapped_and_asks(self):
        planned = plan_dependencies(base_ir(
            actions=[action("a1", "exploited a vulnerable web service", "h1", attack_technique="T1190")],
            hosts=[{"id": "h1", "role": "portal server", "epistemic_status": "supported", "source": "llm"}],
            services=[{"id": "s1", "name": "Apache Struts component", "host_ref": "h1",
                       "epistemic_status": "supported", "source": "llm"}],
            indicators=[{"id": "indicator-1", "type": "cve", "value": "CVE-2017-5638",
                         "epistemic_status": "supported", "source": "program", "evidence_refs": ["e1"]}] ))
        service = next(item for item in planned["services"] if item["id"] == "s1")
        self.assertFalse(service.get("cve"))
        self.assertNotIn("version", service)
        questions = [item for item in planned["missing_items"] if "CVE-2017-5638" in item.get("field", "")]
        self.assertEqual(len(questions), 1)
        self.assertIn("affected software", questions[0]["field"])

class InventoryOverrides(unittest.TestCase):
    def test_cve_substitute_is_only_a_recommendation_until_user_confirms(self):
        source_service = {"id": "s1", "name": "VMware Horizon", "host_ref": "h1",
                          "cve": ["CVE-2021-44228"], "epistemic_status": "supported", "source": "llm"}
        ir = base_ir(
            actions=[action("a1", "Exploit the Horizon portal", "h1")],
            hosts=[{"id": "h1", "role": "application server", "epistemic_status": "supported", "source": "llm"}],
            services=[source_service],
        )
        unconfirmed = plan_dependencies(ir)
        service = next(item for item in unconfirmed["services"] if item["id"] == "s1")
        self.assertNotIn("catalogue_component", service)
        self.assertTrue(service["not_reproducible"])
        self.assertEqual(service["cve"], ["CVE-2021-44228"])
        self.assertEqual(service["reproduces_cve"], [])
        self.assertIn("User confirmation is required", service["not_reproducible_reason"])

        ir["services"][0]["inventory_override"] = {"action": "accept", "at": "2026-11-16T00:00:00+00:00"}
        confirmed = plan_dependencies(ir)
        service = next(item for item in confirmed["services"] if item["id"] == "s1")
        self.assertEqual(service["catalogue_component"], "vuln-log4shell-solr")
        self.assertTrue(service["is_substitute"])
        self.assertEqual(service["cve"], ["CVE-2021-44228"])
        self.assertEqual(service["reproduces_cve"], ["CVE-2021-44228"])

    def test_service_override_survives_dependency_replanning_without_rewriting_source_cve(self):
        ir = base_ir(
            hosts=[{"id": "h1", "role": "web server", "epistemic_status": "supported", "source": "llm"}],
            services=[{"id": "s1", "name": "Apache HTTP Server", "host_ref": "h1",
                       "cve": ["CVE-2024-12345"], "epistemic_status": "supported", "source": "llm",
                       "inventory_override": {"action": "replace", "component_id": "vuln-struts2-s2-045",
                                               "at": "2026-11-16T00:00:00+00:00"}}],
        )
        planned = plan_dependencies(ir)
        service = next(item for item in planned["services"] if item["id"] == "s1")
        self.assertEqual(service["catalogue_component"], "vuln-struts2-s2-045")
        self.assertTrue(service["is_substitute"])
        self.assertEqual(service["substitute_of"], "Apache HTTP Server")
        self.assertEqual(service["inventory_override"]["action"], "replace")
        self.assertEqual(service["cve"], ["CVE-2024-12345"])
        self.assertEqual(service["reproduces_cve"], [])

        again = plan_dependencies(planned)
        replanned = next(item for item in again["services"] if item["id"] == "s1")
        self.assertEqual(replanned["catalogue_component"], "vuln-struts2-s2-045")
        self.assertEqual(replanned["cve"], ["CVE-2024-12345"])
        self.assertEqual(replanned["reproduces_cve"], [])

    def test_generated_program_service_override_survives_replanning_and_clear_restores_auto(self):
        ir = base_ir(
            actions=[action("a1", "Exploit Apache HTTP Server on the portal", "h1",
                            attack_technique="T1190")],
            hosts=[{"id": "h1", "role": "web server", "epistemic_status": "supported", "source": "llm"}],
            indicators=[{"id": "i1", "type": "cve", "value": "CVE-2024-12345"}],
            missing_items=[{"id": "m1", "field": "affected software for CVE-2024-12345",
                            "category": "software", "reason": "The CVE is not linked to a source service.",
                            "status": "open"}],
        )
        generated = plan_dependencies(ir)
        service = generated["services"][0]
        self.assertEqual(service["source"], "program")
        self.assertEqual(service["cve"], [])
        self.assertEqual(generated["indicators"], ir["indicators"])
        self.assertEqual(next(item for item in generated["missing_items"] if item["id"] == "m1")["status"], "open")
        service["inventory_override"] = {
            "action": "replace", "component_id": "vuln-struts2-s2-045",
            "at": "2026-11-16T00:00:00+00:00",
        }

        selected = plan_dependencies(generated)
        chosen = selected["services"][0]
        self.assertEqual(chosen["source"], "program")
        self.assertEqual(chosen["catalogue_component"], "vuln-struts2-s2-045")
        self.assertTrue(chosen["is_substitute"])
        self.assertEqual(chosen["cve"], [])
        self.assertEqual(chosen["reproduces_cve"], [])
        self.assertEqual(selected["indicators"], ir["indicators"])
        self.assertEqual(next(item for item in selected["missing_items"] if item["id"] == "m1")["status"], "open")

        again = plan_dependencies(selected)
        self.assertEqual(again["services"][0]["catalogue_component"], "vuln-struts2-s2-045")
        self.assertEqual(again["services"][0]["cve"], [])

        again["services"][0].pop("inventory_override", None)
        cleared = plan_dependencies(again)
        restored = cleared["services"][0]
        self.assertEqual(restored["catalogue_component"], "oss-httpd")
        self.assertFalse(restored["is_substitute"])
        self.assertNotIn("substitute_of", restored)
        self.assertEqual(restored["cve"], [])
        self.assertEqual(cleared["indicators"], ir["indicators"])
        self.assertEqual(next(item for item in cleared["missing_items"] if item["id"] == "m1")["status"], "open")


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
        matched = " ".join(str(item.get("matched_text") or "") for item in planned["services"])
        self.assertIn("Log4Shell", matched)
        self.assertIn("domain controller", matched)
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
        self.assertEqual((nginx["host_ref"], nginx["lab_version"], nginx["port"], nginx["source"]), ("victim-web", "1.31.8", 80, "user"))
        self.assertEqual((postgres["host_ref"], postgres["lab_version"], postgres["port"]), ("db", "16.16", 5432))
        # USER_SUPPLIED: never a source-stated version, never "supported by the source".
        for service in (nginx, postgres):
            self.assertNotIn("version", service)
            self.assertEqual((service["epistemic_status"], service["provenance_class"], service["version_basis"]),
                             ("absent", "USER_SUPPLIED", "user_supplied"))
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


class DifferentProductsAreNotAliases(unittest.TestCase):
    """Reviewer P1: 'Apache Struts' must never be planned as the Apache HTTP Server."""

    def plan(self, service_name, action_name):
        return plan_dependencies(base_ir(
            actions=[action("a1", action_name, "h1", attack_technique="T1190")],
            hosts=[{"id": "h1", "role": "portal server", "epistemic_status": "supported", "source": "llm"}],
            services=[{"id": "s1", "name": service_name, "host_ref": "h1", "epistemic_status": "supported", "source": "llm"}]))

    def test_vendor_word_inside_another_product_name_does_not_match(self):
        from app.planner.catalogue import component_by_id
        for name in ("Apache Struts Web Framework", "Apache Struts", "Apache Tomcat", "Apache ActiveMQ", "Apache Kafka"):
            planned = self.plan(name, f"exploited a vulnerability in {name} on the portal")
            self.assertEqual([s["id"] for s in planned["services"]], ["s1"], name)
            service = planned["services"][0]
            self.assertNotIn("oss-httpd", str(planned["services"]), name)
            component = component_by_id(service.get("catalogue_component"))
            if component is None:
                self.assertTrue(service.get("no_component"), name)
            else:
                # A match is only legitimate through that component's own alias for this very name.
                self.assertIn(name.casefold(), {alias.casefold() for alias in component["aliases"]}, name)
            host = next(h for h in build_environment_plan(planned)["hosts"] if h["id"] == "h1")
            self.assertNotEqual(host.get("image_hint"), "oss-httpd", name)

    def test_products_the_catalogue_does_not_have_stay_unmatched(self):
        for name in ("Apache ActiveMQ", "Apache Kafka", "Apache Nonexistent Product"):
            planned = self.plan(name, f"exploited a vulnerability in {name} on the portal")
            self.assertTrue(planned["services"][0].get("no_component"), name)
            host = next(h for h in build_environment_plan(planned)["hosts"] if h["id"] == "h1")
            self.assertNotEqual(host.get("component_mode"), "real", name)

    def test_the_product_itself_still_matches_with_generic_words_around_it(self):
        for name in ("Apache HTTP Server", "Apache web server", "apache", "nginx server"):
            planned = self.plan(name, "requested a page")
            self.assertIn(planned["services"][0].get("catalogue_component"), {"oss-httpd", "oss-nginx"}, name)


class SupplementAnswersBindToTheAskedHost(unittest.TestCase):
    """Reviewer P3: software named in an answer about host X runs on host X."""

    def test_service_from_an_answer_is_bound_to_the_host_the_question_was_about(self):
        ir = base_ir(
            actions=[action("a1", "Exploit the web application", "h1", attack_technique="T1190")],
            hosts=[{"id": "h1", "role": "portal", "epistemic_status": "supported", "source": "llm"},
                   {"id": "h2", "role": "records store", "epistemic_status": "supported", "source": "llm"}],
            missing_items=[{"id": "missing-hosts-h2-os", "field": "f", "category": "host", "reason": "r",
                            "status": "user_supplied", "target": {"collection": "hosts", "id": "h2", "field": "os"}}],
            supplements=[{"id": "supplement-1", "source": "user", "targets_missing_item": "missing-hosts-h2-os",
                          "text": "Linux running PostgreSQL 16.16"}])
        planned = plan_dependencies(ir)
        postgres = next(s for s in planned["services"] if s.get("catalogue_component") == "oss-postgres")
        self.assertEqual((postgres["host_ref"], postgres["lab_version"], postgres["source"]), ("h2", "16.16", "user"))
        self.assertNotIn("version", postgres)
        self.assertIn(postgres["id"], next(h for h in planned["hosts"] if h["id"] == "h2")["service_refs"])


class NothingToBuild(unittest.TestCase):
    def test_no_identified_software_is_a_blocker_not_an_empty_plan(self):
        ir = base_ir(actions=[action("a1", "gained access to part of the network", "h1")],
                     hosts=[{"id": "h1", "role": "part of our network", "epistemic_status": "inferred", "source": "llm"}],
                     services=[{"id": "service-unspecified", "name": "Unspecified service (absent)",
                                "epistemic_status": "absent", "source": "program"}])
        planned = plan_dependencies(ir)
        blocker = next(item for item in planned["missing_items"] if item["id"] == "planner_dep_no-target-software")
        self.assertEqual((blocker["severity"], blocker["status"]), ("blocker", "open"))
        self.assertEqual(planned["fidelity"], "not_reproducible")


class ProtocolPorts(unittest.TestCase):
    def test_protocol_label_is_matched_as_a_word(self):
        from app.planner.topology import _port_for
        self.assertEqual(_port_for({"name": "RDP"}), (3389, "tcp"))
        self.assertEqual(_port_for({"name": "Remote Desktop (RDP) service"}), (3389, "tcp"))
        self.assertIsNone(_port_for({"name": "WordPress"}))
        self.assertEqual(_port_for({"name": "HTTPS listener"}), (443, "tcp"))


class StatedPortsForGenericServices(unittest.TestCase):
    """Built-in demo regression: a generically named service still gets the port the source states."""

    def ir(self):
        quotes = ["the attacker first sent HTTP requests to `victim-web` over TCP/80 to identify the web application",
                  "the attacker used `victim-web` to connect to `db` over TCP/5432 and collect records"]
        return base_ir(
            actions=[action("a1", "sent HTTP requests", "h1", evidence_refs=["e1"]),
                     action("a4", "collect records", "h2", source_host_ref="h1", evidence_refs=["e2"])],
            hosts=[{"id": "h1", "name": "victim-web", "role": "internet-facing web application host",
                    "epistemic_status": "supported", "source": "llm"},
                   {"id": "h2", "name": "db", "role": "internal database host", "epistemic_status": "supported", "source": "llm"}],
            services=[{"id": "s1", "name": "web service", "host_ref": "h1", "epistemic_status": "supported", "source": "llm"},
                      {"id": "s2", "name": "database service", "host_ref": "h2", "epistemic_status": "supported", "source": "llm"}],
            evidence=[{"id": f"e{i}", "quote": quote, "locator": {"kind": "paragraph", "ref": str(i)}, "quote_verified": True}
                      for i, quote in enumerate(quotes, start=1)])

    def test_ports_hosts_and_paths_follow_the_source(self):
        planned = plan_dependencies(self.ir())
        services = {service["id"]: service for service in planned["services"]}
        self.assertEqual((services["s1"]["port"], services["s2"]["port"]), (80, 5432))
        self.assertEqual(services["s1"]["field_sources"], {"port": "source_quote"})
        self.assertEqual({host["id"]: host["service_refs"] for host in planned["hosts"]}, {"h1": ["s1"], "h2": ["s2"]})
        plan = build_environment_plan(planned)
        self.assertEqual({(c["from_host"], c["to_host"], c["port"]) for c in plan["connections"]},
                         {("attacker", "h1", 80), ("h1", "h2", 5432)})
        self.assertEqual([(b["from_host"], b["to_host"], b["port"]) for b in plan["verify_blocked"]], [("attacker", "h2", 5432)])

    def test_function_only_services_get_labelled_substitutes_and_a_deployable_plan(self):
        from app.iac.generator import inspect_plan, inventory_plan_blockers
        planned = plan_dependencies(self.ir())
        services = {service["id"]: service for service in planned["services"]}
        self.assertEqual({sid: (s["catalogue_component"], s["is_substitute"], s["source"]) for sid, s in services.items()},
                         {"s1": ("oss-nginx", True, "llm"), "s2": ("oss-postgres", True, "llm")})
        notices = [item for item in planned["missing_items"] if item["id"].startswith("planner_dep_role-substitute")]
        self.assertEqual([item["status"] for item in notices], ["substitute_chosen", "substitute_chosen"])
        plan = build_environment_plan(planned)
        planned["environment_plan"] = plan
        self.assertEqual({h["id"]: h.get("image_hint") for h in plan["hosts"]},
                         {"h1": "oss-nginx", "h2": "oss-postgres", "attacker": "oss-attacker"})
        self.assertEqual(inventory_plan_blockers(planned), [])
        wrong_image = copy.deepcopy(planned)
        next(service for service in wrong_image["services"] if service["id"] == "s1")["catalogue_component"] = "vuln-log4shell-solr"
        next(host for host in wrong_image["environment_plan"]["hosts"] if host["id"] == "h1")["image_hint"] = "vuln-log4shell-solr"
        self.assertTrue(any(item["code"] == "inventory_confirmation_required"
                            for item in inventory_plan_blockers(wrong_image)))
        _, report = inspect_plan(plan, "scn_t")
        self.assertEqual(report.get("errors"), [], report.get("errors"))

    def test_function_substitute_hosts_are_reported_as_substitutes(self):
        from app.iac.generator import inspect_plan
        plan = build_environment_plan(plan_dependencies(self.ir()))
        self.assertEqual({h["id"]: h.get("substitute_for") for h in plan["hosts"]},
                         {"h1": "web service", "h2": "database service", "attacker": None})
        _, report = inspect_plan(plan, "scn_t")
        self.assertEqual({c["host_id"]: c["substitute"] for c in report["components"]},
                         {"h1": True, "h2": True, "attacker": False})

    def test_a_named_product_is_never_swapped_for_a_generic_stand_in(self):
        ir = self.ir()
        ir["services"][0]["name"] = "Confluence web application"
        planned = plan_dependencies(ir)
        service = next(s for s in planned["services"] if s["id"] == "s1")
        self.assertTrue(service.get("no_component"))
        self.assertNotIn("catalogue_component", service)

    def test_unverified_quote_or_two_ports_for_one_host_assign_nothing(self):
        ir = self.ir()
        ir["evidence"][0]["quote_verified"] = False
        ir["evidence"][1]["quote"] += "; `db` also listened on TCP/3306"
        planned = plan_dependencies(ir)
        self.assertFalse(any("port" in service for service in planned["services"]))


class OsAnswerIsNotAService(unittest.TestCase):
    """Reviewer N1: answering a host's OS must not add a 'Windows Server:445' service to it."""

    def ir(self, text="Windows Server 2019", field="os"):
        base = StatedPortsForGenericServices().ir()
        base["hosts"][0]["os"] = text
        base["missing_items"] = [{"id": "missing-hosts-h1-os", "field": "f", "category": "host", "reason": "r",
                                  "status": "user_supplied", "resolution_source": "user",
                                  "target": {"collection": "hosts", "id": "h1", "field": field},
                                  "applied_to": {"collection": "hosts", "id": "h1", "field": field}}]
        base["supplements"] = [{"id": "supplement-1", "source": "user", "text": text,
                                "targets_missing_item": "missing-hosts-h1-os"}]
        return base

    def test_plan_is_unchanged_by_an_os_answer(self):
        from app.iac.generator import inspect_plan
        before = build_environment_plan(plan_dependencies(StatedPortsForGenericServices().ir()))
        planned = plan_dependencies(self.ir())
        self.assertEqual(sorted(service["id"] for service in planned["services"]), ["s1", "s2"])
        self.assertFalse(any("windows" in str(service.get("catalogue_component")) for service in planned["services"]))
        after = build_environment_plan(planned)
        self.assertEqual(after["connections"], before["connections"])
        self.assertEqual([h.get("image_hint") for h in after["hosts"]], [h.get("image_hint") for h in before["hosts"]])
        self.assertEqual(inspect_plan(after, "scn_t")[1].get("errors"), [])
        self.assertEqual(next(h for h in planned["hosts"] if h["id"] == "h1")["os"], "Windows Server 2019")

    def test_application_named_in_an_os_answer_is_still_planned(self):
        planned = plan_dependencies(self.ir("Windows Server 2019 running Redis"))
        components = {service.get("catalogue_component") for service in planned["services"]}
        self.assertIn("oss-redis", components)
        self.assertFalse(any("windows" in str(component) for component in components))


class DeployedVersionBasis(unittest.TestCase):
    """Reviewer N2: a catalogue release the source never stated must be visibly an assumption."""

    def plan(self, version=None):
        from app.planner.catalogue import component_by_id
        self.component = component_by_id("vuln-struts2-s2-045")
        service = {"id": "s1", "name": "Apache Struts", "host_ref": "h1", "epistemic_status": "supported", "source": "llm"}
        if version:
            service["version"] = version
        planned = plan_dependencies(base_ir(
            actions=[action("a1", "exploited Apache Struts on the portal", "h1", attack_technique="T1190")],
            hosts=[{"id": "h1", "role": "portal server", "epistemic_status": "supported", "source": "llm"}],
            services=[service]))
        return planned, next(s for s in planned["services"] if s["id"] == "s1")

    def test_unstated_version_is_marked_assumed_everywhere(self):
        planned, service = self.plan()
        self.assertEqual(service["catalogue_component"], "vuln-struts2-s2-045")
        self.assertEqual((service["version_basis"], service["deployed_version"]), ("assumed", self.component["version"]))
        self.assertNotIn("version", service)  # the IR still does not claim a version the source lacks
        notice = next(i for i in planned["missing_items"] if i["id"].startswith("planner_dep_deployed-version"))
        self.assertEqual((notice["status"], notice["category"]), ("substitute_chosen", "version"))
        host = next(h for h in build_environment_plan(planned)["hosts"] if h["id"] == "h1")
        self.assertEqual((host["version_basis"], host["deployed_version"]), ("assumed", self.component["version"]))

    def test_different_stated_version_is_marked_substituted_and_same_version_is_stated(self):
        _, other = self.plan("2.5.10")
        self.assertEqual((other["version_basis"], other["version"]), ("substituted", "2.5.10"))
        planned, same = self.plan(self.plan()[1]["deployed_version"])
        self.assertEqual(same["version_basis"], "stated")
        self.assertFalse(any(i["id"].startswith("planner_dep_deployed-version") for i in planned["missing_items"]))
        self.assertNotIn("version_basis", next(h for h in build_environment_plan(planned)["hosts"] if h["id"] == "h1"))


class UserChosenSubstitute(unittest.TestCase):
    """frontend-eng: choosing a substitute for an unsupported service must leave a deployable plan."""

    def first(self):
        return plan_dependencies(base_ir(
            actions=[action("a1", "SQL injection against Progress MOVEit Transfer", "h1", attack_technique="T1190")],
            hosts=[{"id": "h1", "role": "internet-facing file transfer server", "epistemic_status": "supported", "source": "llm"}],
            services=[{"id": "s1", "name": "Progress MOVEit Transfer", "host_ref": "h1", "port": 443,
                       "epistemic_status": "supported", "source": "llm"}]))

    def answer(self, planned, text, status="substitute_chosen"):
        question = next(i for i in planned["missing_items"] if i["id"].startswith("planner_dep_software"))
        self.assertEqual(question["service_ref"], "s1")
        question.update({"status": status, "resolution": text, "resolution_source": "user"})
        planned.setdefault("supplements", []).append(
            {"id": "supplement-9", "source": "user", "text": text, "targets_missing_item": question["id"]})
        return plan_dependencies(planned)

    def test_choice_is_applied_to_the_original_service_on_its_host(self):
        from app.iac.generator import inspect_plan
        planned = self.answer(self.first(), "用 nginx 當替代")
        self.assertEqual([service["id"] for service in planned["services"]], ["s1"])
        service = planned["services"][0]
        self.assertEqual((service["catalogue_component"], service["is_substitute"], service["substitute_basis"], service["host_ref"]),
                         ("oss-nginx", True, "user_chosen", "h1"))
        self.assertEqual((service["name"], service["source"]), ("Progress MOVEit Transfer", "llm"))
        self.assertNotIn("no_component", service)
        self.assertEqual(next(h for h in planned["hosts"] if h["id"] == "h1")["service_refs"], ["s1"])
        self.assertTrue(any(i["status"] == "substitute_chosen" and "MOVEit" in i["field"] for i in planned["missing_items"]))
        plan = build_environment_plan(planned)
        host = next(h for h in plan["hosts"] if h["id"] == "h1")
        self.assertEqual(host["image_hint"], "oss-nginx")
        self.assertEqual([(c["from_host"], c["to_host"]) for c in plan["connections"]], [("attacker", "h1")])
        # Planning again keeps the choice and adds nothing.
        self.assertEqual([s["id"] for s in plan_dependencies(planned)["services"]], ["s1"])

    def test_substitute_is_labelled_at_host_level_and_through_iac(self):
        """Reviewer M1(a): the host a stand-in runs on must be reported as a substitute."""
        from app.iac.generator import inspect_plan
        plan = build_environment_plan(self.answer(self.first(), "用 nginx 當替代"))
        host = next(h for h in plan["hosts"] if h["id"] == "h1")
        self.assertEqual((host["substitute_for"], host["substitute_basis"]), ("Progress MOVEit Transfer", "user_chosen"))
        _, report = inspect_plan(plan, "scn_t")
        self.assertEqual(report.get("errors"), [], report.get("errors"))
        component = next(c for c in report["components"] if c["host_id"] == "h1")
        self.assertIs(component["substitute"], True)
        self.assertEqual(component["substitute_for"], "Progress MOVEit Transfer")
        self.assertIn("Progress MOVEit Transfer", component["fidelity_difference"])
        attacker = next(c for c in report["components"] if c["host_id"] == "attacker")
        self.assertIs(attacker["substitute"], False)

    def test_port_the_substitute_cannot_serve_is_replaced_and_said_so(self):
        """Reviewer M1(b): MOVEit on 443 replaced by nginx must not yield an undeployable plan."""
        planned = self.answer(self.first(), "用 nginx 當替代")
        self.assertEqual(planned["services"][0]["port"], 443)  # the IR keeps what the source stated
        plan = build_environment_plan(planned)
        host = next(h for h in plan["hosts"] if h["id"] == "h1")
        self.assertEqual(host["services"], [{"name": "Progress MOVEit Transfer", "port": 80, "protocol": "tcp",
                                             "stated_port": 443, "port_basis": "substitute_default"}])
        self.assertEqual([(c["from_host"], c["to_host"], c["port"]) for c in plan["connections"]], [("attacker", "h1", 80)])
        self.assertTrue(any("443" in note and "substitution" in note for note in plan["notes"]))

    def test_real_component_on_a_port_it_does_not_serve_is_explained_not_silently_moved(self):
        plan = build_environment_plan(plan_dependencies(base_ir(
            actions=[action("a1", "request the nginx site", "h1", attack_technique="T1190")],
            hosts=[{"id": "h1", "role": "web server", "epistemic_status": "supported", "source": "llm"}],
            services=[{"id": "s1", "name": "nginx", "host_ref": "h1", "port": 8443, "epistemic_status": "supported", "source": "llm"}])))
        host = next(h for h in plan["hosts"] if h["id"] == "h1")
        self.assertEqual(host["services"], [{"name": "nginx", "port": 8443, "protocol": "tcp"}])
        self.assertNotIn("substitute_for", host)
        self.assertTrue(any("8443" in note and "IaC generation will refuse" in note for note in plan["notes"]))

    def test_answer_naming_no_or_several_products_changes_nothing(self):
        for text in ("先不部署", "nginx 或 Apache HTTP Server 都可以"):
            planned = self.answer(self.first(), text)
            self.assertEqual([service["id"] for service in planned["services"]], ["s1"], text)
            self.assertTrue(planned["services"][0].get("no_component"), text)


class TrafficDescriptionsAreNotSoftware(unittest.TestCase):
    """QA round 2 (Equifax): 'encrypted communication channels' must not become a dependency."""

    def test_classifier_separates_descriptions_from_named_services(self):
        from app.cti.missing import is_communication_description as check
        for name in ("existing encrypted communication channels", "standard encrypted web protocols",
                     "encrypted channels", "normal network traffic", "Encrypted Communication Channel",
                     "HTTPS", "HTTPS protocol", "HTTPS listener"):
            self.assertTrue(check(name), name)
        for name in ("RDP", "SMB protocol service", "Apache Struts", "web service", "database service",
                     "OpenVPN tunnel", "Remote Desktop Protocol", "File Transfer Protocol server", ""):
            self.assertFalse(check(name), name)

    def test_planner_raises_no_question_and_no_substitute_for_a_traffic_description(self):
        planned = plan_dependencies(base_ir(
            actions=[action("a1", "exploited Apache Struts on the portal", "h1", attack_technique="T1190")],
            hosts=[{"id": "h1", "role": "portal server", "epistemic_status": "supported", "source": "llm"}],
            services=[{"id": "s1", "name": "Apache Struts", "host_ref": "h1", "epistemic_status": "supported", "source": "llm"},
                      {"id": "s2", "name": "existing encrypted communication channels", "host_ref": "h1",
                       "epistemic_status": "supported", "source": "llm"}]))
        self.assertFalse(any("communication channels" in item["field"] for item in planned["missing_items"]))
        s2 = next(service for service in planned["services"] if service["id"] == "s2")
        self.assertNotIn("catalogue_component", s2)
        host = next(h for h in build_environment_plan(planned)["hosts"] if h["id"] == "h1")
        self.assertEqual([entry["name"] for entry in host["services"]], ["Apache Struts"])


class HostEvidenceTopologyBoundaries(unittest.TestCase):
    def test_internal_fqdn_evidence_overrides_a_public_role_for_that_exact_hostname(self):
        quote = "The internal host client.corp.example ran an endpoint agent."
        plan = build_environment_plan(base_ir(
            actions=[action("a1", "Exploit nginx", "h1", attack_technique="T1190")],
            hosts=[{"id": "h1", "name": "client.corp.example", "role": "public web server",
                    "evidence_refs": ["ev1"]}],
            services=[{"id": "s1", "name": "nginx", "host_ref": "h1", "port": 80}],
            evidence=[{"id": "ev1", "quote": quote, "quote_verified": True}],
        ))
        host = next(host for host in plan["hosts"] if host["id"] == "h1")
        self.assertIn("scenario-internal", host["networks"])
        self.assertNotIn("external", host["networks"])
        self.assertFalse(any(connection.get("to_host") == "h1" for connection in plan["connections"]))

    def test_internal_fqdn_prefix_does_not_match_a_longer_hostname(self):
        quote = "The internal host client.corp.example.evil ran an endpoint agent."
        plan = build_environment_plan(base_ir(
            actions=[action("a1", "Exploit nginx", "h1", attack_technique="T1190")],
            hosts=[{"id": "h1", "name": "client.corp.example", "role": "public web server",
                    "evidence_refs": ["ev1"]}],
            services=[{"id": "s1", "name": "nginx", "host_ref": "h1", "port": 80}],
            evidence=[{"id": "ev1", "quote": quote, "quote_verified": True}],
        ))
        host = next(host for host in plan["hosts"] if host["id"] == "h1")
        self.assertIn("external", host["networks"])
        self.assertTrue(any(connection.get("from_host") == "attacker" and connection.get("to_host") == "h1"
                            and connection.get("port") == 80 for connection in plan["connections"]))

    def test_outbound_destination_is_attributed_only_to_the_host_in_its_clause(self):
        quote = ("The internal database db was accessed through the public web host edge. "
                 "The public web host edge connected to external domain update.example over HTTPS "
                 "and downloaded payload.exe.")
        plan = build_environment_plan(base_ir(
            hosts=[{"id": "db", "name": "db", "role": "database", "evidence_refs": ["ev1"]},
                   {"id": "edge", "name": "edge", "role": "public web host", "evidence_refs": ["ev1"]}],
            services=[{"id": "s1", "name": "nginx", "host_ref": "edge", "port": 80}],
            evidence=[{"id": "ev1", "quote": quote, "quote_verified": True}],
        ))
        db = next(host for host in plan["hosts"] if host["id"] == "db")
        edge = next(host for host in plan["hosts"] if host["id"] == "edge")
        self.assertNotIn("external", db["networks"])
        self.assertIn("external", edge["networks"])
        notes = [note for note in plan["notes"] if "outbound HTTPS" in note]
        self.assertEqual(len(notes), 1)
        self.assertIn("from edge to update.example", notes[0])
        self.assertNotIn("payload.exe", notes[0])
        self.assertEqual(plan["connections"], [])

    def test_outbound_clause_naming_two_hosts_is_not_attributed_to_either(self):
        quote = ("The internal database db received a report that the public web host edge "
                 "connected to external domain update.example over HTTPS.")
        plan = build_environment_plan(base_ir(
            hosts=[{"id": "db", "name": "db", "role": "internal database", "evidence_refs": ["ev1"]},
                   {"id": "edge", "name": "edge", "role": "public web host", "evidence_refs": ["ev1"]}],
            evidence=[{"id": "ev1", "quote": quote, "quote_verified": True}],
        ))
        self.assertFalse(any("outbound HTTPS" in note for note in plan["notes"]))


class CVEAffectedProductIsNotInstalled(unittest.TestCase):
    def test_coordinated_affected_product_does_not_become_a_deployed_service(self):
        statements = (
            "Apache Struts runs the portal, and CVE-2024-12345 affects Apache HTTP Server.",
            "Apache Struts runs the portal, while CVE-2024-12345 affects Apache HTTP Server.",
            "CVE-2024-12345 affects Apache HTTP Server, while Apache Struts runs the portal.",
            "CVE-2024-12345 affects Apache HTTP Server;Apache Struts runs the portal.",
            "CVE-2024-12345 影響 Apache HTTP Server。Apache Struts runs the portal.",
        )
        for text in statements:
            with self.subTest(text=text):
                planned = plan_dependencies(base_ir(
                    actions=[action("a1", text, "h1", attack_technique="T1190")],
                    hosts=[{"id": "h1", "role": "portal server", "epistemic_status": "supported", "source": "llm"}],
                ))
                names = [service["name"] for service in planned["services"]]
                self.assertTrue(any("Struts" in name for name in names), names)
                self.assertFalse(any("HTTP Server" in name for name in names), names)
                struts = next(service for service in planned["services"] if "Struts" in service["name"])
                self.assertNotIn("CVE-2024-12345", struts.get("cve", []))
                self.assertTrue(any(item.get("field") == "affected software for CVE-2024-12345"
                                    for item in planned["missing_items"]))

    def test_semicolon_affected_product_list_does_not_create_services(self):
        statements = (
            "CVE-2024-12345 affects Apache Struts;Apache HTTP Server.",
            "CVE-2024-12345 影響 Apache Struts；Apache HTTP Server。",
        )
        for text in statements:
            with self.subTest(text=text):
                planned = plan_dependencies(base_ir(
                    actions=[action("a1", text, "h1", attack_technique="T1190")],
                    hosts=[{"id": "h1", "role": "target", "epistemic_status": "supported", "source": "llm"}],
                ))
                names = [service["name"] for service in planned["services"]]
                self.assertEqual(names, [])
                self.assertTrue(any(item.get("field") == "affected software for CVE-2024-12345"
                                    for item in planned["missing_items"]))

    def test_long_semicolon_affected_product_list_does_not_create_late_services(self):
        text = ("CVE-2024-12345 affects Apache Struts;Apache Tomcat;Oracle Database;"
                "Microsoft Exchange Server;Apache HTTP Server;MariaDB.")
        planned = plan_dependencies(base_ir(
            actions=[action("a1", text, "h1", attack_technique="T1190")],
            hosts=[{"id": "h1", "role": "target", "epistemic_status": "supported", "source": "llm"}],
        ))
        names = [service["name"] for service in planned["services"]]
        self.assertFalse(any("MariaDB" in name or "HTTP Server" in name for name in names), names)
        self.assertTrue(any(item.get("field") == "affected software for CVE-2024-12345"
                            for item in planned["missing_items"]))

    def test_semicolon_after_affected_product_keeps_explicit_deployment_evidence(self):
        text = "CVE-2024-12345 affects Apache HTTP Server;Apache Struts runs the portal."
        planned = plan_dependencies(base_ir(
            actions=[action("a1", text, "h1", attack_technique="T1190")],
            hosts=[{"id": "h1", "role": "target", "epistemic_status": "supported", "source": "llm"}],
        ))
        names = [service["name"] for service in planned["services"]]
        self.assertTrue(any("Struts" in name for name in names), names)
        self.assertFalse(any("HTTP Server" in name for name in names), names)
        self.assertTrue(any(item.get("field") == "affected software for CVE-2024-12345"
                            for item in planned["missing_items"]))

    def test_semicolon_affected_product_with_explicit_installation_is_deployed(self):
        text = "CVE-2024-12345 affects Apache Struts;Apache HTTP Server runs the portal."
        planned = plan_dependencies(base_ir(
            actions=[action("a1", text, "h1", attack_technique="T1190")],
            hosts=[{"id": "h1", "role": "target", "epistemic_status": "supported", "source": "llm"}],
        ))
        names = [service["name"] for service in planned["services"]]
        self.assertTrue(any("HTTP Server" in name for name in names), names)
        self.assertFalse(any("Struts" in name for name in names), names)

    def test_semicolon_affected_product_with_exploit_evidence_is_deployed(self):
        text = "CVE-2024-12345 affects Apache HTTP Server; Apache Struts was exploited."
        planned = plan_dependencies(base_ir(
            actions=[action("a1", text, "h1", attack_technique="T1190")],
            hosts=[{"id": "h1", "role": "target", "epistemic_status": "supported", "source": "llm"}],
        ))
        names = [service["name"] for service in planned["services"]]
        self.assertTrue(any("Struts" in name for name in names), names)
        self.assertFalse(any("HTTP Server" in name for name in names), names)

    def test_published_exploit_code_is_not_deployment_evidence(self):
        text = "CVE-2024-12345 affects Apache HTTP Server; Apache Struts exploit code was published."
        planned = plan_dependencies(base_ir(
            actions=[action("a1", text, "h1", attack_technique="T1190")],
            hosts=[{"id": "h1", "role": "target", "epistemic_status": "supported", "source": "llm"}],
        ))
        self.assertEqual(planned["services"], [])
        self.assertTrue(any(item.get("field") == "affected software for CVE-2024-12345"
                            for item in planned["missing_items"]))

    def test_but_boundary_does_not_turn_affected_http_server_into_deployed_service(self):
        text = "CVE-2024-12345 affects Apache HTTP Server, but Apache Struts runs the portal."
        planned = plan_dependencies(base_ir(
            actions=[action("a1", text, "h1", attack_technique="T1190")],
            hosts=[{"id": "h1", "role": "portal server", "epistemic_status": "supported", "source": "llm"}],
        ))
        names = [service["name"] for service in planned["services"]]
        self.assertTrue(any("Struts" in name for name in names), names)
        self.assertFalse(any("HTTP Server" in name for name in names), names)
        struts = next(service for service in planned["services"] if "Struts" in service["name"])
        self.assertNotIn("CVE-2024-12345", struts.get("cve", []))
        self.assertTrue(any(item.get("field") == "affected software for CVE-2024-12345"
                            for item in planned["missing_items"]))

    def test_negated_installation_does_not_deploy_affected_http_server(self):
        text = ("CVE-2024-12345 affects Apache HTTP Server, which is not installed, "
                "but Apache Struts runs the portal.")
        planned = plan_dependencies(base_ir(
            actions=[action("a1", text, "h1", attack_technique="T1190")],
            hosts=[{"id": "h1", "role": "portal server", "epistemic_status": "supported", "source": "llm"}],
        ))
        names = [service["name"] for service in planned["services"]]
        self.assertTrue(any("Struts" in name for name in names), names)
        self.assertFalse(any("HTTP Server" in name for name in names), names)
        self.assertTrue(any(item.get("field") == "affected software for CVE-2024-12345"
                            for item in planned["missing_items"]))

    def test_not_yet_installed_does_not_deploy_affected_http_server(self):
        text = ("CVE-2024-12345 affects Apache HTTP Server, which is not yet installed, "
                "but Apache Struts runs the portal.")
        planned = plan_dependencies(base_ir(
            actions=[action("a1", text, "h1", attack_technique="T1190")],
            hosts=[{"id": "h1", "role": "portal server", "epistemic_status": "supported", "source": "llm"}],
        ))
        names = [service["name"] for service in planned["services"]]
        self.assertTrue(any("Struts" in name for name in names), names)
        self.assertFalse(any("HTTP Server" in name for name in names), names)
        self.assertTrue(any(item.get("field") == "affected software for CVE-2024-12345"
                            for item in planned["missing_items"]))

    def test_common_contracted_and_previously_negated_installation_is_not_deployed(self):
        for negation in ("isnt installed", "is not installed", "arent installed", "wasnt installed",
                         "werent installed", "hasnt installed", "havent installed",
                         "is not previously installed"):
            with self.subTest(negation=negation):
                text = (f"CVE-2024-12345 affects Apache HTTP Server, which {negation}, "
                        "but Apache Struts runs the portal.")
                planned = plan_dependencies(base_ir(
                    actions=[action("a1", text, "h1", attack_technique="T1190")],
                    hosts=[{"id": "h1", "role": "portal server", "epistemic_status": "supported", "source": "llm"}],
                ))
                names = [service["name"] for service in planned["services"]]
                self.assertTrue(any("Struts" in name for name in names), names)
                self.assertFalse(any("HTTP Server" in name for name in names), names)
                self.assertTrue(any(item.get("field") == "affected software for CVE-2024-12345"
                                    for item in planned["missing_items"]))

    def test_explicitly_installed_running_affected_service_remains_a_candidate(self):
        text = ("CVE-2024-12345 affects Apache HTTP Server, which is installed and running, "
                "but Apache Struts also runs the portal.")
        planned = plan_dependencies(base_ir(
            actions=[action("a1", text, "h1", attack_technique="T1190")],
            hosts=[{"id": "h1", "role": "portal server", "epistemic_status": "supported", "source": "llm"}],
        ))
        names = [service["name"] for service in planned["services"]]
        self.assertTrue(any("HTTP Server" in name for name in names), names)

    def test_neither_installed_nor_running_affected_service_is_not_deployed(self):
        text = ("CVE-2024-12345 affects Apache HTTP Server, which is neither installed nor running, "
                "but Apache Struts runs the portal.")
        planned = plan_dependencies(base_ir(
            actions=[action("a1", text, "h1", attack_technique="T1190")],
            hosts=[{"id": "h1", "role": "portal server", "epistemic_status": "supported", "source": "llm"}],
        ))
        names = [service["name"] for service in planned["services"]]
        self.assertTrue(any("Struts" in name for name in names), names)
        self.assertFalse(any("HTTP Server" in name for name in names), names)
        self.assertTrue(any(item.get("field") == "affected software for CVE-2024-12345"
                            for item in planned["missing_items"]))

    def test_neither_installed_nor_available_affected_service_is_not_deployed(self):
        text = ("CVE-2024-12345 affects Apache HTTP Server, which is neither installed nor available, "
                "but Apache Struts runs the portal.")
        planned = plan_dependencies(base_ir(
            actions=[action("a1", text, "h1", attack_technique="T1190")],
            hosts=[{"id": "h1", "role": "portal server", "epistemic_status": "supported", "source": "llm"}],
        ))
        names = [service["name"] for service in planned["services"]]
        self.assertTrue(any("Struts" in name for name in names), names)
        self.assertFalse(any("HTTP Server" in name for name in names), names)
        self.assertTrue(any(item.get("field") == "affected software for CVE-2024-12345"
                            for item in planned["missing_items"]))

    def test_unrelated_neither_clause_does_not_negate_explicit_installation(self):
        text = ("CVE-2024-12345 affects Apache HTTP Server, which is installed, "
                "neither vendor nor security team documenting the version, "
                "but Apache Struts runs the portal.")
        planned = plan_dependencies(base_ir(
            actions=[action("a1", text, "h1", attack_technique="T1190")],
            hosts=[{"id": "h1", "role": "portal server", "epistemic_status": "supported", "source": "llm"}],
        ))
        names = [service["name"] for service in planned["services"]]
        self.assertTrue(any("HTTP Server" in name for name in names), names)

class OneHostOneComponent(unittest.TestCase):
    """QA round 2: Struts:8080 plus an nginx stand-in on the same host must not reach IaC as deployable."""

    def planned(self):
        return plan_dependencies(base_ir(
            actions=[action("a1", "exploited Apache Struts on the portal", "h1", attack_technique="T1190")],
            hosts=[{"id": "h1", "role": "portal server", "epistemic_status": "supported", "source": "llm"}],
            services=[{"id": "s2", "name": "front proxy", "host_ref": "h1", "catalogue_component": "oss-nginx",
                       "is_substitute": True, "substitute_basis": "user_chosen", "epistemic_status": "supported", "source": "llm"},
                      {"id": "s1", "name": "Apache Struts", "host_ref": "h1", "epistemic_status": "supported", "source": "llm"}]))

    def test_dependencies_report_the_conflict_as_a_blocker(self):
        planned = self.planned()
        conflict = next(i for i in planned["missing_items"] if i["id"] == "planner_dep_host-component-conflict-h1")
        self.assertEqual((conflict["severity"], conflict["status"]), ("blocker", "open"))
        services = {service["id"]: service for service in planned["services"]}
        self.assertEqual(services["s2"]["placement"], "conflict")   # the stand-in yields to the named software
        self.assertNotIn("placement", services["s1"])

    def test_plan_deploys_one_component_declares_only_its_ports_and_passes_iac(self):
        from app.iac.generator import inspect_plan
        plan = build_environment_plan(self.planned())
        host = next(h for h in plan["hosts"] if h["id"] == "h1")
        self.assertEqual(host["image_hint"], "vuln-struts2-s2-045")
        self.assertEqual([entry["name"] for entry in host["services"]], ["Apache Struts"])
        self.assertEqual([entry["name"] for entry in host["unplaced_services"]], ["front proxy"])
        self.assertNotIn("substitute_for", host)
        self.assertTrue(any("not deployed there" in note for note in plan["notes"]))
        self.assertEqual(inspect_plan(plan, "scn_t")[1].get("errors"), [])

    def test_conflict_clears_when_the_extra_service_moves_to_another_host(self):
        ir = self.planned()
        ir["hosts"].append({"id": "h2", "role": "proxy host", "epistemic_status": "supported", "source": "user"})
        next(service for service in ir["services"] if service["id"] == "s2")["host_ref"] = "h2"
        again = plan_dependencies(ir)
        self.assertFalse(any("conflict" in item["id"] for item in again["missing_items"]))
        self.assertFalse(any(service.get("placement") for service in again["services"]))


class UserTextIsNeverSourceFact(unittest.TestCase):
    """QA round 2 (AR2-01, QA-I-R2-02, UXR2-02): caveats and lab choices in free text stay the user's."""

    def ir(self, text):
        return base_ir(
            actions=[action("a1", "exploited Apache Struts on the portal", "h1", attack_technique="T1190")],
            hosts=[{"id": "h1", "role": "portal server", "epistemic_status": "supported", "source": "llm"},
                   {"id": "h2", "role": "records store", "epistemic_status": "supported", "source": "llm"}],
            services=[{"id": "s1", "name": "Apache Struts", "host_ref": "h1", "epistemic_status": "supported", "source": "llm"}],
            supplements=[{"id": "supplement-1", "source": "user", "text": text}])

    def test_limitation_statement_creates_no_service(self):
        for text in ("Linux/Solr 只能作入口漏洞教學替代，不等於 Horizon、Windows Defender、RDP 或 AD 完整重現",
                     "Solr is only a teaching stand-in; it is not VMware Horizon and does not reproduce Active Directory.",
                     "不能重現加密通道；postgres 不代表原本的資料庫"):
            planned = plan_dependencies(self.ir(text))
            self.assertEqual([service["id"] for service in planned["services"]], ["s1"], text)

    def test_product_named_without_a_host_creates_no_orphan_service(self):
        planned = plan_dependencies(self.ir("the lab will also have redis somewhere"))
        self.assertEqual([service["id"] for service in planned["services"]], ["s1"])
        self.assertFalse(any(not service.get("host_ref") for service in planned["services"]))

    def test_lab_release_named_by_the_user_is_not_recorded_as_the_source_version(self):
        planned = plan_dependencies(self.ir(
            "struts2 2.3.30 與 postgres 是本機隔離教學替代元件；不能重現加密通道；OS 與原始版本仍未知。"))
        struts = next(service for service in planned["services"] if service["id"] == "s1")
        self.assertNotIn("version", struts)
        self.assertEqual((struts["lab_version"], struts["field_sources"]["lab_version"], struts["version_basis"]),
                         ("2.3.30", "user", "user_supplied"))
        self.assertEqual((struts["source"], struts["epistemic_status"]), ("llm", "supported"))
        self.assertEqual([service["id"] for service in planned["services"]], ["s1"])  # no host-less postgres

    def test_answered_planner_question_survives_as_history(self):
        first = plan_dependencies(base_ir(
            actions=[action("a1", "SQL injection against Progress MOVEit Transfer", "h1", attack_technique="T1190")],
            hosts=[{"id": "h1", "role": "internet-facing file transfer server", "epistemic_status": "supported", "source": "llm"}],
            services=[{"id": "s1", "name": "Progress MOVEit Transfer", "host_ref": "h1", "epistemic_status": "supported", "source": "llm"}]))
        question = next(i for i in first["missing_items"] if i["id"].startswith("planner_dep_software"))
        question.update({"status": "substitute_chosen", "resolution": "nginx", "resolution_source": "user"})
        first["supplements"] = [{"id": "supplement-9", "source": "user", "text": "nginx", "targets_missing_item": question["id"]}]
        second = plan_dependencies(first)
        kept = next(i for i in second["missing_items"] if i["id"] == question["id"])
        self.assertEqual((kept["status"], kept["resolution"], kept["superseded"]), ("substitute_chosen", "nginx", True))
        third = plan_dependencies(second)
        self.assertEqual(len([i for i in third["missing_items"] if i["id"] == question["id"]]), 1)


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
