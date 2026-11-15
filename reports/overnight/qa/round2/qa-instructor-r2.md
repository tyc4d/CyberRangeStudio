模型：gpt-6.1-sol；reasoning effort：ultra；Fast / ultrafast 均關閉（hc get t3m 啟動參數與本機 TUI 確認）。

# Round 2 講師角色獨立驗收（完成；主要部署流程阻塞）

- 名稱：qa-instructor-r2；站台：http://127.0.0.1:5177；指定凍結版本 main 43ba325（站台實際版本待 GUI 確認）。
- 已完整閱讀根目錄 AGENTS.md、COMMON.md、E-instructor-r2.md。未讀前輪 QA 報告、前端原始碼、expected.md；只測試與報告，沒有修改產品程式、沒有啟動其他 Agent、沒有 git add/commit。
- 證據目錄：reports/overnight/evidence/qa-instructor-r2/
- 啟動設定證據：00-runtime.json。

## 進度

1. 已確認指定 Ultra 與 Fast 關閉。接下來以 Chromium 實際畫面操作兩份情資並保留 trace 與逐步截圖。

## 里程碑一：Equifax 原文分析與補件

- Chromium 實際登入首頁（無帳密畫面），建立 `qa-instructor-r2 Equifax 2017`，Markdown 檔案匯入 12,879 字元，使用預設單次分析。
- 產出 9 行為、8 關係；19 引句中 14 逐字、5 片段，7 個步驟標原文、2 證據不足。主要 RCE→資料庫搜尋→明文帳密→擴張存取→9,000 查詢→分批加密外傳都有納入；無憑空填入 CVE 或資料庫產品。
- 逐條先行原文判讀已存 `05-source-assessment-before-expected.md`，尚未讀標準答案。
- 7 個缺失逐項填入教學替代（Linux Server / Ubuntu 22.04 / isolated-lab / 從掃描開始），另自由補充假資料與 3 月、5 月分別事件。系統留下使用者來源，版本 v1→v9。
- 編輯第一行為的講師說明，確認 6 條依賴並另存 v10；GUI 成功回饋且來源改為使用者。
- 觀察：部分原文被省略註腳／拼接句子後標證據不足（如原文 portal25）；報告的真實行為因此看起來像無根據。補件顯示 0 待補，流程圖主機有「—」資訊；後續已確認是埠欄，不列 OS 問題。
- 截圖與對應文字：01–15；關鍵流程 trace 將於結束儲存。

## 里程碑二：部署規劃阻塞（繼續其他可測項目）

- 執行依賴分析後，把原文的 `encrypted communication channels` 與 `standard encrypted web protocols` 當成軟體，要求選替代品。原文的 DB 資產沒有被抽成資料庫服務。畫面提供英文原始欄位名與缺失，無建議選項。
- 依 UI 流程做教學替代測試：Struts 2.3.30；通道→NGINX；DB 所在 h2 的協定項→PostgreSQL（僅作合成 DB 教學，非真實協定等價）。兩替代品有在所屬主機且 catalogue 有值。依賴頁顯示未對應元件 0（22）。
- 拓樸規劃 h1 同時含 Struts:8080 與 NGINX:80，但只能選一個映像。頁面提醒衝突；選擇隔離網段也使 attacker 無進入路徑，系統如實揭露（24）。核准後仍可進 IaC。
- 生成 IaC 失敗：`host h1 declares port 80, unsupported by vuln-struts2-s2-045`；沒有 compose／容器啟動（26）。頁面同時說「這個情境還沒有生成 IaC。按…」，且各主機「可部署」全是，容易混淆。會嘗試從場景編輯移除協定誤抽項後繼續；原始失敗證據保留。

- 原場景無法從 GUI 找到主機／服務編輯，只有行為可編輯；缺失「全部」中原本兩個替代項已轉為 fidelity 說明，原回答顯示「該缺失項目已不存在」（28）。因此未再改動繞過檢查。
- 部署頁確實停用啟動按鈕，顯示未生成 IaC、0 部署紀錄；驗證頁停用執行並標各層未測。驗證文字卻稱部署狀態 `error`，部署頁則「未部署」（29–30）。原場景沒有建立任何環境，無容器需清除。
- 本次原場景端到端結果：步驟 1–9 已操作，步驟 10 BLOCKED；PoC / 攻擊鏈 NOT_TESTED，不算通過。

