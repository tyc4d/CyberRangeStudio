模型：gpt-6.1-sol；reasoning effort：ultra；Fast／Ultrafast：關閉。依據：evidence/qa-ux-r2/runtime.json 的實際 hc 啟動參數。

# qa-ux-r2 第二輪獨立 UX／QA 驗收

狀態：完成。總分 **62／100**。發現 **3 High、6 Medium、1 Low；本次未發現 Critical**。本報告不將容器啟動、HTTP 200 或教學替代當成原事件重現。

講師可完成「匯入 → 人工審核 → 明確選擇替代 → 隔離部署 → 查看部分驗證 → 清理」，但本次無法完成 MOVEit SQLi／LEMURLOOT 的教學攻擊行為重現。原始 MOVEit 沒有可用映像時正確阻擋；不足情資也正確阻擋部署，沒有硬湊產品或漏洞。主要問題在分析語意、來源分級與驗證摘要。

## 1. 環境、範圍與最終狀態

- 測試日期：2026-11-15，台北時間 07:16–07:40。
- 真實 Playwright + headless Chromium 操作 http://127.0.0.1:5177。只由 GUI 發起分析、補件、規劃、部署、驗證與關閉；API 回應僅由瀏覽器被動錄下作為證據，沒有以直接 API 呼叫替代驗收。
- 已先讀 AGENTS.md、briefs/COMMON.md、briefs/G-ux-r2.md，以 Round 2 補充為準。未讀前輪報告、未讀前端原始碼、未啟動其他 Agent。
- 任務指明站台 qa-round2／main 43ba325；GUI 沒有顯示 build SHA，故沒有獨立證明實際服務的 commit。本人 worktree HEAD 是 75753fe6f5ad90ff8cf66fee2c5ce34425ace0fc，分支 agent/qa-ux-r2，未以該 worktree 自行啟站。
- 實際送出兩次單次情資分析；分階段／複核模式僅切換檢視，沒有執行。最後共享預算顯示估計 $0.36／$50，這是共用累計，不能當成本人費用。
- 未修改產品程式碼，未執行 git add／commit，未重啟共享站台，未操作其他專案或其他測試者的環境。
- **清理完成**：自己的部署由 GUI down；最終 GUI 顯示 not_created、containers 空、關閉紀錄 stopped。證據 [249-final-clean-environment.png](../evidence/qa-ux-r2/249-final-clean-environment.png) 與同名 JSON。
- Chromium 與本人的瀏覽器控制程序已正常結束，exit code 0。未留下自起伺服器或容器。

| 測試情境 | ID／保留版本 | 最終結果 |
|---|---|---|
| ux-r2 CISA AA23-158A MOVEit | scn_4addf8a6ac43／v8 | 原始產品 BLOCKED；明確 nginx 教學替代部署及健康檢查成功；整鏈 PARTIAL；五個原情境動作未執行；已清理 |
| ux-r2 negative insufficient intel | scn_3394f15671b7／v1 | 無具體產品／弱點，IaC BLOCKED，部署及驗證停用；從未部署 |

## 2. 評分

評的是講師完成任務所需的實際內容與操作，不因畫面存在而給滿分。MOVEit 商業軟體不可取得且如實阻擋，本身不列為缺陷；PoC 分數反映本次沒有動作專屬驗證能力。

