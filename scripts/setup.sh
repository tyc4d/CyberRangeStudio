#!/usr/bin/env bash
# Set up the Python env for the backend. Run from repo root.
set -e
cd "$(dirname "$0")/.."
python3 -m venv .venv
. .venv/bin/activate
pip install -U pip -q
pip install -q -r apps/api/requirements.txt
pip install -q -e packages/contracts
echo "setup done"
