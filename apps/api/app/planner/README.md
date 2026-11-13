# Dependency and topology planner

Offline fixtures: `fixtures/offline_scenario.json` exercises exact catalogue mapping, substitutes, and unmet dependencies. `fixtures/demo_roles.json` models an exposed web application and an internal database with a confirmed dependency; role-only hosts receive explicitly labelled substitutes.

Run the structural checks from the repository root:

```sh
source /home/tyc4d/cr-project/.venv/bin/activate
PYTHONPATH=apps/api python -m pytest apps/api/app/planner/test_offline.py -q
```

`pytest apps/api/app/planner/test_offline.py -q` passed all 7 checks. The API smoke test used an isolated `CR_DATA_DIR` on port `8082`; catalogue, dependency generation, topology generation/readback, scenario PUT/versioning, and action/relation CRUD returned the expected results.
