實際模型：GPT-6.1-Sol；reasoning effort：Ultra；Fast：關閉（hc t3f 啟動參數及畫面確認，runtime.json）。

# qa-ux Round 1 獨立 GUI 驗收

**總結：PARTIAL，53 / 100。指定 MOVEit 情境的「講師完成部署並驗證攻擊鏈」任務 BLOCKED。** 情資可匯入、引用可核對、補件與流程編輯可儲存；但主機／服務關聯斷裂，且本站沒有可重現 MOVEit 的元件。本輪沒有成功產生 Compose、啟動容器或重現任何攻擊。站台有如實阻擋，未觀察到把環境或攻擊冒報為成功。

測試日期：2026-11-15（Asia/Taipei），02:16:14–02:42:06。僅測試與回報，不修產品程式碼、不 git add/commit、不啟動其他 Agent。

## 受測環境與證據

- 站台：`http://127.0.0.1:5177`，由 Lead 維護；未重啟前後端、未啟自有 API instance、未讀入金鑰或修改預算。
- 真實 Playwright + Chromium，1440×900、1280×720。先看畫面，未讀前端原始碼找按鈕；所有情境操作、分析、規劃、核准及部署嘗試均從 GUI 觸發。
- 工作樹：`agent/qa-ux`，基底 `f545757a65828f93fdc4871f4e75e27bbc8e922e`。這不是共享站台的不可變 build ID；同站有其他測試者並行工作。
- 主證據：[索引](../evidence/qa-ux/round1/INDEX.md)、[主 trace](../evidence/qa-ux/round1/trace.zip)、[GUI 回應紀錄](../evidence/qa-ux/round1/ui-responses.jsonl)、[瀏覽器事件](../evidence/qa-ux/round1/browser-events.json)、[觀察稽核](../evidence/qa-ux/round1/observed-audit.json)。
- 共 249 個編號步驟，每步 PNG＋JSON；另 2 張深層網址截圖，共 **251 張**。主 trace 約 177.8 MB，已完成封存及 ZIP CRC 檢查；另有 fresh-context trace。
- JSON 是實際 GUI 網路回應的被動紀錄，用於比對內容；沒有以直接打 API 取代 GUI 驗收。未使用 mock。

| 自建情境 | ID | 最終狀態 |
|---|---|---|
| ux CL0P MOVEit round1 | scn_2ae1f51510ca | v7、拓樸待核准、無 Compose、無容器；up/down 各一筆 failed |
| ux 短情資 round1 | scn_f0f589b2b6ed | v1、0 行為、拓樸待核准、無 Compose、無容器、0 部署紀錄 |

兩個情境留供 Lead 重現。測試新加的行為、複製品、條件、運算及資產都已刪除／捨棄；只保留明確標示 UX QA 的補充與一筆行為說明編輯。未操作他人的部署環境。

## 原文對照與來源分級

原文為指定 `fixtures/sample-scenarios/clop-moveit-advisory.md`，1,306 字元，SHA-256 `feb1305b49ea549c93b81a5a5f4e94876e3ecb3e1a7b0400d753615150ddf8b1`。核對的是這份摘要，沒有把連結中的原始 PDF 或唯讀研究資料當成已驗證內容。

| 原文事實／未知 | 實測結果 |
|---|---|
| CL0P 利用 CVE-2023-34362，產品為 Progress MOVEit Transfer | 行為與服務保留產品名稱；CVE 保留在 indicator，**不是整體遺失**，但未關聯至服務，依賴頁 CVE 欄為空 |
| SQL injection → 安裝 LEMURLOOT → 擷取系統及資料庫資訊 | 抽到對應行為；另把「利用 CVE」與「SQL injection」拆成先後兩步，原文不支持這個額外順序 |
| 未提供實際安裝版本、hostname、OS 或特定受害者網路配置 | 沒有把這些寫成確定值；但 placeholder target 在缺失頁被叫作「原文已知」，見 UX-04 |
| 引文應可在輸入中找到 | 9 句中 8 句逐字存在；evidence-5 跨段拼接並略去中間句子，不是原文連續引文。產品有標片段及關係證據不足 |
| 未提供可執行 PoC、實驗環境與預期驗證證據 | 最終分析頁顯示 0/4 步可重現，沒有宣稱已驗證；未自行補成漏洞利用程式 |

分級保持分開：

