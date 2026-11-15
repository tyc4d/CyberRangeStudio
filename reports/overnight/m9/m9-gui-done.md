# m9-gui — done

Branch `agent/m9-gui`, commit e031d9e. tsc `--noEmit` clean; i18n key parity clean (node scripts/i18n-check.mjs).

## Delivered (owned files only)
- **apps/web/src/pages/PocPage.tsx** (new) — the five §8 panels:
  1. **PoC Discovery** — build ValidationPlan (strategy per action, not_executable reason shown as itself) + ranked PocManifest candidates (compatibility %, source link + commit, product/version, exec method, trust).
  2. **Validation Execution** — review (tick runnable `poc_exec` actions) · run · **stop** · re-run; per-action **six-stage timeline** (started→…→action_complete) + ownership-verified flag + confidence/exit + logs_path + evidence (kind/redacted/sha). Confirm dialog before real payloads.
  3. **Attack Chain Validation** — flow view of actions in order with per-action PocPill status + evidence count, plus a transfers table (from→to, carried cred/session/…, verified).
  4. **Fidelity Report** — **five SEPARATE metrics** (deployment readiness · per-vuln · end-to-end chain · scenario fidelity · unverified/unsupported), each `n / total`, never a single combined %. An info note states they are kept separate on purpose.
  5. **Environment Export** — format picker (full / IaC / evidence) · build · download; manifest view (rebuildable, no-secrets, missing_for_rebuild, file list with sha256, bundle_path).
- **apps/web/src/lib/api.ts** — ONE additive `api.poc` group: plan/discover/execute(+AbortSignal)/chain/report/export + exportDownload. All six frozen routes.
- **apps/web/src/App.tsx** — ONE STAGES entry `{path:"/poc", key:"poc", label:"stage.poc"}` after `/report`, + import.

## Had to also touch (flagging for integration)
- **apps/web/src/i18n/{zh-TW,en}.ts** — added the `poc.*` + `stage.poc` keys (both locales, in parity). The i18n table is strictly typed (`MsgKey = keyof zhTW`), so the App.tsx label and every PocPage string require keys here; there was no way to stay purely in the 3 listed files. No other m9 worker touches `apps/web`, so no conflict. All added keys are referenced (i18n-check reports 0 of mine unused).

## Honest degradations (no invented backend routes) — details in requests/m9-gui.md
1. No frozen live-poll/cancel route → synchronous run with elapsed Busy; **Stop = client-side abort** ("stop waiting"); stage timeline from the returned ExecutionResult[] is the status/logs view.
2. `/export` returns a server `bundle_path`, no download route → Download tries `GET …/export/download`, shows a clean notice if absent.
3. Export `format` sent additively (CONTRACT has no field; backend may ignore).
4. `/report` FidelityReport shape not in `types.ts` → 5 metrics derived from ValidationPlan + ExecutionResult[] + ChainValidation; prefers `report.fidelity` for scenario metric when present.

Not verified against a live backend (only `plan` is implemented so far; others are 501 and surface as clean "unimplemented" notices). Ready for integration + m9-review.
