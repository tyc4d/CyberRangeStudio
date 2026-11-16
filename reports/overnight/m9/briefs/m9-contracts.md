# m9-contracts (cr-claude)
Read reports/overnight/m9/PLAN.md and reports/overnight/m9/CONTRACT.md first (authoritative). Follow AGENTS.md. Stay strictly inside your owned file set. Do NOT edit modules 1-8 files, main.py, or other workers' dirs; if you need a change there, write reports/overnight/m9/requests/<you>.md and hc send t31. Do NOT start other agents. Commit small on your branch. When done or blocked: hc send t31 with a one-line status + your report path under reports/overnight/m9/.

Deliver: packages/contracts/schemas/poc-validation.schema.json (ValidationPlan, ValidationItem, PocCandidate,
PocManifest, ExecutionResult+Evidence, ChainValidation, ExportManifest — exactly the CONTRACT shapes), wire it
into packages/contracts/cr_contracts so iter_errors("poc-validation", obj) works, and mirror the types in
packages/contracts/src/types.ts. Scaffold apps/api/app/poc/{__init__,models,store,service}.py and
apps/api/app/routers/poc.py with the 6 documented routes returning HTTP 501 (registered via a note for the Lead
to add to main.py ROUTER_STATUS — do NOT edit main.py yourself; put the exact line in reports/overnight/m9/requests/m9-contracts.md).
poc/store.py: create the 5 SQLite tables under DATA_DIR. poc/service.py: implement ONLY plan() using
planner/reproducibility.classify_action to set strategy/not_executable (real logic, no stub). Unit-test the schema
+ plan(). This is the dependency for everyone else — be fast and correct, then hc send t31.
