"""Offline structural tests for modules 4-5; no network or LLM calls."""
import json
from pathlib import Path

from cr_contracts import iter_errors

from app.planner.catalogue import load_components
from app.planner.dependencies import plan_dependencies
from app.planner.topology import attach_environment_plan

FIXTURE = Path(__file__).with_name("fixtures") / "offline_scenario.json"
DEMO_ROLES_FIXTURE = Path(__file__).with_name("fixtures") / "demo_roles.json"


def fixture_ir():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_catalogue_has_role_keywords_ports_and_closed_attacker_toolbox():
    components = load_components()
    by_id = {component["id"]: component for component in components}

    assert all("role_keywords" in component and "default_ports" in component for component in components)
    for component_id in ("oss-nginx", "oss-httpd"):
        assert {"web", "http", "web application", "web server"} <= set(by_id[component_id]["role_keywords"])
        assert by_id[component_id]["default_ports"] == [{"port": 80, "protocol": "tcp"}]
    assert {"database", "db", "sql"} <= set(by_id["oss-postgres"]["role_keywords"])
    assert by_id["oss-postgres"]["default_ports"] == [{"port": 5432, "protocol": "tcp"}]
    assert by_id["oss-attacker"]["image"] == "alpine:3.22"
    assert by_id["oss-attacker"]["default_ports"] == []


def test_dependencies_map_supported_services_and_report_unmet_items():
    result = plan_dependencies(fixture_ir())

    assert iter_errors("scenario-ir", result) == []
    assert len(result["services"]) == 3
    assert all(service.get("catalogue_component") for service in result["services"])
    assert any(service.get("version") == "1.24" and service.get("cve") == ["CVE-2024-12345"]
               for service in result["services"])
    assert any(service.get("name") == "IIS" and service.get("is_substitute") is True
               for service in result["services"])
    assert any(item.get("status") == "substitute_chosen" and "not a full recreation" in item.get("resolution", "")
               for item in result["missing_items"])
    assert any("Microsoft SQL Server" in item.get("field", "") and item.get("status") == "open"
               for item in result["missing_items"])


def test_topology_validates_and_does_not_promote_temporal_or_unconfirmed_edges():
    result = attach_environment_plan(plan_dependencies(fixture_ir()))
    plan = result["environment_plan"]

    assert iter_errors("environment-plan", plan) == []
    assert iter_errors("scenario-ir", result) == []
    assert all(host.get("networks") for host in plan["hosts"])
    assert next(network for network in plan["networks"] if network["id"] == "scenario-internal")["internal"] is True
    assert plan["access_rules"][0] == {"from": "*", "to": "*", "action": "deny"}
    assert any(connection.get("port") == 8080 for connection in plan["connections"])
    assert not any(connection.get("from_host") == "web_1" and connection.get("to_host") == "win_1"
                   for connection in plan["connections"])


def test_confirmed_dependency_can_add_only_its_destination_service_path():
    ir = fixture_ir()
    ir["relations"][1]["confirmed"] = True
    plan = attach_environment_plan(plan_dependencies(ir))["environment_plan"]

    assert any(connection.get("from_host") == "web_1" and connection.get("to_host") == "win_1"
               and connection.get("port") == 80 and "r-unconfirmed-dependency" in connection.get("reason", "")
               for connection in plan["connections"])


def test_missing_software_version_is_recorded_explicitly():
    ir = fixture_ir()
    del ir["target_context"]["hosts"][0]["services"][0]["version"]
    result = plan_dependencies(ir)

    # Inventory feature: nginx resolves to a catalogue component with a pinned version, so the
    # missing version is RECORDED (disclosed) but NOT raised as a blocking question to the user —
    # the catalogue version is used and the basis is disclosed as assumed.
    version_items = [item for item in result["missing_items"]
                     if item.get("category") == "version" and "nginx" in str(item.get("field", "")).lower()]
    assert version_items, "the missing nginx version must still be recorded explicitly"
    # Catalogue-resolvable: never block the user with a question, and disclose the version used.
    assert all(item.get("question") is None for item in version_items), \
        "a catalogue-resolvable version must not block with a user question"
    assert any("1.31.8" in str(item.get("reason", "")) for item in version_items), \
        "the disclosure must state the catalogue version used"


