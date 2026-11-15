# m9-runner worker report

Implemented under `apps/api/app/poc/runner/`:

- Adapter types and adapters for python, bash, go, metasploit, http_seq, and manual.
- `assert_target_owned()` checks deployment records, scenario-generated service identity,
  container labels/state, isolated internal network, and protected VMIDs. It fails closed.
- `SandboxRunner` calls the mandated `manager.probe_in_service()` only after ownership
  verification, verifies payload hashes / GitHub commit pins, enforces a bounded timeout,
  redacts log output, records artifacts, and only returns PASS when an expected concrete
  exploit-effect marker is present.
- Added an ownership-denied e2e acceptance test proving the probe is not invoked.

Added the required real Struts S2-045 product deployment e2e, guarded to skip unless
Proxmox is selected, reachable, and its approved isolated worker template passes
preflight. A missing preloaded Struts image also skips with an explicit reason. Added a
version-mismatch unit case proving a delivered response without `vulhub=54289` is FAIL,
never PASS. PASS requires the exact runner-owned SHA-pinned Struts request and its
registered effect verifier; arbitrary output markers cannot self-assert success.

Added `run_job()`, which persists the `poc_jobs` row, per-action `poc_runs`, live stages,
and cooperative cancel flag; `execution_status()` and `cancel_execution()` implement the
requested GUI shapes. `routers/poc.py` is outside this worker's file ownership, so its two
route lines are in `requests/m9-runner.md`. Timeout/cancel uses a bounded wrapper around
`manager.probe_in_service` and best-effort removes only a uniquely identified helper
container; see the request note for the manager handle nice-to-have. No tests were run.
