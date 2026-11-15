# claude-mobile-rwd follow-up: readable text first, then mobile review fixes

Branch `agent/claude-mobile-rwd`, on top of 48027af. **Not committed** (per Lead). The working tree has only source, spec and report changes.
The Lead restored `apps/web/e2e/artifacts/results.json` and the evidence PNGs to HEAD, and they are not in `git status`.

## Priority order (product owner, via Lead)

1. Text too small, whole site. Phone body text at least 16 px. Labels and secondary text at least 14 px.
   Desktop 11–12 px text that carries information is raised. Compact badges keep a 12 px minimum.
2. Then the independent review's mobile blockers:
   - Analysis grid
   - table semantics
   - summary touch target
   - observer

## 1. Text size (done first)

### Desktop (> 760 px)

| Element | Before | After |
|---|---|---|
| Body | 13 px | 14 px |
| Tables, notices, page descriptions, key/value lists, quotes, empty states | 12 px | 14 px |

- Every other desktop rule at 10/11 px is now 12 px. Rules at 12 px are now 13 px.
- This covers `theme.css`, `PlacementPanel.css` and `PdfViewer.css`.
- The smallest left is 12 px, on compact labels: badges, tags, zone kicker, node numbers.
- Inline `fontSize` in TSX went up one step: 10/11 → 12, 12 → 13, 13 → 14. That is 118 values across pages and shared components.

### Phone (≤ 760 px)

- 16 px:
  - body, buttons, inputs, field labels
  - notices, empty states, page descriptions
  - table cells, key/value lists, quotes
  - flow findings, topology paths, host details, home hero text
- At least 14 px:
  - badges, tags, column headers, pills, metric labels
  - stage-strip state, legend, design-check list, tech details
  - inline secondary text: inline 12/13 px is raised to 14 px, and inline 14 px to 16 px
- Small buttons are now 44 px tall (were 40 px).
- Flow sidebar summaries and Deploy host-detail headings and code: 14 px, which was missed in the first pass.

### Check

Read-only browser run, below:
- Phones: no visible text under 14 px on any of the 10 pages at 360/390/430 in zh-TW and en.
- Desktop at 1440: no text under 12 px on any page.
- No horizontal overflow at any size.

## 2. Review fixes

1. **Analysis two-column grid squeezed on phones.**
   - The inline `gridTemplateColumns` and table `minWidth` moved into CSS classes (`.analysis-split`, `.analysis-tbl.w640/.w700/.w760`). Desktop values are the same.
   - On phones the grid is one column. The actions and relations tables drop `min-width` (0) and use `table-layout: auto`.
2. **Stacked-table semantics** (`src/lib/stackTables.ts`, `theme.css`).
   - The header row is no longer `display: none`. It is visually hidden (clip) and stays in the accessibility tree.
   - ARIA table roles are set (`table`, `rowgroup`, `row`, `columnheader`, `cell`/`rowheader`), because `display: block` can remove native table semantics.
   - Column names are real DOM elements (`<span class="cell-label" aria-hidden="true">`), not `::before`. They are aria-hidden because the header association already gives the name, so a screen reader does not read it twice.
   - The labels are hidden on desktop. The old `data-label` / `::before` rules were removed.
3. **PlacementPanel technical-details summary.** At least 44 px tall on phones, as a flex row across the full width. The Flow "about"/"version" summaries are 44 px too.
4. **MutationObserver.** A text change reports a Text node, so the Flow-canvas check now uses its `parentElement` (`elementOf()`). Before, `closest` was undefined on Text nodes, so every canvas text change scheduled a rescan. Label insertion does not change the DOM when the labels are already correct, so the observer does not loop.

## Tests

