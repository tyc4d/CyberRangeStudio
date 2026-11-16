"""Inventory: the single source of truth for what this platform can actually stand up.

Built on the curated catalogue (``catalogue/components.json``). Every entry carries a ``tier``
(have | obtainable | unavailable), the CVEs it really reproduces (``reproduces_cve``), what it can
stand in for (``substitute_for``) and how it is obtained (``obtainability``).

``resolve`` is the deterministic decision point described in ``docs/inventory/DESIGN.md``
(Resolution contract). It never asks a version question for something that cannot be deployed,
or whose version a named CVE already fixes; it asks only when several deployable versions of the
named product exist and nothing chooses between them.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from app.planner.catalogue import load_components

TIERS = ("have", "obtainable", "unavailable")
_TIER_RANK = {"have": 0, "obtainable": 1, "unavailable": 2}
_CVE_RE = re.compile(r"CVE-\d{4}-\d{4,}", re.IGNORECASE)
_EMPTY_SUBSTITUTE = {"products": [], "cves": [], "techniques": []}


def _norm(text: Any) -> str:
    return " ".join(str(text or "").casefold().replace("_", " ").split())


def _cve(text: Any) -> str:
    return str(text or "").strip().upper()


def _available(component: dict[str, Any]) -> bool:
    return component.get("tier") in ("have", "obtainable")


def _substitute_for(component: dict[str, Any]) -> dict[str, list[str]]:
    return component.get("substitute_for") or _EMPTY_SUBSTITUTE


def _label(component: dict[str, Any]) -> str:
    version = component.get("version")
    name = re.sub(r"\s*\([^)]*\)\s*$", "", str(component.get("name") or component["id"])).strip()
    return f"{name} {version}" if version and str(version) not in name else name


# ------------------------------------------------------------------ indexes


@lru_cache(maxsize=1)
def cve_index() -> dict[str, tuple[str, ...]]:
    """CVE id -> ids of deployable (have/obtainable) components that actually reproduce it."""
    index: dict[str, list[str]] = {}
    for component in load_components():
        if not _available(component):
            continue
        for cve in component.get("reproduces_cve", []):
            index.setdefault(_cve(cve), []).append(component["id"])
    return {cve: tuple(ids) for cve, ids in index.items()}


@lru_cache(maxsize=1)
def technique_index() -> dict[str, tuple[str, ...]]:
    """ATT&CK technique id -> ids of deployable components that can stand in for it."""
    index: dict[str, list[str]] = {}
    for component in load_components():
        if not _available(component):
            continue
        for technique in _substitute_for(component).get("techniques", []):
            index.setdefault(str(technique).upper(), []).append(component["id"])
    return {technique: tuple(ids) for technique, ids in index.items()}


def components_for_cve(cve: str) -> list[dict[str, Any]]:
    by_id = {component["id"]: component for component in load_components()}
    return [by_id[component_id] for component_id in cve_index().get(_cve(cve), ())]


# ------------------------------------------------------------------ matching


def _names(component: dict[str, Any]) -> set[str]:
    return {_norm(name) for name in [*component.get("aliases", []), *component.get("os_names", [])]}


def _product_matches(name: str, version: str | None) -> list[dict[str, Any]]:
    """Components that ARE the named product (never substitutes).

    A specific name ("Windows Server 2019", or "Windows Server" + version "2019") wins over the
    family name; an OS base image wins over the generic capability record of the same OS.
    """
    if not name:
        return []
    components = load_components()
    specific_keys = {name}
    if version:
        specific_keys.add(_norm(f"{name} {version}"))
    exact = [c for c in components if _names(c) & specific_keys]
    os_exact = [c for c in exact if c.get("kind") == "os_base"]
    if os_exact and any(_norm(n) in specific_keys for c in os_exact for n in c.get("os_names", [])):
        return os_exact
    family = [c for c in components
              if c.get("kind") == "os_base" and name in {_norm(n) for n in c.get("os_family_names", [])}]
    if family:
        return family
    return exact


def _version_matches(component: dict[str, Any], version: str | None) -> bool:
    pinned = _norm(component.get("version"))
    wanted = _norm(version)
    if not pinned or not wanted:
        return False
    wanted = wanted.removeprefix("v")
    return pinned == wanted or pinned.startswith(wanted + ".") or pinned.startswith(wanted + "-")


def _same_product(component: dict[str, Any], own: list[dict[str, Any]], name: str) -> bool:
    return any(c["id"] == component["id"] for c in own) or name in _names(component)


# ------------------------------------------------------------------ resolution


def _resolution(component: dict[str, Any] | None, *, tier: str, is_substitute: bool, version_basis: str,
                reproduces: list[str], substitute_of: str | None, reason: str,
                question: dict[str, Any] | None = None) -> dict[str, Any]:
    result = {
        "tier": tier,
        "component_id": component["id"] if component else None,
        "is_substitute": is_substitute,
        "version_basis": version_basis,
        "reproduces_cve": reproduces,
        "substitute_of": substitute_of,
        "reason": reason,
        "needs_question": question is not None,
    }
    if question is not None:
        result["question"] = question
    return result


def _reproduced(component: dict[str, Any], cves: list[str]) -> list[str]:
    reproduces = [_cve(cve) for cve in component.get("reproduces_cve", [])]
    return [cve for cve in reproduces if cve in cves] if cves else reproduces


def resolve(product_name: str | None, version: str | None = None, cves: list[str] | None = None,
            attack_technique: str | None = None, *, user_supplied: bool = False) -> dict[str, Any]:
    """Resolve one extracted component against the inventory (see DESIGN.md, Resolution contract).

    ``user_supplied=True`` marks ``version`` as given by the user rather than stated by the source.
    """
    name = _norm(product_name)
    display = str(product_name or "").strip() or "unnamed component"
    version = str(version).strip() if version not in (None, "") else None
    wanted_cves = list(dict.fromkeys(
        [_cve(cve) for cve in (cves or []) if _cve(cve)] + [_cve(m) for m in _CVE_RE.findall(display)]))
    technique = str(attack_technique or "").strip().upper() or None
    stated_basis = "user_supplied" if user_supplied else "stated"
    by_id = {component["id"]: component for component in load_components()}
    own = _product_matches(name, version)

    # 1. A named CVE that a deployable component reproduces decides the component; its pinned
    #    version IS the vulnerable version, so no version question is raised.
    cve_hits = {cid for cve in wanted_cves for cid in cve_index().get(cve, ())}
    if cve_hits:
        def rank(cid: str) -> tuple:
            component = by_id[cid]
            return (-len(_reproduced(component, wanted_cves)), not _same_product(component, own, name),
                    technique not in _substitute_for(component).get("techniques", []),
                    _TIER_RANK[component["tier"]], cid)
        chosen = by_id[min(cve_hits, key=rank)]
        reproduced = _reproduced(chosen, wanted_cves)
        missing = [cve for cve in wanted_cves if cve not in reproduced]
        tail = f" Not reproduced by it: {', '.join(missing)}." if missing else ""
        if _same_product(chosen, own, name):
            if version and _version_matches(chosen, version):
                basis = stated_basis
                why = f"stated version {version} matches"
            elif version:
                basis = "substituted"
                why = f"stated version {version} replaced by the pinned vulnerable version {chosen.get('version')}"
            else:
                basis = "assumed"
                why = f"pinned vulnerable version {chosen.get('version')} used; the CVE fixes the version"
            return _resolution(chosen, tier=chosen["tier"], is_substitute=False, version_basis=basis,
                               reproduces=reproduced, substitute_of=None,
                               reason=f"{chosen['id']} reproduces {', '.join(reproduced)}; {why}.{tail}")
        return _resolution(
            chosen, tier=chosen["tier"], is_substitute=True, version_basis="substituted", reproduces=reproduced,
            substitute_of=display,
            reason=(f"{display} itself is not reproducible here; substitute {_label(chosen)} ({chosen['id']}) "
                    f"reproduces the same {', '.join(reproduced)}. It is a flagged stand-in, never the original "
                    f"product.{tail}"))

    cve_note = f" Named CVE(s) {', '.join(wanted_cves)} are not reproducible by any inventory component." \
        if wanted_cves else ""

    # 2. The named product itself is deployable.
    if any(c.get("kind") == "os_base" for c in own):
        own = [c for c in own if c.get("kind") == "os_base"]
    deployable = [c for c in own if _available(c)]
    if deployable:
        if version:
            fitting = [c for c in deployable if _version_matches(c, version)]
            if len(fitting) == 1 or (fitting and len(deployable) == 1):
                chosen = fitting[0]
                return _resolution(chosen, tier=chosen["tier"], is_substitute=False, version_basis=stated_basis,
                                   reproduces=_reproduced(chosen, wanted_cves), substitute_of=None,
                                   reason=f"{_label(chosen)} ({chosen['id']}) matches the {stated_basis} version {version}.{cve_note}")
            if len(deployable) == 1:
                chosen = deployable[0]
                return _resolution(
                    chosen, tier=chosen["tier"], is_substitute=False, version_basis="substituted",
                    reproduces=_reproduced(chosen, wanted_cves), substitute_of=None,
                    reason=(f"Only {_label(chosen)} ({chosen['id']}) is deployable; it runs instead of the "
                            f"{stated_basis} version {version}.{cve_note}"))
            candidates = fitting or deployable
        else:
            if len(deployable) == 1:
                chosen = deployable[0]
                return _resolution(chosen, tier=chosen["tier"], is_substitute=False, version_basis="assumed",
                                   reproduces=_reproduced(chosen, wanted_cves), substitute_of=None,
                                   reason=f"Single deployable version: {_label(chosen)} ({chosen['id']}).{cve_note}")
            defaults = [c for c in deployable if c.get("family_default")]
            if len(defaults) == 1:
                chosen = defaults[0]
                return _resolution(
                    chosen, tier=chosen["tier"], is_substitute=False, version_basis="assumed",
                    reproduces=_reproduced(chosen, wanted_cves), substitute_of=None,
                    reason=(f"No version stated; default release {_label(chosen)} ({chosen['id']}) assumed — "
                            f"the release does not change this lab's behaviour.{cve_note}"))
            candidates = deployable
        # Genuine ambiguity: several deployable versions with different behaviour, nothing chooses.
        candidates = sorted(candidates, key=lambda c: (_TIER_RANK[c["tier"]], str(c.get("version") or ""), c["id"]))
        suggestions = [_label(c) for c in candidates]
        stated = f"（原文版本 {version} 無法部署）" if version else ""
        return _resolution(
            None, tier=min((c["tier"] for c in candidates), key=_TIER_RANK.get), is_substitute=False,
            version_basis=stated_basis if version else "assumed", reproduces=[], substitute_of=None,
            reason=f"{display} has {len(candidates)} deployable versions with different behaviour; a choice is needed.{cve_note}",
            question={"field": f"version for {display}",
                      "text": f"{display} 有多個可部署版本{stated}，請選擇實驗室要用哪一個：{'、'.join(suggestions)}。",
                      "suggestions": suggestions})

    # 3. Not deployable as itself: a by-name or by-technique stand-in, flagged.
    unavailable = next((c for c in own if not _available(c)), None)
    # Only the name as given: an unavailable entry's other aliases ("log4j" ~ "log4shell") must not
    # turn a vague mention into a CVE-specific stand-in.
    by_name = [c for c in load_components() if _available(c)
               and name in {_norm(p) for p in _substitute_for(c).get("products", [])}]
    by_technique = [by_id[cid] for cid in technique_index().get(technique, ())] if technique else []
    pool = by_name or (by_technique if len(by_technique) == 1 else [])
    if pool:
        chosen = min(pool, key=lambda c: (_TIER_RANK[c["tier"]], c["id"]))
        basis = "product name" if by_name else f"technique {technique}"
        return _resolution(
            chosen, tier=chosen["tier"], is_substitute=True, version_basis="substituted",
            reproduces=_reproduced(chosen, wanted_cves), substitute_of=display,
            reason=(f"{display} is not deployable; {_label(chosen)} ({chosen['id']}) stands in by {basis}. "
                    f"Flagged substitute, never the original product.{cve_note}"))

    # 4. Unavailable with no substitute: the version is moot, so no question.
    if unavailable is not None:
        why = unavailable.get("fidelity") or "no deployable image"
        reason = f"{display} is unavailable ({unavailable['id']}): {why}. No substitute in inventory; not reproducible."
    else:
        reason = f"{display} is not in the inventory and no substitute matches; not reproducible."
    if technique and len(by_technique) > 1:
        reason += f" Technique {technique} has several possible stand-ins ({', '.join(c['id'] for c in by_technique)}); none chosen automatically."
    return _resolution(None, tier="unavailable", is_substitute=False,
                       version_basis=stated_basis if version else "assumed", reproduces=[], substitute_of=None,
                       reason=reason + cve_note)


# ------------------------------------------------------------------ summaries


def inventory_entries() -> list[dict[str, Any]]:
    """Structured per-entry availability (for UI and reports)."""
    return [{
        "id": c["id"], "name": c.get("name"), "kind": c.get("kind", "component"), "runtime": c.get("runtime"),
        "version": c.get("version"), "tier": c.get("tier"), "reproduces_cve": list(c.get("reproduces_cve", [])),
        "substitute_for": _substitute_for(c), "obtainability": c.get("obtainability"),
    } for c in load_components()]


def inventory_summary() -> str:
    """Compact availability summary for the analysis LLM prompt (a hint; ``resolve`` decides)."""
    lines = ["Lab inventory (what this platform can stand up; anything else is not reproducible):"]
    for tier in TIERS:
        parts = []
        for c in load_components():
            if c.get("tier") != tier or c["id"] == "oss-attacker":
                continue
            part = _label(c)
            if c.get("reproduces_cve"):
                part += f" [reproduces {', '.join(c['reproduces_cve'])}]"
            products = _substitute_for(c).get("products", [])
            if products:
                part += f" [stand-in for {', '.join(products[:3])}]"
            if tier == "obtainable" and (c.get("obtainability") or {}).get("est_cost_usd") is not None:
                part += f" (${c['obtainability']['est_cost_usd']})"
            parts.append(part)
        if parts:
            lines.append(f"- {tier}: " + "; ".join(parts))
    if cve_index():
        lines.append("- CVE -> deployable component (used as flagged substitute when the product differs): "
                     + "; ".join(f"{cve} -> {', '.join(ids)}" for cve, ids in sorted(cve_index().items())))
    return "\n".join(lines)
