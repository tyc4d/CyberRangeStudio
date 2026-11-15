"""Deterministic compatibility scoring for metadata-only PoC candidates."""
from __future__ import annotations

import re
from typing import Any, Mapping

WEIGHTS = {"version": .35, "env": .20, "code_available": .20, "source_trust": .15, "exec_cost": .10}
_VERSION = r"\d+(?:\.\d+)+"


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _release(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def _compare(left: tuple[int, ...], right: tuple[int, ...]) -> int:
    length = max(len(left), len(right))
    left += (0,) * (length - len(left))
    right += (0,) * (length - len(right))
    return (left > right) - (left < right)


def _in_version_range(target: tuple[int, ...], expression: str) -> bool | None:
    """Evaluate supported release ranges; unknown syntax is not compatibility proof."""
    expression = re.sub(r"^versions?\s+", "", expression.strip().casefold())
    bounded = re.fullmatch(rf"({_VERSION})\s*(?:through|to|[-–])\s*({_VERSION})", expression)
    if bounded:
        lower, upper = map(_release, bounded.groups())
        return _compare(lower, target) <= 0 and _compare(target, upper) <= 0
    bound = re.fullmatch(rf"(before|prior to|earlier than|through|up to|after|at least|<=|>=|<|>)\s*({_VERSION})", expression)
    if bound:
        operator, version = bound.groups()
        comparison = _compare(target, _release(version))
        if operator in {"before", "prior to", "earlier than", "<"}:
            return comparison < 0
        if operator in {"through", "up to", "<="}:
            return comparison <= 0
        if operator in {"after", ">"}:
            return comparison > 0
        return comparison >= 0
    family = re.fullmatch(r"(\d+(?:\.\d+)*)\.(?:x|\*)", expression)
    if family:
        prefix = _release(family.group(1))
        return target[:len(prefix)] == prefix
    if re.fullmatch(_VERSION, expression):
        return _compare(target, _release(expression)) == 0
    return None


def _version_score(target: str | None, version_range: str, product_match: bool) -> float:
    if not product_match:
        return 0.0
    if not target:
        return .45  # product/CVE evidence exists, but no target version to compare
    range_norm = _norm(version_range)
    if not version_range or any(x in range_norm for x in ("all versions", "version independent", "any version")):
        return .65
    # Only a concrete numeric target release can prove range membership. Do not
    # discard qualifiers (e.g. -rc1) or extract an arbitrary endpoint from prose.
    target_release = re.fullmatch(rf"v?({_VERSION})", target.strip().casefold())
    if not target_release:
        return .4
    # _version_hint emits semicolon-separated alternatives. Evaluate complete
    # clauses, preserving exclusive/inclusive bounds instead of matching tokens.
    matches = [_in_version_range(_release(target_release.group(1)), clause)
               for clause in version_range.split(";")]
    if any(match is True for match in matches):
        return 1.0
    return .45 if any(match is None for match in matches) else .05


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
