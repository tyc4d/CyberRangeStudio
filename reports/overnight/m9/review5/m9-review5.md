# Module 9 第五輪獨立 QA — convergence gate

**判定：CHANGES REQUESTED。** 前四輪原案例沒有退回未修狀態，但仍有 **2 類可重現的實質缺口**：**R5-01 / P1 匯出多行秘密而誤報乾淨**、**R5-02 / P2 GUI 的共用 generation counter 丟棄目前執行結果並保留舊 PASS**。因此不能確認「模組核心保證已誠實收斂、只有 #5 延後」。#5 本身確實維持 fail-closed，沒有重新出現真實 late-launch。

受測目錄 `/home/tyc4d/cr-project/.worktrees/m9-review5`，分支 `agent/m9-review5`，日期 2026-11-16（Asia/Taipei）。HEAD 為 `950bf3af9881c8956b975b2c6c53eabb5c89e8e0`；其父為指定的 `5039c32`，`git diff 5039c32 HEAD --stat` 僅 `FIX-ROUND-STATUS.md` 增加 8 行，產品程式與指定版本一致。

先讀根目錄 `AGENTS.md`，核對 approved scope D6、M9 PLAN／CONTRACT、四輪報告／測試與 FIX 文件。未修改既有檔案、產品程式或舊 assertions，未 add/commit、啟動其他 Agent、呼叫 LLM API、部署或執行真 exploit；未讀研究目錄或真實憑證。永久新增僅本報告及同目錄兩份檢查腳本。新 Python 探針以 autouse fixture 禁止 subprocess、HTTP、PVE、helper launch；ZIP 使用記憶體資料，時序控制使用 Event、真 SQLite／runner artifacts／hash／registry／chain verifier，僅模擬 ownership 與 delivery。前端直接擷取、執行未修改的產品 callback／metric／status-map，使用 deferred Promise，沒有改寫判定公式。

## 實際執行結果

| 檢查 | 結果 |
|---|---|
| `apps/api` suite（排除下列 2 個真 Docker integration） | **275 passed、2 deselected、94 subtests passed**，4.81 秒 |
| 未修改 `review/test_m9_review.py` | **57 passed、1 failed**，1.32 秒；唯一失敗 #5 |
| 未修改 `review2/test_m9_review2.py` | **89 passed、0 failed**，2.48 秒 |
| 未修改 `review3/test_m9_review3.py` | **34 passed、0 failed**，1.57 秒 |
| 未修改 `review4/test_m9_review4.py` | **59 passed、0 failed**，2.41 秒 |
| 四份舊 Python 合計（分別執行） | **239 passed、1 failed**，共 240 cases |
| 四份舊 frontend behavior checks | **4/4、6/6、9/9、10/10**，合計 29/29 |
| 舊唯讀 TypeScript checker | **34 個本工作樹來源檔，0 diagnostics** |
| 新 `test_m9_review5.py` 最終完整執行 | **17 passed、7 failed**，共 24 cases，1.10 秒；7 failures 全屬 R5-01 |
| 新 `check_web_review5.cjs` | **3 passed、4 failed**，共 7 checks；4 failures 全屬 R5-02 |
| 真 M9 多服務 exploit E2E、PVE cancel／timeout、隔離乾淨主機 rebuild | **未執行，沒有新增實機驗收證據** |

每次 Python invocation 均有相同 2 個既有 `jsonschema.RefResolver` 棄用警告。沒有 xfail 或弱化舊測試。新增 Python 的通過項包含：5 個實際 secret mapping 控制、1 個乾淨 bundle、3 個 checker 正向控制、1 個真後端交錯時序控制、3 種 backend 原 transport fail-closed、4 種最新零結果 job 狀態。

後端 suite 收集總數 **277 = 275 executed + 2 deselected**。94 subtests 另計，不能加進 277。明確排除的兩個測試是：

1. `app/deploy/test_local_compose_integration.py::LocalComposeIntegrationTests::test_two_container_up_status_validate_down`
2. `app/deploy/test_local_compose_integration.py::HostIsolationIntegrationTests::test_container_on_generated_lab_network_cannot_reach_a_host_service`

兩者會操作真 Docker，依本輪禁止部署而未執行；不聲稱本輪已覆核 277 全部 PASS。

