"""Deterministic compatibility scoring for metadata-only PoC candidates."""
from __future__ import annotations

import re
from typing import Any, Mapping

WEIGHTS = {"version": .35, "env": .20, "code_available": .20, "source_trust": .15, "exec_cost": .10}


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _version_score(target: str | None, version_range: str, product_match: bool) -> float:
    if not product_match:
        return 0.0
    if not target:
        return .45  # product/CVE evidence exists, but no target version to compare
    target_norm = _norm(target)
    range_norm = _norm(version_range)
    if not version_range or any(x in range_norm for x in ("all versions", "version independent", "any version")):
        return .65
    # Explicit ranges commonly include exact versions or family tokens (e.g. 2.3.x).
    tokens = re.findall(r"\d+(?:\.\d+)+(?:\.x)?", version_range.casefold())
    if not tokens:
        return .45
    target_tokens = re.findall(r"\d+(?:\.\d+)+", target.casefold())
    if not target_tokens:
        return .4
    for token in tokens:
        if token.endswith(".x"):
            if target_tokens[0].startswith(token[:-1]):
                return 1.0
        elif target_tokens[0] == token:
            return 1.0
        elif target_tokens[0].startswith(token + "."):
            return .85
    # A known but nonmatching version is meaningful negative evidence.
    return .05


def score_candidate(candidate: Mapping[str, Any], target: Mapping[str, Any] | None = None) -> dict[str, float]:
    """Return the five contract dimensions, each normalized to [0, 1]."""
    target = target or {}
    product = str(candidate.get("product") or "")
    target_product = str(target.get("product") or "")
    cve = str(candidate.get("cve") or "").casefold()
    target_cves = {str(x).casefold() for x in target.get("cves", [])}
    product_match = bool(product and target_product and (
        _norm(product) in _norm(target_product) or _norm(target_product) in _norm(product)))
    cve_match = bool(cve and cve in target_cves)
    version = _version_score(str(target.get("version") or "") or None,
                             str(candidate.get("version_range") or ""), product_match)
    reqs = [str(x).casefold() for x in candidate.get("preconditions", [])]
    env = 1.0
    for requirement in reqs:
        if any(term in requirement for term in ("windows", "linux", "python", "java", "root", "admin")):
            target_text = " ".join(str(target.get(k, "")) for k in ("os", "runtime", "privileges")).casefold()
            if not any(term in target_text for term in re.findall(r"windows|linux|python|java|root|admin", requirement)):
                env = min(env, .25)
    method = str(candidate.get("exec_method", "manual"))
    code = 1.0 if method in {"python", "bash", "go", "http_seq", "metasploit"} else .35
    trust = {"high": 1.0, "medium": .7, "low": .4, "unknown": .2}.get(str(candidate.get("trust", "unknown")), .2)
    cost = {"http_seq": 1.0, "python": .85, "bash": .8, "go": .65, "metasploit": .45, "manual": .1}.get(method, .1)
    return {"version": version, "env": env, "code_available": code,
            "source_trust": trust, "exec_cost": cost}


def rank_candidate(candidate: Mapping[str, Any], target: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Copy candidate fields and attach normalized score breakdown and total."""
    result = dict(candidate)
    breakdown = score_candidate(candidate, target)
    result["score_breakdown"] = breakdown
    result["compatibility_score"] = round(sum(breakdown[k] * WEIGHTS[k] for k in WEIGHTS), 4)
    return result
