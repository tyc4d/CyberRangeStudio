# Round 3 scoped — Independent UX tester

Read `COMMON.md` and `R3-SCOPE.md` first. Test only; do not edit product code. Use a real Chromium browser at `http://127.0.0.1:5199/` (the 5177 preview is GET-only). Start the report with your actual model/reasoning setting; the required template is `cr-codex-ultra` (Ultra, Fast modes off). Do not read previous QA reports before scoring.

Walk all ten pages in Chinese and English, focusing on mobile widths 360–430 and desktop 1280×720 / 1440×900. Create a scenario named with `ux-r3` from `fixtures/sample-scenarios/clop-moveit-advisory.md`, and a second scenario from `fixtures/cti-candidates/negative-insufficient-intel/`. Check navigation, text size, touch targets, keyboard focus, loading/error/empty states, direct deep links, truthful status wording, and whether a short report gives useful next steps. Review instructor entry messaging without claiming actual reachability.

Keep screenshots for each page and a Playwright trace for the main user path in `reports/overnight/evidence/qa-ux-r3/round3/`. Write `reports/overnight/worker-reports/qa-ux-r3-round3.md` with the shared rubric, severity, reproductions, and all limitations. Do not call deploy/down/reset/validate endpoints or use PVE/Docker.
