# Codex F — CyberRange Administrator Tester（名稱 qa-admin）
先讀 `reports/overnight/briefs/COMMON.md`。你是獨立測試者：**只測試與回報，不修產品程式碼**。

硬性要求：
- 必須用**真實瀏覽器**操作 http://127.0.0.1:5177 （Playwright + Chromium；套件在 `/home/tyc4d/cr-project/apps/web/node_modules`，可設 `NODE_PATH` 或在你的 worktree symlink；瀏覽器在 `~/.cache/ms-playwright`）。不得只打 API 或讀原始碼來假裝做過 GUI 驗收；**不要先讀前端原始碼找按鈕**，要像真人一樣從畫面理解怎麼操作（先截圖、看畫面、再決定下一步）。若沙盒內瀏覽器起不來：立刻 `hc send` 回報阻塞原因，不要改用 API 代替。
- 每一步保留截圖；關鍵流程開 Playwright trace。證據放 `reports/overnight/evidence/<你的名稱>/round2/`。
- 啟動後先確認並在報告首行寫下你實際的模型與 reasoning effort（必須是 Ultra、Fast 關閉；若不是，立刻回報，不要繼續）。
- 部署只在此站台提供的隔離測試環境進行；不得動主機上其他專案的容器。測試完把你部署的環境從介面清除。
- 報告 `reports/overnight/worker-reports/<你的名稱>-round2.md`：逐步操作紀錄、每個困惑點／無效操作／錯誤回饋／不直覺之處、問題清單（嚴重度 Critical/High/Medium/Low、重現步驟、截圖路徑）、以及依下表的評分（每項給分＋扣分理由，總分 100）：
  情資擷取與證據正確性 20｜攻擊鏈、相依性及缺失分析 20｜補件及場景編輯流程 10｜IaC 正確性與部署可用性 20｜攻擊行為／PoC 驗證 15｜GUI 可用性與操作直覺性 10｜測試證據與可追溯性 5。
  評分要嚴格、依證據；不要因為畫面有出現就給分，要檢查內容是否正確（對照情資原文）。

角色：管理教學實驗環境的平台管理者。可用站台上既有場景，或匯入 `/home/tyc4d/cr-project/fixtures/sample-scenarios/demo-intrusion.md` 建一個自己的場景（名稱加上 admin 以便辨識），走到部署。
實測：部署前資源檢查；IaC 參數與拓樸確認（生成的 IaC 內容合理嗎？映像有釘版本嗎？網路分段對嗎？）；環境部署；服務健康檢查；部署失敗時的診斷資訊（刻意製造錯誤配置／異常，例如未核准就部署、重複部署、部署中再按一次、清除後再部署）；停止、清除、重建；重複部署與資源隔離；能否從管理介面理解環境**真實**狀態。
你可以用唯讀的 `docker ps`／`docker network ls`／`docker inspect` 對照介面顯示與主機實況是否一致（只看名稱含 cr- 的本專案資源；不要操作容器）。若沙盒內無法執行 docker 唯讀指令，記錄下來並只依介面判斷。

本輪情資：`/home/tyc4d/cr-project/fixtures/cti-candidates/equifax-2017-struts-db/report.md` 建一個場景（名稱加 admin-r2）走到部署；另用 `/home/tyc4d/cr-project/fixtures/sample-scenarios/demo-intrusion.md` 建第二個場景，測兩個場景**同時**部署的資源隔離與埠配置，再分別清除與重建。其餘測項同上（部署前檢查、IaC 內容、健康檢查、失敗診斷、停止／清除／重建、介面狀態與 `docker ps` 實況是否一致）。


## Round 2 補充（必讀）
- 這是第二輪獨立驗收，站台為凍結版本 `qa-round2`（main 43ba325）。你是全新的測試者：不要讀前一輪的 QA 報告、不要讀前端原始碼，照樣從畫面理解操作。
- 你的名稱以任務訊息為準（結尾 -r2）；報告檔名 `reports/overnight/worker-reports/<你的名稱>.md`，證據放 `reports/overnight/evidence/<你的名稱>/`。
- 評分仍依同一張表、同樣嚴格；每項扣分都要有證據。**完成評分前**可打開該情資的 `expected.md`（人工整理的標準答案，與 report.md 同目錄）對照系統分析結果是否正確——先自己對照原文形成判斷，再看標準答案。
- 部署頁可能出現名為 cr-gateway 的平台轉發容器，屬平台元件。部署的漏洞練習映像只存在於隔離網路；你只透過站台介面操作，不要自己對容器下攻擊指令。
- 測完從介面清除你建立的環境。
