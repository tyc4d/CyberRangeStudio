# inv-gui → Lead: route proposal (Lead wires the router; the frontend calls exactly these)

Client methods are in `apps/web/src/lib/api.ts` (`api.inventory`, `api.scenarioInventory`, `api.overrideInventory`)
with typed shapes (`InventoryResolution`, `InventoryEntry`, `InventoryItem`, `InventoryOverrideRequest`).
Until a route exists the panel shows the standard "backend not provided yet" notice (404/501 → `unimplemented`).

## 1. `GET /api/planning/inventory`
`{"entries": inventory_entries()}` — unchanged output of `app.planner.inventory.inventory_entries()`.
Used to fill the "use another component" picker (the UI hides `tier == "unavailable"`).

## 2. `GET /api/planning/{scenario_id}/inventory`
`{"items": [InventoryItem, ...]}`, one per extracted service, plus hosts whose OS goes through resolve:
```
InventoryItem = {
  ref_kind: "service" | "host",
  ref_id: <service.id | host.id>,
  name: <product name as extracted>,            # host: its os
  version: <stated version> | null,             # host: os_version
  cves: [<CVE on the service>],                 # after inv-map propagation
  attack_technique: <technique id> | null,
  resolution: Resolution,                       # EFFECTIVE resolution (after override), exact DESIGN keys
  auto_resolution: Resolution | null,           # the automatic proposal, only when an override changed it
  pending_confirmation: bool,                    # true when a substitute is only a recommendation and is not deployed
  override: {action, component_id?, version?, at?} | null
}
```
`resolution` = `resolve(name, version, cves, attack_technique)` with the override applied (see 3). If
`pending_confirmation=true`, it is a proposal only, not an adopted deployment choice. 404 for an unknown
scenario with a real detail text (not bare "Not Found", which the client reads as "route missing").

## 3. `POST /api/planning/{scenario_id}/inventory/override`
Body `{ref_id, action, component_id?, version?}`; response `{"items": [...same as 2...], "scenario": <updated IR>}`
(`scenario` optional; when present the UI absorbs it so the deps tables refresh).
Persist the override on the IR item (suggest `service.inventory_override` / `host.inventory_override`) so a
re-run of dependency analysis (inv-map) and missing items (inv-missing) honour it:
- `accept` — user confirmed the auto-proposed substitute. Resolution unchanged; STILL `is_substitute=true`
  (substitute_basis `user_chosen` on the IR is fine). Never turns it into the original product.
- `replace` + `component_id` — use that component (must be have/obtainable; 422 otherwise). If it is not the
  same product: `is_substitute=true`, `version_basis="substituted"`, `substitute_of=<original name>`,
  `reproduces_cve` = only what that component really reproduces among the item's CVEs (may be []).
- `version` + `version` — `resolve(name, version, cves, technique, user_supplied=True)` → `version_basis="user_supplied"`.
  The UI sends the entry's PINNED version (e.g. "2019"), not the question's suggestion label: `resolve()` does not
  match "Windows Server 2019 Evaluation" as a version (verified: returns needs_question=true again).
  Optional nicety: add `suggestion_ids` (component ids) next to `question.suggestions` so the UI need not map labels.
- `clear` — drop the override; back to the automatic resolution.

Validation: unknown `ref_id` → 404 with detail; bad action/missing field → 422 (the UI renders FastAPI 422 lists).
An unconfirmed substitute remains visible with `pending_confirmation=true` but is not written into the deployable
dependency plan. Host OS overrides return 422 until the planner can apply them safely; `clear` may remove a stale
host override.

## Mount point
`apps/web/src/pages/DepsPage.tsx`: one import + one line `{has && <InventoryPanel ir={ir} />}` above the catalogue
card. On the RWD/i18n line the mount is the same single line; the panel's strings are self-contained (see report).
