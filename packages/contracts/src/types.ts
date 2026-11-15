// Shared TypeScript types, hand-aligned with ../schemas/*.json (source of truth).
// If a schema changes, update this file to match and tell the Lead.

export type EpistemicStatus = "supported" | "inferred" | "absent" | "insufficient";
export type Source = "llm" | "user" | "stix" | "program";
export type RelationKind = "temporal" | "dependency";
export type CheckStatus = "PASS" | "FAIL" | "PARTIAL" | "NOT_TESTED";

export interface Evidence {
  id: string;
  quote: string;
  locator?: { kind?: "paragraph" | "page" | "stix_path"; ref?: string };
  quote_verified?: boolean;
  /** Graded support of the quote against the source: verbatim, strong, keyword/fragment, or none. */
  quote_match?: "exact" | "strong" | "partial" | "none";
  match_score?: number;
  matched_text?: string;
}

export interface Action {
  id: string;
  name: string;
  description?: string;
  attack_technique?: string;
  attack_tactic?: string;
  effect_refs?: string[];
  asset_refs?: string[];
  technique_id?: string;
  tactic_id?: string;
  execution_start?: string;
  execution_end?: string;
  command_ref?: string;
  /** Host the action is launched from, only when the source states it (target_host_ref is where it takes effect). */
  source_host_ref?: string;
  target_host_ref?: string;
  evidence_refs?: string[];
  epistemic_status: EpistemicStatus;
  source: Source;
  /** B4: can this step be built/validated in the current environment? Honest degradation, never faked. */
  reproducibility?: "reproducible" | "substitute_only" | "needs_vm" | "not_reproducible";
  /** Short reason for the reproducibility verdict (which component/runtime is missing). */
  reproducibility_reason?: string;
}

export interface Relation {
  id: string;
  from_action: string;
  to_action: string;
  kind: RelationKind;
  rationale?: string;
  evidence_refs?: string[];
  epistemic_status: EpistemicStatus;
  source: Source;
  /** User ticked "I checked the source, this ordering holds" for an edge with no matching quote. */
  confirmed?: boolean;
  /** Why the program lowered the status (e.g. the quote exists but does not state order or dependency). */
  epistemic_reason?: string;
}

export interface Host {
  id: string;
  role: string;
  os?: string;
  os_version?: string;
  /** Hostname or label the source gives this machine. */
  name?: string;
  network_placement?: string;
  service_refs?: string[];
  epistemic_status?: EpistemicStatus;
  source?: Source;
  /** Per-field provenance for values not from the record's own source: "user" (supplement) or "source_quote". */
  field_sources?: Record<string, "user" | "source_quote">;
}

export interface ServiceItem {
  id: string;
  name: string;
  version?: string;
  cpe?: string;
  cve?: string[];
  catalogue_component?: string;
  is_substitute?: boolean;
  epistemic_status?: EpistemicStatus;
  source?: Source;
  host_ref?: string;
  port?: number;
  protocol?: "tcp" | "udp";
  /** The catalogue has no component for this software (module 4). */
  no_component?: boolean;
  /** Source words that led module 4 to this product when they are not its name (e.g. "Log4Shell"). */
  matched_text?: string;
  /** How the deployed catalogue release relates to the source: stated, assumed (source gives none) or substituted. */
  version_basis?: "stated" | "assumed" | "substituted";
  /** The catalogue release actually deployed when it is assumed or substituted; `version` holds only stated values. */
  deployed_version?: string;
  /** "user_chosen": a substitute the user picked for a service with no catalogue component. */
  substitute_basis?: "user_chosen";
  substitute_supplement_ref?: string;
  /** Supplement this service was derived from; such services have source "user". */
  supplement_ref?: string;
  field_sources?: Record<string, "user" | "source_quote">;
}

