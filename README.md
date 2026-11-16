# CyberRange

CyberRange builds and validates red-team training scenarios from threat intelligence with generative AI.

The pipeline runs in these steps:

1. Read one threat report.
2. The LLM extracts the attack actions and the source quote for each action.
3. The system fills missing facts.
4. A person edits and approves the attack flow.
5. The system plans the software dependencies and the network topology.
6. A person approves the topology.
7. The system generates a Docker Compose file.
8. The system deploys the lab in isolation (local host or LAN segment).
9. The system runs benign validation.
10. The system writes a three-level fidelity report.

## Honesty rules

The system keeps these rules. They are the point of the project.

- It separates stated fact, inference, and unknown in `epistemic_status`.
- It keeps temporal order and dependency order as separate relations.
- It keeps the three validation levels separate: `env_build`, `behavior_repro`, and `full_chain`.
- It marks every substitute component.
- It does not run a real exploit. Validation is benign only.

## Architecture

- The backend is Python, FastAPI, and SQLite, in `apps/api`.
- The frontend is React, TypeScript, and Vite, in `apps/web`.
- The shared contracts are in `packages/contracts/schemas`. The central structure is the Scenario IR. It links the eight modules.
- Every OpenAI call goes through the budget manager in `apps/api/app/llm`. The hard cap is 50 US dollars. The manager stops new tasks at 45 US dollars.
- The architecture decision is in `docs/decisions/0001-architecture.md`.

## Inventory resolution

Before the system asks a person for a version, it examines what it can deploy or obtain.

- A named vulnerability maps to a deployable image when the catalogue has one. The pinned image is the vulnerable version, so the system does not ask for a version.
- When the exact product has no image, the system proposes a substitute that reproduces the same CVE or technique. It marks the substitute and does not present it as the original product.
- When the product is not reproducible and has no substitute, the system marks it not reproducible. It does not ask for a version it cannot use.
- When a deployable product has a real version choice that changes the lab, the system still asks.

## Start

```bash
bash scripts/setup.sh                                   # once: create the venv, install dependencies
source .venv/bin/activate && set -a && . ./.env && set +a   # .env must hold OPENAI_API_KEY
cd apps/api && CR_DATA_DIR=$PWD/data uvicorn app.main:app --host 127.0.0.1 --port 8077
# frontend, in a second terminal:
cd apps/web && export PATH=$HOME/.nvm/versions/node/v22.23.3/bin:$PATH && npm install && npm run dev  # -> :5174
```

Other projects use ports 8000 and 8080, so the backend uses 8077. When port 5173 is in use, the frontend moves to 5174.

## Demo (needs Docker)

```bash
# built-in intelligence (this really deploys three containers: nginx, postgres, alpine; then validates and cleans up):
API=http://localhost:8077 bash scripts/e2e_demo.sh
# a real public report (CISA AA22-320A):
REPORT=$PWD/fixtures/sample-scenarios/cisa-aa22-320a.md OUT=$PWD/docs/e2e-evidence-cisa \
  API=http://localhost:8077 bash scripts/e2e_demo.sh
```

The evidence goes to `docs/e2e-evidence/` and `docs/e2e-evidence-cisa/`.

### Deployment exposure (`POST /api/deploy/{id}/up`)

- The default is `{"test_approved":true}`. The system binds to `127.0.0.1` only. PostgreSQL uses trust (internal network, no password).
- LAN mode is `{"test_approved":true,"expose":"lan"}`. The system opens the web service and the database to the same network segment. The response gives `lan_host` and a one-time `db_password` (scram-sha-256). The password does not go into the compose file or git. When the system cannot detect the IP, add `"lan_host":"192.168.x.x"`. The ports are in `report.host_port_mappings` (42000 to 42999).
- Both modes need topology approval first (`POST /api/planning/{id}/topology/approve`).

## Test

```bash
source .venv/bin/activate && PYTHONPATH=apps/api python -m pytest apps/api tests -q   # backend
cd apps/web && npm run e2e                                                            # full flow in a browser (Playwright)
```

## Eight modules and acceptance

See the status table in [`docs/progress.md`](docs/progress.md). See the acceptance results in [`docs/round2-report.md`](docs/round2-report.md): real services, network segmentation, validation verdicts, real reports, and repeatable tests.

## Team rules

The work split for people and agents is in [`AGENTS.md`](AGENTS.md). Treat `~/cr-research-m1` and `~/text2redteamscenario` as read-only reference. They are not correct conclusions.
