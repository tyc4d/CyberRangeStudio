# Acceptance execution record — 2026-11-16

## Candidate and safety boundary

- Candidate branch: `agent/acceptance-lead`, forked from current `main` at `f40c241`; PVE acceptance code is committed through recovery fix `a58cca2`, and this report/evidence update is `c0466ae`. Candidate commits are not pushed or merged.
- The live test used the explicitly approved synthetic scenario `scn_2acb1b9c902c`; every deploy/reset/down request included `test_approved=true`.
- The ten initial create/deploy/snapshot/destroy cycles used the candidate API on `127.0.0.1:8077`. Reset/rollback used a temporary API on port `8293` from `agent/acceptance-lead`; ports `8077` and `8283` were left untouched.
- A separate existing worker, VMID `900100` for `scn_db358a6d2c07`, was confirmed running before and after. It was not stopped, modified, or deleted.
- The second API process (`127.0.0.1:8283`) returned the same read-only PVE status and capacity. No credentials were printed.

## Live PVE checks

Initial GET preflight reported PVE 9.2.2 on `pve4-bbf`, template `900000`, one existing worker (`900100`), 8,192 MiB pool memory available, 19,053 MiB node memory free, and 84,636,092,439 bytes free on `local-lvm`. The test scenario was `not_created`, its IaC was current, and one worker slot was available.

Ten initial real create → deploy → snapshot → destroy cycles completed through the application API. The ten up/down record pairs are IDs `62`–`81`; each up was `running`, each down was `stopped`, and all ten used VMID `900101` after its prior deletion. Every up had checked isolation and `vm_has_nic=false`; both guest Docker networks were `internal=true`, `driver=bridge`, and `isolated_gateway=true`. Each cycle returned to `not_created` with one worker remaining.

### Real reset/rollback check

The first live reset attempts exposed two integration defects. One reset booted the rolled-back VM but did not start services whose Compose restart policy is `no`; another restarted services but rejected Compose 5.7.1's newline-delimited JSON status. Both 503 responses retained the worker and reservation. `/down` safely removed those exact owned VMs and restored capacity. These failures are records `83` and `86`; cleanup records are `84` and `88`.

The reset implementation now starts Compose only after isolation passes, rechecks isolation afterward, and validates either JSON arrays or newline-delimited objects. A final real reset returned 200 with both services running, NGINX healthy, zero NICs, and isolation verified. Health returned `healthy=true`; `/down` returned 200. This initial successful retry is record `87`.

After that, **10 consecutive successful create → reset → destroy cycles** completed on VMID `900101`, using records `89`–`118`. All 10 up/reset/down sequences passed; every reset returned running with isolation checked, all services healthy, and every down removed the VM. The evidence file contains 266 PVE node-memory samples at approximately 3-second intervals; the minimum observed free memory was 18,100 MiB. Every cycle ended with pool worker count 1. A final real up/reset/down on the integrated candidate also passed, records `119`–`121`.

Final GETs confirmed:

- Test scenario `scn_2acb1b9c902c`: `not_created`, no containers, no published ports.
- Retained scenario `scn_db358a6d2c07`: still running on VMID `900100`, zero NICs, three containers running, the two web/database services healthy, no published ports.
- Final PVE preflight from both running APIs: pool members `[900000, 900100]`, one worker, capacity `ready`, and about 19,060 MiB node memory free. The test scenario has no VM or containers.

### V1 bridge check and latest live lifecycle

The candidate now reads only `GET /api2/json/nodes/pve4-bbf/network`. Its fail-closed V1 check requires exactly one `vmbr990` row, `type=bridge`, both address methods explicitly `manual`, an explicitly empty `bridge_ports`, and no configured IPv4/IPv6 address or gateway. Missing or unexpected fields fail the check. The API response confirmed `bridge_ports=""`, `method=manual`, `method6=manual`; address, netmask, CIDR, and gateway fields were absent and are recorded as not configured. An independent read-only review approved this guard after requiring the explicit `manual` checks.

Using the candidate API on temporary localhost port `8294` with the existing shared deployment database and PVE reservation database, a new real lifecycle completed on the approved synthetic NGINX/Alpine scenario. The up request returned HTTP 200 and deployment record `125` on VMID `900101`; V1 preflight, immediately-before-clone, and post-deployment checks all passed. Both services were running, NGINX was healthy, no host ports were published, and the worker had zero NICs with isolation confirmed. Reset returned HTTP 200 (record `126`), and down returned HTTP 200 (record `127`). The final state was `not_created`, no scenario containers remained, pool members were `[900000, 900100]`, and worker count returned to 1. The retained worker for `scn_db358a6d2c07` remained running with its three existing services. Both existing API ports, `8077` and `8283`, returned ready capacity after cleanup; the temporary API on `8294` was stopped. No vulnerable image or attack probe was used.

