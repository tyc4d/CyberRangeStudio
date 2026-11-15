模型：gpt-6.1-sol；reasoning effort：Ultra；Fast／Ultrafast：關閉（runtime.json 的啟動參數及本次 session turn_context 已核對）。

# qa-admin-r2 — Round 2 獨立管理者驗收

**總分 54 / 100；整體 PARTIAL。** 真實 Chromium 完成匯入、人工核准、IaC、雙場景同時部署、健康檢查、異常操作、逐一清除及重建。管理生命週期可運作；完整 Equifax 攻擊鏈仍未重現，來源分級與多場景操作有待修問題。問題共 **4 High、5 Medium、1 Low；未發現已證實的 Critical**。

**清場完成：** 兩個啟動過的環境皆由 GUI 執行 down；Docker 複查本次四個場景均為 **0 容器、0 網路**。未操作其他專案資源、未掃外網、未自行對容器下攻擊指令。

## 範圍、方法與限制

- 測試時間：2026-11-15 約 07:15–07:34，Asia/Taipei。
- 站台：http://127.0.0.1:5177。任務指定 qa-round2／main 43ba325；GUI 沒有顯示 build ID，因此未獨立證明伺服器 commit。
- 已讀根目錄 AGENTS.md、COMMON.md、F-admin-r2.md；以 Round 2 補充為準。未讀前輪 QA 報告、未讀前端原始碼、未啟動其他 Agent。
- 所有產品操作均經 Playwright＋真實 Chromium GUI；沒有直接呼叫產品 API、沒有修改產品程式碼或部署設定檔。
- Docker 只使用 ps、network ls、inspect、network inspect，且限定 cr-* 本專案資源；本輪詳細 inspect 只針對自己場景。
- 先讀原文並寫下 [獨立判讀](../evidence/qa-admin-r2/source-assessment-before-expected.md)，之後才讀 expected.md 對照。標準答案中的外部補充未冒充 GAO 原文，也未作為真實部署成功的證據。
- 171 個編號截圖／同名 GUI 文字快照，另 1 張補件區域截圖；兩份 Playwright trace。逐步紀錄見 [step-index.md](../evidence/qa-admin-r2/step-index.md)，完整操作、輸入內容、時間及 native confirm 訊息見 [browser-events.jsonl](../evidence/qa-admin-r2/browser-events.jsonl)。
- Headless 的 native confirm 不會畫入網頁 screenshot，因此另以 dialog 事件記錄文字和接受／取消。首次 up 被 Playwright 預設取消；已另測明確取消及接受，沒有把這次無動作列為產品缺陷。

## 場景與最後狀態

|名稱|ID|用途／實際結果|最後狀態|
|---|---|---|---|
|Equifax 2017 admin-r2|scn_f083b7380452|分階段＋複核；原流程依賴／補件／IaC 失敗診斷|未生成 IaC、從未啟動|
|Demo isolation admin-r2|scn_db358a6d2c07|原 demo；3 主機＋1 gateway，成功啟動、重複 up、down、重建、最後清除|0 容器／0 網路|
|Equifax single lifecycle admin-r2|scn_f67c74550815|單次分析；自由補充來源混淆、無歸屬服務及可部署判定矛盾|已生成 IaC、從未啟動|
|Equifax deploy-only substitutes admin-r2|scn_615acc1be9b1|只填指定缺失以續測管理生命週期；3 容器，與 Demo 同時啟動、逐一清除重建|0 容器／0 網路|

最後一個 Equifax 場景把誤抽的加密通道項目指定以 struts2 替代、另一協定項以 postgres 替代，以避開同主機只能選一映像的限制；入口選 DMZ、DB 選內網。這是**明示的管理生命週期測試替代**，不代表 TLS、原始資料庫、憑證或外傳已被重現。額外場景是為在阻塞後繼續驗收，並非以其成功抹去第一場景的失敗。

## 驗收結果

