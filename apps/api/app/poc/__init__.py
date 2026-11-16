"""Module 9: PoC discovery, exploit validation & environment export.

Package layout (owners per reports/overnight/m9/PLAN.md):
  models.py   dataclasses mirroring packages/contracts poc-validation.schema.json
  store.py    SQLite persistence (poc_plans, poc_candidates, poc_runs, poc_chains, poc_exports)
  service.py  orchestration; plan() is implemented here, the rest are stubs for owners
  discovery/  m9-discovery   runner/ m9-runner   chain/ m9-chain   export/ m9-export

CONTRACT.md in reports/overnight/m9/ is authoritative; do not deviate.
"""
