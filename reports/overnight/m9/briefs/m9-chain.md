# m9-chain (cr-codex)
Read reports/overnight/m9/PLAN.md and reports/overnight/m9/CONTRACT.md first (authoritative). Follow AGENTS.md. Stay strictly inside your owned file set. Do NOT edit modules 1-8 files, main.py, or other workers' dirs; if you need a change there, write reports/overnight/m9/requests/<you>.md and hc send t31. Do NOT start other agents. Commit small on your branch. When done or blocked: hc send t31 with a one-line status + your report path under reports/overnight/m9/.

Deliver: apps/api/app/poc/chain/ — (a) evidence verification helpers that turn runner stages+evidence into a
defensible per-action status; (b) attack-chain DAG validation over relations[] (kind=dependency) producing
ChainValidation: verify state transfer (cred/session/network/token/artifact) from predecessor evidence to
successor preconditions, verify order, objective_reached; support partial/blocked/skip/re-validate; never invent a
dependency without causal evidence; predecessor FAIL => dependents not PASS. (c) FidelityReport aggregation into
the existing validation-report.schema levels {env_build, behavior_repro, full_chain} + fidelity buckets, keeping
all 5 metrics separate (never one success rate). full_chain PASS only if all three levels PASS and chain passes.
Unit tests incl. a broken-chain case (predecessor FAIL) and a missing-transfer case. hc send t31.