def test_user_service_is_mapped_without_losing_its_source_or_host_link():
    ir = fixture_ir()
    ir["services"] = [{"id": "user-nginx", "name": "nginx", "version": "1.24",
                       "source": "user", "epistemic_status": "supported"}]
    ir["hosts"] = [{"id": "web_1", "role": "victim-web", "service_refs": ["user-nginx"],
                    "source": "user", "epistemic_status": "supported"}]

    result = plan_dependencies(ir)

    nginx_services = [service for service in result["services"] if service["name"].casefold() == "nginx"]
    assert len(nginx_services) == 1
    assert nginx_services[0]["id"] == "user-nginx"
    assert nginx_services[0]["catalogue_component"] == "oss-nginx"
    assert nginx_services[0]["source"] == "user"
    assert "user-nginx" in next(host for host in result["hosts"] if host["id"] == "web_1")["service_refs"]


def test_demo_role_substitutes_are_honest_and_topology_is_segmented():
    ir = json.loads(DEMO_ROLES_FIXTURE.read_text(encoding="utf-8"))
    dependencies = plan_dependencies(ir)

    assert iter_errors("scenario-ir", dependencies) == []
    assert dependencies["actions"][0]["target_host_ref"] == "web"
    assert dependencies["actions"][1]["target_host_ref"] == "db"
    assert dependencies["actions"][0]["target_host_ref_source"] == "program"
    assert dependencies["actions"][0]["target_host_ref_epistemic_status"] == "inferred"
    assert len(dependencies["services"]) == 2
    assert all(service["is_substitute"] is True for service in dependencies["services"])
    assert {service["host_ref"] for service in dependencies["services"]} == {"web", "db"}
    assert all("version" not in service for service in dependencies["services"])
    assert all(item["category"] == "software" and item["severity"] == "major"
               and item["status"] == "substitute_chosen" and item.get("resolution")
               for item in dependencies["missing_items"])

    result = attach_environment_plan(dependencies)
    plan = result["environment_plan"]
    assert iter_errors("environment-plan", plan) == []
    assert iter_errors("scenario-ir", result) == []
    networks = {network["id"]: network for network in plan["networks"]}
    assert networks["scenario-internal"]["internal"] is True
    assert networks["external"]["internal"] is False
    hosts = {host["id"]: host for host in plan["hosts"]}
    assert "external" in hosts["web"]["networks"]
    assert "external" not in hosts["db"]["networks"]
    assert hosts["web"]["image_hint"] == "oss-nginx"
    assert hosts["db"]["image_hint"] == "oss-postgres"
    attacker = next(host for host in plan["hosts"] if host["role"] == "attacker")
    assert attacker["image_hint"] == "oss-attacker" and "external" in attacker["networks"]
    assert "scenario-internal" not in attacker["networks"]
    assert any(connection["from_host"] == "attacker" and connection["to_host"] == "web"
               and connection["port"] == 80
               for connection in plan["connections"])
    assert not any(connection["from_host"] == "attacker" and connection["to_host"] == "db"
                   for connection in plan["connections"])
    assert any(connection["from_host"] == "web" and connection["to_host"] == "db"
               and connection["port"] == 5432 for connection in plan["connections"])
    assert any(rule.get("from") == "*" and rule.get("to") == "*" and rule.get("action") == "deny"
               for rule in plan["access_rules"])
    assert any(rule.get("from") == "web" and rule.get("to") == "db"
               and rule.get("port") == 5432 and rule.get("action") == "allow"
               for rule in plan["access_rules"])

    ir["relations"][0]["confirmed"] = False
    unconfirmed = attach_environment_plan(plan_dependencies(ir))["environment_plan"]
    assert not any(connection["from_host"] == "web" and connection["to_host"] == "db"
                   for connection in unconfirmed["connections"])
