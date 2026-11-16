# ImportPage 修復紀錄（Round 3）

## 變更

- 檔案載入提示保存翻譯鍵與參數，PDF 額外提示也依目前 locale 即時渲染。
- 未送出的名稱、格式、分析方式、文字、PDF upload token 與載入提示保存在模組記憶體，不寫入 localStorage/sessionStorage。SPA 導覽卸載頁面時不清除草稿；返回 ImportPage 可還原。Home 以 `fresh: true` 導入時，在草稿 state initializer 前清除舊草稿與 PDF token，因此「新增情境」從空白開始。非預設格式/方法、檔案提示、PDF 狀態或 upload token 也會視為 dirty。分析成功後清除草稿；表單回到預設且無內容後不保留空白草稿。瀏覽器關閉或重新整理仍由 `beforeunload` 提示，原生提示文字由瀏覽器決定。
- 僅當 502 detail 同時包含 `AuthenticationError`、401、API key 與 expired 訊號時，顯示繁中/英文管理員憑證更新指引；單獨的 HTTP 401 維持一般錯誤行為。過期分支的折疊管理員診斷只顯示 request method/path/status 與本地化、已分類的認證錯誤，不顯示任意 detail 或 key。
- 字元數以 number 保存，顯示時依 locale 格式化。

## 聚焦檢查

- `git diff --check`：通過。
- 最終修改後，使用指定 Node 路徑並臨時加入 PATH 執行 `npm run typecheck` 與 `npm run i18n:check` 均通過；i18n 回報 1400 keys、36 source files、0 hard-coded strings，另提示 3 個既有可能未使用 keys。
- 真實瀏覽器 SPA smoke：PASS。ImportPage 輸入名稱與文字、前往 Gaps、瀏覽器上一頁後兩欄均保留；之後回 Home 點「新增情境」，名稱/文字清空且格式與方法回預設。該次所有 `/api` 請求在瀏覽器端 abort，無 POST、analyze POST=0，無 browser errors。
- 直接 extract endpoint：PASS。使用 live candidate API `127.0.0.1:8077` 對本機一頁 PDF fixture 呼叫真實 `/api/ingest/extract`：回傳 `input_kind=text`、`chars=29`，抽出內容包含 fixture 文字。這是 endpoint 驗證，不代表 UI locale 驗證；不涉及分析或 LLM。
- 真實瀏覽器 PDF UI locale check：PASS。以 PDF fixture 走 Vite proxy 至 live `127.0.0.1:8077`，中文「已從 round3.pdf 取出文字」出現後點擊實際 accessible name「切換為英文」，同一提示以 “Text extracted from round3.pdf” 顯示。Network 記錄含 GET `/api/budget` 3 次及 POST `/api/ingest/extract` 1 次；POST `/api/ingest/analyze`=0。這次使用真實 extract endpoint，沒有 fake response。
- Vite 清理：Lead 已核實並停止本任務 5192/5193/5194 三組程序，確認其 worktree cwd/cmdline 後清理，listener 已消失。本次額外啟動的 Vite 使用 5195；對應 exec session 已送 Ctrl-C，但 `ss` 仍看到 127.0.0.1:5195 LISTEN，sandbox 的 `fuser` 無 PID 回報，無法由本執行環境核實或終止 listener。未使用程序名廣泛 kill；未觸及 5199 或其他程序。

## 限制

草稿僅存在目前頁面工作階段的 JavaScript 記憶體。可跨 SPA 頁面卸載與返回保留；分頁關閉、重新整理、瀏覽器崩潰或直接跨文件導覽不承諾保存。認證分類使用受限的 502 狀態碼與錯誤訊息特徵比對；未呼叫認證 API、未重試 API，也未送出 analyze。

## Review follow-up: expired credential action and copy

- Removed the inline Retry action from the exact expired-credential error branch. The normal Start analysis action remains available after the administrator updates the credential and the user returns.
- Updated the bilingual primary instruction to state that the analysis service credential has expired and to ask the user to contact an administrator, then retry after the update. The collapsed diagnostic uses “上游回報服務憑證已過期（401）。” / “The upstream reports the service credential expired (401).”
- Final `npm run typecheck` and `npm run i18n:check` passed after these copy/action changes. i18n reports 1400 keys, 36 source files, 0 hard-coded strings; it still lists the same 3 possibly unused inventory scope keys.
- No API calls were made for this follow-up.

## Lead cleanup follow-up

After the report above was written, Lead verified PID 3027901 as the Node Vite process for this worktree (`apps/web`, port 5195; PGID 3027878), stopped that exact process group, and confirmed the 5195 listener is gone. This is a later cleanup update; the earlier limitation records the state observed at its original check time.

## English UI copy follow-up

- Split the expired-credential instruction into short sentences in both locales: notify an administrator to update the credential, then retry after the update.
- Shortened the collapsed English diagnostic to “Upstream reports an expired service credential (401).”
- `npm run typecheck` and `npm run i18n:check` passed after the copy edit (1400 keys, 36 source files, 0 hard-coded strings). No API calls were made.
