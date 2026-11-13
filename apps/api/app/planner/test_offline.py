"""Offline structural tests for modules 4-5; no network or LLM calls."""
import json
from pathlib import Path

from cr_contracts import iter_errors

from app.planner.dependencies import plan_dependencies
from app.planner.topology import attach_environment_plan

FIXTURE = Path(__file__).with_name("fixtures") / "offline_scenario.json"


def fixture_ir():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_dependencies_map_supported_services_and_report_unmet_items():
    result = plan_dependencies(fixture_ir())

    assert iter_errors("scenario-ir", result) == []
    assert len(result["services"]) == 2
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
    assert all(network.get("internal") is True for network in plan["networks"])
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

    assert any(item.get("category") == "version" and item.get("field") == "version for nginx"
               for item in result["missing_items"])


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
