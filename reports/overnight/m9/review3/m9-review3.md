# Module 9 第三輪獨立 QA

**CHANGES REQUESTED**

受測工作樹／分支：`/home/tyc4d/cr-project/.worktrees/m9-review3`／`agent/m9-review3`。實際 HEAD 為 `0650449a362e1e179a79d74676c0d06ac73b197c`；其父提交是指定的 `15df414`，兩者差異只有 `FIX-ROUND-STATUS.md` 新增的狀態段落，產品程式一致。日期：2026-11-16（Asia/Taipei）。

前兩輪修正沒有在原重現案例中被撤回：第一輪 **57 passed / 1 failed**，第二輪 **89 passed / 0 failed**；唯一舊失敗確實是 #5，且現在因 transport 根本不啟動而失敗，不能把它重報成 late-launch 漏洞。但新探針發現 **4 類剩餘問題**，所以不能認可「整個模組只剩 #5」。最優先是 ZIP 仍帶出合成秘密，`contains_secrets=false` 和 `verify_bundle=[]` 同時給出錯誤保證。

已先讀根目錄 `AGENTS.md`、兩輪報告及測試、三份 FIX 文件、`PLAN.md`、`CONTRACT.md` 與 approved scope D6。未修改任何既有檔案或產品程式、未 add/commit、未啟動其他 Agent、未呼叫 LLM、未部署、未送出真實 exploit，也未接觸研究目錄。永久新增內容只有本報告與同目錄兩份腳本。新 Python 探針使用真正的 SQLite、runner artifact 寫入器、hash、registry 及 chain verifier，僅模擬 ownership／delivery；另設禁止 subprocess、HTTP 與 PVE 呼叫的 guard。沒有將 verifier 或 PASS 結果整體換成手填成功值。

## 實際測試結果

| 檢查 | 結果 |
|---|---|
| `apps/api` 後端 suite，排除下述 2 個真實 Docker 測試 | **261 passed、2 deselected、89 subtests passed**；3.75 秒；2 個既有 RefResolver 警告 |
| 未修改的第一輪 `review/test_m9_review.py` | **57 passed、1 failed**；1.25 秒；唯一失敗為 #5 |
| 未修改的第二輪 `review2/test_m9_review2.py` | **89 passed、0 failed**；1.81 秒 |
| 兩輪 Python 檔合併重跑 | **146 passed、1 failed**；3.36 秒 |
| 新 `review3/test_m9_review3.py`（34 cases） | **24 passed、10 failed**；1.20 秒；沒有 xfail，10 個失敗歸為 R3-01／R3-03 |
| 未修改的第一輪前端行為腳本 | **4 passed、0 failed** |
| 未修改的第二輪前端腳本 | **6 passed、0 failed** |
| 新 `review3/check_web_review3.cjs`（9 checks） | **5 passed、4 failed**；4 個失敗歸為 R3-02／R3-04 |
| 未修改的第一輪唯讀 TypeScript 檢查器 | **34 個本工作樹來源檔、0 diagnostics** |
| 真實 M9 多動作／多服務 exploit E2E、PVE cancel／timeout、乾淨隔離主機重建 | **未執行，沒有新增實機驗收證據** |

這輪遵守「不部署」，明確排除 round-2 已指出的兩個既有無攻擊 Docker 整合測試：

- `app/deploy/test_local_compose_integration.py::…::test_two_container_up_status_validate_down`
- `app/deploy/test_local_compose_integration.py::…::test_container_on_generated_lab_network_cannot_reach_a_host_service`

兩者會操作真實 Docker，**本輪沒有執行，不能聲稱這輪 263 個全部 PASS**；261+2 是原套件收集總數。它們即使在其他輪次通過，也不屬於 M9 真 payload E2E。89 個 subtests 另外列出，不加進 261 當成 test count。此次沒有重現第二輪執行這兩個測試而違反「不部署」的情況。

## 本輪新增、依優先序排列的問題

### R3-01 / P1 — 匯出仍洩漏帶引號、編碼參數及 secret map key，掃描器仍宣稱正常

位置：`apps/api/app/poc/export/bundle.py:94`（inline 值）、`:101`（query 值）、`:203`（dict 只處理 value）、`:223`（最終掃描）、`:251`（欄位掃描）。

使用全合成值 `round3-synthetic-credential-N627`，真實 `build_bundle` 產出的以下 5 種輸入都洩漏到 `scenario/scenario.json` 和 `scenario/scenario.yaml`：

