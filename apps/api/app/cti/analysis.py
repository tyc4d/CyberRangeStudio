"""LLM-backed Scenario IR construction, constrained by source locators."""
from __future__ import annotations

import hashlib
import html
import json
import re
from typing import Any

from app.cti.attack import lookup as lookup_attack_technique
from app.cti.citations import evidence_record, grade_quote, strip_attack_tags
from app.cti.missing import calculate_missing_items, is_communication_description
from app.cti.parser import SourceUnit
from app.llm.client import complete


METHODS = {"single_pass", "staged", "staged_review"}
_STATUSES = {"supported", "inferred", "absent", "insufficient"}
_RELATION_KINDS = {"temporal", "dependency"}
_PROMPT_FORMAT = {"type": "json_object"}
_ATTACK_TECHNIQUE_RE = re.compile(r"^T\d{4}(?:\.\d{3})?$", re.IGNORECASE)
_ATTACK_TACTIC_ID_RE = re.compile(r"^TA\d{4}$", re.IGNORECASE)
_CVE_RE = re.compile(r"\bCVE-\d{4}-\s*\d{4,7}\b", re.IGNORECASE)
_IPV4_RE = re.compile(r"(?<![\w.])\d{1,3}(?:\[\.\]|\.)\d{1,3}(?:\[\.\]|\.)\d{1,3}(?:\[\.\]|\.)\d{1,3}(?![\w.])")
_DOMAIN_RE = re.compile(
    r"(?<![A-Za-z0-9@_-])(?:\*\.)?(?:[A-Za-z0-9_*~\u2010-\u2014-]+(?:\[\.\]|\.)+)+"
    r"(?:[A-Za-z]{2,}|xn--[A-Za-z0-9-]{2,})(?![A-Za-z0-9_-])"
)
_URL_RE = re.compile(r"\b(?:https?|hxxps?)://[^\s<>\"'`()]+", re.IGNORECASE)
_HASH_RE = re.compile(r"(?<![A-Fa-f0-9])(?:[A-Fa-f0-9]{128}|[A-Fa-f0-9]{64}|[A-Fa-f0-9]{40}|[A-Fa-f0-9]{32})(?![A-Fa-f0-9])")
_SHELL_COMMAND_RE = re.compile(
    r"\b(?P<interpreter>powershell(?:\.exe)?|pwsh(?:\.exe)?|cmd(?:\.exe)?)\s+(?P<args>[^\r\n]+)",
    re.IGNORECASE,
)
_COMMAND_ARG_RE = re.compile(
    r"^(?:-[A-Za-z][\w:-]*|/[A-Za-z]+|try\s*\{|\{|\$|&|[\[\"']|"
    r"(?:get|set|new|add|remove|invoke|start|stop|write|read|select|where|foreach|"
    r"whoami|net|ipconfig|rundll32|certutil|reg|sc|tasklist|wmic|dir|echo|ping)[\w.-]*\b)",
    re.IGNORECASE,
)
_KNOWN_TACTIC_IDS = {
    "TA0001": "initial-access", "TA0002": "execution", "TA0003": "persistence",
    "TA0004": "privilege-escalation", "TA0005": "defense-evasion",
    "TA0006": "credential-access", "TA0007": "discovery", "TA0008": "lateral-movement",
    "TA0009": "collection", "TA0010": "exfiltration", "TA0011": "command-and-control",
    "TA0040": "impact", "TA0042": "resource-development", "TA0043": "reconnaissance",
}
_KNOWN_TACTICS = frozenset(_KNOWN_TACTIC_IDS.values())
_IOC_CONTEXT_RE = re.compile(
    r"\b(?:ioc|indicators?|known malicious|malicious (?:ip|domain|url)|c2|server|"
    r"connection|connected|callback|download(?:ed)?|beacon|resolved?|observed|phishing|infra)\b",
    re.IGNORECASE,
)
# Placeholder words a model may use where the source names no machine. They are never host ids.
_NON_ATTACKER_ACTORS = frozenset({"defender", "victim", "responder", "analyst", "investigator", "vendor", "other"})
_RESERVED_HOST_IDS = frozenset({"unknown", "unspecified", "none", "null", "n/a", "na", "any", "various", "multiple"})

# Words by which a source sentence itself states order or enablement. A relation is only
# "supported" when a verified quote contains such wording; a quote that merely describes one
# endpoint proves the action, not the edge.
_TEMPORAL_CUE_RE = re.compile(
    r"\b(?:then|after(?:wards?)?|following|followed[\s-]by|subsequent(?:ly)?|next|once|upon|before|prior\s+to|"
    r"preced\w+|later|finally|first|initially|earlier|thereafter|when|occurs[\s-](?:before|after)|"
    r"as\s+part\s+of)\b|[之隨]後|然後|接著|之前|首先|最後",
    re.IGNORECASE,
)
_DEPENDENCY_CUE_RE = re.compile(
    r"\b(?:using|by\s+(?:exploiting|using|leveraging|abusing)|leverag\w+|with\s+(?:the|this|these|those|that)|"
    r"via\s+(?:the|this|these|those|that)|through\s+(?:the|this|these|those|that)|enabl\w+|allow\w+|"
    r"prerequisites?|requir\w+|depend\w+|in\s+order\s+to|so\s+that|newly\s+(?:created|obtained|acquired)|"
    r"(?:stolen|harvested|obtained|compromised|downloaded|created)\s+\w+(?:\s+\w+)?\s+to\b|"
    r"when\s+executed|which\s+(?:was|were)\s+(?:then\s+)?used|as\s+a\s+result\s+of|result(?:ed|ing)\s+in|"
    r"led\s+to|thereby|after\s+(?:gaining|obtaining|acquiring|establishing)|because)\b|利用|藉由|透過|憑藉|使用(?:該|此|這)",
    re.IGNORECASE,
)
_PROVENANCE_LABEL_RE = re.compile(
    r"\b(?:source|official advisory|reference|citation|licen[sc]e)\b[^:\n]{0,40}:", re.IGNORECASE)
# "URL:"/"Link:" only describe the document itself inside a block that already has a Source line.
_PROVENANCE_LINK_LABEL_RE = re.compile(r"\b(?:url|link)\b[^:\n]{0,20}:", re.IGNORECASE)
_PROVENANCE_HASH_LABEL_RE = re.compile(
    r"\b(?:source|document|advisory|report|pdf)\b[^:\n]{0,30}\b(?:sha-?\d*|md5|checksum|hash)\b", re.IGNORECASE)


# Wording by which a source marks its own statement as uncertain or unconfirmed.
_HEDGE_RE = re.compile(
    r"\b(?:may|might|could)\s+have\b|\bappears?\s+to\b|\bseems?\s+to\b|\bwe\s+believe\b|\bis\s+believed\b|"
    r"\b(?:possibly|reportedly|allegedly|presumably|purportedly|unconfirmed|suspected)\b|\breason\s+to\s+believe\b|"
    r"\bnot\s+(?:able\s+to\s+)?confirm(?:ed)?\b|可能|疑似|據稱|尚未證實|未經證實",
    re.IGNORECASE,
)


