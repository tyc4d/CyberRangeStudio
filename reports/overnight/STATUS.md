# 過夜執行狀態（Lead 維護）

最後更新：2026-11-15（Phase 0 完成，Phase 1 進行中）

## Phase 0 基準
- main = `d99957e` 起，工作樹乾淨。後端 `pytest` 39 passed（2026-11-15 實跑）。
- 共用 QA 站台（main 程式）：前端 http://127.0.0.1:5177 （Herdr `qa-web`），API http://127.0.0.1:8077 （Herdr `qa-api`）。
- OpenAI 預算：已用約 $0.15／上限 $50（`GET /api/budget`）。
- KVM/libvirt：可用（需 `sg kvm`／`sg libvirt`）。Windows Server 2022 Eval ISO 已完整下載並核對大小（5,044,094,976 bytes）。
- Codex Ultra：預設模型 gpt-6-luna 不支援 ultra，測試者改用 gpt-6.1-sol＋effort=ultra＋停用 fast/ultrafast＋daybreak=false（範本 `cr-codex-ultra`）。已在三個測試者畫面上確認 "GPT-6.1-Sol ultra"。

## Agent 名冊
| 名稱 | 角色 | 工具 | Herdr | Worktree / 分支 | 狀態 |
|---|---|---|---|---|---|
| cti-research | A CTI Researcher | Claude Code (auto) | t34 | .worktrees/cti-research / agent/cti-research | 執行中 |
| scenario-eng | B 模組1–5 | Claude Code (auto) | t35 | .worktrees/scenario-eng / agent/scenario-eng | 執行中 |
| infra-eng | C 模組6–7 | Claude Code (auto) | t36 | .worktrees/infra-eng / agent/infra-eng | 執行中 |
| poc-eng | D 模組8 | Claude Code (auto) | t37 | .worktrees/poc-eng / agent/poc-eng | 執行中 |
| qa-instructor | E 講師測試 | Codex gpt-6.1-sol ultra | t3c | .worktrees/qa-instructor | Round 1 執行中 |
| qa-admin | F 管理者測試 | Codex gpt-6.1-sol ultra | t3d | .worktrees/qa-admin | Round 1 執行中 |
| qa-ux | G UX/QA | Codex gpt-6.1-sol ultra | t3f | .worktrees/qa-ux | Round 1 執行中 |
| （待啟動） | H Integration Reviewer | Claude Code | — | — | 等第一批成果 |
| （待啟動） | 前端修復 Worker | Claude Code | — | — | 等 QA Round 1 問題清單 |

恢復方式：`hc ls` 看存活終端；`hc read <名稱>` 看畫面；任務書在 `reports/overnight/briefs/`；各 Worker 報告在其 worktree 的 `reports/overnight/worker-reports/`。