| case | 合成輸入摘要 | 實際結果 |
|---|---|---|
| `quoted-password-single` | description 內 `password='<合成值>'` | 整個值保留 |
| `quoted-password-double` | description 內 `password="<合成值>"` | 整個值保留 |
| `quoted-query-suffix` | `https://example.invalid/?access_token=public'<合成值>` | `public` 被遮，單引號後的秘密仍保留 |
| `encoded-query-key` | `https://example.invalid/?%61ccess_token=<合成值>` | key 未解碼，整個值保留 |
| `secret-dictionary-key` | `credentials: {<合成值>: "[REDACTED]"}` | 值已遮但敏感 mapping key 原樣保留 |

**這 5 個成品全部 `manifest.contains_secrets == false`，而 `verify_bundle(data) == []`。** 沒有真密碼，也沒有真 HTTP。前 4 個是自由文字／URL 的直接洩漏；第 5 個是刻意把合成 credential 放在 mapping key 的額外對抗案例，不主張所有 dictionary key 本身都是秘密。

原因不是上一輪 regex 完全沒修：舊一般 URL、普通 query、`${VALUE:+literal}`、`clientSecret` 等控制組可安全 redaction 或明確拒絕。剩餘問題是 inline 模式不接受引號包值，query 模式遇單引號即停止且不解碼參數名，結構遍歷只清 value；最終掃描也沒有補足這些盲點。

獨立 checker 探針另外將合成秘密放進乾淨 ZIP 的 JSON、同步更新該檔 manifest hash，排除單純 checksum mismatch：quoted-password、encoded-query-key、secret-dictionary-key 三個仍未被 `verify_bundle` 抓到。未重現外部任意檔案注入；這是成品秘密掃描的精度驗證。

重現：`test_fresh_bundle_secrets_are_removed_or_export_is_refused` 的上述 5 cases；`test_verify_bundle_independently_detects_unredacted_structured_secret` 的上述 3 cases。共 **8 個 Python failures**。需要清理完整語意值或拒絕匯出，不能保留錯誤的無秘密保證。這是第一輪 #2／R2-01 的新格式缺口，舊格式沒有 regression。

### R3-02 / P2 — 重跑失敗仍顯示上一輪 PASS，未驗證數字再度變成 0/2

位置：`apps/web/src/pages/PocPage.tsx:354`、`:430`、`:468`。

新腳本直接執行現有 `execAct` callback、`fid` 與 `statusByAction`，只以 stub 代替 API／React setter；status map 的 TypeScript 型別透過既有 TypeScript 套件轉譯，不重寫計算。

可達流程：先持有兩個經驗證單動作 PASS 的 `chain.per_action`（整鏈仍 false）；再執行一次兩動作 FAIL 的批次。`execAct` 更新 `results` 並取得新 report，卻沒有更新或失效化舊 `chain`。實際輸出：

```text
raw results:          FAIL, FAIL
new report:          reproduced=[], not_reproduced=[a1,a2]
GUI vuln:            0/2
GUI scenario:        0/2
GUI unverified:      0/2       （錯；沒有目前有效的成功驗證）
GUI action badges:   PASS, PASS（沿用舊 chain）
```

另一個新 case 讓目前 chain 為 BLOCKED、舊 report 還有 reproduced，`new Set([...reproducedIds,...chainPassIds])` 的聯集仍把動作當已驗證。換言之，**「讀了 chain/report」不等於驗證是同一批、目前有效的資料**。需要隨新執行／IR 變動失效化或重算舊 snapshot，並在來源衝突時避免用任一舊 PASS 覆蓋新結果。

證據：`check_web_review3.cjs` 的三個 failure（failed rerun metric、failed rerun badges、stale report override）。沒有重現 backend 整鏈 false 被改成 true；這是 GUI 的錯誤單動作 PASS 與 metrics。正向 fixture 代表合法 runner/artifact 協定資料；本輪不宣稱實際發動過真攻擊來得到這些 PASS。

### R3-03 / P2 — 重疊 execute 工作的狀態混批，較新已完成工作會遮住仍在跑的工作，無法取消

位置：`apps/api/app/poc/runner/runner.py:387`、`:399`、`:431`；`service.execute`／HTTP router 沒有拒絕同 scenario 的重疊 execute。

兩個 fresh cases 經真正 `service.execute`、`run_job` 與 SQLite，使用巢狀模擬 delivery 安排確定的交錯順序，沒有並行實機操作：

