# inv-missing integration request

The unit suite still has planner-owned missing-item failures that cannot be corrected within `apps/api/app/cti/missing.py`:

- `planner_dep_software-*` items emitted by `app/planner/dependencies.py` have no `service_ref` when they correspond to an original IR service. `test_round2_rules.UnsupportedSoftwareQuestion` and `test_planning_consistency.UserChosenSubstitute` require this reference so the answer can be applied to the original service. Please preserve/add `service_ref=original.get("id")` to these items.
- That question must retain its plain-language `question` and substitute `suggestions`; the current result for the database-function example only contains id/field/reason/status.

In `missing.py`, raw IR `missing-service-<id>-version` questions retain their stable ID and write-back target. Inventory suppression remains enabled for product-specific resolved/unavailable cases and generic services carrying an inventory resolution; unresolved raw services retain the legacy write-back question for compatibility.

Targeted tests for those raw-IR write-back fields pass. The remaining `service_ref` failures belong to planner-generated questions and need a planner/dependencies.py change by the owning agent/Lead.
