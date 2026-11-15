# Module 9 — Fix Round 3 (after round-3 QA CHANGES REQUESTED)

Round-3 QA confirmed ALL 24 prior findings stay fixed (review1 57/1, review2 89/0 — no regression). It found 4
new issues. Acceptance = `reports/overnight/m9/review3/test_m9_review3.py` (10 failing) +
`review3/check_web_review3.cjs` (4 failing); keep review1 57/1, review2 89/89, full suite green. Run backend with
`PYTHONPATH=<your-worktree>/packages/contracts`. No manufactured PASS; honest refuse/flag is correct.

## m9-export (cr-claude) — R3-01 / P1 (the only P1) — apps/api/app/poc/export/**
Export STILL leaks synthetic secrets AND reports `contains_secrets=false` / `verify_bundle==[]` for:
`password='<v>'` and `password="<v>"` (quoted inline), `?access_token=public'<v>` (single-quote stops the
query scan), `?%61ccess_token=<v>` (percent-encoded key not decoded), and a secret in a MAPPING KEY
`{<v>: "[REDACTED]"}`. **Adopt a fail-closed stance to end the whack-a-mole:** the final scan must
percent-decode keys, handle quoted/delimited values in free text and URLs, and inspect mapping keys, not just
values; and when a secret-shaped token cannot be proven safe, FLAG it (`contains_secrets=true` + verify_bundle
reports it) or REFUSE the export — never emit a false clean guarantee. Make
`test_fresh_bundle_secrets_are_removed_or_export_is_refused` (5) +
`test_verify_bundle_independently_detects_unredacted_structured_secret` (3) pass; keep your prior export tests
green.

## m9-gui (cr-claude) — R3-02 + R3-04 / P2 — apps/web/src/pages/PocPage.tsx (+ i18n)
- **R3-02:** a new execute must INVALIDATE the stale `chain`/`report` snapshot; do not union old
  `reproducedIds`/`chainPassIds` with new results so an action keeps a stale PASS badge or the unverified count
  reads 0/2 after a failing rerun. Recompute/clear old verification on new run or IR change; on source conflict,
  never let an old PASS override a newer result.
- **R3-04:** render the ACTUAL `/execute/status` shape — `live.per_action[{action_id, stages}]` + `logs_tail`
  — so the live per-action stage timeline is visible; today `liveResults` reads `live.results` (null) and shows
  nothing.
- Acceptance: `review3/check_web_review3.cjs` 9/9, tsc clean, prior web scripts still green.

## m9-runner (cr-codex-ultra) + Lead/service.py — R3-03 / P2
Overlapping `execute` jobs for the same scenario mix state and evade cancel: `execution_status` picks the newest
job but queries `poc_runs.ts >= job.created_at` (pulls another job's rows); `cancel_execution` only looks at the
newest job, so an older STILL-RUNNING job is never cancelled (`{cancelled:false}`).
- **runner (owns runner):** `execution_status` and `cancel_execution` must act on a specific job identity —
  select rows by `job_id` (not a `ts>=` window), and cancel must target the oldest/any still-running job for the
  scenario (or all running jobs), returning `{cancelled:true}` when one was flagged. Cases
  `test_status_must_not_mix_overlapping_jobs`, `test_completed_newer_job_cannot_hide_an_older_still_running_job_from_cancel`.
- **Lead/service.py:** reject a new `execute` for a scenario that already has a running job (HTTP 409 via a
  clean exception), so overlap doesn't arise in the product flow. Coordinate: if runner makes
  status/cancel job-identified, service's reject-overlap + runner's per-job targeting together satisfy the cases.
  (Confirm which layer each case asserts; keep both honest.)

Report hc send t31 when done. Lead integrates, re-runs all three review files + full suite, then reviewer round 4.
The deploy-layer guaranteed-cancel handle (#5) remains the one honest deferred item.
