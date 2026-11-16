# Round 3 scoped — Instructor tester

Read `COMMON.md` and `R3-SCOPE.md` first. Test only; do not edit product code. Use a real Chromium browser at `http://127.0.0.1:5199/` (the 5177 preview is GET-only). Start the report with your actual model/reasoning setting; the required template is `cr-codex-ultra` (Ultra, Fast modes off). Do not read previous QA reports before scoring.

Use `fixtures/cti-candidates/equifax-2017-struts-db/report.md` and the matching `evidence-brief.pdf`. Give the scenario a name containing `instructor-r3`. In the browser, work from import through analysis, citation comparison, missing information, attack flow, dependencies, topology, approval, and IaC preview. Check source attribution, CVE propagation, service identity, deploy blockers, and whether assumed versions are labelled as assumptions. Review deployment preflight and instructor-access messaging without deploying. Explicitly mark actual deployment and attack verification NOT TESTED because of R3 scope.

Keep screenshots at each step and a Playwright trace for the main browser path in `reports/overnight/evidence/qa-instructor-r3/round3/`. Write `reports/overnight/worker-reports/qa-instructor-r3-round3.md` with the shared rubric, severity, reproductions, and all limitations. Do not call deploy/down/reset/validate endpoints or use PVE/Docker.
