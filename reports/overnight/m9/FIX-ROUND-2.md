# Module 9 — Fix Round 2 (after round-2 independent QA CHANGES REQUESTED)

Round-2 QA (`reports/overnight/m9/review2/m9-review2.md`) confirmed round-1 fixes are genuinely real (not
gamed), and found 9 deeper issues. Acceptance bar = `reports/overnight/m9/review2/test_m9_review2.py` (14 failing)
+ `review2/check_web_review2.cjs` (4 failing), AND keep round-1 `review/test_m9_review.py` at 56/2 and the full
backend suite green. **Make YOUR cases pass without weakening them. No manufactured PASS; honest BLOCKED/not_executable
is fine.** Run backend tests with `PYTHONPATH=<your-worktree>/packages/contracts`.

Root cause of R2-02/R2-03b/R2-04/R2-09: the Lead's `service.execute` ran run_job PER ACTION (one job each), so
gating only saw in-set predecessors, cancel covered one job, and chain's latest-job selection dropped other valid
results. **Fix = ONE job per execute batch, with predecessor gating inside it.** Split:

## m9-runner (cr-codex-ultra) — apps/api/app/poc/runner/**
- **R2-04 / R2-02 mechanism:** `run_job` takes the full ordered request list and gates WITHIN ONE job:
  add `required_predecessors: tuple[str,...] = ()` to ExecutionRequest; iterate in given order maintaining a
  per-job status map; for a request whose ANY required predecessor is not PASS in THIS job (including a predecessor
  that is absent from the batch — deselected/not_executable/substitute), emit a BLOCKED result in the same job and
  `save_run` it, do NOT execute it. One job_id for the whole batch.
- **R2-03b cancel scope:** `cancel_execution` must stop ALL not-yet-started actions in the one job (cooperative
  flag checked before each action), so a later independent action does not start after a cancel.
- Keep real-transport fail-closed (local-docker BLOCKED), #1/#3/#4/#9/#11 behavior, and the log protocol. The
  guaranteed-cancel transport handle (#5/R2-03a) stays a deploy-layer follow-up — the reviewer confirms fail-closed
  is honest; do not fake it.

## Lead / service.py + deploy caps + store (I own these)
- **R2-02/R2-04 (service side):** build the FULL ordered request set for selected poc_exec+verifier items, set
  each request's `required_predecessors` from the plan (ALL declared, even predecessors that are not in the
  executable set), and call `run_job` ONCE. Remove the per-action loop. A dependent with an unmet declared
  predecessor must come back BLOCKED (from run_job), not executed.
- **R2-05:** `_service_for`/`_service_by_id` must resolve a service via the canonical `hosts[].service_refs`
  (schema relation), not only `service.host_ref`, so a normal IR reaches poc_exec instead of not_executable. If
  `planner/reproducibility.classify_action` also needs canonical resolution to avoid a wrong not_reproducible,
  make that minimal change too (Lead-owned module-4/5 file).
- **R2-06:** add `--memory`, `--cpus`, `--pids-limit` to the sandbox helper `docker run` at
  `deploy/manager.py` (PVE helper) and `deploy/backends/local_docker.py` helper launch. Additive hardening; assert
  via mock (no real run needed). Reviewer confirms this is NOT a hardware blocker.
- **R2-09:** `service.execute` BLOCKED results must be persisted (run_job now saves them). Empty-but-completed
  discovery must persist: `save_manifest(items=[])` leaves a record and `get_manifest` returns the empty manifest
  (not None), so export says "discovery recorded (0 candidates)" not "none".

## m9-export (cr-claude) — apps/api/app/poc/export/**
- **R2-01:** redact secrets in the NEW formats the fresh probes leak: URL password containing a quote
  (`https://u:pass'ok@h`), URL token-as-username with no colon (`https://<token>@h`), query token
  (`?access_token=<v>`), and the value in a secret-named field's `${VAR:?<literal>}` error-branch. Make redaction
  and the final scan field/URL-structure aware (userinfo + query + all interpolation branches); fail-closed
  (abort export + verify_bundle reports it) if a secret can't be confirmed removed. Keep the 23 green.

## m9-gui (cr-claude) — apps/web/src/pages/PocPage.tsx (+ i18n)
- **R2-03c:** Stop must keep polling GET /execute/status until a terminal job_state (or show an honest failure
  when cancel is rejected/errors); remove the i18n copy claiming continuous polling + cleanup that doesn't happen.
- **R2-08:** the unverified/readiness metric must count from CURRENT valid verification (chain.per_action /
  report.fidelity), not raw runner `status=='PASS'`; invalidated/unverified actions stay in the unverified count.
- Acceptance: `review2/check_web_review2.cjs` 6/6 and keep tsc clean.

## m9-discovery (cr-codex-ultra) — apps/api/app/poc/discovery/**
- **R2-07:** `engine.py:_version_hint` must PRESERVE range operators (after / `<` / before / through) before
  ranking; an unrecognised range stays unknown, never an exact-match high score. Make
  `test_discovery_preserves_range_operators_before_ranking` pass.

Report via hc send t31 when done. The Lead integrates, re-runs both review files + the full suite, then
re-dispatches the reviewer (round 3).
