# M9 cancellable probe transport

Implemented a per-probe operation ID and a durable start/cancel fence in the shared PVE reservation database and worker guest. The guest supervisor serializes `start`, `wait`, `cancel`, and `join`, persists cancellation tombstones before launch, checks the helper's ownership and exact target network, and confirms helper absence before reporting a terminal cleanup state. Uncertain outcomes remain recorded and block worker `down`, `reset`, and reuse. The PoC job store keeps the operation identity so a later API worker can retry cancellation. Vulnerable PoC execution remains refused on `local-docker` under D6.

Validation:

- Focused runner/backend suite: 77 passed, 2 existing `jsonschema.RefResolver` deprecation warnings.
- `py_compile` on all changed Python files: passed.
- `git diff --check`: passed.
- Guest supervisor checks use a fake Docker CLI that launches only harmless local `sleep` processes. They are not PVE/QGA/Docker deployment acceptance.

Limits: no PVE, QGA, Docker daemon, vulnerable image, or attack probe was invoked. Live PVE behavior, installed worker-template dependencies, API-worker shared database mounting, and cancellation under real QGA/network failures remain unverified and require the authorized PVE validation step.
