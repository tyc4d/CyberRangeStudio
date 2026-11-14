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

## 批次 2（commit 見 git log「explain blocked states…」）

| QA 編號 | 問題 | 修法 | 驗證 |
|---|---|---|---|
| EI-09 | 導覽列缺失數比缺失頁多 1 | 導覽改用與頁面相同的「卡片」計數（相同問題合併） | e2e 通過。注意：測試用情境沒有可合併的重複問題，只驗證兩數相等，未實際重現「多 1」 |
| admin M3 | 已選情境時「＋ 新建情境」只開啟現有匯入內容 | 首頁按鈕明確要求空白表單 | e2e 通過 |
| EI-06／ux M | 依賴頁初次進入看不出尚未分析 | 未分析時顯示「尚未執行依賴分析」警告，按鈕為主要按鈕「執行依賴分析」 | e2e 通過 |
| Lead 轉達／ux High／admin | 行為與主機參照不一致→服務被排除、零連線、IaC 拒絕 | 依賴／拓樸／IaC 頁顯示「主機參照不一致」說明：哪些行為指向未指明主機、哪些服務沒有主機、能在哪裡改；拓樸零連線另有警告；規劃備註中文化（保留英文原文） | e2e 通過；截圖 03、04 |
| EI-10 | IaC 錯誤是多層英文原始欄位 | 生成被拒時顯示白話原因清單＋每台主機對應表，原始報告收合 | e2e 通過；截圖 05 |
| EI-10／admin M5 | 部署紀錄失敗原因只有「—」 | 由紀錄的 reason／error／stderr／結束代碼取原因 | **未以真實失敗紀錄驗證**（只有 typecheck）|
| EI-11 | 無資源時 down 可按、未部署時驗證可按 | 沒有 IaC 也沒有容器時停用 down；部署狀態非 running 時停用「執行驗證」並引導到部署頁 | e2e 通過；截圖 06 |

`npx playwright test qa-fixes` 實際輸出：`6 passed (10.9s)`；`npm run build` 成功。

### 重要：這一項前端只能說明，不能解決（需後端）

用測試情境（CL0P MOVEit 第 1 版）在自己的 API 實測：

1. 執行依賴分析後，主機由 1 台（`host-target`）變 3 台（多出 `unknown`、`host_target`），服務 `svc1` 仍不屬於任何主機。
2. 把 4 個行為的目標主機全部改成 `host-target` 並儲存，再重新分析：結果相同，`svc1` 仍未歸屬；拓樸 0 連線。

也就是說，**目前沒有任何畫面操作能把服務歸到主機**，使用者照著改也到不了可部署。前端提示已如實寫出這個限制，沒有寫成「照做就會好」。

## 給 Lead／後端的事項

- 「接受未知」的 text 契約：目前由前端代填固定備註。若後端改成 `accepted_unknown` 可不帶 text，前端可移除代填（`UNKNOWN_DEFAULT_NOTE`）。
- 關係來源被洗成使用者（EI-01）：Lead 告知根因在後端且已修，前端未改。
- 依賴分析會產生重複主機（`host-target`／`host_target`／`unknown`），且不會把服務歸到主機；修正行為的目標主機後重新分析也無效（重現步驟見批次 2）。需要 scenario-eng／planner 處理，或提供「指定服務所在主機」的 API，前端才能做對應操作。
- 流程儲存新版本後，舊拓樸仍顯示「已核准」、啟動可用（admin 里程碑 5）。前端無法判斷規劃是否過期：`environment_plan` 沒有記錄它是由哪個 `ir_version` 產生的。若後端在規劃上加這個欄位，前端可顯示「規劃已過期，請重新規劃」。**此項未修。**
- EI-05（補件沒有套用到主機規格）、EI-02（主機角色被合併）、EI-07／EI-08（關係無依據、引句逐字標示）屬分析／後端資料問題，前端未遮掩、未處理。

## 尚未完成

- 完整 `npm run e2e`（full-flow，真實 LLM＋Docker）執行中／待補結果。
- 422 白話訊息、部署紀錄原因兩項沒有 e2e 覆蓋。