One earlier candidate startup had accidentally inherited PVE `probe` mode: the up request returned HTTP 503 with `writes are disabled in probe mode`, and the backend reported that no clone write was sent. It left no worker; the subsequent live-mode preflight showed one existing worker before the successful lifecycle.

### Real failure injection: Compose cleanup unavailable

To exercise the down cleanup failure path without a mock, another approved synthetic worker was deployed (record `130`, VMID `900101`) with V1 and isolation passing. Through its owned QGA session, the test stopped `docker.socket` and `docker.service`; both stops returned exit code 0. `/down` then observed guest Compose cleanup exit code 1 and recorded `guest Compose down returned a nonzero exit code`, but continued through the owned VM shutdown/delete path and returned HTTP 200 (record `131`). The test worker and its reservation were removed. Post-check showed the scenario `not_created`, no scenario containers, pool worker count 1, capacity `ready`, and the sole active reservation still belonged to VMID `900100` for the retained scenario. The first attempt that stopped only `docker.service` did not trigger the failure (Compose returned 0); the second attempt stopped the socket as well and did.

### Owner-approved worker hard cap of five

The owner raised the hard worker cap from 2 to 5. The candidate sets both the worker-count and running-worker ceiling to 5; node, pool-memory, storage, and durable-reservation checks remain unchanged. Independent read-only review approved the cap change with these capacity limits. A live read-only preflight on the candidate returned ready with one worker (VMID `900100`), 8192 MiB pool memory available, 18972 MiB node memory free, and `local-lvm` free bytes `84636092439`.

The current 16384 MiB pool budget includes the 4096 MiB template, leaving 12288 MiB for workers. At 4096 MiB per worker, the current pool budget can hold at most **3 worker VMs** total; other node or storage checks can lower that further. Five workers require at least 24576 MiB of pool memory, plus sufficient node memory and storage. No resources were changed, and five-worker capacity was not tested. The cap is therefore the policy ceiling; it is not evidence that five VMs can run now.

### Local QA API cutover

Following the owner's earlier request to replace old services so the new limit is active, the legacy API processes on `8077` and `8283` were stopped before either candidate process started. The updated `agent/acceptance-lead` API now runs on both ports with the same data directory and reservation database; no old/new API versions are mixed. Both APIs returned HTTP 200 for read-only preflight and status, capacity `ready`, and V1 true. The approved test scenario remains `not_created`; pool members remain `[900000, 900100]`, and no PVE write was sent during cutover. The existing web UI on port `5286` still returns HTTP 200 and points to API `8283`; `5177` has no listener.

### Candidate backend regression after the M9 cancellation fix

On candidate `agent/acceptance-lead` at `2b97589`, ran `PYTHONPATH=apps/api /home/tyc4d/cr-project/.venv/bin/python -m pytest apps/api tests/unit -q --ignore=apps/api/app/deploy/test_local_compose_integration.py`. Result: **485 passed, 2 warnings, 160 subtests passed in 7.63s**. The warnings are the existing `jsonschema.RefResolver` deprecation. This run excluded the local Compose integration module and did not run `tests/e2e`; it did not call Docker, PVE, the LLM, or attack probes. It is backend regression evidence only and does not satisfy P4/P5 or formal Round 3.

### Post-cutover live API cycle and requested worker cleanup

After cutover, a real lifecycle was run through candidate API `8077` on the approved, non-vulnerable synthetic scenario `scn_2acb1b9c902c`. Baseline preflight reported current IaC, `not_created`, capacity ready, V1 true, one other active worker, and 8192 MiB pool memory available. `up` returned HTTP 200 on VMID `900100` with isolation checked and confirmed; both services were running with no published ports. Status and health passed. `reset` returned HTTP 200, then status showed both services running and health remained healthy. `down` returned HTTP 200; final status was `not_created`, worker count returned to 1, V1 remained true, and the other scenario remained running. Evidence: `evidence/pve-cap5-live-api-cycle-20261116.json`.

The owner then explicitly authorized clearing all scenario workers. Read-only reservation/status checks found one active scenario worker, VMID `900101` for `scn_dfa700bd9bc4`; `/down` returned HTTP 200 (record `137`). Final preflight reports pool members `[900000]`, zero worker VMs, 12288 MiB pool memory available, V1 true, and no remaining reservation. The template `900000`, protected existing VMIDs, and local UI/API processes were left untouched. Evidence: `evidence/pve-scenario-worker-cleanup-20261116.json`.

