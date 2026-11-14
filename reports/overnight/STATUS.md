# 過夜執行狀態（Lead 維護）

最後更新：2026-11-15（Phase 0 完成，Phase 1 進行中）

## Phase 0 基準
- main = `d99957e` 起，工作樹乾淨。後端 `pytest` 39 passed（2026-11-15 實跑）。
- 共用 QA 站台（main 程式）：前端 http://127.0.0.1:5177 （Herdr `qa-web`），API http://127.0.0.1:8077 （Herdr `qa-api`）。
- OpenAI 預算：已用約 $0.15／上限 $50（`GET /api/budget`）。
- KVM/libvirt：可用（需 `sg kvm`／`sg libvirt`）。Windows Server 2022 Eval ISO 已完整下載並核對大小（5,044,094,976 bytes）。
- Codex Ultra：預設模型 gpt-6-luna 不支援 ultra，測試者改用 gpt-6.1-sol＋effort=ultra＋停用 fast/ultrafast＋daybreak=false（範本 `cr-codex-ultra`）。已在三個測試者畫面上確認 "GPT-6.1-Sol ultra"。

## 整合進度（main）
| 分支@commit | 審查 | 併入 main |
|---|---|---|
| agent/cti-research | 研究資料（無程式碼） | ✔ bee0b0c |
| agent/infra-eng@5059c10（edge 隔離、動態配埠、失敗清理、catalogue） | APPROVE | ✔ |
| agent/scenario-eng@c9a63dd（模組1–5 修復） | APPROVE | ✔ 0d31c04 |
| agent/frontend-eng@4625120（QA Round1 GUI 修復） | APPROVE | ✔ 990d40b |
| agent/poc-eng@b51a7f5（驗證器假 PASS 修復） | APPROVE（兩次退回後） | ✔ 22d1740 |
| agent/infra-eng@227a74c（宿主機隔離） | REQUEST_CHANGES：G1 cr-gateway 可被當跨網段跳板 | ✗ 修正中 |
| agent/scenario-eng@8a55f73（N1/N2 version_basis） | 審查中 | ✗ |
| agent/frontend-eng 4625120 之後 | 待審 | ✗ |
| agent/infra-eng@3e3f0a9（Windows VM 後端；已真實安裝並開到登入畫面，guest agent 待 virtio-win 完整檔） | 待審 | ✗ |

main 回歸：後端 134 passed（2026-11-15，併入 poc-eng 後實跑）。前端 e2e：frontend-eng 分支上 16 passed（含真實部署／驗證／清理），曾有 1 次偶發整頁空白，原因追查中。

QA Round 1 基準：講師 43／管理者 54／UX 53（見 QA-SCORES.md）。Round 2 待上述分支整合後啟動。

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
