# Module 9 — FINAL confirmation QA / round 7

**判定：APPROVE。Module 9 對核心宣稱的處理誠實；#5 的安全封閉延後，以及無法證明乾淨時拒絕匯出，都是已記錄的行為。此次未發現需要修改的新實質缺陷。**

- 日期：2026-11-16，Asia/Taipei；Lead：t31。
- 工作樹：`/home/tyc4d/cr-project/.worktrees/m9-review7`，分支 `agent/m9-review7`。
- 實際 HEAD：`6eb9379`。指定基準 `58c4dc0` 到 HEAD **只多了 `FIX-ROUND-STATUS.md` 的 11 行狀態更新，產品碼相同**。
- 已先讀根目錄 `AGENTS.md`，核對 approved scope、M9 PLAN／CONTRACT、六輪 review 與 FIX-ROUND／STATUS。
- 未修改產品碼、既有驗收測試或研究參考資料；未 add／commit；未啟動其他 Agent；未呼叫 LLM、部署、真實 exploit 或 PVE。持久新增檔案僅本目錄的報告及 Python QA 腳本；測試暫存、SQLite 與合成匯出 ZIP 均在 `/tmp`。

## 實際執行結果

| 檢查 | 結果 |
|---|---|
| `apps/api` backend suite | **283 passed、2 deselected、131 subtests passed**，6.21 秒 |
| R1 Python 原驗收 | **57 passed、1 failed**，1.34 秒；唯一失敗為 #5 |
| R2 Python 原驗收 | **89 passed**，2.43 秒 |
| R3 Python 原驗收 | **34 passed**，1.64 秒 |
| R4 Python 原驗收 | **59 passed**，2.41 秒 |
| R5 Python 原驗收 | **24 passed**，1.31 秒 |
| R6 Python 原驗收 | **49 passed**，2.34 秒 |
| 六份原 Python 驗收合計 | **312 passed、1 failed**；未排除、修改、xfail 或 skip #5 |
| R1～R6 六份 frontend behavior scripts | **4/4、6/6、9/9、10/10、7/7、8/8**，共 **44/44** |
| 唯讀 TypeScript CompilerHost 檢查 | **34 個本工作樹來源檔、0 diagnostics** |
| 本輪新增 `test_m9_review7.py` | **25 passed**，2.12 秒；最終版本完整重跑通過 |

Python 各 invocation 都只有原有的兩個 `jsonschema.RefResolver` 棄用警告。前端用主 checkout 已安裝的 TypeScript／依賴解析本工作樹來源與 contracts，未安裝依賴、未寫入產品檔案。

backend suite 的兩個 deselected 是會實際建立 Docker 環境的既有 integration；依本任務「No deploy」限制排除：

1. `app/deploy/test_local_compose_integration.py::LocalComposeIntegrationTests::test_two_container_up_status_validate_down`
2. `app/deploy/test_local_compose_integration.py::HostIsolationIntegrationTests::test_container_on_generated_lab_network_cannot_reach_a_host_service`

因此此次獨立重現的是 **283 passed + 2 deselected**，不冒稱獨立執行了狀態文件中的 285/285。所有六輪指定 Python／frontend 原驗收均完整執行。

## 36 項既有 findings：追蹤狀態無回歸

下表以原報告的 finding 為單位，共 15 + 9 + 4 + 4 + 2 + 2 = 36 項。#5 保持延後；R2-03a 是同一限制，沒有新增第二個 deferral。這裡的「通過」指原驗收與本輪檢查成立，不把尚未實跑的 exploit 稱為成功。

