# CyberRange 進度

> 給產品負責人：醒來只需看這份的「現在能做什麼」與各模組狀態，細節在各 docs。

## 現在能做什麼

一份情資 → 分析 → 規劃 → 生成 IaC → 本機部署 3 容器 → 無害驗證 → 三層報告，全程跑通。詳見 `docs/overnight-report.md`。

## 架構（已定）

- 後端 Python + FastAPI + SQLite（`apps/api`）。前端 React + TS + Vite（`apps/web`）。
- 共用契約在 `packages/contracts/schemas`，中央結構是 Scenario IR。
- 所有 OpenAI 呼叫經 `apps/api/app/llm`（Budget Manager，硬上限 $50，估到 $45 停新任務）。
- 架構決策：`docs/decisions/0001-architecture.md`。

## 八個模組狀態

狀態分四級：✅已實作且實際驗證 / 🟡已實作未完整驗證 / 🟠部分完成 / ⬜未完成。

| # | 模組 | 狀態 | 負責 | 備註 |
|---|---|---|---|---|
| 1 | 情資報告分析 | ✅ 實作+實際驗證 | Codex be-cti | 真實 LLM 驗過 |
| 2 | 缺失項目補齊 | ✅ 實作+實際驗證 | Codex be-cti | |
| 3 | 攻擊流程編輯 | 🟡 後端驗證，GUI 未逐頁測 | sc-plan+前端 | |
| 4 | 軟體依賴分析 | ✅ 實作+實際驗證 | Codex sc-plan | |
| 5 | 拓樸分析 | ✅ 實作+實際驗證 | Codex sc-plan | |
| 6 | IaC 生成 | ✅ 實作+實際驗證 | Codex infra | |
| 7 | 部署 | ✅ 實作+實際驗證 | Codex infra | 真實 docker |
| 8 | PoC 驗證 | ✅ 實作+實際驗證 | Codex infra | 三層+忠實度 |
| — | GUI | 🟡 實作、未完整驗證 | Claude 前端 | build/proxy 過 |

## 已通過的測試

25 項 pytest 全過＋端到端示範（證據 `docs/e2e-evidence/`）。

## 已知問題

見 `docs/overnight-report.md`「尚未完成/已知問題」。

## 下一個待處理

見 `docs/overnight-report.md` 末「需要你決定的產品問題」。

## API 預算使用

- 由 `GET /api/budget` 即時查詢。硬上限 $50。