### Real API crash recovery after a completed clone task

After integrating recovery commit `a58cca2`, both API ports were drained and restarted from the same candidate code, data directory, and reservation database. Read-only preflight on both ports confirmed the approved synthetic scenario `scn_2acb1b9c902c` was topology-approved, had current IaC, and PVE contained only template `900000` with zero worker VMs.

For a controlled failure injection, a temporary one-request API process used the real candidate code and real PVE but terminated itself immediately after `_clone_worker` returned. This is after PVE completed the real clone and after the exact clone UPID had been committed, but before the application updated the reservation from `cloning` or wrote its successful lifecycle record. The request ended with an empty HTTP response as expected. The durable row showed VMID `900100`, state `cloning`, clone UPID present, no delete UPID, and `delete_intent=not_requested`.

The still-running candidate API on port `8283` then received the normal `/down` request. It validated the saved clone task and exact provisional VM identity, sent one owned deletion, persisted and verified the `qmdestroy` task, confirmed the VMID was absent and free, and returned HTTP 200 with `recovered_provisional=true` (deployment record `146`). Final preflight showed `not_created`, zero workers, pool members `[900000]`, and no reservation. The temporary crash hook was removed; the standard candidate API was restarted on `8077`.

This is a real PVE recovery check for the crash after the clone UPID is saved. It does not cover a crash after PVE accepts clone but before the UPID is saved (intentionally manual reconciliation), nor the live DELETE-response-loss window; the latter remains fail-closed by the durable delete-intent and no-repeat-delete regressions. No vulnerable image or attack probe was used.

### Additional real P4 lifecycle failure injections

On the same approved synthetic NGINX/Alpine scenario, controlled failures were injected at four points while the worker lifecycle still used real PVE operations: provisional-VM configuration, VM start, guest-agent readiness, and deployed-snapshot creation. Each `/up` returned HTTP 503; the exact owned clone/worker and reservation were removed by the normal cleanup path. After every case, read-only status and preflight showed `not_created`, pool members `[900000]`, zero worker VMs, and no scenario reservation.

A fifth injection interrupted reset immediately before rollback. `/reset` returned HTTP 503 and correctly retained the stopped, owned VM and its active reservation; the normal `/down` then returned HTTP 200 and removed both. Final state again showed only template `900000`, zero workers, and no reservation. The `agent` case is an application-level readiness-timeout injection after the real VM start; later shutdown, deletion, and all other PVE interactions were real. No vulnerable image or probe was used.

Evidence: `evidence/pve-p4-live-failure-injections-20261116.json`. The accompanying API-preflight memory sampler had one request timeout, so that artifact's overall result is marked `FAIL` even though all five lifecycle checks passed. A follow-up real up/reset/down cycle sampled the PVE node-status endpoint directly at a one-second target interval: 68 samples, zero sample errors, minimum free memory 18,907 MiB (above the 3,072 MiB reserve), with final zero-worker state. This is periodic sampling, not proof of every instant. Evidence: `evidence/pve-p4-direct-node-memory-cycle-20261116.json`.

An initial temporary hook process started without the API's `.env` loading option. Its preflight failed closed before any clone write; a subsequent diagnostic `/down` produced failed audit record `147` because the temporary process could not resolve the scenario data. No PVE VM or reservation was created. The verified run used the same `.env` loading option as the candidate APIs and guarded every write with a ready, zero-worker preflight.

### Secret-pattern scan

Scanned 91 deployment records for the two acceptance scenarios and the five persisted PVE acceptance artifacts/reports. The scan found zero PVE API-token, Authorization, generated database-password, or credential-like key/value patterns; values were not printed. A follow-up scan read all seven available Herdr terminal histories named `acceptance-*` (`t5k`, `t5m`, `t5n`, `t5q`, `t5r`, `t5x`, `t5y`); it found zero PVE token assignments, Authorization credentials, private-key blocks, or database-password assignments. No persistent API log file exists under `apps/api/data`. Scan counts only are preserved in `evidence/pve-acceptance-terminal-secret-scan-20261116.json`; no secret values were stored. This covers the available acceptance terminal histories, not arbitrary logs outside Herdr or processes that did not persist terminal output.

## Limits and remaining acceptance gates

