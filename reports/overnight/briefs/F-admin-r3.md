# Round 3 scoped — CyberRange administrator tester

Read `COMMON.md` and `R3-SCOPE.md` first. Test only; do not edit product code. Use a real Chromium browser at `http://127.0.0.1:5199/` (the 5177 preview is GET-only). Start the report with your actual model/reasoning setting; the required template is `cr-codex-ultra` (Ultra, Fast modes off). Do not read previous QA reports before scoring.

Use `fixtures/sample-scenarios/demo-intrusion.md` and create a scenario named with `admin-r3`. Through the UI, inspect readiness, IaC, topology approval, deployment placement hierarchy, read-only PVE preflight/status, stopped/not-created states, port/connection display, and whether the UI distinguishes a plan from a deployed environment. Check that the UI explains capacity/backend errors accurately and shows no invented instructor address. This round does not include actual deployment, reset, or cleanup; mark those as NOT TESTED.

Keep screenshots at each step and a Playwright trace for the main browser path in `reports/overnight/evidence/qa-admin-r3/round3/`. Write `reports/overnight/worker-reports/qa-admin-r3-round3.md` with the shared rubric, severity, reproductions, and all limitations. Do not call deploy/down/reset/validate endpoints or use PVE/Docker.