export interface MissingItem {
  id: string;
  field: string;
  category: "host" | "software" | "version" | "network" | "account" | "dependency" | "precondition" | "proprietary" | "other";
  reason: string;
  severity?: "blocker" | "major" | "minor";
  status: "open" | "user_supplied" | "llm_suggested" | "substitute_chosen" | "accepted_unknown";
  resolution?: string;
  resolution_source?: Source;
  /** Where an answer to this question is written in the IR. */
  target?: { collection: "hosts" | "services"; id: string; field: string };
  /** Set when the answer was written to that field. */
  applied_to?: { collection: "hosts" | "services"; id: string; field: string };
  /** Reason the answer was kept as text only and not written to a field. */
  write_back?: string;
  /** Plain-language question for the user, so they need not read the whole report to know what is asked. */
  question?: string;
  /** Which scenario steps / hosts this gap concerns, for grounding (derived from current IR facts, never invented). */
  affects?: string[];
  /** Example answers, to make an abstract field concrete. Examples only — not claims about the report. */
  examples?: string[];
  /** @deprecated single substitute; prefer `suggestions`. */
  suggestion?: string;
  /** Benign substitutes the user can accept in one click. Substitutes, not report facts. */
  suggestions?: string[];
  /** Facts the report DOES give that bound this gap (shown as "原文已知"). Derived from IR, never invented. */
  known?: { field: string; value: unknown; source_ref?: string; epistemic_status?: EpistemicStatus; evidence_refs?: string[] }[];
  /** True when the gap is a choice for the user to make rather than a fact to recover from the report. */
  needs_user_decision?: boolean;
  /** Reliable jump target in the source PDF; only present when the backend is confident. */
  anchor?: { page: number; quote: string; evidence_ref?: string };
}

export interface Indicator {
  id: string;
  type: "ip" | "domain" | "url" | "hash" | "cve";
  value: string;
  source: Source;
  epistemic_status: EpistemicStatus;
  evidence_refs?: string[];
}

export interface CommandItem {
  id: string;
  interpreter: "powershell" | "cmd";
  command: string;
  source: Source;
  epistemic_status: EpistemicStatus;
  evidence_refs?: string[];
}

export interface Supplement {
  id: string;
  text: string;
  targets_missing_item?: string;
  source: Source;
  /** When the supplement fills a concrete field, it is written back to this host/service field. */
  host_id?: string;
  service_id?: string;
  field?: string;
  value?: string;
}

export interface EnvHostService { name: string; port: number; protocol?: "tcp" | "udp"; }
export interface VmGuest { os_family?: string; os_release?: string; image_ref?: string; image_digest?: string; cpu?: number; memory_mib?: number; disk_gib?: number; }
export interface EnvHost { id: string; role: string; image_hint?: string; services?: EnvHostService[]; networks: string[]; runtime?: "container" | "vm"; component_mode?: "real" | "substitute" | "unsupported" | "vm"; guest?: VmGuest; }
export interface EnvNetwork { id: string; segment?: string; internal?: boolean; }
export interface EnvConnection { from_host: string; to_host: string; port?: number; protocol?: "tcp" | "udp"; reason?: string; }
export interface EnvAccessRule { from?: string; to?: string; port?: number; action?: "allow" | "deny"; }

export interface EnvironmentPlan {
  hosts: EnvHost[];
  networks: EnvNetwork[];
  connections?: EnvConnection[];
  access_rules?: EnvAccessRule[];
  notes?: string[];
}

export interface Quality {
  quote_verified_rate?: number;
  unsupported_claim_count?: number;
  inferred_count?: number;
  absent_count?: number;
  method?: "single_pass" | "staged" | "staged_review";
  provisional?: boolean;
  /** Which quote grader produced the levels; lets stale scenarios be re-graded on read. */
  grader_version?: string;
}

export interface ValidationCheck {
  id: string;
  name: string;
  category: "service_up" | "connectivity" | "dependency_present" | "behavior" | "chain" | "version";
  status: CheckStatus;
  expected?: string;
  observed?: string;
  evidence?: string;
  action_ref?: string;
}

export interface ValidationReport {
  scenario_id?: string;
  deployment_id?: string;
  run_at?: string;
  levels: { env_build: CheckStatus; behavior_repro: CheckStatus; full_chain: CheckStatus };
  checks: ValidationCheck[];
  fidelity?: {
    reproduced?: string[];
    partial?: string[];
    not_reproduced?: string[];
    not_tested?: string[];
    substitutes_used?: { service_ref?: string; real?: string; substitute?: string; difference?: string }[];
    summary?: string;
  };
}

export type FlowScope = "incident" | "campaign" | "threat-actor" | "malware" | "emulation-plan" | "attack-tree" | "other";
export interface AttackFlowMetadata { name?: string; scope?: FlowScope; start_refs: string[]; description?: string; }
export interface AttackFlowCondition { id: string; description?: string; on_true_refs?: string[]; on_false_refs?: string[]; pattern?: string; pattern_type?: string; epistemic_status: EpistemicStatus; source: Source; evidence_refs?: string[]; }
export interface AttackFlowOperator { id: string; operator: "AND" | "OR"; effect_refs?: string[]; epistemic_status: EpistemicStatus; source: Source; evidence_refs?: string[]; }
export interface AttackFlowAsset { id: string; name?: string; description?: string; object_ref?: string; epistemic_status: EpistemicStatus; source: Source; evidence_refs?: string[]; }