| 項目 | 得分／滿分 | 扣分理由與證據 |
|---|---:|---|
| 情資擷取與證據正確性 | **12／20** | 能力寫成已發生 −3、username 語意錯誤 −1（01）；使用者 nginx 誤標原文 −2（02）；未保留標頭認證及受影響版本線等關鍵內容 −2（04）。018、104、217 |
| 攻擊鏈、相依性及缺失分析 | **11／20** | 漏認證依賴 −3、沒有資料庫服務／位置分析 −2（04）；CVE 與已知產品關聯遺失 −2（05）；負向缺失清單未優先詢問弱點／工具等關鍵問題 −2（04）。067、077、099、159、164 |
| 補件及場景編輯流程 | **8／10** | 依賴產生的問題是原始英文欄位且輸入指引不足 −1（05）；重新分析後補件問題連結消失 −1（10）。099、100、248。編輯、儲存、捨棄與必要欄位驗證實際可用 |
| IaC 正確性與部署可用性 | **17／20** | 拓樸「可對外」與實際 internal 網路不一致 −2（06）；同一服務重複公開兩個轉發埠 −1（09）。106、109、114、generated-docker-compose.yml。實際替代部署、YAML 解析、清理成功 |
| 攻擊行為／PoC 驗證 | **3／15** | 五個原動作全未執行，沒有 SQLi／webshell／帳號／外洩專屬佐證 −9；HTTP 200 被摘要為行為重現通過、未執行算部分 −3（03）。119、120–131、217。保留少量分數給真實 TCP／HTTP 證據與整鏈警告 |
| GUI 可用性與操作直覺性 | **7／10** | 節點快捷按鈕被工具列遮蔽、滑鼠無法點 −2（08）；未部署在報告頁卻顯示 error −1（07）。225、227、flow-overlay-hit-test.json、094、095、172。導覽、Loading、空狀態、基本鍵盤與表單可用 |
| 測試證據與可追溯性 | **4／5** | 產品內補件歷史的問題參照失效 −1（10）。248。本人另留 249 組步驟快照、251 張截圖、三份完整 trace、初始分析、來源先行判斷與網路紀錄 |
| **總分** | **62／100** | 同一問題可能影響不同能力面向；上列逐項列明各項扣分，沒有把原產品缺映像重複扣成部署失敗 |

## 3. 問題清單與重現方式

所有截圖／JSON／trace 均位於 reports/overnight/evidence/qa-ux-r2/。同編號 JSON 保留當時完整可見文字與控制元件；圖片只呈現當時可見區域，原文與長表格另有內部捲動。

### UXR2-01 — High：引文逐字成立，主張語意仍有錯

1. 上傳指定 MOVEit report.md，單次分析。
2. 檢視第 4、5 個行為：系統寫 created／deleted，好像已確認發生；原文是驗證後能執行的工具能力。
3. 第 4 行為還說 username、LoginName、RealName 都設成 Health Check Service；原文 username 是隨機，只有後兩者固定。
4. 這兩個行為卻都顯示「原文」「引文全部成立」。引句字面相符不能證明主張語意正確。

證據：[018-moveit-analysis-result.png](../evidence/qa-ux-r2/018-moveit-analysis-result.png)、同名 JSON、moveit-initial-analysis-response.json 的 a4／a5；原文第 31、32 段。217 仍可重現。建議 Lead 將能力／已發生分開，不只核對引文字串。

### UXR2-02 — High：USER_SUPPLIED 自動顯示為「原文」

1. 原始依賴分析說 MOVEit 沒對應元件。
2. 缺失卡 software dependency: MOVEit Transfer 選「用替代方案」，填 nginx；另自由補充說明只測生命週期。
3. 重新依賴分析。
4. nginx 列的來源是「使用者」，依據卻是綠色「原文」。原始 report.md 沒有 nginx。

證據：[104-substitution-dependencies-result.png](../evidence/qa-ux-r2/104-substitution-dependencies-result.png)、101–103。IaC／報告有另揭露替代，不能消除依賴表本身的來源誤標。

### UXR2-03 — High：只確認 nginx 首頁，摘要卻是「行為重現通過」

1. 以上述明確替代生成、核准、部署。
2. 到驗證報告執行驗證。
3. 第 2 層「行為重現」PASS 的唯一檢查是 GET / 得到 nginx 200；對應行為卻是 exploited CVE-2023-34362。
4. 下方五個 IR 動作均明寫 not executed，卻計入「部分重現 5、未測試 0」。
5. 回分析頁，同一情境又正確說「0/5 步可重現、5 步只能替身」，與報告摘要口徑不一致。

