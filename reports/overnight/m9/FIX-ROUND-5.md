# Module 9 — Fix Round 5 (after round-5 QA CHANGES REQUESTED)

Round-5 QA confirmed all 32 prior findings hold (review1 57/1, review2 89/0, review3 34/0, review4 59/0;
frontend 4/6/9/10). 2 new issues. Acceptance = `reports/overnight/m9/review5/test_m9_review5.py` (7 failing) +
`review5/check_web_review5.cjs` (4 failing); keep all prior review files + full suite green. Run backend with
`PYTHONPATH=<worktree>/packages/contracts`.

## m9-export (cr-claude) — R5-01 / P1 — apps/api/app/poc/export/**
Secrets leak when the value is MULTI-LINE: YAML literal block `password: |` + next line, YAML folded
`password: >` + next line, plain `password:` + value on next line, multi-line double-quoted value, and shell
`\`-newline continuation. Root cause: `_value_end` stops at the newline; `>` is treated as an empty value;
`|` gets replaced but the real secret stays on the following line; `_embedded_structure` only parses full JSON.
**The convergent fix is to stop bounding value spans with regex and instead verify STRUCTURALLY:**
- In the FINAL scan and `verify_bundle`, PARSE the emitted bundle files (scenario.json as JSON, scenario.yaml
  as YAML — the files you actually write) into data structures and walk them: any secret-named key (the deep
  traversal you already have) whose parsed value is a non-empty/real string is a leak — this normalises
  multi-line block scalars, folded values, quoting and line continuations automatically.
- For secret structures embedded INSIDE a free-text description string, parse embedded YAML as well as JSON
  (reuse `yaml.safe_load` on candidate substrings), then redact the whole parsed value.
- Redaction must cover the ENTIRE multi-line value (whole block scalar / all continuation lines), not just the
  first line. When a multi-line secret structure cannot be proven fully removed, REFUSE the export.
Scope note from the reviewer: this is NOT about structureless prose secrets (it does not flag an arbitrary
base64 token with no key); it is secret-NAMED keys with standard multi-line value structure. Make
`test_multiline_secret_builder_redacts_entire_value_or_refuses` (5) +
`test_multiline_secret_checker_detects_even_with_correct_hash` (2) pass; keep ALL prior export tests green.

## m9-gui (cr-claude) — R5-02 / P2 — apps/web/src/pages/PocPage.tsx (+ i18n)
One shared generation counter is bumped by execute AND by the chain/report snapshot reads, so reading a snapshot
(e.g. pressing "verify chain" while an execute POST is still in flight) invalidates the in-flight execute: its
completed FAIL/BLOCKED `results` and the follow-up report refresh are discarded, leaving old PASS badges /
`results=null`. Root: conflating the execute-batch/IR generation with per-query response ordering.
- Separate the identities: a snapshot read (chain/report) must NOT invalidate an in-flight execute's completion;
  guard each query against ITS OWN later supersession, not a globally shared counter the other buttons bump.
- Gate the "verify chain"/report buttons on `execAct.busy` too (don't let a snapshot read run mid-execute), or
  otherwise prevent the incompatible concurrent operation.
- The current execute's results (incl. a BLOCKED with its reason) must always be stored and shown; never leave
  `results=null` after an execute completes.
- Acceptance: `review5/check_web_review5.cjs` 7/7, tsc clean, prior web scripts green.

Report hc send t31 when done. Lead integrates, re-runs all five review files + full suite, then reviewer round 6.
#5 deploy-layer guaranteed-cancel handle remains the one honest deferred item.