export interface ScenarioIR {
  schema_version: "1.0";
  id: string;
  name: string;
  created_at?: string;
  updated_at?: string;
  ir_version?: number;
  provenance: { input_kind: "text" | "markdown" | "stix2.1"; input_sha256: string; source_name?: string; source_url?: string };
  evidence?: Evidence[];
  actions: Action[];
  relations: Relation[];
  indicators?: Indicator[];
  commands?: CommandItem[];
  flow?: AttackFlowMetadata;
  conditions?: AttackFlowCondition[];
  operators?: AttackFlowOperator[];
  assets?: AttackFlowAsset[];
  hosts?: Host[];
  services?: ServiceItem[];
  missing_items?: MissingItem[];
  supplements?: Supplement[];
  environment_plan?: EnvironmentPlan;
  quality?: Quality;
  deployments?: unknown[];
  validation?: ValidationReport;
}

// --- Module 9: PoC discovery, exploit validation & environment export ---
// Mirrors packages/contracts/schemas/poc-validation.schema.json.
// PocCheckStatus is CheckStatus plus BLOCKED (ownership/safety hard-stop); kept as a distinct
// name so module 8's CheckStatus and Evidence are untouched.
export type PocCheckStatus = "PASS" | "FAIL" | "PARTIAL" | "BLOCKED" | "NOT_TESTED";

export type PocStrategy = "poc_exec" | "config_check" | "log_check" | "not_executable";

export interface ValidationItem {
  action_id: string;
  target_host_ref?: string;
  service_ref?: string;
  cve?: string;
  attack_technique?: string;
  strategy: PocStrategy;
  poc_required: boolean;
  required_predecessors: string[];
  preconditions: string[];
  expected_evidence: string;
  /** Required when strategy === "not_executable". Such items never become PASS. */
  not_executable_reason?: string;
}

export interface ValidationPlan {
  scenario_id: string;
  generated_at: string;
  items: ValidationItem[];
}

export interface PocRef { commit_sha?: string; release?: string; }

export interface ScoreBreakdown {
  version: number;
  env: number;
  code_available: number;
  source_trust: number;
  exec_cost: number;
}

export interface PocCandidate {
  action_id: string;
  cve?: string;
  source: "github" | "exploitdb" | "nvd" | "vendor";
  source_url: string;
  ref: PocRef;
  product: string;
  version_range: string;
  language: string;
  dependencies: string[];
  preconditions: string[];
  exec_method: "python" | "bash" | "go" | "metasploit" | "http_seq" | "manual";
  license?: string;
  trust: "high" | "medium" | "low" | "unknown";
  last_updated?: string;
  compatibility_score: number;
  score_breakdown: ScoreBreakdown;
}

/** Ranked desc by compatibility_score. */
export interface PocManifest {
  scenario_id: string;
  generated_at: string;
  items: PocCandidate[];
}

export type PocEvidenceKind =
  | "exploit_effect" | "callback" | "file_written" | "shell_output"
  | "state_change" | "log" | "request" | "response";

export interface PocEvidence {
  kind: PocEvidenceKind;
  path: string;
  sha256: string;
  redacted: boolean;
  note?: string;
}

export interface ExecStages {
  started: boolean;
  delivered: boolean;
  responded: boolean;
  vuln_behavior: boolean;
  state_change: boolean;
  action_complete: boolean;
}

export interface ExecutionResult {
  action_id: string;
  poc: { source_url: string; ref: PocRef; sha256: string };
  status: PocCheckStatus;
  stages: ExecStages;
  evidence: PocEvidence[];
  exit_code?: number;
  logs_path: string;
  failure_reason?: string;
  confidence: number;
  target_ownership_verified: boolean;
  payload_sha256: string;
  started_at: string;
  ended_at: string;
}

export interface ChainTransfer {
  from_action: string;
  to_action: string;
  carried: "cred" | "session" | "network" | "token" | "artifact";
  verified: boolean;
  evidence_ref?: string;
}

export interface ChainValidation {
  scenario_id: string;
  objective_reached: boolean;
  passes: boolean;
  transfers: ChainTransfer[];
  order_ok: boolean;
  per_action: { action_id: string; status: PocCheckStatus }[];
}

export interface ExportFile { path: string; sha256: string; generated_by: string; }

export interface ExportManifest {
  scenario_id: string;
  scenario_version: string | number;
  created_at: string;
  files: ExportFile[];
  rebuildable: boolean;
  missing_for_rebuild: string[];
  contains_secrets: false;
}
