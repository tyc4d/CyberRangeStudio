# Acceptance execution record — 2026-11-16

## Candidate and safety boundary

- Candidate branch: `agent/acceptance-lead`, based on `agent/trapa-deploy-ui` at `f020597`. PVE acceptance updates are locally committed; `main` remains `4c2c5fa`, and no acceptance commit has been pushed or merged.
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

### Secret-pattern scan

Scanned 91 deployment records for the two acceptance scenarios and the five persisted PVE acceptance artifacts/reports. The scan found zero PVE API-token, Authorization, generated database-password, or credential-like key/value patterns; values were not printed. No persistent API log file exists under `apps/api/data`; prior interactive terminal sessions were not part of this scan, so the broader console-log scan remains open.

## Limits and remaining acceptance gates

- **P4 is still incomplete.** The ten create/reset/destroy cycles and sampled memory floor passed, V7 zero-NIC evidence was checked, V1 now passed before and after a real deployment, and the real down-cleanup failure injection removed the owned worker/reservation. Failure injection at the other lifecycle stages remains outstanding. V2 passed for `192.168.16.214:22/8006`, but the design's “other node addresses” list is undefined and the PVE API read did not return any additional interface addresses; do not guess or scan other hosts. The deployment-record/artifact secret scan passed; prior interactive terminal logs were not in scope. The memory evidence is periodic sampling, not a continuous proof at every instant.
- V2 was checked from one worker to PVE management `192.168.16.214` on ports 22 and 8006; both returned guest `ENETUNREACH`. Other node addresses remain untested. A single V6 positive path (`h2` → `h1` HTTP/80) returned the NGINX page. This does not complete the full V1–V7 matrix.
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
- P4 V1 lifecycle evidence: `evidence/pve-v1-lifecycle-20261116.json`.
- Real down-cleanup failure-injection evidence: `evidence/pve-failure-down-cleanup-20261116.json`.
- Owner-approved cap-5 and current capacity evidence: `evidence/pve-worker-cap-5-readiness-20261116.json`.
- Local API cutover evidence: `evidence/pve-cap5-api-cutover-20261116.json`.
- V2/V6 smoke evidence: `evidence/pve-v2-v6-smoke-20261116.json`.
