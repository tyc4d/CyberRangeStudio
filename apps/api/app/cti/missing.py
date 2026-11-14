"""Derive concrete, source-grounded build questions from Scenario IR facts."""
from __future__ import annotations

import re
from typing import Any, Iterable


_UNKNOWN = {"unknown", "unspecified", "absent", "n/a", "none", "null"}
_SUPPORTED_STATUSES = {"supported", "user_supplied"}


def _present(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip()) and value.strip().casefold() not in _UNKNOWN
    if isinstance(value, (list, tuple, set)):
        return any(_present(item) for item in value)
    return value is not None


def _supported(item: dict[str, Any]) -> bool:
    return item.get("epistemic_status") in _SUPPORTED_STATUSES or item.get("source") == "user"


def _supported_value(item: dict[str, Any], fields: Iterable[str]) -> bool:
    """A value counts as known when its record is supported or the user supplied that field."""
    field_sources = item.get("field_sources") if isinstance(item.get("field_sources"), dict) else {}
    return any(_present(item.get(field)) and (_supported(item) or field_sources.get(field) in {"user", "source_quote"})
               for field in fields)


def _known_fact(field: str, value: Any, source_ref: str, item: dict[str, Any] | None = None,
                evidence_refs: Iterable[str] | None = None, *, epistemic_status: str | None = None) -> dict[str, Any] | None:
    if not _present(value):
        return None
    refs = list(dict.fromkeys(str(ref) for ref in (evidence_refs or (item or {}).get("evidence_refs", []) or []) if _present(ref)))
    fact: dict[str, Any] = {
        "field": field,
        "value": value,
        "source_ref": source_ref,
        "epistemic_status": epistemic_status or ((item or {}).get("epistemic_status") if item else None) or "insufficient",
    }
    if refs:
        fact["evidence_refs"] = refs
    return fact


def _name(item: dict[str, Any], fallback: str = "") -> str:
    return str(item.get("name") or item.get("role") or item.get("id") or fallback)


def _text(item: dict[str, Any]) -> str:
    return " ".join(str(item.get(key) or "") for key in ("id", "name", "role", "description", "version", "software"))


def _all_source_text(ir: dict[str, Any]) -> str:
    parts: list[str] = []
    for collection in ("actions", "relations", "hosts", "services", "indicators", "artifacts", "assets", "conditions"):
        for item in ir.get(collection) or []:
            if isinstance(item, dict):
                parts.append(_text(item))
    for item in ir.get("evidence") or []:
        if isinstance(item, dict):
            parts.append(str(item.get("quote") or ""))
    return " ".join(parts).casefold()


def _clues(text: str) -> set[str]:
    value = text.casefold()
    found: set[str] = set()
    if any(term in value for term in ("windows", "powershell", "defender", "lsass", "defaultaccount", "active directory", "domain controller", "vmware horizon", "vdi-kms")):
        found.add("windows")
    if any(term in value for term in ("active directory", "domain controller", "get-adcomputer", "domain administrator")):
        found.add("ad")
    if re.search(r"\brdp\b", value) or "remote desktop" in value:
        found.add("windows")
        found.add("rdp")
    if "vmware" in value or "horizon" in value or "vdi-kms" in value:
        found.add("vmware")
    if "log4shell" in value or "log4j" in value:
        found.add("log4j")
    if "wordpress" in value or "corporate blog" in value:
        found.add("wordpress")
    if any(term in value for term in ("linux", "ubuntu", "debian", "red hat", "rhel", "apache httpd")):
        found.add("linux")
    return found


def _host_os_suggestions(text: str) -> list[str]:
    clues = _clues(text)
    if "windows" in clues or "ad" in clues or "rdp" in clues or "vmware" in clues or "log4j" in clues:
        return [
            "Windows Server 2019（候選；請核對原文或資產清單）",
            "Windows Server 2016（候選；請核對原文或資產清單）",
            "Windows Server 2022（候選；請核對原文或資產清單）",
            "其他 Windows 版本（請填確切版本）",
            "其他作業系統（請填確切名稱）",
        ]
    if "wordpress" in clues:
        return ["Linux（WordPress 常見部署候選；發行版待確認）", "Windows Server（候選；需確認）", "其他作業系統"]
    if "linux" in clues:
        return ["原文提及的 Linux 發行版（請填確切名稱）", "Ubuntu Server（候選；需確認）", "Debian（候選；需確認）", "其他作業系統"]
    return ["Windows Server（候選；需確認）", "Linux Server（候選；需確認）", "其他作業系統（請填確切名稱）"]


def _os_version_suggestions(text: str) -> list[str]:
    clues = _clues(text)
    if "windows" in clues or "ad" in clues or "rdp" in clues or "vmware" in clues or "log4j" in clues:
        return ["Windows Server 2019（確切 build 待確認）", "Windows Server 2016（確切 build 待確認）", "Windows Server 2022（確切 build 待確認）"]
    if "wordpress" in clues:
        return ["請從 WordPress 主機資產清單確認 Linux 發行版與版本", "Ubuntu LTS（候選；需確認）", "Debian（候選；需確認）"]
    return ["請填原文或資產清單中的確切作業系統版本", "Windows Server（build 待確認）", "Linux 發行版（版本待確認）"]


def _network_suggestions(context: str, all_text: str) -> list[str]:
    value = f"{context} {all_text}".casefold()
    internal = any(term in value for term in ("domain controller", "active directory", "vdi-kms", "lateral", "內網", "internal")) or bool(re.search(r"\brdp\b", value))
    exposed = any(term in value for term in ("public-facing", "public facing", "internet-facing", "internet facing", "對外", "public web"))
    if internal:
        return ["內部／管理網段（候選；請確認允許來源）", "隔離測試網段（只連必要主機）", "其他網段（請描述區域與可達路徑）"]
    if exposed:
        return ["對外 DMZ／公開服務區（候選；請確認實際曝露方式）", "隔離測試網段模擬對外入口", "其他網段（請描述區域與可達路徑）"]
    return ["隔離測試網段（只連必要主機）", "內部網段（請描述允許來源）", "對外 DMZ（只有原文/拓樸確認時才選）"]


