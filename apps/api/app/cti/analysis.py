"""LLM-backed Scenario IR construction, constrained by source locators."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from app.cti.citations import evidence_record
from app.cti.missing import calculate_missing_items
from app.cti.parser import SourceUnit
from app.llm.client import complete


METHODS = {"single_pass", "staged", "staged_review"}
_STATUSES = {"supported", "inferred", "absent", "insufficient"}
_RELATION_KINDS = {"temporal", "dependency"}
_PROMPT_FORMAT = {"type": "json_object"}


class AnalysisError(ValueError):
    """Raised when the model response cannot be safely converted into an IR."""


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
        "a verbatim quote and the exact source_ref from the supplied source units. If a fact is missing, use epistemic_status "
        "'absent' or 'insufficient'. Each action, relation, host, service, and artifact must have epistemic_status. "
        "Relations must use kind 'temporal' for stated order and 'dependency' only when the source says the later action "
        "requires an earlier result; never infer dependency from order. Default relation epistemic_status to 'insufficient' "
        "unless a quote directly supports that relation."
    )
    if extraction:
        rules += " Return {\"observations\":[{\"claim\":string,\"quote\":string,\"source_ref\":string,\"epistemic_status\":string}]}"
    else:
        rules += (
            " Return JSON with arrays actions, relations, artifacts, and target_context {hosts, services}. "
            "Each item may contain evidence:[{quote,source_ref}]. Actions need id,name; relations need id,from_action,to_action,kind; "
            "hosts need id,role; services need id,name. Include only information found in the report."
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
        if not item_refs or any(not next(e for e in evidence if e["id"] == ref)["quote_verified"] for ref in item_refs):
            unsupported += 1
            if item.get("epistemic_status") != "absent":
                item["epistemic_status"] = "insufficient"
        return list(dict.fromkeys(item_refs))

    def normalize_status(item: dict[str, Any]) -> str:
        status = item.get("epistemic_status")
        if status not in _STATUSES:
            status = "insufficient"
        item["epistemic_status"] = status
        return status

    def _ref_verified(ref: str) -> bool:
        rec = next((e for e in evidence if e["id"] == ref), None)
        return bool(rec and rec.get("quote_verified"))

    def settle_status(item: dict[str, Any], refs: list[str]) -> str:
        """Deterministic epistemic rule, overriding the model's conservatism.

        - 'inferred' / 'absent' kept as the model reasoned/declared them.
        - otherwise: a program-VERIFIED verbatim quote => 'supported' (explicit in source);
          no verified quote => 'insufficient'.
        A verified quote proves the text exists at the locator; whether the quote
        semantically supports the claim is the staged_review / human layer (documented).
        """
        status = normalize_status(item)
        if status in ("inferred", "absent"):
            return status
        if refs and any(_ref_verified(r) for r in refs):
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
        for key in ("description", "attack_technique", "attack_tactic", "target_host_ref", "precondition", "initial_access"):
            if isinstance(item.get(key), str) and item[key].strip():
                action[key] = item[key].strip()
        _refs = attach(item)
        action["evidence_refs"] = _refs
        action["epistemic_status"] = settle_status(item, _refs)
        actions.append(action)

    relations_raw = _array(result, "relations")
    relations: list[dict[str, Any]] = []
    relation_ids: set[str] = set()
    for index, raw in enumerate(relations_raw, start=1):
        item = dict(raw)
        kind = item.get("kind")
        if kind not in _RELATION_KINDS:
            raise AnalysisError(f"Relation {index} has invalid kind; use temporal or dependency.")
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
        unsupported_before_relation = unsupported
        _refs = attach(item)
        relation["evidence_refs"] = _refs
        relation["epistemic_status"] = settle_status(item, _refs)
        if invalid_endpoints:
            relation["epistemic_status"] = "insufficient"
            if unsupported == unsupported_before_relation:
                unsupported += 1
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
        for key in ("os", "os_version", "network_placement"):
            if isinstance(item.get(key), str) and item[key].strip():
                host[key] = item[key].strip()
        _refs = attach(item)
        host["evidence_refs"] = _refs
        host["epistemic_status"] = settle_status(item, _refs)
        hosts.append(host)
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

    # Program placeholders are not claims; count only analyst-produced entities.
    all_claims = [*actions, *relations, *hosts, *services, *artifacts]
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