|測項|結果|實際觀察與證據|
|---|---|---|
|真實瀏覽器、匯入兩份指定文件|PASS|Equifax report.md 12,879 字元；demo 1,163 字元；003、009|
|情資分析與原文核對|PARTIAL|分階段＋複核：8 行為／6 關係、31 引文（29 逐字、2 片段）；單次：9 行為／8 關係、19 引文（14 逐字、5 片段）；011、081|
|缺失補充、版本儲存|PARTIAL|可接受未知、選替代、存版本；指定網路可寫回；部分軟體／版本回答僅留文字；重新分析後原缺失 ID 消失且出現新缺失；045、047、070–075|
|未核准即部署|PASS（GUI 閘門）|未核准時 up disabled，未繞過按鈕、未偽造 API 拒絕；013、unapproved-buttons.json|
|修改已部署場景的拓樸|PASS|重新規劃後 up disabled，但 down 仍可用，最後確實可清除；161、162、167、168|
|IaC 內容與可部署檢查|PARTIAL|可用版本有 digest、資源上限、內網與安全設定；首場景同主機多元件產生埠不相容而拒絕；051、061、133|
|部署前資源檢查|PARTIAL|GUI 可看 Compose 的 mem_limit／cpus／pids_limit；未找到部署前可見的宿主可用 RAM／CPU／磁碟及容量判定。確認框只問是否啟動；062–065、133–135|
|真實部署與服務健康|PASS（環境層）|Demo 4 容器、Equifax 3 容器；服務 healthy，attacker 未設健康探測但如實標示；076、142、docker-concurrent-initial.json|
|部署中再按 up|PASS（同分頁）|up／down disabled；正常 click 等待後 timeout，未強制點擊；065、066、demo-repeat-during-up.txt|
|執行中重複 up|PARTIAL|執行完成，但重建 DB 與 gateway、改埠，非維持原容器；077、082、141|
|錯誤配置診斷|PASS（IaC 拒絕）|具體顯示 `host h1 declares port 80, unsupported by vuln-struts2-s2-045`，沒有產生 compose、沒有啟動；051|
|真實 runtime 故障注入|NOT_TESTED|GUI 未提供直接改 Compose／殺服務的操作；未越界用 Docker 操作容器製造故障。不能以 IaC 拒絕冒稱測過 runtime 失敗|
|兩場景同時部署及埠配置|PASS（資源層）|7 容器同時 running；網路 ID 無交集；Demo 只有 localhost gateway 公開埠，Equifax 漏洞服務不公開；142、145、docker-concurrent-initial.json|
|跨場景主動 TCP 隔離|NOT_TESTED|GUI 驗證只探測本場景的允許／拒絕路徑，沒有跨場景測項；未自行進容器探測，因此只有結構隔離證據|
|逐一清除、重建及另一場景持續運作|PASS|Demo 清除後 Equifax ID 不變；反向亦同。重建各自產生新 ID；12 項生命週期證據檢查全部通過|
|停止但保留環境|NOT_TESTED|GUI 只有 up／down；down 會移除容器及網路，不能算已驗證 stop-only|
|介面狀態對照主機|PARTIAL|容器表、健康表及埠大致吻合；清除後頂部仍可能說執行中，重複 up 時新舊埠短暫並存；082、150、151、163、169|
|攻擊行為／PoC|PARTIAL|兩情境皆 0 個完全重現；未證明 RCE、取得憑證、查詢資料或外傳。136、147|
|最後清場|PASS|GUI down 完成後，四個本輪場景均無容器／網路；168–171、docker-final-cleanup.json|

## 逐步操作與困惑紀錄

完整的每一步及其時間、截圖、當時可見文字在 [逐步索引](../evidence/qa-admin-r2/step-index.md)。以下串起主要操作及當下判斷；截圖前綴都是 evidence/qa-admin-r2/ 內的實際檔名。

