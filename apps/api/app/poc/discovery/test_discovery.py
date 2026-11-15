from __future__ import annotations

import unittest
from unittest.mock import Mock

from cr_contracts import iter_errors_shape

from app.poc.discovery.engine import DiscoveryEngine
from app.poc.discovery.ranking import rank_candidate, score_candidate
from app.poc.discovery.sources import MetadataClient, cve_ids


class RankingTests(unittest.TestCase):
    def candidate(self, **updates):
        return {"action_id": "a1", "cve": "CVE-2021-44228", "source": "github",
                "source_url": "https://github.com/example/log4shell-check", "ref": {"commit_sha": "a" * 40},
                "product": "Apache Log4j", "version_range": "2.0.0 through 2.14.1",
                "language": "python", "dependencies": [], "preconditions": [], "exec_method": "python",
                "license": "MIT", "trust": "medium", "last_updated": "2021-12-10T00:00:00Z", **updates}

    def test_compatible_version_and_product_score_high(self):
        result = rank_candidate(self.candidate(), {"product": "Apache Log4j", "version": "2.14.1", "cves": ["CVE-2021-44228"]})
        self.assertEqual(result["score_breakdown"]["version"], 1)
        self.assertGreater(result["compatibility_score"], .8)
        self.assertEqual(set(result["score_breakdown"]), {"version", "env", "code_available", "source_trust", "exec_cost"})

    def test_incompatible_version_is_heavily_penalized(self):
        scores = score_candidate(self.candidate(), {"product": "Apache Log4j", "version": "2.17.1", "cves": ["CVE-2021-44228"]})
        self.assertEqual(scores["version"], .05)

    def test_matching_cve_does_not_override_wrong_product(self):
        scores = score_candidate(self.candidate(), {"product": "Apache Struts", "version": "2.14.1", "cves": ["CVE-2021-44228"]})
        self.assertEqual(scores["version"], 0)

    def test_version_ranges_respect_numeric_order_and_boundaries(self):
        cases = [
            ("2.10.0", "before 2.15.0", 1),
            ("2.15.0", "before 2.15.0", .05),
            ("2.16.0", "before 2.15.0", .05),
            ("2.15", "prior to 2.15.0", .05),
            ("2.14.1", "versions prior to 2.15.0", 1),
            ("2.0.0", "2.0.0 through 2.14.1", 1),
            ("2.10.0", "2.0.0 through 2.14.1", 1),
            ("2.14.1", "2.0.0 through 2.14.1", 1),
            ("1.9.9", "2.0.0 through 2.14.1", .05),
            ("2.15.0", "2.0.0 through 2.14.1", .05),
            ("2.10.0", "2.0.0 to 2.14.1", 1),
            ("2.10.0", "2.0.0 – 2.14.1", 1),
            ("2.0.0", "2.14.1 through 2.0.0", .05),
            ("2.15.0", "up to 2.15.0", 1),
            ("2.15.1", "through 2.15.0", .05),
            ("2.15.0", "<2.15.0", .05),
            ("2.15.0", "<=2.15.0", 1),
            ("2.15.0", ">=2.15.0", 1),
            ("2.15.0", "after 2.15.0", .05),
            ("2.15.1", "after 2.15.0", 1),
            ("2.3.30", "2.3.x", 1),
            ("2.30.0", "2.3.x", .05),
            ("2.3", "2.3.0", 1),
            ("2.3.1", "2.3.0", .05),
            ("2.12.0", "before 2.3.0; 2.10.0 through 2.14.1", 1),
            ("2.15.0", "before 2.3.0; 2.10.0 through 2.14.1", .05),
        ]
        for target, version_range, expected in cases:
            with self.subTest(target=target, version_range=version_range):
                score = score_candidate(self.candidate(version_range=version_range),
                                        {"product": "Apache Log4j", "version": target})
                self.assertEqual(score["version"], expected)

    def test_unsupported_version_text_does_not_prove_compatibility(self):
        for target, version_range in [("2.15.0-rc1", "before 2.15.0"),
                                      ("2.15.0", "not 2.15.0"),
                                      ("2.15.0", ">=2.0.0, <2.15.0"),
                                      ("2.15.0", "unconfirmed")]:
            with self.subTest(target=target, version_range=version_range):
                score = score_candidate(self.candidate(version_range=version_range),
                                        {"product": "Apache Log4j", "version": target})
                self.assertLess(score["version"], .9)