- New `apps/web/e2e/mobile-rwd.spec.ts`. It is read-only: every non-GET `/api` request is aborted, and the test fails if one was attempted. It needs an existing scenario in `CR_E2E_SCENARIO` and skips without it.
  - At 360/390/430 on Analysis:
    - no sideways scroll
    - one grid column
    - tables have `min-width` 0 and fit the viewport
    - `role=table`, header not `display:none`, `columnheader` > 1, rows/cells have roles
    - a visible `.cell-label` matching its header
    - no visible text under 14 px
    - body, table cells and notice text at least 16 px
  - At 390 on Deploy: the technical-details summary is at least 44 px tall (when the runtime shows it), and there is no overflow.
  - At 1440 on Analysis: two columns, table `min-width` 640/760, tables not stacked, no text under 12 px.
- Updated earlier (uncommitted, same working tree): `full-flow.spec.ts`, `qa-fixes.spec.ts`, `motion.spec.ts` selectors use roles, labels and test ids, with text from `src/i18n/zh-TW.ts`.
  `equifax-goal.spec.ts` does not exist on this branch.

## Verification (exact)

### Static checks
- `npx tsc --noEmit`: pass.
- `npm run build`: pass (existing > 500 kB chunk warning only).
- `npm run i18n:check`: 0 hard-coded strings. Key sets are equal.
- `git diff --check`: clean.
- e2e type check: only the existing missing `@types/node` errors. They also occur in unchanged `seed.ts`.
- `playwright test --list --reporter=list`: 23 tests in 4 files load. No artifact was written.

### Browser runs (read-only, existing scenario `scn_6125b061b4af` on the already-running API 127.0.0.1:8077)

| Run | Server | Result |
|---|---|---|
| `CR_E2E_SCENARIO=scn_6125b061b4af npx playwright test e2e/mobile-rwd.spec.ts --reporter=list --output=<scratchpad>` | own Vite 127.0.0.1:5198 | **5 passed**, 0 write requests |
| Screenshot audit (`shots-followup.mjs`), 10 pages × 360/390/430 × zh-TW/en | own Vite 127.0.0.1:5191, non-GET aborted | after the last CSS fix all OK: no overflow, no text < 14 px, no control < 36 px, no page errors, `blockedNonGET = []` |
| Same audit, 10 pages × 1440 × zh-TW/en (en: 8 pages) | same | no overflow, no text < 12 px, no page errors |

- Screenshots: `/tmp/claude-1000/-home-tyc4d-cr-project--worktrees-claude-mobile-rwd/8d2ab891-5f61-428c-bb66-3b06a9cd4419/scratchpad/followup-check/` (older folders kept).
- No POST/PATCH/PUT/DELETE was sent. No up, down or reset. No deployment or probe. The full E2E suite was not re-run.
- Both Vite servers were stopped afterwards (5191 by PID; 5198 by Playwright).

## Changed files (uncommitted)

- `apps/web/src/styles/theme.css`
  - desktop sizes
  - phone floors
  - `.analysis-*`
  - `.cell-label`
  - stacked-table rules
  - capability-note summary
- `apps/web/src/pages/PlacementPanel.css`: sizes, tech summary at 44 px, inspector headings/code
- `apps/web/src/components/PdfViewer.css`: sizes
- `apps/web/src/lib/stackTables.ts`: ARIA roles, DOM labels, `elementOf()` observer fix
- `apps/web/src/pages/AnalysisPage.tsx`: grid/table classes instead of inline styles, inline sizes
- Inline `fontSize` only:
  - `src/components/ui.tsx`, `src/components/VersionBasis.tsx`
  - `src/pages/{Deploy,Deps,Flow,Home,Iac,Import,Missing,Report,Topology}Page.tsx`
- `apps/web/e2e/mobile-rwd.spec.ts` (new)
- `apps/web/e2e/{full-flow,qa-fixes,motion}.spec.ts` (selector update, earlier task)
- this report

## Not verified / limitations

- Screen-reader output was not tested with a real screen reader. Roles and the accessibility tree were checked in Chromium through Playwright only.
- Chromium emulation only. Not tested on physical iOS Safari or Android devices.
- The Flow canvas card text is still scaled by the canvas zoom: minimum 0.8 on phones.
- Desktop text is larger, so desktop pages are a bit longer.
  - Layout density was checked at 1440 only, with no overflow.
  - 1024–1280 px widths were not checked in this follow-up.