| R1 | 本輪核對 |
|---|---|
| #1 錯誤 marker 假 PASS | 原錯誤案例、R2 stdout/stderr/exit 變異、R4 spoof controls 均通過。 |
| #2 匯出秘密 | 原 URL/default、後續各輪結構化案例全過；R6 四種 tagged YAML builder 已過。 |
| #3 D6 本機攻擊 | vulnerable／non-vulnerable 舊例通過；原 transport 與 public flow 均零 launch。 |
| #4 額外非 lab 網路 | extra-network、external/edge/other-lab/isolation controls 通過。 |
| #5 guaranteed cancel | **唯一未完成項，持續 fail-closed BLOCKED**；詳下節。 |
| #6 independent／keyword／時間造全鏈 PASS | 原三類與真 artifact controls 全過；單步 PASS 不冒充全鏈 PASS。 |
| #7 前置失敗與傳遞 | 原 transitive／uncited／batch 及 R4 diamond gating 通過。 |
| #8 service／host mapping | 原 discovery／service mapping、canonical host.service_refs controls 通過。 |
| #9 evidence／hash／pin／identity | 原 missing/unregistered、R2 integrity、R3/R4 job／batch controls 通過。 |
| #10 無 verifier／依名稱判 exploit | upfront not_executable／reason 與 exploit 分類通過。 |
| #11 BLOCKED／nullable serialization | BLOCKED 保持；原 schema 及嚴格 nonnullable serialization controls 通過。 |
| #12 discovery／chain 保存 | 原 save cases、非空／空 discovery、BLOCKED persistence 通過。 |
| #13 fidelity 分開／全鏈指標 | 原 4/4 與後續 stale-response scripts 全過；R6 交錯方向也已修。 |
| #14 helper caps | PVE／local 原 cases 通過；256m、1 CPU、128 PIDs 保留。 |
| #15 version range | before／through、metadata→ranking、operators／boundaries 通過。 |

| R2 | 本輪核對 |
|---|---|
| R2-01 新 secret formats | userinfo／query／interpolation branch 原 cases 全過。 |
| R2-02 漏選／不可執行／substitute predecessor | 原三類與後續 DAG controls 通過。 |
| R2-03 transport／batch cancel／GUI | 3a 仍同 #5；3b 後續 action 不啟動，3c reject/error/nonterminal 不假稱停止，均過。 |
| R2-04 一次 execute 一個 job | 批次 identity／完整保存、FAIL-BLOCKED-sibling cases 通過。 |
| R2-05 canonical host.service_refs | discovery／plan／execute 原 cases 全過。 |
| R2-06 helper caps | PVE／local controls 全過，已完成。 |
| R2-07 range operators | 真 metadata→ranking 與邊界 cases 通過。 |
| R2-08 unverified 使用有效證據 | raw-PASS 失效案例及 R3～R6 交錯 controls 全過。 |
| R2-09 空 discovery／BLOCKED 保存 | 真 SQLite cases 通過。 |

| R3 | 本輪核對 |
|---|---|
| R3-01 quoted／encoded／map-key secrets | 原 builder／checker cases 與後續結構化 controls 全過。 |
| R3-02 failed rerun stale chain | rerun、衝突來源與後續 stale snapshot cases 全過。 |
| R3-03 overlapping jobs／cancel | status 不混批，仍在執行的工作不被較新 done job 遮住；原 cases 通過。 |
| R3-04 live per_action rendering | production status shape 對應畫面階段的原 check 通過。 |

| R4 | 本輪核對 |
|---|---|
| R4-01 quoted keys／headers／concat／nested secrets | 全部原 builder／正確 hash 的 checker cases 通過；R5/R6 類型也已過。 |
| R4-02 raw invalidation／late responses | pending、error、舊 chain/report callback 與原 10 web checks 全過。 |
| R4-03 job identity／stop confirmation | 原 overlapping-job Python、cancelled-id 與 contradictory active-state web cases 全過。 |
| R4-04 最新零結果 job | terminal cancelled/error 及 pending/running cases 全過，不回退舊 PASS。 |

| R5 | 本輪核對 |
|---|---|
| R5-01 multiline structured secret | 原多行 builder／checker／真正 secret-field cases 全過；tagged YAML 也已閉合原重現路徑。 |
| R5-02 snapshot 作廢 execute | 原 FAIL/BLOCKED 結果保存與 7 web checks 全過。 |

| R6 | 本輪核對 |
|---|---|
| R6-01 tagged YAML 假乾淨匯出 | 四種 builder 與全部 verifier controls 通過；本輪 parser oracle／refusal 流程亦通過。 |
| R6-02 execute 中開始、完成後才回來的 snapshot | 8/8 web checks 通過；FAIL 結果、0 reproduced／2 unverified、FAIL badges 均未被舊資料改回。 |

## 匯出核對：解析後清理與拒絕流程成立

核對 `apps/api/app/poc/export/bundle.py`：

