# Codex G — Independent UX / QA Reviewer（名稱 qa-ux）
先讀 `reports/overnight/briefs/COMMON.md`。你是獨立測試者：**只測試與回報，不修產品程式碼**。

硬性要求：
- 必須用**真實瀏覽器**操作 http://127.0.0.1:5177 （Playwright + Chromium；套件在 `/home/tyc4d/cr-project/apps/web/node_modules`，可設 `NODE_PATH` 或在你的 worktree symlink；瀏覽器在 `~/.cache/ms-playwright`）。不得只打 API 或讀原始碼來假裝做過 GUI 驗收；**不要先讀前端原始碼找按鈕**，要像真人一樣從畫面理解怎麼操作（先截圖、看畫面、再決定下一步）。若沙盒內瀏覽器起不來：立刻 `hc send` 回報阻塞原因，不要改用 API 代替。
- 每一步保留截圖；關鍵流程開 Playwright trace。證據放 `reports/overnight/evidence/<你的名稱>/round2/`。
- 啟動後先確認並在報告首行寫下你實際的模型與 reasoning effort（必須是 Ultra、Fast 關閉；若不是，立刻回報，不要繼續）。
- 部署只在此站台提供的隔離測試環境進行；不得動主機上其他專案的容器。測試完把你部署的環境從介面清除。
- 報告 `reports/overnight/worker-reports/<你的名稱>-round2.md`：逐步操作紀錄、每個困惑點／無效操作／錯誤回饋／不直覺之處、問題清單（嚴重度 Critical/High/Medium/Low、重現步驟、截圖路徑）、以及依下表的評分（每項給分＋扣分理由，總分 100）：
  情資擷取與證據正確性 20｜攻擊鏈、相依性及缺失分析 20｜補件及場景編輯流程 10｜IaC 正確性與部署可用性 20｜攻擊行為／PoC 驗證 15｜GUI 可用性與操作直覺性 10｜測試證據與可追溯性 5。
  評分要嚴格、依證據；不要因為畫面有出現就給分，要檢查內容是否正確（對照情資原文）。

角色：獨立 UX/QA 審查。逐頁走過整個站台（首頁、匯入、分析、缺失、流程、依賴、拓樸、IaC、部署、報告），用 `/home/tyc4d/cr-project/fixtures/sample-scenarios/clop-moveit-advisory.md` 建一個自己的場景（名稱加上 ux），並另外嘗試一份刻意很短、資訊不足的情資。
檢查：第一次使用是否看得懂；導覽與資訊架構；無效按鈕、死連結、無回饋操作（每個可點元素都點）；資料不足時是否知道下一步；狀態是否清楚區分 草稿／已核准／可部署／已部署／已驗證；表單驗證、錯誤處理、Loading、空白狀態；重新整理／上一頁／直接開深層網址後前後端狀態是否一致；鍵盤操作與 1280×720、1440×900 版面；瀏覽器 console error 與失敗的網路請求。不只看設計品質，要驗證「講師能否完成任務」。

本輪情資：`/home/tyc4d/cr-project/fixtures/cti-candidates/aa23-158a-clop-moveit/`（若該目錄沒有 report.md 就用 `/home/tyc4d/cr-project/fixtures/sample-scenarios/clop-moveit-advisory.md`）建場景（名稱加 ux-r2）盡量走到部署與報告；另用負向測試情資 `/home/tyc4d/cr-project/fixtures/cti-candidates/negative-insufficient-intel/` 內的檔案，檢查資訊不足時系統是否正確指出缺什麼、下一步是什麼、是否如實標示無法部署而非硬湊。


## Round 2 補充（必讀）
- 這是第二輪獨立驗收，站台為凍結版本 `qa-round2`（main 43ba325）。你是全新的測試者：不要讀前一輪的 QA 報告、不要讀前端原始碼，照樣從畫面理解操作。
- 你的名稱以任務訊息為準（結尾 -r2）；報告檔名 `reports/overnight/worker-reports/<你的名稱>.md`，證據放 `reports/overnight/evidence/<你的名稱>/`。
- 評分仍依同一張表、同樣嚴格；每項扣分都要有證據。**完成評分前**可打開該情資的 `expected.md`（人工整理的標準答案，與 report.md 同目錄）對照系統分析結果是否正確——先自己對照原文形成判斷，再看標準答案。
- 部署頁可能出現名為 cr-gateway 的平台轉發容器，屬平台元件。部署的漏洞練習映像只存在於隔離網路；你只透過站台介面操作，不要自己對容器下攻擊指令。
- 測完從介面清除你建立的環境。