## 補充交叉測試：Equifax 分階段＋複核

為排除單次分析模式影響，透過同一 GUI 原文另建 `qa-instructor-r2 Equifax staged review`，選分階段＋複核，原文完全相同、未摻入測試指令（34–38）。產出 8 行為／6 關係、31 引句、8 步驟引文全部成立，但依賴分析仍把兩個加密協定抽成無對應軟體，也沒有資料庫引擎。此模式未消除部署規劃根因，沒有再用不等價替代品強行宣稱成功；此額外場景未部署。

## 里程碑三：CISA 分析、限制及部署規劃

- 新建 `qa-instructor-r2 CISA AA22-320A`，Markdown 9,935 字元、單次分析，16 行為／15 關係，79 引句：51 逐字、1 相符、10 片段、17 沒對上（40）。
- 16 行為大致保留原文：Log4Shell、Defender 排除、下載／刪除、XMRig、SYSTEM 排程、RDP/DefaultAccount、工具下載、Mimikatz/rogue domain admin、多主機 Defender/Ngrok、DC 列舉、改密碼及 LSASS 嘗試。沒有把 LSASS 嘗試改寫為成功，完整引文也保留 AV 阻擋。ATT&CK 將 XMRig 安裝配為 T1136.001 Local Account，與該行為主述不一致；Mimikatz＋建帳號合併也只標 T1136.002，遺漏取憑證的 technique。
- 所有 15 條關係全標證據不足，對應 evidence-23–37 都是 `unresolved:empty`；多句同時又在行為引文中逐字成立（例如 file.zip、DefaultAccount、Mimikatz、改密碼、LSASS），造成設計圖 15 待處理、12 時序不計入鏈（41、47）。
- 缺失頁有 25 項，能用中文理解 OS、版本、網段、AD、RDP、Defender 初始狀態、假帳號、外連限制。測試 Horizon/Log4j「接受未知」、外連封鎖、lab.test 教學網域、不啟用 RDP，並加自由補充明確說「Linux/Solr 只能作入口漏洞教學替代，不等於 Horizon、Windows Defender、RDP 或 AD 完整重現」（43–46）。
- **新問題**：這段否定／限制說明被轉成 Solr 服務（使用者來源卻顯示「✓ 原文」），而且無主機歸屬；依賴／拓樸明示目前沒有指定服務主機的 GUI 操作（48–49）。原文 report.md 無 Solr。
- 依賴分析沒有抽成可部署的 Mimikatz/XMRig/PsExec/Ngrok 元件；Horizon、AD 都明示 unsupported，不會冒充自動重現。拓樸備註清楚說 Horizon 需外部後端、AD 需版本化的 DC/member 隔離拓樸；這部分誠實。
- 「不啟用 RDP、將此步驟標記未重現」補件後，拓樸仍會開 h1→h2 TCP3389，且沒有逐行為未重現標示（45-3、49）；需確認補件只記錄文字、不會改規劃的限制是否符合需求。

## 最終補查與更正

- 產生規劃後回到「分析結果」，其實有逐行為的「可否重現」欄：Equifax 顯示 5/9 可重現、4 只能替身（58、60）；CISA 顯示 0/16 可重現、7 需 Windows VM、9 無法重現（61）。這是規劃能力預估，頁面明說不等於已執行／驗證通過；最終驗證報告仍完全不存在，不能當成五類驗證結果都已實測。
- Equifax 的「既有加密通道送查詢／取 PII」被標「可重現」，滑鼠說明僅因 h1 有 pinned Struts 元件可做 service-level check，沒有證明該行為的 HTTPS／資料流可重現；且同個場景 IaC 已被埠衝突拒絕（26、60）。
- 主機在攻擊流程左欄顯示的「—」是埠資訊，不是 OS。依賴頁已正確顯示使用者填的 Linux Server / Ubuntu 22.04（16–17）；先前懷疑補件未寫入 OS，已排除，不列產品問題。
- 本輪三個情境的部署頁皆為 0 部署紀錄／未部署（56、65、66），沒有曾建立的環境需要從介面清除；未操作其他測試者的情境與容器。

## 最終結論與驗收範圍

