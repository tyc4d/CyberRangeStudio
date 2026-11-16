# Brief: eval-run — run the system on all threat reports (2026-11-16)

Goal: real system output for a larger evaluation set. You only RUN and RECORD. Scoring is done later by two separate judges.

## Inputs
All folders in `fixtures/cti-candidates/` that have a `report.md` (11 new from agent/eval-cti + the existing ones). Skip folders without `report.md`. Do NOT open any `expected.md` (the answer keys) — you must stay blind to them.

## What to run
For each report, run modules 1–5 of the product as it is on this branch (= main + fixtures): analysis (attack steps, quotes, ATT&CK), gap analysis, dependency/topology planning, per-step reproducibility, and IaC generation/blocker result. Use the real LLM path (`apps/api/app/llm`, Budget Manager). Find the exact way the earlier runs were made in `reports/overnight/evidence/scenario-eng/` and the scenario-eng worker report, and use the same entry points/settings (same model and mode as those runs).
- **3 independent runs per report** (bypass the LLM cache for runs 2 and 3, or use a fresh data dir per run; record how).
- Use your own data dir, e.g. `CR_DATA_DIR=$PWD/.data-eval`. Never touch `apps/api/data/` of the main checkout.
- The OpenAI key is in `/home/tyc4d/cr-project/.env`; load it into the environment, never print it, never copy it into the worktree or logs.
- Total LLM spend cap for this task: **$10** (stop and report if you approach it).
- **No deployment.** Do not start Docker labs, VMs or Proxmox, and do not run probes.
- Do NOT change product code, prompts or settings. If the product crashes on a report, record the error as a result; do not fix it.

## Output
`reports/eval/runs/<report-id>/run-<n>/` with the same files as `after-r2` (00-input.txt, 00-units.json, 01-ir.json, 02-dependencies.json, 03-topology.json, plus IaC result/blockers), and `reports/eval/eval-run-summary.md`: per report × run — status, #attack steps, #hosts, #missing items, blocker yes/no, reproducibility counts, LLM cost, duration, errors. Also the commit SHA you ran and the exact command lines.

Commit on branch `agent/eval-run`. Do not merge, push or start other agents. When done or blocked: `hc send t31 "<one line + summary path>"`.
