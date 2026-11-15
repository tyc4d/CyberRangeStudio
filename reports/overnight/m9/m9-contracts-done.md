# m9-contracts — DONE

Branch `agent/m9-contracts`. The dependency skeleton for all other M9 workers is committed,
CONTRACT-conformant, and tested. No files outside my owned set were edited.

## Delivered
- `packages/contracts/schemas/poc-validation.schema.json` — all 8 CONTRACT shapes exactly:
  ValidationPlan, ValidationItem, PocCandidate, PocManifest, ExecutionResult, Evidence,
  ChainValidation, ExportManifest (+ CheckStatus incl. BLOCKED). Root validates a ValidationPlan;
  `not_executable` enforces `not_executable_reason`; `contains_secrets` fixed to `false`.
- `packages/contracts/cr_contracts/__init__.py` — registered `"poc-validation"` so
  `iter_errors("poc-validation", obj)` works; added `iter_errors_shape(shape, obj)` /
  `validate_shape(shape, obj)` + `POC_SHAPES` so each worker can validate its own shape
  (e.g. `iter_errors_shape("PocManifest", m)`).
- `packages/contracts/src/types.ts` — TS mirror of every shape. Named `PocCheckStatus`,
  `PocEvidence`, `PocEvidenceKind` to avoid clobbering module 8's existing `CheckStatus`/`Evidence`.
- `apps/api/app/poc/{__init__,models,store,service}.py` + `apps/api/app/routers/poc.py`.
  - store.py: 5 SQLite tables (poc_plans, poc_candidates, poc_runs, poc_chains, poc_exports)
    under DATA_DIR/poc.db, plus a `poc_jobs` table (state/cancel/timeout) for GUI polling.
    Evidence raw bytes never stored here — only paths (CONTRACT §Evidence).
  - service.py: **plan() is real** (no stub) — maps planner.reproducibility.classify_action →
    strategy: reproducible+exploit→poc_exec; reproducible+non-exploit→config_check;
    substitute_only→config_check; needs_vm/not_reproducible→not_executable (reason carried;
    never becomes PASS). Only dependency relations count as required_predecessors (temporal excluded).
    discover/execute/chain/report/export raise NotImplementedError for their owners.
  - routers/poc.py: 6 CONTRACT routes under `/api/poc`. `plan` is wired to service.plan;
    discover/execute/chain/report/export return HTTP 501 for their owners.

## Tests — all green
`apps/api/app/poc/test_contracts.py` (15 tests): schema accepts valid shapes & rejects malformed
(bad strategy, missing not_executable_reason, bad status, contains_secrets=true); plan() is
schema-valid and maps every reproducibility class correctly; dependency-only predecessors; persistence.

Run: `PYTHONPATH=packages/contracts:apps/api .venv/bin/python -m pytest apps/api/app/poc/test_contracts.py -q`
→ 15 passed. Full `apps/api` suite: **135 passed** (no regressions).

NOTE: the installed editable `cr-contracts` points at the MAIN checkout, so tests need
`packages/contracts` FIRST on PYTHONPATH to pick up this worktree's schema until merged.

## Lead action needed
`reports/overnight/m9/requests/m9-contracts.md`: add one line to main.py ROUTER_STATUS
(`"poc": _safe_include("app.routers.poc")`). I did not edit main.py (Lead-owned).
