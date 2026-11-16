# eval-run: system output on 17 threat reports × 3 runs (2026-11-16)

Raw output only. **No scoring was done.** `expected.md` files were not opened.

## How the runs were made
- Product code: commit `fbfd050aa3b4bf9400145b296303547122b10611` (branch `agent/eval-run` = main + eval-cti fixtures + brief). Product code, prompts and settings were not changed.
- Inputs: the 17 folders in `fixtures/cti-candidates/` that have `report.md`. All 17 have one (`aa23-289a` has no `expected.md`, which does not matter here).
- Modules 1, 2, 4, 5 use the same entry point and settings as the scenario-eng `after-r2` runs: `reports/overnight/evidence/scenario-eng/run_real.py <report.md> markdown single_pass <out> <id>`, unchanged. Model `gpt-4.1-mini` (default `CR_MODEL_CHEAP`), single_pass. Budget Manager caps are set by run_real.py (hard cap $5 / stop-new $4 for each data dir). Every run made the same 3 LLM calls: `cti_analysis_single_pass`, `cti_analysis_context`, `cti_analysis_relations`.
- Module 6 (IaC): `app.iac.generator.inspect_plan(03-topology.json, "evidence")`. If the plan is deployable, `compose_document` also writes `04-docker-compose.yml`. These calls only build and check the plan in memory. Nothing was deployed, and no Docker, VM, Proxmox or probe was started.
- Cache independence: **each report × run has its own new `CR_DATA_DIR`** (`.data-eval/run-<n>/<report-id>`, not committed). The runner checks that `llm_cache.db` does not exist yet, so no run can reuse another run's LLM cache. Result: 0 cached calls in all 51 runs (from the ledgers).
- The OpenAI key is loaded from `/home/tyc4d/cr-project/.env` by run_real.py. It is not in the worktree or in the logs.
- Wrapper: `reports/eval/run_eval.py` (no LLM calls of its own). Table: `reports/eval/summarize.py`.

Exact command lines:
```sh
P=/home/tyc4d/cr-project/.venv/bin/python
# one report × run (what run_eval.py does):
CR_DATA_DIR=.data-eval/run-<n>/<id> $P reports/overnight/evidence/scenario-eng/run_real.py fixtures/cti-candidates/<id>/report.md markdown single_pass reports/eval/runs/<id>/run-<n> <id>
# then the module-6 check: inspect_plan / compose_document on reports/eval/runs/<id>/run-<n>/03-topology.json
# batch: for n in 1 2 3 (in parallel); for each id: $P reports/eval/run_eval.py <id> <n>
$P reports/eval/summarize.py
```
Each run's exact command is also in `runs/<id>/run-<n>/run.log` and `meta.json`.

## Files for each run (`reports/eval/runs/<id>/run-<n>/`)
`00-input.txt`, `00-units.json`, `01-ir.json` (module 1: steps, quotes, ATT&CK, module-1 missing items), `02-dependencies.json` (module 2/4 gaps + per-step `reproducibility` + `fidelity`), `03-topology.json` (module 5 environment plan), `04-iac-report.json` (module 6 result + `blockers`), `04-docker-compose.yml` (only when deployable), `meta.json` (status, time, LLM calls/tokens/cost, errors), `run.log` (stdout/stderr).

## Totals
- 51/51 runs finished with no crash and no errors. IR schema errors: none.
- Total LLM cost (Budget Manager estimate, prices set on the high side on purpose): **$1.91** of the $10 cap.
- IaC blocked in 36/51 runs. Blocker codes: `no_deployable_target` ×36, `port_not_served_by_image` ×2, `missing_backing_service` ×1. Some runs have more than one code, so the codes add up to more than 36.
- IaC deployable in 15/51 runs: equifax 3/3, androxgh0st 3/3, ivanti 3/3, teamcity 2/3, clop 1/3.
- The results change between runs even with temperature 0. For example, teamcity, clop and the IaC result change, and aa22-257a has 20/24/12 steps across its 3 runs.

