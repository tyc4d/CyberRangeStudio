# CyberRange 進度

> 給產品負責人：醒來只需看這份的「現在能做什麼」與各模組狀態，細節在各 docs。

## 現在能做什麼

（建置中，T0 = 2026-11-14 04:55 CST）

## 架構（已定）

- 後端 Python + FastAPI + SQLite（`apps/api`）。前端 React + TS + Vite（`apps/web`）。
- 共用契約在 `packages/contracts/schemas`，中央結構是 Scenario IR。
- 所有 OpenAI 呼叫經 `apps/api/app/llm`（Budget Manager，硬上限 $50，估到 $45 停新任務）。
- 架構決策：`docs/decisions/0001-architecture.md`。

## 八個模組狀態

狀態分四級：✅已實作且實際驗證 / 🟡已實作未完整驗證 / 🟠部分完成 / ⬜未完成。

| # | 模組 | 狀態 | 負責 | 備註 |
|---|---|---|---|---|
| 1 | 情資報告分析 | ⬜ | Codex backend | 契約已定，待實作 |
| 2 | 缺失項目補齊 | ⬜ | Codex backend | |
| 3 | 攻擊流程編輯 | ⬜ | Codex scenario + 前端 | |
| 4 | 軟體依賴分析 | ⬜ | Codex scenario | |
| 5 | 拓樸分析 | ⬜ | Codex scenario | |
| 6 | IaC 生成 | ⬜ | Codex infra | Docker Compose |
| 7 | 部署 | ⬜ | Codex infra | 本機隔離 |
| 8 | PoC 驗證 | ⬜ | Codex infra | 只做無害檢查 |
| — | GUI | ⬜ | Claude 前端 | 10 個頁面 |

## 已通過的測試

（待補）

## 已知問題

（待補）

## 下一個待處理

- 啟動 5 個 Worker 平行開發核心骨架之上的各模組。

## API 預算使用

- 由 `GET /api/budget` 即時查詢。硬上限 $50。
