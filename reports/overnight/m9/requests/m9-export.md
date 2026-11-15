# m9-export → Lead requests (files outside my set)

1. **Wire it up (service.py / routers/poc.py, not mine):**
   - `poc/service.py`: `def export(scenario_id): from app.poc.export import export as _e; return _e(scenario_id)`
   - `routers/poc.py` `/export`: `return service.export(scenario_id)`; `KeyError` → 404;
     `app.poc.export.bundle.ExportError` → 409 (export refused fail-closed, e.g. secret found);
     `app.iac.generator.PlanError` from `validate_id` → 400.
   - Response is exactly `{bundle_path, manifest}` (CONTRACT §HTTP API).

2. **Contract question — "distinguish 描述檔可匯出 vs 環境可完全重建 in the manifest".**
   `ExportManifest` is `additionalProperties: false`, so I did NOT add a field. Today:
   `rebuildable` = 環境可完全重建; descriptors are always exportable when the scenario exists; the
   README has an explicit two-row table. If you want it machine-readable in manifest.json, m9-contracts
   could add optional `export_levels: {descriptors_exportable: bool, fully_rebuildable: bool}`; it is a
   two-line change in `build_bundle` on my side.

3. **Contract tension — terraform/ansible in `missing_for_rebuild`.** The brief says list them; CONTRACT says
   `rebuildable=false if any are missing`. Applied literally, rebuildable would always be false (the project
   never generates Terraform/Ansible), making the field useless. I list them as entries starting with
   `infrastructure/terraform/` / `infrastructure/ansible/` and treat only those two as NON-blocking; every
   other entry forces `rebuildable=false`. `verify_bundle` enforces exactly that. Your call if you prefer
   otherwise.

4. **Judgement call — deploy-time secrets.** `${CR_DB_PASSWORD:?...}` / `${CR_PG_PASSWORD:?...}` are values the
   operator generates fresh at deploy time (manager.do_up does this itself), so they are NOT counted as
   "missing secrets"; they appear in `.env.example` as empty REQUIRED placeholders (compose refuses to start
   until set). A secret that genuinely cannot be regenerated would need an IR/plan marker that does not
   exist today.
