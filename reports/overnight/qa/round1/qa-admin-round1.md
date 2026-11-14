實際模型：GPT-6.1-Sol（gpt-6.1-sol）；reasoning effort：Ultra；Fast：關閉（啟動參數 `--disable fast_mode --disable ultrafast_mode -c daybreak=false`，TUI 無 Fast 標示）。

# qa-admin 第一輪管理者驗收

**最終：54 / 100，PARTIAL。** 最小 synthetic NGINX 場景已真實部署、HTTP 200、重複 up、down、重建；原示範情資仍未完成部署。並行情境撞固定 42000 埠，留下 partial 環境。測試完成後，四組自建情境的容器／網路均已確認為零。僅測試與回報，未修改產品碼，未 add／commit。

測試時間：2026-11-15 約 02:16–02:35（Asia/Taipei）。真實 Playwright + Chromium 159.0.8154.6，1440×1000。對象為共享 QA 站台 http://127.0.0.1:5177，未重啟。自己的 worktree 基準 SHA 為 f545757a65828f93fdc4871f4e75e27bbc8e922e；共享站台的完整執行版本無畫面資訊可核實，不把本地 SHA 當成服務版本。

完整逐步操作：[steps-index.md](../evidence/qa-admin/round1/steps-index.md)（001–157，含填寫、無效操作、錯誤與截圖）；[Playwright trace](../evidence/qa-admin/round1/admin-trace.zip)。下方里程碑保留測試過程，當時的 BLOCKED 若有進展已逐次更新；最後判定、問題與評分見本文後段。

證據目錄：`reports/overnight/evidence/qa-admin/round1/`。
啟動證據：`runtime-launch.json`；已讀根目錄 AGENTS.md、COMMON.md、F-admin.md。

## 進度

- 已核實執行模型與 effort，待真實瀏覽器實測。

## 里程碑 1：情資至流程

- 真實 Chromium 159.0.8154.6 可用；已建立自己的情境 `admin-round1-demo-20261115` / `scn_737c76774c81`。
- 4 步驟、3 時序與 2 前置依賴對上示範原文；14 引文逐字成立。未憑空補 CVE 或 OS／軟體版本。確認兩條依賴並儲存為 v2。
- 發現 Medium：缺失卡「補充 → 接受未知 → 送出」會送空 `text`，後端 422 `string_too_short`；畫面仍是待補充。證據 `011-accept-unknown.png`、`012-submit-unknown.png`、`network.jsonl`。沒有填寫原因的必填提示。
- 軟體依賴頁顯示 HTTP/80、DB/5432 但兩項均未對應元件，將續測是否能在 GUI 完成部署。
- 此 worktree 不存在 `docs/approved-scope.md`；本任務仍依明確 brief 進行既有功能 QA，不開發功能。

## 里程碑 2：閘門與無效配置

- 未有拓樸／未核准時，GUI 啟動停用（018、021）。此處只驗證 GUI 閘門，未繞過介面直接呼叫 API。
- 拓樸生成後允許核准，但開通與必須阻擋路徑均為 0；明確的 HTTP/80、DB/5432 未綁定主機，規劃備註指出服務 association 未解析（020）。原文已明示 db 不可由 external 直達，未列阻擋探測。
- 核准後 IaC 拒絕未知映像（025），誠實顯示 unsupported，沒有假裝可部署。
- IaC 未生成時啟動按鈕仍可用；按下回報 `compose file has not been generated`，失敗紀錄存在（027）；沒有建立容器。
- 「接受未知」填入理由後成功（032，v3），但 placeholder 明寫「選填」，確認空字串 422 是前後端契約／UX 缺陷。
- 正在透過 GUI 自由補充提供明示的教學替代（NGINX／PostgreSQL），不把替代品視為事件原文。

## 里程碑 3：補件阻塞與第二組資料

