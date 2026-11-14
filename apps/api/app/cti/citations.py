"""Program-side quote and locator verification."""
from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from typing import Any

from app.cti.parser import SourceUnit


_STIX_PATH = re.compile(r"^(?:objects\[(\d+)\]|object)(?:\.([A-Za-z0-9_]+))?$")

# Model-inserted MITRE ATT&CK annotations (technique ids like [T1190]/[T1059.001] and
# tactic ids like [TA0001]). The source prose does not contain these inline tags; strip
# them so an otherwise-verbatim quote still matches, and so the stored quote shows the
# real source wording. ATT&CK ids live in attack_technique/attack_tactic, not in quotes.
_ATTACK_TAG = re.compile(r"\s*\[(?:T\d{4}(?:\.\d{3})?|TA\d{4})\]")
_WS = re.compile(r"\s+")

# Conservative thresholds: require substantial contiguous/overall agreement for
# strong support, and broad content-word coverage for partial support.
_STRONG_CONTIGUOUS_RATIO = 0.70
_STRONG_CONTIGUOUS_MIN_CHARS = 40
_STRONG_SEQUENCE_RATIO = 0.85
_PARTIAL_KEYWORD_COVERAGE = 0.60
_MATCHED_TEXT_MAX_CHARS = 160
_ENGLISH_STOP_WORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "been", "being", "but", "by",
    "can", "could", "did", "do", "does", "for", "from", "had", "has", "have",
    "he", "her", "hers", "him", "his", "i", "if", "in", "into", "is", "it",
    "its", "may", "might", "more", "most", "of", "on", "or", "our", "ours",
    "she", "should", "so", "such", "than", "that", "the", "their", "theirs",
    "them", "then", "there", "these", "they", "this", "those", "to", "was",
    "we", "were", "what", "when", "where", "which", "who", "will", "with",
    "would", "you", "your", "yours",
})


def _content_words(text: str) -> list[str]:
    return [word for word in re.findall(r"[a-z0-9]+(?:['’][a-z0-9]+)?", text.lower())
            if word not in _ENGLISH_STOP_WORDS]


def grade_quote(quote: str, source_text: str) -> dict[str, Any]:
    """Grade quote support against a single source text unit."""
    needle = _match_norm(quote) if isinstance(quote, str) else ""
    haystack = _match_norm(source_text) if isinstance(source_text, str) else ""
    result: dict[str, Any] = {"level": "none", "score": 0.0, "matched": ""}
    if not needle or not haystack:
        return result

    if needle in haystack:
        return {"level": "exact", "score": 1.0, "matched": needle[:_MATCHED_TEXT_MAX_CHARS]}

    matcher = SequenceMatcher(None, needle, haystack, autojunk=False)
    longest = matcher.find_longest_match(0, len(needle), 0, len(haystack))
    ratio = matcher.ratio()
    if longest.size >= max(_STRONG_CONTIGUOUS_MIN_CHARS, len(needle) * _STRONG_CONTIGUOUS_RATIO) or ratio >= _STRONG_SEQUENCE_RATIO:
        start = longest.b
        matched = haystack[start:start + longest.size]
        return {"level": "strong", "score": round(max(ratio, longest.size / len(needle)), 4), "matched": matched[:_MATCHED_TEXT_MAX_CHARS]}

    words = _content_words(needle)
    source_words = set(_content_words(haystack))
    if words:
        coverage = sum(word in source_words for word in words) / len(words)
        if coverage >= _PARTIAL_KEYWORD_COVERAGE:
            matched_words = set(words) & source_words
            source_tokens = re.finditer(r"[a-z0-9]+(?:['’][a-z0-9]+)?", haystack, re.IGNORECASE)
            positions = [m.start() for m in source_tokens if m.group(0).lower() in matched_words]
            if positions:
                start = max(0, positions[0] - 55)
                end = min(len(haystack), start + _MATCHED_TEXT_MAX_CHARS)
                return {"level": "partial", "score": round(coverage, 4), "matched": haystack[start:end]}

    if longest.size:
        start = longest.b
        result["matched"] = haystack[start:start + longest.size][:_MATCHED_TEXT_MAX_CHARS]
    return result