- **SOURCE_SUPPORTED**：上述產品、CVE、SQL injection、LEMURLOOT、資料擷取及 8 句可直接找到的引文。
- **EXTERNAL_ENRICHMENT**：內建 catalogue 的 image/version 為工具補強，未當作事件原文；本輪沒有獨立拉取映像或核對 digest。
- **USER_SUPPLIED**：本測試者的 5 筆補件／備註與儲存的行為說明。畫面有「使用者」標籤；修改原 LLM 行為後也改標使用者。
- **ASSUMED·SUBSTITUTED**：明示「非原事件」的隔離教學網段，以及規劃器補的 attacker scaffold。未宣稱可取代 MOVEit 漏洞行為。
- **BLOCKED·UNKNOWN**：受害主機實際 OS/build、MOVEit 安裝版本、媒體、服務的實際主機歸屬及可執行驗證；未以猜測補成已知。

## 逐步操作與實際結果

完整逐步畫面、URL、viewport 與控制項見 INDEX；下表按可驗收流程分組，步驟號對應同名 PNG/JSON。

| 步驟 | 操作 | 實際結果 |
|---|---|---|
| 001–020 | 首頁、重新整理、新建；未選情境時走分析／缺失／流程／依賴／拓樸／IaC／部署／報告 | 各空白頁有返回首頁／匯入引導，導覽可用 |
| 021–024 | 輸入 ux 名稱，從檔案選擇器載入指定 MD，開始單次分析 | 自動識別 Markdown；Loading 顯示秒數並停用表單，完成後進分析頁 |
| 025–032 | 行為／關係兩頁及來源篩選 | 4 行為、3 關係；空篩選有說明，r1 為證據不足，沒有誤當全部關係成立 |
| 033–040 | 缺失篩選、展開受影響主機、選項、補充、三種回答模式與取消 | 可帶入文字；空答案禁止送出；初始僅 3 項主機問題 |
| 041–046 | 流程設計檢查、依賴重新分析、產生拓樸 | 出現額外軟體問題；IR 主機 ID 分裂、服務未歸屬，拓樸有雙 target、0 開通連線 |
| 047–054 | 未核准前產生 IaC、部署狀態／健康檢查／更新、執行驗證 | IaC 回 422；up 停用且提示人工核准；驗證回 400「尚未部署」 |
| 055–077 | OS/build/軟體接受未知、網段明示替代、自由補充；全部／待補充；重新整理 | 版本至 v6；補充保存，使用者來源清楚；接受未知沒有填入確定 OS。空白自由補充禁止送出 |
| 078–084 | 清空行為名稱、捨棄、修改說明、存 v7、重新整理 | 空名稱顯示「無法儲存」且按鈕停用；捨棄及儲存有效，刷新後說明仍在 |
| 085–125 | 縮放／fit／排版；三種連線模式；新增／複製／刪除行為；條件真分支拖線；AND/OR；資產；關係類型／理由／刪除；捨棄；版本與說明展開 | 操作有反應，未命名／孤兒／缺分支有設計提醒；恢復原圖。INVALID 技術文字曾在暫存卡出現，未儲存，不能據此宣稱後端接受無效 ATT&CK ID |
| 126–136 | 1280×720、鍵盤 Enter 開行為／Tab 到欄位、拓樸重設／縮放、核准備註 | 鍵盤基本編輯可用；小視窗有特定重疊情況；核准前後狀態有區分 |
| 137–148 | 核准後再產 IaC；up/down 原生確認框先取消、後明確接受重測；重新規劃 | 仍無法生成 IaC；確認 up/down 都回 503 並寫 failed 紀錄；容器為空。重新規劃撤銷核准 |
| 149–173 | 回到已匯入內容；9 個引文按鈕逐一點選；查看分析／瀏覽器上一頁；匯入新報告／返回；切換所有格式及分析模式；無效 STIX JSON | 8 個引文可標示，拼接引文不能整句定位；上一頁可返回。無效 JSON 有中文錯誤且送出停用；只切換選項，未執行分階段／複核分析 |
| 174–180 | 貼上「某公司遭到入侵，細節不明。」（13 字元），以 Tab/Enter 完成送出 | 格式、模式、檔案、內容、送出焦點順序合理；表單 label 有關聯 |
| 181–193 | 短情資分析後走完整下游頁；產生依賴／拓樸／IaC；執行驗證；直接開 /missing | 0 行為、0 引文，指標為不適用，沒有幻造攻擊；仍因無可用元件阻擋 IaC／部署／驗證 |
| 深層網址 | 同 context 新分頁 /flow；全新 context /report | 前者保留所選短情境；後者顯示未選情境與匯入引導，沒有借用別人的情境 |
| 194–225 | 首頁開啟自己的情境；兩種尺寸逐頁檢查，長頁補拍上下段 | 來源、版本與所選情境一致；主內容為內部捲動容器，fullPage 本身不會展開全部內容，所以另外補拍底部 |
| 226–239 | 精確重現捲動保留；再核准／前往 IaC／部署；重新規劃；短情境新增第一行為後捨棄；最終容器檢查 | 捲動由前頁 623 保留到新頁 246；兩個情境最終均無容器、待核准。只保留自己的測試資料 |
| 240–249 | 四個行為及三條關係逐一開屬性、拓樸網路節點選取、最終分析狀態 | 最終清楚顯示 0/4 步可重現。沒有把設計檢查通過當成部署／驗證通過 |