1. J1/a1 已啟動，在其模擬 transport 返回之前啟動並完成 J2/a2；最後才讓 J1 寫結果。`execution_status` 選了較新 J2，卻以 `poc_runs.ts >= J2.created_at` 撈資料，得到 **`per_action=[a2,a1]`**，log tail 也指向 J1，混進不屬於所選 job 的結果。
2. J2 已完成但 J1 仍在 transport 中，DB 明確顯示 J1 `state=running`；這時 `cancel_execution` 只查最新 job J2，回 **`{cancelled:false}`**，並未對仍在執行的 J1 設 cancel flag。

重現：`test_status_must_not_mix_overlapping_jobs`、`test_completed_newer_job_cannot_hide_an_older_still_running_job_from_cancel`，共 **2 個 Python failures**。

一個 execute 已確實對應一個 job，R2-04 的原單批次拆 job 問題修好了；但「同一 scenario 同時接受兩個 job」仍缺一貫的狀態／取消身分。可拒絕重疊或以明確 job 身分追蹤；這是 API／store 協定問題，可以用 mock 修驗，不能全部歸因於 #5 的 deploy handle。

**風險界線：**目前真 transport 仍封閉，本輪沒有證明真 helper 在取消後繼續執行；重現的是 cooperative cancellation 的可達性與狀態混批，不能冒充實機清理失敗。

### R3-04 / P2 — GUI 有輪詢，但後端動作階段沒有真的顯示

位置：後端 `runner/runner.py:428`，前端 `PocPage.tsx:427`、`:545`。

後端回 `{job_state, per_action:[{action_id,stages}], logs_tail}`；前端 `liveResults` 卻只讀 `live.results`。新腳本把實際 backend shape 餵進原計算式，得到 **`liveResults=null`**，因此 `execAct.busy` 下的 per-action ResultCard 區塊不顯示。`live.per_action` 與 `live.logs_tail` 也沒有其他 render 使用點。

重現：`check_web_review3.cjs` 的 `actual execute/status shape supplies visible live action stages`。修正需要使用真正的 progress shape 顯示目前階段，不能只靠 URL 字串存在或 polling function 有執行就宣稱即時階段／日誌畫面完成。這不會製造 backend PASS，但屬於「宣稱完成是否真的可見」的缺口。

## 第一輪 15 項逐一回歸裁定

「舊案例保持修正」和「整類問題再無缺口」分開裁定；本輪沒有將舊 assertions 改弱。

| 第一輪項目 | 本輪裁定 |
|---|---|
| #1 錯誤文字 marker 製造 PASS | 舊 case 及 R2 的 12 種 stdout/stderr/exit 變異全過；成功仍限 pinned payload 的 exact stdout、空 stderr、exit 0。未發現這條路徑 regression。 |
| #2 ZIP 秘密外洩 | 兩個 R1 格式和 R2 的 8 個格式全過；**整類未完，R3-01 的 5 個新格式洩漏。** |
| #3 D6 本機攻擊路徑 | 不分 target vulnerable 標記均 BLOCKED；新 public batch 恢復原 `_probe_with_cancel` 後本機也零 launch，沒有僅靠改 test transport 過關。 |
| #4 額外非 lab 網路 | 舊 case、R2 external/edge/other-lab/non-isolated/not-member 都拒絕；逐張附加網路檢查仍在。 |
| #5 取消／晚到 launch | **真 transport fail-closed 成立，保證取消功能未完成。**舊 case 仍 fail，詳見下節；GUI terminal polling 原缺口已修，但另有 R3-03／04。 |
| #6 獨立／keyword／時間順序造整鏈 PASS | 舊三類及 R2 真 artifact cases 全過；新多動作正常單步 PASS 仍不能製造整鏈 PASS，沒有 production transfer verifier 被憑空加入。 |
| #7 FAIL 前置阻擋 | 舊案例、漏選/not_executable/substitute 的 R2 cases 全過；新 self/cycle/missing/diamond-missing/prior-job 與反向 IR 排序全過。未把 temporal 發明成硬 dependency。 |
| #8 IR service／host mapping | R1 service.host_ref 與 R2 canonical host.service_refs cases 都過；不再只修 discovery、漏 plan。 |
| #9 artifact／pin／run identity | R2 17 種 artifact/context 變異、每次獨立 artifact 路徑與單 job 成果保存皆過。新 `[FAIL,BLOCKED,PASS]` 保留 sibling，最新失敗批次不撿舊 PASS。status/cancel 的多 job 缺口另列 R3-03，不宣稱 chain 拼舊成功又回歸。 |
| #10 no_verifier／exploit-by-name | upfront not_executable 有 reason；缺 technique 的 exploit 仍 poc_exec；substitute/disabled 不偷執行。config_check 分類不等於已執行 benign check，未將其計為真 exploit 成功。 |
| #11 BLOCKED／schema | BLOCKED 保持；R2 獨立鎖回 nonnullable integer/string 的實際 public serialization 也過，並非只靠放寬 schema 通過。 |
| #12 discovery／chain 保存 | R1 save spies 與 R2 真 SQLite 非空／空 discovery、chain、gated BLOCKED 保存全過；新 fail-blocked-sibling 亦完整入庫。 |
| #13 五個 metrics | 舊 4 checks 和 R2 6 checks 全過，整鏈按 0/1 顯示；**新跨批次 snapshot 缺口 R3-02 仍會錯報單步 PASS／未驗證數字。** |
| #14 helper 資源上限 | R1 PVE command case 已 PASS；靜態與新 local benign helper mock 都確認 `--memory 256m --cpus 1 --pids-limit 128`。這項確實 DONE，非硬體 blocker。 |
| #15 version ranking | 原 before/through、R2 10 個直接邊界與真正 discovery 保留 after/< 等 4 cases 全過；未發現舊格式 regression。 |

