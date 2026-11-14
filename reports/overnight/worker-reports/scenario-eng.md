# scenario-eng 過夜報告（模組 1–5 後端）

分支 `agent/scenario-eng`。證據在 `reports/overnight/evidence/scenario-eng/`。

## 0. 基準

- 測試指令：`PYTHONPATH=apps/api /home/tyc4d/cr-project/.venv/bin/python -m pytest apps/api tests -q`
- 開工時實際結果：**54 passed, 1 failed**（不是 brief 寫的 39 passed）。
  失敗的是 `apps/api/app/deploy/test_local_compose_integration.py::test_two_container_up_status_validate_down`
  （模組 7 Docker 整合測試，不屬於我的檔案所有權，未處理）。

## 1. 盤點（里程碑 1）

做法：用真實 LLM（`gpt-4.1-mini`，`single_pass`，自己的 `CR_DATA_DIR=.data`，上限 $5）跑四份情資，
把輸出與原文逐項比對。重現方式：

```sh
P=/home/tyc4d/cr-project/.venv/bin/python; E=reports/overnight/evidence/scenario-eng
$P $E/run_real.py fixtures/sample-scenarios/cisa-aa22-320a.md markdown single_pass $E/before/cisa-aa22-320a-single
$P $E/dump.py $E/before/cisa-aa22-320a-single     # 人可讀的比對輸出
```

修復前輸出保存在 `evidence/scenario-eng/before/<案例>/`（`00-input.txt` 原文、`01-ir.json`、
`02-dependencies.json`、`03-topology.json`）。

### 嚴重度：高

| # | 模組 | 問題 | 實際觀察（重現案例） | 根因 |
|---|---|---|---|---|
| H1 | 1 | 多台主機被併成一台假主機 `unknown` | CISA：原文明確有 Horizon server、VDI-KMS host、domain controller；輸出只有 `h1` 與 `id=unknown, role="unspecified hosts including VDI-KMS host, domain controller, and others"`，a14–a26 全指向它 | 提示詞叫模型「不知道就填 unknown」，程式沒有把 `unknown` 當保留字，也沒要求一台機器一筆 |
| H2 | 1 | 敘事順序被標成「原文支持」的事實 | CISA r3 `a3→a4 temporal [supported]`，引句只是 a4 自己那一句，完全沒有先後字眼；25 條關係中多數如此。Clop r1 `a1→a2`：兩個其實是同一件事（利用 CVE＝SQL injection） | 程式只檢查引句是否存在於原文，不檢查引句是否真的陳述了順序／相依 |
| H3 | 2 | 補件沒有回寫到 IR | 前端只送 `{text, targets_missing_item, status}`；後端只把文字存進 `missing_item.resolution`。使用者回答「Windows Server 2019」後，`hosts[].os` 仍是空的，模組 4/5 完全看不到 | 缺失項沒有機器可讀的回寫目標；`supplement` 只有在呼叫端另外給 `field/value` 時才寫入（前端從不給） |
| H4 | 2/4 | 重新產生相依會洗掉使用者的決定 | `plan_dependencies` 把所有 `planner_dep_*` 缺失項丟掉重建成 `open`，使用者先前的 resolution／status 消失 | 重建時沒有保留既有狀態 |
| H5 | 2 | 結構化補件會把整筆主機洗成「原文支持」 | `supplement` 寫入一個欄位後把整個 entity 設成 `source=user, epistemic_status=supported`，模型推測的 role 也跟著變成已支持 | 來源標記是整筆而非逐欄位 |
| H6 | 4 | IR 與相依結果主機不一致：憑空多出主機 | Clop：IR 一台 `host-target`，相依結果變三台 `host-target`、`host_target`、`unknown`；拓樸再把 `unknown` 當成一台容器 | `_host_id` 把 `-` 轉 `_` 後又用原 id 合併；`target_host_ref="unknown"` 被當成真主機 id |
| H7 | 4 | 把漏洞名與角色當成「軟體」 | CISA：服務名稱 `Log4Shell`、`domain controller`，並產生「version for Log4Shell」「version for domain controller」缺失項 | 用 catalogue alias 命中的原文字串直接當服務名稱 |
| H8 | 4 | 模組 1 抽出的服務被模組 4 忽略 | `_collect_candidates` 只看 `source == "user"` 的服務；模型抽到但 catalogue 沒有的軟體不會產生「無對應元件」缺失項 | 同左 |
| H9 | 5 | 初始入侵目標連不到，攻擊鏈入口不存在 | CISA：`h1`（T1190 利用對外服務）只在 `scenario-internal`，`connections=[]`，攻擊機完全到不了 | 是否對外只看 role 文字關鍵字，不看該主機是否為初始入侵目標 |
| H10 | 5 | 不支援的元件被標成可部署 | CISA：`unsupported-vmware-horizon` → `runtime=container, component_mode=substitute`；`unsupported-ad-ds` → `runtime=vm, component_mode=real`、guest 全是 null | 拓樸只分 vm／其他，沒有處理 catalogue 標為不支援的元件 |
| H11 | 1/5 | STIX 明確寫的主機、連接埠沒進環境計畫 | demo STIX：原文寫 `victim-web` TCP/80、`db` TCP/5432、db 只收內網；輸出主機沒有名稱、沒有服務、拓樸 0 條連線 | 提示詞沒要求服務／連接埠／主機名稱；模型常回空陣列 |