1. **001–011：建立與核對。** 從首頁按新建，Equifax 選 Markdown、分階段＋複核；等待時開第二分頁匯入 demo。Equifax 約一分多鐘完成。分析有暫定結果提示，主張和引文核對分開顯示，方向清楚。
2. **012–019：核准與依賴。** 先看缺失，再直接進部署檢查未核准閘門。流程圖確認既有依賴、存 v2，再執行依賴分析。困惑：原文的通訊方式被列成軟體，元件目錄沒有對應；DB 主機反而沒有真正的資料庫軟體。畫布上「主機」文字點擊沒有開出服務編輯器（067–068），不能藉此修改映像。
3. **020–051：補件與拒絕路徑。** 遵照畫面指示填 nginx／postgres 替代，OS／版本接受未知，兩主機先選隔離網段。畫面如實告知 attacker 無路徑；這是本次選擇造成，沒有算成系統誤判。所有缺失曾到 0，重分析又新增 2。拓樸提示一台主機只能選一映像；核准後 IaC 因 Struts 映像不支援 80 埠而拒絕。無效操作及結果均留證。
4. **052–076：Demo 部署。** Demo 四個行為對得上原文；系統用 nginx／postgres 作為明示替代，規劃 attacker→Web:80、Web→DB:5432，阻擋 attacker→DB。檢查 Compose 後開始部署；native confirm 取消不啟動，接受才啟動。部署中再點 up 被 disabled 擋住。成功後核對 Docker。
5. **070–075、077–104：修改限制與來源問題。** 回第一 Equifax 的全部缺失頁改替代軟體，該項已變為 fidelity 文字紀錄，重分析仍是 nginx。Demo 重複 up；兩個容器被 recreate、埠由 42931 改 42153。再建立單次 Equifax，指定 struts2／postgres；用自由補充說明這些是替代、OS 原始版本未知，重分析卻新增無主機 postgres，並把 2.3.30 列「原文版本」。
6. **105–144：完成雙場景測試。** Demo 執行驗證；再建只填指定缺失的 Equifax 管理場景，避免自由補充副作用。檢查並核准拓樸、生成 IaC，成功啟動，與 Demo 同時存在。標準答案在獨立原文判讀之後才閱讀。沒有依標準答案人工補造行為來提高分數。
7. **138–139：確認 orphan 的實際判定。** 按生成後仍產生 compose、標可部署；同頁警告卻說不會顯示可部署。**這不是 runtime 阻擋**；未啟動該 orphan 場景。早期里程碑將它稱阻塞只是依警告的暫時判斷，最終以本次實測更正。
8. **145–155：Demo 清除與多分頁。** 清除 Demo，Docker 證明其資源全移除、Equifax ID 不變。介面下方已 not_created，頂部卻仍執行中。再檢查未消失；browser reload 卻切成另一分頁選過的 Equifax。察覺後先回首頁、選回 Demo，沒有誤刪環境。重新選取才清掉舊徽章。
9. **156–165：逐一重建。** Demo 重新啟動改配 42169；Equifax 清除後 Demo 的四個 ID 不變。Equifax 再次重建成功，三個 ID 全更新。另測 Demo 已部署後重規劃，核准被撤銷、up 停用但 down 保持可用。
10. **166–171：清場。** 核對每個分頁上的場景名稱與 ID 後，兩場景各由 GUI down。最終 Docker 四個自己場景全部無資源；另外兩個場景的 GUI 也確認從未部署。關閉 Chromium 並保存兩份 trace。

## 問題清單（含重現步驟）

### AR2-01 — High：使用者的替代說明被標成原文版本

- 重現：以 Equifax 原文單次分析 → 執行依賴分析 → 指定 struts2／postgres 替代 → 自由補充填：
  `admin-r2 管理生命週期測試：struts2 2.3.30 與 postgres 是本機隔離教學替代元件；不能重現加密通道／TLS 過期憑證、實際 PII、48 個 DB 或完整外傳；OS 與原始版本仍未知。`
  → 重新分析依賴 → 生成拓樸、核准、生成 IaC。
- 實際：Struts 2.3.30 顯示「原文版本」，新增 postgres 服務的依據顯示原文、來源使用者；IaC 的「原文寫的版本」也是 2.3.30。原 GAO 根本沒有此版本，且補充明示為替代。
- 影響：SOURCE_SUPPORTED 與 USER_SUPPLIED／ASSUMED 混用；補充文字不能用來證明原事件版本。
- 證據：[100](../evidence/qa-admin-r2/100-equifax-single-limits-save.png)、[102](../evidence/qa-admin-r2/102-equifax-single-deps-after-input-analyzed.png)、[139](../evidence/qa-admin-r2/139-equifax-orphan-iac-attempt.png)；同名 .txt 可搜尋完整欄位。

