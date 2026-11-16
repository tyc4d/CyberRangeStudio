# Module 9 — API & Safety Contract (authoritative interface)

All workers conform to this. Shapes are the source of truth; m9-contracts turns them into JSON Schema +
`types.ts` and the `poc/models.py` dataclasses. Statuses reuse the existing `CheckStatus`:
`PASS | FAIL | PARTIAL | BLOCKED | NOT_TESTED`.

## Data shapes
**ValidationPlan** (m9-contracts schema; produced by poc/service from the IR):
`{scenario_id, generated_at, items: ValidationItem[]}`
**ValidationItem**: `{action_id, target_host_ref, service_ref, cve?, attack_technique?,
strategy: "poc_exec"|"config_check"|"log_check"|"not_executable", poc_required: bool,
required_predecessors: action_id[], preconditions: string[], expected_evidence: string,
not_executable_reason?: string}`
- `not_executable` is set upfront for: closed-source/appliance with no image, needs-VM image we lack, no
  compatible PoC, or `reproducibility ∈ {not_reproducible}`. These NEVER later become PASS.

**PocCandidate** (m9-discovery): `{action_id, cve?, source: "github"|"exploitdb"|"nvd"|"vendor",
source_url, ref: {commit_sha?|release?}, product, version_range, language, dependencies: string[],
preconditions: string[], exec_method: "python"|"bash"|"go"|"metasploit"|"http_seq"|"manual",
license?, trust: "high"|"medium"|"low"|"unknown", last_updated?, compatibility_score: 0..1,
score_breakdown: {version, env, code_available, source_trust, exec_cost}}`
**PocManifest**: `{scenario_id, generated_at, items: PocCandidate[]}`. Ranked desc by compatibility_score.
Rule: name-contains-CVE is NOT sufficient; score version/product/preconditions. Never execute here.

**ExecutionResult** (m9-runner): `{action_id, poc: {source_url, ref, sha256}, status,
stages: {started, delivered, responded, vuln_behavior, state_change, action_complete}  // all bool,
evidence: Evidence[], exit_code?, logs_path, failure_reason?, confidence: 0..1,
target_ownership_verified: bool, payload_sha256, started_at, ended_at}`
- `status = PASS` ⇔ `vuln_behavior == true` backed by ≥1 Evidence of kind that proves the exploit effect.
  `delivered && responded` but no `vuln_behavior` ⇒ `FAIL`. Ownership not verified ⇒ `BLOCKED` (no execution).
**Evidence**: `{kind: "exploit_effect"|"callback"|"file_written"|"shell_output"|"state_change"|"log"|"request"|"response",
path, sha256, redacted: bool, note}` — secrets/creds redacted; raw stored under DATA_DIR artifacts, never in DB text.

**ChainValidation** (m9-chain): `{scenario_id, objective_reached: bool, passes: bool,
transfers: {from_action, to_action, carried: "cred"|"session"|"network"|"token"|"artifact", verified: bool, evidence_ref}[],
order_ok: bool, per_action: {action_id, status}[]}`
- Chain PASS ⇔ every required action PASS AND every required transfer verified AND order follows relations[].
  A chain is never PASS from independent per-action PASSes alone.

**FidelityReport** reuses existing `validation-report.schema.json` levels `{env_build, behavior_repro,
full_chain}` + `fidelity{reproduced,partial,not_reproduced,not_tested,substitutes_used}`. Keep the 5 metrics
separate; never merge into one success rate.

**ExportManifest** (m9-export): `{scenario_id, scenario_version, created_at, files: {path, sha256, generated_by}[],
rebuildable: bool, missing_for_rebuild: string[], contains_secrets: false}`. ZIP layout per the owner's prompt
(scenario/ infrastructure/ validation/ evidence/ manifest.json + README.md). Only REAL generated IaC is included;
absent images/licensed material listed in `missing_for_rebuild`; `rebuildable=false` if any are missing. Never
write real passwords/tokens/keys — emit `.env.example` with placeholders.

## HTTP API (router `routers/poc.py`, prefix `/api/poc`; m9-contracts stubs → 501, owners fill)
- `POST /api/poc/{scenario_id}/plan` → ValidationPlan (poc/service, uses planner/reproducibility)
- `POST /api/poc/{scenario_id}/discover` → PocManifest (m9-discovery)
- `POST /api/poc/{scenario_id}/execute` body `{action_ids?[]}` → ExecutionResult[] (m9-runner; auto-runs, gated)
- `POST /api/poc/{scenario_id}/chain` → ChainValidation (m9-chain)
- `GET  /api/poc/{scenario_id}/report` → FidelityReport (m9-chain aggregates runner+chain)
- `POST /api/poc/{scenario_id}/export` → `{bundle_path, manifest}` (m9-export)
Persistence: `poc/store.py` SQLite tables `poc_plans, poc_candidates, poc_runs, poc_chains, poc_exports`
(separate file under DATA_DIR, like deployments/validation). Long runs are synchronous like module 8 but must
support a `cancel` flag + timeout; record a `job` row with state for the GUI to poll.

## Safety (m9-runner MUST implement; m9-review MUST verify)
1. **Ownership guard before any payload** — `poc/runner/guard.py:assert_target_owned(scenario_id, target)`:
   resolve the target to a container/VM that THIS scenario's deployment record created (match deployment
   labels/records from `deploy/manager.records`), confirm it is on an isolated/internal network, and confirm it
   is NOT in the protected set. Hard-block list (never target, even if asked): PVE VMIDs 501, 2001, 2002,
   3001-3004, 80000, 80001, anything not in pool `cr-range`, and any host not created by this deployment. On any
   doubt → return BLOCKED, do not execute. (PVE is not wired yet; still encode the guard so it is safe when it is.)
2. **Sandboxed execution** — reuse the `deploy/manager.probe_in_service` pattern: ephemeral, non-root,
   `--network container:<target>` (shares only the target's netns), `--pull=never`, no bind of host paths,
   resource + time limits, guaranteed cleanup (`--rm` + finally-kill). No execution on the platform host.
3. **Pinned third-party code** — every external PoC pinned by commit SHA + recorded sha256; dependencies vendored
   or installed only inside the sandbox; NEVER pipe a remote install script to a shell; no silent `curl|bash`.
4. **No outbound internet** from the sandbox except the in-lab callback listener (`cr-listener`) on the isolated
   net. No lateral reach to non-experiment segments; no host privilege.
5. **No environment tampering to force success** — do not open firewalls, add vulnerabilities, change the target
   image, or alter the scenario's requirements to make a test pass. If the env genuinely needs a change, write a
   request note + message the Lead.
6. **No secrets in reports** — redact credentials/tokens; never read real production creds.
7. Timeout, resource cap, emergency stop, and cleanup on every path including error/cancel.

If a PoC cannot be run safely under these rules → `BLOCKED` with the reason + the manual step needed. Never
relax a rule to get a green result.
