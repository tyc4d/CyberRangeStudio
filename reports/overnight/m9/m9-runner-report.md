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

**Blocked / incomplete:** the required real Struts (or Log4Shell) success and version-
mismatch e2e cases cannot execute through the mandated manager path. The current deploy
flow refuses vulnerable hosts and `probe_in_service()` refuses their probes. The runner
does not bypass those controls. The additional helper cleanup handle needed for guaranteed
kill on cancellation is also not exposed. See `reports/overnight/m9/requests/m9-runner.md`
for the minimal Lead-owned interface request. No tests were run.
