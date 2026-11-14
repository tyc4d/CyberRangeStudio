# 過夜執行狀態（Lead 維護）

最後更新：2026-11-15（Phase 0 完成，Phase 1 進行中）

## Phase 0 基準
- main = `d99957e` 起，工作樹乾淨。後端 `pytest` 39 passed（2026-11-15 實跑）。
- 共用 QA 站台（main 程式）：前端 http://127.0.0.1:5177 （Herdr `qa-web`），API http://127.0.0.1:8077 （Herdr `qa-api`）。
- OpenAI 預算：已用約 $0.15／上限 $50（`GET /api/budget`）。
- KVM/libvirt：可用（需 `sg kvm`／`sg libvirt`）。Windows Server 2022 Eval ISO 已完整下載並核對大小（5,044,094,976 bytes）。
- Codex Ultra：預設模型 gpt-6-luna 不支援 ultra，測試者改用 gpt-6.1-sol＋effort=ultra＋停用 fast/ultrafast＋daybreak=false（範本 `cr-codex-ultra`）。已在三個測試者畫面上確認 "GPT-6.1-Sol ultra"。

## 整合進度（main）——全部經獨立 reviewer APPROVE 後由 Lead 併入
- cti-research（研究資料）、infra-eng@5059c10／713aa43／e761d07（edge 隔離、動態配埠、失敗清理、catalogue、宿主機隔離、cr-gateway、Windows VM 後端與真實驗證）、scenario-eng@c9a63dd／8a55f73／592e1c7（模組1–5、version_basis、替代標示）、frontend-eng@4625120／0aa4bfa／d434fb8（GUI 修復、e2e 穩定）、poc-eng@b51a7f5／df0f802（驗證器假 PASS 修復、Phase 3 真實 PoC）。
- 退回紀錄：poc-eng 2 次、scenario-eng 1 次、infra-eng 1 次（G1 跨網段跳板）——皆修正後複審通過。reviewer 報告共 17 節：`.worktrees/reviewer/reports/overnight/worker-reports/reviewer.md`。
- 待審／待併：infra-eng@67ffe92（VM 擁有權真實測試、最終整理）、poc-eng 驗證報告 substitute_for 顯示。
- main 回歸：後端 177 passed（43ba325 實跑）；前端 e2e 18 passed（reviewer 實跑，含真實部署／驗證／清理）。
- Phase 3 真實 PoC（reviewer 獨立重跑確認）：Struts S2-045 真實重現、Log4Shell(Solr) 真實 JNDI→LDAP 回呼；Horizon／Windows／AD 專屬步驟 BLOCKED。見 `E2E-RESULTS.md`。
- Windows VM：Server 2022 Eval 真實無人值守安裝、隔離網路、guest agent 原生健康檢查、銷毀無殘留；尚未接入環境計畫部署流程（BLOCKED，見 INFRA-VALIDATION §7）。

## QA
- Round 1（修復前）：講師 43／管理者 54／UX 53。
- Round 2：進行中。凍結版本 tag `qa-round2`（43ba325），站台由 `.worktrees/qa-site` 提供（:5177／:8077）。測試者 qa-instructor-r2(t3m)、qa-admin-r2(t3n)、qa-ux-r2(t3p)，皆 Codex gpt-6.1-sol ultra。

## Agent 名冊
| 名稱 | 角色 | 工具 | Herdr | Worktree / 分支 | 狀態 |
|---|---|---|---|---|---|
| cti-research | A CTI Researcher | Claude Code (auto) | t34 | .worktrees/cti-research / agent/cti-research | 執行中 |
| scenario-eng | B 模組1–5 | Claude Code (auto) | t35 | .worktrees/scenario-eng / agent/scenario-eng | 執行中 |
| infra-eng | C 模組6–7 | Claude Code (auto) | t36 | .worktrees/infra-eng / agent/infra-eng | 執行中 |
| poc-eng | D 模組8 | Claude Code (auto) | t37 | .worktrees/poc-eng / agent/poc-eng | 執行中 |
| qa-instructor | E 講師測試 | Codex gpt-6.1-sol ultra | t3c | .worktrees/qa-instructor | Round 1 完成，待 Round 2 |
| qa-admin | F 管理者測試 | Codex gpt-6.1-sol ultra | t3d | .worktrees/qa-admin | Round 1 完成，待 Round 2 |
| qa-ux | G UX/QA | Codex gpt-6.1-sol ultra | t3f | .worktrees/qa-ux | Round 1 完成，待 Round 2 |
| reviewer | H Integration Reviewer | Claude Code (auto) | t3h | .worktrees/reviewer | 審查中 |
| frontend-eng | 前端修復 | Claude Code (auto) | t3g | .worktrees/frontend-eng / agent/frontend-eng | 執行中 |

恢復方式：`hc ls` 看存活終端；`hc read <名稱>` 看畫面；任務書在 `reports/overnight/briefs/`；各 Worker 報告在其 worktree 的 `reports/overnight/worker-reports/`。