### 嚴重度：中

| # | 模組 | 問題 | 實際觀察 | 根因 |
|---|---|---|---|---|
| M1 | 1 | 原文有標的 ATT&CK tactic 被丟掉 | CISA a1 原文 `[TA0001]`，模型回 `["TA0001"]`（陣列），輸出沒有 tactic | 程式只接受字串 |
| M2 | 1 | 把「觀察」「說明」當成攻擊者行為 | CISA a4/a5/a6「Observe HTTPS activity…」、a11「file.zip contained XMRig…」、a8 重複 a3 | 提示詞沒定義 action 是攻擊者行為 |
| M3 | 1 | 行為名稱被換成戰術分類 | demo STIX：`External web reconnaissance` 變成 `Reconnaissance`，`Public web application exploitation` 變 `Initial access` | 同上，提示詞未要求保留原文用語 |
| M4 | 1 | 漏掉工具／檔案節點 | CISA：XMRig、PsExec、Mimikatz、Ngrok、mde.ps1、file.zip 都在原文，`artifacts=[]`；四份情資 artifacts 全為 0 | 提示詞對 artifacts 沒有任何說明 |
| M5 | 1 | 相依被標成單純先後 | CISA r6「By exploiting Log4Shell, the actors gained access…」標 temporal；下載 Mimikatz→執行 Mimikatz 標 temporal | 模型判斷；提示詞範例不足 |
| M6 | 1 | 把文件自己的出處當成 IOC | CISA：`www.cisa.gov`（出處網址）與來源 PDF 的 SHA-256 被列為 indicator | 出處判斷只看同一行前綴的少數字眼，雜湊完全沒檢查 |
| M7 | 1 | 主機沒有引句 → 一律「不足」 | CISA/demo：原文明確寫的主機全部 `insufficient` | 提示詞沒要求主機／服務附引句 |
| M8 | 2 | 缺失項寫死在特定案例的產品清單 | `missing.py` 內建 Horizon／Log4j／WordPress／XMRig／PsExec／Mimikatz／Ngrok 與 `horizon`、`vdi-kms` 角色群組；Clop 原文明講「未指出安裝版本」，卻沒有 MOVEit 版本問題 | 針對示範案例硬編碼 |
| M9 | 2 | 缺失項重複／問錯對象 | CISA：`missing-account-a18` 與 `missing-account-a19` 同一題（a19 是「使用」帳號卻被說成「建立」）；模組 2 的 `missing-product-vmware-horizon-version` 與模組 4 的 `planner_dep_version-vmware-horizon-h1` 重複 | 關鍵字比對；兩模組各自產生 |
| M10 | 2/3 | IR 被編輯後缺失項不會重算 | `PUT /api/scenario/{id}`、增刪 action 後 `missing_items` 維持分析當下的內容 | 只有分析時計算一次 |
| M11 | 4 | 佔位服務殘留 | 相依產生真服務後 `service-unspecified` 仍留在 IR，拓樸多一條雜訊註記 | 未清除 |
| M12 | 1 | STIX 的結構化資料沒被使用 | `extract_stix_candidates`（relationship、indicator、network-traffic）只有測試在用，STIX 匯入完全靠 LLM | 未整合 |