## 新問題，按嚴重度排序

### R5-01 / P1 — 多行秘密的值被截在換行處，ZIP 外洩而 builder／checker 同時誤報乾淨

位置：`apps/api/app/poc/export/bundle.py:211`（`_value_end`）、`:244`（空值安全判斷）、`:258`（`_label_pass`）、`:325`（只解析完整 JSON 的 `_embedded_structure`）、`:337`（free-string 重掃）、`:461`（成品掃描）。

將以下**合法 YAML 片段作為 IR description 字串**，走真正 `build_bundle`。`S` 在所有測試中只是合成值 `round5-synthetic-credential-M937`：

```yaml
password: >
  S
```

最簡單的另一個案例是 `password:\n  S\n`（冒號後的值放下一行）。這兩種輸入均可由 `yaml.safe_load` 解析為含 S 的 password mapping；新增 builder 測試先斷言這點，並非無意義或不合法的 quoting nitpick。

| case | builder 結果 | 直接放入成品並更新正確 hash 的 checker |
|---|---|---|
| YAML literal block `password: \|` + 下一行 S | 洩漏 | 能抓到原始 literal block；**抓不到 builder 遮掉 `\|` 後留下的 S** |
| YAML folded block `password: >` + 下一行 S | 洩漏 | **未偵測** |
| YAML value on next line `password:` + 下一行 S | 洩漏 | **未偵測** |
| 合法 YAML 跨行 double-quoted password | 洩漏 | 能抓原始輸入；**builder 只遮第一行後的成品仍放行** |
| shell assignment 的 backslash-newline continuation | 洩漏 | 能抓原始輸入；**builder 只遮第一行後的成品仍放行** |

**5 個 builder cases 全部保留完整 S 到 `scenario/scenario.json` 和 `scenario/scenario.yaml`，同時 `manifest.contains_secrets=false`、`verify_bundle(data)==[]`。** folded／next-line 的獨立 checker 也失敗（已更新 scenario JSON 的 manifest hash，排除 checksum mismatch）。共 **7 個 failures**，同一個多行值邊界缺陷。

根因可直接定位：`_value_end` 遇裸值的 newline 就停止；quoted 值遇比 closing quote 更早的 newline 也回傳該位置。folded indicator `>` 又在 `_BARE_STOP` 中，所以被當作空值；下一行值的第一個字元本來就是 newline，同樣被視為安全空值。literal block 的 `|` 被替換成 `[REDACTED]`，真正密碼仍留下一行；最終重掃只看到安全 placeholder 的 label，不能再把剩餘文字綁回原欄位。`_embedded_structure` 只解析完整 JSON，不解析這類 YAML。

這不是要辨識沒有任何線索的任意自然語言秘密：輸入有明確的 `password` key 和標準多行值結構。actual secret-named mapping 的 5 個控制 cases 全部安全，證明 round-4 deep traversal 有效；盲點是**自由文字中的結構與多行值範圍仍不完整**。需要確定遮蔽整個值，或對無法確認清乾淨的多行 secret 結構拒絕匯出；目前的「converged／truthful verify_bundle」不成立。

重現：新 Python 中 `test_multiline_secret_builder_redacts_entire_value_or_refuses`（5 failures）及 `test_multiline_secret_checker_detects_even_with_correct_hash`（folded、next-line 2 failures）。

### R5-02 / P2 — chain/report 共用 generation 會作廢仍在途中的 execute，讓舊 PASS 留在目前畫面

位置：`apps/web/src/pages/PocPage.tsx:354`（report 遞增 generation）、`:362`（chain 遞增 generation）、`:375`／`:385`（execute 身分與回應 gate）、`:632`（chain button 執行期間仍可按）。

R4 的「先發舊 chain/report，後發 execute，舊回應晚到」確實已修。新的問題是**後發讀取 snapshot 不等於後發一次 execute**，卻共用同一個 counter 讓前面的真 execute 結果失效。可達順序：

