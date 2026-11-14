# frontend-eng 過夜報告（持續更新）

分支 `agent/frontend-eng`。自己的站台：API 127.0.0.1:8131、Vite 127.0.0.1:5181、`CR_DATA_DIR=<worktree>/.data`。未動共用 QA 站台。

## 批次 1（commit 09fd549）

| QA 編號 | 問題 | 修法 | 驗證 |
|---|---|---|---|
| EI-04／admin M1 | 缺失頁「接受未知」備註標選填，留白送出回 422 | 留白時前端送出明確文字「接受未知（使用者未填寫備註）」（後端要求 text 至少 1 字，且會把它存成 resolution）；表單下方加一行說明哪種模式必填／選填 | e2e 通過；截圖 `evidence/frontend-eng/01-accept-unknown-blank-note.png` |
| EI-04 附帶 | 422 以原始 `string_too_short / body.text` 顯示 | `ApiNotice` 把 FastAPI 欄位驗證錯誤轉成白話（「內容」不能留白），並說明資料未儲存 | 只有 typecheck；**沒有 e2e 覆蓋**（介面已無會送空白的路徑） |
| EI-11／admin M2 | 拓樸核准後、IaC 未生成時「啟動」可按，按了才失敗並留下 failed 紀錄 | 部署頁讀取 IaC 狀態：未生成或報告判定不可部署時停用「啟動」，顯示原因與「前往 IaC 預覽」 | e2e 通過；截圖 `02-deploy-blocked-no-iac.png` |

改動檔：`apps/web/src/pages/MissingPage.tsx`、`DeployPage.tsx`、`components/ui.tsx`；新增 `apps/web/e2e/qa-fixes.spec.ts`、`e2e/seed-scenario.py`、`e2e/fixtures/seed-scenario.json`。

測試指令（在 `apps/web`）：

```sh
CR_E2E_API_PORT=8131 CR_E2E_WEB_PORT=5181 CR_DATA_DIR=<worktree>/.data CR_VENV=/home/tyc4d/cr-project/.venv \
CR_ENV_FILE=/home/tyc4d/cr-project/.env CR_BUDGET_HARD_CAP_USD=5 CR_BUDGET_STOP_NEW_USD=4 npx playwright test qa-fixes
```

實際輸出：`3 passed (3.5s)`；`npx tsc --noEmit` 通過。完整 `npm run e2e`（含真實 LLM 的 full-flow）**尚未跑**。

測試方式說明：`qa-fixes` 不呼叫 LLM。情境由 `seed-scenario.py` 透過後端 `store.create` 寫入，內容是一份真實分析結果的第 1 版（CL0P MOVEit，缺失項全為待補）。只略過分析步驟，其餘都打真實 API，沒有 mock。

## 給 Lead／後端的事項

- 「接受未知」的 text 契約：目前由前端代填固定備註。若後端改成 `accepted_unknown` 可不帶 text，前端可移除代填（`UNKNOWN_DEFAULT_NOTE`）。
- 關係來源被洗成使用者（EI-01）：Lead 告知根因在後端且已修，前端未改。