**本輪講師端驗收未通過，綜合評分 45/100。** 原文分析、補件、行為編輯、人工核准等頁面可操作；Equifax 的協定／服務誤判讓主要情資卡在 IaC，CISA 的 Windows/Horizon/AD 限制被誠實揭露，但來源分級、關係引文與補件採用仍有問題。**沒有完成真實部署、PoC、攻擊鏈或驗證報告驗收，這些全部 NOT_TESTED／BLOCKED。** 不是容器啟動成功，更不是完整攻擊鏈 PASS。

### 站台、模型與資料

- 2026-11-15 執行；日期／輸入雜湊證據：`review-time.txt`、`input-sha256.txt`。UI 時間為 07:xx，主機 Asia/Taipei 時間約 15:xx；未把 UI 時區差異判成攻擊時間問題。
- Chromium/Playwright 真實瀏覽器，1440×1050；操作只走 http://127.0.0.1:5177 GUI，未直接發 API 請求、未讀前端原始碼、未對容器發攻擊指令。
- 依 Lead 指定測試凍結站台 `qa-round2` / main `43ba325`。GUI 沒有顯示可核對的執行版本；本工作樹 HEAD 為 `75753fe6f5ad90ff8cf66fee2c5ce34425ace0fc`（`worktree-head.txt`），**不將工作樹 HEAD 當成站台實際版本證據**。
- 原文先行判讀：`05-source-assessment-before-expected.md`。完成兩份原文判讀及主要 GUI 操作後，才讀同目錄 `expected.md`，沒有讀前輪 QA 報告。
- 情境 ID：主測 Equifax `scn_3d56cb2ee150`（最終 v13）；交叉測試 Equifax `scn_fb5785a18f78`（v1）；CISA `scn_fa2301161837`（v8）。建立新情境，不覆蓋他人資料。

### 十步操作與實際結果

| 步驟 | Equifax 實際操作／結果 | CISA 實際操作／結果 | 主要證據（同名 .png + .txt） |
|---|---|---|---|
| 1 進入／登入 | 首頁可進，未出現登入要求 | 同一瀏覽器另建新情境 | 01、02、31 |
| 2 匯入原文 | 上傳 report.md，12,879 字元，預設單次分析 | 上傳 report.md，9,935 字元，單次分析 | 03、31 |
| 3 對照分析 | 9 行為／8 關係，核心行為存在，2 行為證據不足 | 16 行為／15 關係，4 行為證據不足；多句引文重複判定不一致 | 07、40、41、63、64 |
| 4 理解流程 | 3 月→5 月為時間先後，沒有誤畫存取相依；6 依賴需人工確認 | 15 關係皆 unresolved，12 時序不計入鏈 | 13、47、59 |
| 5 檢查缺失 | 初始 7 項；依賴分析後增加 Struts 版號、錯誤協定軟體項 | 初始 25 項；具體詢問 AD/RDP/Defender/帳號/外連 | 08、18、42 |
| 6 提供補充 | 逐項教學替代＋自由文字，保留使用者來源 | Horizon/Log4j 未知，封鎖外連、lab.test、不啟用 RDP＋限制說明 | 10–12、19–21、43–46、54、55 |
| 7 修改行為／場景 | 改第一行為說明、確認 6 依賴、另存 v10，後續補件至 v13 | 規格透過補件修改；未把無法驗證關係一鍵全當正確 | 14、15、45、47 |
| 8 拓樸 | h1 Struts+NGINX 衝突、h2 PostgreSQL 替身；attacker 無入口均有警示 | Horizon/AD 不可部署、Solr 無歸屬；仍規劃 RDP3389 | 24、49 |
| 9 審核規劃／IaC | 核准後生成被拒：h1 的 80 埠不受 Struts 元件支持 | 審核後只生成檢查報告，4 主機無可用映像、AD VM 後端未整合 | 25、26、50 |
| 10 部署／驗證／報告 | **BLOCKED**。啟動停用、0 紀錄；驗證停用、沒有報告 | 依 brief 不啟動部署；另確認驗證頁如實沒有結果 | 29、30、51、56、65、66 |

沒有取得成功部署後的報告，因此「真實重現／教學替代／部分／未驗證／無法重現」五類**最終驗證結果**的完整呈現與匯出，這輪無法驗收。分析頁的能力預估另在 58、61 留證，不冒充驗證報告。