def _hedged_statement(quotes: list[str], unit_texts: list[str]) -> bool:
    """True when a sentence the quote comes from is itself hedged ("may have", "appears to").

    The quote can be clipped after the hedge, so the enclosing source sentence is checked.
    """
    normalise = lambda value: re.sub(r"\s+", " ", value).strip().casefold()
    for quote in quotes:
        needle = normalise(quote)
        if not needle:
            continue
        if _HEDGE_RE.search(quote):
            return True
        for text in unit_texts:
            for sentence in re.split(r"(?<=[.!?])\s+", text):
                plain = normalise(sentence)
                if plain and (needle in plain or plain in needle) and _HEDGE_RE.search(sentence):
                    return True
    return False


_BLOCKED_RE = re.compile(
    r"\b(?:was|were|been|being)\s+(?:stopped|blocked|prevented|thwarted|denied|interrupted)\b|"
    r"\b(?:unsuccessful(?:ly)?|did\s+not\s+succeed|failed\s+to|without\s+success)\b|未成功|被阻擋|被攔阻|失敗", re.IGNORECASE)
_PARTIAL_RE = re.compile(r"\b(?:a\s+portion\s+of|some\s+of|part\s+of|partially|partly)\b[^.]{0,60}\bsuccess", re.IGNORECASE)


def _enclosing_sentences(quotes: list[str], unit_texts: list[str]) -> list[str]:
    normalise = lambda value: re.sub(r"\s+", " ", value).strip().casefold()
    found = list(quotes)
    for quote in quotes:
        needle = normalise(quote)
        for text in unit_texts:
            for sentence in re.split(r"(?<=[.!?])\s+", text):
                plain = normalise(sentence)
                if needle and plain and (needle in plain or plain in needle):
                    found.append(sentence)
    return found


def _stated_outcome(model_value: str, quotes: list[str], unit_texts: list[str]) -> str | None:
    """Outcome the source states for an action; a blocked attempt is never left looking successful."""
    text = " ".join(_enclosing_sentences(quotes, unit_texts))
    if _BLOCKED_RE.search(text):
        return "failed"
    if _PARTIAL_RE.search(text):
        return "partial"
    value = model_value.strip().casefold()
    return value if value in {"succeeded", "failed", "partial"} else None


def _technique_stated_for(technique_id: str, action_name: str, quotes: list[str], cited_units: list[str],
                          units: list[SourceUnit], input_kind: str) -> bool:
    """Whether the report gives this technique id for this behaviour.

    Accepted when the id stands in a unit the action cites, or in a unit (such as an ATT&CK
    table row) whose wording substantially overlaps the action. An id that the report lists
    for some other behaviour, or does not contain at all, is not kept on the action.
    """
    pattern = re.compile(rf"(?<![A-Za-z0-9.]){re.escape(technique_id)}(?![0-9.]\d)", re.IGNORECASE)
    if any(pattern.search(text) for text in cited_units):
        return True
    carrying = [unit.text for unit in units if pattern.search(unit.text)]
    if not carrying:
        # Structured STIX keeps ids in external references that are not text units.
        return input_kind == "stix2.1"
    words = lambda value: {word for word in re.findall(r"[a-z0-9]{4,}", value.casefold())}
    wanted = words(action_name + " " + " ".join(quotes))
    if not wanted:
        return False
    return any(len(wanted & words(text)) / len(wanted) >= 0.5 for text in carrying)


def _locate_quote(quote: str, source_ref: str, units: list[SourceUnit]) -> str:
    """The unit a quote is really in, when the model named none or the wrong one.

    Whether a quote is in the source is a fact about the source, not about the locator the
    model typed. The same sentence must verify the same way for an action and for a relation.
    """
    if not quote.strip():
        return source_ref
    named = next((unit for unit in units if unit.id == source_ref), None)
    if named is not None and grade_quote(strip_attack_tags(quote), named.text)["level"] in {"exact", "strong"}:
        return source_ref
    best: tuple[int, str] | None = None
    for unit in units:
        level = grade_quote(strip_attack_tags(quote), unit.text)["level"]
        if level == "exact":
            return unit.id
        if level == "strong" and best is None:
            best = (1, unit.id)
    return best[1] if best else source_ref


def _relation_cue(kind: str, quotes: list[str]) -> str | None:
    """Return which stated-relation wording the verified quotes contain, if any."""
    text = " ".join(quotes)
    if kind == "dependency" and _DEPENDENCY_CUE_RE.search(text):
        return "dependency"
    if _TEMPORAL_CUE_RE.search(text):
        return "temporal"
    if _DEPENDENCY_CUE_RE.search(text):
        return "dependency"
    return None


def _host_match_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _resolve_action_hosts(actions: list[dict[str, Any]], hosts: list[dict[str, Any]], evidence: list[dict[str, Any]]) -> None:
    """Resolve only explicit host names/roles present in action text or its citations."""
    by_id = {host["id"]: host for host in hosts}
    evidence_by_id = {item["id"]: item.get("quote", "") for item in evidence}
    aliases: list[tuple[str, dict[str, Any]]] = []
    for host in hosts:
        for key in ("name", "role"):
            value = host.get(key)
            if isinstance(value, str) and len(_host_match_key(value)) >= 3:
                parts = re.split(r"[^A-Za-z0-9]+", value.strip())
                pattern = r"(?<![A-Za-z0-9])" + r"[\s_-]*".join(map(re.escape, parts)) + r"(?![A-Za-z0-9])"
                aliases.append((pattern, host))
        label = " ".join(str(host.get(key, "")) for key in ("name", "role")).casefold()
        if "domain controller" in label or re.search(r"\bdc\b", label):
            aliases.append((r"(?<![A-Za-z0-9])domain\s+controller(?![A-Za-z0-9])", host))
            aliases.append((r"(?<![A-Za-z0-9])DC(?![A-Za-z0-9])", host))
    for action in actions:
        current = action.get("target_host_ref")
        if current in by_id:
            continue
        fragments = [str(action.get(key, "")) for key in ("name", "description", "precondition", "initial_access")]
        fragments.extend(evidence_by_id.get(ref, "") for ref in action.get("evidence_refs", []))
        text = " ".join(fragments)
        candidates: dict[str, dict[str, Any]] = {}
        for pattern, host in aliases:
            if re.search(pattern, text, re.IGNORECASE):
                candidates[host["id"]] = host
        if len(candidates) == 1:
            action["target_host_ref"] = next(iter(candidates))


class AnalysisError(ValueError):
    """Raised when the model response cannot be safely converted into an IR."""


