# M9 cancellable probe transport

Implemented a per-probe operation ID and a durable start/cancel fence in the shared PVE reservation database and worker guest. The guest supervisor serializes `start`, `wait`, `cancel`, and `join`, persists cancellation tombstones before launch, checks the helper's ownership and exact target network, and confirms helper absence before reporting a terminal cleanup state. Uncertain outcomes remain recorded and block worker `down`, `reset`, and reuse. The PoC job store keeps the operation identity so a later API worker can retry cancellation. Vulnerable PoC execution remains refused on `local-docker` under D6.

Follow-up race correction: each worker reservation has a generation ID. Successful deployment records carry that ID, and a POC job captures its worker identity before running actions. The PVE launch reservation must match the job's VMID, host, and generation, so a delayed job cannot attach to a replacement worker even when PVE reuses the same VMID. A `reserved` ledger row is committed before the operation is attached to the job and blocks `down`/`reset`; cancellation scans that ledger to reconcile a process crash in the attachment gap. Jobs in `error` with an unresolved operation remain eligible for cancellation.

Validation:

- Focused runner/backend suite: 79 passed, 2 existing `jsonschema.RefResolver` deprecation warnings.
- `py_compile` on all changed Python files: passed.
- `git diff --check`: passed.
- Deterministic regression: a reserved operation blocks `down`/`reset`; after a simulated same-VMID redeploy with a new generation, the old pinned start is rejected before QGA.
- Guest supervisor checks use a fake Docker CLI that launches only harmless local `sleep` processes. They are not PVE/QGA/Docker deployment acceptance.

Limits: no PVE, QGA, Docker daemon, vulnerable image, or attack probe was invoked. Live PVE behavior, installed worker-template dependencies, API-worker shared database mounting, and cancellation under real QGA/network failures remain unverified and require the authorized PVE validation step.