## 原文及 expected.md 交叉對照

### Equifax（以原文為依據；expected 只作最後複查）

| 原文要點 | 系統輸出判讀 |
|---|---|
| 3 月掃描、找到脆弱 Struts、RCE 確認，沒有取資料 | a1–a3 有抓到；a3 名稱沒有補入「當時未取資料」，引句的已附內容也未包含這一句，不宜讓講師誤以為當時已外傳 |
| 5 月 13 日是 separate incident | a4 與 3 月 a3 以「時間先後」相連（59），沒有畫成沿用先前存取的依賴，正確 |
| 加密通道掩飾查詢／指令／取資料 | a5 有抓到，但錯當獨立軟體導致部署衝突；Struts 映像存在不能證明這個加密資料流成立 |
| 明文帳密、從 3 個資料庫擴至另外 48 個 | a6、a7 和引文正確；資產全部折疊為 h2，服務未抽到 DB 引擎待選／版本待補，後續無真實帳密與資料 fixture |
| 約 9,000 查詢、只有部分成功 | a8 有數量，原文引文保留「a portion」；行為名稱與主張欄沒有獨立標「部分成功」 |
| 小量分批、加密 web 外傳、76 天 | a9 有抓分批外傳；未規劃可驗證的接收端／批量資料與 TLS 條件 |
| OS／Struts 版本／CVE／DB 引擎／PoC 形式未知 | 沒憑空把 Solaris、ACIS、web shell、Wget、CVE-2017-5638 當原文；Struts 2.3.30 明示假設版本。缺失提問不足以補齊 DB、Java、憑證位置與外傳通道細節 |
| 憑證過期、缺乏分段、缺乏查詢頻率限制為背景，事後封鎖／下線為防守行為 | 5 項防守動作排除正確（58）；背景因素沒有變造為攻擊者關閉設備 |

expected.md 的核心行為與來源界線與先行判讀一致。其建議的 Struts→合成資料庫→隔離外傳是可行教學方向，但本輪產品 GUI 沒有完成這條鏈；未因 expected 說「適合完整重現」就給產品部署通過分。

### CISA

| 原文要點 | 系統輸出判讀 |
|---|---|
| Horizon Log4Shell／CVE-2021-44228 | 入口 a1 正確；CVE 有在原文引文/evidence-66（40），依賴軟體的 CVE 欄卻全為「—」（48） |
| Defender 排除 C:\、下載與自刪 | a2–a4 正確描述，程式引句因換行／格式沒有完全對上；不能等同沒有事實依據 |
| XMRig、RuntimeBroker 的「can create local account」能力、SYSTEM 排程 | 挖礦與排程有抓到；XMRig 安裝卻標 T1136.001 Local Account，未把「工具具有能力」與「這個安裝行為的技術」分清楚（40、47） |
| DefaultAccount/RDP、工具下載、Mimikatz、rogue domain admin | 主要行為存在；未把下載 PsExec 擴張成「已使用 PsExec」。取憑證與建帳號被合在一項，依賴不夠細 |
| Ngrok、Defender GUI、DC 列舉、改密碼 | 名稱與相關引句大致正確；自訂 Ngrok domain 未變成攻擊行為。沒有對應可部署的工具鏈 |
| LSASS dump 嘗試被額外 AV 擋下，主機未指明 | a16 保留 attempted，完整引文保留 stopped，沒有直接寫成功；但缺少清楚的「失敗／被阻擋」結果欄，目標卻歸至 h4，沒有清楚標出此位置為推定 |
| 關係證據 | 15 條關係全部「沒對上」，相同 file.zip 句在 evidence-6 為逐字、evidence-26 為 unresolved:empty（63、64）；原文正確關係因此無法形成可用鏈 |
| Windows/Horizon/AD 與替代的界線 | 拓樸與 IaC 清楚標不可部署（49、50）；分析能力預估 0/16（61），沒有把 Linux 當 Windows 真實重現；但使用者補充的 Solr 服務錯掛「原文」徽章（52） |

expected.md 另提 LDAP 回呼的時間歧義，系統沒有建立這個獨立行為，因此沒有觀察到錯排為「2 月入侵幾秒後回呼」，但此行為也沒有被完整納入流程。沒有因 standard answer 提到工具或 PoC 就在測試中自行執行。

