實際模型：gpt-6.1-sol；reasoning effort：ultra；Fast／Ultrafast：關閉（執行時 turn_context 與 hc 啟動參數確認）。

# qa-instructor 第一輪獨立 GUI 驗收

結果：**43 / 100；整體 PARTIAL，部署與 PoC BLOCKED／NOT_TESTED。** 2026-11-15 約 02:17–02:27（Asia/Taipei）完成真實 Chromium GUI 第一輪。沒有任何成功部署或攻擊重現。本報告完成於同日；只新增報告與證據，未修改產品程式碼、未提交、未啟動其他 Agent。

- 工作目錄：`/home/tyc4d/cr-project/.worktrees/qa-instructor`
- 站台：`http://127.0.0.1:5177`，共用 QA 站台，未重啟。
- 情資：`/home/tyc4d/cr-project/fixtures/sample-scenarios/cisa-aa22-320a.md`
- 證據：`reports/overnight/evidence/qa-instructor/round1/`
- 設定證據：`runtime-hc.json`；session `01a1db46-2133-7921-aa23-cfc6140faf83` 的 turn_context 為 `model=gpt-6.1-sol, effort=ultra`。
- 初始 Git 工作目錄乾淨；不執行 git add／commit。

## 執行邊界與基線

- 本 worktree HEAD：`f545757a65828f93fdc4871f4e75e27bbc8e922e`；實際受測為 Lead 維護的共用 main 站台，不能以 worktree HEAD 當成站台版本。
- `docs/approved-scope.md` 在此 worktree 不存在；依明確指派只測既有流程，未增加功能。
- 未讀取前端原始碼找入口。以 Chromium 畫面、可見文字及 DOM 表單標籤辨識操作。
- 操作開始：2026-11-15 約 02:17 Asia/Taipei；事件 log 使用 UTC。
- 來源分級：指定 CTI 摘錄是 SOURCE_SUPPORTED 的比對依據；測試者補件另標 USER_SUPPLIED；部署替代不得當作原事件證據。未補外部情資（無 EXTERNAL_ENRICHMENT）。

## 操作紀錄

