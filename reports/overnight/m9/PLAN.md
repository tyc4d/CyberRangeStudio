# Module 9 — PoC Discovery, Exploit Validation & Environment Export — Integration Plan

Owner-approved 2026-11-16. Base branch: `agent/m9-base` (off `agent/claude-mobile-rwd` 48027af = main + finished
mobile RWD + i18n). Lead = Claude session t31. Workers each own a disjoint file set; the Lead integrates and
owns the shared-file edits. **Read `CONTRACT.md` in this folder before writing any code — it is the interface
and the safety contract. Do not deviate from it; if it is wrong, message the Lead (hc send t31), do not freelance.**

## Non-negotiables (from the owner)
1. **Real payloads only.** Every target that reaches the execution path gets a real payload; `PASS` requires
   concrete exploit evidence (OGNL arithmetic echoed, in-lab LDAP callback received, file written, shell output).
   HTTP 200, container-up, health check, or an LLM opinion is NOT success. See CONTRACT §Evidence.
2. **No faked success.** A real payload that does not exploit the target = `FAIL`. Targets that genuinely cannot
   be exploited (closed-source appliance, needs a VM image we do not have, no compatible PoC) are classified
   `not_executable` in the ValidationPlan **before** execution and reported honestly — never fake-`PASS`. This
   is the Lead's standing ruling; only the owner may override it.
3. **Ownership-gated execution.** A payload may hit ONLY a target this scenario's own deployment created, in the
   isolated network. Ownership is verified before every execution. Protected machines and anything outside our
   own pool are hard-blocked. See CONTRACT §Safety. This holds even though PoCs auto-run without per-PoC approval.
4. Reuse Scenario IR + modules 1–8; do NOT build a second scenario model or refactor other modules.

## Reality corrections from the repo map (believe these over the prompt)
- **No Proxmox/PVE code exists.** Deployment = Docker Compose (`deploy/manager.py`) + libvirt/KVM VM
  (`deploy/vm.py`). Module 9 targets those two runtimes only. (PVE is future work, not this module.)
- **No MCP interface.** Do not try to reuse one.
- Real exploit precedent already in `apps/api/app/validator/runner.py`: `_struts_s2045_probe`,
  `_log4shell_solr_probe`, run via `deploy/manager.py:probe_in_service` (namespace-scoped, non-root, ephemeral
  container sharing only the target's network namespace). **This is the execution-isolation pattern to reuse.**
- Real PoC assets + runners already exist under `tests/e2e/phase3-real-poc/` (guard.py, poc_common.py,
  run_struts_s2045.py, run_log4shell_solr.py) and `tests/e2e/log4shell-callback/`. Reuse, don't reinvent.

## File ownership (disjoint — do not edit outside your set)
| Worker | Template | Owns (create/edit only here) |
|---|---|---|
| **m9-contracts** | cr-claude | `packages/contracts/**` (new `poc-validation.schema.json`, extend types.ts); scaffold only: `apps/api/app/poc/__init__.py`, `poc/models.py`, `poc/store.py` (shared SQLite for poc tables), `poc/service.py` (orchestration stubs), and an empty `routers/poc.py` with the documented routes returning 501. Commits the skeleton the others build on. |
| **m9-discovery** | **cr-codex** | `apps/api/app/poc/discovery/**` + its unit tests. PoC Discovery Engine + Ranking. READ-ONLY external calls; NEVER executes a PoC. |
| **m9-runner** | **cr-codex** | `apps/api/app/poc/runner/**` + e2e under `tests/e2e/m9-runner/`. Adapters + Sandbox Runner + real payload execution + ownership guard. Reuses `deploy/manager.probe_in_service` by import (do not edit manager.py). |
| **m9-chain** | **cr-codex** | `apps/api/app/poc/chain/**` + tests. Evidence verification + attack-chain DAG + fidelity roll-up. |
| **m9-export** | cr-claude | `apps/api/app/poc/export/**` + `tests/.../test_export*.py`. ZIP bundle builder. |
| **m9-gui** | cr-claude | `apps/web/src/pages/PocPage.tsx` (new), one method in `apps/web/src/lib/api.ts`, one `STAGES` entry in `apps/web/src/App.tsx`. Reuse `components/ui.tsx`, `VersionBasis.tsx`. |
| **m9-review** | **cr-codex-ultra** | read-only QA; writes only `reports/overnight/m9/review/**`. |

**Lead owns at integration:** `apps/api/app/main.py` (ROUTER_STATUS registration), and any real edit to
modules 1–8 files (`validator/runner.py`, `deploy/manager.py`, `planner/reproducibility.py`, `store.py`). If a
worker needs a change in those, it writes a request note in `reports/overnight/m9/requests/<worker>.md` and
messages the Lead — it does not edit them.

## Dispatch order
1. **m9-contracts first** — commits the skeleton + CONTRACT-conformant schema. Lead merges it into `agent/m9-base`.
2. Then **m9-discovery, m9-runner, m9-chain, m9-export, m9-gui** in parallel off the updated `agent/m9-base`.
3. **m9-review (cr-codex-ultra)** after the five report done; then Lead integrates, runs full QA, iterates.
4. **Demo video** (owner: "跟之前的 prompt 一樣", OneTake, `artifacts/demo-video/`) starts ONLY after dev + QA pass.

## Acceptance (Lead verifies before declaring done) — from the owner's §11
Known vuln + compatible PoC → discovered & really exploited (evidence). Version-incompatible → not PASS.
No PoC → honest not-executable with reason. Predecessor FAIL → dependents not PASS. Timeout/err/missing-dep →
safe stop + cleanup, no leftover containers/secrets. PoC cannot reach a non-authorized target. Evidence traces
to action+PoC+deployment. Export ZIP has real IaC + manifests and redeploys on a clean isolated box. Tests
include success AND failure cases; ≥1 multi-action multi-service real end-to-end. Blocked-by-environment is
recorded as blocked, never PASS.