### 嚴重度：低

- L1：一個 action 只能存一個 technique；CISA a3 原文同時標 `T1059.001` 與 `T1562.001`，a14 同時標 `T1021.001` 與 `T1078.001`，第二個遺失（契約限制）。
- L2：`182.54.217[.]2/mdepoy.txt` 只抽到 IP，沒有抽成 URL。
- L3：`reproducibility` 只寫在各 action 與 `fidelity`，沒有彙總欄位（非錯誤，記錄）。

### 盤點後由 QA／Reviewer 追加的項目

| # | 來源 | 問題 | 根因 |
|---|---|---|---|
| Q1 | qa-instructor（High） | 只改一個行為後，所有未動的關係來源變成「使用者」 | 補件回應的 IR 沒有 `confirmed` 預設值，前端原樣送回；後端比對時自己把舊資料補上 `confirmed=false`，於是判定每條都被改過 |
| Q2 | qa-instructor | 20 條關係全部是推論、沒有依據 | 與 H2 同源：合併在一次提問時，模型幾乎不替關係附引句 |
| Q3 | qa-admin／qa-ux | 原文明寫的服務↔主機對應遺失、零路徑、IaC 拒絕 | H8＋H11 |
| Q4 | qa-admin | 補件後重新分析多出同名主機 `victim_web` | H6 |
| Q5 | qa-admin | PostgreSQL 被掛到 web 主機、產生 attacker→web:5432 | 行為文字提到的軟體一律綁到該行為的 `target_host_ref` |
| Q6 | qa-admin | 改名後舊的 `svc-oss-postgres-web` 殘留、主機顯示「—」 | 重新規劃時把上一輪模組 4 自己產生的服務當成「分析結果」保留 |
| Q7 | qa-admin | 自由補充寫明 host↔service 對應，重新分析沒有採用 | 自由補充文字從未被模組 4 讀取 |
| R1 | reviewer（P1，本分支新引入後已修） | `Apache Struts` 被比對成 Apache httpd，主機變 `real/oss-httpd` | 我加的「名稱內含產品字眼即比對」沒有排除「廠牌字＋另一個產品名」 |
| R2 | reviewer（P2） | 「不確定…」被原樣寫進 `os_version` 並結案 | 回寫沒有判斷回答是否為可用的值 |
| R3 | reviewer（P3） | 補件產生的服務沒綁到被回答的主機 | 補件文字沒寫主機名稱時沒有用「這題問的是哪台主機」當依據 |

## 2. 修復紀錄

全部是規則層級的根因修正，沒有針對任何案例的字串或 id 做特判。每項都有單元／整合測試；測試中的 LLM 一律是
`tests/fixtures/recorded/` 的錄製回應或手寫輸入，不呼叫真 API。

### 批次 1 — 模組 1 分析（各批 commit 見 `git log agent/scenario-eng`）