| 步驟 | 實際操作與結果 | 證據 |
|---|---|---|
| 1 | Chromium 開啟首頁，無登入畫面；已存在的兩個情境不操作。 | `01-entry.png/.txt` |
| 2 | 點「＋ 新建情境」，看到上傳／貼上、格式與分析方式。 | `03-import-form.png/.txt` |
| 3 | 輸入 `qa-instructor round1 CISA AA22-320A`，選擇指定 `.md`；顯示已載入 6,066 字元、自動選 Markdown。保留預設「單次分析」。 | `04-cti-uploaded.png/.txt`、`input-cti.md`、`input-sha256.txt` |
| 4 | 點「開始分析」，顯示正在處理、請勿關閉頁面及已過秒數。 | `05-analysis-started.png/.txt` |
| 5 | 等待分析完成，建立情境 `scn_05880c494a13` v1：25 行為、20 關係、39 引句。逐條人工對照指定 CTI，詳見 `cti-audit.md`。 | `06-analysis-outcome` |
| 6 | 點 LSASS 行為，右側篩選到 E28，原文保留「遭額外防毒攔阻」。 | `07-lsass-detail`、`07-lsass-viewport` |
| 7 | 切「關係 20」：全部推論／LLM、理由空、未附依據。 | `08-analysis-relations`、`08-relations-viewport` |
| 8 | 點攻擊流程，檢視畫布：24 待處理、3 未確認依賴、17 條無引文先後、4 孤立節點。沒有按任何關係確認。 | `09-flow-initial` |
| 9 | 點缺失補充：導覽 18，頁內待補 17；原文與補件雙欄可見。 | `10-gaps-initial` |
| 10 | 第一張 OS 卡選 Windows Server 2022，自動帶入「用替代方案」。填寫明確教學替代、不聲稱來源證實，送出成功建立 v2。 | `11-os-option`、`12-os-substitution-filled`、`13-os-substitution-submitted` |
| 11 | OS build 卡點補充→接受未知→留白送出。備註明寫選填但回 422。 | `14-accept-unknown-version`、`15-unknown-version-submitted` |
| 12 | 選外連「封鎖對外連線（隔離預設）」；取消前張失敗表單，送出外連補件成功 v3。 | `16-egress-block-option`、`17-egress-submitted` |
| 13 | OS build 再選接受未知，填 BLOCKED·UNKNOWN 備註後送出成功 v4。 | `18-unknown-with-note`、`19-unknown-with-note-submitted` |
| 14 | 自由補充教學規格：只用本地隔離、分開 VDI-KMS／DC／其他主機、保留 LSASS 失敗；成功 v5。沒有附件上傳入口，選擇文字補件已完成要求中的「文字或附件」。 | `20-free-supplement-filled`、`21-free-supplement-submitted` |
| 15 | 回畫布點 a25，編輯名稱／說明明示 LSASS 被攔阻，填版本備註、儲存 v6。畫布提示「原文・已編輯」、屬性來源「使用者」。 | `22-flow-after-supplements`–`25-lsass-saved` |
| 16 | 嘗試點左側主機名稱以找場景規格編輯，沒有開啟主機面板，a25 面板維持原樣；目前未找到可填 OS／VM image／CPU/RAM 的可見入口。**場景規格只成功文字補充，結構化修改 PARTIAL。** | `26-host-select-attempt` |
| 17 | 返回分析／關係：20 條未修改關係全部變「使用者」來源，仍為無依據推論；畫布警示已由 24 減到 7。 | `27-relations-after-behavior-save` |
| 18 | 初進依賴頁僅 1 個 absent service；點重新分析才增加 Horizon、Log4Shell、domain controller。OS 仍未知，工具未有安裝對應。 | `28-software-dependencies`、`29-dependencies-reanalyzed` |
| 19 | 進拓樸→產生規劃：加入 attacker、沒有開通連線、阻擋 attacker→合併主機 389；拒絕所有 ACL。 | `30-topology-initial`、`31-topology-generated` |
| 20 | 進 IaC→生成：失敗，deployable=false，Horizon／AD 無映像、VM backend 未設定。 | `32-iac-before-approval`、`33-iac-generation-attempt` |
| 21 | 進部署：up disabled、無容器；回拓樸核准以測試後續拒絕路徑，自動導向 IaC；重新生成仍失敗。 | `34-deployment-before-approval`–`36-iac-after-approval` |
| 22 | 核准後 up enabled。第一次點擊觸發原生確認，被 Playwright 預設取消，沒有請求；加 dialog handler 後再次點擊，確認「本機隔離環境」啟動。真正請求失敗，returncode=2、無 compose；部署記錄 id 26=failed。 | `37-deploy-after-approval`、`38-deploy-up-result`、`39-deploy-confirmed-result`、`browser-events.jsonl` 的 dialog |
| 23 | 進驗證→執行驗證：回「尚未部署，請先部署」，無驗證報告。 | `40-verification-initial`、`41-verification-attempt` |
| 24 | 返回缺失→在原文中定位，正確高亮第 25 行原始句（含 ATT&CK 標籤）。重新分析新增缺失後仍保留已補文字。 | `42-gaps-after-reanalysis`、`43-source-location` |
| 25 | 回部署→關閉 down，接受原生清除確認；因未生成 compose 回 returncode=2，down 記錄 id 30=failed。無已建立容器。 | `44-cleanup-before-down`、`45-cleanup-down-result` |
| 26 | 重新規劃拓樸撤回測試用核准；回部署立即更新，顯示待核准、up disabled、無容器。精確標籤查詢容器／網路／volume 都空。 | `46-topology-approval-reset`、`47-final-deployment-state`、`own-project-*.txt` |
| 27 | 停止 trace、關閉 Chromium，檢查 trace ZIP 完整性。 | `instructor-round1-trace.zip`、`verification-summary.json` |

測試工具紀錄：最初非 TTY session 的 stdin 無法續寫，重新以 TTY 啟動；第一份 `02-new-scenario.png` 截於頁面轉場，畫面為空，已補 `03` 穩定截圖。一次腳本變數作用域錯誤發生在點擊後的截圖呼叫，點擊成功，已補 `05` 截圖；這些是 QA 工具問題，不算產品缺陷。

