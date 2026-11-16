# inv-map (cr-codex) — CVE propagation + inventory-aware component mapping
Read docs/inventory/DESIGN.md first (authoritative — esp. the Resolution contract). Follow AGENTS.md. Stay strictly in your owned file set; cross-file needs go to reports/inventory/requests/<you>.md + hc send t31. Do NOT start other agents. Commit small. hc send t31 when done or blocked.

Deliver: (1) apps/api/app/cti/analysis.py — propagate a report-level CVE onto the service/action whose cited
evidence names that vuln (so a Log4Shell action+service actually carries CVE-2021-44228), without inventing CVEs
not in the source. (2) apps/api/app/planner/dependencies.py — when assigning a service's catalogue_component,
call app.planner.inventory.resolve(name, version, cves, attack_technique) and set catalogue_component /
is_substitute / version_basis / cve / substitute_of from the Resolution; feed inventory_summary() into the
analysis context (pre-LLM grounding). Never claim the original product when a substitute is chosen. Import
inventory; do NOT edit catalogue/inventory.py. Tests: a Log4Shell-on-Horizon fixture resolves the Log4j service
to the vulhub substitute with version_basis=substituted and the Horizon host to not_reproducible; a same-product
deployable case stays exact. hc send t31.
