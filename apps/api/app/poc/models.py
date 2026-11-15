"""Dataclasses mirroring packages/contracts/schemas/poc-validation.schema.json.

These are convenience containers for the owning workers; the JSON Schema (validated
via cr_contracts.iter_errors / iter_errors_shape) remains the source of truth. Keep
field names identical to the schema so ``asdict(obj)`` validates cleanly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

CheckStatus = Literal["PASS", "FAIL", "PARTIAL", "BLOCKED", "NOT_TESTED"]
PocStrategy = Literal["poc_exec", "config_check", "log_check", "not_executable"]


# --- Plan (poc/service) -----------------------------------------------------
@dataclass
class ValidationItem:
    action_id: str
    strategy: PocStrategy
    poc_required: bool
    required_predecessors: list[str] = field(default_factory=list)
    preconditions: list[str] = field(default_factory=list)
    expected_evidence: str = ""
    target_host_ref: Optional[str] = None
    service_ref: Optional[str] = None
    cve: Optional[str] = None
    attack_technique: Optional[str] = None
    not_executable_reason: Optional[str] = None


@dataclass
class ValidationPlan:
    scenario_id: str
    generated_at: str
    items: list[ValidationItem] = field(default_factory=list)


# --- Discovery (m9-discovery) ----------------------------------------------
@dataclass
class PocRef:
    commit_sha: Optional[str] = None
    release: Optional[str] = None


@dataclass
class ScoreBreakdown:
    version: float
    env: float
    code_available: float
    source_trust: float
    exec_cost: float


@dataclass
class PocCandidate:
    action_id: str
    source: Literal["github", "exploitdb", "nvd", "vendor"]
    source_url: str
    ref: PocRef
    product: str
    version_range: str
    language: str
    exec_method: Literal["python", "bash", "go", "metasploit", "http_seq", "manual"]
    trust: Literal["high", "medium", "low", "unknown"]
    compatibility_score: float
    score_breakdown: ScoreBreakdown
    dependencies: list[str] = field(default_factory=list)
    preconditions: list[str] = field(default_factory=list)
    cve: Optional[str] = None
    license: Optional[str] = None
    last_updated: Optional[str] = None


@dataclass
class PocManifest:
    scenario_id: str
    generated_at: str
    items: list[PocCandidate] = field(default_factory=list)


# --- Execution (m9-runner) --------------------------------------------------
EvidenceKind = Literal[
    "exploit_effect", "callback", "file_written", "shell_output",
    "state_change", "log", "request", "response",
]


@dataclass
class Evidence:
    kind: EvidenceKind
    path: str
    sha256: str
    redacted: bool
    note: Optional[str] = None


@dataclass
class ExecStages:
    started: bool = False
    delivered: bool = False
    responded: bool = False
    vuln_behavior: bool = False
    state_change: bool = False
    action_complete: bool = False


@dataclass
class ExecutionResult:
    action_id: str
    poc: dict  # {source_url, ref, sha256}
    status: CheckStatus
    stages: ExecStages
    logs_path: str
    confidence: float
    target_ownership_verified: bool
    payload_sha256: str
    started_at: str
    ended_at: str
    evidence: list[Evidence] = field(default_factory=list)
    exit_code: Optional[int] = None
    failure_reason: Optional[str] = None


# --- Chain (m9-chain) -------------------------------------------------------
@dataclass
class ChainTransfer:
    from_action: str
    to_action: str
    carried: Literal["cred", "session", "network", "token", "artifact"]
    verified: bool
    evidence_ref: Optional[str] = None


@dataclass
class ChainValidation:
    scenario_id: str
    objective_reached: bool
    passes: bool
    order_ok: bool
    transfers: list[ChainTransfer] = field(default_factory=list)
    per_action: list[dict] = field(default_factory=list)  # {action_id, status}


# --- Export (m9-export) -----------------------------------------------------
@dataclass
class ExportFile:
    path: str
    sha256: str
    generated_by: str


@dataclass
class ExportManifest:
    scenario_id: str
    scenario_version: str | int
    created_at: str
    rebuildable: bool
    files: list[ExportFile] = field(default_factory=list)
    missing_for_rebuild: list[str] = field(default_factory=list)
    contains_secrets: bool = False
