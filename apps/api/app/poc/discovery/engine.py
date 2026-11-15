"""Scenario action PoC discovery; external integrations are metadata-only."""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Callable, Mapping

from .ranking import rank_candidate
from .sources import MetadataClient, cve_ids


def _text(*values: Any) -> str:
    return " ".join(str(v) for v in values if v is not None)


def _method(language: str) -> str:
    name = (language or "").casefold()
    if "python" in name: return "python"
    if name in {"shell", "bash", "sh"}: return "bash"
    if name == "go": return "go"
    return "manual"


class DiscoveryEngine:
    """Build a ranked PocManifest from a scenario IR mapping or action sequence.

    Sources expose repository/CVE/index metadata only. This class never downloads PoC
    bodies and never invokes candidate code.
    """
    def __init__(self, client: MetadataClient | None = None):
        self.client = client or MetadataClient()

    def discover(self, scenario_id: str, scenario: Mapping[str, Any] | list[Mapping[str, Any]],
                 generated_at: str | None = None) -> dict[str, Any]:
        actions = scenario if isinstance(scenario, list) else scenario.get("actions", [])
        services = [] if isinstance(scenario, list) else scenario.get("services", [])
        hosts = [] if isinstance(scenario, list) else scenario.get("hosts", [])
        service_by_id = {str(s.get("id")): s for s in services}
        host_by_id = {str(h.get("id")): h for h in hosts}
        output: list[dict[str, Any]] = []
        for action in actions:
            action_id = str(action.get("id", ""))
            service = service_by_id.get(str(action.get("service_ref", "")), {})
            host = host_by_id.get(str(action.get("target_host_ref", "")), {})
            product = _text(service.get("product"), service.get("name"), action.get("product"))
            target = {"product": product, "version": _text(service.get("version"), action.get("version")),
                      "os": host.get("os", ""), "runtime": _text(service.get("runtime"), service.get("language")),
                      "privileges": action.get("required_privileges", ""),
                      "cves": cve_ids(service.get("cve"), service.get("cves"), action.get("cve"))}
            cves = cve_ids(action.get("cve"), service.get("cve"), service.get("cves"), action.get("name"), action.get("description"))
            # Don't discover generic text-only actions: require a structured CVE or product evidence.
            if not cves and not product:
                continue
            raw_candidates: list[dict[str, Any]] = []
            for cve in cves:
                nvd = self.client.nvd_search(cve)
                exploit_rows = self.client.exploitdb_search(cve)
                github_rows = self.client.github_search(f'"{cve}" exploit')
                # NVD is a reference index, not an executable PoC. Its reference links
                # only seed source lookups and are never emitted as executable candidates.
                if nvd:
                    for ref_url in nvd.get("references", []):
                        if "github.com/" in ref_url.casefold():
                            github_rows += self.client.github_search(ref_url.split("github.com/", 1)[-1].split("/", 2)[0] + " " + cve)
                for row in github_rows:
                    desc = row.get("description", "")
                    if not self._relevant(row, cve, product, desc):
                        continue
                    raw_candidates.append(self._candidate(action_id, cve, row, product, service, "github"))
                for row in exploit_rows:
                    if self._relevant(row, cve, product, row.get("description", "")):
                        raw_candidates.append(self._candidate(action_id, cve, row, product, service, "exploitdb"))
                if nvd and self._vendor_reference(nvd, product):
                    raw_candidates.append({"action_id": action_id, "cve": cve, "source": "nvd",
                        "source_url": nvd["source_url"], "ref": {}, "product": product or "unspecified",
                        "version_range": self._version_hint(nvd.get("description", "")), "language": "unknown",
                        "dependencies": [], "preconditions": [], "exec_method": "manual", "trust": "high",
                        "last_updated": nvd.get("last_updated"), "license": ""})
            # Product-only lookup helps vendor/code-repo discovery, but product names alone
            # cannot qualify: candidate must also link this CVE and match product evidence.
            if product and not cves:
                for row in self.client.github_search(f'"{product}" exploit'):
                    row_cves = cve_ids(row.get("description"))
                    if not row_cves:
                        continue
                    for cve in row_cves:
                        if self._relevant(row, cve, product, row.get("description", "")):
                            raw_candidates.append(self._candidate(action_id, cve, row, product, service, "github"))
            for candidate in raw_candidates:
                if candidate["source"] == "nvd":
                    # NVD metadata is useful as a pointer, not runnable code; avoid implying
                    # code availability. It can rank only when a linked public PoC exists.
                    continue
                output.append(rank_candidate(candidate, target))
        output.sort(key=lambda item: (-item["compatibility_score"], item["source"], item["source_url"]))
        return {"scenario_id": scenario_id, "generated_at": generated_at or dt.datetime.now(dt.timezone.utc).isoformat(), "items": output}

    @staticmethod
    def _relevant(row: Mapping[str, Any], cve: str, product: str, description: str) -> bool:
        text = _text(row.get("product"), row.get("name"), description, row.get("source_url"))
        # CVE token alone is insufficient; require an independent product identifier or
        # exploit-context signal. The product check is deliberately conservative.
        has_cve = cve.casefold() in text.casefold()
        p = re.sub(r"[^a-z0-9]", "", product.casefold())
        t = re.sub(r"[^a-z0-9]", "", text.casefold())
        product_match = len(p) >= 4 and p in t
        return has_cve and (product_match or "exploit" in text.casefold() or "poc" in text.casefold())

    @staticmethod
    def _vendor_reference(nvd: Mapping[str, Any], product: str) -> bool:
        if not product:
            return False
        p = re.sub(r"[^a-z0-9]", "", product.casefold())
        return len(p) >= 4 and any(p in re.sub(r"[^a-z0-9]", "", u.casefold()) for u in nvd.get("references", []))

    @staticmethod
    def _version_hint(description: str) -> str:
        matches = re.findall(r"(?:versions?\s+)?(?:before|prior to|through|up to)?\s*\d+(?:\.\d+){1,3}(?:\s*(?:through|to|-|–)\s*\d+(?:\.\d+){1,3})?", description, re.I)
        return "; ".join(matches[:4])

    @staticmethod
    def _candidate(action_id: str, cve: str, row: Mapping[str, Any], product: str,
                   service: Mapping[str, Any], source: str) -> dict[str, Any]:
        ref = dict(row.get("ref") or {})
        if source == "github":
            # The repository default branch is not immutable. Resolve it to a commit ref
            # using API metadata in the future; omit fake commit pins here.
            ref = {}
        return {"action_id": action_id, "cve": cve, "source": source,
                "source_url": row.get("source_url", ""), "ref": ref,
                "product": product or row.get("product") or "unspecified",
                "version_range": str(service.get("version_range") or DiscoveryEngine._version_hint(row.get("description", ""))),
                "language": row.get("language") or "unknown", "dependencies": [],
                "preconditions": [], "exec_method": _method(str(row.get("language") or "")),
                "license": row.get("license") or "", "trust": "high" if source == "vendor" else "medium",
                "last_updated": row.get("last_updated") or ""}


def discover(scenario_id: str, scenario: Mapping[str, Any] | list[Mapping[str, Any]],
             client: MetadataClient | None = None, generated_at: str | None = None) -> dict[str, Any]:
    return DiscoveryEngine(client).discover(scenario_id, scenario, generated_at)