## 問題清單（沒有觀察到 Critical）

### QA-I-R2-01 — High：協定被當成軟體，教學替代後無法產生 IaC

- 重現：匯入 Equifax 原文（單次分析或分階段＋複核）→執行依賴分析→兩個加密協定沒有 catalogue 元件→依提示以 NGINX、PostgreSQL 作教學替代→重新分析→產生拓樸、核准→生成 IaC。
- 實際：h1 同時宣告 Struts8080、NGINX80，卻只有 Struts 映像；`host h1 declares port 80, unsupported by vuln-struts2-s2-045`。依賴頁「尚未對應元件 0」不足以讓講師知道下一步仍不可部署。資料庫產品問題反而沒被正確提出。
- 影響：主要講師任務無法往部署與驗證前進。NGINX/PG 是測試者明確填的教學選擇，**不是**聲稱它們等價於原文協定；正常操作需要有能修正服務歸屬／映像衝突的路徑。
- 證據：[17](../evidence/qa-instructor-r2/17-equifax-dependency-analyzed.png)、[22](../evidence/qa-instructor-r2/22-equifax-dependency-reanalysis.png)、[24](../evidence/qa-instructor-r2/24-equifax-topology-plan.png)、[26](../evidence/qa-instructor-r2/26-equifax-iac.png)、[38](../evidence/qa-instructor-r2/38-equifax-staged-dependencies.png)。

### QA-I-R2-02 — High：自由補充中的教學限制變成「原文」服務

- 重現：匯入 CISA→Horizon/Log4j 接受未知→自由補充填入「Linux/Solr 只能作入口漏洞教學替代，不等於 Horizon、Windows Defender、RDP 或 AD 完整重現」→依賴分析。
- 實際：新增 Solr，來源「使用者」，依據卻為「✓ 原文」，沒有替代品標記；沒有歸屬主機，規劃也不能部署。原始 report.md 完全沒有 Solr。
- 影響：來源分級誤導講師，且文字限制被當成結構設定。USER_SUPPLIED／ASSUMED·SUBSTITUTED 應與 SOURCE_SUPPORTED 可區分。
- 證據：[補充原話](../evidence/qa-instructor-r2/54-cisa-negative-context.png)、[錯誤服務列](../evidence/qa-instructor-r2/52-cisa-solr-source-row.png)、[48](../evidence/qa-instructor-r2/48-cisa-dependencies.png)、[49](../evidence/qa-instructor-r2/49-cisa-topology.png)。

### QA-I-R2-03 — High：相同原文在行為中成立，在關係中全部失配

- 重現：匯入 CISA 原文、單次分析→分析結果「關係15」→比對右側 evidence-6 與 evidence-26。
- 實際：完全相同的 `file.zip contained XMRig cryptocurrency mining software and associated configuration files.`，前者逐字、第12段；後者沒對上、`unresolved:empty`。15 條關係均受影響；畫布 12 時序不計入鏈。
- 影響：正確的來源內容被判沒有證據，人工審查負擔大幅增加，後續規劃少用有效關係。不是「LLM 真的捏造了 15 句」。
- 證據：[41](../evidence/qa-instructor-r2/41-cisa-relations.png)、[47](../evidence/qa-instructor-r2/47-cisa-flow.png)、[關係列](../evidence/qa-instructor-r2/62-cisa-valid-text-unresolved-relation.png)、[逐字成功](../evidence/qa-instructor-r2/63-cisa-same-text-matched.png)、[同句失敗](../evidence/qa-instructor-r2/64-cisa-same-text-unresolved.png)。

### QA-I-R2-04 — High：「可重現」能力預估用映像存在替代了行為條件

- 重現：Equifax 完成依賴與拓樸（即使 IaC 失敗）→回分析頁→a5 加密通道送查詢與取 PII→看「可重現」滑鼠說明。
- 實際：標 5/9 可重現，a5 的理由只是 `Pinned catalogue component vuln-struts2-s2-045 is available for this service-level check`。沒有 TLS／查詢／PII 流程驗證，IaC 甚至不能建置。
- 影響：雖然頁面明說「不代表攻擊已執行或驗證通過」，依然把建置元件的能力推成能重現該行為；這個加密流程至多是尚未驗證／部分支持。
- 證據：[58](../evidence/qa-instructor-r2/58-equifax-excluded-actions.png)、[a5](../evidence/qa-instructor-r2/60-equifax-encrypted-repro-row.png)、`60-equifax-repro-titles.json`、[26](../evidence/qa-instructor-r2/26-equifax-iac.png)。

