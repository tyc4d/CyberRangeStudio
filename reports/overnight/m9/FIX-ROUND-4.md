# Module 9 — Fix Round 4 (after round-4 QA CHANGES REQUESTED)

Round-4 QA confirmed ALL 28 prior findings stay fixed (review1 57/1, review2 89/0, review3 34/0). 4 new issues.
Acceptance = `reports/overnight/m9/review4/test_m9_review4.py` (27 failing) + `review4/check_web_review4.cjs`
(8 failing); keep all prior review files green + full suite. Run backend with `PYTHONPATH=<worktree>/packages/contracts`.
No manufactured PASS; honest refuse/flag is correct.

## m9-export (cr-codex-ultra) — R4-01 / P1 (the only P1) — apps/api/app/poc/export/**
Stop adding value-patterns; do a STRUCTURAL redaction pass — the reviewer's cases all carry a secret-indicating
STRUCTURE, so this is convergent, not an arms race. Root-cause blind spots to fix:
- inline regex requires the label directly followed by `:`/`=` — also match quoted keys (`"password":`,
  `'password':`) and secret-named keys inside embedded JSON/YAML within a plain description string (re-scan nested).
- a quoted value is treated safe if it `startswith('${')`, and a bare value if it `startswith('[REDACTED]')` —
  WRONG: scan the ENTIRE value; redact the whole thing, including a secret after a `[REDACTED]` prefix or after a
  `${...}` reference, and ALL segments of a shell/SQL concatenation (`'public'"S"`, `'public''S'`), not just the first.
- URL userinfo must be caught WITHOUT a scheme too (`//user:secret@host`), and with quotes in the password.
- `Authorization: Basic <base64>` / `Bearer <token>` and `Cookie: <name>=<value>` in free text must be redacted
  (Basic decodes to user:secret — treat the credential as secret).
Rule of thumb: redact by the KEY/HEADER/URL STRUCTURE regardless of the value's quoting/encoding/concatenation; a
secret-named field's value is redacted whole. The final scan + verify_bundle must catch every case above; when a
secret-structured token cannot be proven removed, REFUSE the export (never emit contains_secrets=false falsely).
Make `test_export_new_syntax_removed_or_refused` (13) + `test_checker_detects_secret_even_when_hash_is_correct`
(9) pass; keep all prior export tests green. (Assigned to cr-codex-ultra for a thorough structural rewrite.)

## m9-chain (cr-codex-ultra) — R4-04 / P2 — apps/api/app/poc/chain/**
When the NEWEST execute job is terminal with ZERO runs (cancelled/error), `_select_runs` currently falls back to
the previous job's runs, so chain.per_action and report.reproduced silently show the OLD batch's PASS as if
current. Fix: select the newest execute job by job identity (incl. a terminal cancelled/error job that has no
runs); if the current batch has no verifiable runs, its actions are NOT_TESTED for THIS batch — do not reuse an
older batch's PASS. Keep history available but mark provenance (which job/when); never present stale PASS as the
current result. Make `test_new_empty_terminal_job_never_reuses_older_verified_passes` (2) pass; keep review3's
"newest batch really has FAIL/BLOCKED runs" cases green.

## m9-runner (cr-codex-ultra) — R4-03 / P2 (runner half) — apps/api/app/poc/runner/**
R3 fixed run-mixing and cancel-all. Remaining: `execution_status` must expose the JOB IDENTITY (return the
selected job's id + state, and ideally the set of still-running execute jobs for the scenario) so a client can
confirm that the job(s) it cancelled actually reached a terminal state — not treat a newer job's `done` as the
older cancelled job's stop-confirmation. Make `test_status_cannot_announce_terminal_while_older_execute_is_running`
(2) + `test_real_threads_newer_done_does_not_hide_older_active_from_cancel_confirmation` (1) pass. Do NOT reject
overlap (R3-03 tests require overlap allowed).

## m9-gui (cr-claude) — R4-02 + R4-03 (GUI half) — apps/web/src/pages/PocPage.tsx (+ i18n, lib/hooks.ts)
- **R4-02:** a new execute must invalidate RAW results too (not just chain/report) in the pending and
  fetch-reject/abort paths; and add a response-identity/generation guard so a late-arriving OLD chain/report/results
  response cannot overwrite newer state. No stale PASS badge, no 0/2-or-2/2 unverified after a failing rerun.
- **R4-03 (GUI):** confirm "stopped" only when the specific job(s) the user cancelled reach a terminal state
  (use the job identity the runner now returns) — do not treat a newer job's completion as the cancelled job's
  stop confirmation.
- Acceptance: `review4/check_web_review4.cjs` 10/10, tsc clean, prior web scripts green.

Report hc send t31 when done. Lead integrates, re-runs all four review files + full suite, then reviewer round 5.
The deploy-layer guaranteed-cancel handle (#5) remains the one honest deferred item.