def _suggestions_for(field_code: str, context: str, all_text: str) -> list[str]:
    text = f"{context} {all_text}".casefold()
    if field_code == "host_os":
        return _host_os_suggestions(text)
    if field_code == "os_version":
        return _os_version_suggestions(text)
    if field_code == "network":
        return _network_suggestions(context, all_text)
    if field_code == "log4j_version":
        return ["Apache Log4j 2.x（確切版號請由 JAR/SBOM 核對）", "無法確認；保留為未知"]
    if field_code == "horizon_version":
        return ["VMware Horizon（確切版號請由 Console/資產清單核對）", "無法確認；保留為未知"]
    if field_code == "wordpress_version":
        return ["WordPress（請由後台或部署檔確認確切版本）", "無法確認；保留為未知"]
    if field_code == "tool_version":
        return ["從來源、資產清單或套件雜湊核對確切版本", "選用隔離靶場已核准版本並標記為替代", "無法確認；保留為未知"]
    if field_code == "defender_state":
        return ["由隔離靶場決定初始保護/排除項狀態", "複製報告明確描述的狀態並標記證據", "無法確認；保留為未知"]
    if field_code == "egress":
        return ["封鎖對外連線（隔離預設）", "只允許連到指定 sinkhole/模擬服務", "只允許報告列出的目的地（需確認隔離規則）"]
    if field_code == "domain_name":
        return ["隔離靶場專用網域（例如 lab.test）", "從原文/資產清單填實際網域", "無法確認；保留為未知"]
    if field_code == "account":
        return ["使用專用測試帳號（不提供真實密碼）", "沿用報告明確提及的帳號名稱並指定安全替身", "無法確認；保留為未知"]
    if field_code == "phishing_domain":
        return ["隔離靶場的 .test 網域", "受控 sinkhole/模擬網域", "不建立外部網域，將此步驟標記未重現"]
    if field_code == "host_mapping":
        return ["把 IR 資產對應到一台隔離靶場主機", "若不需要主機靶場，標記此資產只作流程節點"]
    return ["請依來源或靶場設定補上具體值", "無法確認；保留為未知"]