- **P4 is still incomplete.** Ten create/reset/destroy cycles passed. Real PVE failure injections at configuration, start, guest-agent readiness, snapshot creation, and reset rollback all followed their expected cleanup/retention behavior; every scenario worker and reservation was then cleared. The saved-clone-UPID crash recovery also passed. V1 and V7 passed. Direct PVE node-status sampling during a real up/reset/down cycle recorded 68 one-second-target samples with no errors and a 18,907 MiB minimum, but this is periodic sampling rather than an absolute every-instant proof. Live DELETE-response-loss and the clone-accepted-before-UPID-persisted crash window remain deliberately untested because they require manual reconciliation. V2 passed for `192.168.16.214:22/8006`; read-only PVE inventory listed one online node and four configured interfaces but exposed no address fields. Do not guess or scan other hosts; no authoritative additional address list is available. The deployment-record/artifact secret scan passed; prior interactive terminal logs were not in scope.
- V2 was checked from one worker to PVE management `192.168.16.214` on ports 22 and 8006; both returned guest `ENETUNREACH`. The PVE node inventory and configured-interface evidence are in `evidence/pve-v2-node-address-inventory-20261116.json`. A single V6 positive path (`h2` → `h1` HTTP/80) returned the NGINX page. This does not complete every P4 acceptance condition.
- **P5 is not accepted.** No Equifax deployment or action-specific attack probe was run; the jump host and J1–J6 learner-path checks remain outstanding. Follow the PVE audit report before any vulnerable image/probe run.
- Reset and up fail-closed fixes are in the unmerged `agent/acceptance-lead` worktree. Reset was independently approved and exercised against live PVE. The up status/reservation fixes were independently approved and then exercised in one additional real lifecycle. None of this work has been merged to `main`.

## Other parallel checks

- Independent read-only review found no reproducible blocking or major code finding; it did not run live PVE or tests: `../acceptance-review/reports/overnight/worker-reports/acceptance-review.md`.
- Frontend production build passed on the candidate. Vite reported a large-chunk warning; `npm ci` reported 5 dependency advisories.
- A real headless Chromium check opened the running placement UI at `127.0.0.1:5286/deploy` with the retained PVE scenario selected in browser storage. It showed the placement hierarchy (`Proxmox VE` → node `pve4-bbf` → pool `cr-range` → worker VM `900100`), 4096 MiB, 20 GiB, and zero NICs; there were no page errors, 62 requests, and all were GET. The UI accurately says physical room/rack location is unavailable from current PVE metadata.
- Before the reset/up fail-closed changes, the safe backend regression suite passed: **237 passed, 2 deselected, 2 warnings, 3 subtests passed**. The two live Docker integration tests were deliberately deselected. Test-only edits are also present in this acceptance worktree. The backend suite was not rerun on the final integration candidate; full browser E2E was not run because it seeds persistent data, calls the live LLM, and can deploy local Docker services.
- The read-only PVE phase audit is at `../acceptance-pve-audit/reports/overnight/worker-reports/acceptance-pve-audit.md`.
- Reset implementation and its live-driven corrections are in this `acceptance-lead` worktree; the independent reset review is `../acceptance-review/reports/overnight/worker-reports/acceptance-reset-review.md`, with a later follow-up `APPROVE` recorded by the read-only reviewer. The up fail-closed review also returned `APPROVE`; its candidate implementation is in `../pve-up-failclosed`.
- P4 reset-cycle evidence: `evidence/pve-p4-reset-cycles-20261116.jsonl`.
- Post-cutover live API up/reset/down evidence: `evidence/pve-cap5-live-api-cycle-20261116.json`.
- Owner-requested cleanup of all scenario workers: `evidence/pve-scenario-worker-cleanup-20261116.json`.
- P4 V1 lifecycle evidence: `evidence/pve-v1-lifecycle-20261116.json`.
- P4 acceptance terminal secret scan: `evidence/pve-acceptance-terminal-secret-scan-20261116.json`.
- Real down-cleanup failure-injection evidence: `evidence/pve-failure-down-cleanup-20261116.json`.
- Owner-approved cap-5 and current capacity evidence: `evidence/pve-worker-cap-5-readiness-20261116.json`.
- Local API cutover evidence: `evidence/pve-cap5-api-cutover-20261116.json`.
- V2/V6 smoke evidence: `evidence/pve-v2-v6-smoke-20261116.json`.
- P4 real lifecycle failure-injection evidence: `evidence/pve-p4-live-failure-injections-20261116.json` (injection paths passed; initial API-preflight sampler had one timeout).
- P4 direct PVE node-memory sampling during real lifecycle: `evidence/pve-p4-direct-node-memory-cycle-20261116.json`.
- Read-only PVE node/interface address inventory for V2: `evidence/pve-v2-node-address-inventory-20261116.json`.
