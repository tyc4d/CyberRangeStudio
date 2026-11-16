# Module 9 第六輪 FINAL-GATE 獨立 QA

**判定：CHANGES REQUESTED。兩項實質缺陷：R6-01 / P1 結構化秘密外洩且誤報乾淨；R6-02 / P2 延遲 snapshot 恢復過期的驗證判定。**

- 日期：2026-11-16（Asia/Taipei）。工作樹／分支：`m9-review6`／`agent/m9-review6`。
- 實際 HEAD：`d47d8f3d17cb6410fb96e66c110fd9a5d32828f8`。指定產品基準為 `b81486c966cb34007cfc6a99797ba4ac4f8d7b7f`；兩者唯一差異為 `FIX-ROUND-STATUS.md` 增加 round-5 狀態，`apps/`、`packages/` 沒有差異，因此沒有換測其他產品版本。
- 已先讀根目錄 `AGENTS.md`，核對前五輪報告／重現檔、五份 FIX-ROUND、狀態文件、CONTRACT、PLAN、approved scope。未改產品程式、既有測試或既有文件；未 add/commit、未啟動其他 Agent、未呼叫 LLM、未部署或執行真實 exploit。新增永久檔案僅此報告與同目錄兩份檢查腳本。
- 所有新增憑證皆合成。Python 使用記憶體 ZIP、既有 fixture 的來源替身與真正的 serializer/redactor/verifier；新增測試禁止 subprocess、HTTP、PVE、probe。前端執行未改動的 production callback／metric，並執行 production `ApiNotice` 的 retry 元件建構；HTTP 使用 deferred Promise，沒有啟動瀏覽器或服務。

## 實際測試結果

| 檢查 | 本輪結果 |
|---|---|
| `apps/api` suite，明確排除下述兩個 Docker integration | **276 passed、2 deselected、94 subtests passed**；4.51 秒 |
| 原 `review/test_m9_review.py` | **57 passed、1 failed**；1.33 秒；唯一 failure 為 #5 |
| 原 `review2/test_m9_review2.py` | **89 passed、0 failed**；2.34 秒 |
| 原 `review3/test_m9_review3.py` | **34 passed、0 failed**；1.54 秒 |
| 原 `review4/test_m9_review4.py` | **59 passed、0 failed**；2.18 秒 |
| 原 `review5/test_m9_review5.py` | **24 passed、0 failed**；1.19 秒 |
| 五份原前端行為腳本 | **4/4、6/6、9/9、10/10、7/7**，共 **36 passed、0 failed** |
| 原唯讀 TypeScript 檢查 | **34 個本工作樹來源檔，0 diagnostics** |
| 新 `review6/test_m9_review6.py` | **45 passed、4 failed**；1.98 秒；4 failures 同屬 R6-01，沒有 xfail／skip |
| 新 `review6/check_web_review6.cjs` | **4 passed、4 failed**；4 failures 同屬 R6-02 |

五份既有 Python 檔合計 **263 passed、1 failed，264 cases**；沒有跳過 #5 或改舊 assertions。每次 Python invocation 均有相同兩個既有 `jsonschema.RefResolver` 棄用警告，載入路徑確認為本工作樹的 contracts。

後端 suite 收集總數為 **278 = 276 executed + 2 deselected**。94 subtests 另計，不加進 278；本輪不能描述為「獨立確認 278 passed」。依任務禁止部署，明確排除：

1. `app/deploy/test_local_compose_integration.py::LocalComposeIntegrationTests::test_two_container_up_status_validate_down`
2. `app/deploy/test_local_compose_integration.py::HostIsolationIntegrationTests::test_container_on_generated_lab_network_cannot_reach_a_host_service`

## R6-01 / P1 — 合法 YAML 型別標記讓 exporter 只遮掉 tag，留下秘密，且 builder／verifier 都誤報乾淨

重現檔：`review6/test_m9_review6.py:64`，`test_tagged_yaml_builder_removes_real_parsed_secret_or_refuses` 的四個參數。沒有改造 manifest、hash、redactor 或 checker；直接檢查 production builder 產生的 ZIP。

合成秘密為 `round6-synthetic-credential-QA642`。以下原始 `description` 都是合法 YAML mapping，`yaml.safe_load(original)["password"]` 確實得到完整秘密（`!!binary` 得到對應 bytes）：

```yaml
password: !!str round6-synthetic-credential-QA642
```

