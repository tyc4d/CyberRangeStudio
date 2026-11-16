"""Offline tests for the inventory data layer and the resolve() contract (docs/inventory/DESIGN.md)."""
from app.planner.catalogue import load_components, match_software
from app.planner.inventory import (cve_index, components_for_cve, inventory_entries, inventory_summary,
                                   resolve)

CONTRACT_KEYS = {"tier", "component_id", "is_substitute", "version_basis", "reproduces_cve", "substitute_of",
                 "reason", "needs_question"}


def _check_shape(result):
    assert CONTRACT_KEYS <= set(result) <= CONTRACT_KEYS | {"question"}
    assert result["tier"] in {"have", "obtainable", "unavailable"}
    assert result["version_basis"] in {"stated", "assumed", "substituted", "user_supplied"}
    assert ("question" in result) is result["needs_question"]
    if result["is_substitute"]:
        assert result["substitute_of"] and result["version_basis"] == "substituted"
    return result


def test_every_entry_carries_inventory_fields():
    for component in load_components():
        assert component["tier"] in {"have", "obtainable", "unavailable"}, component["id"]
        assert isinstance(component["reproduces_cve"], list), component["id"]
        assert set(component["substitute_for"]) == {"products", "cves", "techniques"}, component["id"]
        assert {"source", "pullable", "est_cost_usd"} <= set(component["obtainability"]), component["id"]
        if component["tier"] == "obtainable":
            assert component["obtainability"]["est_cost_usd"] <= 50, component["id"]
        if component["tier"] == "unavailable":
            assert component["obtainability"]["pullable"] is False, component["id"]
        # Vulnerable images reproduce exactly the CVEs they are documented for.
        if component.get("vulnerable"):
            assert component["reproduces_cve"] == component["cves"], component["id"]


def test_cve_index_maps_only_deployable_reproducers():
    assert cve_index()["CVE-2021-44228"] == ("vuln-log4shell-solr",)
    assert cve_index()["CVE-2017-5638"] == ("vuln-struts2-s2-045",)
    assert [c["id"] for c in components_for_cve("cve-2021-44228")] == ["vuln-log4shell-solr"]


def test_same_product_have_with_matching_version():
    result = _check_shape(resolve("nginx", "1.31.8"))
    assert result["tier"] == "have" and result["component_id"] == "oss-nginx"
    assert result["is_substitute"] is False and result["version_basis"] == "stated"
    assert result["needs_question"] is False

    user = _check_shape(resolve("NGINX", "1.31", user_supplied=True))
    assert user["component_id"] == "oss-nginx" and user["version_basis"] == "user_supplied"


def test_same_product_single_version_never_asks():
    unstated = _check_shape(resolve("Apache Tomcat"))
    assert unstated["component_id"] == "oss-tomcat" and unstated["version_basis"] == "assumed"
    assert unstated["needs_question"] is False

    other = _check_shape(resolve("nginx", "1.24"))
    assert other["component_id"] == "oss-nginx" and other["version_basis"] == "substituted"
    assert other["is_substitute"] is False and other["needs_question"] is False


def test_same_product_with_its_cve():
    result = _check_shape(resolve("Apache Struts", "2.5.10", ["CVE-2017-5638"]))
    assert result["component_id"] == "vuln-struts2-s2-045" and result["is_substitute"] is False
    assert result["reproduces_cve"] == ["CVE-2017-5638"] and result["version_basis"] == "substituted"
    assert result["needs_question"] is False


def test_cve_maps_to_flagged_substitute_without_version_question():
    # scn_6ad6ad85538c: VMware Horizon exploited through Log4Shell.
    result = _check_shape(resolve("VMware Horizon", None, ["CVE-2021-44228"], "T1190"))
    assert result["tier"] == "have" and result["component_id"] == "vuln-log4shell-solr"
    assert result["is_substitute"] is True and result["version_basis"] == "substituted"
    assert result["reproduces_cve"] == ["CVE-2021-44228"] and result["substitute_of"] == "VMware Horizon"
    assert result["needs_question"] is False
    assert "never the original" in result["reason"]

    for name, cves in (("Log4j", ["CVE-2021-44228"]), ("Log4Shell", None), ("CVE-2021-44228", None)):
        sub = _check_shape(resolve(name, None, cves))
        assert sub["component_id"] == "vuln-log4shell-solr" and sub["is_substitute"] is True, name
        assert sub["needs_question"] is False, name