未發現上述主要功能類型的死連結或完全無回應操作；看到的錯誤多有回饋，但部分只有英文與大量原始欄位。**不宣稱無例外點遍全站每個 DOM 元素**：沒有逐一開啟他人的情境、沒有覆蓋不可達的成功部署後專屬控制項，亦未窮舉所有相同圖節點的所有交互組合。

## 問題清單

### UX-01 — High：主機與服務關聯斷裂，規劃出重複 target

重現：匯入指定 MD → 分析 → 軟體依賴「重新分析依賴」→「產生拓樸規劃」。

實際：匯入回應僅有 `host-target`，4 個 action 的 target 卻都是不存在的 `unknown`；規劃後 IR 有 `host-target`、`unknown`、`host_target` 三筆，畫布可看到 3 個 target，拓樸有 2 個 target。`svc1` 沒有 host 關聯，規劃備註說已排除該服務；CVE 留在 indicator，但沒有掛到 MOVEit 服務，依賴頁 CVE 為空，另要求使用者識別受影響軟體。action 名稱本身其實已含該 CVE 與 MOVEit。

影響：講師無法確認步驟到底作用在哪個 target，不能得到一致的攻擊／環境關聯。即使本站不支援 MOVEit，IR 仍應保留穩定且可解釋的未知主機關聯。沒有證據證明只修這一點就能部署：缺少 MOVEit 元件是另一個真實阻礙。

證據：[依賴](../evidence/qa-ux/round1/043-deps-first-view.png)、[拓樸](../evidence/qa-ux/round1/046-topology-generated.png)、[目標選單](../evidence/qa-ux/round1/079-flow-action-inspector.png)、observed-audit.json 及實際 ingest/dependencies/topology 回應。

### UX-02 — Medium：必要的軟體補件問題沒有可理解內容

重現：上述重新分析依賴後回缺失頁。

實際：新增第 4 項僅顯示「軟體相關資訊（後端未提供中文問題）」，沒有說明 CVE、要補什麼、影響誰或原因。被動回應的 field 是 `affected software for CVE-2023-34362`，reason 也有內容，但 GUI 沒呈現。

影響：使用者不知道如何處理這個阻礙，無法把依賴問題和補件操作接起來；首次缺失頁又未提示後面的依賴分析會新增問題。

證據：[新增問題](../evidence/qa-ux/round1/055-missing-after-dependency-analysis.png)、[編輯畫面](../evidence/qa-ux/round1/070-missing-software-opaque-edit.png)。

### UX-03 — Medium：缺失嚴重度的中文呈現與後端 major 不一致

重現：開啟任一自建情境的缺失頁，對照 GUI 載入的 missing_items。

實際：後端 OS、build、網路及軟體項目為 `severity: major`，畫面一律顯示「次要」。

影響：可能降低講師對必要重建資訊的注意。請 Lead 核對嚴重度字典；本輪依一般 major 語意判為呈現不一致，沒有自行更改產品定義。

證據：[缺失頁](../evidence/qa-ux/round1/033-missing-first-view.png)、ui-responses.jsonl 中 ingest/analyze 及 dependencies 回應。

### UX-04 — Medium：程式建立且證據不足的 target 被稱為「原文已知」

重現：以 13 字短情資建情境 → 缺失補充。

實際：原文沒有主機名稱、OS、資產線索，卻顯示「原文已知：target」及「原文只提供主機/資產線索」。回應中 target 是 `source: program`、`epistemic_status: insufficient`；缺失 known 項也不是 supported。

影響：混淆 SOURCE_SUPPORTED 與 BLOCKED·UNKNOWN。程式 placeholder 可以保留，但應讓講師看出它沒有原文依據。

證據：[短情資缺失](../evidence/qa-ux/round1/184-short-missing.png)、原文只有 13 字的同頁及 ingest/analyze 回應。