1. 已有前一批合法、可驗的單動作 PASS（整鏈仍 false）。使用者按重跑；execute callback 取得 generation 1，先清 results／chain／report，POST 仍在途中。
2. 使用者再按「驗證攻擊鏈」。此按鈕只檢查 `chainAct.busy`，沒有受 `execAct.busy` 限制。chain callback 遞增到 2，讀取前一批成果並 setChain；自動 report callback 又遞增到 3，讀到前批 reproduced。
3. 新 POST 之後進入後端並完成，回傳 `[FAIL, FAIL]`。execute callback 發現 generation 不是 1，**整個 `setResults(d)` 及完成後的 report refresh 都被丟棄**。

直接執行原產品 callbacks／公式的實測結果：

```text
new execute HTTP result:   FAIL, FAIL
GUI stored results:        null
GUI action badges:         PASS, PASS
GUI scenario:              2/2
GUI unverified:            0/2
GUI whole chain:           0/1 (沒有宣稱 false full-chain PASS)
report refreshes:          1   (只有 execute 完成前的舊 snapshot)
```

三個前端斷言失敗（保存新 FAIL results、移除舊 PASS badges、修正 reproduced／unverified）。第四個斷言讓中途 chain request 本身丟錯：counter 仍已遞增，所以最後的 execute **BLOCKED** 詳細結果也被丟棄，永久留 `results=null`，無法呈現這次執行的阻擋證據。即使沒有歷史 PASS、真 transport 全封閉，仍可丟失目前的 BLOCKED 與原因。這是目前結果遺失／錯誤判讀，不是 cosmetic。

**後端可達性另有實際證據：**新增 `test_real_backend_can_return_prior_chain_report_while_execute_is_pending` 先經真 `service.execute`／SQLite／artifact writer／hash／registry 產生雙 PASS 並逐筆 verify；使用 Event 將下一個 execute handler 暫停在進入 `run_job` 前（同樣可由一般 HTTP transit 造成），此時真正 `service.chain`／`service.report` 回前批 PASS。release 後下一批雙 FAIL 正常保存；再讀後端 chain/report 已是 FAIL／reproduced=[]。此 positive control **通過**，沒有手改 verifier／chain／report。錯誤在 GUI 丟棄較新的執行完成與其 refresh，並非後端冒稱失敗批次 PASS。

若 execute job 已先建立，期間 chain 可能讀到 NOT_TESTED／部分結果；此時仍會丟掉最後 raw execution results，只是未必留下舊 PASS。因此不能靠「通常先建立 job」消除此缺陷。建議把「執行批次／IR 世代」與「各類查詢 request 順序」分開辨識，或阻止不相容的並行操作；讀 snapshot 不應作廢同批仍在進行的執行完成。

前端沒有啟 browser／React 渲染，本輪是原 callback 的確定時序測試，另以現有 JSX button 的 enabled 條件確認可操作順序；後端 PASS 僅使用合成傳輸，不聲稱執行過真 exploit。

## 32 項既有 finding 逐項回歸

以下是未修改的原重現案例結果。「原案例通過」不等於整類保證收斂。**除 #5（及 R2-03a 所指的同一 deferral）外，各項已修的原案例均維持修正；沒有將 #5 列為修好。**

| R1 finding（15 項） | 本輪核對 |
|---|---|
| #1 error marker 假 PASS | 原例、R2 channel 變異、R4 10 種 spoof 全過；精確 stdout／exit／stderr 協定未放寬。 |
| #2 ZIP secrets | 原 URL/default cases 全過；多行結構有新增 R5-01。 |
| #3 D6 本機攻擊封鎖 | 原 vulnerable／non-vulnerable cases 均過；新增 public flow 原 transport 本機零 launch。 |
| #4 附加非 lab 網路 | 原 extra-network 與 R2 網路隔離變異全過。 |
| #5 guaranteed cancel | **仍未完成；唯一舊 failure。**原 transport 零 launch，詳下節。 |
| #6 獨立／keyword／錯時間造全鏈 PASS | 原 cases 全過；本輪真 artifacts 的 independent PASS 仍 whole-chain false。 |
| #7 predecessor FAIL／傳遞 | 原 transitive／uncited／service batch cases 及 R4 diamond 全過。 |
| #8 discovery／service-host mapping | 原 fixture 與 canonical host.service_refs 的 discovery／plan／execute 全過。 |
| #9 evidence/hash/pin/run identity | 原 missing／unregistered、R2 integrity、R3 新批次、R4 零結果 cases 全過。 |
| #10 no verifier／exploit-by-name | upfront not_executable、有原因、名稱分類原 cases 全過。 |
| #11 BLOCKED／nullable serialization | 原兩類及 R2 嚴格 schema serialization cases 全過。 |
| #12 discover／chain 保存 | 原 save spies、R2 空 discovery／gated BLOCKED persistence 全過。 |
| #13 五個 fidelity metrics | R1 4/4、後續原 stale cases 均過；新的並行 snapshot 問題見 R5-02。 |
| #14 helper caps | PVE／local 原 cases 均過；memory=256m、cpus=1、pids-limit=128 已有。 |
| #15 version range | before／through、R2 metadata/operator 與邊界 cases 全過。 |