## 第二輪 9 項逐一回歸裁定

| 第二輪項目 | 本輪裁定 |
|---|---|
| R2-01 秘密格式 | 原 8 cases 全過；新格式有 R3-01，不能對秘密消除作全面完成保證。 |
| R2-02 前置繞過 | 漏選、not_executable、substitute 全過；新 DAG／舊 job 不能滿足前置等 case 也過。所有 declared predecessors 都送入單批 requests gating。 |
| R2-03 取消 | deploy 3a 仍誠實封閉；3b 單批次兩／四個獨立動作取消都僅一次 transport、後續不啟動；3c 原腳本全過，新 terminal/running/error/40 次未終止輪詢也不假報 stopped。重疊 job 問題另列 R3-03。 |
| R2-04 一次 execute 一個 job | 確實一次 `run_job`；合法雙 PASS 保留兩筆 per_action，整鏈 false；新失敗／阻擋／sibling identity cases 也過。非把 chain 放寬跨批次拼接來過測試。 |
| R2-05 canonical service mapping | 原正常 host.service_refs 的 discovery／plan case 已過，service/classifier 都有相應解析。 |
| R2-06 helper caps | PVE 與 local command 實際均帶三個 cap，mock 驗證過，確實完成。 |
| R2-07 範圍運算子 | 正式 discovery metadata extraction 保留 after、<、before、through 的原重現 cases 全過。 |
| R2-08 unverified | 原「raw PASS + chain/report 同時失效」case 已過；但 chain/report 跨批次不一致時仍過度認定，見 R3-02。 |
| R2-09 保存 | 空 discovery 保留 marker；執行前阻擋也寫 artifacts 與 SQLite；原 cases 及新完整三筆結果核對皆過。 |

## `[FAIL,BLOCKED]` edge、真實取消及完成度界線

新增 probes 特別先產生合法可驗的舊 `[PASS,PASS]`，再跑最新 `[FAIL,BLOCKED]` 或 `[BLOCKED,BLOCKED]`。最新兩筆都有可讀的 hash-bound log 和同一 job_id，chain 保留兩筆正確狀態；report.reproduced 為空。再加第三個獨立成功動作，`[FAIL,BLOCKED,PASS]`／`[BLOCKED,BLOCKED,PASS]` 也完整保留，不因 gated result 缺 ownership 而丟掉 sibling 或撿回舊批次。ownership 在第一步就拒絕的 `[BLOCKED,BLOCKED,PASS]` 亦通過。這個 `15df414` 修正有真實作用。

**#5 的 fail-closed 確實誠實：**`runner/runner.py:172` 的原 `_probe_with_cancel` 沒有啟 daemon thread、沒有呼叫 `manager.probe_in_service`，在 local Docker 回 D6 BLOCKED，PVE／unknown backend 回 guaranteed-cancel handle 缺失的 BLOCKED。新 public batch case 讓 ownership 通過、恢復原 wrapper、把實際 launch 設成「一被呼叫即失敗」；三種 backend 均零 launch、零 delivery/response/effect evidence，只有 log。R2 四種 backend/cancel case 也全部通過。

原 #5 test 的失敗點仍是 `finished.wait(1)`：它期待已停用的 transport 曾執行；這不代表 late helper delivery，又不能因 safe BLOCKED 就宣稱 cancellable execution 已完成。

共享 deploy API 的缺口仍真實存在：`manager.py:377` 為同步 `probe_in_service`；`proxmox.py:949` 的 `guest_exec` 在 placement lock 內等 polling，`:968` 的 QGA PID 不對外暴露，timeout 只丟例外。不存在可供 runner 使用的 start/wait/cancel/join handle 或 pending-launch fence；掃描後 kill 不能替代它。這是靜態流程確認，沒有實機清理／timeout 保證實測。#14 的 caps 不能補出 #5 的生命週期能力。

