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

---
## Round 2 (GUI): export format + download route — exact lines for `routers/poc.py` / `service.py`

Implemented in my set (`app.poc.export`): `export(scenario_id, fmt)` with fmt `full|iac|evidence`
(unknown/absent → `full`; `iac` = infrastructure/ + manifest.json; `evidence` = validation/ + evidence/ +
manifest.json, and its manifest has `rebuildable=false` + a leading missing entry saying the infra is not in
this archive). Non-full files are named `...-iac.zip` / `...-evidence.zip`. Every variant goes through the same
redaction + fail-closed secret scan. `latest_bundle(scenario_id) -> Path | None` returns the newest recorded
export that still exists **inside `DATA_DIR/exports/<id>/`** (a DB row pointing elsewhere is ignored).
Note: it reads `poc_exports` via `poc_store._conn/_LOCK` because poc/store.py has no getter; if you prefer, add
`poc_store.latest_export_path()` and I'll switch.

`poc/service.py` (replaces the stub):
```python
def export(scenario_id: str, fmt: str | None = None) -> dict[str, Any]:  # m9-export
    from app.poc.export import export as _export
    return _export(scenario_id, fmt)
```

`routers/poc.py` — imports:
```python
from fastapi.responses import FileResponse
from app.iac.generator import PlanError
from app.poc.export import ExportError, latest_bundle
```
model (next to ExecuteRequest):
```python
class ExportRequest(BaseModel):
    format: str | None = None  # 'full' | 'iac' | 'evidence'; unknown/absent -> 'full'
```
replace the `/export` route and add the download route right after it:
```python
@router.post("/{scenario_id}/export")
def poc_export(scenario_id: str, request: ExportRequest | None = None):
    """{bundle_path, manifest} (m9-export)."""
    try:
        return service.export(scenario_id, request.format if request else None)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown scenario")
    except PlanError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ExportError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/{scenario_id}/export/download")
def poc_export_download(scenario_id: str):
    """ZIP bytes of the most recent export for this scenario (404 if none)."""
    try:
        path = latest_bundle(scenario_id)
    except PlanError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if path is None:
        raise HTTPException(status_code=404, detail="no export for this scenario")
    return FileResponse(path, media_type="application/zip", filename=path.name)
```
(`ExportRequest | None = None` keeps a body-less POST working → full bundle.)