def strip_attack_tags(text: str) -> str:
    """Remove model-inserted [T####]/[TA####] annotations from a quote (keeps source wording)."""
    return _ATTACK_TAG.sub("", text).strip() if isinstance(text, str) else ""


def _match_norm(text: str) -> str:
    """Normalise for verbatim matching: drop injected ATT&CK tags and collapse whitespace.

    PDF extraction hard-wraps lines and pads columns, so the same words arrive with
    different whitespace; collapsing it is not a licence for paraphrase — any changed
    word still fails the substring test.
    """
    return _WS.sub(" ", _ATTACK_TAG.sub("", text)).strip()


def verify_quote(quote: str, locator: dict[str, str], units: list[SourceUnit], parsed_source: dict[str, Any] | None) -> bool:
    """Check that a verbatim quote is present at the supplied source locator."""
    if not isinstance(quote, str) or not quote:
        return False
    needle = _match_norm(quote)
    if not needle:
        return False
    kind = locator.get("kind")
    ref = locator.get("ref", "")
    if kind == "paragraph":
        try:
            index = int(ref)
        except (TypeError, ValueError):
            return False
        return any(unit.locator == {"kind": "paragraph", "ref": str(index)} and grade_quote(needle, unit.text)["level"] in {"exact", "strong"} for unit in units)
    if kind != "stix_path" or parsed_source is None:
        return False
    match = _STIX_PATH.fullmatch(ref)
    if not match:
        return False
    object_index, property_name = match.groups()
    if object_index is None:
        obj = parsed_source
    else:
        objects = parsed_source.get("objects")
        idx = int(object_index)
        if not isinstance(objects, list) or idx >= len(objects) or not isinstance(objects[idx], dict):
            return False
        obj = objects[idx]
    value: Any = obj.get(property_name) if property_name else obj
    if isinstance(value, str):
        return grade_quote(needle, value)["level"] in {"exact", "strong"}
    if isinstance(value, (dict, list)):
        canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return grade_quote(needle, canonical)["level"] in {"exact", "strong"}
    return False


def evidence_record(evidence_id: str, quote: str, source_ref: str, units: list[SourceUnit], parsed_source: dict[str, Any] | None) -> dict[str, Any]:
    """Build a schema-shaped evidence record and retain failed citations."""
    unit_by_id = {unit.id: unit for unit in units}
    unit = unit_by_id.get(source_ref)
    if unit is None:
        locator = {"kind": "paragraph", "ref": f"unresolved:{source_ref or 'empty'}"}
    else:
        locator = dict(unit.locator)
    # Store the quote with any model-inserted ATT&CK tags removed, so what is shown is
    # the source's own wording (ids belong in attack_technique/attack_tactic).
    clean_quote = strip_attack_tags(quote)
    source_text = unit.text if unit is not None else ""
    if unit is not None and unit.locator.get("kind") == "stix_path" and parsed_source is not None:
        match = _STIX_PATH.fullmatch(unit.locator.get("ref", ""))
        if match:
            object_index, property_name = match.groups()
            obj: Any = parsed_source
            if object_index is not None:
                objects = parsed_source.get("objects")
                idx = int(object_index)
                obj = objects[idx] if isinstance(objects, list) and idx < len(objects) else None
            value = obj.get(property_name) if isinstance(obj, dict) and property_name else obj
            if isinstance(value, str):
                source_text = value
            elif isinstance(value, (dict, list)):
                source_text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    grade = grade_quote(clean_quote, source_text)
    quote_verified = grade["level"] in {"exact", "strong"}
    return {
        "id": evidence_id,
        "quote": clean_quote,
        "locator": locator,
        "quote_verified": quote_verified,
        "quote_match": grade["level"],
        "match_score": grade["score"],
        "matched_text": grade["matched"],
    }