### AR2-02 — High：把加密通道／協定當軟體，正常補件路徑無法生成 IaC

- 重現：Equifax 原文 → 任一已測分析模式 → 執行依賴分析；兩個協定名都被當成缺軟體。按 UI 指引以 nginx 及 postgres 替代 → 重新分析 → 規劃、核准 → 生成。
- 實際：h1 同時有 Struts:8080 與 nginx:80，卻只能選 Struts 單一映像，生成被拒絕。重新分析後原缺失已被換成 fidelity 項；修改它只留文字，不能改掉原元件。第一 Equifax 最終仍不能部署。
- 後續只以不具原通訊語意的 struts2 同映像替代完成管理生命週期，不能當此問題已解決。
- 證據：[019](../evidence/qa-admin-r2/019-equifax-analyze-dependencies.png)、[049](../evidence/qa-admin-r2/049-equifax-topology-generated.png)、[051](../evidence/qa-admin-r2/051-equifax-iac-generated.png)、[070](../evidence/qa-admin-r2/070-equifax-all-gaps.png)、[075](../evidence/qa-admin-r2/075-equifax-replacement-reanalyzed.png)。

### AR2-03 — High：多分頁重新整理會無提示切換部署目標

- 重現：同瀏覽器分頁 A 選 Demo、停在 /deploy；分頁 B 選 Equifax；回 A 按重新整理。
- 實際：A 相同 /deploy 網址改顯示 Equifax 的名稱、ID 與容器。沒有切換提醒，up/down 的 native confirm 也不含場景名稱。
- 影響：管理者可能把之後的啟動／清除做在另一個場景。測試中察覺並重新選回，**沒有實際清錯環境**。
- 證據：[150](../evidence/qa-admin-r2/150-demo-down-outcome.png)、[152](../evidence/qa-admin-r2/152-demo-cleared-page-reload.png)、[155](../evidence/qa-admin-r2/155-demo-reselected-deploy.png)，及 browser-events.jsonl 的 reload 與 confirm 訊息。

### AR2-04 — High：核心攻擊行為仍沒有動作專屬驗證

- 重現：部署 Demo 或 Equifax 管理替代場景 → 驗證報告 → 執行驗證。
- 實際：Demo 0 完全重現／3 部分／1 未測；Equifax 0 完全重現／6 部分／3 未測。Equifax 的 RCE 沒執行、取得憑證／擴大 DB 存取、查詢資料、外傳均無佐證；Struts 甚至顯示沒有適用的無害行為探測。
- 系統有如實把整鏈標 PARTIAL，這點保留；但「行為重現：通過」實際只根據 HTTP200／pg_isready，不能據此驗收 PoC 或教學攻擊鏈。屬可用能力不足，未冒稱系統偽造成功。
- 證據：[136](../evidence/qa-admin-r2/136-demo-validation-result.png)、[147](../evidence/qa-admin-r2/147-equifax-validation-result.png)、[149](../evidence/qa-admin-r2/149-equifax-validation-first-evidence-expanded.png)。

### AR2-05 — Medium：狀態標示與即時容器／埠資訊不同步

- 重現一：部署後按 down → 等完成、立即更新及重新檢查。
- 實際：Docker 已空、部署與健康區 not_created，頂部和導覽仍說容器執行中；重新選情境後才更新。最後 Equifax 清場後亦復現。
- 重現二：執行中再按 up；健康表已是新埠 42153，上方公開埠仍顯示 42931。
- 證據：[082](../evidence/qa-admin-r2/082-demo-duplicate-up-outcome.png)、[150](../evidence/qa-admin-r2/150-demo-down-outcome.png)、[151](../evidence/qa-admin-r2/151-demo-cleared-health-recheck.png)、[169](../evidence/qa-admin-r2/169-equifax-final-cleanup-outcome.png)、docker-final-cleanup.json。