- React may rewrite a cell's text, which removes its label element. The observer adds it back in the next animation frame.
- Not re-run:
  - full-flow (2 tests)
  - the deploy-related qa-fixes tests (2)
  - motion and the other qa tests after the type change (selectors do not depend on font size)

---

# Round 3: instructor access block + 44 px touch targets (uncommitted)

The product owner approved this scope via the Lead: an instructor gets usable connection facts quickly, like TRAPA. The UI QA target is at least 70.
Work continued on the current diff. Nothing was reset. Not committed and not integrated.

## Instructor access block (Deploy page)

New file `apps/web/src/pages/InstructorAccess.tsx`. It sits above the hosts panel and is i18n'd: 38 keys `ia.*` in zh-TW and en.
The UI makes no PVE, network or deployment write. The component sends no request of its own.

### Evidence rules (Lead clarifications applied)

| Case | What the UI shows |
|---|---|
| Source of addresses | only `status.published_ports`, which the backend reads from the running gateway. Shown only while state = running. |
| Bound port, no evidence | "可達性未驗證 / Access not verified". A bind is not shown as reachable. |
| Loopback `127.x` / `::1` | "僅限平台主機本機 / Platform host only". No LAN claim. |
| Interface address (for example 192.168.x) | "區網介面位址" + "可達性未驗證". No reach claim. |
| `0.0.0.0` / `::` | "綁定位址（所有介面）". Not a destination, so no copy button. Never marked reachable, even if the server says so. |
| "可連線 / Reachable" | only if the backend sends explicit evidence on the entry (`reachable: true`). The current backend never sends it, so this label does not appear today. |
| Proxmox (zero-NIC workers, no inbound path) | "講師入口尚未提供". No VM, IP or port is presented as reachable. No guessed address or credentials. |
| Not running / no published ports / status unknown | a plain sentence. No rows. |
| Scenario-internal facts | a folded section, always badged "僅限靶場內 / Range only". It lists plan hosts, network segments, services as name + protocol/port, and the allowed internal connections (`plan.connections`). |

- The old "連線位址" block inside the Deploy details is removed. It read ports from the last start record, not live status.
- The `published-ports` test id moved to the new table.
- Old keys `dp.ports.*` were removed. `qa-fixes.spec.ts` now expects `ia.scope.local` and `ia.st.unverified`.

## 44 px touch targets on phones (independent review findings + new audit)

| Control | Before | After |
|---|---|---|
| Flow zoom Controls | 34 px | 44 px |
| node-toolbar | 32 px | 44 px |
| canvas-tools | 40 px | 44 px |
| PDF viewer buttons | 36 px | 44 × 44 px |
| ref-row icon (removes a flow line; interactive) | 28 px | 44 px |

The stricter audit then found more, now fixed:
- Brand link: 30 px → 44 px.
- "← previous step" links: 26 px → 44 px.
- Import quote buttons: inline `minHeight: 0`, 42 px → 44 px.
- `summary` folding headers, checkbox label rows, `button.link`, analysis quote chips: 44 px.
- Flow card edit fields (inside the zoomed canvas): 56 px in CSS, so they render at 44 px or more at the 0.8 phone zoom floor.
- Flow lines: the invisible touch stroke is 56 units on phones (22 on desktop), so it is at least 44 px on screen.
- Bug found by the test: React Flow's own `fitView` (used before nodes are measured) and the Controls fit button used the desktop floor of 0.5 zoom.
  - Both now use the phone floor of 0.8.
  - Before the fix, card fields rendered 28 px.
- Topology on phones: items are not selectable, draggable or focusable.
  - On Topology, selecting or dragging changes nothing in the plan. On a phone those items were sub-44 px fake targets that also fight panning.
  - Pan and the 44 px zoom buttons still work. Desktop is unchanged.

