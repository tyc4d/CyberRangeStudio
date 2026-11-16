# inv-missing (cr-codex) — substitute-first missing-item logic
Read docs/inventory/DESIGN.md first (authoritative — esp. the Resolution contract). Follow AGENTS.md. Stay strictly in your owned file set; cross-file needs go to reports/inventory/requests/<you>.md + hc send t31. Do NOT start other agents. Commit small. hc send t31 when done or blocked.

Deliver: apps/api/app/cti/missing.py — consume the inventory Resolution (via the service's resolved fields /
inventory.resolve) so that: a component auto-resolved to a have/obtainable (incl. substitute) component does NOT
raise a version question; an unavailable component with no substitute does NOT raise a moot version question (the
host/step is marked not_reproducible elsewhere); a GENUINE deployable-version ambiguity still raises its question
with suggestions, as today. Keep all other missing-item categories (network, OS, accounts, entry CVE when truly
absent) working. Do not weaken honesty: substitutes stay flagged. Tests: the scn_6ad6ad85538c-style Log4Shell +
Horizon case yields NO Horizon/Log4j version question (auto-substitute) while a real ambiguous deployable version
still asks. hc send t31.
