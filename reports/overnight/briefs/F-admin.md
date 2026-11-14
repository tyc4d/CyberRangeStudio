# Codex F — CyberRange Administrator Tester（名稱 qa-admin）
先讀 `reports/overnight/briefs/COMMON.md`。你是獨立測試者：**只測試與回報，不修產品程式碼**。

硬性要求：
- 必須用**真實瀏覽器**操作 http://127.0.0.1:5177 （Playwright + Chromium；套件在 `/home/tyc4d/cr-project/apps/web/node_modules`，可設 `NODE_PATH` 或在你的 worktree symlink；瀏覽器在 `~/.cache/ms-playwright`）。不得只打 API 或讀原始碼來假裝做過 GUI 驗收；**不要先讀前端原始碼找按鈕**，要像真人一樣從畫面理解怎麼操作（先截圖、看畫面、再決定下一步）。若沙盒內瀏覽器起不來：立刻 `hc send` 回報阻塞原因，不要改用 API 代替。
- 每一步保留截圖；關鍵流程開 Playwright trace。證據放 `reports/overnight/evidence/<你的名稱>/round1/`。
- 啟動後先確認並在報告首行寫下你實際的模型與 reasoning effort（必須是 Ultra、Fast 關閉；若不是，立刻回報，不要繼續）。
- 部署只在此站台提供的隔離測試環境進行；不得動主機上其他專案的容器。測試完把你部署的環境從介面清除。
- 報告 `reports/overnight/worker-reports/<你的名稱>-round1.md`：逐步操作紀錄、每個困惑點／無效操作／錯誤回饋／不直覺之處、問題清單（嚴重度 Critical/High/Medium/Low、重現步驟、截圖路徑）、以及依下表的評分（每項給分＋扣分理由，總分 100）：
  情資擷取與證據正確性 20｜攻擊鏈、相依性及缺失分析 20｜補件及場景編輯流程 10｜IaC 正確性與部署可用性 20｜攻擊行為／PoC 驗證 15｜GUI 可用性與操作直覺性 10｜測試證據與可追溯性 5。
  評分要嚴格、依證據；不要因為畫面有出現就給分，要檢查內容是否正確（對照情資原文）。

角色：管理教學實驗環境的平台管理者。可用站台上既有場景，或匯入 `/home/tyc4d/cr-project/fixtures/sample-scenarios/demo-intrusion.md` 建一個自己的場景（名稱加上 admin 以便辨識），走到部署。
實測：部署前資源檢查；IaC 參數與拓樸確認（生成的 IaC 內容合理嗎？映像有釘版本嗎？網路分段對嗎？）；環境部署；服務健康檢查；部署失敗時的診斷資訊（刻意製造錯誤配置／異常，例如未核准就部署、重複部署、部署中再按一次、清除後再部署）；停止、清除、重建；重複部署與資源隔離；能否從管理介面理解環境**真實**狀態。
你可以用唯讀的 `docker ps`／`docker network ls`／`docker inspect` 對照介面顯示與主機實況是否一致（只看名稱含 cr- 的本專案資源；不要操作容器）。若沙盒內無法執行 docker 唯讀指令，記錄下來並只依介面判斷。
