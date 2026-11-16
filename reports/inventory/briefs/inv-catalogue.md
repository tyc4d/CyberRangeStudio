# inv-catalogue (cr-claude) — the inventory data layer (dependency for others)
Read docs/inventory/DESIGN.md first (authoritative — esp. the Resolution contract). Follow AGENTS.md. Stay strictly in your owned file set; cross-file needs go to reports/inventory/requests/<you>.md + hc send t31. Do NOT start other agents. Commit small. hc send t31 when done or blocked.

Deliver: extend apps/api/app/planner/catalogue/components.json so every entry carries: tier
(have|obtainable|unavailable), reproduces_cve (list), substitute_for ({products,cves,techniques} it can stand in
for — build on the existing substitutes_for), obtainability ({source, pullable, est_cost_usd}), and add OS base
image entries (the Windows/Linux versions we have or can get within $50). Create apps/api/app/planner/inventory.py
with: resolve(product_name, version=None, cves=None, attack_technique=None) -> Resolution (EXACT shape + rules in
DESIGN), a CVE->component index, and inventory_summary() returning a compact availability summary for the LLM
prompt. resolve() is the deterministic decision point — real logic, not a stub (map Log4Shell/CVE-2021-44228 ->
vuln-log4shell-solr as a substitute with version_basis=substituted and needs_question=false; unsupported +
no-substitute -> needs_question=false, not_reproducible reason; deployable-with-real-version-ambiguity ->
needs_question=true). Unit-test resolve() for: same-product-have, CVE->substitute, unavailable-no-substitute,
genuine-version-question, OS base resolution. You are the dependency for inv-map/inv-missing/inv-gui — be fast + correct.