## Column meanings
- #steps = IR actions. #hosts IR = IR hosts. #hosts env plan = hosts in the environment plan; this count includes the attacker host.
- #missing IR = module-1 missing items. #missing after mod 4 = all missing items after dependency planning. #open blocker-severity = open items with `severity=blocker`.
- IaC blocked = `04-iac-report.json` has `deployable=false`; the number in brackets is how many blockers it has.
- Reproducibility = per-step counts from `02-dependencies.json`. Fidelity = the worst value over the required steps.

| report | run | status | #steps (IR actions) | #hosts IR | #hosts env plan | #missing IR (mod 1) | #missing after mod 4 | #open blocker-severity items | IaC blocked (#blockers) | reproducibility per step | fidelity | LLM $ | sec | errors |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| aa22-074a-russia-mfa-printnightmare | 1 | ok | 11 | 3 | 4 | 13 | 17 | 0 | yes (1) | needs_vm:10 not_reproducible:1 | not_reproducible | 0.0293 | 52.3 |  |
| aa22-074a-russia-mfa-printnightmare | 2 | ok | 11 | 2 | 3 | 10 | 14 | 0 | yes (1) | needs_vm:11 | needs_vm | 0.0271 | 44.5 |  |
| aa22-074a-russia-mfa-printnightmare | 3 | ok | 10 | 3 | 4 | 13 | 17 | 0 | yes (1) | needs_vm:9 not_reproducible:1 | not_reproducible | 0.0275 | 50.0 |  |
| aa22-257a-irgc-log4j-horizon | 1 | ok | 20 | 6 | 7 | 24 | 27 | 0 | yes (1) | needs_vm:1 not_reproducible:19 | not_reproducible | 0.0375 | 53.7 |  |
| aa22-257a-irgc-log4j-horizon | 2 | ok | 24 | 4 | 5 | 17 | 20 | 0 | yes (1) | needs_vm:1 not_reproducible:23 | not_reproducible | 0.0428 | 67.5 |  |
| aa22-257a-irgc-log4j-horizon | 3 | ok | 12 | 7 | 8 | 24 | 28 | 0 | yes (1) | needs_vm:1 not_reproducible:11 | not_reproducible | 0.0402 | 67.6 |  |
| aa22-320a-log4shell-horizon | 1 | ok | 17 | 4 | 5 | 24 | 29 | 0 | yes (1) | needs_vm:11 not_reproducible:6 | not_reproducible | 0.0441 | 75.3 |  |
| aa22-320a-log4shell-horizon | 2 | ok | 16 | 4 | 5 | 24 | 28 | 0 | yes (1) | needs_vm:3 not_reproducible:13 | not_reproducible | 0.0457 | 77.5 |  |
| aa22-320a-log4shell-horizon | 3 | ok | 14 | 4 | 5 | 25 | 29 | 0 | yes (1) | needs_vm:7 not_reproducible:7 | not_reproducible | 0.0398 | 66.1 |  |
| aa23-144a-volt-typhoon-lotl | 1 | ok | 9 | 2 | 3 | 11 | 18 | 0 | yes (1) | needs_vm:9 | needs_vm | 0.0400 | 43.6 |  |
| aa23-144a-volt-typhoon-lotl | 2 | ok | 9 | 2 | 3 | 9 | 18 | 0 | yes (1) | needs_vm:9 | needs_vm | 0.0427 | 50.6 |  |
| aa23-144a-volt-typhoon-lotl | 3 | ok | 9 | 2 | 3 | 8 | 15 | 0 | yes (1) | needs_vm:9 | needs_vm | 0.0409 | 48.5 |  |
| aa23-158a-clop-moveit | 1 | ok | 8 | 1 | 2 | 5 | 10 | 0 | no | not_reproducible:8 | not_reproducible | 0.0228 | 30.7 |  |
| aa23-158a-clop-moveit | 2 | ok | 6 | 1 | 2 | 4 | 6 | 0 | yes (1) | not_reproducible:6 | not_reproducible | 0.0209 | 34.6 |  |
| aa23-158a-clop-moveit | 3 | ok | 6 | 1 | 2 | 4 | 6 | 0 | yes (1) | not_reproducible:6 | not_reproducible | 0.0220 | 26.5 |  |
| aa23-250a-manageengine-fortinet | 1 | ok | 34 | 5 | 6 | 22 | 28 | 0 | yes (1) | needs_vm:5 not_reproducible:29 | not_reproducible | 0.0761 | 116.7 |  |
| aa23-250a-manageengine-fortinet | 2 | ok | 24 | 5 | 6 | 21 | 26 | 0 | yes (1) | needs_vm:18 not_reproducible:6 | not_reproducible | 0.0633 | 91.1 |  |
| aa23-250a-manageengine-fortinet | 3 | ok | 32 | 5 | 6 | 21 | 27 | 0 | yes (1) | needs_vm:2 not_reproducible:30 | not_reproducible | 0.0669 | 95.0 |  |
| aa23-289a-confluence-cve-2023-22515 | 1 | ok | 5 | 1 | 2 | 6 | 7 | 0 | yes (1) | not_reproducible:5 | not_reproducible | 0.0168 | 22.7 |  |
| aa23-289a-confluence-cve-2023-22515 | 2 | ok | 3 | 1 | 2 | 6 | 7 | 0 | yes (1) | not_reproducible:3 | not_reproducible | 0.0155 | 20.2 |  |
| aa23-289a-confluence-cve-2023-22515 | 3 | ok | 4 | 1 | 2 | 5 | 6 | 0 | yes (1) | not_reproducible:4 | not_reproducible | 0.0151 | 17.5 |  |
| aa23-347a-svr-teamcity-cve-2023-42793 | 1 | ok | 28 | 4 | 5 | 16 | 22 | 0 | no | needs_vm:12 not_reproducible:16 | not_reproducible | 0.0713 | 104.5 |  |
| aa23-347a-svr-teamcity-cve-2023-42793 | 2 | ok | 26 | 2 | 3 | 13 | 21 | 0 | yes (1) | needs_vm:4 not_reproducible:21 reproducible:1 | not_reproducible | 0.0678 | 110.5 |  |
| aa23-347a-svr-teamcity-cve-2023-42793 | 3 | ok | 30 | 4 | 5 | 12 | 18 | 0 | no | needs_vm:22 not_reproducible:8 | not_reproducible | 0.0720 | 108.9 |  |
| aa24-016a-androxgh0st | 1 | ok | 14 | 4 | 5 | 16 | 21 | 0 | no | not_reproducible:12 reproducible:2 | not_reproducible | 0.0292 | 47.3 |  |
| aa24-016a-androxgh0st | 2 | ok | 24 | 3 | 4 | 13 | 19 | 0 | no | not_reproducible:23 reproducible:1 | not_reproducible | 0.0421 | 79.0 |  |
| aa24-016a-androxgh0st | 3 | ok | 23 | 4 | 5 | 17 | 23 | 0 | no | not_reproducible:22 reproducible:1 | not_reproducible | 0.0394 | 67.0 |  |
| aa24-046a-former-employee-account | 1 | ok | 10 | 5 | 6 | 17 | 22 | 0 | yes (1) | needs_vm:8 not_reproducible:2 | not_reproducible | 0.0286 | 49.3 |  |
| aa24-046a-former-employee-account | 2 | ok | 5 | 4 | 5 | 16 | 21 | 0 | yes (1) | needs_vm:5 | needs_vm | 0.0259 | 41.0 |  |
| aa24-046a-former-employee-account | 3 | ok | 8 | 4 | 5 | 16 | 20 | 0 | yes (1) | needs_vm:8 | needs_vm | 0.0307 | 49.2 |  |
| aa24-249a-gru-confluence-cve-2022-26134 | 1 | ok | 41 | 7 | 8 | 25 | 36 | 0 | yes (1) | needs_vm:5 not_reproducible:35 reproducible:1 | not_reproducible | 0.0830 | 127.9 |  |
| aa24-249a-gru-confluence-cve-2022-26134 | 2 | ok | 40 | 5 | 6 | 21 | 31 | 0 | yes (1) | needs_vm:3 not_reproducible:36 reproducible:1 | not_reproducible | 0.0723 | 111.8 |  |
| aa24-249a-gru-confluence-cve-2022-26134 | 3 | ok | 43 | 5 | 6 | 19 | 31 | 0 | yes (1) | needs_vm:5 not_reproducible:38 | not_reproducible | 0.0790 | 137.0 |  |
| aa24-290a-iran-bruteforce | 1 | ok | 22 | 3 | 4 | 15 | 24 | 0 | yes (1) | needs_vm:7 not_reproducible:15 | not_reproducible | 0.0424 | 73.7 |  |
| aa24-290a-iran-bruteforce | 2 | ok | 22 | 3 | 4 | 14 | 21 | 0 | yes (1) | needs_vm:7 not_reproducible:15 | not_reproducible | 0.0403 | 65.7 |  |
| aa24-290a-iran-bruteforce | 3 | ok | 24 | 3 | 4 | 13 | 20 | 0 | yes (1) | needs_vm:6 not_reproducible:18 | not_reproducible | 0.0445 | 72.3 |  |
| aa25-022a-ivanti-csa-chain | 1 | ok | 20 | 4 | 5 | 14 | 19 | 0 | no | not_reproducible:20 | not_reproducible | 0.0415 | 61.1 |  |
| aa25-022a-ivanti-csa-chain | 2 | ok | 17 | 2 | 3 | 7 | 10 | 0 | no | not_reproducible:17 | not_reproducible | 0.0462 | 73.4 |  |
| aa25-022a-ivanti-csa-chain | 3 | ok | 20 | 3 | 4 | 11 | 17 | 0 | no | not_reproducible:20 | not_reproducible | 0.0422 | 69.0 |  |
| equifax-2017-struts-db | 1 | ok | 8 | 2 | 3 | 11 | 13 | 0 | no | not_reproducible:5 reproducible:3 | not_reproducible | 0.0309 | 44.8 |  |
| equifax-2017-struts-db | 2 | ok | 8 | 2 | 3 | 11 | 13 | 0 | no | not_reproducible:5 reproducible:3 | not_reproducible | 0.0296 | 45.0 |  |
| equifax-2017-struts-db | 3 | ok | 8 | 3 | 4 | 13 | 17 | 0 | no | not_reproducible:5 reproducible:3 | not_reproducible | 0.0306 | 44.2 |  |
| negative-insufficient-intel | 1 | ok | 5 | 3 | 4 | 13 | 14 | 2 | yes (1) | not_reproducible:5 | not_reproducible | 0.0112 | 19.6 |  |
| negative-insufficient-intel | 2 | ok | 5 | 3 | 4 | 12 | 13 | 2 | yes (1) | not_reproducible:5 | not_reproducible | 0.0123 | 22.1 |  |
| negative-insufficient-intel | 3 | ok | 5 | 3 | 4 | 13 | 14 | 2 | yes (1) | not_reproducible:5 | not_reproducible | 0.0132 | 23.3 |  |
| weak-aa21-042a-water-facility | 1 | ok | 14 | 2 | 3 | 12 | 16 | 0 | yes (1) | needs_vm:3 not_reproducible:11 | not_reproducible | 0.0230 | 34.4 |  |
| weak-aa21-042a-water-facility | 2 | ok | 11 | 2 | 3 | 12 | 16 | 0 | yes (1) | needs_vm:2 not_reproducible:9 | not_reproducible | 0.0226 | 38.0 |  |
| weak-aa21-042a-water-facility | 3 | ok | 12 | 2 | 3 | 10 | 14 | 0 | yes (1) | needs_vm:8 not_reproducible:4 | not_reproducible | 0.0240 | 42.2 |  |
| weak-pin-20221104-hacktivist-ddos | 1 | ok | 5 | 3 | 4 | 11 | 12 | 1 | yes (1) | not_reproducible:5 | not_reproducible | 0.0117 | 16.6 |  |
| weak-pin-20221104-hacktivist-ddos | 2 | ok | 6 | 3 | 4 | 11 | 12 | 1 | yes (1) | not_reproducible:6 | not_reproducible | 0.0133 | 19.7 |  |
| weak-pin-20221104-hacktivist-ddos | 3 | ok | 5 | 3 | 4 | 11 | 12 | 1 | yes (1) | not_reproducible:5 | not_reproducible | 0.0118 | 16.6 |  |