def _slug(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return (text[:56].strip("-") or "item")


def _field_value(item: dict[str, Any], fields: Iterable[str]) -> Any:
    for field in fields:
        if _present(item.get(field)):
            return item[field]
    return None


def _host_evidence_refs(host: dict[str, Any], actions: list[dict[str, Any]]) -> list[str]:
    refs = list(host.get("evidence_refs") or [])
    role = _text(host).casefold()
    for action in actions:
        action_text = _text(action).casefold()
        explicit = action.get("target_host_ref") == host.get("id") or host.get("id") in (action.get("host_refs") or [])
        shared = bool(set(action.get("evidence_refs") or []).intersection(host.get("evidence_refs") or []))
        role_groups = (
            ("horizon",),
            ("vdi-kms",),
            ("domain controller", "active directory", "get-adcomputer", "domain administrator"),
        )
        lexical = any(any(term in role for term in group) and any(term in action_text for term in group)
                      for group in role_groups)
        if explicit or shared or lexical:
            refs.extend(action.get("evidence_refs") or [])
    return list(dict.fromkeys(str(ref) for ref in refs if _present(ref)))


def _related_action_ids(subject: dict[str, Any], actions: list[dict[str, Any]], *, collection: str) -> list[str]:
    subject_id = subject.get("id")
    subject_text = _text(subject).casefold()
    output: list[str] = []
    for action in actions:
        action_text = _text(action).casefold()
        refs = action.get("asset_refs" if collection == "assets" else "service_refs") or []
        explicit = subject_id in refs or action.get("target_host_ref") == subject_id or action.get("target_service_ref") == subject_id
        shared = bool(set(action.get("evidence_refs") or []).intersection(subject.get("evidence_refs") or []))
        if collection == "assets":
            terms = [term for term in ("wordpress", "employee", "account", "corporate blog") if term in subject_text]
            lexical = any(term in action_text for term in terms)
        else:
            terms = [term for term in ("windows defender", "rdp", "ngrok", "log4j", "log4shell") if term in subject_text]
            lexical = any(term in action_text for term in terms)
        if explicit or shared or lexical:
            output.append(str(action.get("id") or action.get("name") or "action"))
    return list(dict.fromkeys(output))


def _evidence_index(ir: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(entry["id"]): entry for entry in (ir.get("evidence") or [])
            if isinstance(entry, dict) and _present(entry.get("id"))}


def _anchor(ir: dict[str, Any], evidence_refs: Iterable[str], terms: Iterable[str]) -> dict[str, Any] | None:
    """Only emit PDF anchors backed by an exact, verified quote and explicit page locator."""
    evidence = _evidence_index(ir)
    normalized_terms = [term.casefold().strip() for term in terms if _present(term)]
    for evidence_ref in dict.fromkeys(str(ref) for ref in evidence_refs if _present(ref)):
        item = evidence.get(evidence_ref)
        if not item or item.get("quote_verified") is not True:
            continue
        locator = item.get("locator") or {}
        if locator.get("kind") != "page":
            continue
        page_value = locator.get("ref")
        try:
            page = int(str(page_value).strip())
        except (TypeError, ValueError):
            continue
        quote = item.get("quote")
        if not _present(quote) or (normalized_terms and not any(term in str(quote).casefold() for term in normalized_terms)):
            continue
        return {"page": page, "quote": quote, "evidence_ref": evidence_ref}
    return None


def _add_item(items: list[dict[str, Any]], ir: dict[str, Any], *, item_id: str, field: str,
              category: str, reason: str, question: str, affects: list[str], known: list[dict[str, Any]] | None = None,
              suggestions: list[str] | None = None, examples: list[str] | None = None,
              evidence_refs: Iterable[str] = (), anchor_terms: Iterable[str] = (), severity: str = "major",
              target: dict[str, str] | None = None) -> None:
    if any(item.get("id") == item_id for item in items):
        return
    item: dict[str, Any] = {
        "id": item_id,
        "field": field,
        "category": category,
        "reason": reason,
        "severity": severity,
        "status": "open",
        "question": question,
        "affects": list(dict.fromkeys(affects)),
        "suggestions": list(suggestions or []),
        "known": list(known or []),
        "needs_user_decision": True,
    }
    if examples:
        item["examples"] = list(examples)
    if target:
        # Where a user's answer is written back in the IR (collection, entity id, field).
        item["target"] = dict(target)
    anchor = _anchor(ir, evidence_refs, anchor_terms)
    if anchor:
        item["anchor"] = anchor
    items.append(item)


def _host_affects(host: dict[str, Any], linked_action_ids: list[str], actions_by_id: dict[str, dict[str, Any]], *, source_kind: str) -> list[str]:
    host_name = _name(host)
    output = [f"{source_kind}:{host.get('id') or 'target'} — {host_name}"]
    for action_id in linked_action_ids:
        action = actions_by_id.get(action_id)
        if action:
            output.append(f"action:{action_id} — {_name(action)}")
    return output


def _host_questions(ir: dict[str, Any], subjects: list[tuple[dict[str, Any], str]], actions: list[dict[str, Any]],
                    all_text: str, items: list[dict[str, Any]]) -> None:
    actions_by_id = {str(action.get("id")): action for action in actions if action.get("id")}
    for host, source_kind in subjects:
        if re.search(r"\b(?:attacker|red[\s-]team|operator)\b", str(host.get("role") or ""), re.IGNORECASE):
            continue  # the lab's own attacker machine is scaffolding, not a target to reconstruct
        host_id = str(host.get("id") or "target")
        label = _name(host, host_id)
        refs = _host_evidence_refs(host, actions) if source_kind == "hosts" else list(host.get("evidence_refs") or [])
        if source_kind == "hosts":
            refs_set = set(host.get("evidence_refs") or [])
            role = _text(host).casefold()
            role_groups = (
                ("horizon",),
                ("vdi-kms",),
                ("domain controller", "active directory", "get-adcomputer", "domain administrator"),
            )
            linked_action_ids = [
                str(action.get("id")) for action in actions
                if action.get("id") and (
                    action.get("target_host_ref") == host.get("id")
                    or host.get("id") in (action.get("host_refs") or [])
                    or bool(refs_set.intersection(action.get("evidence_refs") or []))
                    or any(any(term in role for term in group) and any(term in _text(action).casefold() for term in group)
                           for group in role_groups)
                )
            ]
        else:
            linked_action_ids = _related_action_ids(host, actions, collection="assets")
        linked_actions = [action for action in actions if str(action.get("id")) in linked_action_ids]
        affects = _host_affects(host, linked_action_ids, actions_by_id, source_kind=source_kind)
        host_context = " ".join([_text(host), *(_text(action) for action in linked_actions)])
        clue_text = host_context
        role_known = _known_fact("host role or asset", _name(host), f"{source_kind}:{host_id}.role",
                                 host, evidence_refs=refs)
        common_known = [fact for fact in [role_known] if fact]

        for code, keys, field_label, category, reason, question, severity in (
            ("os", ("os", "operating_system"), "作業系統", "host",
             "來源未提供這台主機/資產的作業系統；不能由產品或角色直接推定。",
             f"{label} 實際使用哪個作業系統？原文只提供主機/資產線索，請填實際系統或標記未知。", "major"),
            ("os-version", ("os_version", "os_build", "build"), "作業系統版本", "version",
             "來源未提供這台主機/資產的確切 OS 版本或 build。",
             f"{label} 的作業系統確切版本/build 是什麼？若無法確認，請明確保留未知。", "major"),
            ("network", ("network_placement", "network_segment", "network", "networks", "segment"), "網段/網路位置", "network",
             "IR 有主機或資產線索，但沒有可部署的網段與可達性設定。",
             f"{label} 要放在哪個網段？請指出隔離/內網/DMZ 等位置，以及哪些來源可以連到它。", "major"),
        ):
            value = _field_value(host, keys)
            if _supported_value(host, keys):
                continue
            known = list(common_known)
            if _present(value):
                fact = _known_fact(field_label, value, f"{source_kind}:{host_id}.{keys[0]}", host, evidence_refs=refs)
                if fact:
                    known.append(fact)
            _add_item(
                items, ir,
                item_id=f"missing-{source_kind}-{_slug(host_id)}-{code}",
                field=f"{label} — {field_label}",
                category=category,
                reason=reason,
                question=question,
                affects=affects,
                known=known,
                suggestions=_suggestions_for(
                    "host_os" if code == "os" else "os_version" if code == "os-version" else "network",
                    clue_text,
                    "",
                ),
                examples=_host_os_suggestions(clue_text)[:3] if code == "os" else None,
                evidence_refs=refs,
                anchor_terms=[label, str(value or "")],
                severity=severity,
                target=({"collection": "hosts", "id": host_id, "field": keys[0]}
                        if source_kind == "hosts" and not host.get("_placeholder") else None),
            )


def _software_version_questions(ir: dict[str, Any], hosts: list[dict[str, Any]], assets: list[dict[str, Any]],
                                services: list[dict[str, Any]], actions: list[dict[str, Any]],
                                items: list[dict[str, Any]], all_text: str) -> None:
    # These products are version-sensitive in the actual actions. Other named
    # services remain visible as known facts, without generating a generic version survey.
    products = (
        ("VMware Horizon", "horizon_version", ("vmware horizon", "horizon server"), "VMware Horizon version", "version", "horizon_version"),
        ("Apache Log4j", "log4j_version", ("log4shell", "log4j"), "Log4j version used by the Log4Shell step", "version", "log4j_version"),
        ("WordPress", "wordpress_version", ("wordpress", "corporate blog"), "WordPress version", "software", "wordpress_version"),
        ("XMRig", "xmrig_version", ("xmrig",), "XMRig version", "software", "tool_version"),
        ("PsExec", "psexec_version", ("psexec",), "PsExec version", "software", "tool_version"),
        ("Mimikatz", "mimikatz_version", ("mimikatz",), "Mimikatz version", "software", "tool_version"),
        ("Ngrok", "ngrok_version", ("ngrok",), "Ngrok version", "software", "tool_version"),
    )
    for product, code, aliases, field, category, suggestion_code in products:
        matched_actions = [action for action in actions if any(alias in _text(action).casefold() for alias in aliases)]
        matched_hosts = [host for host in hosts if any(alias in _text(host).casefold() for alias in aliases)]
        matched_services = [service for service in services if any(alias in _text(service).casefold() for alias in aliases)]
        matched_assets = [asset for asset in assets if any(alias in _text(asset).casefold() for alias in aliases)
                          and not (product == "WordPress" and any(term in _text(asset).casefold()
                                                                  for term in ("account", "credential", "user")))]
        related_hosts = list(matched_hosts)
        action_evidence_refs = {ref for action in matched_actions for ref in (action.get("evidence_refs") or [])}
        for host in hosts:
            if host not in related_hosts and action_evidence_refs.intersection(host.get("evidence_refs") or []):
                related_hosts.append(host)
        linked_actions = list(matched_actions)
        for host in related_hosts:
            host_refs = set(host.get("evidence_refs") or [])
            for action in actions:
                if action not in linked_actions and host_refs.intersection(action.get("evidence_refs") or []):
                    linked_actions.append(action)
        if not (matched_actions or related_hosts or matched_services or matched_assets):
            continue

        related_subjects = related_hosts + matched_services + matched_assets
        matched_host_ids = {str(subject.get("id")) for subject in related_hosts}
        matched_service_ids = {str(subject.get("id")) for subject in matched_services}
        refs: list[str] = []
        known: list[dict[str, Any]] = []
        affects: list[str] = []
        for subject in related_subjects:
            subject_id = str(subject.get("id") or "target")
            collection = "hosts" if subject_id in matched_host_ids else "services" if subject_id in matched_service_ids else "assets"
            refs.extend(subject.get("evidence_refs") or [])
            fact = _known_fact("受害軟體/服務", product if product != "Apache Log4j" else "Log4Shell (Apache Log4j)",
                               f"{collection}:{subject_id}", subject)
            if fact:
                known.append(fact)
            if collection == "hosts":
                affects.append(f"host:{subject_id} — {_name(subject)}")
            elif collection == "assets":
                affects.append(f"asset:{subject_id} — {_name(subject)}")
            else:
                affects.append(f"service:{subject_id} — {_name(subject)}")
        for action in linked_actions:
            action_id = str(action.get("id") or _name(action))
            refs.extend(action.get("evidence_refs") or [])
            fact = _known_fact("相關步驟", _name(action), f"actions:{action_id}.name", action)
            if fact:
                known.append(fact)
            affects.append(f"action:{action_id} — {_name(action)}")

        # A version in a supported product/service record is already known. Product
        # mentions without an exact version remain a question, with the mention shown in `known`.
        has_supported_version = any(
            _supported_value(subject, ("version", "software_version"))
            for subject in related_subjects + linked_actions
        )
        if has_supported_version:
            continue
        # Avoid asking a version if the exact product + version is already present in
        # a supported name/description, even when the structured `version` property is absent.
        version_pattern = re.compile(r"(?i)(?:\b\d{1,4}\.){1,3}\d{1,4}(?:[-+][a-z0-9.]+)?")
        if any(_supported(subject) and version_pattern.search(_text(subject)) for subject in related_subjects + linked_actions):
            continue

        if product == "VMware Horizon":
            question = "原文指出 VMware Horizon server，但未提供產品版號。靶場要重建哪個 Horizon 版本？請核對版本，不要由產品名稱猜測。"
            anchor_terms = ["VMware Horizon", "Horizon server"]
        elif product == "Apache Log4j":
            initial_action = next((action for action in linked_actions if "log4shell" in _text(action).casefold()), None)
            initial_id = str(initial_action.get("id")) if initial_action and initial_action.get("id") else "Log4Shell 步驟"
            question = f"{initial_id} 已知是 Log4Shell 初始入侵；不必再問如何取得立足點。為重建漏洞條件，該 VMware Horizon 主機上與此漏洞相關的 Apache Log4j 確切版本是什麼？"
            anchor_terms = ["Log4Shell", "Log4j"]
        elif product == "WordPress":
            question = "AttackFlow 指出目標是 Corporate Blog on WordPress，但沒有版號。靶場要對應哪個 WordPress 版本？"
            anchor_terms = ["WordPress", "corporate blog"]
        else:
            action_names = ", ".join(str(action.get("id") or _name(action)) for action in linked_actions)
            question = f"{action_names or 'IR 步驟'} 提到 {product}，但沒有提供可重現的版號。若靶場需要固定版本，請從來源或資產清單核對；否則選擇隔離靶場替代並標記。"
            anchor_terms = [product]
        _add_item(
            items, ir,
            item_id=f"missing-product-{_slug(product)}-version",
            field=field,
            category=category,
            reason=f"IR 指出 {product} 相關步驟，但沒有可重現所需的確切版本。",
            question=question,
            affects=affects or [f"action:{action.get('id')} — {_name(action)}" for action in matched_actions],
            known=known,
            suggestions=_suggestions_for(code, product + " " + " ".join(_text(x) for x in related_subjects + linked_actions), all_text),
            evidence_refs=refs,
            anchor_terms=anchor_terms,
        )


_PLACEHOLDER_SERVICE_IDS = {"service-unspecified"}
# Exploitation techniques: of a public-facing app, for client execution, of remote services,
# for privilege escalation, credential access and defense evasion.
_EXPLOIT_TECHNIQUES = ("T1190", "T1203", "T1210", "T1068", "T1212", "T1211")
_VERSION_IN_TEXT = re.compile(r"(?i)(?:\b\d{1,4}\.){1,3}\d{1,4}(?:[-+][a-z0-9.]+)?")


def _generic_service_version_questions(ir: dict[str, Any], services: list[dict[str, Any]], actions: list[dict[str, Any]],
                                       items: list[dict[str, Any]]) -> None:
    """Ask the version of every named target service the IR holds, whatever the product is.

    A reproduction needs a concrete release for any software an action exploits or uses.
    Services already covered by a product-specific question above are not asked twice.
    """
    covered = " ".join(str(item.get("id")) + " " + " ".join(item.get("affects") or []) for item in items)
    for service in services:
        service_id = str(service.get("id") or "")
        name = str(service.get("name") or "").strip()
        if not service_id or not name or service_id in _PLACEHOLDER_SERVICE_IDS or "(substitute)" in name:
            continue
        if service.get("source") == "program":
            continue  # module 4 raises its own questions for the services it derives
        if f"service:{service_id} " in covered or _supported_value(service, ("version", "software_version")):
            continue
        if _VERSION_IN_TEXT.search(name):
            continue
        linked_ids = _related_action_ids(service, actions, collection="services")
        name_key = name.casefold()
        linked_ids += [str(action.get("id")) for action in actions
                       if action.get("id") and name_key in _text(action).casefold() and str(action.get("id")) not in linked_ids]
        linked = [action for action in actions if str(action.get("id")) in linked_ids]
        cves = [str(cve) for cve in (service.get("cve") or [])]
        # The release matters when the service is what gets exploited. A service that is merely
        # logged in to or switched off (RDP, an antivirus) is covered by its configuration question.
        exploited = any(
            str(action.get("attack_technique") or "").upper().startswith(_EXPLOIT_TECHNIQUES)
            or re.search(r"\b(?:exploit\w*|vulnerab\w*|injection|CVE-\d{4}-\d+)\b", _text(action), re.IGNORECASE)
            for action in linked)
        if not cves and not exploited:
            continue
        known = [fact for fact in [
            _known_fact("受害軟體/服務", name, f"services:{service_id}.name", service),
            _known_fact("相關漏洞", ", ".join(cves), f"services:{service_id}.cve", service) if cves else None,
        ] if fact]
        refs = list(service.get("evidence_refs") or [])
        affects = [f"service:{service_id} — {name}"]
        for action in linked:
            refs.extend(action.get("evidence_refs") or [])
            affects.append(f"action:{action.get('id')} — {_name(action)}")
        because = f"（{', '.join(cves)}）" if cves else ""
        _add_item(
            items, ir,
            item_id=f"missing-service-{_slug(service_id)}-version",
            field=f"{name} — 版本",
            category="version",
            reason=f"IR 指出 {name}{because}，但沒有可重現所需的確切版本。",
            question=f"靶場要重建 {name} 的哪個版本？{'請選受 ' + ', '.join(cves) + ' 影響的版本；' if cves else ''}"
                     "原文沒有寫的話，請從資產清單核對或明確選擇替代版本，不要由產品名稱猜測。",
            affects=affects,
            known=known,
            suggestions=["填入來源或資產清單記載的確切版本", "選用隔離靶場可取得的替代版本並標記為替代", "無法確認；保留為未知"],
            evidence_refs=refs,
            anchor_terms=[name],
            target={"collection": "services", "id": service_id, "field": "version"},
        )


def _defender_questions(ir: dict[str, Any], services: list[dict[str, Any]], actions: list[dict[str, Any]],
                        items: list[dict[str, Any]]) -> None:
    related_actions = [action for action in actions if "windows defender" in _text(action).casefold()]
    related_services = [service for service in services if "windows defender" in _text(service).casefold()]
    if not related_actions and not related_services:
        return
    if any(_supported_value(action, ("initial_state", "state", "configuration", "exclusions", "enabled"))
           for action in related_actions) or any(_supported_value(service, ("initial_state", "state", "configuration", "exclusions", "enabled"))
                                                for service in related_services):
        return
    refs: list[str] = []
    known: list[dict[str, Any]] = []
    affects: list[str] = []
    for service in related_services:
        refs.extend(service.get("evidence_refs") or [])
        fact = _known_fact("安全產品", _name(service), f"services:{service.get('id')}.name", service)
        if fact:
            known.append(fact)
        affects.append(f"service:{service.get('id')} — {_name(service)}")
    for action in related_actions:
        refs.extend(action.get("evidence_refs") or [])
        fact = _known_fact("已描述的行為", _name(action), f"actions:{action.get('id')}.name", action)
        if fact:
            known.append(fact)
        affects.append(f"action:{action.get('id')} — {_name(action)}")
    action_ids = ", ".join(str(action.get("id")) for action in related_actions if action.get("id"))
    _add_item(
        items, ir,
        item_id="missing-security-windows-defender-state",
        field="Windows Defender 初始保護狀態/排除項",
        category="dependency",
        reason="步驟提到新增 Defender 排除項或停用 Defender，但靶場初始狀態與版本/政策未提供。",
        question=f"{action_ids or '相關步驟'} 執行前，Windows Defender 的即時防護、既有排除項與套用政策是什麼？請給初始狀態；不要貼任何真實機密。原文描述的停用/新增排除行為不代表初始狀態。",
        affects=affects,
        known=known,
        suggestions=_suggestions_for("defender_state", "Windows Defender PowerShell GUI", ""),
        evidence_refs=refs,
        anchor_terms=["Windows Defender", "Defender"],
    )


def _service_dependency_questions(ir: dict[str, Any], services: list[dict[str, Any]], actions: list[dict[str, Any]],
                                  items: list[dict[str, Any]]) -> None:
    """Turn named action dependencies into service-specific setup questions."""
    for service in services:
        service_text = _text(service).casefold()
        if "windows defender" in service_text:
            continue  # covered by the state/exclusion question above
        linked_ids = _related_action_ids(service, actions, collection="services")
        if not linked_ids:
            continue
        if _supported_value(service, ("configuration", "port", "ports", "auth_method", "endpoint", "protocol", "enabled", "state")):
            continue
        linked_actions = [action for action in actions if str(action.get("id")) in linked_ids]
        refs: list[str] = list(service.get("evidence_refs") or [])
        known = [_known_fact("IR 服務線索", _name(service), f"services:{service.get('id')}.name", service)]
        affects = [f"service:{service.get('id')} — {_name(service)}"]
        for action in linked_actions:
            action_id = str(action.get("id") or _name(action))
            refs.extend(action.get("evidence_refs") or [])
            known.append(_known_fact("依賴此服務的步驟", _name(action), f"actions:{action_id}.name", action))
            affects.append(f"action:{action_id} — {_name(action)}")
        label = _name(service)
        if "rdp" in service_text:
            detail = "RDP 是否啟用、靶場連接埠、允許來源與驗證方式"
            suggestions = ["TCP 3389（常見預設；請核對靶場設定）", "隔離測試網段內的替代連接埠", "不啟用 RDP，將此步驟標記未重現"]
        elif "ngrok" in service_text:
            detail = "本機端點、模擬 relay/tunnel 位置與外連規則"
            suggestions = ["只連到隔離 sinkhole/模擬 relay", "封鎖外連並將此步驟標記未重現", "填入靶場自建的模擬端點"]
        else:
            detail = "部署端點、連接埠、啟用狀態與允許來源"
            suggestions = ["只在隔離網段開放必要連接埠", "以來源明確記載的設定為準", "保留未知並不部署此服務"]
        action_names = ", ".join(str(action.get("id") or _name(action)) for action in linked_actions)
        _add_item(
            items, ir,
            item_id=f"missing-service-{_slug(str(service.get('id') or label))}-configuration",
            field=f"{label} — 靶場部署/連線設定",
            category="dependency",
            reason=f"{action_names or '相關步驟'} 使用 {label}，但 IR 沒有提供重建所需的服務設定。",
            question=f"{action_names or '相關步驟'} 依賴 {label}。靶場中{detail}要如何設定？請只提供隔離靶場資訊。",
            affects=affects,
            known=[fact for fact in known if fact],
            suggestions=suggestions,
            evidence_refs=refs,
            anchor_terms=[label],
        )


def _ad_domain_question(ir: dict[str, Any], hosts: list[dict[str, Any]], actions: list[dict[str, Any]],
                        items: list[dict[str, Any]]) -> None:
    relevant_actions = [action for action in actions if any(term in _text(action).casefold() for term in
                       ("active directory", "domain controller", "get-adcomputer", "domain administrator"))]
    relevant_hosts = [host for host in hosts if any(term in _text(host).casefold() for term in
                     ("domain controller", "active directory"))]
    context = [ir] + relevant_hosts + relevant_actions
    if not relevant_actions and not relevant_hosts:
        return
    if any(_supported_value(subject, ("domain_name", "domain", "ad_domain")) for subject in context if isinstance(subject, dict)):
        return
    refs: list[str] = []
    known: list[dict[str, Any]] = []
    affects: list[str] = []
    for host in relevant_hosts:
        refs.extend(host.get("evidence_refs") or [])
        fact = _known_fact("主機角色", _name(host), f"hosts:{host.get('id')}.role", host)
        if fact:
            known.append(fact)
        affects.append(f"host:{host.get('id')} — {_name(host)}")
    for action in relevant_actions:
        refs.extend(action.get("evidence_refs") or [])
        fact = _known_fact("AD 相關步驟", _name(action), f"actions:{action.get('id')}.name", action)
        if fact:
            known.append(fact)
        affects.append(f"action:{action.get('id')} — {_name(action)}")
    known.append({"field": "目錄服務線索", "value": "Active Directory / domain controller", "source_ref": "ir:actions+hosts",
                  "epistemic_status": "supported" if any(_supported(x) for x in relevant_actions + relevant_hosts) else "insufficient"})
    host_names = ", ".join(f"{host.get('id')} ({_name(host)})" for host in relevant_hosts)
    action_names = ", ".join(str(action.get("id") or _name(action)) for action in relevant_actions)
    _add_item(
        items, ir,
        item_id="missing-ad-domain-name",
        field="Active Directory 網域名稱",
        category="dependency",
        reason="IR 提到 AD/domain controller，但沒有網域名稱或隔離靶場對應方式。",
        question=f"{action_names or '相關 AD 步驟'} 涉及 Active Directory{f'（{host_names}）' if host_names else ''}，但 IR 沒有網域名稱。靶場要使用哪個網域名稱？可提供 lab 專用名稱（例如 lab.test），不要提供密碼或真實帳密。",
        affects=affects,
        known=known,
        suggestions=_suggestions_for("domain_name", "Active Directory Domain Controller", ""),
        evidence_refs=refs,
        anchor_terms=["Active Directory", "domain controller", "domain"],
    )


def _account_questions(ir: dict[str, Any], actions: list[dict[str, Any]], assets: list[dict[str, Any]],
                       conditions: list[dict[str, Any]],
                       items: list[dict[str, Any]]) -> None:
    # Explicit named accounts are known facts, but their scope/role or safe lab mapping
    # may still be missing. Never request passwords or other secrets.
    for action in actions:
        value = _text(action).casefold()
        action_id = str(action.get("id") or _name(action))
        account_profile: tuple[str, str, str, list[str]] | None = None
        if "defaultaccount" in value:
            account_profile = (
                "DefaultAccount 的範圍/狀態", f"{action_id} 提到 Windows 內建帳號 DefaultAccount，但沒有說明它是本機或網域帳號、是否啟用，以及靶場如何安全映射。",
                f"{action_id} 使用已知帳號名稱 DefaultAccount。它在來源主機上是本機還是網域帳號、當時是否啟用？靶場要映射到哪個專用測試帳號？請勿提供密碼。",
                ["defaultaccount"],
            )
        elif "rogue domain administrator" in value or "domain administrator account" in value:
            account_profile = (
                "新增網域管理員帳號的安全靶場映射", f"{action_id} 說明建立 rogue domain administrator account，但未提供帳號名稱或所屬群組。",
                f"{action_id} 描述建立 rogue domain administrator account。靶場使用哪個專用帳號名稱/群組來表示這個步驟？不要提供真實密碼。",
                ["domain administrator", "domain admin"],
            )
        elif "local administrator account" in value or "local admin" in value:
            account_profile = (
                "受影響主機上的本機管理員帳號", f"{action_id} 提到修改 several hosts 的 local administrator 密碼，但沒有列出主機或帳號映射。",
                f"{action_id} 涉及哪些主機上的本機管理員帳號？請列主機 ID/名稱與安全測試帳號映射；不要提供任何真實密碼。",
                ["local administrator", "local admin"],
            )
        if not account_profile:
            continue
        # If a structured account scope/identity is already supported, don't repeat it.
        if _supported_value(action, ("account_scope", "account_ref", "account_name", "lab_account_ref")):
            continue
        label, reason, question, anchor_terms = account_profile
        earlier = next((item for item in items if item.get("field") == label), None)
        if earlier is not None:
            # The same account in a later step is one question, not one per step.
            earlier["affects"] = list(dict.fromkeys([*earlier["affects"], f"action:{action_id} — {_name(action)}"]))
            continue
        account_name = "DefaultAccount" if "defaultaccount" in value else "rogue domain administrator account" if "domain administrator" in value else "local administrator account"
        known = [_known_fact("帳號線索", account_name, f"actions:{action_id}.name", action)]
        known = [fact for fact in known if fact]
        _add_item(
            items, ir,
            item_id=f"missing-account-{_slug(action_id)}",
            field=label,
            category="account",
            reason=reason,
            question=question,
            affects=[f"action:{action_id} — {_name(action)}"],
            known=known,
            suggestions=_suggestions_for("account", _text(action), ""),
            evidence_refs=action.get("evidence_refs") or [],
            anchor_terms=anchor_terms,
        )

    # AttackFlow assets can state that an account exists while omitting its safe lab identity.
    for asset in assets:
        asset_text = _text(asset).casefold()
        if not any(term in asset_text for term in ("account", "credential", "user account")):
            continue
        if _supported_value(asset, ("lab_account_ref", "account_name", "account_scope")):
            continue
        linked = _related_action_ids(asset, actions, collection="assets")
        linked_set = set(linked)
        actions_by_id = {str(action.get("id")): action for action in actions if action.get("id")}
        affects = [f"asset:{asset.get('id')} — {_name(asset)}"]
        affects.extend(f"action:{action_id} — {_name(actions_by_id[action_id])}" for action_id in linked if action_id in actions_by_id)
        fact = _known_fact("帳號資產", _name(asset), f"assets:{asset.get('id')}.name", asset)
        known = [fact] if fact else []
        for condition in conditions:
            description = str(condition.get("description") or "")
            condition_id = str(condition.get("id") or "")
            refs_from_condition = set(condition.get("on_true_refs") or [])
            refs_from_actions = {str(ref) for action in actions_by_id.values()
                                 if str(action.get("id")) in linked_set
                                 for ref in (action.get("effect_refs") or [])}
            mentions_credential = any(term in description.casefold() for term in ("credential", "password", "account"))
            if not mentions_credential or not (refs_from_condition.intersection(linked_set) or condition_id in refs_from_actions):
                continue
            known_condition = _known_fact("AttackFlow 已知帳號前置條件", description,
                                          f"conditions:{condition_id}.description", condition)
            if known_condition:
                known.append(known_condition)
        refs = list(asset.get("evidence_refs") or [])
        for action in actions:
            if action.get("id") in linked:
                refs.extend(action.get("evidence_refs") or [])
        _add_item(
            items, ir,
            item_id=f"missing-account-asset-{_slug(str(asset.get('id') or _name(asset)))}",
            field=f"{_name(asset)} — 靶場帳號映射",
            category="account",
            reason="AttackFlow 指明帳號/憑證資產，但沒有可安全使用的靶場帳號識別或權限範圍。",
            question=f"來源指出「{_name(asset)}」。請指定隔離靶場的測試帳號名稱/權限映射；不需要、也不要提供真實密碼。",
            affects=affects,
            known=known,
            suggestions=_suggestions_for("account", _text(asset), ""),
            evidence_refs=refs,
            anchor_terms=["WordPress account", "credentials", "account"],
        )


def _egress_questions(ir: dict[str, Any], actions: list[dict[str, Any]], items: list[dict[str, Any]], all_text: str) -> None:
    related = []
    for action in actions:
        text = _text(action).casefold()
        if any(term in text for term in ("download", "upload", "transfer.sh", "ngrok", "reverse proxy", "command and control", "outbound", "internet connectivity")):
            related.append(action)
    if not related:
        return
    # One explicit network decision can cover multiple download/C2 steps while naming
    # only those steps; it never claims the whole chain needs unrestricted Internet.
    if any(_supported_value(subject, ("outbound_connectivity", "egress_policy", "network_access"))
           for subject in [ir] + (ir.get("hosts") or []) + (ir.get("services") or [])):
        return
    refs: list[str] = []
    known: list[dict[str, Any]] = []
    affects: list[str] = []
    evidence = _evidence_index(ir)
    seen_destinations: set[str] = set()
    for action in related:
        action_id = str(action.get("id") or _name(action))
        refs.extend(action.get("evidence_refs") or [])
        fact = _known_fact("需要外連的步驟", _name(action), f"actions:{action_id}.name", action)
        if fact:
            known.append(fact)
        affects.append(f"action:{action_id} — {_name(action)}")
        for ref in action.get("evidence_refs") or []:
            entry = evidence.get(str(ref))
            quote = str(entry.get("quote") or "") if entry else ""
            if not quote:
                continue
            # Preserve only destinations literally stated in the cited quote.
            destinations = re.findall(r"(?i)(?:\b\d{1,3}(?:\[\.\]|\.)\d{1,3}(?:\[\.\]|\.)\d{1,3}(?:\[\.\]|\.)\d{1,3}\b|[a-z0-9.-]+\.(?:com|net|org|sh|test))", quote)
            for destination in destinations:
                normalized = destination.casefold()
                if normalized in seen_destinations:
                    continue
                seen_destinations.add(normalized)
                clue = _known_fact("原文列出的外部目的地", destination, f"evidence:{ref}", entry or {},
                                   evidence_refs=[str(ref)],
                                   epistemic_status="supported" if entry.get("quote_verified") is True else "insufficient")
                if clue:
                    known.append(clue)
    action_names = ", ".join(str(action.get("id") or _name(action)) for action in related)
    _add_item(
        items, ir,
        item_id="missing-network-outbound-policy",
        field="下載/C2 步驟的對外連線政策",
        category="network",
        reason="多個具名步驟需要下載檔案或建立 Ngrok/C2 連線，但 IR 沒有說明靶場允許哪些外連。",
        question=f"{action_names} 涉及下載、上傳或 Ngrok/C2。靶場是否完全封鎖外連、只接 sinkhole/模擬服務，或僅允許原文列出的目的地？請指定封鎖/允許規則；不要直接開放任意網際網路。",
        affects=affects,
        known=known,
        suggestions=_suggestions_for("egress", " ".join(_text(action) for action in related), all_text),
        evidence_refs=refs,
        anchor_terms=["download", "ngrok", "transfer.sh", "internet connectivity", "182.54.217"],
        severity="major",
    )


def _phishing_domain_questions(ir: dict[str, Any], actions: list[dict[str, Any]], items: list[dict[str, Any]], all_text: str) -> None:
    domain_actions = [action for action in actions if any(term in _text(action).casefold() for term in
                     ("acquire infrastructure: domains", "phishing domain", "phishing link"))]
    if not domain_actions:
        return
    if any(_supported_value(subject, ("lab_domain", "domain_name", "controlled_domain"))
           for subject in [ir] + actions):
        return
    refs = [ref for action in domain_actions for ref in (action.get("evidence_refs") or [])]
    known = [_known_fact("攻擊基礎設施線索", _name(action), f"actions:{action.get('id')}.name", action)
             for action in domain_actions]
    _add_item(
        items, ir,
        item_id="missing-phishing-domain",
        field="受控的釣魚測試網域",
        category="network",
        reason="AttackFlow 提到取得仿冒網域/釣魚連結，但沒有指定隔離演練使用的受控網域。",
        question="這些步驟需要哪個受控的靶場網域？請用 .test 網域或 sinkhole，避免註冊/連線到真實仿冒網域。",
        affects=[f"action:{action.get('id')} — {_name(action)}" for action in domain_actions],
        known=[fact for fact in known if fact],
        suggestions=_suggestions_for("phishing_domain", " ".join(_text(action) for action in domain_actions), all_text),
        evidence_refs=refs,
        anchor_terms=["phishing domain", "phishing link", "domain"],
    )


def _generic_entry_questions(ir: dict[str, Any], actions: list[dict[str, Any]], items: list[dict[str, Any]]) -> None:
    """Ask for a start condition only if no action already states how the scenario begins."""
    if not actions:
        return
    explicit_entry_terms = (
        "initial access", "initial foothold", "log4shell", "exploit", "spearphishing", "phishing",
        "acquire infrastructure", "credentials have been compromised",
    )
    if any(any(term in _text(action).casefold() for term in explicit_entry_terms)
           or "initial access" in str(action.get("attack_tactic") or "").casefold()
           for action in actions):
        return
    flow_refs = set((ir.get("flow") or {}).get("start_refs") or []) if isinstance(ir.get("flow"), dict) else set()
    candidate = next((action for action in actions if action.get("id") in flow_refs), actions[0])
    if _supported_value(candidate, ("precondition", "initial_access", "preconditions")):
        return
    action_id = str(candidate.get("id") or _name(candidate))
    known = [_known_fact("IR 起始步驟", _name(candidate), f"actions:{action_id}.name", candidate)]
    _add_item(
        items, ir,
        item_id=f"missing-action-{_slug(action_id)}-start-condition",
        field=f"{_name(candidate)} — 執行前置條件",
        category="precondition",
        reason="IR 沒有說明這個情境的起始存取狀態；不假設攻擊者已經有立足點。",
        question=f"情境從「{_name(candidate)}」開始。執行這一步前需要哪個已知帳號、服務或其他狀態？若來源沒有說明，請選擇直接從此步驟開始或保留未知。",
        affects=[f"action:{action_id} — {_name(candidate)}"],
        known=[fact for fact in known if fact],
        suggestions=["直接從這一步開始重現（前置條件不重建）", "補上來源明確記載的前置條件", "保留未知"],
        evidence_refs=candidate.get("evidence_refs") or [],
        anchor_terms=[_name(candidate)],
    )


def _unresolved_dependency_refs(ir: dict[str, Any], hosts: list[dict[str, Any]], services: list[dict[str, Any]],
                               assets: list[dict[str, Any]], actions: list[dict[str, Any]],
                               items: list[dict[str, Any]]) -> None:
    """Ask for the target of explicit action references absent from the IR collections."""
    accounts = [item for item in (ir.get("accounts") or []) if isinstance(item, dict)]
    accounts.extend(asset for asset in assets if any(term in _text(asset).casefold() for term in ("account", "credential", "user")))
    software = [item for item in (ir.get("software") or []) if isinstance(item, dict)]
    software.extend(services)
    known_ids = {
        "host": {str(item.get("id")) for item in hosts if item.get("id")},
        "service": {str(item.get("id")) for item in services if item.get("id")},
        "asset": {str(item.get("id")) for item in assets if item.get("id")},
        "account": {str(item.get("id")) for item in accounts if item.get("id")},
        "software": {str(item.get("id")) for item in software if item.get("id")},
    }
    for action in actions:
        action_id = str(action.get("id") or _name(action))
        refs_to_check = (
            ("service", action.get("service_refs") or []),
            ("host", action.get("host_refs") or []),
            ("host", [action.get("target_host_ref")] if _present(action.get("target_host_ref")) else []),
            ("asset", action.get("asset_refs") or []),
            ("account", action.get("account_refs") or []),
            ("software", action.get("software_refs") or []),
        )
        for kind, refs in refs_to_check:
            for reference in refs:
                ref = str(reference)
                if ref in known_ids[kind]:
                    continue
                # Host refs may intentionally target an asset in AttackFlow.
                if kind == "host" and ref in known_ids["asset"]:
                    continue
                if kind == "asset" and ref in known_ids["host"]:
                    continue
                if kind in {"account", "software"} and ref in known_ids["asset"]:
                    continue
                label = {"host": "主機", "service": "服務", "asset": "資產", "account": "帳號", "software": "軟體"}[kind]
                _add_item(
                    items, ir,
                    item_id=f"missing-action-{_slug(action_id)}-{kind}-{_slug(ref)}-mapping",
                    field=f"{_name(action)} — {label}依賴對應",
                    category="host" if kind == "host" else "account" if kind == "account" else "version" if kind == "software" else "dependency",
                    reason=f"IR 的 {action_id} 指向 {ref}，但沒有對應的 {label}紀錄。",
                    question=f"{action_id} 參照 {ref}。請補上這個{label}的名稱/角色與靶場對應，或確認此參照是否應移除。",
                    affects=[f"action:{action_id} — {_name(action)}", f"{kind}_ref:{ref}"],
                    known=[fact for fact in [_known_fact("未解析的 IR 參照", ref,
                                                         f"actions:{action_id}.{kind}_refs", action)] if fact],
                    suggestions=[f"新增 {label} 紀錄並對應到隔離靶場", "確認參照錯誤後移除", "保留未知"],
                    evidence_refs=action.get("evidence_refs") or [],
                    anchor_terms=[ref, _name(action)],
                )


def calculate_missing_items(ir: dict[str, Any]) -> list[dict[str, Any]]:
    """Build host- and action-scoped open questions from facts actually present in IR.

    Supported values are not repeated as questions. Incomplete/insufficient values
    remain visible in ``known`` with their epistemic status so the UI distinguishes an
    original clue from a user decision. Evidence becomes a PDF ``anchor`` only when it
    has a verified exact quote and an explicit page locator.
    """
    if not isinstance(ir, dict):
        return []
    hosts = [item for item in (ir.get("hosts") or []) if isinstance(item, dict)]
    services = [item for item in (ir.get("services") or []) if isinstance(item, dict)]
    actions = [item for item in (ir.get("actions") or []) if isinstance(item, dict)]
    assets = [item for item in (ir.get("assets") or []) if isinstance(item, dict)]
    conditions = [item for item in (ir.get("conditions") or []) if isinstance(item, dict)]
    all_text = _all_source_text(ir)
    items: list[dict[str, Any]] = []

    _host_questions(ir, [(host, "hosts") for host in hosts], actions, all_text, items)

    represented_hosts = {str(host.get("id")) for host in hosts if host.get("id")}
    referenced_hosts = list(dict.fromkeys(
        str(ref) for action in actions
        for ref in ([action.get("target_host_ref")] + list(action.get("host_refs") or []))
        if _present(ref) and str(ref) not in represented_hosts
    ))
    for target_ref in referenced_hosts:
        placeholder = {"id": target_ref, "role": target_ref, "epistemic_status": "insufficient", "source": "program",
                       "_placeholder": True}
        _host_questions(ir, [(placeholder, "hosts")], actions, all_text, items)

    # Attack Flow imports may express affected machines as assets and leave hosts empty.
    # Turn only explicit web/app/server assets into host-like gaps; account assets stay
    # account questions and attacker-owned domains are handled separately.
    host_assets: list[dict[str, Any]] = []
    account_assets: list[dict[str, Any]] = []
    for asset in assets:
        value = _text(asset).casefold()
        if any(term in value for term in ("account", "credential", "user account")):
            account_assets.append(asset)
        elif any(term in value for term in ("wordpress", "website", "web site", "blog", "application server", "host", "endpoint", "database server")):
            host_assets.append(asset)
    if not hosts and host_assets:
        _host_questions(ir, [(asset, "assets") for asset in host_assets], actions, all_text, items)
    elif not hosts and not host_assets:
        target_refs = referenced_hosts
        if target_refs:
            pass  # unresolved target refs were already expanded above
        elif actions:
            # There's no host or target reference to ask per-machine questions about.
            first = next((action for action in actions if any(term in _text(action).casefold()
                          for term in ("exploit", "initial access", "public-facing", "target host"))), actions[0])
            first_id = str(first.get("id") or _name(first))
            _add_item(
                items, ir,
                item_id="missing-target-host-mapping",
                field="受害主機/資產對應",
                category="host",
                reason="IR 有攻擊步驟，但沒有 hosts、host_ref 或可識別的目標主機資產，無法把 OS/網段問題落到具體主機。",
                question=f"{first_id}「{_name(first)}」涉及受害端，但 IR 沒有主機或資產對應。請先指出這個步驟作用在哪台/哪種主機。",
                affects=[f"action:{first_id} — {_name(first)}"],
                known=[fact for fact in [_known_fact("目標步驟", _name(first), f"actions:{first_id}.name", first)] if fact],
                suggestions=_suggestions_for("host_mapping", _text(first), all_text),
                evidence_refs=first.get("evidence_refs") or [],
                anchor_terms=[_name(first)],
            )

    _software_version_questions(ir, hosts, assets, services, actions, items, all_text)
    _generic_service_version_questions(ir, services, actions, items)
    _defender_questions(ir, services, actions, items)
    _service_dependency_questions(ir, services, actions, items)
    _ad_domain_question(ir, hosts, actions, items)
    _account_questions(ir, actions, account_assets, conditions, items)
    _unresolved_dependency_refs(ir, hosts, services, assets, actions, items)
    _egress_questions(ir, actions, items, all_text)
    _phishing_domain_questions(ir, actions, items, all_text)
    _generic_entry_questions(ir, actions, items)
    return items


_RESOLUTION_KEYS = ("status", "resolution", "resolution_source", "applied_to", "write_back")


def refresh_missing_items(ir: dict[str, Any], *, add_new: bool = True) -> list[dict[str, Any]]:
    """Recompute the analysis-stage questions for the current IR, keeping the user's decisions.

    - A question that still applies keeps its status and resolution.
    - A question the user already resolved stays in the list as history even when the IR no
      longer raises it (for example because the answer was written into the host record).
    - An open question the IR no longer raises is dropped.
    - Items owned by other modules (ids not starting with ``missing-``) are left untouched.
    - ``add_new=False`` only re-evaluates questions already in the IR (used by planning,
      which must settle what it answered without starting a new questionnaire).
    """
    previous = [item for item in (ir.get("missing_items") or []) if isinstance(item, dict)]
    by_id = {str(item.get("id")): item for item in previous}
    fresh = calculate_missing_items(ir)
    if not add_new:
        fresh = [item for item in fresh if item["id"] in by_id]
    fresh_ids = {item["id"] for item in fresh}
    for item in fresh:
        old = by_id.get(item["id"])
        if old and old.get("status") not in (None, "open"):
            for key in _RESOLUTION_KEYS:
                if key in old:
                    item[key] = old[key]
    kept: list[dict[str, Any]] = []
    for item in previous:
        item_id = str(item.get("id"))
        if item_id in fresh_ids:
            continue
        if not item_id.startswith("missing-") or item.get("status") not in (None, "open"):
            kept.append(item)
    return fresh + kept