證據：[119-verification-result.png](../evidence/qa-ux-r2/119-verification-result.png)、同名完整 JSON、120–131 的輸出、217。整鏈總結為 PARTIAL 且有警告，沒有假造完整 PASS；問題是分層摘要仍易誤導講師。實際 CVE、LEMURLOOT、帳號操作與外洩均 **NOT_TESTED**。

### UXR2-04 — Medium：攻擊鏈與缺失清單漏掉原文已指出的關鍵結構

1. 匯入 MOVEit 原文，檢視 5 行為及 4 關係。
2. 沒有 X-siLock-Comment 密碼驗證步驟；建帳號、刪帳號、取資料直接接到安裝 webshell，沒有「驗證後」前提。
3. 依賴只有一台 Web 資產與 MOVEit 服務；沒有底層 DB 資產／服務候選，也沒有引導釐清 DB 引擎、位置。
4. 原文七條受影響版本線未呈現為支援內容；實際安裝版本列未知是正確的，但支援清單仍應保留。
5. 負向情資初步十項幾乎是三個資產各問 OS／版本／網路；沒有優先詢問對外產品、弱點、管理工具、資料位置、時間等關鍵缺失。

證據：018、067、077、099、159、164；source-assessment-before-expected.md、negative-source-check-before-expected.md。沒有將缺版本硬指定為原事件事實，這部分正確。

### UXR2-05 — Medium：已知 CVE→MOVEit 關聯沒有帶入，補件誤稱原文未寫

1. MOVEit 分析明確抓到 CVE-2023-34362。
2. 去依賴頁：MOVEit 服務 CVE 顯示空，原始回應 s1.cve=[]、evidence_refs=[]。
3. 回缺失頁，出現 affected software for CVE-2023-34362，並說「報告沒有寫到這項資訊」。
4. 原文明明多次把 CVE、SQL injection 與 MOVEit 放在同一句。應區分「產品已知但 catalogue 缺映像」與「產品未知」。
5. 問題直接呈現 software dependency／affected software 等原始欄位及英文原因，新使用者很難知道預期填入格式。

證據：[099-missing-after-dependencies.png](../evidence/qa-ux-r2/099-missing-after-dependencies.png)、077、100、248、moveit-initial-analysis-response.json。這會增加無效補件循環。

### UXR2-06 — Medium：拓樸「可對外」與實際隔離網路的說法不一致

1. 生成替代拓樸。
2. external 節點顯示「可對外」、圖例說虛線代表可對外。
3. GUI 生成的 Compose 則 external.internal=true；可部署表也同時列 internal=是、plan_internal=否。
4. 本次實際隔離更嚴格，沒有發現逃逸；問題是講師可能把設計區域當成實際外網可達性。

證據：106、109、generated-docker-compose.yml、rendered-iac-static-check.json。建議清楚區分情境角色命名與實際執行網路狀態。

### UXR2-07 — Medium：未部署在不同頁面變成 error

1. 對原始 MOVEit 產生 IaC，因缺映像被拒絕。
2. 部署頁說「未部署（尚未生成 IaC）」、沒有容器與紀錄。
3. 按下一步到報告，顯示「目前部署狀態為 error，請先啟動環境」，但啟動又受前置條件阻擋。
4. 負向情資同樣重現。

證據：094 對 095、170 對 172。執行驗證確實停用，未產生假 PASS；仍應將未建立與執行故障區別。

### UXR2-08 — Medium：第一個流程節點的快捷按鈕被工具列攔截

1. 在 1440×900 開啟本場景 /flow，點左側第一個行為。
2. 該節點的「查看這個行為的設計檢查」快捷按鈕落在上方工具列後面。
3. 正常滑鼠點擊重試後仍被 AND/OR 按鈕攔截；等待版面穩定後再試仍相同。
4. 此按鈕可用鍵盤 focus＋Enter 觸發，是可繞過的滑鼠操作障礙。

