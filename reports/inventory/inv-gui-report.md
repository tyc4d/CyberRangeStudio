# inv-gui — done (branch agent/inv-gui, commit 3bd617a + this report)

## What
- `apps/web/src/components/InventoryPanel.tsx` (new): "Component inventory" card on the Software (deps) page.
  Per extracted component: tier tag (have / obtainable / unavailable), "needs version" flag, deployed component or
  "not deployed", substitute tag + "stands in for X", reproduced CVEs, version basis (stated / assumed /
  substituted / user_supplied), the backend's reason (collapsed, shown verbatim), override state + "automatic
  proposal was …". Summary counts in the card head.
- Override control (per row, opens below the table): accept substitute (only offered for a substitute; it stays
  flagged), use another component (picker lists have/obtainable only), set version (free text or the question's
  suggestions), back to automatic. The UI only forwards; the backend decides the new Resolution.
- `apps/web/src/lib/api.ts`: types + `api.inventory()`, `api.scenarioInventory(id)`, `api.overrideInventory(id, body)`.
- `apps/web/src/pages/DepsPage.tsx`: 1 import + 1 mount line.
- Route proposal for the Lead: `reports/inventory/requests/inv-gui.md`.

## i18n / RWD (base-agnostic, as agreed)
- Own zh-TW + en tables inside the component; `en: Record<keyof typeof zh, string>` → tsc fails on a missing or
  extra key. Locale follows the app's `cr.locale` storage key (zh-TW default). At integration the Lead may move the
  keys into `src/i18n/*.ts` (`inv.*`), not required.
- Uses existing classes only (`card flush`, `tbl`, `tag user|major|blocker|sub`, `chip`, `notice`, buttons).
  A plain `table.tbl` with a thead → the RWD line's `stackTables` stacks it on phones automatically. The editor is
  rendered below the table (not as a colSpan row) so stacked-row labels stay correct.

## Tests (really run)
- `tsc --noEmit`: pass.
- `apps/web/e2e/inventory-panel.spec.ts` (Playwright, API fully mocked; mock rows = real `resolve()` outputs in
  `e2e/fixtures/inventory-mock.json`): 3/3 pass —
  zh-TW render + accept/version override requests + replace picker hides unavailable; en strings; narrow (390px)
  panel does not overflow its card. Run with a vite-only config (the default config also boots the real API;
  the spec doesn't need it but works under it too).
- Screenshots: `reports/inventory/inv-gui-desktop.png`, `reports/inventory/inv-gui-narrow.png`.
- NOT done: no real-backend run (the routes don't exist yet). No full-page phone check: this base (main) has no
  mobile layout, so the app shell itself is ~1040px wide at 390px viewport — pre-existing, not from this panel.

## Found while building (for Lead / inv-catalogue)
- `question.suggestions` are display labels ("Windows Server 2019 Evaluation"); `resolve()` does not accept them as
  a version (verified → needs_question again). The UI maps a clicked suggestion to the matching entry's pinned
  version ("2019"). Cleaner: add component ids next to the suggestions (noted in the request file).