### Kept smaller (for QA review)

- The Flow connection-handle **dot** stays 11 px, because a larger dot covers the card text. It has an invisible 45 px touch area (`::before`, inset −17 px).
- Links inside running text (paragraphs, notices, table cells) are exempt from the 44 px rule (WCAG 2.5.8 inline exception).

## Tests

`apps/web/e2e/mobile-rwd.spec.ts`, read-only (non-GET aborted, the test fails if one was attempted), `CR_E2E_SCENARIO=<existing id>`.

1. Phone layout and type (5 tests, from round 2).
2. Touch targets at 390 px on /analysis, /missing, /flow (with a node selected), /deploy, /import.
   - Every button, link, input, select, textarea, summary, `[role=button]`, chip and React Flow control must be at least 44 px.
   - A Flow line is measured by its on-screen touch-stroke width.
3. Instructor block, 7 cases: Proxmox no-entry, loopback, LAN, wildcard, explicit evidence, not running, internal section at 360 px.
   - **Scope note (Lead):** these cases answer three GET requests (`deploy status/preflight/health`) with fixed data.
   - They are **UI rendering tests only**. They are not an instructor UI QA score and not connection evidence.
   - The Lead runs a separate read-only blind test on the existing API and scenario.

## Verification (exact)

- Static checks: `tsc --noEmit` pass; `npm run build` pass; `npm run i18n:check` 0 hard-coded strings; e2e type check has no errors except the missing `@types/node`; `git diff --check` clean.
- `git status`: source, specs, `InstructorAccess.tsx`, this report. No artifacts or evidence images.
- `mobile-rwd.spec.ts`: **17/17 passed**, twice in a row after the fitView fix.
  - Existing API 127.0.0.1:8077, scenario `scn_6125b061b4af`, own Vite on 5198.
  - `--reporter=list`, output in the scratchpad.
- 10-page screenshot audit (`shots-44.mjs`, 44 px rule on phones, non-GET aborted):
  - 360/390/430 × zh-TW/en: all pages OK (no overflow, no text < 14 px, no control < 44 px), no page errors, `blockedNonGET = []`.
  - 1440 × zh-TW/en: all 10 pages OK (no overflow, no text < 12 px), no page errors, `blockedNonGET = []`. The 44 px rule applies to phones only.
  - Screenshots: `/tmp/claude-1000/-home-tyc4d-cr-project--worktrees-claude-mobile-rwd/8d2ab891-5f61-428c-bb66-3b06a9cd4419/scratchpad/instructor-check/final44b-*`.
- No deploy, up, down or reset. No probe. No new service. Only my own Vite dev servers ran, and they are stopped at the end.

## Remaining limitations

- Real instructor reachability is not tested. No backend gives reachability evidence, so "可連線" cannot appear yet.
- A LAN-bound local-docker deployment and a running local-docker deployment were only rendered with fixed status answers. No real one was run (deploying is out of scope).
- The PDF viewer 44 px buttons were checked by CSS only: the test scenario has no PDF, so the audit had no PDF toolbar to measure.
- The ref-row icon was checked by CSS only: the scenario has no conditions or operators, so no ref-row was on screen.
- Screen readers, physical iOS and Android devices, and 1024–1280 px desktop widths were not tested.
- Phone-only behavior change for QA to review: the Topology canvas is view-only (pan and zoom) on phones.

---

# Round 3b: hosts-panel safety chip wording (Lead spot check)

The chip in the Deploy hosts panel still said "網路隔離：啟動時檢查 / Network isolation: checked at start". That is an internal deployment term.
Only this text was changed. The backend safety gate and the folded technical details are unchanged.

| State | Before (zh / en) | After (zh / en) |
|---|---|---|
| passed (runtime reports 0 interfaces) | 網路隔離：已確認 / Network isolation: confirmed | 安全檢查：通過 / Security check: passed |
| not yet known (no worker yet) | 網路隔離：啟動時檢查 / Network isolation: checked at start | 安全檢查：啟動前進行 / Security check: before start |
| not confirmed (runtime reports interfaces) | 網路隔離：未確認 / Network isolation: not confirmed | 安全檢查：未確認 / Security check: not confirmed |