class DiscoveryTests(unittest.TestCase):
    def linked_fixture(self):
        client = Mock()
        client.nvd_search.return_value = None
        client.exploitdb_search.return_value = []
        client.github_search.return_value = [{"source_url": "https://github.com/example/log4j-poc",
            "description": "Apache Log4j CVE-2021-44228 exploit versions before 2.15.0", "language": "Python"}]
        ir = {"services": [{"id": "svc1", "name": "Apache Log4j", "version": "2.10.0",
                             "cve": ["CVE-2021-44228"]},
                            {"id": "foreign", "name": "Unrelated service", "host_ref": "h2",
                             "cve": ["CVE-2099-0001"]}],
              "hosts": [{"id": "h1", "os": "Linux", "service_refs": ["svc1"]},
                        {"id": "h2", "service_refs": ["foreign"]}],
              "actions": [{"id": "a1", "target_host_ref": "h1", "name": "Exploit service"}]}
        return client, ir

    def test_target_host_resolves_services_using_either_ir_link(self):
        for link in ("service_refs", "host_ref", "both"):
            with self.subTest(link=link):
                client, ir = self.linked_fixture()
                if link != "service_refs":
                    ir["services"][0]["host_ref"] = "h1"
                if link == "host_ref":
                    ir["hosts"][0].pop("service_refs")
                manifest = DiscoveryEngine(client).discover("s", ir, "t")
                self.assertEqual(iter_errors_shape("PocManifest", manifest), [])
                self.assertEqual(len(manifest["items"]), 1)
                item = manifest["items"][0]
                self.assertEqual((item["action_id"], item["cve"]), ("a1", "CVE-2021-44228"))
                self.assertEqual(item["score_breakdown"]["version"], 1)
                client.nvd_search.assert_called_once_with("CVE-2021-44228")

    def test_multiple_host_services_keep_cves_and_versions_separate(self):
        client, ir = self.linked_fixture()
        ir["services"].append({"id": "svc2", "name": "Apache Log4j", "version": "2.15.0",
                               "cve": ["CVE-2021-45046"]})
        ir["hosts"][0]["service_refs"].append("svc2")
        client.github_search.side_effect = lambda query: [{
            "source_url": "https://github.com/example/" + query.split('"')[1],
            "description": "Apache Log4j " + query.split('"')[1] + " exploit before 2.15.0",
            "language": "Python"}]
        manifest = DiscoveryEngine(client).discover("s", ir, "t")
        self.assertEqual({item["cve"]: item["score_breakdown"]["version"] for item in manifest["items"]},
                         {"CVE-2021-44228": 1, "CVE-2021-45046": .05})
        self.assertEqual(client.nvd_search.call_count, 2)

    def test_explicit_service_ref_takes_precedence_over_host_services(self):
        client, ir = self.linked_fixture()
        ir["hosts"][0]["service_refs"].append("foreign")
        ir["actions"][0]["service_ref"] = "svc1"
        manifest = DiscoveryEngine(client).discover("s", ir, "t")
        self.assertEqual(len(manifest["items"]), 1)
        client.nvd_search.assert_called_once_with("CVE-2021-44228")

    def test_unresolved_references_do_not_search_unrelated_services(self):
        for updates in ({"target_host_ref": "missing"}, {"service_ref": "missing"}):
            with self.subTest(updates=updates):
                client, ir = self.linked_fixture()
                ir["actions"][0].update(updates)
                self.assertEqual(DiscoveryEngine(client).discover("s", ir, "t")["items"], [])
                client.github_search.assert_not_called()
                client.nvd_search.assert_not_called()

    def test_manifest_candidates_are_ranked_and_contract_valid(self):
        client = Mock()
        client.nvd_search.return_value = {"source_url": "https://nvd.nist.gov/vuln/detail/CVE-2021-44228",
            "references": [], "description": "Apache Log4j 2.0.0 through 2.14.1 remote code execution", "last_updated": "2021"}
        client.exploitdb_search.return_value = [{"source_url": "https://www.exploit-db.com/exploits/1", "ref": {"release": "1"},
            "product": "Apache Log4j CVE-2021-44228 exploit", "description": "Apache Log4j CVE-2021-44228 exploit",
            "language": "python", "last_updated": "2021"}]
        client.github_search.return_value = [{"source_url": "https://github.com/example/log4j-poc", "ref": {},
            "product": "log4j-poc", "description": "Apache Log4j CVE-2021-44228 exploit proof of concept",
            "language": "Python", "license": "MIT", "last_updated": "2021", "stars": 1}]
        ir = {"services": [{"id": "svc1", "name": "Apache Log4j", "version": "2.14.1", "cve": ["CVE-2021-44228"]}],
              "hosts": [{"id": "h1", "os": "Linux"}],
              "actions": [{"id": "a1", "service_ref": "svc1", "target_host_ref": "h1", "name": "Exploit Log4j"}]}
        manifest = DiscoveryEngine(client).discover("scenario-1", ir, "2026-11-16T00:00:00Z")
        self.assertEqual(iter_errors_shape("PocManifest", manifest), [])
        self.assertEqual(len(manifest["items"]), 2)
        self.assertEqual(manifest["items"], sorted(manifest["items"], key=lambda x: -x["compatibility_score"]))

    def test_cve_name_without_correlated_product_evidence_emits_nothing(self):
        client = Mock()
        client.nvd_search.return_value = {"source_url": "https://nvd.nist.gov/vuln/detail/CVE-2021-44228", "references": [], "description": "Apache Log4j"}
        client.exploitdb_search.return_value = []
        client.github_search.return_value = [{"source_url": "https://github.com/random/repo", "product": "repo", "description": "CVE-2021-44228"}]
        ir = {"services": [{"id": "svc", "name": "Apache Struts", "version": "2.5", "cve": ["CVE-2021-44228"]}],
              "actions": [{"id": "a", "service_ref": "svc", "name": "CVE-2021-44228"}]}
        self.assertEqual(DiscoveryEngine(client).discover("s", ir, "t")["items"], [])

    def test_no_public_poc_emits_empty_manifest(self):
        client = Mock()
        client.nvd_search.return_value = {"source_url": "https://nvd.nist.gov/vuln/detail/CVE-2020-0001", "references": [], "description": "Vendor product affected"}
        client.exploitdb_search.return_value = []
        client.github_search.return_value = []
        ir = {"services": [{"id": "svc", "name": "Vendor Widget", "cve": ["CVE-2020-0001"]}],
              "actions": [{"id": "a", "service_ref": "svc"}]}
        self.assertEqual(DiscoveryEngine(client).discover("s", ir, "t")["items"], [])

    def test_product_only_discovery_requires_cve_correlation(self):
        client = Mock()
        client.github_search.return_value = [{"source_url": "https://github.com/x/y", "product": "widget", "description": "Widget exploit", "language": "Python"}]
        manifest = DiscoveryEngine(client).discover("s", {"services": [{"id": "svc", "name": "Widget"}],
            "actions": [{"id": "a", "service_ref": "svc"}]}, "t")
        self.assertEqual(manifest["items"], [])


class MetadataClientTests(unittest.TestCase):
    def test_cve_extraction(self):
        self.assertEqual(cve_ids("CVE-2021-44228 cve-2021-44228", "CVE-2017-5638"), ["CVE-2017-5638", "CVE-2021-44228"])

    def test_github_rate_limit_degrades_without_repeating_request(self):
        client = MetadataClient(github_token="fixture")
        from unittest.mock import patch
        from urllib.error import HTTPError
        error = HTTPError("https://api.github.com", 403, "rate limited", {"X-RateLimit-Reset": "4102444800"}, None)
        with patch("app.poc.discovery.sources.urllib.request.urlopen", side_effect=error) as open_url:
            self.assertEqual(client.github_search("CVE-2021-44228"), [])
            self.assertEqual(client.github_search("CVE-2017-5638"), [])
        self.assertEqual(open_url.call_count, 1)


if __name__ == "__main__":
    unittest.main()