- 自由補充明確提供 NGINX／PostgreSQL 教學替代及 host-service 對應（033、034），儲存為 v4。按重新分析依賴（036）仍是 2 項未對應，並由 2 主機變 3 主機，多出 `victim_web`（原本 `victim-web`）。已觀察 GUI 補件無法完成該部署配置，不直接修改資料庫或 API。
- 未部署時執行驗證，誠實回覆「尚未部署，請先部署」（038）。
- 為續測生命週期，新增明確標示 synthetic／USER_SUPPLIED 的 `admin-lifecycle-fixture.md`，使用目錄中的 NGINX／PostgreSQL 安全元件，不宣稱重現原事件。這是額外 QA 輸入，原始 fixture 沒改。
- 既有 Example Flow 只查看，未執行生成、補件、部署。步驟 040 誤開其他 QA 情境，僅閱讀，未變更；後續改用名稱定位列。
- 新建情境按鈕於已選情境時只開現有匯入內容，必須再按「匯入新報告」（046→050）；3 次自動化等待失敗（047–049）屬測試腳本依錯誤頁面狀態排程，不作產品 API 失敗計數，但入口標籤不符預期。

## 里程碑 4：第二組同樣阻塞

- 第二組 `admin-round1-lifecycle-lab` / `scn_fcb226d3bed7` 已成功匯入，明確來源寫 Linux、nginx 1.31.8、PostgreSQL 16.16、各 host-service association 與隔離規則。
- GUI 仍把 OS／版本顯示未知、服務無主機且未對應（058）；拓樸 0 開通／0 阻擋路徑（060）；核准後 IaC 同樣失敗，`web`、`db` 無安全映像（063）。
- High 阻塞：從兩組 GUI 匯入無法到真實部署，現階段不能驗收成功部署、實際健康、部署中重按、停止重建與跨情境實際隔離。這些不得記 PASS。
- 繼續測失敗後狀態／紀錄、重新規劃撤銷核准、重複失敗與無資源清除；不繞 GUI 建構假成功。

## 里程碑 5：錯誤回復新進展（更新前述 BLOCKED）

- 重新規劃會清除核准，部署重新停用（077、078），此 GUI 閘門 PASS。
- 修改攻擊目標並儲存 v3 時，仍顯示舊拓樸已核准／啟動可用（074、075）；未看到「規劃過期」提示。這僅證明 UI 版本關聯不清，不推論可繞過後端安全檢查。
- 無 Compose 時 down 與兩次 up 均回 503，真實失敗紀錄 3 筆；重新整理後歷史只有 failed，說明為「—」，點列也不能查看 stderr（069、070）。
- 第二組在針對 OS 卡補件，再次按重新分析後（084）**終於出現目錄元件**。前述「完全無法對應」是截至 063 的階段阻塞，不是最後定論。OS 仍顯未知，但服務增為 5，錯把 PostgreSQL 加到 web。
- 重新規劃有 3 允許／1 阻擋路徑（086），其中 attacker→web:5432 是誤推論；IaC 成功辨識元件及 digest，但安全驗證拒絕 nginx 主機宣告 5432（089）。
- 接續透過自己的場景編輯將 discovery 名稱改為不歧義的「Enumerate internal network from web foothold」，不修改產品碼或驗證結果，嘗試真正完成生命週期。

## 里程碑 6：服務推論修正後的殘留

- 將 discovery 名稱改成通用網路枚舉後，重新分析移除 web 主機的 PostgreSQL 顯示，但舊 `svc-oss-postgres-web` 仍留在服務清單，所在主機改成「—」（096）。
- 拓樸開通路徑由 3 條減為 2 條，符合人工更正，但 web 節點仍列 PostgreSQL:5432／multi-component 警告（098），呈現出殘留推論不一致。
- 因第二組受殘留服務影響，追加最小一主機 NGINX synthetic fixture（`admin-minimal-fixture.md`）作生命週期隔離測試，不把它當原 CTI 攻擊鏈驗收。

## 里程碑 7：最小 synthetic 實際部署成功

- 第三組 `admin-round1-minimal-lifecycle` / `scn_2acb1b9c902c`，一個 NGINX HTTP GET，按「重新分析依賴」後可生成一條 attacker→web:80 路徑（107、109）。原始服務仍未對應，但程式新增了推論服務。
- IaC 61 行成功生成（112）：NGINX、Alpine 都釘版本＋digest；non-root、read_only、cap_drop、no-new-privileges；external 和 scenario-internal 都 internal=true；另自動加 edge internal=false 與 127.0.0.1:42000→80，雖 QA 來源要求無 published ports。此與來源／拓樸的差異需明示，不直接推論能對外攻擊。
- GUI up 實際啟動 2 容器（114–115），操作中 up/down 都停用。Docker 唯讀對照兩個名稱／ID／running 與介面一致：NGINX `2c7958bd2697`、Alpine `9a26b6dae335`。
- Docker inspect 證據 `docker-minimal-inspect.json`、`networks-minimal-inspect.json`；正在續測重複 up／驗證／清除重建。此成功僅是最小 synthetic 環境，**不解除原情資重建阻塞**。

