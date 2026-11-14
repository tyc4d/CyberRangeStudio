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

## 2. 修復紀錄

（後續批次接在下面）
