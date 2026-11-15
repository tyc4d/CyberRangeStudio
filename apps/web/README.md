# apps/web — CyberRange Studio GUI

React + TypeScript + Vite。`npm install && npm run dev`（5173，`/api` 代理到 127.0.0.1:8077）。
`npm run typecheck` 檢查型別。`npm run e2e` 用 Playwright 開瀏覽器跑完整流程（需後端與 Docker；說明與最近一次結果見 `e2e/RESULTS.md`）。

## 前端假設的後端端點

所有路徑集中在 `src/lib/api.ts`。骨架裡只定了前三項，其餘是前端開工時的**假設**；
後端若用不同路徑或格式，只需改 `api.ts`（或告知前端）。端點不存在（404/405/501）或後端沒開時，
頁面會顯示「尚未提供／無法連線」提示，不會崩潰，也不會顯示假資料。

| 用途 | 方法與路徑 | 請求 | 前端期待的回應 |
|---|---|---|---|
| Scenario 清單 | `GET /api/scenario/list` | — | `[{id,name,created_at,updated_at}]` |
| 取得 IR | `GET /api/scenario/{id}` | — | Scenario IR（可直接回，或包在 `scenario` / `ir` 裡） |
| 情資分析 | `POST /api/ingest/analyze` | `{input_kind: text\|markdown\|stix2.1, content, method: single_pass\|staged\|staged_review, name}` | Scenario IR（同上），或至少 `{scenario_id}` |
| 存新版本（模組 3） | `PUT /api/scenario/{id}` | `{ir, note}` | 更新後的 IR（`ir_version` 遞增） |
| 版本清單 | `GET /api/scenario/{id}/versions` | — | `[{ir_version,note,ts}]` |
| 補充缺失（模組 2） | `POST /api/ingest/{id}/supplement` | `{text, targets_missing_item?, status?}` | 更新後的 IR |
| 依賴分析（模組 4） | `POST /api/planning/{id}/dependencies` | — | 更新後的 IR |
| 元件 catalogue | `GET /api/planning/catalogue` | — | 陣列，或 `{components:[...]}` |
| 拓樸規劃（模組 5） | `POST /api/planning/{id}/topology` | — | 更新後的 IR（含 `environment_plan`） |
| IaC 讀取／生成（模組 6） | `GET /api/iac/{id}`、`POST /api/iac/{id}/generate` | — | `{compose: "<yaml 文字>", report: {...}}`（compose 也接受 `compose_yaml`/`docker_compose`/`files`） |
| 部署（模組 7） | `POST /api/deploy/{id}/up`、`/down`；`GET /api/deploy/{id}/status`、`/health` | — | 任意 JSON；有 `state`/`status`、`containers`/`services` 陣列會特別排版 |
| 驗證（模組 8） | `POST /api/validate/{id}/run`、`GET /api/validate/{id}/report` | — | `validation-report` 契約 |

「更新後的 IR」若沒回，前端會自動重抓 `GET /api/scenario/{id}`。

與後端實作對齊的細節：`POST /api/deploy/{id}/up` 會帶 `{test_approved: true}`（後端的明確核准閘門），
前端只在使用者於確認視窗按下確定後才送出。補充缺失時同時送 `targets_missing_item` 與 `missing_item_id`。

## 開發

- Node 在 `~/.nvm/versions/node/v22.23.3/bin`（非互動 shell 需自行加入 PATH）。
- 後端不在 8077 時：`CR_API_URL=http://127.0.0.1:<port> npm run dev`。
- 5173 被占用時 Vite 會自動改用下一個埠（看啟動訊息）。

## 結構

- `src/lib/api.ts` 端點與錯誤分類（尚未提供／無法連線／失敗）；`scenario.tsx` 目前情境狀態；`hooks.ts` 載入與動作狀態；`layout.ts` 圖形排版。
- `src/components/ui.tsx` 共用元件（epistemic badge、提示、進度、未知格式 JSON 的 `DataView`）。
- `src/pages/*` 10 個頁面。節點位置只存在瀏覽器 localStorage，不寫入 IR。

## 自測紀錄（2026-11-14）

`npm run typecheck`、`npm run build` 通過。以 headless Chromium 對 sc-plan 分支的後端（scenario / planning 為真實端點）
加上契約合法的測試情境實跑：首頁清單與開啟、分析結果與證據對照、攻擊流程編輯並存成 v2、依賴與拓樸、
驗證報告（讀 IR 內的 validation）皆正常，無 console 錯誤。IaC／部署／驗證端點在該後端不存在時顯示「尚未提供」；
這三頁有資料時的畫面，是在測試程式內以符合 infra 分支回傳格式的攔截回應驗證的（未連真實 Docker）。
未實測：真實 LLM 分析（避免花預算）、補充缺失的成功路徑、真實 up/down。

## 介面語言（i18n）

- 預設繁體中文（zh-TW），頂列右側可切換英文；選擇記在瀏覽器（`cr.locale`）。
- 所有固定介面文字都在 `src/i18n/zh-TW.ts`（鍵的來源）與 `src/i18n/en.ts`；`en.ts` 型別為 `Messages`，少一個鍵 `tsc` 就會失敗。英文需要單複數時用 `{ one, other }`。
- 使用者情資、引文、名稱與 API 資料原樣顯示，不翻譯。後端固定錯誤訊息在 `src/lib/errors.ts` 對應到語系鍵；其他錯誤顯示簡短通用訊息，原始內容收在「技術細節」。
- `npm run i18n:check`：找出 `src/` 中寫死的中文（`src/i18n/`、註解、標 `i18n-ignore` 的行與 `lib/errors.ts` 除外），並比對兩個語系的鍵與 `{變數}`。
- 文案原則：參考 ASD-STE100 的結構規則（短句、主動語態、一句一個動作、不用分號、同一概念用同一個詞）。中文是比照這些原則的改寫，不是正式的 STE 標準；也未使用官方字典。

## 手機版面

`theme.css` 末段的 `@media (max-width: 760px)` 與 `(max-width: 400px)`：單欄、內文 15px、輸入框 16px、按鈕至少 44px 高。手機上多欄表格由 `src/lib/stackTables.ts` 依表頭加上 `data-label`，以卡片方式逐列顯示。