## 里程碑 8：重複部署、服務驗證與清除重建

- running 時再按 up，Compose 重用原兩個容器 ID，沒有新增重複容器（116、`docker-after-duplicate.jsonl`）。操作中兩個按鈕停用，沒有以 force 觸發第二個請求。
- 驗證實際取得 NGINX 1.31.8、Alpine 3.22.8、TCP CONNECTED、HTTP 200 與預設頁面（119、120、`minimal-validation-response.json`）。環境／無害行為 PASS，完整攻擊鏈 PARTIAL，動作 a1 明確 not executed，沒有把容器啟動當漏洞成功。
- down 移除兩容器及三個情境網路，Docker `ps -a`／network ls 為空；GUI not_created（123）。再次 down 可成功，留下 stopped 紀錄（124）。沒有獨立「停止但保留容器」按鈕；GUI 的關閉就是清除。
- 清除後重新驗證回「尚未部署」但保留舊報告與舊時間戳（126），應更清楚標成歷史結果。
- 清除後 up 重建成功，容器 ID 更換為 `ca75a5f279fa`／`eef99893b2d1`，映像 digest 與網路名稱相同。證據 `docker-recreated-inspect.json`、`docker-lifecycle-observations.json`，首頁再次顯示容器執行中（130）。
- 正在以相同 synthetic fixture 建第二個並行情境，測主機埠衝突與情境間資源隔離，之後會從介面清除兩組。

## 里程碑 9：並行情境埠衝突（High）

- 第四組 `admin-round1-isolation-peer` / `scn_ba5daad2f2ab` 使用同一 minimal fixture；IaC 仍固定配置 127.0.0.1:42000，與執行中的第三組相同（143）。
- GUI 沒有資源／埠預檢或可調埠欄位，up 先建立 3 網路與 2 容器，再因 `Bind for 127.0.0.1:42000 failed: port is already allocated` 失敗（147）。留下 h1=created、h2=running，GUI 自動更新為 partial／healthy=否，與 Docker 一致。
- 失敗回饋提供真 stderr，但整份細節重複展開多次，將目前狀態推到很下面；部署歷史說明仍「—」。
- 證據 `143-peer-iac.png`、`147-peer-final-start-state.png`、`docker-peer-concurrent.jsonl`、`docker-parallel-inspect.json`、`networks-parallel-inspect.json`。
- 網路命名與 endpoints 分屬各自情境，沒有共用外部／內部 network ID；但這只是結構比對，未執行跨情境 TCP 攻擊測試，不能宣稱完整流量隔離 PASS。
- 即將驗證 partial 環境是否如實失敗，再從 GUI 清除 peer，確認第三組不受影響並最後清除。

## 最終清理與驗收矩陣

- 並行失敗的 peer 驗證被拒絕為「尚未部署」（149），未假報 PASS。GUI down 成功清除該 partial 環境（152）；另一組原容器 ID 仍 running（155、docker-surviving-minimal.jsonl），確認清除只影響選定情境。
- 最後再從 GUI down 第三組（156–157）。四個自建 ID 各檢查 ps -a 與 network ls，共 8 次，returncode 全 0、stdout 全空，`cleanup-verification.json` 的 `all_clear: true`。場景資料及紀錄保留供 Lead 查證，沒有刪除情境。