def test_unavailable_without_substitute_is_moot_not_a_question():
    for name, version in (("VMware Horizon", None), ("VMware Horizon", "8.3"), ("Active Directory", None),
                          ("Log4j", None), ("Totally Unknown Product", "1.0")):
        result = _check_shape(resolve(name, version))
        assert result["tier"] == "unavailable" and result["component_id"] is None, name
        assert result["is_substitute"] is False and result["needs_question"] is False, name
        assert "not reproducible" in result["reason"], name


def test_unknown_cve_with_unavailable_product_stays_unreproducible():
    result = _check_shape(resolve("VMware Horizon", None, ["CVE-2099-0001"]))
    assert result["tier"] == "unavailable" and result["needs_question"] is False
    assert "CVE-2099-0001" in result["reason"]


def test_role_substitute_by_name_is_flagged():
    result = _check_shape(resolve("IIS"))
    assert result["component_id"] == "oss-nginx" and result["is_substitute"] is True
    assert result["substitute_of"] == "IIS" and result["needs_question"] is False


def test_technique_only_substitute_needs_a_unique_stand_in():
    # T1190 has two possible stand-ins (Struts, Solr): nothing is chosen silently.
    result = _check_shape(resolve("Citrix ADC", None, None, "T1190"))
    assert result["tier"] == "unavailable" and result["component_id"] is None
    assert "several possible stand-ins" in result["reason"]


def test_genuine_version_question_for_several_deployable_releases():
    result = _check_shape(resolve("Windows Server"))
    assert result["needs_question"] is True and result["component_id"] is None
    assert result["tier"] == "obtainable"
    question = result["question"]
    assert question["field"] == "version for Windows Server"
    assert question["suggestions"] == ["Windows Server 2016 Evaluation", "Windows Server 2019 Evaluation",
                                       "Windows Server 2022 Evaluation"]

    # A stated release that is not deployable still leaves a real choice to make.
    unmatched = _check_shape(resolve("Windows Server", "2025"))
    assert unmatched["needs_question"] is True and len(unmatched["question"]["suggestions"]) == 3


def test_os_base_resolution():
    stated = _check_shape(resolve("Windows Server", "2019"))
    assert stated["component_id"] == "os-windows-server-2019-eval" and stated["tier"] == "obtainable"
    assert stated["version_basis"] == "stated" and stated["needs_question"] is False

    named = _check_shape(resolve("Microsoft Windows Server 2022"))
    assert named["component_id"] == "os-windows-server-2022-eval" and named["needs_question"] is False

    default = _check_shape(resolve("Ubuntu"))
    assert default["component_id"] == "os-ubuntu-24.04" and default["version_basis"] == "assumed"
    assert default["needs_question"] is False
    assert _check_shape(resolve("ubuntu", "22.04"))["component_id"] == "os-ubuntu-22.04"

    legacy = _check_shape(resolve("Windows Server", "2008 R2"))
    assert legacy["tier"] == "unavailable" and legacy["component_id"] is None
    assert legacy["needs_question"] is False


def test_os_images_are_invisible_to_the_service_planner():
    os_ids = {c["id"] for c in load_components() if c.get("kind") == "os_base"}
    assert os_ids
    for name in ("Ubuntu", "Windows Server 2019", "Debian 12", "Windows 11"):
        component, _ = match_software(name)
        assert component is None or component["id"] not in os_ids, name


def test_inventory_summary_is_compact_and_grounded():
    summary = inventory_summary()
    assert "CVE-2021-44228 -> vuln-log4shell-solr" in summary
    assert "- have:" in summary and "- obtainable:" in summary and "- unavailable:" in summary
    assert "VMware Horizon" in summary
    assert len(summary) < 3000
    assert {entry["tier"] for entry in inventory_entries()} == {"have", "obtainable", "unavailable"}
