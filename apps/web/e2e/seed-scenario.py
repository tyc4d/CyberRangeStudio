"""Seed one scenario into the e2e API's store without calling the LLM.

Used by e2e/qa-fixes.spec.ts. The IR in fixtures/seed-scenario.json is a real analysis result
(version 1 of a CL0P MOVEit advisory analysis, all missing items still open) exported from the store.
Only the analysis step is skipped; every later call in the spec hits the real API.

usage: seed-scenario.py <scenario_id>   (CR_DATA_DIR selects the store, same default as start-api.sh)
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
os.environ.setdefault("CR_DATA_DIR", str(ROOT / "apps" / "api" / "data"))
sys.path[:0] = [str(ROOT / "apps" / "api"), str(ROOT / "packages" / "contracts")]

from app import store  # noqa: E402

ir = json.loads((HERE / "fixtures" / "seed-scenario.json").read_text(encoding="utf-8"))
ir["id"] = sys.argv[1]
ir["name"] = f"e2e seeded (no LLM) {sys.argv[1]}"
print(store.create(ir)["id"])