| 實測項目 | 最終判定 | 實際結果／證據（檔名均在 round1 證據目錄） |
|---|---|---|
| 原短文步驟、關係、引文 | PASS（僅此短文） | 四步驟、3 時序、2 依賴；獨立 substring 檢查14/14成立，quote-independent-check.json |
| 原文未知不偽造 CVE／版本 | PASS | 顯示未知，未憑空補 CVE |
| 缺失分析完整性 | FAIL | 原示範缺 CVE／軟體版本卻未問；synthetic 明寫 Linux 卻稱來源未提供（079） |
| 補件、接受未知 | PARTIAL | 選填理由留白422；填理由成功，自由補充未直接解決部署（012、032、036） |
| 場景編輯與版本儲存 | PASS（功能） | 確認依賴、改目標／名稱、儲存新版本成功（014–015、073–074、093） |
| 規劃更新的可理解性 | PARTIAL | 改流程仍顯示舊拓樸已核准，需自行重分析／重規劃（075、097） |
| 未核准 GUI 部署閘門 | PASS | 未核准 up disabled，重新規劃撤銷核准（018、021、078）；未繞 GUI 測後端授權 |
| 未知映像／不相容埠阻擋 | PASS | IaC 拒絕無映像及 nginx 配5432（025、063、089） |
| 原示範 CTI 成功部署 | BLOCKED | association／映像未對應，原事件未重現 |
| 部署前資源檢查、參數 | FAIL／NOT_TESTED | 未見 CPU、記憶體、磁碟、Docker readiness 或主機埠預檢，也無埠／映像可調欄位；實際建立容器後撞埠 |
| 版本釘選與限制 | PASS（可見設定） | NGINX／Alpine tag+digest、non-root、read_only、cap_drop、no-new-privileges（112、inspect） |
| 最小 synthetic up／狀態 | PASS | 真實兩容器 running，UI 名稱／ID 與 Docker 相符（115） |
| 部署中重按 | PASS（同頁防重） | 操作中 up/down disabled（114、116、122）；未 force 點 disabled，未測跨分頁競態 |
| 已執行時重複 up | PASS | 沿用原兩個容器 ID，無重複容器（116、docker-after-duplicate.jsonl） |
| 服務健康 | PARTIAL | UI healthy，但 Docker 無 Healthcheck／Health；後續才以驗證證實 HTTP |
| 無害服務驗證 | PASS | TCP CONNECTED、HTTP200、NGINX1.31.8、Alpine3.22.8（119–120） |
| 原情資漏洞／完整攻擊鏈 | NOT_TESTED／BLOCKED | 無真 exploit；驗證如實標 PARTIAL、動作 not executed |
| down／重複 down／清除重建 | PASS | 移除容器與三網路後可重建，新ID／同digest（123–130、docker-lifecycle-observations.json） |
| 雙情境並行 | FAIL | 固定127.0.0.1:42000衝突，留下h1=created、h2=running（147） |
| 部分失敗狀態對照 | PASS | GUI partial／healthy=否，與Docker一致（147、150） |
| 失敗紀錄診斷 | PARTIAL | 當下有stderr，回頁歷史說明「—」，不可展開（069、070、150） |
| 情境網路結構隔離 | PASS（只限結構） | 不同network ID／endpoint；跨情境實際TCP流量隔離 NOT_TESTED（parallel-observations.json） |
| 清peer不影響另一組 | PASS | peer歸零、另一組原ID仍running（152、155） |
| 最終清理 | PASS | 四組自建ID容器／網路全空（157、cleanup-verification.json） |

## 問題清單（最後判定）

### ADM-01 — High：並行情境固定使用同一主機埠，無事前預檢

重現：以 admin-minimal-fixture.md 建第一個情境，重新分析依賴→產生拓樸→核准→生成IaC→up；再用相同fixture建第二個情境並up。兩份IaC都配置127.0.0.1:42000→80。第二次503，`Bind for 127.0.0.1:42000 failed: port is already allocated`。失敗前已建立三網路與兩容器，須手動down。GUI沒有主機埠預檢或可修改欄位。

證據：112-minimal-iac.png、143-peer-iac.png、147-peer-final-start-state.png、peer-port-conflict-response.json、docker-parallel-inspect.json。

### ADM-02 — High：原文主機／服務／版本沒有形成可部署資料

重現：匯入原示範→確認兩依賴→規劃，開通／阻擋均0。自由補充明寫host-service association，重新分析仍未對應，且多出victim_web，與victim-web並存。第二份synthetic明寫host、service、Linux、版本與catalogue ID，初次同樣未對應。須多次重分析與人工改步驟才產生推論服務；原文服務仍未對應，GUI未告知有效的修正方式。這是觀察到的資料落差，不推測確切程式根因。

證據：017-dependencies.png、020-generate-topology.png、025-generate-iac.png、036-reanalyze-deps.png、058-lifecycle-deps.png、063-lifecycle-iac.png。

### ADM-03 — High：依動作文字誤掛服務，修正後殘留