## 主要已確認發現

- High：僅編輯 a25 的名稱、說明並儲存為 v6，沒有操作任何關係／確認按鈕，原本全部 20 條關係的來源卻從 LLM 變成「使用者」。同時畫布待處理由 24 降到 7（17 條無引文先後不再報警）。分析頁仍顯示這些關係「推論補全，未附推論依據」，可追溯性與設計檢查不一致。重現：初始畫布→點 a25→補上原文已明示的 LSASS 被攔阻名稱及說明→儲存新版本→分析結果／關係；沒有按確認所有依賴。證據 `22-flow-after-supplements`、`23-lsass-edit-panel`、`24-lsass-edited-unsaved`、`25-lsass-saved`、`27-relations-after-behavior-save`。
- High：來源清楚提及 VDI-KMS、domain controller 與多台其他主機，分析卻只建立 Horizon 與 `unspecified hosts including VDI-KMS host, domain controller, and multiple other hosts` 兩個資產。步驟 14–25 在分析表顯示「未指明的主機（步驟 N）」；畫布將這些不同角色都指向同一資產。證據 `06-analysis-outcome`、`09-flow-initial`。
- Medium：20 條關係全是推論，理由皆 `—`，顯示「推論補全，未附推論依據」。原文已有明確前後語（When executed、Using the newly created account、Once ...）仍未引用支持；畫布因此有 24 個待處理、17 條先後不計入攻擊鏈，4 節點完全孤立。標示本身誠實，但需要大量人工處理。證據 `08-analysis-relations`、`09-flow-initial`。
- Medium：缺失卡片「補充」→「接受未知」，備註欄 placeholder 為 `（選填）備註為何可以不補`。留白按送出卻失敗，畫面顯示 `string_too_short / body.text / String should have at least 1 character`，HTTP 422。加備註後成功建立 v4。證據 `14-accept-unknown-version`、`15-unknown-version-submitted`、`18-unknown-with-note`、`19-unknown-with-note-submitted`。已向 Lead 回報並更正初次口述誤稱「沒有文字欄」；實際是有欄位但標示選填。
- Low：缺失導覽數量比缺失頁待補數持續多 1（初始導覽 18／卡片 17；補件後導覽 15／待補 14）。證據 `10-gaps-initial`、`21-free-supplement-submitted`。待確認是否未說明另一種缺失計數。

補件實際結果：Windows Server 2022 Evaluation 的隔離教學替代（不冒充來源事實）→v2；封鎖外連預設→v3；原事件 OS build 接受未知並加備註→v4；自由補充（角色分開、只用本地環境、LSASS 原文被攔阻）→v5。補充清單都標示「使用者」。證據 `12`–`21`。

## 部署路徑目前結果

- 本輪情境 ID：`scn_05880c494a13`，容器專案前綴 `cr-demo-scn_05880c494a13`。
- 初次進依賴頁只顯示 `Unspecified service (absent)`，需手動「重新分析依賴」才增加 Horizon、Log4Shell、domain controller；仍無 XMRig／Mimikatz／Ngrok／PsExec 的安裝對應。主機 OS 依然未知，補件未變成可部署主機設定。
- 產生拓樸：Horizon、合併主機、程式加入的 attacker。開通連線 0；要求阻擋 attacker→合併主機 TCP 389；ACL 拒絕所有。規劃文字明示未知服務埠保持不通。
- IaC 產生失敗：Horizon 與合併主機沒有安全本地映像；VM 後端未安裝／設定，且缺 OS release、image ref/digest、CPU、RAM、disk。`deployable=否`。錯誤報告有列出實際 networks internal=true（包括計畫中標可對外的 external 網路），未放寬隔離。
- 拓樸未核准時部署 up 按鈕確實 disabled，沒有容器、部署紀錄為 0，state=error，原因 compose 尚未產生。
- 為測試核准後的錯誤路徑，從介面點「核准並繼續」；只開放測試繼續，**不代表 QA 接受此攻擊鏈／重建正確**。未新增任何開通連線。核准後重試 IaC 仍失敗。
- 證據 `28-software-dependencies`–`37-deploy-after-approval`；拒絕啟動、驗證入口與清理的最終結果見 `39`–`47` 及下方清理紀錄。