```yaml
password: !!str |
  round6-synthetic-credential-QA642
```

另有 `!!str >` folded scalar，以及標準 YAML `!!binary |` 承載同一秘密的 base64。四者都成功匯出，秘密出現在 **`scenario/scenario.json` 與 `scenario/scenario.yaml`**；manifest **`contains_secrets=false`**，**`verify_bundle(data) == []`**。

例如 literal-block 案例的實際輸出 description 是：

```text
password: [REDACTED] |
  round6-synthetic-credential-QA642
```

inline 案例則成為 `password: [REDACTED] round6-synthetic-credential-QA642`。`!!binary` 也僅移除 tag，base64 全部留在下一行。這是**明確 password key 的標準 YAML 值**，不是任意 structureless prose token，也不是要求辨識沒有上下文的 base64。

原因與位置：

- `apps/api/app/poc/export/bundle.py:401` 的 `_redact_free_string` 只對原始 **JSON** 做結構式改寫；原始 YAML 仍先走文字 span 清理。
- `:244` 的 `_value_end` 將 `!!str`／`!!binary` 當成值的第一段，在空格停止；`:305` 的 `_label_pass` 只把 tag 換成 `[REDACTED]`，沒有清掉真正 scalar／block。
- 清理後的 embedded YAML 已不合法。`:384` 的 `_embedded_structure` 在 parse exception 時回 `None`，`:409`、`:519` 因此不再做這段結構的 field check；文字掃描則認為 label 後第一段 `[REDACTED]` 已安全。
- `:528` 的**外層** JSON/YAML parse 確實存在且正常；它讀到的是合法 scenario 文件內的一段字串，不能補救清理器已破壞、又被忽略的內嵌 YAML。最終 scan 與 `verify_bundle` 共用這個盲點。

**收斂裁定：直接的已解析物件欄位有實質收斂，完整 STRUCTURED-secret 類別仍未閉合。**本輪 45 個通過的 controls 包含：對成品檔重新計算正確 hash 後，JSON escaped key、編碼／多行／numeric／list／map 的 password 值均被抓到；真正 YAML 的 block／unicode escape／tag／binary／list／map 也被抓到；尚未清理的合法 tagged YAML 放在 description 也會被抓到。實際 password 欄位的 builder 清理、無法解析的外層文件拒絕、乾淨匯出亦通過。因此問題不是「沒有實作 parse」，而是**先用 span 改壞內嵌結構，再把 parse 失敗當作沒有結構可查**。

影響為帶秘密的 ZIP 外送並附假安全保證，定 P1；四種語法算同一項，不拆成四個 findings。驗收仍可選擇整段清除或明確拒絕，沒有要求保留這段描述。依 `FIX-ROUND-STATUS.md:59`–`:61` 的既定處置，本輪再次找到 export edge 應由 **Lead 提交 owner 決定 export guarantee／後續處置**；本 QA 未擅改保證或再開修正輪。

## R6-02 / P2 — snapshot 在 execute 期間開始、完成後才回來，仍能恢復舊驗證結果

重現檔：`review6/check_web_review6.cjs`。執行的 callback、狀態表與 fidelity 計算皆抽自目前 `PocPage.tsx`，沒有自行實作另一套判斷。

**不經 retry、不穿過 disabled 按鈕的正常操作順序：**

1. 有上一批有效個別證據，使用者按「驗證攻擊鏈」，chain request 尚未回覆。
2. 使用者按 execute 重跑；execute 按鈕不受 `chainAct.busy` 限制，舊結果立即清空。
3. 舊 chain 回覆到達。generation guard 正確丟棄該 chain，但 `PocPage.tsx:373` **仍無條件 `reportAct.run()`**，於 execute 期間啟動 report 讀取。
4. 此 report 在 execute 請求尚未進入 `run_job` 前取得上一批資料，回覆暫時延遲。這個後端可達性由已重跑通過的 R5 `test_real_backend_can_return_prior_chain_report_while_execute_is_pending` 以真 SQLite／artifacts 證明。
5. execute 完成，兩個 action 均 FAIL；它啟動的新 report 也先完成，畫面正確為 reproduced **0/2**、unverified **2/2**。
6. 第 3 步那個舊 report 才到。`PocPage.tsx:360`–`:363` 只比 `__execStarted`，並在**回覆當下**看 `__execDone == __execStarted`；沒有識別這份 snapshot 開始時 execute 正在進行，也沒有區分同世代的前後 report。因此接受舊 report，畫面恢復 reproduced **2/2**、unverified **0/2**，raw results 明明仍是 **FAIL、FAIL**。