### UX-05 — Medium：下一步沿用前頁捲動位置，跳過新頁說明

重現：1440×900 開分析頁 → 捲到底 → 按「下一步：缺失補充」。

實際：前頁 `main.scrollTop=623`，新缺失頁 `scrollTop=246`，標題、說明及頁首狀態在視野外。最初的分析完成跳轉與其他底部下一步操作也有類似困惑。

預期：使用者明確進入下一階段時，應從該頁開始處閱讀。

證據：[前頁底部](../evidence/qa-ux/round1/226-scroll-analysis-bottom.png)、[新頁位置](../evidence/qa-ux/round1/227-scroll-preserved-new-missing.png)、route-scroll-result.json。

### UX-06 — Medium：展開設計檢查後縮小視窗，畫布控制項覆蓋行為卡

重現：1440×900 流程頁展開下方設計檢查 → 改成 1280×720。

實際：畫布可用高度縮小，既有圖的位置未同步適配；圖例、zoom、minimap 與行為卡重疊，第四步超出中央區域。

範圍：不是所有 1280 畫面都壞掉。重新進入頁面、收合檢查後的預設版面較正常，已另留對照圖；問題是 resize 加展開狀態。

證據：[重疊](../evidence/qa-ux/round1/126-flow-1280x720.png)、[重新進入後對照](../evidence/qa-ux/round1/202-sweep-1280-flow-top.png)。

### UX-07 — Low：尚無 Compose 仍可啟動，錯誤回饋偏向原始資料

重現：核准目前無法生成 IaC 的拓樸 → 部署 → 確認啟動。

實際：啟動按鈕已啟用，最後回 503、`compose file has not been generated`，畫面展開很多英文 key、stdout/stderr 等欄位；未提供清楚的下一個修復操作。從未部署的狀態直接呈現 error。

影響：讓「已核准」與「可部署」的分別仍需靠試錯理解。後端確實拒絕且記錄 failed，沒有誤啟動或假成功。

證據：[確認啟動後](../evidence/qa-ux/round1/145-deploy-up-confirmed.png)、[最終部署狀態](../evidence/qa-ux/round1/237-final-clop-container-check.png)。

### UX-08 — Low：模型把跨段內容合成引文，並多建一條不受支持的時序

重現：指定 MD 的本次單次分析 → 關係 r1／引文 evidence-5。

實際：將第 3、4 段部分句子拼接為引文，略去中間句子；另把漏洞利用概述當成 SQL injection 之前的一步。不是原文明確記載的兩個依序行為。

範圍：這次 LLM 輸出的品質問題，不聲稱每次都相同。產品已正確標成 partial／insufficient，原文定位也沒有假裝命中，沒有當成全鏈已證實。

證據：[關係](../evidence/qa-ux/round1/030-analysis-filter-5.png)、[無法整句標示](../evidence/qa-ux/round1/154-source-quote-5.png)、observed-audit.json 的逐字核對。

未發現 Critical 問題；本輪沒有觀察到跨情境容器被修改、未核准部署成功或攻擊結果假 PASS。這只是本次觀察，不能代表未測路徑也安全／正確。

## 評分（依本輪實證，總分 100）

| 項目 | 分數 | 給分與扣分理由 |
|---|---:|---|
| 情資擷取與證據正確性 | 16 / 20 | 核心產品、CVE、3 個實際行為與未知保留正確；8/9 引文逐字成立。扣分：拼接引文、不受支持的額外時序、placeholder 的原文標示 |
| 攻擊鏈、相依性及缺失分析 | 10 / 20 | 行為、兩個原文時序及可重現性 0/4 有呈現，unsupported 沒冒充可用；扣分：4 個懸空 host ref、多重 target、服務／CVE 未連接，以及不清楚的補件迴路 |
| 補件及場景編輯流程 | 7 / 10 | 回答模式、取消、空值防護、版本、儲存／捨棄與刷新可用；扣分：軟體問題空泛、嚴重度對應、未知 placeholder 的來源誤導 |
| IaC 正確性與部署可用性 | 6 / 20 | 無安全映像時拒絕、人工核准閘門及重規劃撤銷核准有證據；未取得成功 IaC／部署，不能給其餘可用性分數 |
| 攻擊行為／PoC 驗證 | 2 / 15 | 未部署時拒絕驗證，並明確區分可重現與已執行；沒有任何 runtime 行為或攻擊鏈證明，其餘不給分 |
| GUI 可用性與操作直覺性 | 7 / 10 | 主導覽、空白／Loading、引文定位、鍵盤基本操作、情境切換與深層網址可用；扣分：捲動跳頁、小視窗重疊、部署準備狀態與錯誤資訊不直覺 |
| 測試證據與可追溯性 | 5 / 5 | 真實瀏覽器逐步圖、trace、實際回應、原文核對、錯誤與未測範圍完整分開 |
| **總分** | **53 / 100** | **不是部署或攻擊驗證 PASS；僅代表指定資料與本站當時狀態的本輪驗收** |