| 修復 | 對應 | 作法 | 檔案 | 測試 |
|---|---|---|---|---|
| 關係只有在引句真的陳述先後／相依時才算「原文支持」 | H2、Q2 | 已驗證引句必須含先後或相依用語（then／after／following／using the…／as a result of…，含中文與 STIX `precedes` 等）；否則降為 `inferred` 並寫明 `epistemic_reason`。標成 dependency 但引句只有先後字眼，同樣降級 | `cti/analysis.py` | `test_cti_analysis_rules.py`（4 個） |
| 關係改由專門一次提問產生 | H2、M5、Q2 | 新增「關係」專用提問：針對最終行為清單，要求引用陳述連結的原句；沒有原句才給 `inferred`。失敗時退回第一次提問的結果 | `cti/analysis.py` | 真實 LLM 驗證（§3） |
| `unknown` 不是主機 | H1 | `unknown`／`unspecified`／`none` 等保留字的主機項目直接丟棄並計入 `quality.dropped_placeholder_hosts`；行為指到不存在的主機一律改回 `unknown` | `cti/analysis.py` | `test_catch_all_unknown_host_is_not_a_host`、`test_distinct_hosts_stay_distinct…` |
| 主機／服務／工具改由專門一次提問產生 | H1、H11、M4、M7、Q3 | 新增「目標環境」專用提問：一台機器一筆、必附引句、服務帶 `host_ref`／版本／連接埠／CVE、每個行為的作用主機與（原文有寫時的）發動主機。失敗時退回 | `cti/analysis.py` | `test_service_keeps_stated_host_port_and_cve_only`、真實 LLM 驗證 |
| 防守方行為不進攻擊流程 | M2 | 每個行為要標 `actor`；`defender`／`other` 不進 `actions`，改列在 `quality.excluded_non_attacker_actions`，指向它們的關係一併移除 | `cti/analysis.py` | 真實 LLM 驗證（Equifax：偵測、封鎖、通報 FBI 等 8 項被排除） |
| 原文標的 tactic 不再遺失 | M1 | `attack_tactic` 接受陣列 | `cti/analysis.py` | `test_tactic_returned_as_list_is_kept` |
| 文件出處不當成 IOC | M6 | 文件中繼資料區塊（多行 `鍵: 值` 且含 Source／Publisher／License 等）內未去活化的網址、網域、雜湊不列為 indicator；「Source SHA-256」類標籤的雜湊不列入。一般 IOC 表的 `SHA256:` 不受影響 | `cti/analysis.py` | `test_document_provenance_is_not_an_indicator`、`test_labelled_ioc_hash_is_kept…` |
| 行為名稱保留原文用語 | M3 | 提示詞 | `cti/analysis.py` | 真實 LLM 驗證 |

### 批次 2 — 模組 2 缺失與補件

| 修復 | 對應 | 作法 | 檔案 | 測試 |
|---|---|---|---|---|
| 補件寫回 IR | H3 | 缺失項帶 `target`（collection／id／field）；前端照原本方式只送文字與題目 id，後端就把答案寫進該主機／服務欄位，並記 `applied_to` | `cti/missing.py`、`routers/ingest.py` | `test_supplement_writeback.py::WriteBack`（6 個） |
| 逐欄位來源 | H5 | 只有被補的欄位記 `field_sources[欄位]="user"`；整筆的 `source`／`epistemic_status` 不變 | `routers/ingest.py`、`cti/missing.py` | `test_answer_sent_the_way_the_ui_sends_it…` |
| 非答案不寫入 | R2 | 「不確定／unknown／not sure」→ 不寫入，狀態改 `accepted_unknown`；「可能／maybe／？」這類猜測 → 不寫入、題目維持 `open`、文字保留為補充；過長的說明文字也不寫入。原因記在 `write_back` | `routers/ingest.py` | `NonAnswers`（3 個） |
| IR 被編輯後缺失項重算並保留使用者決定 | M10 | `refresh_missing_items`：仍成立的題目保留狀態；已回答的題目留作紀錄；不再成立的未答題目移除；其他模組的題目不動。補件與模組 3 每次存檔都會呼叫 | `cti/missing.py`、`routers/scenario.py`、`routers/ingest.py` | `RefreshOnEdit`（2 個） |
| 版本問題不再只認固定產品 | M8 | 任何「被利用」的服務（帶 CVE，或相關行為是利用類技術／文字）都會問版本，並帶回寫目標。舊的固定產品清單仍保留為相容路徑（見 §5） | `cti/missing.py` | `test_questions_name_where_their_answer_belongs` |
| 同一帳號只問一次；攻擊機不問 OS | M9 | 同題目併入 `affects`；角色是 attacker 的主機不產生題目 | `cti/missing.py` | 既有測試＋真實驗證 |