- `:398` 的 `_parse_embedded` 先解析 JSON／YAML，再交由 redactor；tag、binary、alias／merge 等交給 parser 解析。文件候選解析失敗會丟 `ExportError`。
- `:451` 的 `_redact_free_string` 從已清理結構重新序列化，重新解析待寫入字串並檢查；不再只替換 tag 的文字 span。
- `:488`／`:514` 的 resolved scalar／secret-copy 核對，以及 depth／cycle 限制保留；不能證明秘密副本移除便拒絕。
- `:605` 的 `find_field_secrets` 走解析後的欄位與內嵌文件；`:663` 的 `_file_secrets` 對實際 emitted `.json` 用 `json.loads`、`.yaml` 用 `yaml.safe_load`，供 builder final scan 及 `verify_bundle` 共用。解析失敗算 unsafe。
- `:1013` 的 final scan 發現 unsafe 即丟 `ExportError`；公開 export route 將它回為 HTTP 409。安全 marker、空值、null／boolean 與純 runtime reference 沿用既有規則；有 literal secret 的 branch／prefix／concat 不獲豁免。

本輪新增 25 個檢查的證據在 `test_m9_review7.py`，沒有替換 production parser／redactor／serializer／verifier：

1. **8 個實際 emitted bundle 檢查**：`!!str`、`!!binary`、escaped key、merge、JSON 裡的 YAML、YAML 裡的 JSON、雙重 JSON、前言加 YAML。獨立 oracle 用真正 parser 遞迴檢查秘密值，未引用 production secret-detection helpers；兩份 emitted scenario 的解析結果一致，所有 manifest hash 另行計算通過，原 SQLite IR 未被 redaction 改寫。
2. **10 個 verifier 檢查**：原文先經獨立 parser oracle 證實帶秘密；再放入 scenario YAML 本文或 JSON description，重算正確 SHA-256。verifier 仍報 `secret material in <path>`，沒有靠 hash mismatch 通過，也沒有在錯誤訊息吐出合成秘密。
3. **4 個真 persistence／ASGI 流程檢查**：malformed secret、未知 tag、secret 的 public alias 副本、cycle 均收到 HTTP 409。拒絕前後原情境、discovery manifest、既有 ZIP bytes、poc_exports rows 完全保留，沒有新增 partial ZIP；下載仍回既有檔案。改回公開描述後可成功匯出另一份 ZIP，舊檔未被覆寫。
4. **3 個乾淨格式 controls**：full／iac／evidence 均可匯出並獲 verifier 接受；evidence-only 仍誠實標 `rebuildable=false`。

本輪未找到「parser 可解析出的具名秘密值仍被送出、同時聲稱乾淨」的重現。無法解析／不能證明已清理的輸入被拒絕，符合這一版約定，未列為缺陷。任意沒有結構上下文的散文／opaque token 不在本次宣稱或攻防範圍。

## GUI 的 R6 修正核對

`apps/web/src/pages/PocPage.tsx:363`／`:369` 在 snapshot **開始時**記錄 `__execStarted` 和 `__execDone`，回覆時要求原本沒有 execute 在途且兩值未改變。R6 原案例實際執行 production callbacks，所有舊 chain/report 回覆均無法恢復過期驗證。

chain callback 仍會觸發一次 report refresh；該 refresh 受同一開始／完成 stamp 防線約束，原 R6 case 與前五輪案例已驗證此路徑安全。`PocPage.tsx:665`／`:673` 的兩個 ApiNotice 傳入 `retryDisabled={execAct.busy}`，`components/ui.tsx:222` 確實將它送到 button disabled。

R6 舊腳本還會印出 `OBSERVED ... retry is enabled`，因其直接建構 retry 元件時未傳入新 props，並強制呼叫 callback。實際頁面的 disabled gate 已在來源核對；即使腳本強制呼叫，generation guard 也已讓全部 assertions 通過。這不是新 UI 缺陷。此次未啟動瀏覽器做視覺／人工 E2E。

## #5 是唯一誠實 deferral

原 #5 的 failure 原樣保留：

```text
test_cancel_does_not_allow_delayed_launch_after_cleanup_returns
review/test_m9_review.py:259: assert finished.wait(1)
AssertionError: test transport did not finish
1 failed, 57 passed
```

