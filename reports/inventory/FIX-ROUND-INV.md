# Inventory — Fix Round (after QA CHANGES REQUESTED)
QA report: reports/inventory/review/inv-review.md (7 findings, 3 P1 honesty). Acceptance script:
/home/tyc4d/cr-project/.worktrees/<your-wt>/review/qa_inventory.py (run: cd apps/api &&
PYTHONPATH=<wt>/packages/contracts /home/tyc4d/cr-project/.venv/bin/python ../review/qa_inventory.py — it must
report all checks PASS). Also keep the full suite green: cd apps/api && PYTHONPATH=<wt>/packages/contracts
/home/tyc4d/cr-project/.venv/bin/python -m pytest . ../../tests/unit -q. NO manufactured results; honesty first.

## m9... no — inv-map (cr-codex) — apps/api/app/planner/dependencies.py + apps/api/app/cti/analysis.py
- **#1 P1 (core goal):** plan_dependencies must NOT let the old unsupported-* matcher override the resolver's
  chosen substitute. When resolve() picks a deployable substitute (Log4Shell -> vuln-log4shell-solr), that
  component + is_substitute + version_basis=substituted must SURVIVE into the plan and topology as a deployable
  substitute target. The resolver is the authority; do not wipe it with the old sentinel.
- **#2 P1 (honesty):** propagate a source CVE to a service ONLY when the SOURCE associates them (the CVE appears
  in a quote cited by THAT service/action). NEVER attach a CVE just because resolve() returns a component.
  CVE-2017-5638 must not leak onto PostgreSQL, and PostgreSQL must not be substituted to Struts.
- **#3 P1 (honesty):** never add a CVE to a service's source `cve` that the source did not state. Keep the
  component's `reproduces_cve` (capability) SEPARATE from the service's source-stated `cve`. assumed version is
  fine; a fabricated source CVE is not.
- **#4 P2:** respect an explicit user component choice (field_sources.catalogue_component="user" /
  substitute_basis="user_chosen"); do not overwrite it on replan while still labelling it user_chosen.
- **#6 P2:** an `obtainable` component (Windows Server eval) must stay tier=obtainable in the plan, not be
  recorded as `have`.
- **#7 P2:** the original Horizon host keeps external_platform / not-reproduced in the dependency IR.

## inv-missing (cr-codex) — apps/api/app/cti/missing.py
- **#5 P2:** a raw-IR unavailable product (e.g. VMware Horizon / Citrix ADC with no inventory metadata yet) must
  suppress the moot version question by calling resolve() directly (needs_question=false), not require the
  service to already carry inventory metadata. Keep genuinely-resolvable version questions.

Lead integrates + re-runs qa_inventory.py + full suite, then re-review. Do not merge/push until QA passes.