### QA-I-R2-05 — Medium：有「不啟用 RDP」補件選項，卻無法改變規劃

- 重現：CISA 缺失的 RDP 卡→用替代方案→填選項「不啟用 RDP，將此步驟標記未重現」→重新分析、規劃。
- 實際：仍會開 h1→h2 TCP3389；步驟沒有因該回答變成使用者指定的未重現。卡片誠實揭露「這個回答只保留為文字紀錄；後續…不一定會採用」，因此不是隱藏地宣稱已套用，但操作無法完成使用者表達的設定。
- 證據：[處理內容與限制](../evidence/qa-instructor-r2/55-cisa-rdp-resolution.png)、[49](../evidence/qa-instructor-r2/49-cisa-topology.png)。

### QA-I-R2-06 — Medium：分析的技術、結果、未知粒度不足

- 重現：檢視 Equifax a8、CISA a5／a16；對照原文與 expected。
- 實際：XMRig 安裝配成 Local Account 技術；9000 次查詢沒有「部分成功」結果欄；LSASS attempted 的完整引文雖有 stopped，但缺顯眼的失敗結果與目標未知。CVE-2021-44228 出現在原文證據，依賴軟體 CVE 卻全「—」。
- 影響：講師必須自行重建成功／失敗／只具備能力與未知主機，ATT&CK 徽章也可能被誤用。
- 證據：[07](../evidence/qa-instructor-r2/07-equifax-analysis-result.png)、[40](../evidence/qa-instructor-r2/40-cisa-analysis-result.png)、[47](../evidence/qa-instructor-r2/47-cisa-flow.png)、[48](../evidence/qa-instructor-r2/48-cisa-dependencies.png)。這不等於系統已把 LSASS 說成成功。

### QA-I-R2-07 — Low：阻擋理由與下一步提示不一致

- 重現：Equifax IaC 生成失敗→看各主機可部署欄、下方提示→前往部署及驗證頁。
- 實際：IaC 報錯但各主機可部署全「是」，仍提示「還沒有生成…按生成」；建議只查未對應服務，但本次所有服務都有對應、真正問題為多映像埠衝突。部署頁「未部署」，驗證頁稱 `error`。缺失頁部分內容退回英文原始欄位名稱，缺少下一步可執行修正。
- 證據：[18](../evidence/qa-instructor-r2/18-equifax-new-gaps.png)、[26](../evidence/qa-instructor-r2/26-equifax-iac.png)、[29](../evidence/qa-instructor-r2/29-equifax-deploy-blocked.png)、[30](../evidence/qa-instructor-r2/30-equifax-report-not-tested.png)。

## 評分（嚴格依本輪結果，總分 45/100）

| 項目 | 分數 | 扣分理由與證據 |
|---|---:|---|
| 情資擷取與證據正確性 | 14/20 | 核心行為多數正確且防守動作有排除；扣 2：使用者 Solr 升格原文（52）；扣 2：同句引用判定互斥（63–64）；扣 1：XMRig ATT&CK 配對（40）；扣 1：查詢部分成功／LSASS 失敗／能力缺少明確結果欄（07、40） |
| 攻擊鏈、相依性及缺失分析 | 9/20 | 3 月與5月分開正確；扣 5：把協定當服務、漏掉 DB 服務／版本結構（17、38）；扣 3：CISA 15 關係皆不可用、12 時序不計（41、47）；扣 3：缺失不足以支撐 Java/DB/憑證與外傳資料流（08、18、24） |
| 補件及場景編輯流程 | 6/10 | 逐項處理、未知與來源、另存版本可用；扣 2：RDP 回答只記錄不套用（55、49）；扣 1：服務無歸屬無 GUI 可修（48）；扣 1：多服務映像衝突缺修正入口（24–28） |
| IaC 正確性與部署可用性 | 5/20 | 拒絕不相容設定與 Horizon/AD 限制明示有價值；扣 12：指定主要情資實際不能生成／部署，複核模式未解根因（26、38、65）；扣 3：主機全可部署與整體生成失敗、錯誤修正指引落差（26） |
| 攻擊行為／PoC 驗證 | 0/15 | 扣 15：沒有可啟動環境，沒有實際攻擊行為、PoC、全鏈或驗證報告結果（29、30、51）；沒有用能力預估或 mock 給分 |
| GUI 可用性與操作直覺性 | 6/10 | 大部分站點與上一步／下一步清楚；扣 2：不可部署後沒有可執行的修正迴路（26、48）；扣 1：英文欄位與錯誤狀態不一致（18、30）；扣 1：「可重現」理由只在 hover 且語意過強（60） |
| 測試證據與可追溯性 | 5/5 | 真實瀏覽器、逐步 png/txt、完整 Playwright trace、來源雜湊、原文先行判讀與事後 expected 對照齊備；阻塞與未做項目明列 |