另兩條可操作路徑是舊 chain/report error 的「重試」：`PocPage.tsx:663`、`:671` 的 `ApiNotice` 沒有 exec busy gate，`components/ui.tsx:221` 會產生可按的 retry。腳本實際執行 production `ApiNotice` 建構，確認這不是憑空呼叫使用者按不到的 callback。重試期間讀到的舊 report 在 execute 後回來會恢復錯誤數字；舊 chain 在 execute 後回來則連 action badges 都恢復 **PASS、PASS**。

舊五輪 web cases 全過，是因它們測到的 snapshot 在 execute 前開始，或在 execute 尚未完成時就回來；沒有涵蓋這次「執行中開始、執行完成後才回來」的方向。主 chain 按鈕新增 busy gate 是有效改善，但不足以阻擋自動 refresh／retry 入口。

本項是 GUI **錯誤驗證判定**，定 P2。沒有證明後端 evidence／DB 被改成 PASS，也沒有把 whole-chain `passes=false` 說成變成 true；一般 report 路徑的 raw vulnerability count 仍為 0/2。需要使 snapshot 的起始執行狀態及先後身分足以排除這些舊讀取；原 R5 已修好的 execute 結果不能再被 snapshot 丟棄。

## 34 項既有 findings 的回歸核對

**前五輪原始 assertions 沒有回歸。**下表的「通過」只代表既有案例維持修正，不把同類新增路徑也算已修。#5 仍是既有唯一 failure；R2-03a 指同一 deferral，不另算新的未完成項。

| R1（15 項） | 本輪結果 |
|---|---|
| #1 error-marker 假 PASS | 原例、R2 stdout/stderr/exit 變異、R4 spoof controls 均通過。 |
| #2 export secret | 原 URL/default 案例通過；新 tagged embedded YAML 缺口見 R6-01。 |
| #3 D6 本機攻擊 | vulnerable／non-vulnerable 舊例均通過；原 transport 本機零 launch。 |
| #4 額外非 lab 網路 | 原 extra-network 與 R2 external/edge/other-lab/isolation controls 通過。 |
| #5 guaranteed cancel | **未完成，仍唯一既有 failure，且安全封閉。**詳下節。 |
| #6 independent／keyword／時間造全鏈 PASS | 原例及真 artifact controls 通過，個別 PASS 不等於全鏈 PASS。 |
| #7 predecessor FAIL／傳遞 | 原例、R2 transitives、R4 diamond gating 通過。 |
| #8 service／host mapping | 原 discovery、canonical host.service_refs 的 plan／execute 均通過。 |
| #9 evidence/hash/pin/identity | 原例、R2 integrity 與 R3/R4 batch controls 通過。 |
| #10 no verifier／exploit by name | upfront not_executable 與 exploit 分類原例通過。 |
| #11 BLOCKED／nullable schema | 原例與 R2 鎖定原非 nullable 輸出的 serialization controls 通過。 |
| #12 保存 discovery／chain | 原 save cases、R2 空 manifest／BLOCKED 保存通過。 |
| #13 fidelity 分開／全鏈指標 | 原 4/4 與後續原 stale cases 通過；新延遲 snapshot 見 R6-02。 |
| #14 helper caps | PVE／local 原 assertions 通過；256m、1 CPU、128 PIDs 已落實。 |
| #15 version range | before／through 原例與 R2 metadata/operators/boundaries 通過。 |

| R2（9 項） | 本輪結果 |
|---|---|
| R2-01 新 secret formats | 原 userinfo/query/branch cases 全過。 |
| R2-02 漏選／不可執行／substitute predecessor | 原三類及 R3 DAG cases 全過。 |
| R2-03 transport／batch cancel／GUI | 3a 同 #5；3b 後續 action 不啟動，3c reject/error/nonterminal 不假稱停止，原例全過。 |
| R2-04 一次 execute 一個 job | 原批次身分／結果保存、FAIL-BLOCKED-sibling 全過。 |
| R2-05 canonical host.service_refs | discovery／plan／execute 原例全過。 |
| R2-06 helper caps | PVE／local controls 全過，沒有另列 deferral。 |
| R2-07 範圍運算子 | 真 metadata→ranking 原例全過。 |
| R2-08 unverified 讀有效證據 | 原失效 raw-PASS cases 全過；新增交錯見 R6-02。 |
| R2-09 空 discovery／BLOCKED 保存 | 原真 SQLite cases 全過。 |

