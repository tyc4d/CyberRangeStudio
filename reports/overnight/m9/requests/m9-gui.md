# m9-gui → Lead (t31): interface gaps the GUI hit

Built `apps/web/src/pages/PocPage.tsx` strictly against the 6 frozen routes in CONTRACT.md §HTTP API.
Four things the owner's §8 GUI asks for are **not covered by the frozen contract**. I did NOT invent backend
routes; I degraded the GUI honestly and list the gaps here so you / the backend owners can decide.

1. **Live status + logs poll + cancel during execution.**
   CONTRACT says execute is synchronous and "record a job row with state for the GUI to poll", but the HTTP API
   lists no `GET …/execute/status` (or `…/job`) and no `POST …/cancel`. The GUI therefore:
   - shows an honest elapsed-seconds Busy while the single synchronous `POST /execute` runs;
   - renders the returned `ExecutionResult[]` per-action **stage timeline** (started→delivered→responded→
     vuln_behavior→state_change→action_complete) + `logs_path` + evidence as the "status/logs" view;
   - implements **Stop** as a client-side `AbortController` that stops the GUI waiting (clearly labelled
     「停止等待」 / "Stop waiting"). It cannot signal the backend cancel flag without a route.
   If you want true live polling + server-side cancel, m9-runner needs to add (and freeze):
   `GET /api/poc/{id}/execute/status` → `{job_state, per_action stages, logs_tail?}` and
   `POST /api/poc/{id}/execute/cancel`. I'll wire them in one additive block if added.

2. **Export download bytes.** `/export` returns `{bundle_path, manifest}` where `bundle_path` is a server
   filesystem path, not a URL. There is no frozen route to fetch the ZIP. The GUI shows the manifest (files,
   sha256, rebuildable, missing_for_rebuild) + the bundle_path, and the Download button does a `GET
   /api/poc/{id}/export/download` (convention) — it surfaces an "unimplemented" notice cleanly if that route
   is absent. m9-export would need a download route (or static serving) for a working download.

3. **Export format param.** §8 wants a "format picker". The contract body has no `format` field. The GUI sends
   `{format: "full"|"iac"|"evidence"}` in the POST body; a backend that ignores it just returns the full bundle,
   so this is additive and safe. Confirm whether m9-export will honour it.

4. **/report (FidelityReport) shape not in `types.ts`.** The contract says it reuses validation-report levels +
   fidelity, but §8 demands **5 separate** metrics (deployment readiness, per-vuln, end-to-end chain, scenario
   fidelity, unverified/unsupported — never one combined %). I render the 5 metrics **derived from the data the
   GUI already holds** (ValidationPlan + ExecutionResult[] + ChainValidation), and overlay any structured
   `metrics`/`fidelity` object the `/report` endpoint returns if present. No combined success rate is ever shown.
   If m9-chain settles on a concrete `/report` metrics shape, tell me and I'll prefer it.

None of these block the GUI compiling or rendering real data; they only limit download + live-cancel until the
backend routes exist. — m9-gui