`apps/api/app/poc/runner/runner.py:172` 的原 `_probe_with_cancel` 不建立 thread、也不呼叫同步 probe。local Docker 因 D6 BLOCKED；其餘 backend 因缺 guaranteed-cancel handle／launch fence／finally-kill／join 而 BLOCKED。這個 failure 來自測試傳輸根本沒有啟動，沒有重現晚到 launch。

R2／R4 的 backend × cancel controls、R5 的 public execute controls 重新通過：放行合成 ownership 後，原 transport 仍零 launch，沒有 delivered/responded/vuln_behavior/state_change，只留下誠實 log／BLOCKED 結果並保存。`deploy/manager.py:377` 仍只有同步 probe API；Proxmox QGA 的同步 guest_exec 未提供 M9 所需的可取消 transport handle。因此沒有將 #5 說成已完成，也沒有用假取消換取全綠。

已知的 registry／實機界線沿用既有紀錄：目前 production proof 的範圍有限，尚無此次 QA 的真多服務 exploit、state-transfer 或乾淨主機重建證據。任務禁止這些實跑，未把 mock PASS 或單元測試視為該類證據；本判定是對目前誠實、安全封閉行為的核准。既有 36 項中的唯一未完成工程工作仍是 #5；沒有新增 deferral。

## 重跑命令

全部 Python 命令從本工作樹 `apps/api` 執行，使用本工作樹 contracts、獨立 `/tmp` data／basetemp，不寫 bytecode 或 pytest cache：

```sh
cd /home/tyc4d/cr-project/.worktrees/m9-review7/apps/api
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/tyc4d/cr-project/.worktrees/m9-review7/packages/contracts

CR_DATA_DIR=/tmp/m9-review7-suite-data /home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider --basetemp=/tmp/m9-review7-suite-tmp --deselect=app/deploy/test_local_compose_integration.py::LocalComposeIntegrationTests::test_two_container_up_status_validate_down --deselect=app/deploy/test_local_compose_integration.py::HostIsolationIntegrationTests::test_container_on_generated_lab_network_cannot_reach_a_host_service

# 第一輪預期僅 #5 失敗；迴圈繼續執行後面五輪。
for n in 1 2 3 4 5 6; do
  if [ "$n" = 1 ]; then
    review_dir=review
    review_file=test_m9_review.py
  else
    review_dir=review$n
    review_file=test_m9_review$n.py
  fi
  CR_DATA_DIR=/tmp/m9-review7-r$n-data /home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider ../../reports/overnight/m9/$review_dir/$review_file --basetemp=/tmp/m9-review7-r$n-tmp --tb=short
done

CR_DATA_DIR=/tmp/m9-review7-confirmation-final-data /home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider ../../reports/overnight/m9/review7/test_m9_review7.py --basetemp=/tmp/m9-review7-confirmation-final-tmp --tb=short
```

```sh
cd /home/tyc4d/cr-project/.worktrees/m9-review7
/home/tyc4d/.nvm/versions/node/v22.23.3/bin/node reports/overnight/m9/review/check_web_behavior.cjs
/home/tyc4d/.nvm/versions/node/v22.23.3/bin/node reports/overnight/m9/review2/check_web_review2.cjs
/home/tyc4d/.nvm/versions/node/v22.23.3/bin/node reports/overnight/m9/review3/check_web_review3.cjs
/home/tyc4d/.nvm/versions/node/v22.23.3/bin/node reports/overnight/m9/review4/check_web_review4.cjs
/home/tyc4d/.nvm/versions/node/v22.23.3/bin/node reports/overnight/m9/review5/check_web_review5.cjs
/home/tyc4d/.nvm/versions/node/v22.23.3/bin/node reports/overnight/m9/review6/check_web_review6.cjs
/home/tyc4d/.nvm/versions/node/v22.23.3/bin/node reports/overnight/m9/review/check_web_typecheck.cjs
```

**最終結論：APPROVE。36 項既有追蹤狀態無回歸；未發現新的 manufactured PASS、parser 可解析秘密外送的假乾淨保證、錯誤 exploit verdict、隔離缺口或資料損失。#5 持續誠實封閉延後，export-refusal 是既定安全行為。**
