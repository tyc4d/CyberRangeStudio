# m9-runner (cr-codex) — the real-payload core
Read reports/overnight/m9/PLAN.md and reports/overnight/m9/CONTRACT.md first (authoritative). Follow AGENTS.md. Stay strictly inside your owned file set. Do NOT edit modules 1-8 files, main.py, or other workers' dirs; if you need a change there, write reports/overnight/m9/requests/<you>.md and hc send t31. Do NOT start other agents. Commit small on your branch. When done or blocked: hc send t31 with a one-line status + your report path under reports/overnight/m9/.

Deliver: apps/api/app/poc/runner/ — Adapter interface (python/bash/go/metasploit/http_seq/manual) + a Sandbox
Runner that REALLY sends payloads at the deployed isolated target and returns ExecutionResult. REUSE
deploy/manager.probe_in_service (import it; do not edit manager.py) for namespace-scoped, non-root, ephemeral,
--pull=never execution, exactly like validator/runner.py:_struts_s2045_probe / _log4shell_solr_probe. REUSE the
existing real PoC runners in tests/e2e/phase3-real-poc/ and tests/e2e/log4shell-callback/.
MANDATORY: implement poc/runner/guard.py:assert_target_owned per CONTRACT §Safety #1 and call it before EVERY
execution; BLOCKED (no execution) if ownership/isolation not verified or target is protected. PASS only on
concrete exploit evidence (CONTRACT §Evidence) — never HTTP 200/up/LLM. Real payload that does not exploit =>
FAIL. SHA-pin third-party PoCs, sandbox, timeout, cancel flag, guaranteed cleanup, redact secrets. Provide a real
e2e under tests/e2e/m9-runner/ that deploys Struts S2-045 (or Log4Shell) in isolation, runs the real payload, and
asserts PASS by the exploit effect, plus a version-mismatch case asserting NOT PASS, plus an ownership-denied case
asserting BLOCKED with no container left behind. hc send t31.
