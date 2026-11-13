# Dependency and topology planner

Offline fixture: `fixtures/offline_scenario.json` exercises exact catalogue mapping, an explicitly flagged IIS substitute, an unmet SQL Server dependency, and confirmed versus unconfirmed relations.

Run the structural checks from the repository root:

```sh
source /home/tyc4d/cr-project/.venv/bin/activate
PYTHONPATH=apps/api python -m pytest apps/api/app/planner/test_offline.py -q
```

The current shared venv did not include `pytest`; the fixture checks were run directly with Python and passed. The API smoke test used an isolated `CR_DATA_DIR` on port `8082`; catalogue, dependency generation, topology generation/readback, scenario PUT/versioning, and action/relation CRUD all returned the expected results.
