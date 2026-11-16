# inv-gui (cr-claude) — inventory status + substitute override in the UI
Read docs/inventory/DESIGN.md first (authoritative — esp. the Resolution contract). Follow AGENTS.md. Stay strictly in your owned file set; cross-file needs go to reports/inventory/requests/<you>.md + hc send t31. Do NOT start other agents. Commit small. hc send t31 when done or blocked.

Deliver: surface each extracted component's inventory status (have/obtainable/unavailable), the chosen
component/substitute, and the reproduces_cve, on the analysis/missing/deps UI (reuse existing components +
styling, match the finished mobile RWD). Add an OVERRIDE control so the user can accept/replace the auto-proposed
substitute or supply a version. Add one method group to apps/web/src/lib/api.ts for the inventory/resolution
endpoint (coordinate the route name in requests/inv-gui.md; Lead wires the router). Keep it a pro SecOps console,
minimal decoration; i18n zh-TW/en parity. hc send t31.
