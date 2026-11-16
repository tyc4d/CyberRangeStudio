# Module 9 — Fix Round 6 (after round-6 final-gate QA CHANGES REQUESTED)

Round-6 QA: all 34 prior findings hold (review1 57/1, review2 89/0, review3 34/0, review4 59/0, review5 24/0;
frontend 4/6/9/10/7). 2 new: R6-01 (P1 export tagged-YAML leak), R6-02 (P2 GUI late-snapshot). Acceptance =
`reports/overnight/m9/review6/test_m9_review6.py` (4 failing) + `review6/check_web_review6.cjs` (4 failing);
keep ALL prior review files + full suite green.

## m9-export (cr-codex-ultra) — R6-01 / P1 — apps/api/app/poc/export/** — MAKE IT FAIL-CLOSED & SOUND
This is the 6th export round; stop the encoding whack-a-mole with a CATEGORICAL fix. Root cause (reviewer-
verified): the redactor does SPAN string-manipulation that only strips a YAML tag (`!!str`, `!!binary`) and
leaves the real scalar/block value; that corrupts the embedded structure; then `_embedded_structure` gets a
parse exception and the code treats "parse failed => no structure to check" as SAFE. So a secret ships with
`contains_secrets=false` / `verify_bundle==[]`.
Fix with these invariants (soundness by construction, independent of encoding):
- **verify_bundle / final scan parse the EMITTED files** (`yaml.safe_load` scenario.yaml, `json.loads`
  scenario.json) so ALL tags/anchors/encodings/multi-line forms are RESOLVED to their values, then walk the
  resolved structure; any secret-named key with a non-empty resolved value (string OR bytes, e.g. `!!binary`) is
  a leak.
- **Redact on PARSED structure, not text spans** — for secret structures embedded inside a description string,
  parse (JSON and YAML), redact the resolved value, re-serialize; never leave a half-cleaned span.
- **Fail-closed:** if an embedded structure cannot be parsed after cleaning, OR a secret-named value cannot be
  proven removed, REFUSE the export (raise ExportError) — a parse failure is UNSAFE, never "no structure => safe".
  A clean refusal is acceptable; keeping the description is not required.
Net guarantee: the exporter emits a bundle ONLY when a real parser confirms no secret-named key carries a value;
otherwise it refuses. Make `test_tagged_yaml_builder_removes_real_parsed_secret_or_refuses` (4 params) +
any review6 verifier cases pass; keep ALL prior export tests green (incl. clean-export + legitimate content).
(Assigned to cr-codex-ultra for a rigorous soundness-oriented pass.)

## m9-gui (cr-claude) — R6-02 / P2 — apps/web/src/pages/PocPage.tsx (+ i18n, components/ui.tsx retry gate)
A snapshot read that STARTED during an execute but RETURNS AFTER it completes still restores stale verdicts:
- `PocPage.tsx:373` unconditionally calls `reportAct.run()` after a chain response even mid-execute; and the
  guard at `:360`-`:363` only compares `__execStarted` and checks `__execDone==__execStarted` at RESPONSE time,
  not whether the snapshot BEGAN while an execute was in flight — so an old report/chain arriving after the new
  execute completes overwrites correct new results (reproduced 2/2, unverified 0/2 while raw results are FAIL/FAIL;
  old chain even restores PASS badges).
- The `ApiNotice` retry entries (`:663`, `:671`; `components/ui.tsx:221`) have no exec-busy gate.
Fix: stamp each snapshot read with the execute generation IN EFFECT WHEN IT STARTED, and reject applying it if a
newer execute has started or completed since; don't auto-run report mid-execute; gate the retry entries on
`execAct.busy`. The current execute's results must never be overwritten by a snapshot that began before/during it.
Acceptance: `review6/check_web_review6.cjs` 8/8, tsc clean, prior web scripts green.

Report hc send t31 when done. Lead integrates, re-runs all six review files + full suite, then a FINAL reviewer pass.
#5 deploy-layer guaranteed-cancel handle remains the one honest deferred item. (Owner is being told export hit 6
rounds and that a fail-closed export is now applied — posture decision surfaced for the owner.)