def _normalise_tactic(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def _validated_attack_technique(value: Any) -> tuple[str | None, dict[str, Any] | None]:
    raw = _string(value)
    if not raw or not _ATTACK_TECHNIQUE_RE.fullmatch(raw):
        return None, None
    technique_id = raw.upper()
    technique = lookup_attack_technique(technique_id)
    if technique is None:
        return None, None
    return technique_id, technique


def _validated_attack_tactic(value: Any, technique: dict[str, Any] | None) -> str | None:
    if isinstance(value, list):
        # Models often return ["TA0001"]; keep the first entry that validates.
        for entry in value:
            tactic = _validated_attack_tactic(entry, technique)
            if tactic:
                return tactic
        return None
    raw = _string(value)
    if not raw or _ATTACK_TECHNIQUE_RE.fullmatch(raw):
        return None
    if _ATTACK_TACTIC_ID_RE.fullmatch(raw):
        tactic = _KNOWN_TACTIC_IDS.get(raw.upper())
        output = raw.upper()
    else:
        tactic = _normalise_tactic(raw)
        output = tactic
    if tactic not in _KNOWN_TACTICS:
        return None
    if technique is not None:
        technique_tactics = {
            _normalise_tactic(value)
            for value in technique.get("tactics", [])
            if isinstance(value, str)
        }
        if tactic not in technique_tactics:
            return None
    return output


def _valid_ipv4(value: str) -> bool:
    octets = re.split(r"\[\.\]|\.", value)
    return len(octets) == 4 and all(part.isdigit() and 0 <= int(part) <= 255 for part in octets)


def _near_ioc_context(text: str, start: int, end: int) -> bool:
    context = text[max(0, start - 90):min(len(text), end + 60)]
    return bool(_IOC_CONTEXT_RE.search(context))


def _is_source_reference_url(text: str, start: int) -> bool:
    """True when the value on this line is labelled as the report's own provenance."""
    line_start = text.rfind("\n", 0, start) + 1
    prefix = text[line_start:start]
    if _PROVENANCE_LABEL_RE.search(prefix):
        return True
    return bool(_PROVENANCE_LINK_LABEL_RE.search(prefix) and _PROVENANCE_LABEL_RE.search(text[:line_start]))


_METADATA_LINE_RE = re.compile(r"^[\s>*•-]*[A-Za-z][\w /()-]{1,40}:\s+\S", re.MULTILINE)
_PROVENANCE_KEY_RE = re.compile(
    r"^[\s>*•-]*(?:source|publisher|published|licen[sc]e|retrieved|accessed|author|document|report)\b[^:\n]{0,40}:",
    re.IGNORECASE | re.MULTILINE)


def _is_provenance_block(text: str) -> bool:
    """A key: value header describing the document itself (publisher, URL, licence, checksum)."""
    return len(_METADATA_LINE_RE.findall(text)) >= 3 and bool(_PROVENANCE_KEY_RE.search(text))


def _is_source_checksum(text: str, start: int) -> bool:
    """A checksum labelled as belonging to the source document is provenance, not an IOC."""
    line_start = text.rfind("\n", 0, start) + 1
    return bool(_PROVENANCE_HASH_LABEL_RE.search(text[line_start:start]))


def _extract_literal_indicators(units: list[SourceUnit]) -> list[dict[str, Any]]:
    """Find IOC-shaped values in source units without asserting their role or maliciousness."""
    found: dict[tuple[str, str], dict[str, Any]] = {}

    def add(kind: str, value: str, quote: str, unit: SourceUnit) -> None:
        key = (kind, value.casefold())
        item = found.setdefault(key, {
            "id": f"indicator-{len(found) + 1}", "type": kind, "value": value,
            "source": "program", "epistemic_status": "supported", "evidence_refs": [],
        })
        item["_citations"] = item.get("_citations", []) + [{"quote": quote, "source_ref": unit.id}]

    for unit in units:
        text = unit.text
        # In a document-metadata header only defanged values can be indicators.
        provenance_block = _is_provenance_block(text)
        url_matches = []
        for match in _URL_RE.finditer(text):
            raw = match.group(0).rstrip(".,;:!?)]}")
            end = match.start() + len(raw)
            if not raw or _is_source_reference_url(text, match.start()):
                continue
            url_matches.append((match.start(), end))
            if provenance_block and not (raw.casefold().startswith("hxxp") or "[.]" in raw):
                continue
            if raw.casefold().startswith("hxxp") or "[.]" in raw or _near_ioc_context(text, match.start(), end):
                add("url", raw, raw, unit)

        for match in _IPV4_RE.finditer(text):
            value = match.group(0)
            if _valid_ipv4(value) and ("[.]" in value or _near_ioc_context(text, match.start(), match.end())):
                add("ip", value, value, unit)

        for match in _DOMAIN_RE.finditer(text):
            value = match.group(0).rstrip(".")
            normalised_host = value.replace("[.]", ".").translate(str.maketrans({"‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-"}))
            labels = normalised_host.lstrip("*.").split(".")
            in_url = any(start <= match.start() < end for start, end in url_matches)
            is_ipv4_fragment = bool(labels) and all(label.isdigit() for label in labels)
            is_technique_id = bool(re.fullmatch(r"T\d{4}(?:\.\d{3})?", value, re.IGNORECASE))
            is_file_extension = bool(labels and labels[-1].casefold() in {
                "txt", "text", "ps1", "zip", "exe", "dll", "sys", "json", "log", "dat", "pdf", "doc", "docx",
            })
            if _is_source_reference_url(text, match.start()) or is_ipv4_fragment or is_technique_id or is_file_extension:
                continue
            if provenance_block and "[.]" not in value:
                continue
            if "[.]" in value or in_url or _near_ioc_context(text, match.start(), match.end()):
                add("domain", value, value, unit)

        for match in _HASH_RE.finditer(text):
            value = match.group(0)
            # A checksum of the report/source document itself is provenance, not an IOC.
            if provenance_block or _is_source_checksum(text, match.start()):
                continue
            add("hash", value, value, unit)

        for match in _CVE_RE.finditer(text):
            quote = match.group(0)
            value = re.sub(r"\s+", "", quote).upper()
            add("cve", value, quote, unit)

    return list(found.values())


def _extract_literal_commands(units: list[SourceUnit]) -> list[dict[str, Any]]:
    """Extract explicit PowerShell/cmd invocations; narrative mentions alone do not qualify."""
    found: dict[tuple[str, str], dict[str, Any]] = {}
    non_command_starts = {"command", "commands", "execution", "script", "scripts", "can", "was", "is", "to", "used"}

    for unit in units:
        lines = unit.text.splitlines()
        for line_index, line in enumerate(lines):
            for match in _SHELL_COMMAND_RE.finditer(line):
                interpreter_raw = match.group("interpreter")
                args = match.group("args").strip().rstrip("`.,;:")
                first_arg = args.split(maxsplit=1)[0].casefold() if args else ""
                if first_arg in non_command_starts or not _COMMAND_ARG_RE.match(args):
                    continue
                indent = len(line) - len(line.lstrip())
                parts = [f"{interpreter_raw} {args}"]
                for continuation in lines[line_index + 1:]:
                    if not continuation.strip():
                        break
                    continuation_indent = len(continuation) - len(continuation.lstrip())
                    if continuation_indent < max(indent, 1) or _SHELL_COMMAND_RE.match(continuation.strip()):
                        break
                    nested_command = _SHELL_COMMAND_RE.search(continuation)
                    if nested_command:
                        prefix = continuation[:nested_command.start()].strip()
                        if prefix:
                            parts.append(prefix)
                        break
                    parts.append(continuation.strip())
                raw_command = re.sub(r"\s+", " ", " ".join(parts)).strip().rstrip("`.,;:")
                command = html.unescape(raw_command)
                interpreter = "cmd" if interpreter_raw.casefold().startswith("cmd") else "powershell"
                key = (interpreter, command.casefold())
                item = found.setdefault(key, {
                    "id": f"command-{len(found) + 1}", "interpreter": interpreter, "command": command,
                    "source": "program", "epistemic_status": "supported", "evidence_refs": [],
                })
                item["_citations"] = item.get("_citations", []) + [{"quote": raw_command, "source_ref": unit.id}]

    return list(found.values())


def analyze_source(
    *, input_kind: str, content: str, source_name: str | None,
    units: list[SourceUnit], parsed_source: dict[str, Any] | None,
    method: str, name: str,
) -> dict[str, Any]:
    if method not in METHODS:
        raise AnalysisError(f"Unsupported analysis method: {method!r}.")
    source_payload = [{"source_ref": unit.id, "locator": unit.locator, "text": unit.text} for unit in units]
    if method == "single_pass":
        result = _call_json(
            _messages("Analyze the report", source_payload),
            purpose="cti_analysis_single_pass",
        )
    else:
        extracted = _call_json(
            _messages("Extract candidate facts with verbatim quotes and source_ref values", source_payload, extraction=True),
            purpose="cti_analysis_extract",
        )
        draft = _call_json(
            _messages("Build a Scenario IR analysis using only the cited extracted facts", source_payload, extracted=extracted),
            purpose="cti_analysis_synthesis",
        )
        if method == "staged_review":
            result = _call_json(
                _messages("Review and correct this draft for unsupported claims, citation accuracy, and relation semantics", source_payload, extracted=extracted, draft=draft, review=True),
                purpose="cti_analysis_review",
            )
        else:
            result = draft
    _merge_target_context(result, source_payload)
    _merge_relations(result, source_payload)
    return _build_ir(
        result, input_kind=input_kind, content=content, source_name=source_name,
        units=units, parsed_source=parsed_source, method=method, name=name,
    )


_CONTEXT_RULES = (
    "Return only a JSON object {\"hosts\":[],\"services\":[],\"artifacts\":[],\"action_hosts\":[]}. Use only facts stated in the "
    "source units; never invent hosts, products, versions, ports or CVE ids. Every host, service and artifact needs "
    "evidence:[{quote,source_ref}] where quote is an exact, unaltered substring of the source unit and source_ref is that unit's "
    "source_ref, and an epistemic_status of 'supported' (explicitly stated) or 'inferred'. "
    "hosts: one entry for each distinct machine, system, database or explicitly described group of machines that the listed "
    "attacker actions targeted, used or moved through. Never merge differently named or differently described machines and "
    "never add a catch-all entry for unidentified hosts. Fields: id (h1, h2, ...; never 'unknown'), name (hostname or label if "
    "given), role (the report's words), and os, os_version, network_placement only when stated. "
    "services: each product, application, protocol service or security product on those machines that an action exploits, logs "
    "in to, queries, disables or otherwise depends on. A service is software or a named protocol service (for example RDP, "
    "SMB, SSH) present on a target machine; a description of how traffic flowed ('encrypted communication channels', "
    "'standard web protocols', 'normal network traffic') is not a service and must not be listed. When the report says an "
    "action queried or accessed databases, list the database as a service of the machine that hosts it, named in the "
    "report's words. Fields: id (s1, ...), name (the report's words; a vulnerability nickname "
    "or CVE id is not a name: name the affected product), host_ref (a host id above), and version, port (integer), protocol "
    "(tcp/udp), cve (array of CVE ids) only when the report states them. "
    "artifacts: each tool, malware family, script, file, scheduled task or account the report names as used, created or "
    "dropped. Fields: id, name, type (tool, malware, file, script, account or other). "
    "action_hosts: for each listed action {action_id, target_host_ref, source_host_ref}. target_host_ref is the host id the "
    "action took effect on (for lateral movement or a remote query, the destination), or 'unknown' when the report does not "
    "identify the machine. source_host_ref is the host id the action was launched from, only when the report states it."
)


def _merge_target_context(result: dict[str, Any], source_payload: list[dict[str, Any]]) -> None:
    """Second, focused pass for hosts/services/artifacts and each action's machines.

    Asked together with the whole flow, models routinely return these arrays empty even when
    the report names every machine and product. A dedicated question fixes that at source.
    If the pass fails or returns nothing usable, the first pass's context is kept as it was.
    """
    actions = [{"action_id": item.get("id"), "name": item.get("name"), "description": item.get("description", "")}
               for item in result.get("actions") or [] if isinstance(item, dict)
               and str(item.get("actor") or "attacker").strip().casefold() not in _NON_ATTACKER_ACTORS]
    if not actions:
        return
    messages = [
        {"role": "system", "content": "You are a careful cyber threat intelligence analyst producing provisional, evidence-grounded data."},
        {"role": "user", "content": json.dumps({
            "task": "Identify the target environment of these attacker actions",
            "rules": _CONTEXT_RULES, "actions": actions, "source_units": source_payload,
        }, ensure_ascii=False)},
    ]
    try:
        context = _call_json(messages, purpose="cti_analysis_context")
    except AnalysisError:
        return
    hosts = context.get("hosts")
    if not isinstance(hosts, list) or not all(isinstance(item, dict) for item in hosts):
        return
    def objects(key: str) -> list[dict[str, Any]]:
        value = context.get(key)
        return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    previous = result.get("target_context") if isinstance(result.get("target_context"), dict) else {}
    result["target_context"] = {"hosts": hosts, "services": objects("services") or previous.get("services") or []}
    if objects("artifacts"):
        result["artifacts"] = objects("artifacts")
    placement = {str(item.get("action_id")): item for item in objects("action_hosts")}
    for action in result.get("actions") or []:
        entry = placement.get(str(action.get("id"))) if isinstance(action, dict) else None
        # The first pass named hosts by its own ids, which the new host list replaces.
        action["target_host_ref"] = (entry or {}).get("target_host_ref") or "unknown"
        action.pop("source_host_ref", None)
        if entry and entry.get("source_host_ref"):
            action["source_host_ref"] = entry["source_host_ref"]


_RELATION_RULES = (
    "Return only a JSON object {\"relations\":[{id, from_action, to_action, kind, epistemic_status, rationale, "
    "evidence:[{quote, source_ref}]}]}. Connect the listed attacker actions the way the source describes; use only the listed "
    "action ids. Work in two steps. "
    "Step 1 - stated links: for each action, find the source wording that says what it came after or what it relied on. Such "
    "wording is usually in the sentence about the later action and refers back to the earlier one: 'then', 'after ...', "
    "'following ...', 'once ...', 'upon ...', 'subsequently', 'next', 'finally', 'as a result of ...', 'using the newly created "
    "account', 'with these credentials', 'leveraged ... to', 'by exploiting ...', 'after gaining ...', 'when executed, X ...'. "
    "Add an edge from the earlier action to the later one with epistemic_status 'supported' and one evidence quote that is an "
    "exact, unaltered substring of a source unit and includes those linking words themselves (quote the whole clause, not only "
    "the part describing the action). kind is 'dependency' when the later action uses something the earlier one produced "
    "(access, a foothold, an account, credentials, a downloaded tool or file) and rationale names that thing; kind is "
    "'temporal' when the wording gives only the order. Where the source says two events were separate or independent, do not "
    "make one depend on the other. "
    "Step 2 - narrative order: only for an action that step 1 left unconnected, add one edge from the action narrated just "
    "before it, with kind 'temporal', epistemic_status 'inferred', no evidence, and rationale 'narrative order only'. "
    "The edges must form a directed acyclic graph with at most one edge per ordered pair. Never alter a quote and never add "
    "ATT&CK ids or bracketed notes to it; the program checks every quote against the source and rejects edges whose quote "
    "does not state the link."
)


def _merge_relations(result: dict[str, Any], source_payload: list[dict[str, Any]]) -> None:
    """Focused pass that connects the final action list and cites the wording stating each link.

    In the combined pass models mostly return edges without evidence, or cite a sentence that
    only describes one endpoint. If this pass fails, the first pass's relations are kept.
    """
    actions = [{"id": item.get("id"), "name": item.get("name"),
                "evidence": [entry.get("quote") for entry in item.get("evidence") or [] if isinstance(entry, dict)]}
               for item in result.get("actions") or [] if isinstance(item, dict)
               and str(item.get("actor") or "attacker").strip().casefold() not in _NON_ATTACKER_ACTORS]
    if len(actions) < 2:
        return
    messages = [
        {"role": "system", "content": "You are a careful cyber threat intelligence analyst producing provisional, evidence-grounded data."},
        {"role": "user", "content": json.dumps({
            "task": "State how these attacker actions are ordered and which depend on which",
            "rules": _RELATION_RULES, "actions": actions, "source_units": source_payload,
        }, ensure_ascii=False)},
    ]
    try:
        answer = _call_json(messages, purpose="cti_analysis_relations")
    except AnalysisError:
        return
    relations = answer.get("relations")
    if isinstance(relations, list) and relations and all(isinstance(item, dict) for item in relations):
        result["relations"] = relations


def _call_json(messages: list[dict[str, str]], *, purpose: str) -> dict[str, Any]:
    # The structured IR echoes verbatim quotes back, so a long report needs a larger
    # output budget or the JSON is truncated and unparseable. Scale with the input size
    # (rough 4 chars/token), with a floor and a conservative ceiling kept cheap on the
    # mini model and well under the budget caps.
    input_chars = sum(len(message.get("content", "")) for message in messages)
    max_out = max(3000, min(12000, (input_chars // 4) * 4))
    response = complete(
        messages,
        purpose=purpose,
        response_format=_PROMPT_FORMAT,
        max_output_tokens=max_out,
        temperature=0,
        agent="cti",
    )
    text = response.get("text", "")
    try:
        result = json.loads(text)
    except (TypeError, json.JSONDecodeError) as exc:
        excerpt = str(text)[:300]
        raise AnalysisError(f"LLM returned invalid JSON; response was retained for diagnosis: {excerpt!r}.") from exc
    if not isinstance(result, dict):
        raise AnalysisError("LLM response must be a JSON object.")
    return result


def _messages(task: str, source_payload: list[dict[str, Any]], *, extracted: dict[str, Any] | None = None,
              draft: dict[str, Any] | None = None, extraction: bool = False, review: bool = False) -> list[dict[str, str]]:
    rules = (
        "Return only a JSON object. Use only facts stated in the source. Never invent real hosts, products, versions, CVEs, "
        "accounts, network details, or preconditions. For each claim include an evidence array with objects containing "
        "a verbatim quote and the exact source_ref from the supplied source units. Use epistemic_status with these distinct meanings: "
        "'supported' means explicitly stated and every citation is exact or strong; 'inferred' means the source does not state the "
        "claim verbatim but it is a reasonable, source-grounded inference needed to connect the sequence; 'absent' means the source "
        "does not provide the information and the user must supply it; 'insufficient' means one or more supplied citations fail to "
        "match the source strongly and a human must check the original. Never use 'insufficient' to mean the source omits a fact, "
        "and never use 'absent' for a reasonable inferred step. Each action, relation, host, service, and artifact must have an "
        "epistemic_status. Relations must use kind 'temporal' for stated order and 'dependency' when a later action uses or requires "
        "an earlier action's result; order alone is temporal, not dependency. Dependency examples include wording such as 'using the "
        "newly created account', 'with the credentials', or 'leveraged the [account/tool/session] to [perform the next action]': "
        "link the action that created/obtained that prerequisite to the action that used it. Do not create an unsupported relation edge; "
        "if the edge is a reasonable inference from the source but has no direct relation quote, mark that edge 'inferred'. "
        "Relations must form a directed acyclic graph (DAG): no self edges and no cycles such as a6->a8->a9->a6. "
        "For every action, fill target_host_ref with the id of the host entry it took effect on; use 'unknown' when the source "
        "does not identify the machine."
    )
    if extraction:
        rules += " Return {\"observations\":[{\"claim\":string,\"quote\":string,\"source_ref\":string,\"epistemic_status\":string}]}"
    else:
        rules += (
            " Return JSON with arrays actions, relations, artifacts, and target_context {hosts, services}. "
            "Each item may contain evidence:[{quote,source_ref}]. Actions need id,name,target_host_ref; relations need id,from_action,to_action,kind; "
            "hosts need id,role; services need id,name. Include only information found in the report. "
            "ACTIONS: an action is something the threat actor did. Give every action an occurrence field: 'performed' when the "
            "report says it happened in this incident, 'capability' when the report only says what a tool, web shell or malware "
            "can do or is designed to do ('can run commands that ...', 'is able to', 'designed to'). List each capability the "
            "report enumerates as its own action; never present a capability as something that happened. Keep distinct "
            "operations as distinct actions (for example authenticating to a web shell, and each command it then accepts). In "
            "Give every action an outcome field: 'succeeded', 'failed' (the report says the attempt was stopped, blocked or "
            "unsuccessful), 'partial' (the report says only part of it succeeded) or 'unknown'. In "
            "name and description keep each value attached to the attribute the report attaches it to: do not move a value "
            "from one attribute to another or apply it to more attributes than the report does. Give every action an actor field: 'attacker' for the threat "
            "actor, 'defender' for the victim organisation, responders, vendors or investigators (detecting, patching, blocking, "
            "notifying, investigating), 'other' otherwise. Name it with the report's own wording for that behaviour, not "
            "with a tactic or category label. Do not create actions for what a defender or analyst observed, assessed or detected, "
            "for a description of what a file or tool contains, or for a restatement of an earlier action's effect; cite such "
            "sentences as additional evidence of the attacker action they describe. One behaviour is one action even if the report "
            "mentions it more than once (for example 'exploited CVE-X' and 'SQL injection against the application' describing the "
            "same exploitation). "
            "HOSTS: create one host entry for each distinct machine or explicitly described group of machines that the report "
            "says was targeted or used; never merge differently named or differently described machines into one entry, and never "
            "create a catch-all entry for unidentified hosts. Give each host a short id such as h1, a name when the report gives a "
            "hostname or label, a role in the report's words, os/os_version/network_placement only when stated, and evidence quoting "
            "the words that mention that machine. The ids 'unknown', 'unspecified' and 'none' are reserved and must not be used as "
            "host ids; an action whose machine the report does not identify gets target_host_ref 'unknown' and no host entry. "
            "target_host_ref is the machine on which the action took effect (for lateral movement, the destination). "
            "When the report states which machine an action was launched from (for example 'from the web server, connected to "
            "the database'), also set source_host_ref to that host's id; omit it otherwise. "
            "SERVICES: list each product, application, protocol service or security product on a target machine that an action "
            "exploits, logs in to, disables or otherwise depends on, with name in the report's words, host_ref, and version, "
            "port (integer), protocol, and cve (array) only when the report states them, plus evidence. A vulnerability nickname or "
            "CVE id is not a service name: name the affected product and put the CVE id in cve. "
            "ARTIFACTS: list each tool, malware family, script, file, scheduled task or account that the report names as used, "
            "created or dropped, with name, type (tool, malware, file, script, account or other) and evidence. "
            "RELATIONS: add an edge only between two actions of this analysis. When the report states the order or the dependency, "
            "the relation's evidence quote must be the exact words that state it, including the ordering or enabling words themselves "
            "(for example 'then', 'after', 'following', 'once', 'upon', 'using the newly created account', 'by exploiting', "
            "'as a result of', 'leverage these credentials', 'after gaining'). For every edge, first look for that wording: it is "
            "usually in the sentence about the later action, which refers back to the earlier one. Quote it and mark the edge "
            "'supported'. Only when the report has no such wording and you connect two actions merely because it narrates them one "
            "after the other, give the edge epistemic_status 'inferred' and no evidence. Prefer "
            "'dependency' when the later action uses something the earlier one produced (access, an account, credentials, a downloaded "
            "tool or file), and say what in rationale. "
            "When the report states or lists a MITRE ATT&CK technique for an action (for example a TTP/MITRE ATT&CK table), set "
            "attack_technique to only the exact T#### or T####.### id. attack_tactic may contain only a stated tactic name/category "
            "or TA#### tactic id, as a single string; never put a technique name or T#### technique id in attack_tactic. Put ATT&CK ids only in these "
            "two fields. Never insert an id, a tactic name, or any bracketed annotation into an evidence quote: every evidence quote "
            "must stay an exact, unaltered, character-for-character substring of the source text. Do not guess or fill an ATT&CK id "
            "the report does not give. The program separately extracts IOC-like values into indicators[] and literal PowerShell/cmd "
            "invocations into commands[]; do not fabricate entries for those arrays."
        )
    if review:
        rules += " Keep valid draft claims, remove unsupported factual detail only by marking it insufficient and retaining its evidence. Return the corrected full analysis object."
    user_payload: dict[str, Any] = {"task": task, "rules": rules, "source_units": source_payload}
    if extracted is not None:
        user_payload["extracted_facts"] = extracted
    if draft is not None:
        user_payload["draft"] = draft
    return [
        {"role": "system", "content": "You are a careful cyber threat intelligence analyst producing provisional, evidence-grounded data."},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]


def _build_ir(result: dict[str, Any], *, input_kind: str, content: str, source_name: str | None,
              units: list[SourceUnit], parsed_source: dict[str, Any] | None, method: str, name: str) -> dict[str, Any]:
    evidence: list[dict[str, Any]] = []
    evidence_cache: dict[tuple[str, str], str] = {}
    unsupported = 0

    def attach(item: dict[str, Any]) -> list[str]:
        nonlocal unsupported
        citations = item.get("evidence", [])
        refs = item.get("evidence_refs", [])
        if citations is None:
            citations = []
        if refs is None:
            refs = []
        if not isinstance(citations, list) or not isinstance(refs, list):
            raise AnalysisError("Each claim's evidence and evidence_refs must be arrays.")
        pairs: list[tuple[str, str]] = []
        for citation in citations:
            if not isinstance(citation, dict):
                raise AnalysisError("Evidence entries must be objects with quote and source_ref.")
            quote = citation.get("quote", "")
            source_ref = citation.get("source_ref", "")
            if not isinstance(quote, str) or not isinstance(source_ref, str):
                raise AnalysisError("Evidence quote and source_ref must be strings.")
            pairs.append((quote, source_ref))
        unit_by_id = {unit.id: unit for unit in units}
        for ref in refs:
            if not isinstance(ref, str):
                raise AnalysisError("evidence_refs entries must be strings.")
            unit = unit_by_id.get(ref)
            pairs.append((unit.text if unit else "", ref))

        item_refs: list[str] = []
        for quote, source_ref in pairs:
            source_ref = _locate_quote(quote, source_ref, units)
            cache_key = (quote, source_ref)
            evidence_id = evidence_cache.get(cache_key)
            if evidence_id is None:
                evidence_id = f"evidence-{len(evidence) + 1}"
                evidence_cache[cache_key] = evidence_id
                evidence.append(evidence_record(evidence_id, quote, source_ref, units, parsed_source))
            item_refs.append(evidence_id)
        item_refs = list(dict.fromkeys(item_refs))
        if not item_refs or any(not _ref_strong(ref) for ref in item_refs):
            unsupported += 1
        return item_refs

    def normalize_status(item: dict[str, Any]) -> str:
        status = item.get("epistemic_status")
        if status not in _STATUSES:
            status = "insufficient"
        item["epistemic_status"] = status
        return status

    def _ref_strong(ref: str) -> bool:
        rec = next((e for e in evidence if e["id"] == ref), None)
        return bool(rec and rec.get("quote_match") in {"exact", "strong"})

    def settle_status(item: dict[str, Any], refs: list[str]) -> str:
        """Deterministic epistemic rule, overriding the model's conservatism.

        - A failed/weak citation always means 'insufficient', regardless of the
          model's claim label; a human must inspect the source.
        - With no weak citations, 'inferred' and 'absent' retain their distinct
          meanings from the prompt.
        - 'supported' requires every citation to be exact or strong.
        """
        status = normalize_status(item)
        if refs and any(not _ref_strong(ref) for ref in refs):
            return "insufficient"
        if status in ("inferred", "absent"):
            return status
        if refs and all(_ref_strong(ref) for ref in refs):
            return "supported"
        return "insufficient"

    all_actions_raw = _array(result, "actions")
    # The flow is the attacker's. What defenders did is kept out of it (and reported in quality)
    # rather than silently presented as attack steps.
    actions_raw = [raw for raw in all_actions_raw
                   if str(raw.get("actor") or "attacker").strip().casefold() not in _NON_ATTACKER_ACTORS]
    excluded_actions = [{"id": _string(raw.get("id")) or "", "name": _string(raw.get("name")) or "",
                         "actor": str(raw.get("actor")).strip().casefold()}
                        for raw in all_actions_raw if raw not in actions_raw]
    excluded_action_ids = {item["id"] for item in excluded_actions if item["id"]}
    actions: list[dict[str, Any]] = []
    action_ids: set[str] = set()
    action_id_map: dict[str, str] = {}
    misplaced_techniques: list[dict[str, str]] = []
    for index, raw in enumerate(actions_raw, start=1):
        item = dict(raw)
        action_id = _unique_id(item.get("id"), f"action-{index}", action_ids)
        action_ids.add(action_id)
        model_action_id = _string(item.get("id"))
        if model_action_id:
            action_id_map.setdefault(model_action_id, action_id)
        action = {"id": action_id, "name": _required_text(item, "name"), "source": "llm"}
        for key in ("description", "precondition", "initial_access"):
            if isinstance(item.get(key), str) and item[key].strip():
                action[key] = item[key].strip()
        action["target_host_ref"] = _string(item.get("target_host_ref")) or "unknown"
        technique_id, technique_info = _validated_attack_technique(item.get("attack_technique"))
        if technique_id:
            action["attack_technique"] = technique_id
        tactic = _validated_attack_tactic(item.get("attack_tactic"), technique_info)
        if tactic:
            action["attack_tactic"] = tactic
        _refs = attach(item)
        action["evidence_refs"] = _refs
        action["epistemic_status"] = settle_status(item, _refs)
        cited_units = [unit.text for unit in units
                       if any(unit.locator == rec["locator"] for rec in evidence if rec["id"] in _refs)]
        cited_quotes = [rec["quote"] for rec in evidence if rec["id"] in _refs]
        if technique_id and not _technique_stated_for(technique_id, action["name"], cited_quotes, cited_units, units, input_kind):
            # The id is in the report, but next to a different behaviour (or not in it at all).
            misplaced_techniques.append({"action": action_id, "technique": technique_id})
            action.pop("attack_technique", None)
            action.pop("attack_tactic", None)
        outcome = _stated_outcome(str(item.get("outcome") or ""), cited_quotes, cited_units)
        if outcome:
            action["outcome"] = outcome
        if str(item.get("occurrence") or "").strip().casefold() == "capability":
            # What a tool can do is not an event of this incident. Keep the step, say what it is.
            action["occurrence"] = "capability"
            action["source_certainty"] = "capability"
            action["epistemic_reason"] = "原文描述的是工具／惡意程式具備的能力，沒有說這個動作在本事件中實際發生。"
        elif action["epistemic_status"] == "supported":
            cited = [rec for rec in evidence if rec["id"] in _refs]
            unit_texts = [unit.text for unit in units if any(unit.locator == rec["locator"] for rec in cited)]
            if _hedged_statement([rec["quote"] for rec in cited], unit_texts):
                # The report says this, but says it is not sure. Keep that visible.
                action["source_certainty"] = "hedged"
                action["epistemic_reason"] = "原文以不確定語氣陳述（如 may have／appears to／we believe），不是已確認的事實。"
        actions.append(action)

    relations_raw = _array(result, "relations")
    relations: list[dict[str, Any]] = []
    relation_ids: set[str] = set()
    relation_graph: dict[str, set[str]] = {}

    def creates_cycle(from_action: str, to_action: str) -> bool:
        if from_action == to_action:
            return True
        pending = [to_action]
        visited: set[str] = set()
        while pending:
            action_id = pending.pop()
            if action_id == from_action:
                return True
            if action_id in visited:
                continue
            visited.add(action_id)
            pending.extend(relation_graph.get(action_id, set()))
        return False

    for index, raw in enumerate(relations_raw, start=1):
        item = dict(raw)
        if {_string(item.get("from_action")), _string(item.get("to_action"))} & excluded_action_ids:
            continue  # an edge to a step that is not part of the attack flow
        kind = item.get("kind")
        coerced_kind = kind not in _RELATION_KINDS
        if coerced_kind:
            # One malformed relation must not sink the whole analysis: fall back to the
            # weaker "temporal" reading; the epistemic status below is forced to inferred.
            kind = "temporal"
        relation_id = _unique_id(item.get("id"), f"relation-{index}", relation_ids)
        relation_ids.add(relation_id)
        relation = {
            "id": relation_id,
            "from_action": _required_text(item, "from_action"),
            "to_action": _required_text(item, "to_action"),
            "kind": kind,
            "source": "llm",
        }
        relation["from_action"] = action_id_map.get(relation["from_action"], relation["from_action"])
        relation["to_action"] = action_id_map.get(relation["to_action"], relation["to_action"])
        invalid_endpoints = relation["from_action"] not in action_ids or relation["to_action"] not in action_ids
        if isinstance(item.get("rationale"), str) and item["rationale"].strip():
            relation["rationale"] = item["rationale"].strip()
        _refs = attach(item)
        relation["evidence_refs"] = _refs
        # A relation with no citation can still bridge source-grounded steps,
        # but it must remain explicitly inferred rather than supported.
        relation["epistemic_status"] = "inferred" if not _refs else settle_status(item, _refs)
        if coerced_kind:
            relation["epistemic_status"] = "inferred"
        if relation["epistemic_status"] == "supported":
            quotes = [rec["quote"] for rec in evidence if rec["id"] in _refs]
            cue = _relation_cue(kind, quotes)
            if cue is None:
                # The quote exists in the source but does not state order or enablement.
                relation["epistemic_status"] = "inferred"
                relation["epistemic_reason"] = (
                    "引句存在於原文，但沒有陳述先後或相依的字眼；此關係是依敘事順序推論，需人工確認。"
                )
            elif kind == "dependency" and cue == "temporal":
                relation["epistemic_status"] = "inferred"
                relation["epistemic_reason"] = (
                    "引句只陳述先後順序，沒有陳述後一步使用前一步的結果；相依屬推論，需人工確認。"
                )
        if invalid_endpoints:
            relation["epistemic_status"] = "insufficient"
        elif creates_cycle(relation["from_action"], relation["to_action"]):
            unsupported += 1
            continue
        else:
            relation_graph.setdefault(relation["from_action"], set()).add(relation["to_action"])
        relations.append(relation)

    target = result.get("target_context") or {}
    if not isinstance(target, dict):
        raise AnalysisError("target_context must be an object containing hosts and services arrays.")
    hosts_raw = _array(target, "hosts")
    services_raw = _array(target, "services")
    hosts: list[dict[str, Any]] = []
    services: list[dict[str, Any]] = []
    host_id_map: dict[str, str] = {}
    dropped_placeholder_hosts = 0
    for index, raw in enumerate(hosts_raw, start=1):
        item = dict(raw)
        model_host_id = _string(item.get("id"))
        if model_host_id and model_host_id.casefold() in _RESERVED_HOST_IDS:
            # A catch-all "unknown" entry is not a machine the source identified.
            dropped_placeholder_hosts += 1
            unsupported += 1
            continue
        host: dict[str, Any] = {
            "id": _unique_id(item.get("id"), f"host-{index}", {x["id"] for x in hosts}),
            "role": _string(item.get("role")) or "target",
            "source": "llm",
        }
        if isinstance(item.get("name"), str) and item["name"].strip():
            host["name"] = item["name"].strip()
        for key in ("os", "os_version", "network_placement"):
            if isinstance(item.get(key), str) and item[key].strip():
                host[key] = item[key].strip()
        _refs = attach(item)
        host["evidence_refs"] = _refs
        host["epistemic_status"] = settle_status(item, _refs)
        hosts.append(host)
        if model_host_id:
            host_id_map.setdefault(model_host_id, host["id"])
    known_host_ids = {host["id"] for host in hosts}
    for action, raw in zip(actions, actions_raw):
        origin = host_id_map.get(_string(raw.get("source_host_ref")) or "", _string(raw.get("source_host_ref")))
        if origin in known_host_ids:
            action["source_host_ref"] = origin
    for action in actions:
        ref = host_id_map.get(action["target_host_ref"], action["target_host_ref"])
        # A reference to no host entry carries no information; keep the explicit marker.
        action["target_host_ref"] = ref if ref in known_host_ids else "unknown"
    _resolve_action_hosts(actions, hosts, evidence)
    dropped_non_software: list[str] = []
    for index, raw in enumerate(services_raw, start=1):
        item = dict(raw)
        if is_communication_description(item.get("name")):
            # A description of the attacker's traffic, not software to install on a host.
            dropped_non_software.append(str(item.get("name")).strip())
            continue
        service: dict[str, Any] = {
            "id": _unique_id(item.get("id"), f"service-{index}", {x["id"] for x in services}),
            "name": _string(item.get("name")) or "Unspecified service (absent)",
            "source": "llm",
        }
        for key in ("version", "cpe", "catalogue_component"):
            if isinstance(item.get(key), str) and item[key].strip():
                service[key] = item[key].strip()
        if isinstance(item.get("cve"), list):
            service["cve"] = [v.upper() for v in item["cve"] if isinstance(v, str) and _CVE_RE.fullmatch(v.strip())]
        elif isinstance(item.get("cve"), str) and _CVE_RE.fullmatch(item["cve"].strip()):
            service["cve"] = [item["cve"].strip().upper()]
        service_host = host_id_map.get(_string(item.get("host_ref")) or "", _string(item.get("host_ref")))
        if service_host in known_host_ids:
            service["host_ref"] = service_host
        try:
            port = int(item.get("port"))
        except (TypeError, ValueError):
            port = None
        if port is not None and 1 <= port <= 65535:
            service["port"] = port
            if _string(item.get("protocol")) and item["protocol"].strip().casefold() in {"tcp", "udp"}:
                service["protocol"] = item["protocol"].strip().casefold()
        _refs = attach(item)
        service["evidence_refs"] = _refs
        service["epistemic_status"] = settle_status(item, _refs)
        services.append(service)

    # A CVE the source names in the same sentence as a recorded product belongs to that product.
    sentences = [sentence for unit in units for sentence in re.split(r"(?<=[.!?])\s+|\n+", unit.text)]
    for service in services:
        name = str(service.get("name") or "").casefold().strip()
        if len(name) < 4:
            continue
        found = [re.sub(r"\s+", "", match).upper() for sentence in sentences if name in sentence.casefold()
                 for match in _CVE_RE.findall(sentence)]
        merged = list(dict.fromkeys([*service.get("cve", []), *found]))
        if merged != service.get("cve", []):
            service["cve"] = merged
            service.setdefault("field_sources", {})["cve"] = "source_quote"

    # Explicit non-factual seeds keep downstream modules aware that target data
    # is not yet known. The accompanying missing_items explain what is absent.
    if not hosts:
        hosts.append({"id": "host-target", "role": "target", "epistemic_status": "insufficient", "source": "program"})
    if not services:
        services.append({"id": "service-unspecified", "name": "Unspecified service (absent)", "epistemic_status": "absent", "source": "program"})

    artifacts_raw = _array(result, "artifacts")
    artifacts: list[dict[str, Any]] = []
    artifact_ids: set[str] = set()
    for index, raw in enumerate(artifacts_raw, start=1):
        item = dict(raw)
        artifact = {k: v for k, v in item.items() if k in {"name", "type", "value", "description", "hashes", "path", "filename"} and v is not None}
        artifact["id"] = _unique_id(item.get("id"), f"artifact-{index}", artifact_ids)
        artifact_ids.add(artifact["id"])
        artifact["source"] = "llm"
        _refs = attach(item)
        artifact["evidence_refs"] = _refs
        artifact["epistemic_status"] = settle_status(item, _refs)
        artifacts.append(artifact)

    indicators = _extract_literal_indicators(units)
    for indicator in indicators:
        citations = indicator.pop("_citations", [])
        refs = attach({"evidence": citations, "epistemic_status": "supported"})
        indicator["evidence_refs"] = refs
        indicator["epistemic_status"] = settle_status(indicator, refs)

    commands = _extract_literal_commands(units)
    for command in commands:
        citations = command.pop("_citations", [])
        refs = attach({"evidence": citations, "epistemic_status": "supported"})
        command["evidence_refs"] = refs
        command["epistemic_status"] = settle_status(command, refs)

    # Program placeholders are not claims; count only analyst-produced entities.
    all_claims = [*actions, *relations, *hosts, *services, *artifacts, *indicators, *commands]
    statuses = [item.get("epistemic_status") for item in all_claims]
    ir: dict[str, Any] = {
        "schema_version": "1.0",
        "name": name,
        "provenance": {
            "input_kind": input_kind,
            "input_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            **({"source_name": source_name} if source_name else {}),
        },
        "actions": actions,
        "relations": relations,
        "hosts": hosts,
        "services": services,
        "target_context": {"host_refs": [host["id"] for host in hosts], "service_refs": [service["id"] for service in services]},
        "artifacts": artifacts,
        "indicators": indicators,
        "commands": commands,
        "evidence": evidence,
        "missing_items": [],
        "quality": {
            "quote_verified_rate": round(sum(bool(item["quote_verified"]) for item in evidence) / len(evidence), 4) if evidence else 0.0,
            "unsupported_claim_count": unsupported,
            "inferred_count": statuses.count("inferred"),
            "absent_count": statuses.count("absent"),
            "method": method,
            "provisional": True,
            "dropped_placeholder_hosts": dropped_placeholder_hosts,
            "excluded_non_attacker_actions": excluded_actions,
            "hedged_action_count": sum(1 for action in actions if action.get("source_certainty") == "hedged"),
            "capability_action_count": sum(1 for action in actions if action.get("occurrence") == "capability"),
            "dropped_non_software_services": dropped_non_software,
            "dropped_misplaced_techniques": misplaced_techniques,
        },
    }
    ir["missing_items"] = calculate_missing_items(ir)
    return ir


def _array(parent: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = parent.get(key, [])
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise AnalysisError(f"LLM field {key!r} must be an array of objects.")
    return value


def _required_text(item: dict[str, Any], key: str) -> str:
    value = _string(item.get(key))
    if value is None:
        raise AnalysisError(f"LLM item is missing required string field {key!r}.")
    return value


def _string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _unique_id(value: Any, fallback: str, used: set[str]) -> str:
    candidate = _string(value) or fallback
    candidate = re.sub(r"[^A-Za-z0-9_.:-]+", "-", candidate).strip("-") or fallback
    if candidate not in used:
        return candidate
    suffix = 2
    while f"{candidate}-{suffix}" in used:
        suffix += 1
    return f"{candidate}-{suffix}"