## 問題清單與重現

以下證據路徑全部相對於 `reports/overnight/evidence/qa-instructor/round1/`；表內無副檔名者同時有 `.png` 截圖與 `.txt` 原始畫面文字。未發現可證明的 Critical 問題。

| ID／嚴重度 | 問題、重現步驟及實際影響 | 截圖 |
|---|---|---|
| EI-01 **High** | 初始分析→攻擊流程→僅編輯 a25 名稱／說明→儲存→分析結果／關係。未碰任何關係，20 條來源全從 LLM 改成使用者，17 條無引文警示消失。使用者不曾做的判斷被歸到使用者名下，設計檢查因此放寬。 | `22-flow-after-supplements.png`、`24-lsass-edited-unsaved.png`、`25-lsass-saved.png`、`27-relations-after-behavior-save.png` |
| EI-02 **High** | 匯入指定 CTI→檢查行為 14–25／攻擊流程／拓樸。VDI-KMS、DC、多台主機被合成 `unknown` 一個資產，分析表甚至顯示每步「未指明主機」。原文未知個別身份不等於角色相同，橫向移動與 AD 路徑無法對照。 | `06-analysis-outcome.png`、`09-flow-initial.png`、`31-topology-generated.png` |
| EI-03 **High；環境／能力阻塞** | 依賴重新分析→產生拓樸→生成 IaC（核准前後各一次）。Horizon 無安全本地映像，AD VM backend 未配置且 guest 欄位全缺，deployable=false。核准後確認啟動仍無 compose，驗證拒絕。本案例無法走到可部署、可驗證的教學環境。此為可用性缺口，阻擋本身是正確的。 | `33-iac-generation-attempt.png`、`36-iac-after-approval.png`、`39-deploy-confirmed-result.png`、`41-verification-attempt.png` |
| EI-04 **Medium** | OS build 卡→補充→接受未知→備註留白→送出。標為選填的文字被 API 要求至少 1 字，回 422；填備註才成功。 | `14-accept-unknown-version.png`、`15-unknown-version-submitted.png`、`19-unknown-with-note-submitted.png` |
| EI-05 **Medium** | OS 補件填 Windows Server 2022 教學替代並送出，缺失卡消失、v2 成功；之後在 v6 依賴頁（含重新分析）Horizon OS 仍未知。自由補件角色拆分也僅保存在補充清單。UI 沒說如何把已收錄答案套用成主機／VM 規格；本輪未能完成結構化場景規格修改。 | `13-os-substitution-submitted.png`、`21-free-supplement-submitted.png`、`26-host-select-attempt.png`、`29-dependencies-reanalyzed.png` |
| EI-06 **Medium** | 初進依賴頁顯示 1 個 `Unspecified service (absent)` 且名稱是「重新分析依賴」，不易察覺尚未有效分析；點擊才出現 3 個關鍵產品／角色，但來源明示的 XMRig、Mimikatz、Ngrok、PsExec 仍無元件安裝對應。缺失頁有問工具版本，沒有可驗證的下游對應。 | `28-software-dependencies.png`、`29-dependencies-reanalyzed.png` |
| EI-07 **Medium** | 匯入→關係 tab／畫布：20 關係全是推論、沒有理由與引文。連原文明示新帳號→RDP、腳本執行→下載刪除等也未留下依據；4、5、6、7 孤立。這是分析品質問題，介面確實有警告，不算假冒來源支持。 | `08-analysis-relations.png`、`09-flow-initial.png` |
| EI-08 **Medium** | 匯入→分析結果，39/39 都標逐字；逐句與上傳原文比較，29 句逐字、10 句移除 ATT&CK 標籤。正規化後全部語意／文字可對上，沒有證據支持「引句造假」，但 literal 標示不正確。 | `06-analysis-outcome.png`、`43-source-location.png`；計算證據 `quote-comparison.json` |
| EI-09 **Low** | 缺失導覽數字持續比頁內待補數多 1（18 vs17、15 vs14），無計數範圍說明；第一次使用者無法判斷是否漏看一項。可能來自不同範圍，本輪未猜測根因。 | `10-gaps-initial.png`、`21-free-supplement-submitted.png`、`42-gaps-after-reanalysis.png` |
| EI-10 **Low** | IaC 錯誤以多層原始英文欄位／表格直接鋪出，guest 欄窄到逐字換行；部署清單的失敗原因欄只顯示 `—`，需回上方原始結果找原因。缺少能完成設定的直接入口。 | `33-iac-generation-attempt.png`、`39-deploy-confirmed-result.png`、`47-final-deployment-state.png` |
| EI-11 **Low** | IaC 不存在但核准後 up 可按；未部署時執行驗證可按，沒有資源時 down 可按。各次 API 均正確拒絕，但用戶需經失敗回饋才理解下一步，空環境 down 又被記一次 failed。 | `37-deploy-after-approval.png`、`40-verification-initial.png`、`41-verification-attempt.png`、`45-cleanup-down-result.png` |

