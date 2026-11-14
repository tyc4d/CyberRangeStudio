# Worker Brief — Claude Frontend

你負責 GUI 修復與 **Playwright 真實瀏覽器端到端測試**。只改：

- `apps/web/**`（含新增 `apps/web/e2e/` Playwright 測試、`apps/web/playwright.config.ts`、package.json 的 devDependencies/scripts）

**不要改**：`apps/api`、`packages/contracts`、任何後端檔。你是 Claude worker，可在自己的分支 commit（絕不碰 main）。

## 任務（Task 3）

### A. 補上「拓樸核准」UI
後端新增了人工核准閘。部署前必須核准拓樸，否則 `POST /api/deploy/{id}/up` 回 409。
新端點：`POST /api/planning/{id}/topology/approve`，body `{"approved":true,"approved_by":"user","note":"..."}`，回傳更新後的 environment_plan（含 `approval`）。
請在拓樸頁（或部署頁前）顯示：規劃出的連線（connections）與「必須保持阻擋」的路徑（`environment_plan.verify_blocked`），並提供「核准並繼續」按鈕呼叫該端點。核准前，部署頁的「部署」動作要停用或提示需先核准。

### B. Playwright 全流程瀏覽器測試（核心交付）
用 Playwright 實際開瀏覽器，走完整流程至少成功一次：
上傳情資 → 分析 → 補充缺失 → 編輯流程（確認依賴關係）→ 產生環境（依賴+拓樸）→ 預覽 IaC → **核准拓樸** → 部署 → 驗證 → 查看報告 → 清理。
- 不能只測 API，也不能只確認前端可編譯。要真的點 UI。
- 需要後端在跑：測試前啟動後端（8077，需 `.env` 的 OPENAI_API_KEY）與前端 dev server（5174），或用 webServer 設定自動拉起。Docker 需可用（部署步驟）。
- 留下：失敗紀錄、關鍵步驟截圖（存 `apps/web/e2e/artifacts/` 或 `docs/e2e-evidence/gui/`）、**可重跑的測試腳本**與指令（`npm run e2e` 類）。
- 若某步驟環境不具備（如 Docker 不在），要讓測試**誠實標記 skip/fail**，不可假裝通過。

### C. 修 GUI 讓流程真的能走
逐頁實際操作，修掉擋住流程的 bug（錯誤處理、空狀態、stage 進度、呼叫參數）。typecheck/build 要過。

## 環境備忘
- Node：`export PATH=$HOME/.nvm/versions/node/v22.23.3/bin:$PATH`；`npm install`；`npm run dev` → 5174（5173 常被占用會 fallback）。
- 後端起法見 `README.md` / `docs/overnight-report.md`。8000/8080 被其他專案占用，用 8077。
- Vite proxy 指向 8077。

## 規則
- 讀 `AGENTS.md`。只在你的 worktree 工作，只 commit 到自己的分支。
- Playwright 只連本機 localhost；不得連外部目標。
- 完成或卡住時回報：詳細結果寫成檔案，只傳路徑（含截圖位置與重跑指令）。
