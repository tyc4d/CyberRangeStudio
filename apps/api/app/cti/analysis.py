"""LLM-backed Scenario IR construction, constrained by source locators."""
from __future__ import annotations

import hashlib
import html
import json
import re
from typing import Any

from app.cti.attack import lookup as lookup_attack_technique
from app.cti.citations import evidence_record
from app.cti.missing import calculate_missing_items
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
    line_start = text.rfind("\n", 0, start) + 1
    prefix = text[line_start:start]
    return bool(re.search(r"\b(?:source|official advisory|reference|citation)\b", prefix, re.IGNORECASE))


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
        url_matches = []
        for match in _URL_RE.finditer(text):
            raw = match.group(0).rstrip(".,;:!?)]}")
            end = match.start() + len(raw)
            if not raw or _is_source_reference_url(text, match.start()):
                continue
            url_matches.append((match.start(), end))
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
            if "[.]" in value or in_url or _near_ioc_context(text, match.start(), match.end()):
                add("domain", value, value, unit)

        for match in _HASH_RE.finditer(text):
            value = match.group(0)
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
    return _build_ir(
        result, input_kind=input_kind, content=content, source_name=source_name,
        units=units, parsed_source=parsed_source, method=method, name=name,
    )


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
        "For every action, fill target_host_ref with the supported host reference when possible; use 'unknown' when the source "
        "does not identify the host."
    )
    if extraction:
        rules += " Return {\"observations\":[{\"claim\":string,\"quote\":string,\"source_ref\":string,\"epistemic_status\":string}]}"
    else:
        rules += (
            " Return JSON with arrays actions, relations, artifacts, and target_context {hosts, services}. "
            "Each item may contain evidence:[{quote,source_ref}]. Actions need id,name,target_host_ref; relations need id,from_action,to_action,kind; "
            "hosts need id,role; services need id,name. Include only information found in the report. "
            "When the report states or lists a MITRE ATT&CK technique for an action (for example a TTP/MITRE ATT&CK table), set "
            "attack_technique to only the exact T#### or T####.### id. attack_tactic may contain only a stated tactic name/category "
            "or TA#### tactic id; never put a technique name or T#### technique id in attack_tactic. Put ATT&CK ids only in these "
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

    actions_raw = _array(result, "actions")
    actions: list[dict[str, Any]] = []
    action_ids: set[str] = set()
    action_id_map: dict[str, str] = {}
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
    for index, raw in enumerate(hosts_raw, start=1):
        item = dict(raw)
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
    _resolve_action_hosts(actions, hosts, evidence)
    for index, raw in enumerate(services_raw, start=1):
        item = dict(raw)
        service: dict[str, Any] = {
            "id": _unique_id(item.get("id"), f"service-{index}", {x["id"] for x in services}),
            "name": _string(item.get("name")) or "Unspecified service (absent)",
            "source": "llm",
        }
        for key in ("version", "cpe", "catalogue_component"):
            if isinstance(item.get(key), str) and item[key].strip():
                service[key] = item[key].strip()
        if isinstance(item.get("cve"), list):
            service["cve"] = [v for v in item["cve"] if isinstance(v, str)]
        _refs = attach(item)
        service["evidence_refs"] = _refs
        service["epistemic_status"] = settle_status(item, _refs)
        services.append(service)

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