## 嚴格評分

這是本次指定 CTI 的實際教學流程評分，不是全產品覆蓋率，也不因頁面存在就給功能分。無法實跑的項目不假定成功。

| 項目 | 得分／滿分 | 扣分依據 |
|---|---:|---|
| 情資擷取與證據正確性 | **15 / 20** | 25 主張的核心內容都可對照；未杜撰版本、密碼、LSASS 成功。扣 2：10 句正規化引文誤稱逐字；扣 2：明示主機角色／上下文遺失；扣 1：原文複數技術標籤未完整保留（如 T1562.001、T1078.001）。 |
| 攻擊鏈、相依性及缺失分析 | **8 / 20** | 缺失問題會引用來源且保留未知。扣 5：20 關係無來源依據、單步存檔又洗成使用者；扣 3：不同主機角色合併；扣 3：工具及環境依賴沒有可用安裝對應；扣 1：4 孤立節點。 |
| 補件及場景編輯流程 | **5 / 10** | 文字補件及行為修改會版本化、可追溯為使用者。扣 2：選填未知備註留白失敗；扣 2：成功補件未可見套用到主機規格；扣 1：本輪未找到 VM／主機結構化設定入口。 |
| IaC 正確性與部署可用性 | **4 / 20** | 已確認：未核准 up disabled、unsupported／缺設定明確拒絕、錯誤報告維持 internal 網路，未偷偷換成可啟動占位機。扣 12：本 CTI 無可生成／部署 IaC；扣 4：缺 guest 映像與資源參數且 GUI 無完成路徑。沒有給任何「部署成功」分。 |
| 攻擊行為／PoC 驗證 | **0 / 15** | BLOCKED／NOT_TESTED：沒有環境、沒有行為實跑、沒有攻擊鏈或報告可驗收。驗證拒絕誠實，但不等於 PoC 已驗證。 |
| GUI 可用性與操作直覺性 | **6 / 10** | 導覽、中文提示、來源定位、補件帶入選項可用。扣 1：計數不明；扣 1：原始巢狀錯誤難讀；扣 1：補件／VM 設定修正路徑不明；扣 1：缺前提仍可按，須反覆收錯誤。 |
| 測試證據與可追溯性 | **5 / 5** | 49 截圖、每站文字快照、完整 GUI action／error log、輸入 hash／副本、逐項原文核對、完整 Chromium trace；工具錯誤及未完成項目皆揭露。 |
| **總分** | **43 / 100** | **前半流程可操作；本 CTI 尚無可部署、可驗證的完整結果。** |

## 測試命令、實際輸出及清理