證據：225、227、229；flow-overlay-hit-test.json：快捷按鈕 x=508.34、y=140.39、32×32，中心命中的是畫布工具列的 AND/OR。browser-events.jsonl 的 product-observation 有實際攔截紀錄。1280×720 的工具列還會換行，畫布閱讀更吃力（074）。

### UXR2-09 — Low：同一 h1:80 重複公開兩個轉發埠

1. 明確選 nginx 替代，重新依賴、拓樸與 IaC。
2. 原 MOVEit 服務與新增 nginx 服務都落在 h1:80。
3. Compose 產生 20000=h1:80、20001=h1:80，部署指派 127.0.0.1:42581 與 42582，兩個都轉到同一服務。

證據：104、109、114、generated-docker-compose.yml。沒有造成這次部署失敗，卻增加不必要的端點並讓講師難以判斷兩者差異。

### UXR2-10 — Medium：重新分析後，替代補件失去原問題參照

1. 對 software dependency: MOVEit Transfer 補 nginx（102）。
2. 重新依賴分析，替代成功。
3. 再進缺失頁，已加入補充裡 nginx 對應問題只剩「該缺失項目已不存在」，無法從歷史列回看原問題。

證據：[248-remaining-control-recovery.png](../evidence/qa-ux-r2/248-remaining-control-recovery.png)、同名 JSON 對照 102。替代關係在其他表仍有揭露；缺陷是補件歷史本身失去問題快照／參照，影響稽核與教學解釋。

## 4. 原文與人工答案的核對

先自行讀兩份 report.md，留下 source-assessment-before-expected.md；負向實際結果再留 negative-source-check-before-expected.md。完成自己的判斷後才讀同目錄 expected.md，沒有拿人工答案當所有假設的唯一真相。

| 核對點 | 系統實際結果 |
|---|---|
| MOVEit 核心 SQLi→LEMURLOOT→竊取資料 | 抓到；主線未混入團體歷史工具 |
| Get2、SDBot、Truebot、Cobalt Strike、Accellion／GoAnywhere | 未被塞入本次行為鏈；CVE-2023-0669 僅出現在原文引文區，不代表當成本事件弱點 |
| 能力與已發生事件 | 建／刪帳號未正確區別；隨機 username 還被改成固定值 |
| HTTP 標頭密碼驗證、Azure／SQL 枚舉、同名字串取檔、gzip | 未完整保留成可審核結構；原文對 hard-coded 與安裝時隨機密碼的不同說法也未呈現 |
| 受影響版本 vs 真正安裝版本 | 真正版本保留未知正確；受影響版本線沒有被結構化呈現 |
| 負向不確定性 | 五個抽象行為都有 hedge 標記，關係三推論、一證據不足；沒編 CVE、具體產品、工具、攻擊者或加密 |
| 防禦者行為 | 偵測、下線、重設密碼、更新、通知警方等七項被排除（173–174） |
| 負向的 3–4 個抽象行為建議 | 系統拆成五個，但每個有原文且帶不確定性，未僅因數量不同判錯 |
| 不足情資的部署／PoC | 正確 BLOCKED／NOT_TESTED，沒有 PASS；但缺失問題不夠聚焦 |

來源分級：SOURCE_SUPPORTED 僅指原文真的陳述的利用／安裝／資料竊取與能力描述；USER_SUPPLIED 是本人的補件與 nginx 選擇；ASSUMED·SUBSTITUTED 包含 nginx 1.31.8、攻擊者骨架、教學網路；BLOCKED·UNKNOWN 包含原目標 OS／DB／實際版本與攻擊細節；本次沒有自行加入 EXTERNAL_ENRICHMENT。nginx、教學版本與無害檢查結果均不是原事件事實。

## 5. 逐步操作紀錄與控制元件覆蓋

完整逐步清單是 [steps-index.tsv](../evidence/qa-ux-r2/steps-index.tsv)／steps-index.json。每一列都指向一張截圖與一份完整 DOM 快照。

