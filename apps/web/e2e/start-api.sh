#!/usr/bin/env bash
# Starts the CyberRange API for the browser e2e run. Used by playwright.config.ts (webServer).
# Needs a Python venv with the backend deps and an env file holding OPENAI_API_KEY.
#   CR_VENV      venv directory           (default: <repo>/.venv)
#   CR_ENV_FILE  env file to load         (default: <repo>/.env)
#   CR_E2E_API_PORT                       (default: 8077)
#   CR_DATA_DIR  backend runtime data     (default: <repo>/apps/api/data)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
VENV="${CR_VENV:-$ROOT/.venv}"
ENV_FILE="${CR_ENV_FILE:-$ROOT/.env}"
PORT="${CR_E2E_API_PORT:-8077}"
[ -x "$VENV/bin/uvicorn" ] || { echo "start-api: no uvicorn in $VENV (run scripts/setup.sh or set CR_VENV)" >&2; exit 1; }
[ -f "$ENV_FILE" ] || { echo "start-api: env file $ENV_FILE not found (set CR_ENV_FILE)" >&2; exit 1; }
set -a; . "$ENV_FILE"; set +a
export CR_DATA_DIR="${CR_DATA_DIR:-$ROOT/apps/api/data}"
# Use this checkout's contracts package even if the venv has another checkout installed in editable mode.
export PYTHONPATH="$ROOT/packages/contracts${PYTHONPATH:+:$PYTHONPATH}"
cd "$ROOT/apps/api"
exec "$VENV/bin/uvicorn" app.main:app --host 127.0.0.1 --port "$PORT"