重現：synthetic三步lab→把collection目標改db→重新分析，系統將「從web發現PostgreSQL」推成web也裝PostgreSQL，規劃多開attacker→web:5432。IaC正確拒絕nginx主機5432，但GUI沒有服務刪除／重新映射入口。把discovery名稱改為一般網路枚舉並重分析，主機欄已只剩NGINX，舊svc-oss-postgres-web仍在服務清單；重規劃節點仍列PostgreSQL:5432與multi-component警告。

證據：084-known-os-reanalyze.png、086-plan-after-dependency-retry.png、089-iac-after-dependency-retry.png、096-reanalyze-neutral-discovery.png、098-replan-neutral-discovery.png。安全阻擋有效，配置修復仍受阻。

### ADM-04 — Medium：缺失問題與引文本身矛盾，漏掉關鍵未知

重現：匯入synthetic lab→缺失補充。來源明寫Linux OS，卡片卻稱「來源未提供作業系統／報告沒有寫」，同時引用含Linux那句。原示範明說CVE／軟體版本未識別，6個問題只有OS／OS build／網路，沒有服務或CVE問題。確切OS build的確沒寫，不將那個問題誤報為錯。

證據：009-missing.png、079-lifecycle-source-versus-missing.png。

### ADM-05 — Medium：「接受未知」的選填理由實際必填

重現：補充→接受未知→不填理由→送出。按鈕可用，422 `text String should have at least 1 character`；placeholder卻是「（選填）備註為何可以不補」。填理由後成功。

證據：011-accept-unknown.png、012-submit-unknown.png、030-unknown-with-reason-mode.json、032-unknown-with-reason-submit.png。

### ADM-06 — Medium：錯誤資訊當下過量、事後不足

重現：並行up撞埠。stderr與nested deployment_record重複展開多次，長行水平溢出，根因在行尾、目前狀態推到下方。返回部署頁後，歷史只有failed／說明「—」，點列無細節。缺Compose失敗同樣不能從歷史看stderr。

證據：069-failure-history-reload.png、070-history-row-no-detail.png、147-peer-final-start-state.png、150-peer-cleanup-nav.png。

### ADM-07 — Medium：核准、健康與歷史報告的適用範圍不清

重現A：核准後改action目標、存新版本，仍顯示舊拓樸已核准且up可按，沒有規劃需更新提示；只有重新規劃才清核准（075→078）。此僅證明UI版本關聯不清，未證實後端審核可繞過。

重現B：兩容器無Docker healthcheck卻顯示healthy；應說明僅以running判斷，服務驗證另看報告（115、docker-lifecycle-observations.json）。清除後舊報告仍顯示PASS／舊時間，重新驗證顯示「尚未部署」後，下方仍保留舊結果，欠明確歷史標記（126）；本輪未把舊報告視為新成功。

### ADM-08 — Medium：拓樸與隔離說明未完整呈現實際邊界

重現：minimal synthetic明說不要求published ports；拓樸只畫external／scenario-internal，IaC卻自動增加edge internal=false與loopback42000。Docker inspect確認web接edge且綁127.0.0.1:42000，部署回應仍expose=internal。這是可審核性／邊界說明缺陷；未測公網egress，不宣稱已發生外部存取，不自行改隔離界線。

證據：109-minimal-plan.png、112-minimal-iac.png、minimal-docker-compose.yml、docker-minimal-inspect.json、networks-minimal-inspect.json。

### ADM-09 — Low：「＋新建情境」先顯示既有原文

重現：已選情境→首頁「＋新建情境」→現有情境匯入原文，須再按「匯入新報告」才有表單。沒有覆寫，保護有說明，但入口多一步且名稱不符預期。證據：046-new-lifecycle-import.png→050-new-report-required.png。

## 嚴格評分

| 項目 | 得分 | 扣分理由 |
|---|---:|---|
| 情資擷取與證據正確性 | 15 / 20 | 原短文14引文、四步正確且不偽造CVE；明寫Linux／版本／association未落地，未知問題不完整 |
| 攻擊鏈、相依性及缺失分析 | 8 / 20 | 原依賴可確認；零路徑、錯掛DB、殘留推論及關鍵缺失使原鏈不可部署 |
| 補件及場景編輯流程 | 5 / 10 | 可改目標與存版本；接受未知契約錯誤，補件後缺有效的元件映射／更新指引 |
| IaC正確性與部署可用性 | 11 / 20 | 釘版本、限制與安全拒絕有效，最小lab真up/down/recreate；原CTI阻塞、並行撞埠、無預檢、邊界說明落差 |
| 攻擊行為／PoC驗證 | 6 / 15 | 真TCP／HTTP／版本及整鏈PARTIAL誠實；原漏洞與collection未測，健康語意不足 |
| GUI可用性與操作直覺性 | 4 / 10 | 可操作且現況更新；錯誤溢出／歷史缺診斷、參數不可改、過期資訊不清、新建多一步 |
| 測試證據與可追溯性 | 5 / 5 | 每步截圖、trace、瀏覽器回應、原文hash與獨立比對、Docker及清理證據 |
| **總分** | **54 / 100** | synthetic成功不抵銷原CTI阻塞，未測項不計PASS |

