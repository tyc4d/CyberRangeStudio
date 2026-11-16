# Brief: eval-100 — 100 real CTI reports, full cycle, per-case report (2026-11-17)

Owner (going to sleep, autonomous): test 100 cases through the system, up to $100 API budget, a COMPLETE cycle
per case, and a report PER case. Each report must include the HOSTS and TOPOLOGY the system produces, and whether
those services can be validated using an online PoC.

## Inputs
100 reports from `fixtures/cti-corpus/<id>/report.md` (231 available). Pick the first 100 in sorted id order;
record which 100 in the summary. Do NOT open any `expected.md`.

## Per-case full cycle (run the real system, no stubs)
For each report, run the SAME pipeline the product uses, then add inventory + PoC discovery:
1. Analysis + deps + topology: `reports/overnight/evidence/scenario-eng/run_real.py <report.md> markdown single_pass <out> <id>`
   (modules 1,2,4,5 -> 01-ir.json, 02-dependencies.json, 03-topology.json). Model gpt-4.1-mini, single_pass, unchanged.
2. IaC check (module 6): `app.iac.generator.inspect_plan(03-topology.json, <id>)` for deployable/blockers. No deploy.
3. Inventory resolution per service: `app.planner.inventory.resolve(name, version, cve, attack_technique)` ->
   tier (have/obtainable/unavailable), component_id, is_substitute, version_basis, reproduces_cve, needs_question.
4. PoC discovery per service/action with a CVE or product: `app.poc.discovery.discover(<id>, ir)` -> PocManifest.
   This hits GitHub/Exploit-DB/NVD (network). GitHub token from /home/tyc4d/cr-project/.env if present; degrade
   gracefully + record rate-limit/unauth. Record per candidate: source, source_url, ref, compatibility_score.

## Per-case report  reports/eval-100/cases/<id>.md
- Header: id, title, publisher, date, source URL.
- HOSTS: table of each host (id, role, os/os_version, deployable yes/no + reason).
- TOPOLOGY: networks (id, internal), connections, zones/segments, which hosts are in deployment vs not_deployed.
- SERVICES: table per service — name, version (+basis), CVE(s), inventory tier, chosen component / substitute,
  reproduces_cve; and **PoC-validatable?**: `deployable` (inventory have/obtainable AND a real PoC/vulhub image)
  / `substitute` (same CVE on a different product image) / `online-PoC-only` (a real online PoC exists but no
  deployable image here) / `no` (no PoC/image). Include the top online PoC URL found, if any.
- One honest line: what was NOT done (we did not deploy+exploit this case; actual live exploit is proven
  separately for Struts S2-045 on the PVE farm — cite reports, don't re-run 100 live).

## Aggregate  reports/eval-100/SUMMARY.md
Table of all 100 (id, #hosts, #services, deployable hosts, any PoC-validatable service y/n, tier mix). Totals:
how many of 100 produced a deployable lab; how many have >=1 service that is deployable/substitute/online-PoC/no;
PoC-found rate; inventory tier distribution; crashes/blocked. State plainly: these are PLAN + DISCOVERY results;
only the deployable/substitute subset could be truly validated, and a real live exploit was separately proven for
Struts S2-045. NO invented numbers — every number computed from the run files.

## Budget + rules
- Use a FRESH CR_DATA_DIR per report (e.g. .data-eval100/<id>) so no LLM cache is reused; check 0 cached calls.
- Run `CR_BUDGET_HARD_CAP_USD=20 CR_BUDGET_STOP_NEW_USD=18` (well under the $100 the owner allowed; analysis is
  ~$0.03/report so ~$3-5 total). If spend approaches the cap, STOP and report, do not shrink the task silently.
- Exact per-report command (what a runner does), batch with <=4 parallel:
  `P=/home/tyc4d/cr-project/.venv/bin/python`
  `CR_DATA_DIR=.data-eval100/<id> CR_BUDGET_HARD_CAP_USD=20 PYTHONPATH=/home/tyc4d/cr-project/.worktrees/eval-100/packages/contracts \`
  `$P reports/overnight/evidence/scenario-eng/run_real.py fixtures/cti-corpus/<id>/report.md markdown single_pass reports/eval-100/runs/<id> <id>`
  then load 01-ir.json, call inventory.resolve + discovery.discover in-process for the report fields.
- Do NOT change product code. Only add files under reports/eval-100/ and .data-eval100 (gitignore the data).
- Commit is done by the Lead (you cannot commit). Report: `hc send t31 "<one-line status + SUMMARY path>"` when
  done, over budget, or blocked. Follow AGENTS.md.
