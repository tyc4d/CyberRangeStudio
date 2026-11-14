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
  target_host_ref?: string;
  evidence_refs?: string[];
  epistemic_status: EpistemicStatus;
  source: Source;
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
}

export interface Host {
  id: string;
  role: string;
  os?: string;
  os_version?: string;
  service_refs?: string[];
  epistemic_status?: EpistemicStatus;
  source?: Source;
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
}

export interface Supplement {
  id: string;
  text: string;
  targets_missing_item?: string;
  source: Source;
}

export interface EnvHostService { name: string; port: number; protocol?: "tcp" | "udp"; }
export interface EnvHost { id: string; role: string; image_hint?: string; services?: EnvHostService[]; networks: string[]; }
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
}

export interface ValidationCheck {
  id: string;
  name: string;
  category: "service_up" | "connectivity" | "dependency_present" | "behavior" | "chain";
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
