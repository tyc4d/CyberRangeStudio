"""Small, read-only metadata adapters. Fetched text is never treated as instructions."""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

USER_AGENT = "CyberRange-PoC-Metadata-Discovery/1.0"


class MetadataClient:
    def __init__(self, timeout: float = 8, github_token: str | None = None):
        self.timeout = timeout
        self.github_token = github_token if github_token is not None else _github_token()
        self._cache: dict[str, tuple[float, Any]] = {}
        self._github_reset = 0.0

    def _json(self, url: str, github: bool = False) -> Any:
        cached = self._cache.get(url)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        if github and self._github_reset > time.monotonic():
            return None
        headers = {"Accept": "application/vnd.github+json" if github else "application/json", "User-Agent": USER_AGENT}
        if github and self.github_token:
            headers["Authorization"] = f"Bearer {self.github_token}"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read(2_000_000).decode("utf-8"))
                self._cache[url] = (time.monotonic() + 300, data)
                return data
        except urllib.error.HTTPError as exc:
            if github and exc.code == 403:
                reset = exc.headers.get("X-RateLimit-Reset")
                try:
                    wait = max(60.0, float(reset or 0) - time.time())
                    self._github_reset = time.monotonic() + wait
                except ValueError:
                    self._github_reset = time.monotonic() + 60
            return None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            return None

    def github_search(self, query: str) -> list[dict[str, Any]]:
        url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode({"q": query, "sort": "updated", "per_page": 10})
        data = self._json(url, github=True) or {}
        results = []
        for item in data.get("items", []):
            # Search metadata only. No source files, README, issues, or instructions are fetched.
            results.append({"source": "github", "source_url": item.get("html_url", ""),
                            "ref": {"commit_sha": item.get("default_branch") or ""},
                            "product": item.get("name", ""), "description": item.get("description") or "",
                            "license": (item.get("license") or {}).get("spdx_id"),
                            "last_updated": item.get("pushed_at"), "stars": item.get("stargazers_count", 0),
                            "language": item.get("language") or "unknown", "fork": item.get("fork", False)})
        return results

    def nvd_search(self, cve: str) -> dict[str, Any] | None:
        url = "https://services.nvd.nist.gov/rest/json/cves/2.0?" + urllib.parse.urlencode({"cveId": cve})
        data = self._json(url) or {}
        rows = data.get("vulnerabilities", [])
        if not rows:
            return None
        item = rows[0].get("cve", {})
        refs = item.get("references", [])
        return {"source": "nvd", "cve": cve, "source_url": f"https://nvd.nist.gov/vuln/detail/{cve}",
                "description": next((d.get("value", "") for d in item.get("descriptions", []) if d.get("lang") == "en"), ""),
                "references": [r.get("url", "") for r in refs], "last_updated": item.get("lastModified"),
                "weaknesses": [d.get("value") for w in item.get("weaknesses", []) for d in w.get("description", [])]}

    def exploitdb_search(self, cve: str) -> list[dict[str, Any]]:
        # Exploit-DB provides a public CSV metadata index; fetch only that index, never exploit files.
        url = "https://raw.githubusercontent.com/offensive-security/exploitdb/master/files_exploits.csv"
        data = self._json_csv(url)
        rows = []
        for row in data:
            haystack = " ".join(str(row.get(k, "")) for k in ("description", "codes", "platform", "type"))
            if cve.casefold() in haystack.casefold():
                eid = str(row.get("id", ""))
                rows.append({"source": "exploitdb", "source_url": f"https://www.exploit-db.com/exploits/{eid}",
                             "ref": {"release": eid}, "product": row.get("description", ""),
                             "description": row.get("description", ""), "language": "unknown",
                             "last_updated": row.get("date_published"), "trust_hint": "medium"})
        return rows[:10]

    def _json_csv(self, url: str) -> list[dict[str, str]]:
        cached = self._cache.get(url)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                import csv
                import io
                parsed = list(csv.DictReader(io.StringIO(response.read(5_000_000).decode("utf-8", "replace"))))
                self._cache[url] = (time.monotonic() + 3600, parsed)
                return parsed
        except (urllib.error.URLError, TimeoutError, OSError):
            return []


def cve_ids(*values: Any) -> list[str]:
    text = " ".join(str(v or "") for v in values)
    return sorted({match.upper() for match in re.findall(r"CVE-\d{4}-\d{4,}", text, re.I)})


def _github_token() -> str | None:
    token = os.getenv("GITHUB_TOKEN")
    if token:
        return token
    # Read only the explicitly named API token from the project .env; never expose it
    # in metadata or error text. Parsing stays deliberately narrow and non-interpolating.
    path = os.environ.get("CR_PROJECT_ENV", "/home/tyc4d/cr-project/.env")
    try:
        with open(path, encoding="utf-8") as env_file:
            for line in env_file:
                key, sep, value = line.strip().partition("=")
                if sep and key.strip() in {"GITHUB_TOKEN", "GH_TOKEN"}:
                    return value.strip().strip("\"'") or None
    except OSError:
        pass
    return None