| 步驟編號 | 實際操作與結果 |
|---|---|
| 001–013 | 首頁、重新整理、logo、新建；未選情境的八個後續頁面均有可理解的空狀態與返回匯入路徑 |
| 014–018 | 指定 MOVEit Markdown 上傳、Loading 秒數、完成分析；5 行為、4 關係、23 引文 |
| 019–028 | 分類篩選、關係頁籤、缺失下一步、原文定位、候選選項 |
| 029–040 | 我知道／替代／未知模式、取消、接受未知送出、全部／待補充篩選、自由補充；OS 欄曾帶入 Windows Server 後接受未知，該字串只是未知備註，依賴頁 OS 仍未知 |
| 041–076 | 行為編輯、捨棄、新增、複製、刪除、條件、AND/OR、資產、排版、縮放、連線類型、設計檢查；確認原文依賴後存 v6、版本歷史、1280×720、重新整理 |
| 077–099 | 依賴／重新分析、拓樸、重設與縮放、未核准閘門、原始 IaC 拒絕；部署刷新／健康、報告停用；核准全部不通後 IaC 仍拒絕 |
| 100–114 | 按 UI 指引明確選 nginx 替代、重新規劃核准、IaC 生成／複製／重生、confirm 後實際部署成功 |
| 115–140 | 真實驗證；12 個佐證輸出全展開；1280×720、報告 reload／深層網址；剪貼簿取出 YAML；GUI down 與歷史報告狀態提示 |
| 141–156 | 查看分析／返回／匯入新報告、三分析選項、格式選項、無效 STIX、無害 .exe 文字、檔案選擇器上傳負向、鍵盤 Enter、1280×720 |
| 157–174 | 負向全流程；缺失／流程／依賴／拓樸／IaC／部署／報告；原文不確定性與七項被排除防禦行為核對 |
| 175–218 | 負向 12 個與 MOVEit 23 個引文定位按鈕逐個點測；返回檢視、上一頁／下一頁、首頁重開自己的場景；MITRE T1190 外連可開啟新分頁 |
| 219–249 | 五個行為逐個選取；空名稱設計檢查顯示「無法儲存」；覆蓋問題重現與鍵盤替代、側欄新增、狀態選項／主機／ATT&CK／描述／起點／刪除／捨棄；補件空白必填／未知選填；最終環境清理確認 |

其他已確認：
- 匯入表單有語意 labels；import-accessibility-snapshot.txt 保留 accessibility tree。Enter 送分析／返回、Tab 與快捷鍵盤觸發可用，沒有發現基本鍵盤陷阱。
- 無效 JSON 及必填空白會顯示理由並停用送出；未知備註可不填。副檔名不在宣告清單的無害 .exe 文字仍會載入（153），沒有執行；這是觀察項，不誇大為安全漏洞。
- 三種分析方式僅單次真正執行。PDF／STIX 成功分析、其他人的情境、未實作的服務歸屬編輯及真實 CVE 攻擊均未測，不冒稱完整通過。
- 未遍歷每個重複候選值的所有組合；導覽與主要可點控制、所有本人的引文定位、所有驗證佐證均有點測。阻擋或被遮蔽的控制記為實際限制。
- 圖形條件／AND/OR／資產的新增、編輯／檢查或捨棄已測，沒有宣稱所有分支組合都經執行；它們是設計圖。

## 6. 瀏覽器、網路及測試方法紀錄

[browser-diagnostics-summary.json](../evidence/qa-ux-r2/browser-diagnostics-summary.json) 是完整分類。

