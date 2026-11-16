# UI 導覽與部署核准狀態修復

## 變更
- `apps/web/src/App.tsx`：每次路由變更後查找目前 `aria-current="page"` 的步驟連結；若超出水平導覽視區，只捲動導覽容器讓 active 項目可見。
- `apps/web/src/pages/DeployPage.tsx`：Deploy 詳細資料中的 `approval.message` 依後端固定 `code` 翻譯系統狀態，涵蓋 `no_plan`、`not_approved`、`approval_metadata_invalid`、`scenario_changed`、`topology_changed`、`approved`。舊版核准依 `code === "approved"` 且 `versioned === false` 辨識。未知 code/message 保持原文。
- `apps/web/src/i18n/zh-TW.ts`、`apps/web/src/i18n/en.ts`：新增相同的十一個 approval locale keys。

## 驗證
- 已閱讀根目錄 `AGENTS.md` 與 `docs/approved-scope.md`。工作樹起始於 `a033c53`，未執行 commit。
- TypeScript：`node node_modules/typescript/bin/tsc --noEmit` 通過。
- i18n：`node scripts/i18n-check.mjs` 通過，0 hard-coded strings；工具提示 3 個既有的可能未使用 keys。
- Playwright 既有唯讀 PoC 測試：360、390、430px 均通過；使用 scenario `scn_6125b061b4af`，API 非 GET 請求會被阻擋。
- 手機 390px 直接開 `/poc` 與站內由 `/` 點選 `/poc` 均通過：active 導覽連結完整位於導覽視區，`documentElement.scrollWidth` 為 390px，沒有 API 寫入請求。
- Playwright 首次執行更新了 `apps/web/e2e/artifacts/results.json`。檢查 diff 確認內容是該次執行的路徑與結果；已精確還原至 HEAD。後續測試輸出指定到 `/tmp`。
- `git diff --check` 通過。未呼叫 LLM、未碰 ImportPage、PVE、Docker、deploy 或 validate 執行路徑；未修改 QA 報告。

## 限制
- 舊版核准沒有獨立 `code`，目前以 `code === "approved"` 且 `versioned === false` 判斷。`versioned` 缺漏或其他值會走一般 approved 翻譯或保留原始訊息。未知訊息維持原樣。
- Lead 指出 5199 已有 frozen candidate 佔用；最終導覽檢查改用空閒的 5298，並以 `/proc/<pid>/cwd` 確認 Vite cwd 為此 worktree 的 `apps/web`。直接載入和 SPA 導覽均通過；輸出只在終端，Playwright artifact 目錄在 `/tmp`。5298 測試伺服器已停止。

## Lead review follow-up
- 移除以中文 Unicode code points 建立的舊版訊息前綴比對。現在只在 `approval.code === "approved"` 且 `approval.versioned === false` 時使用舊版核准 locale；`versioned` 缺漏或非布林 false 時，走一般 approved 翻譯或保留原始 message。
- 重跑 `npm run typecheck`、`npm run i18n:check`：均通過，i18n 為 0 hard-coded strings（仍提示 3 個既有可能未使用 keys）。
- 純函式聚焦檢查通過：舊版分支依 `versioned=false`，mapping 不檢查 message 文本；沒有 API 呼叫或寫入。

## Deployment stale-approval safety review
- Deploy 同時檢查 status 與 preflight 回傳的 `approval`。任一有效狀態為 `deployable === false` 就停用 Up；`no_plan`／`not_approved` 使用既有拓樸引導，其他拒絕顯示 stale 提示與拓樸連結。讀取失敗或缺少 approval state 不會當成後端拒絕。若已顯示 409 stale 專屬錯誤，隱藏重複提示。
- `ApiError.data.code === "approval_stale"` 有獨立的雙語錯誤訊息「拓樸核准已失效，這次部署未開始。」／“The topology approval is no longer valid. Deployment did not start.” 與返回拓樸的下一步，不會被映射成 `topology_changed`。預防性標題為「拓樸核准已失效。請檢查拓樸，再核准一次。」／“The topology approval is no longer valid. Review the topology. Approve it again.”；內文分別提示前往拓樸頁、檢查目前內容、重新產生拓樸並核准。
- 步驟導覽在路由或語言切換後重新定位，並監聽視窗 resize 與導覽尺寸變化。
- `npm run typecheck`、`npm run i18n:check` 通過；i18n 0 hard-coded strings，仍提示 3 個原有可能未使用 keys。
- 聚焦靜態 gate 檢查確認任一 approval refusal 都會禁用 Up、no plan/未核准分流、stale 拒絕提示與獨立 409 文案、locale/resize 監聽及不檢查中文訊息文字；未呼叫 API 或寫入資料。
- Race review：status/preflight 兩份讀取中任一明確回報 `deployable=false` 就採該 refusal；只有 409 `approval_stale` 顯示「部署未開始」，預防性提示只引導重新檢查與核准。
- 重跑 typecheck、i18n check 與聚焦靜態檢查均通過；未呼叫 API。
- 文案校訂：approval 操作文案已拆成短句與獨立步驟，例如先建立新拓樸規劃、再核准；繁中也採短句呈現。預防性提示使用一般使用者易懂的「檢查拓樸」說法。`npm run i18n:check` 通過，0 hard-coded strings；未呼叫 API。

## Recovery after a stale 409
- `approval_stale` keeps Up disabled unless status or preflight completes a successful refresh with `approval.deployable === true`. The same recovery boolean hides the stale 409 notice. The post-up status/preflight refreshes are non-silent so retained old data cannot count as a fresh approval while the GET is pending; failed refreshes keep their error and do not unlock Up.
- Pure cases, run separately: stale 409 + failed GET stayed blocked (`true`); stale 409 + fresh successful deployable=true response unblocked (`false`). Both passed.
- `npm run typecheck` and `npm run i18n:check` passed; i18n reported 0 hard-coded strings and the same 3 possibly unused keys.
- The first pure-check harness attempts failed because the ad hoc runner did not strip a TypeScript cast and then omitted a helper argument. The runner was corrected; the separately rerun intended cases both passed. No API calls were made.
- Final consistency review：`stale409Recovered` 另要求目前 status/preflight 沒有任何 `deployable === false` refusal，故單一成功讀取不能遮蔽另一讀取的拒絕，也不會隱藏 stale 409 提示。
- 重跑 typecheck、i18n check 通過。三個純案例分別通過：失敗 GET 保持阻擋；成功且明確 deployable=true 可恢復；status 有效但 preflight 明確拒絕時仍阻擋並保留錯誤提示。未呼叫 API。