此分數是這個講師情境的可交付程度，不是把 Horizon 本身不適合 Docker 當程式錯誤扣分；主要部署分數失去是因為選定較適合容器教學的 Equifax 仍無法完成。

## 指令、輸出、證據與清理

- 啟動瀏覽器：
  ```sh
  export PATH="$HOME/.nvm/versions/node/v22.23.3/bin:$PATH"
  node reports/overnight/evidence/qa-instructor-r2/browser-driver.cjs
  ```
  實際以 PTY 執行，Playwright `chromium.launch({headless:true})` 成功；透過互動 driver 呼叫 GUI 的 role/label、檔案上傳、點擊、輸入與截圖，所有產品動作都經瀏覽器。driver 不載入產品程式碼、不直接打 API。
- 真實輸出逐步存在同名 `.txt`；重要失敗原話為 `host h1 declares port 80, unsupported by vuln-struts2-s2-045`（26）、`host h3 runtime=vm is not supported ...`（50）。`http-errors.log` 是瀏覽器被動收集的回應，含兩次 IaC 422；source/file、尚未產生 IaC/report 的 404 不單獨當作崩潰。
- `round2-trace.zip`：涵蓋兩份情資、補件、版本編輯與第三個分階段交叉測試，含螢幕與 DOM snapshots。以 Playwright trace viewer 開啟可查每一步。沒有 pageerror 事件；`pageerrors.log` 未建立，不能將 `cat` 找不到檔案誤算產品錯誤。
- 自動化曾誤用 button locator 找導覽 link，造成一個 30 秒等待，改按實際 link 後繼續。初次 driver 未使用 PTY 導致無法再輸入，重新以 PTY 啟動；這兩件為測試工具操作問題，**沒有列為產品缺陷**。
- 結束時 UI 確認三個自己建立的情境均未部署、部署紀錄 0（56、65、66），沒有可清除環境；沒有動別人的容器。第一個空白瀏覽器 driver 已送 SIGINT 結束（exit130），正式 driver 已儲存 trace 並關閉 Chromium。
- 未跑 Python／前端單元測試：此任務是獨立 GUI 驗收、沒有修改產品程式，沒有用測試套件替代 GUI 操作。
- 改動檔案僅本報告與 `reports/overnight/evidence/qa-instructor-r2/**`；沒有產品程式變更、沒有 git add/commit。commit：無，依指示留檔給 Lead 檢查。

## 未解問題與需決定事項

- 技術問題請 Lead 分派：QA-I-R2-01–04 優先，之後處理補件採用與錯誤導引；本測試者未修產品程式。
- 主要情資完整部署／PoC／報告與部署後清除流程尚未可驗收，修復後應使用新的獨立情境重跑，不把本輪結果改成 PASS。
- 需產品負責人決定：本輪沒有新增產品範圍的提案；沒有擅自要求第九模組或改變隔離邊界。Windows/Horizon/AD 的既有重現限制如需調整產品承諾，由 Lead 回報產品負責人。

### 交付檔案檢查

最終留存 74 張 PNG、69 份文字檔（包含輸入雜湊等）、`round2-trace.zip`（2,464 個 ZIP entry，完整性檢查無損壞）。報告內所有證據連結皆存在；分數加總 45。證據檔大小與 SHA-256 清單見 `manifest.json`。正式瀏覽器關閉輸出：`TRACE_SAVED_BROWSER_CLOSED`，exit0。最後 `git status --short` 僅顯示本報告與本人證據目錄為 untracked。
