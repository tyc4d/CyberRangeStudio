"""Minimum context requirements used to calculate missing IR fields."""
from __future__ import annotations

from typing import Any


# Keep this checklist small and explicit. A missing value stays unknown until a
# source or user supplies it; this module never guesses a real-world *report fact*.
# To stop each item from reading as an abstract field name, every entry also carries
# a plain-language question, example answers, and a benign substitute the user can
# accept in one click. Examples and the suggestion are clearly substitutes/examples,
# never presented as something the report said.
#
# Each entry: (field, category, reason, grounding, question, examples, suggestions)
# `grounding` picks which scenario steps/hosts the gap concerns, from facts already
# in the IR — "entry" = the first step(s), "targets" = the hosts steps act on.
# `examples` prefill the "我知道答案" box; `suggestions` are benign substitutes the
# user can accept in one click (recorded as substitute_chosen). Several are offered
# so the choice is concrete, never a single take-it-or-leave-it default.
MINIMUM_REQUIRED_FIELDS = (
    (
        "target host identity", "host", "Identify the affected host or its role.", "targets",
        "這個情境攻擊的是哪一台（或哪一種）主機？報告沒有明確指出主機身分或角色。",
        ["對外 Web 伺服器", "Active Directory 網域控制站", "內部資料庫伺服器"],
        ["對外 Web 伺服器（web）", "應用伺服器（app）", "資料庫伺服器（db）", "網域控制站（dc）", "檔案伺服器（file）"],
    ),
    (
        "target host operating system", "host", "The target operating system is needed to choose a faithful environment.", "targets",
        "受害主機跑的是什麼作業系統？這會決定要用哪種環境來重建。",
        ["Windows Server 2019", "Ubuntu 22.04 LTS", "Red Hat Enterprise Linux 9"],
        ["Ubuntu 22.04 LTS", "Debian 12", "Red Hat Enterprise Linux 9", "Windows Server 2022", "Alpine 3.20（極簡替身）"],
    ),
    (
        "target host OS version", "version", "The OS version can affect behavior and deployment fidelity.", "targets",
        "作業系統的確切版本是哪一個？版本會影響行為與重建的忠實度。",
        ["Windows Server 2019（1809）", "Ubuntu 22.04.4"],
        ["Ubuntu 22.04.4", "Debian 12.6", "RHEL 9.4", "Windows Server 2022（21H2）"],
    ),
    (
        "target network placement", "network", "Network placement is needed to model reachability.", "targets",
        "這台主機位在網路的哪個位置？對外可連入，還是只允許內網？",
        ["對外 DMZ，可從網際網路連入", "僅內網，只接受內部來源", "後端網段，只開放給應用層"],
        ["僅內網，只接受內部來源", "對外 DMZ，可從網際網路連入", "後端網段，只開放給應用層", "管理網段，只接受跳板機"],
    ),
    (
        "target service name", "software", "At least one affected service or application must be identified.", "targets",
        "被攻擊的服務或應用程式是什麼？至少要能指出一個。",
        ["Nginx", "Apache HTTP Server", "PostgreSQL", "Microsoft Exchange"],
        ["Nginx（Web 替身）", "Apache HTTP Server（Web 替身）", "PostgreSQL（DB 替身）", "MySQL（DB 替身）", "Redis（快取替身）"],
    ),
    (
        "target service version", "version", "The exact service version is needed for a reproducible setup.", "targets",
        "該服務的確切版本是哪一個？可重現的環境需要明確版本。",
        ["Nginx 1.27.2", "PostgreSQL 16.4"],
        ["Nginx 1.27.2", "Apache 2.4.62", "PostgreSQL 16.4", "MySQL 8.4", "目錄最新釘選版本"],
    ),
    (
        "attacker access precondition", "precondition", "The initial access condition is needed to understand the scenario start.", "entry",
        "攻擊者是如何取得初始立足點的？這決定整個情境的起點。",
        ["利用對外服務的已知漏洞", "使用竊得的有效帳密登入", "釣魚信附件被開啟"],
        ["已取得初始立足點（從已知起點開始重現）", "利用對外服務的已知漏洞", "使用竊得的有效帳密登入", "釣魚信附件被開啟", "供應鏈／第三方被入侵"],
    ),
)


def calculate_missing_items(ir: dict[str, Any]) -> list[dict[str, Any]]:
    """Return open items for checklist fields not supported by current IR data."""
    hosts = ir.get("hosts") or []
    services = ir.get("services") or []
    actions = ir.get("actions") or []
    has_host_identity = any(
        (host.get("role") not in {None, "", "target", "unidentified target"} and _supported(host))
        or (_verified_value(host, "name") or _verified_value(host, "hostname"))
        for host in hosts
    )
    has_host_os = any(_verified_value(host, "os") for host in hosts)
    has_host_os_version = any(_verified_value(host, "os_version") for host in hosts)
    has_network = any(_verified_value(host, "network_placement") or _verified_value(host, "network") for host in hosts)
    has_service_name = any(_verified_value(service, "name") and service.get("epistemic_status") != "absent" for service in services)
    has_service_version = any(_verified_value(service, "version") for service in services)
    has_precondition = any(_verified_value(action, "precondition") or _verified_value(action, "initial_access") for action in actions)

    present = (
        has_host_identity, has_host_os, has_host_os_version, has_network,
        has_service_name, has_service_version, has_precondition,
    )

    # Grounding drawn only from facts already in the IR, so the question can name
    # the concrete steps/hosts the gap concerns instead of a bare field name.
    targeted = {r.get("to_action") for r in (ir.get("relations") or [])}
    entry_names = [a.get("name") for a in actions if a.get("id") not in targeted and a.get("name")]
    if not entry_names and actions:
        entry_names = [a.get("name") for a in actions[:1] if a.get("name")]
    target_refs: list[str] = []
    for a in actions:
        ref = a.get("target_host_ref")
        if ref and ref not in target_refs:
            target_refs.append(ref)
    chain_note = f"整條攻擊鏈（共 {len(actions)} 步）" if actions else "尚無攻擊步驟"

    def grounding(kind: str) -> list[str]:
        if kind == "entry":
            return (entry_names or [chain_note])[:3]
        return (target_refs or [chain_note])[:4]

    items: list[dict[str, Any]] = []
    for index, (entry, exists) in enumerate(zip(MINIMUM_REQUIRED_FIELDS, present), start=1):
        if exists:
            continue
        field, category, reason, ground_kind, question, examples, suggestions = entry
        items.append({
            "id": f"missing-{index}",
            "field": field,
            "category": category,
            "reason": reason,
            "severity": "major" if index in {1, 2, 5, 7} else "minor",
            "status": "open",
            "question": question,
            "affects": grounding(ground_kind),
            "examples": list(examples),
            "suggestions": list(suggestions),
        })
    return items


def _known(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value.strip().lower() not in {"unknown", "unspecified", "absent", "n/a"}


def _supported(item: dict[str, Any]) -> bool:
    return item.get("epistemic_status") == "supported" or item.get("source") == "user"


def _verified_value(item: dict[str, Any], field: str) -> bool:
    return _known(item.get(field)) and _supported(item)