## 來源、指令、實際輸出與限制

SOURCE_SUPPORTED：原短文支持4步、HTTP80、web→db5432、external不直達db及collection兩個前置。USER_SUPPLIED：自己的補充與兩份synthetic QA fixture，僅為測試輸入，不是事件事實。ASSUMED·SUBSTITUTED：教學NGINX／PostgreSQL／Alpine與程式推論服務。EXTERNAL_ENRICHMENT：本輪未做。BLOCKED·UNKNOWN：原CVE／軟體版本／OS版本、真實exploit與collection。沒有用mock冒充部署或驗證。

執行：`/home/tyc4d/.nvm/versions/node/v22.23.3/bin/node reports/overnight/evidence/qa-admin/round1/browser-driver.cjs`（PTY），輸出`ready:true,browser:159.0.8154.6`。每個JSON action是Playwright操作；network.jsonl僅被動攔錄瀏覽器回應，未直接打API來替代GUI。

原文比對指令使用主庫venv Python逐句檢查原始字串，實際輸出：`Original quotes exact substring: 14 / 14`；證據為original-analysis-response.json、quote-independent-check.json、fixture-sha256.txt、original-demo-intrusion.md。

Docker僅唯讀：`docker ps -a --filter name=cr-demo-<自建ID> --format '{{json .}}'`、`docker inspect cr-demo-<自建ID>-h1 ...-h2`、`docker network ls/inspect`。建立／移除均走GUI。摘要docker-lifecycle-observations.json及parallel-observations.json可對回原始inspect。最終cleanup-verification.json含8個完整指令、returncode、stdout／stderr，全部成功且無資源。

Trace ZIP檢查實際輸出：`trace zip entries 4376 bad entry None`。第一次在Playwright尚未寫完時檢查得到BadZipFile，待closed後重查通過；此為測試收尾時序，非產品錯誤。

未跑pytest／前端build：獨立黑箱GUI QA且無產品碼變更，不把未跑的測試列PASS。未做真漏洞利用、跨情境TCP、負載／CPU記憶體耗盡、VM／KVM部署，也未強制突破disabled按鈕或用API建立成功環境。整個過程未掃公網、未點驗證頁NGINX回應中的外部連結、未動其他專案容器或服務。

腳本無效操作保留並區分：003 selector未匹配省略type屬性的textbox；016匹配兩個連結；047–049在既有原文頁嘗試填新建表單；094在inspector開啟時找不到下一步。均按可見畫面修正，未當成產品API失敗。

## 改動、commit、未解問題與產品決定

產品碼與共用檔變更：**無**。commit：**無**，未執行add／commit。只新增自己的`reports/overnight/worker-reports/qa-admin*.md`與`reports/overnight/evidence/qa-admin/round1/**`：driver、兩份synthetic輸入、原來源副本、截圖、JSON／JSONL、trace、摘要及索引。

待Lead優先修ADM-01並行埠／預檢，以及ADM-02／03服務映射與殘留清理，再用原示範情資重跑部署和真正的阻擋路徑驗證。本輪未證實原事件可重現。

需產品負責人決定事項：沒有新增功能或方向提案。`docs/approved-scope.md`在此worktree不存在（實際讀取No such file or directory），請Lead校正文檔位置；本輪依明確brief僅做既有功能QA。

收尾證據檢查：157個GUI步驟、157張截圖（含6個腳本無效操作的錯誤截圖），報告／索引連結無缺檔，trace ZIP無壞檔；詳evidence-verification.json。trace寫完後已關瀏覽器。最初不帶PTY的driver因stdin先關閉而未操作頁面，收尾時核對自己的工作路徑與完整argv後只終止該孤立driver；drivers-after-cleanup.json為空陣列，沒有保留自己的測試程序。