| R2 finding（9 項） | 本輪核對 |
|---|---|
| R2-01 新 secret formats | 原 userinfo/query/branch cases 全過；不擴大為多行已安全。 |
| R2-02 漏選／不可執行／substitute predecessor | 原三類和 R3 DAG controls 全過。 |
| R2-03 cancel transport/batch/GUI | 3a 對應 #5；3b 後續 actions 不啟動、3c reject/error/nonterminal 輪詢原 checks 全過。 |
| R2-04 一次 execute 一個 job | 原多 action 保存／同批身份、R3 FAIL-BLOCKED-sibling、R4 diamond 均過。 |
| R2-05 canonical host.service_refs | 原 discover、plan／execute cases 全過。 |
| R2-06 helper caps | 原 PVE assertion 與 local control 全過，非剩餘 blocker。 |
| R2-07 range operators | 真 metadata→ranking 原 cases 全過。 |
| R2-08 unverified 讀驗證證據 | 原 raw PASS 失效案例全過；新讀取／執行交錯見 R5-02。 |
| R2-09 空 discovery／阻擋結果保存 | 原真 SQLite cases 全過。 |

| R3 finding（4 項） | 本輪核對 |
|---|---|
| R3-01 quoted/encoded/map-key secrets | 全部舊 builder／checker 原 cases 通過。 |
| R3-02 failing rerun stale chain | 舊一般 rerun 與來源衝突 cases 全過。 |
| R3-03 overlapping rows／cancel hidden job | 原兩個 cases 全過，status 不混批、cancel 能旗標 active jobs。 |
| R3-04 live per_action rendering | 原實際 status shape mapping check 通過。 |

| R4 finding（4 項） | 本輪核對 |
|---|---|
| R4-01 quoted keys／headers／concat／nested secrets | 原 24 builder＋12 checker cases 全過；structural rewrite 有效，但多行邊界 R5-01 未收斂。 |
| R4-02 pending/error raw invalidation／late response | 原 10 frontend checks 全過；新增「先 execute，再 chain/report」方向有 R5-02。 |
| R4-03 job identity／stop confirmation | 原 4 overlapping-job Python cases 全過；新前端 historical-cancelled＋newer-done、矛盾 active identity controls 均過。 |
| R4-04 latest zero-result job | 原 cancelled／error cases 通過；新增 pending/running/cancelled/error 4 狀態均不回退舊 PASS。 |

## #5 的封閉性與驗收界線

`runner.py:172` 的原 `_probe_with_cancel` 仍沒有 daemon-thread launch，也不呼叫 `manager.probe_in_service`。新 public-flow 探針恢復這個原函式，ownership 僅用 mock 接受，真正 launch 一旦被呼叫即失敗：local-docker／proxmox／unknown-backend 全部 **BLOCKED、零 launch、零 delivered/responded/vuln_behavior/state_change、僅 log evidence**，兩筆結果完整保存。R4 6 種 backend／already-cancelled cases 也全過。

舊 #5 失敗點依然是 `test_m9_review.py:259` 的 `finished.wait(1)`，期待的 transport 本來就沒被啟動，**不代表又觀察到 late delivery**。但也不能據此宣稱 guaranteed-cancel 已完成。

deploy API 確實還缺能力：`deploy/manager.py:377` 是同步 probe；`proxmox.py:955` 持 placement lock 等 guest_exec，`:982` 的 PID 留在函式內，`:993` timeout 只丟例外。沒有可供 M9 呼叫的 start/wait/cancel/join handle 與 pending-launch fence。這是靜態能力核對，沒有實機 cleanup 保證實測。helper caps 已有，不能替代生命周期保證。