## 測試指令、輸出與瀏覽器錯誤

實際啟動：

```sh
/home/tyc4d/.nvm/versions/node/v22.23.3/bin/node reports/overnight/evidence/qa-ux/round1/browser.cjs
```

以 PTY 保留互動輸入，第一個有效結果為 `ready: true`。後續命令在同一個真實 page 執行，過程由 trace 與逐步檔保存。結束收到 `closed: true`，瀏覽器已關閉、trace 已封存；控制器 TTY 仍保持開啟，因此最後 Ctrl-C 結束控制器（exit 1），不能把該程序退出碼當作產品測試失敗或成功。

第一個非 PTY 啟動因 stdin 關閉而結束，未做情境操作；改用 PTY 後執行上述全部流程。5 筆 harness error 分別為側欄按鈕可存取名稱不同、匯入頁處於唯讀狀態、STIX placeholder 改變、送出鈕因無效 JSON 停用、拓樸節點名稱定位不符，均已釐清，沒有列成產品 bug。

實際證據稽核：

```sh
/home/tyc4d/cr-project/.venv/bin/python reports/overnight/evidence/qa-ux/round1/observed-audit.py
```

輸出（exit 0，原檔 audit-output.txt）：

```text
scn_2ae1f51510ca ux CL0P MOVEit round1: 4 actions, 3 relations, 4 unresolved action host references
  Source audit: 8/9 literal quotes in supplied fixture
scn_f0f589b2b6ed ux 短情資 round1: 0 actions, 0 relations, 0 unresolved action host references
Screenshots: 251; uncaught page errors: 0; transport failures: 0; harness errors: 5
HTTP responses >=400: 89
```

這是觀察資料的稽核，不是另一個部署測試。89 次 HTTP 錯誤包含重複載入與刻意負向測試：82 次 404（沒有 PDF 原檔、未生成 IaC、未有報告）、2 次未部署驗證 400、3 次 IaC 422、up/down 各 1 次 503。未把它們全部當成 89 個 bug，也沒有忽略。console 有對應 HTTP error；**0 uncaught page error、0 requestfailed transport failure**。完整分類見 observed-audit.json。

`trace.zip` ZIP 檢查：4,104 entries，`testzip() = None`；fresh-context trace：33 entries，同樣無損壞。沒有跑 pytest、前端 unit test 或 build；本任務是獨立 GUI QA，沒有產品程式變更，不把未執行項目寫成 PASS。

## 阻礙、未測與清理

- **BLOCKED**：指定 MOVEit 案例成功 IaC／部署／執行後報告、主機／服務真實健康、PoC 行為、全鏈、拒絕路徑實際探測。兩個情境皆無可部署元件，沒有以其他軟體或 mock 冒充。
- **NOT_TESTED**：PDF 上傳／PDF 頁面定位、有效 STIX bundle 的完整分析、分階段／複核實際 LLM 分析、Windows VM、成功部署後才出現的 GUI 控件、完整純鍵盤畫布連線、其他人的情境操作、所有重複控件的無例外窮舉。
- **清理**：GUI 最終確認兩個情境容器為空（237、238；final-container-checks.json）。本輪從未成功啟動容器；down 因無 Compose 失敗，不能宣稱 down 成功。瀏覽器已關閉，沒有啟動測試伺服器／容器需額外停止，也未碰其他專案容器或埠。
- **未解**：UX-01–08 全部只回報，沒有修產品碼。資料不足／不支援元件造成的失敗仍保留供 Lead 判斷。
- **需產品負責人決定**：本輪沒有要求新增功能或變更產品方向。是否增加特定 MOVEit 可重現方案由 Lead 依既有核准範圍處理；本 QA 不自行擴充。

## 檔案變更與提交

僅新增／更新 `reports/overnight/worker-reports/qa-ux-round1.md`、摘要 `qa-ux.md` 與 `reports/overnight/evidence/qa-ux/round1/**`（測試控制器、稽核腳本、截圖、JSON、trace、索引、manifest）。沒有產品程式碼變更，沒有 git add／commit；由 Lead 檢查並決定保存／整合方式。