1. 以真實 Chromium 執行（Playwright 相依使用既有套件，沒有讀取前端原始碼）：

   ```sh
   /home/tyc4d/.nvm/versions/node/v22.23.3/bin/node reports/overnight/evidence/qa-instructor/round1/browser.cjs
   ```

   TTY 持續執行，輸出 `BROWSER_READY`。操作逐行記於 `browser-events.jsonl`；截圖／畫面文字逐步存檔。`CLOSE` 輸出 `CLOSED`，已停止 trace 並關閉 Chromium。第一次非 TTY 啟動的續寫問題與一次 helper 作用域錯誤列於前文；另一次原生啟動確認被 Playwright 預設取消，重新掛 dialog handler 後才產生真正 up 失敗紀錄，未把取消誤算成產品請求失敗。

2. GUI 實際業務結果：ingest 成功→supplement v2–v5→行為編輯 v6→IaC 不可部署→up confirmed `returncode=2 / compose file has not been generated / id=26 failed`→validate「尚未部署」→down confirmed 同樣 `returncode=2 / id=30 failed`。補件與 IaC HTTP 422、啟動／關閉 503、驗證 400；尚不存在的 PDF 原檔／IaC／驗證報告讀取有 404。事件記錄共 23 個 HTTP error 回應（含上述預期不存在項目），沒有 uncaught pageerror；細節以 `browser-events.jsonl`、`verification-summary.json` 與 trace 為準，未靠手動 API 替代畫面驗收。

3. 清理：從介面執行 down，但因始終沒有 compose 而失敗，不能稱 down PASS。實際從未成功部署，最終 GUI 容器為空。另以**只篩本輪專案精確標籤**的唯讀命令查證，三者 exit=0、stdout 空：

   ```sh
   docker ps -a --filter label=com.docker.compose.project=cr-demo-scn_05880c494a13 --format '{{.ID}} {{.Names}} {{.Status}}'
   docker network ls --filter label=com.docker.compose.project=cr-demo-scn_05880c494a13 --format '{{.ID}} {{.Name}}'
   docker volume ls --filter label=com.docker.compose.project=cr-demo-scn_05880c494a13 --format '{{.Name}}'
   ```

   證據為 `own-project-containers.txt`、`own-project-networks.txt`、`own-project-volumes.txt`。未啟動自己的 API／Web instance，未修改或停止共用 QA 站台，未動其他專案容器。透過「重新規劃拓樸」撤回本次測試用核准，最終待核准、up disabled。只留下 QA 情境及失敗歷史供 Lead 檢查；首頁未見刪情境入口，未另用 API 刪除。

4. 證據檢查：trace ZIP `testzip=None`（完整），含 `.trace`、`.network`、`.stacks`，1,203 個成員；檔案大小 61,742,446 bytes，49 張 PNG。另有輸入 hash、副本及 `quote-comparison.json`（39 quotes，29 exact，39 normalized）。證據不代表成功部署。未跑 pytest／build／實際 PoC，因本任務為既有站台 GUI 驗收且部署已阻塞；不把基準測試數當本輪結果。

5. 修改檔案：僅 `reports/overnight/worker-reports/qa-instructor*.md` 與 `reports/overnight/evidence/qa-instructor/round1/**`。**無產品程式碼修改、無 git add、無 commit**。完整檔案索引在 `evidence-manifest.json`；trace 約 62 MB，由 Lead 決定證據保存方式。

## 未解問題與需決定事項

- 需 Lead 處理：關係來源被整批改寫／警示消失；資產角色拆分；補件與結構化規格銜接；修正接受未知的選填契約；決定既有 Horizon／AD 支援路徑與 VM backend／fixture 如何補齊。這些都在既有八模組流程內，本輪未自行實作。
- 需產品負責人決定：**本輪沒有新增產品範圍的要求。** 是否接受以教學替代覆蓋特定無法重現的攻擊步驟，若將來改變 fidelity／驗收門檻，再由 Lead 提請決定；本輪未將任何替代當原事件成功。
- 未測：完整 PDF 匯入／原 PDF 閱讀器（指定輸入為 Markdown）、附件補件、實際 VM／容器啟動、網路動態探測、XMRig／Mimikatz／Ngrok／Log4Shell 行為、完整攻擊鏈、驗證報告下載。部署前提未滿足的項目均維持 BLOCKED／NOT_TESTED。