- The tooltips now say only: passed; runs before start and nothing starts if it fails; not confirmed, contact an administrator. No isolation, NIC or network wording.
- Test added in `mobile-rwd.spec.ts`: "deploy hosts panel: security-check chip uses plain words in both languages".
  - Read-only, existing scenario, non-GET aborted.
  - It asserts that the chip and its tooltip name a security check and contain none of: 隔離, 網卡, PVE, Proxmox, worker, VM, Compose, isolation, NIC, network interface.
  - Result: 1/1 passed (zh-TW and en). The chip was present: `scn_6125b061b4af` runs on Proxmox and shows "before start".
- Checks: `tsc`, `i18n:check` (0 hard-coded strings) and `git diff --check` pass. No artifacts in `git status`. Not committed.

---

# Round 3c: review REQUEST CHANGES (3 points) + instructor blind-test items

UI, i18n and read-only tests only. No API, deployment or other scope. Not committed.

1. **Isolation/security chip removed** from the Deploy hosts panel (component, usage and 6 `pl.iso.*` keys in both locales).
   - `/status` has no complete isolation evidence, so the UI does not show pass/fail for isolation.
   - Unchanged: the backend safety gate, deploy error messages and the folded technical details (which keep the raw NIC count).
2. **Multi-network note** (follows `docs/deploy-placement-ui.md`).
   - When a plan host is drawn in more than one network zone, one line appears under the zones:
     "同一台主機可以出現在多個網段，它仍然是一台主機。 / A host can appear in more than one network. It is still one host."
   - Not shown when there is no repeat.
3. **Plan wording**
   - InstructorAccess: "允許的內部連線" became "拓樸規劃的內部連線（n） / Planned internal connections (n)".
   - A new line follows it: "這是拓樸規劃，不表示這些連線已經部署或啟用。 / This is the topology plan. It does not mean that these connections are deployed or active."
   - The empty case is "拓樸規劃中沒有內部連線".
   - The PlacementPanel description says "current topology plan / 目前的拓樸規劃" instead of "approved topology".

## Blind-test items added in this round (Lead, interim score 84/100)

- Proxmox "no entry" card ends with one next step:
  "下一步：請管理員設定講師連線入口，完成後回到這一頁查看。 / Next: ask an administrator to set up an instructor entry. Then come back to this page."
- Hosts are named by their short plan code (h1, h2…) in planned connections (`h1 → h2 tcp/8983`) and in published-address targets.
  The role text is in the line's title. It is shown as written and not translated.
- Internal host table: the code is the main label (mono, bold). The role description is cut to 2 lines (`.clamp-2`), and the full value is in `title`.

## Tests (`apps/web/e2e/mobile-rwd.spec.ts`, read-only, non-GET aborted)

- "no isolation/security chip and no implementation terms in its header (zh-TW, en)".
- "multi-network note appears only when a host is drawn in several networks" (real plan).
- "multi-network note text": a GET-only fixed plan answer puts host 1 on 2 networks. The note text and two host tiles are checked. Rendering only.
- Proxmox instructor case: the next-step line is present.
- Internal section:
  - host codes are the main labels;
  - role text is at most 2 lines and has the full `title`;
  - each planned connection reads `from → to` by code;
  - the planned note is present.

## Verification

- `tsc`, `i18n:check` (0 hard-coded strings, 1183 keys) and `git diff --check` pass. e2e type check: only the existing `@types/node` errors.
- Focused run: 10/10 passed. Whole `mobile-rwd.spec.ts`: **20/20 passed**. Both on the existing API 8077, scenario `scn_6125b061b4af`, own Vite on 5198 (stopped afterwards).
- `git status`: no artifacts or evidence images.