| R3（4 項） | 本輪結果 |
|---|---|
| R3-01 quoted/encoded/map-key secrets | 原 builder／checker cases 全過。 |
| R3-02 failed rerun stale chain | 原 rerun／衝突來源 cases 全過。 |
| R3-03 overlapping jobs／cancel | 原 status 不混批、可取消 active job cases 全過。 |
| R3-04 live per_action rendering | 原實際 status shape mapping 通過。 |

| R4（4 項） | 本輪結果 |
|---|---|
| R4-01 quoted keys／headers／concat／nested secrets | 原 24 builder＋12 checker cases 全過。 |
| R4-02 pending/error raw invalidation／late response | 原 10 web checks 全過；同類未涵蓋方向見 R6-02。 |
| R4-03 job identity／stop confirmation | 原 overlapping-job Python 與前端 identity controls 全過。 |
| R4-04 最新零結果 job | 原 terminal／R5 pending/running/cancelled/error cases 全過。 |

| R5（2 項） | 本輪結果 |
|---|---|
| R5-01 multiline structured secret | 原 5 builder、5 checker、多行真正 secret-field controls 全過；tagged YAML 值仍未收斂，見 R6-01。 |
| R5-02 snapshot 作廢 execute | 原 FAIL/BLOCKED 結果保存與 7 web checks 全過；新增延遲回覆恢復舊驗證見 R6-02。 |

## #5 唯一既有 deferral：確實 fail-closed，不等於取消功能完成

原 `test_cancel_does_not_allow_delayed_launch_after_cleanup_returns` 仍失敗於 `review/test_m9_review.py:259` 的 `finished.wait(1)`，原因是 transport **根本沒啟動**；本輪沒有觀察到 late delivery，不能把這個 failure 重新描述成安全繞過。

`runner/runner.py:172` 的原 `_probe_with_cancel` 不建立 thread、不呼叫 `manager.probe_in_service`；local Docker 直接 D6 BLOCKED，其餘在缺 handle 時也 BLOCKED。重跑的 R4 的 3 backend × 2 cancellation 狀態（6 cases），以及 R5 三個 public execute backend cases 均通過：**零 launch、零 delivered/responded/vuln_behavior/state_change、只有 log evidence、公開結果完整保存**。ownership 在這些測試用 mock 放行，故不是靠 ownership 提早擋住來掩蓋 launch 缺口。

deploy 能力核對亦成立：`deploy/manager.py:377` 只有同步 probe；`deploy/backends/proxmox.py:949` 的 guest_exec 持 lock 等待；`:982` 的 QGA PID 沒有透出可取消 handle，`:993` timeout 丟例外，沒有 M9 可用的 start/wait/cancel/join、pending-launch fence／finally-kill 協定。helper caps 已有，不能替代生命周期保證。

所以 #5 是唯一**已記錄且尚未完成的舊 deferral**，不是這版唯一實質缺口（另有 R6-01／02）。目前 M9 真 attack execution 仍封鎖，不能宣稱 real exploit／guaranteed cancellation 已完成。production registry 的單一 Struts arithmetic proof、缺 production state-transfer verifier，以及 owner-gated 真多服務 E2E／乾淨隔離主機重建，沿用先前已記錄界限；本輪未實跑，也沒有將這些待驗證證據另包裝成新的 findings。

## FIX-ROUND-STATUS 的宣稱核對

