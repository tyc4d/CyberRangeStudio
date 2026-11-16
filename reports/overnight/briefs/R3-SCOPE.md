# Round 3 scoped acceptance — 2026-11-16

## Candidate and environment

- Product-code freeze: `agent/acceptance-lead` at `be4947e`; documentation-only commits may follow. The serving checkout was later verified as `agent/acceptance-lead@a033c53`; no product-code changes occurred between those commits.
- Real browser URL: `http://127.0.0.1:5199/`; its Vite proxy sends `/api` to candidate API `127.0.0.1:8077`.
- `http://127.0.0.1:5177/` is an owner-facing read-only preview and rejects non-GET/HEAD requests. Do not use it for state-changing QA steps.
- Candidate API has live Proxmox selected, but all QA agents must avoid lifecycle writes.

## In scope

Use the role briefs to test the browser workflows for import, evidence review, missing-information completion, attack-flow and dependency analysis, topology review, approval, IaC generation/preview, and truthful deployment status. Use separate scenarios with a clear role-specific suffix. Keep screenshots and a Playwright trace for the main workflow. Test both Chinese and English where practical; include mobile layout for UX.

Read-only deployment status and preflight are allowed. Scenario creation, analysis, and topology/IaC preparation are allowed. Do not press deploy, reset, or teardown controls; no PVE worker should be created in this round.

## Explicit exclusions

- Do not deploy Equifax or any vulnerable image.
- Do not run an attack probe, vulnerability validation, segmentation test, or other exploit action.
- Do not use local Docker for vulnerable images or probes.
- Do not test learner/instructor network reachability or claim that a planned connection is reachable. The UI must continue to state that an instructor entry point is unavailable.
- Do not call POST `/api/deploy/{id}/up`, `/down`, `/reset`, or `/api/validate/{id}/run` directly.

These exclusions are due to the open P4/P5 gates and the missing PVE network ACL for an instructor entry point. This is a scoped Round 3 usability/workflow result, not P4, P5, or overall acceptance.

## Scoring and reporting

Use the existing 100-point rubric in `COMMON.md` without changing weights. If a category depends on an excluded operation, mark it NOT TESTED and explain the deduction; never infer PASS from a preview. Do not read previous QA score reports before scoring. Report each severity with a browser reproduction path and screenshot/trace evidence. Do not edit product code or commit.