### AR2-06 — Medium：重複 up 會重建資料庫與閘道，確認框未說明影響

- 重現：Demo running 時再次 up 並接受確認。
- 實際：h2 ID 由 8ff357f38366 變 5341794cab0e；gateway 由 3e696c201a41 變 e27b15daddfc，埠 42931 → 42153。完整輸出明列 Recreate，其他兩容器仍原 ID。
- 未測試有資料時的保存狀況，**不宣稱已證實資料遺失**；但資料層會被重建與服務端點改變應在操作前說明。
- 證據：[141](../evidence/qa-admin-r2/141-demo-deploy-history-full-output.png)、docker-demo-running.jsonl、docker-demo-after-duplicate.jsonl、browser-events.jsonl（確認文字只詢問是否啟動）。

### AR2-07 — Medium：無歸屬服務的警告與「可部署」總判定矛盾，GUI 無法修歸屬

- 重現：依 AR2-01 加自由補充 → 重新分析 → 產生拓樸、核准、生成 IaC。
- 實際：新增 postgres 沒有主機。畫面說服務會被排除、無法部署出可用連線且不會顯示可部署；同頁卻顯示可部署、生成 compose，該額外服務未在 compose。GUI 明說沒有指定歸屬的操作。
- 只驗證到生成，未啟動此場景；不能說 runtime 已拒絕或已成功部署全部服務。
- 證據：[102](../evidence/qa-admin-r2/102-equifax-single-deps-after-input-analyzed.png)、[104](../evidence/qa-admin-r2/104-equifax-single-topology-generated.png)、[139](../evidence/qa-admin-r2/139-equifax-orphan-iac-attempt.png)。

### AR2-08 — Medium：關鍵資產、促成因素與缺失項仍不足

- 重現：Equifax 原文匯入後比較分析、缺失與流程圖。
- 實際：主要行為有抓到，但初始 3 DB、憑證儲存區、額外 48 DB 合成單一 DB 主機，未建出憑證後擴大存取的可部署區別；流量檢查設備／過期憑證、無分段、查詢頻率無限制未形成可用前置條件。分階段結果的查詢步驟無前置依賴；單次結果也沒有把收集→外傳列為相依。
- 初始缺失以 OS／OS 版本／網路為主，未完整追問 GAO 未交代的 CVE、Java／應用伺服器、DB 品牌版本、明文憑證位置與格式、加密外傳細節。catalogue 有漏洞映像，不等於這些資訊已由原文證實。
- March 與 May 有保留成分開的行為，未觀察到把兩次存取硬接成相依；ATT&CK 空白不當作原文錯誤扣分，因其本屬外部對應。
- 證據：[011](../evidence/qa-admin-r2/011-equifax-analysis-current.png)、[012](../evidence/qa-admin-r2/012-equifax-gaps.png)、[015](../evidence/qa-admin-r2/015-equifax-flow.png)、[083](../evidence/qa-admin-r2/083-equifax-single-flow.png)、[088](../evidence/qa-admin-r2/088-equifax-single-missing.png)；source-assessment-before-expected.md、expected-equifax-read-after-assessment.md。

### AR2-09 — Medium：部署前無可見的主機容量檢查結果

- 重現：IaC 可部署後進部署管理、按 up。
- 實際：可看每個容器的上限，但確認框沒有顯示需多少／剩多少 CPU、RAM、磁碟、現有場景占用或容量檢查結果。
- 限定為 GUI 缺少可見資訊，**未讀後端判斷、不宣稱後端完全沒有檢查**，也未以填滿主機來測耗盡。
- 證據：[062](../evidence/qa-admin-r2/062-demo-deploy-ready.png)、[064](../evidence/qa-admin-r2/064-demo-cancel-up-confirmation.png)、[133](../evidence/qa-admin-r2/133-equifax-clean-iac-generated.png)、[134](../evidence/qa-admin-r2/134-equifax-clean-deploy-ready.png)。