另外幾個已在前輪說明的驗收界線必須保留：

- production registry 只有 Struts arithmetic proof，沒有 `state_transfer_types`；synthetic chain unit fixture 的正向全鏈 PASS 不能當作實際多服務 credential/session transfer 已完成。
- M9 的 config_check／substitute 分類是誠實分類；`execute` 仍只選 poc_exec，不能從分類存在推論 benign 檢查已執行。
- 本輪 mock-delivery 的 PASS 可驗證真正 log/artifact/store/chain 協定；由於所有真 attack transport 被封閉，不能將它算成真實 exploit E2E。
- 乾淨隔離主機重建尚未實跑；ZIP 的 generator bytes／hash／rebuildable 邏輯測試不是實機 rebuild 成功證據。

## FIX-ROUND-STATUS 的過度宣稱裁定

`FIX-ROUND-STATUS.md:35` 的 review1 **57/1**、review2 **89/89** 在本輪重現；263 是套件總數，本輪因不部署只重跑其中 261，另 2 個未執行，不宣稱覆核其 PASS。`:37` 的 runner fail-closed 和 #14 DONE 都有程式及動態 mock 證據，成立。

`:31` 的「9 findings fixed」可限定解讀為**原重現 cases 已修正**。若用來表示 secret redaction、GUI 現行驗證及執行狀態整類已完整完成，則被 R3-01／02／03／04 反證。`:36` 的「sole remaining failure is #5」對當時兩份舊 Python acceptance files 的失敗數成立，**不適合延伸為只有一個剩餘產品缺口**。新增 Python 10 failures、前端 4 failures 不能因舊檔全綠而忽略。實機 PVE E2E 本來在文件列為 pending，本輪沒有把這項誠實待驗證事項算成文件造假。

## 重跑方式

後端從本工作樹 `apps/api` 執行，明確指定本工作樹 contracts；關閉 bytecode／pytest cache，輸出暫存只放 review3。測試產物可刪除，不需要提交。

```sh
cd /home/tyc4d/cr-project/.worktrees/m9-review3/apps/api
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/tyc4d/cr-project/.worktrees/m9-review3/packages/contracts /home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider -k 'not test_two_container_up_status_validate_down and not test_container_on_generated_lab_network_cannot_reach_a_host_service' --basetemp=../../reports/overnight/m9/review3/.suite-tmp --tb=short

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/tyc4d/cr-project/.worktrees/m9-review3/packages/contracts /home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider ../../reports/overnight/m9/review/test_m9_review.py --basetemp=../../reports/overnight/m9/review3/.round1-tmp --tb=short

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/tyc4d/cr-project/.worktrees/m9-review3/packages/contracts /home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider ../../reports/overnight/m9/review2/test_m9_review2.py --basetemp=../../reports/overnight/m9/review3/.round2-tmp --tb=short

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/tyc4d/cr-project/.worktrees/m9-review3/packages/contracts /home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider ../../reports/overnight/m9/review3/test_m9_review3.py --basetemp=../../reports/overnight/m9/review3/.fresh-tmp --tb=short
```

```sh
cd /home/tyc4d/cr-project/.worktrees/m9-review3
/home/tyc4d/.nvm/versions/node/v22.23.3/bin/node reports/overnight/m9/review/check_web_behavior.cjs
/home/tyc4d/.nvm/versions/node/v22.23.3/bin/node reports/overnight/m9/review2/check_web_review2.cjs
/home/tyc4d/.nvm/versions/node/v22.23.3/bin/node reports/overnight/m9/review/check_web_typecheck.cjs
/home/tyc4d/.nvm/versions/node/v22.23.3/bin/node reports/overnight/m9/review3/check_web_review3.cjs
```

另保留 **#5 deploy guaranteed-cancel handle** 的既有未完成項；在生命週期保證完成並驗證前維持真 transport fail-closed。尚未具備真實多服務 exploit E2E／乾淨主機重建的驗收證據。

最終裁定：**CHANGES REQUESTED**。

1. **R3-01 / P1：**補齊成品秘密消除與獨立掃描，停止輸出錯誤無秘密保證。
2. **R3-02 / P2：**修正跨批次 GUI PASS／metrics 的 stale snapshot。
3. **R3-03 / P2：**讓重疊工作的 status/cancel 身分一致，或明確拒絕重疊工作。
4. **R3-04 / P2：**接上真正的即時 progress 回傳格式。