- `:58` 的五份 review Python 數字與五份 frontend 數字**完整重現**；`:55` 的 emitted YAML/JSON structural parse 也確實實作，不是虛報未做。
- `:47`–`:48` 的 **“converged”／“truthful verify_bundle”** 不能成立為一般保證；R6-01 是合法 secret-named YAML scalar，在 production exporter 自己的輸出中洩漏並被 verifier 接受。
- `:55` 的 **“root-cause fix”** 對 outer parsed fields 與舊 R5 cases 有真改善，若延伸為 STRUCTURED-secret 類別已閉合，則被 R6-01 反證。不是要求掃描任意 prose token。
- `:56`–`:57` 的 separate execute lifecycle 與「snapshot 不再丟棄執行中的 execute completion」通過原例；但不能延伸為「GUI 不再恢復 stale verification」。R6-02 保留了 raw FAIL，卻恢復過期 report／chain 判定。
- `:59` 的 **“Sole remaining failure: #5”** 對五份既有 Python acceptance files 成立，fail-closed 也成立；對本輪所有實質缺陷則不成立。新測試有 4 Python failures、4 frontend failures，分別歸屬一項缺陷。
- `:58` 的 **278 passed** 與 suite 收集總數 278 相符，但本輪實跑為 **276 passed、2 deselected**。不推翻 Lead 可能在其授權環境實跑 Docker 的歷史紀錄，也不冒稱已獨立覆核那兩項。
- `:60`–`:61` 已明載遇到 round-6 export edge 要升級給 owner 決策。本輪證據觸發此處置；需要 Lead 帶著具體可重現結果回報，而非直接宣告 APPROVE 或悄悄限縮保證。

## 重跑方式

以下只讀既有來源與測試；bytecode／pytest cache 關閉，runtime artifacts 使用 `/tmp`。本輪執行時各 invocation 使用獨立的 `CR_DATA_DIR` 與 `--basetemp`，避免互相污染。

```sh
cd /home/tyc4d/cr-project/.worktrees/m9-review6/apps/api
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/tyc4d/cr-project/.worktrees/m9-review6/packages/contracts

CR_DATA_DIR=/tmp/m9-review6-suite-data /home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider --basetemp=/tmp/m9-review6-suite-tmp --deselect=app/deploy/test_local_compose_integration.py::LocalComposeIntegrationTests::test_two_container_up_status_validate_down --deselect=app/deploy/test_local_compose_integration.py::HostIsolationIntegrationTests::test_container_on_generated_lab_network_cannot_reach_a_host_service

CR_DATA_DIR=/tmp/m9-review6-review1-data /home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider ../../reports/overnight/m9/review/test_m9_review.py --basetemp=/tmp/m9-review6-review1-tmp --tb=short
CR_DATA_DIR=/tmp/m9-review6-review2-data /home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider ../../reports/overnight/m9/review2/test_m9_review2.py --basetemp=/tmp/m9-review6-review2-tmp --tb=short
CR_DATA_DIR=/tmp/m9-review6-review3-data /home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider ../../reports/overnight/m9/review3/test_m9_review3.py --basetemp=/tmp/m9-review6-review3-tmp --tb=short
CR_DATA_DIR=/tmp/m9-review6-review4-data /home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider ../../reports/overnight/m9/review4/test_m9_review4.py --basetemp=/tmp/m9-review6-review4-tmp --tb=short
CR_DATA_DIR=/tmp/m9-review6-review5-data /home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider ../../reports/overnight/m9/review5/test_m9_review5.py --basetemp=/tmp/m9-review6-review5-tmp --tb=short
CR_DATA_DIR=/tmp/m9-review6-new-data /home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider ../../reports/overnight/m9/review6/test_m9_review6.py --basetemp=/tmp/m9-review6-new-tmp --tb=short
```

```sh
cd /home/tyc4d/cr-project/.worktrees/m9-review6
/home/tyc4d/.nvm/versions/node/v22.23.3/bin/node reports/overnight/m9/review/check_web_behavior.cjs
/home/tyc4d/.nvm/versions/node/v22.23.3/bin/node reports/overnight/m9/review2/check_web_review2.cjs
/home/tyc4d/.nvm/versions/node/v22.23.3/bin/node reports/overnight/m9/review3/check_web_review3.cjs
/home/tyc4d/.nvm/versions/node/v22.23.3/bin/node reports/overnight/m9/review4/check_web_review4.cjs
/home/tyc4d/.nvm/versions/node/v22.23.3/bin/node reports/overnight/m9/review5/check_web_review5.cjs
/home/tyc4d/.nvm/versions/node/v22.23.3/bin/node reports/overnight/m9/review/check_web_typecheck.cjs
/home/tyc4d/.nvm/versions/node/v22.23.3/bin/node reports/overnight/m9/review6/check_web_review6.cjs
```

**FINAL-GATE 未通過。優先序：R6-01 / P1 匯出假乾淨保證（依現有狀態文件交 owner 決定處置）→ R6-02 / P2 snapshot 過期驗證判定；#5 繼續明確延後並保持零啟動封鎖。**