### AR2-10 — Low：補件及部署狀態仍暴露內部英文欄位

- 重現：依賴分析後回缺失頁，或看未部署／已清除狀態。
- 實際：問題以「後端未提供中文問題」及 `software dependency:`、`exact software fidelity:` 顯示；not_created、starting、healthy 等直接露出。管理者需理解資料欄位才能操作，與前段中文引導落差大。
- 證據：[020](../evidence/qa-admin-r2/020-equifax-software-gaps.png)、[070](../evidence/qa-admin-r2/070-equifax-all-gaps.png)、[082](../evidence/qa-admin-r2/082-demo-duplicate-up-outcome.png)、[168](../evidence/qa-admin-r2/168-demo-final-cleanup-outcome.png)。

## 嚴格評分

|項目|得分|扣分理由（逐項有上列證據）|
|---|---:|---|
|情資擷取與證據正確性（20）|13|−4 使用者替代版本被當原文（01）；−3 關鍵資料層分組、流量檢查資產及促成因素未完整形成結果（08）。主要行為與可對回的引文給分，未因頁面有數字就算正確。|
|攻擊鏈、相依性及缺失分析（20）|9|−4 協定誤判為軟體（02）；−3 關鍵相依／前置條件不完整（08）；−2 真實重建所需的 CVE／DB／憑證／外傳缺失未完整提出（08）。|
|補件及場景編輯流程（10）|4|−2 替代項重分析後只能留文字、無法修回元件（02）；−2 自由補充產生無歸屬服務（07）；−1 沒有服務主機歸屬編輯（07）；−1 補件以原始英文字段提出（10）。|
|IaC 正確性與部署可用性（20）|14|−2 正常補件造成同主機多元件無法部署（02）；−2 GUI 無容量檢查結果（09）；−1 重複 up 未提示重建影響（06）；−1 狀態／埠更新不同步（05）。實際雙場景生命週期、digest 釘版與隔離配置依證據給分。|
|攻擊行為／PoC 驗證（15）|4|−8 無 RCE／憑證取得／查詢／外傳動作專屬證據（04）；−2 Struts 無適用無害行為探測（04）；−1 DB 只 pg_isready、未查得資料列（04）。有實際連線與分段探測且誠實 PARTIAL，給 4 分。|
|GUI 可用性與操作直覺性（10）|5|−3 多分頁 reload 切錯場景（03）；−1 清除後仍顯示執行中（05）；−1 原始狀態碼與英文欄位（10）。|
|測試證據與可追溯性（5）|5|真實 GUI 每步截圖／文字、兩份 trace、原文判讀、唯讀 Docker 分期對照、操作及清場記錄完整；未測部分明確標出。|
|**合計（100）**|**54**|**PARTIAL，不可宣稱完整 Equifax 攻擊鏈驗收通過。**|

## 來源分級核對

|分級|本輪如何判定|
|---|---|
|SOURCE_SUPPORTED|GAO 的 Struts 名稱、兩次存取、未加密憑證、3→額外48 DB、約9000查詢部分取到PII、小量加密外傳；demo 的80／5432與內網限制。|
|EXTERNAL_ENRICHMENT|catalogue 提供 CVE-2017-5638／練習映像資訊；不把它算成 GAO 已寫，也未另查外部來源證明 Equifax 的確切版本。|
|USER_SUPPLIED|本次 DMZ／內網選擇、替代答案、自由補充、接受未知決定。|
|ASSUMED·SUBSTITUTED|Struts 2.3.30、PostgreSQL 16.16、nginx、Docker/Linux、縮成一台 DB、額外 attacker scaffold，均是實驗選擇。|
|BLOCKED·UNKNOWN|GAO 未寫的真實 CVE 編號、精確 OS／Struts／DB 版本、漏洞程式、憑證格式、TLS／外傳目的地及批次細節；動作未執行的結果。|

AR2-01 是對以上邊界的實際違反。能部署教學替代元件，不等於還原原事件的產品、配置或行為。

## 測試指令、實際輸出與檔案

執行方式（皆在本 worktree）：

