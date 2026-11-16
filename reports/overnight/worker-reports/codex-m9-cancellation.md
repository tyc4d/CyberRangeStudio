# M9 cancellable probe transport

Implemented a per-probe operation ID and a durable start/cancel fence in the shared PVE reservation database and worker guest. The guest supervisor serializes `start`, `wait`, `cancel`, and `join`, persists cancellation tombstones before launch, checks the helper's ownership and exact target network, and confirms helper absence before reporting a terminal cleanup state. Uncertain outcomes remain recorded and block worker `down`, `reset`, and reuse. The PoC job store keeps the operation identity so a later API worker can retry cancellation. Vulnerable PoC execution remains refused on `local-docker` under D6.

Follow-up race correction: each worker reservation has a generation ID. Successful deployment records carry that ID, and a POC job captures its worker identity before running actions. The PVE launch reservation must match the job's VMID, host, and generation, so a delayed job cannot attach to a replacement worker even when PVE reuses the same VMID. A `reserved` ledger row is committed before the operation is attached to the job and blocks `down`/`reset`; cancellation scans that ledger to reconcile a process crash in the attachment gap. Jobs in `error` with an unresolved operation remain eligible for cancellation.

Migration follow-up: ledgers created before job IDs were persisted can still have `job_id=NULL`. Cancellation now binds such a row only under the shared placement lock and only when operation ID, scenario, host, VMID, service, target, and generation all match. It conditionally updates the null field, rereads the committed row, then proceeds with cancel; mismatched rows remain unbound and fail closed.

The migration setup now commits schema changes and legacy generation backfills before returning values to callers. A regression starts from the 1e0c4a3-era table definitions with no generation/job columns, migrates an active worker and running operation, then confirms the generated identity persists across lock acquisitions and cancellation binds the matching job before issuing the guest cancel command.

Validation before the live follow-up:

- Focused runner/backend suite: 82 passed, 2 existing `jsonschema.RefResolver` deprecation warnings.
- `py_compile` on all changed Python files: passed.
- `git diff --check`: passed.
- Deterministic regression: a reserved operation blocks `down`/`reset`; after a simulated same-VMID redeploy with a new generation, the old pinned start is rejected before QGA.
- Deterministic regressions: an exact legacy row with a null job ID binds and cancels; a service/target identity mismatch remains unbound and is rejected before QGA.
- Migration regression: the 1e0c4a3-era SQLite schema is upgraded and persists generation/job columns before matching cancellation.
- Guest supervisor checks use a fake Docker CLI that launches only harmless local `sleep` processes. They are not PVE/QGA/Docker deployment acceptance.

## Live PVE follow-up (2026-11-16)

- Reused the already approved non-vulnerable synthetic scenario `scn_2acb1b9c902c` (NGINX and Alpine only). PVE deployed worker VMID 900100 with zero NICs; the backend reported checked isolation and no published ports.
- A real PVE/QGA helper was started inside the NGINX service namespace. Its only code was `time.sleep(180)`; it made no network requests and contained no exploit. The helper was confirmed running before cancellation.
- Initial live attempts returned `uncertain`. Guest inspection showed Docker had canonicalized `container:<service-name>` to `container:<full-service-ID>`, while the supervisor accepted only the name. Docker also returned lowercase `no such object`, while absence checks expected title case. The supervisor now resolves the target service's exact Docker ID and accepts only that ID or the exact service name; missing-object checks are case-insensitive.
- Added regressions for both Docker behaviors. Post-fix focused supervisor/backend/runner tests: **53 passed**, 2 existing `jsonschema.RefResolver` deprecation warnings; `py_compile` and `git diff --check` passed.
- One local orchestration attempt also tried to read the shared SQLite reservation DB while the start call held its exclusive placement lock, then exited early. The helper was reconciled through the cancellation path. For a helper left by the earlier attempt, full labels, pinned image, resource limits, service target and exact service ID were checked before removing only that operation's container through the isolation-checked guest command.
- After restarting API 8077 with the fix loaded, re-ran cancellation through `POST /api/poc/{scenario}/execute/cancel` while a harmless helper was confirmed running. Result: `joined=true`, `uncertain=false`, helper absence confirmed; runner returned `125` with the confirmed-cancel reason. The job and operation reached `cancelled` and the job-operation binding was cleared.
- The scenario was then stopped through `POST /api/deploy/{scenario}/down` (HTTP 200). PVE preflight returned `ready`, `running_workers=0`, `worker_vmid_count=0`, and pool membership only template VMID 900000; the durable worker reservation is empty.
- An earlier interrupted local monitor hit SQLite's exclusive placement lock and exited while the probe was `starting`. The operation was recovered through the normal cancellation path; the later live API test passed. This did not leave a worker or helper behind.

Limits: this verifies successful cancellation and cleanup while QGA was available. Cancellation under QGA loss, network failure, and API-worker restart during an active helper still needs fault-injection coverage. No vulnerable image or exploit probe was used in this follow-up; this is not the P5 attack-probe acceptance.

Independent review of `b160e1f`: **APPROVE, no blocking findings**. The reviewer noted a non-blocking hardening opportunity to require the missing-object error text to name the requested container reference; no reproducible false-positive path was found.