### 批次 3 — 模組 3 流程編輯

| 修復 | 對應 | 作法 | 檔案 | 測試 |
|---|---|---|---|---|
| 無關編輯不會把未動的項目洗成「使用者」 | Q1 | 比對時「缺欄位／null／空／false」視為相同；未動的項目沿用原來源，不採信前端回傳的 `source` | `scenario/graph.py` | `test_unedited_items_keep_provenance_when_client_omits_defaults`、`test_confirming_a_relation_is_a_user_change`；另以舊程式重現確認會變成 user |

注意：已經被洗掉來源的既有情境不會自動還原（原來源已不在資料裡）。

### 批次 4 — 模組 4 軟體依賴

| 修復 | 對應 | 作法 | 檔案 | 測試 |
|---|---|---|---|---|
| 主機 id 前後一致 | H6、Q4 | 內部正規化後一律映回 IR 原本的主機 id；`unknown` 不建立主機 | `planner/dependencies.py` | `HostIdentity`（2 個） |
| 分析抽到的服務都納入規劃 | H8、Q3 | 不再只看使用者新增的服務；有 catalogue 對應就沿用原服務 id 標上元件，沒有就標 `no_component` 並產生缺失項 | 同上 | `RecordedServices`（3 個） |
| 軟體綁到「該子句點名的主機」 | Q5 | 順序：同子句中緊接在後的主機名 → 子句唯一點名的主機 → 角色唯一相符的主機 → 行為的作用主機。同時讀出同子句的版本與連接埠 | 同上 | `HostBindingFromText`（6 個） |
| 自由補充與題目回答都會被讀取 | Q7、R3 | 補件文字中的軟體以 `source=user`、`supplement_ref` 建立；回答某主機題目的補件以該主機為預設 | 同上 | `test_free_text_supplement_maps…`、`SupplementAnswersBindToTheAskedHost` |
| 已驗證引句中的版本／連接埠補進服務 | H11 | 主機、服務自己引用的已驗證原文句子會被讀取，寫入時記 `field_sources="source_quote"`，並把對應的版本題目結掉 | 同上 | `test_version_stated_in_a_verified_host_quote…` |
| 漏洞名／角色不當軟體名稱 | H7 | 由別名命中的服務以產品名命名，原字眼存 `matched_text` | 同上 | `MentionNaming` |
| 不同產品不互相比對 | R1 | 別名後面緊跟另一個大寫產品字（Apache **Struts**／**Tomcat**／**ActiveMQ**）不算命中；名稱內含產品字眼時，其餘字必須是 server／service 這類通用詞 | 同上 | `DifferentProductsAreNotAliases`（2 個） |
| 重新規劃保留使用者決定、不留殘留 | H4、Q6、M11 | 同 id 的 `planner_dep_*` 題目沿用使用者的狀態；上一輪模組 4 產生的服務不沿用；有真服務後移除佔位服務；模組 2 已問過的版本不重複問 | 同上 | `UserDecisionsSurviveReplanning`、`test_stale_planner_service…`、`test_placeholder_service_is_dropped…` |

### 批次 5 — 模組 5 拓樸

| 修復 | 對應 | 作法 | 檔案 | 測試 |
|---|---|---|---|---|
| 攻擊鏈有入口 | H9 | 沒有任何主機被原文／使用者標為對外時，把初始入侵行為（initial-access tactic 或 T1190／T1133／T1189／T1566／T1195／T1199）的目標主機放上 external，標 `exposure_basis=inferred_entry_point` 並在 notes 要求人工確認；找不到就明講「攻擊機沒有路徑」 | `planner/topology.py` | `EntryPoint`（4 個） |
| 使用者補的網路位置優先 | H3 | `network_placement`（含補件）先於角色字眼判斷；寫 internal 就不對外 | 同上 | `test_user_supplied_internal_placement_wins` |
| 原文明寫的跨主機步驟開通該路徑 | H11、Q3 | 行為有 `source_host_ref`≠`target_host_ref`、且是原文支持或使用者建立時，開通「來源→目標：該步驟點名的服務埠」。只有先後順序仍不開路徑 | 同上 | `test_stated_cross_host_step_opens_exactly_that_path`、`test_inferred_step_does_not…`、`test_temporal_order_alone…` |
| 不支援的元件不標成可部署 | H10 | catalogue runtime 為 `external_platform`／`unsupported` 的主機輸出 `runtime=<該值>`、`deployable=false`、不給 `component_mode`；無法建置的 VM 元件不再標 `real` | 同上 | `UnsupportedComponents` |