因此 #5 是**唯一仍失敗的舊 acceptance case／已記錄的既有 deferral**，但不是目前唯一產品缺口：本輪還有 R5-01／02。production registry 仍只有 Struts arithmetic proof、沒有 production state-transfer verifier；synthetic 全鏈單元 fixture 不等於真多服務 E2E。實機多服務驗收與乾淨主機重建依任務限制沒有執行，沒有把這些已知待驗證事項另算成新 finding。

## FIX-ROUND-STATUS 的宣稱核對

- `:50–51` 的四份 review Python／frontend 數字在本輪重現。277 與目前 suite 的收集總數一致，但本輪僅實跑 275，另 2 Docker tests 未執行；不推翻 Lead 可能在其授權環境執行過它們，也不冒稱已獨立覆核 277 PASS。
- `:47–48` 的 **“converged”／“truthful verify_bundle”** 被 R5-01 反證。rewrite 確實修好舊格式，不能宣稱成品秘密保證已收斂。
- `:48` 的 generation guard 與 `:49` 的 no-stale-batch 確實存在並通過原例；但若將其延伸為 GUI 已無 stale PASS，則被 R5-02 反證。job identity 與後端零結果 job 兩項則通過新增邊界控制。
- `:52` 的 **“Sole remaining failure: #5”** 對當時四份舊 Python 檔的失敗數成立，runner fail-closed 也成立；不能延伸成「唯一剩餘產品缺口」。本輪新增 7 個 Python failures、4 個 frontend failures 仍需處理。

## 重跑命令

以下從本工作樹執行，bytecode/cache 關閉；只使用本工作樹 contracts。暫存產物僅放 review5 並已於本輪完成後移除。

```sh
cd /home/tyc4d/cr-project/.worktrees/m9-review5/apps/api
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/tyc4d/cr-project/.worktrees/m9-review5/packages/contracts

/home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider --basetemp=../../reports/overnight/m9/review5/tmp-suite --deselect=app/deploy/test_local_compose_integration.py::LocalComposeIntegrationTests::test_two_container_up_status_validate_down --deselect=app/deploy/test_local_compose_integration.py::HostIsolationIntegrationTests::test_container_on_generated_lab_network_cannot_reach_a_host_service

/home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider ../../reports/overnight/m9/review/test_m9_review.py --basetemp=../../reports/overnight/m9/review5/tmp-review --tb=short
/home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider ../../reports/overnight/m9/review2/test_m9_review2.py --basetemp=../../reports/overnight/m9/review5/tmp-review2 --tb=short
/home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider ../../reports/overnight/m9/review3/test_m9_review3.py --basetemp=../../reports/overnight/m9/review5/tmp-review3 --tb=short
/home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider ../../reports/overnight/m9/review4/test_m9_review4.py --basetemp=../../reports/overnight/m9/review5/tmp-review4 --tb=short
/home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider ../../reports/overnight/m9/review5/test_m9_review5.py --basetemp=../../reports/overnight/m9/review5/tmp-review5 --tb=short
```

```sh
cd /home/tyc4d/cr-project/.worktrees/m9-review5
/home/tyc4d/.nvm/versions/node/v22.23.3/bin/node reports/overnight/m9/review/check_web_behavior.cjs
/home/tyc4d/.nvm/versions/node/v22.23.3/bin/node reports/overnight/m9/review2/check_web_review2.cjs
/home/tyc4d/.nvm/versions/node/v22.23.3/bin/node reports/overnight/m9/review3/check_web_review3.cjs
/home/tyc4d/.nvm/versions/node/v22.23.3/bin/node reports/overnight/m9/review4/check_web_review4.cjs
/home/tyc4d/.nvm/versions/node/v22.23.3/bin/node reports/overnight/m9/review/check_web_typecheck.cjs
/home/tyc4d/.nvm/versions/node/v22.23.3/bin/node reports/overnight/m9/review5/check_web_review5.cjs
```

**要求修改優先序：R5-01 / P1 完整多行秘密消除或拒絕匯出 → R5-02 / P2 區分執行世代與 snapshot 查詢，避免丟棄目前結果／恢復舊 PASS。另保留 #5 的既有 deploy-layer deferral，持續 fail-closed。**