- 主頁面的 pageerror **0**、requestfailed **0**。
- console error **59**。被動錄得的 HTTP 錯誤全部是缺 PDF／未生成 IaC／未生成驗證報告的 404（共 56 次），以及如實拒絕 IaC 的 422（3 次）。未見 5xx。不可把這些預期空資源與阻擋全部當產品故障，也不能聲稱 console 完全沒有 error。
- 八次控制指令錯誤留在 log：多數是自動化可及名稱／placeholder 改變、停用按鈕或等待參數；其中節點快捷按鈕被遮蔽已用穩定版面及 hit-test 獨立重現，列為 08。未為了讓測試通過使用 force click。
- 快速切換節點立即輸入的一次自動化動作清空了前一選取節點；等待選取穩定後內容正常。該未儲存修改已捨棄，未將此競態直接列為產品錯誤。
- DOM pre.innerText 會把視覺程式碼行拼接，最初無法以該文字解析 YAML；沒有把測試方法問題當產品缺陷。改以真正「複製」按鈕／瀏覽器剪貼簿取得後，YAML 解析通過。
- UI 啟動／關閉 confirm 由測試腳本接受，對應本任務明確授權的隔離部署與清理。

主要實際指令與輸出：

    /home/tyc4d/.nvm/versions/node/v22.23.3/bin/node reports/overnight/evidence/qa-ux-r2/browser.cjs
    → Chromium 啟動、001-home-initial、READY；最終正常 exit_code: 0

    /home/tyc4d/cr-project/.venv/bin/python
    → yaml.safe_load(GUI 剪貼簿取得的 generated-docker-compose.yml)
    → yaml_parse: PASS
    → services: h1, attacker, cr-gateway
    → external: internal=true；scenario-internal: internal=true；edge: internal=false
    → h1／attacker published_ports=[]；只有 cr-gateway 綁定預設 127.0.0.1

    zipfile.ZipFile(...).testzip()
    → trace-original-moveit.zip: PASS
    → trace-substitution-deploy.zip: PASS
    → trace.zip: PASS

未改產品，因此沒有執行 pytest／build，也沒有宣稱單元測試或建置通過。實際站台回應、完整輸出及瀏覽器動作在證據內。

## 7. 證據索引、異動與未解事項

證據共 **249 組編號截圖＋JSON、另 2 張新分頁截圖，合計 251 PNG**。三份 trace 已檢查 ZIP 完整性：

- trace-original-moveit.zip：原始匯入至依賴替代前後的初段。
- trace-substitution-deploy.zip：明確替代、IaC、真實部署／驗證／關閉。
- trace.zip：負向情資、來源定位、最後控制元件與清理。
- browser.cjs、browser-events.jsonl、browser-diagnostics-summary.json：控制程序與實際事件。
- moveit-initial-analysis-response.json、negative-initial-analysis-response.json：最初 GUI 分析回應。
- source-assessment-before-expected.md、negative-source-check-before-expected.md：先自行判斷的紀錄。
- input-files.json：兩份 report.md 與 expected.md 的實際 SHA-256。
- generated-docker-compose.yml、rendered-iac-static-check.json：GUI 複製出的真正 YAML 與安全靜態檢視。
- flow-overlay-hit-test.json、import-accessibility-snapshot.txt、deep-link-new-tab.json、external-mitre-link.json。
- milestone-history.md：先前逐里程碑報告，保留當時的進度敘述；最終結論以本檔為準。
- trace-validation.json、steps-index.tsv／json、final-git-status.txt。

Repository 異動僅本報告與 reports/overnight/evidence/qa-ux-r2/；沒有產品程式碼變更，**沒有 commit**。共享 QA 資料只新增本人的兩個情境及其測試版本／報告；部署資源已清理，保留情境供 Lead 複查。

未解：上列十項產品問題；原 MOVEit 與五個攻擊動作未執行；不足情資缺乏建立環境的必要資料。服務未歸屬主機的情況，UI 誠實承認目前沒有指定歸屬操作（164／168），屬已記錄的流程限制。

需產品負責人決定事項：**本輪沒有另提功能／範圍決策**。優先修正來源與驗證標示屬既有範圍；是否新增 MOVEit 教學機制不在本 QA 自行開發或核准，交 Lead 依既有 approved-scope 判斷。