## 3. 真實 LLM 驗證（`gpt-4.1-mini`，single_pass，最終程式）

九份情資的輸入／輸出在 `evidence/scenario-eng/after/<案例>/`，總表 `after-run.log`；重跑 `sh reports/overnight/evidence/scenario-eng/run_all.sh after`，
比對摘要 `python reports/overnight/evidence/scenario-eng/summary.py <目錄>`。修復前輸出在 `before/`。

| 案例 | 對照標準答案的結果 |
|---|---|
| AA22-320A（cti-research） | 主機拆成 4 台（Horizon、VDI-KMS、DC、多台主機群）；15 條關係中 10 條附有陳述連結的原句、5 條如實標推論／不足；原文的 technique／tactic 保留 |
| Equifax（cti-research） | 8 個攻擊者行為對應 B1–B8；防守方行為 8 項被排除；3 月→5 月標為先後而非相依（符合「separate incident」陷阱）；沒有憑空產生 CVE／ATT&CK；Struts 不再被當成 httpd。**未達成**：三組資料庫仍併成一筆主機群 |
| 負向（資訊不足） | 沒有 CVE／產品／工具名稱／ATT&CK；應變措施 7 項被排除；5 個行為全部標 `source_certainty=hedged`；模組 4 產生 blocker「沒有任何目標軟體」，`fidelity=not_reproducible`（已用真 LLM 重跑確認） |
| qa-admin lifecycle | attacker→web:80、web→db:5432、attacker→db 必須阻擋；版本 1.31.8／16.16 帶到 |
| demo-intrusion.md（內建示範） | attacker→victim-web:80、victim-web→db:5432 開通，attacker→db:5432 必須阻擋；`h1.service_refs=[s1]`、`h2.service_refs=[s2]`。根因修正：原文寫在主機名稱旁的連接埠（已驗證引句）會補進該主機唯一缺埠的服務；沒有 catalogue 元件的服務仍掛回主機 |

## 4. 測試

`PYTHONPATH=apps/api /home/tyc4d/cr-project/.venv/bin/python -m pytest apps/api tests -q` → 合併 main 與 agent/frontend-eng 後 **124 passed**（開工時 54 passed, 1 failed）。

## 5. 未完成／未解

- 與 main（含 infra-eng@5059c10）合併後，catalogue 已有 Struts／Tomcat 真元件；別名測試改為驗證不變量「絕不比對成 Apache httpd、只能經由該元件自己的別名命中、catalogue 沒有的產品維持未對應」，沒有放寬。
- `missing.py` 舊的固定產品清單（Horizon／Log4j／WordPress…）仍在，只是多了通用路徑，沒有移除。
- STIX 的 `extract_stix_candidates` 仍未接進流程（M12）；一個行為多個 technique（L1）未處理。
- Schema JSON 未改，新欄位只寫在 `types.ts` 與 contracts README。
- 前端待辦（不歸我）：`source_certainty=hedged`、`epistemic_reason`、`write_back`、`exposure_basis`、`quality.excluded_non_attacker_actions` 目前畫面上不會顯示。
- 分析現在是三次 LLM 呼叫（流程、環境、關係），費用與時間約為原本的 2–3 倍。

## 6. 需產品負責人決定

- 推論出的入口主機要不要自動放上對外網段（目前會放並標示需確認）。
- 原文語氣不確定的行為，要不要擋住後續部署（目前只標記）。