```sh
/home/tyc4d/.nvm/versions/node/v22.23.3/bin/node reports/overnight/evidence/qa-admin-r2/browser-harness.cjs
python3 reports/overnight/evidence/qa-admin-r2/browser-command.py
python3 reports/overnight/evidence/qa-admin-r2/capture-docker.py concurrent-initial
python3 reports/overnight/evidence/qa-admin-r2/capture-docker.py demo-cleared-equifax-running
python3 reports/overnight/evidence/qa-admin-r2/capture-docker.py concurrent-after-demo-rebuild
python3 reports/overnight/evidence/qa-admin-r2/capture-docker.py equifax-cleared-confirmed-demo-running
python3 reports/overnight/evidence/qa-admin-r2/capture-docker.py concurrent-after-both-rebuilt
python3 reports/overnight/evidence/qa-admin-r2/capture-docker.py final-cleanup
python3 reports/overnight/evidence/qa-admin-r2/verify-lifecycle.py
```

browser-command.py 的每次 stdin 為 Playwright GUI 操作；完整內容在 browser-events.jsonl。capture-docker.py 只呼叫上述 Docker 唯讀指令。另有一次名為 `equifax-cleared-demo-running` 的中途快照，當時 down 尚在處理，**不可用它判定已清除**；以後續 `equifax-cleared-confirmed-demo-running` 為準。

實際生命週期檢查輸出：`"passed": 12, "failed": 0`，exit 0。詳見 [lifecycle-check-output.txt](../evidence/qa-admin-r2/lifecycle-check-output.txt)／[JSON](../evidence/qa-admin-r2/lifecycle-check-results.json)。這 12 項只驗證資源生命週期，不代表 PoC 或跨場景主動 TCP 檢查通過。

最終 Docker 輸出摘要：

```json
{"scn_db358a6d2c07":{"containers":[],"networks":[]},"scn_615acc1be9b1":{"containers":[],"networks":[]},"scn_f083b7380452":{"containers":[],"networks":[]},"scn_f67c74550815":{"containers":[],"networks":[]}}
```

- Trace：[匯入／規劃／首次部署](../evidence/qa-admin-r2/trace-01-import-planning-first-deploy.zip)、[驗證／隔離／生命週期](../evidence/qa-admin-r2/trace-02-validation-isolation-lifecycle.zip)。
- 生成的 Compose 由 GUI 可見內容保存於 equifax-clean-compose-visible.yml；Demo 原始 DOM 文字在 demo-iac-visible.txt，較易閱讀的完整內容另見 061 同名 .txt。未改實際部署檔案。
- 瀏覽器已關閉，兩份 trace 已保存；測試 harness 的 launcher 最後回報 exit 143，GUI client 的關閉回應為 browserClosed=true。這不是產品測試失敗，保留實際程序結果而不改稱 exit 0。
- 未執行 pytest／前端 build：本輪只做指定 GUI 驗收，沒有產品程式修改。未呼叫單元測試中的真實 LLM。

**只新增／變更：** `reports/overnight/worker-reports/qa-admin-r2.md` 與 `reports/overnight/evidence/qa-admin-r2/**`。含 QA harness、Docker 讀取／證據核對腳本、截圖、trace、來源副本、索引與里程碑報告歷史；沒有產品程式碼。**未 git add、未 commit，交由 Lead 檢查。**

## 尚未解決與需決定事項

- AR2-01–10 均未修復；獨立 QA 不修改產品。
- 未測：真實攻擊動作／RCE、跨場景主動連線、資料保存、資源耗盡、runtime 故障注入、stop-only；不能把未測項算 PASS。
- 沒有新的產品範圍決定需求。以上為既有模組的正確性、管理操作與驗證限制，交 Lead 排定修復；若要擴大真實攻擊驗證能力，仍依既有核准範圍由 Lead 協調。

回報狀態：已執行指定的 `hc send t31`，命令 exit 0，回應 `started:true`、`status:error`；只確認回報指令已執行，未確認 Lead 已讀。原始回應見 `evidence/qa-admin-r2/hc-final-send.json`。
