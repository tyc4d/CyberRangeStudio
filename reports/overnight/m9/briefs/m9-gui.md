# m9-gui (cr-claude)
Read reports/overnight/m9/PLAN.md and reports/overnight/m9/CONTRACT.md first (authoritative). Follow AGENTS.md. Stay strictly inside your owned file set. Do NOT edit modules 1-8 files, main.py, or other workers' dirs; if you need a change there, write reports/overnight/m9/requests/<you>.md and hc send t31. Do NOT start other agents. Commit small on your branch. When done or blocked: hc send t31 with a one-line status + your report path under reports/overnight/m9/.

Deliver: apps/web/src/pages/PocPage.tsx (new) with the 5 panels from the prompt §8: PoC Discovery, Validation
Execution (review/run/stop/re-run + live status/logs poll), Attack Chain Validation view (reuse the flow/graph
viz + per-action status/evidence), Fidelity Report (5 SEPARATE metrics: deployment readiness, per-vuln, end-to-end
chain, scenario fidelity, unverified/unsupported — never one combined %), Environment Export (format picker +
download). Add ONE method group to apps/web/src/lib/api.ts for /api/poc/*, and ONE STAGES entry in
apps/web/src/App.tsx after /report ({path:"/poc", key:"poc", label per existing zh-TW/en i18n}). Reuse
components/ui.tsx + VersionBasis.tsx + lib/scenario.tsx + lib/stages.ts; match the just-finished mobile RWD styling
(responsive, i18n). Keep it a pro SecOps console, minimal decoration. These 3 files (PocPage new, api.ts, App.tsx)
are the only shared ones — App.tsx/api.ts edits must be additive single insertions. hc send t31.
