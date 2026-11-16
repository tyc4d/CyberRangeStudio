# Module 9 第四輪獨立 QA（final gate）

**CHANGES REQUESTED**

前三輪原重現案例沒有被撤回修正：三份 Python 檔分別 **57 passed / 1 failed、89 passed / 0 failed、34 passed / 0 failed**，合跑 **180 passed / 1 failed**。唯一舊失敗仍為 #5，而且真實 attack transport 確實保持 fail-closed。但本輪找到 **4 類新缺口**，不能確認「產品只剩 #5」；最嚴重的是 ZIP 仍帶出明確標示的合成憑證，卻同時給出 `contains_secrets=false` 與 `verify_bundle=[]`。

受測工作樹：`/home/tyc4d/cr-project/.worktrees/m9-review4`，分支 `agent/m9-review4`。實際 HEAD `1cfa534593332205f2af29fba46d825022d5df1c`，父提交為指定的 `9bf2b7d`。`git diff 9bf2b7d HEAD --stat` 只有 `FIX-ROUND-STATUS.md` 新增 6 行，產品程式一致。日期：2026-11-16（Asia/Taipei）。

已先讀根目錄 `AGENTS.md`，並讀前三輪報告、測試、FIX 文件、`PLAN.md`、`CONTRACT.md` 與 approved scope D6。沒有修改任何既有檔案、產品程式或舊 assertions，沒有 add/commit、啟動 Agent、呼叫 LLM API、部署或執行真 exploit，也沒有讀取研究目錄或真實憑證。永久新增內容只有本報告、`test_m9_review4.py`、`check_web_review4.cjs`。Python 新測試禁止真實 subprocess、HTTP、PVE 與 helper launch；測試使用合成值、記憶體 ZIP、真 SQLite／artifact writer／hash／registry／chain verifier，僅模擬 ownership 與 transport。

## 測試數量與實際結果

| 檢查 | 本輪實際結果 |
|---|---|
| `apps/api` 後端 suite，排除下述 2 個 Docker integration | **266 passed、2 deselected、89 subtests passed**，3.91 秒 |
| 未修改 `review/test_m9_review.py`（58 cases） | **57 passed、1 failed**，1.29 秒；失敗只有 #5 |
| 未修改 `review2/test_m9_review2.py`（89 cases） | **89 passed、0 failed**，2.28 秒 |
| 未修改 `review3/test_m9_review3.py`（34 cases） | **34 passed、0 failed**，1.49 秒 |
| 上述三份 Python 合跑（181 cases） | **180 passed、1 failed**，4.42 秒；同一個 #5 |
| 新 `review4/test_m9_review4.py`（59 cases，最後完整重跑） | **32 passed、27 failed**，2.26 秒；沒有 xfail |
| 未修改三輪前端行為腳本 | **4/4、6/6、9/9 passed** |
| 新 `review4/check_web_review4.cjs` | **2 passed、8 failed**（10 checks） |
| 未修改的唯讀 TypeScript 檢查器 | **34 個本工作樹來源檔、0 diagnostics** |
| 真實多服務 exploit E2E、PVE cancel/timeout、乾淨隔離主機重建 | **沒有執行，沒有新增實機驗收證據** |

每次 Python invocation 都有相同 2 個既有 `jsonschema.RefResolver` 棄用警告。subtests 另列，沒有加進 test count。後端總收集數 **268 = 266 executed + 2 deselected**；不是這輪 268 全部 PASS。明確排除：

1. `app/deploy/test_local_compose_integration.py::LocalComposeIntegrationTests::test_two_container_up_status_validate_down`
2. `app/deploy/test_local_compose_integration.py::HostIsolationIntegrationTests::test_container_on_generated_lab_network_cannot_reach_a_host_service`

它們會操作真 Docker，故遵守本輪「不部署」而不執行；也不能把這兩個無攻擊 integration 的結果當作 M9 真 payload E2E。

新 Python 結果可分解成：export builder **11 pass / 13 fail**；獨立 ZIP checker **3 pass / 9 fail**；重疊工作／取消 **1 pass / 3 fail**；最新空批次 **0 pass / 2 fail**；原 wrapper fail-closed **6 pass**；新的 stdout/stderr/timeout spoof **10 pass**；五動作 diamond predecessor gating **1 pass**。總計 **32/27**。

## 本輪問題，按建議修正優先序排列

### 1. R4-01 / P1 — 匯出仍外洩 quoted-key、認證標頭、插值／拼接秘密，最終掃描仍報乾淨

位置：`apps/api/app/poc/export/bundle.py:98`、`:103`、`:193`、`:217`、`:289`、`:320`、`:696`、`:784`。

全部使用合成值 `S = round4-synthetic-credential-K842`。把下列文字放在合法的 IR `description`，真正 `build_bundle` 都產出 ZIP，兩個 scenario JSON/YAML 檔仍含 S（Basic case 保留可還原成 `qa-user:S` 的 base64）。**13 個 builder failures 全部 `contains_secrets=false`，而 `verify_bundle(data)==[]`。**

| case id | 輸入摘要（S 代表合成值） |
|---|---|
| `json-quoted-key` | `{"password": "S"}` 作為 description 字串 |
| `single-quoted-key` | `'password': 'S'` |
| `escaped-json-nesting` | 外層 JSON 字串的 nested 欄位再放一段 `{"token":"S"}` |
| `basic-authorization` | `Authorization: Basic base64(qa-user:S)` |
| `cookie-header` | `Cookie: session_id=S` |
| `protocol-relative-url` | `//qa-user:S@example.invalid/private` |
| `double-quote-in-url-password` | 原始文字 `https://qa-user:public"S@example.invalid/` |
| `shell-concatenated-quotes` | `password='public'"S"` |
| `sql-doubled-quotes` | `password='public''S'` |
| `redacted-prefix-with-secret` | `password=[REDACTED]S` |
| `reference-with-literal-suffix` | `password="${DB_PASSWORD}S"` |
| `inline-generic-default` | `password="${VALUE:-S}"` |
| `inline-generic-error` | `password='${VALUE:?S}'` |

這裡沒有聲稱 literal 雙引號 URL 是合規的 URI，也沒有聲稱任何任意 base64 字串都必須視為秘密。Basic case 有明確的 `Authorization: Basic` 語意；error-branch case 的內容是刻意放入該字串的合成秘密，不是主張所有錯誤訊息都是密碼。即使排除這兩個較特殊的文字案例，quoted JSON password／認證標頭／cookie／插值仍足以阻擋驗收。

根因有數個明確盲點：inline regex 要求 label 後直接接 `:`/`=`，漏掉 label 外的引號；quoted 值只要 `startswith('${')` 就視為安全，bare 值只要 `startswith('[REDACTED]')` 就放過整個值；redaction 只處理拼接值的第一段，保留後面的秘密。URL userinfo 需要 scheme，沒有處理 `//...`。Basic／Cookie 自由文字也沒有對應的最終檢查。解析外層 JSON/YAML 後，`find_field_secrets` 不會再辨識普通 description 字串中嵌入的結構。

checker 的額外 12 cases 直接在乾淨 ZIP 的 scenario JSON 放入未遮蔽合成值，並同步更新該檔 manifest hash，排除單純 checksum failure。**quoted-key、nested JSON、Basic、Cookie、protocol-relative URL、redacted-prefix、reference-suffix、generic-default 共 9 cases 仍回 `[]`**；shell concatenation、完整 percent-encoded query key、nested secret mapping 的未遮蔽輸入則有被抓到。builder 已遮第一段後留下的 shell suffix 仍可穿過最終掃描，故 checker 的那一個正向控制不會推翻 builder 洩漏。

新增百分比編碼 query/欄位名稱、巢狀 credentials map/list、secret-field nested interpolation、普通 quoted password 與舊 URL 格式控制皆安全處理或拒絕匯出，證明 R3 修正有實際作用。新缺口不是舊原格式被 un-fix。

重現：`test_export_new_syntax_removed_or_refused` 的前 13 cases，以及 `test_checker_detects_secret_even_when_hash_is_correct` 的上述 9 cases，共 **22 failures**。需要完整值的安全判斷／可辨識結構處理或拒絕匯出；現況的 false-clean 保證不能保留。

### 2. R4-03 / P2 — cancel 會旗標所有 active job，但 status 只看最新 job，可過早宣稱停止

位置：`apps/api/app/poc/runner/runner.py:334`、`:387`、`:436`；`apps/api/app/poc/service.py:266`；`apps/web/src/pages/PocPage.tsx:422`、`:428`。

R3 的兩個原問題確實修好：status 不再把另一個 job 的 run 混進結果，cancel 也真的會旗標所有 pending/running jobs。不過**接受重疊工作、取消全部工作、只輪詢最新工作的三個語意仍未對齊**。service/store 沒有拒絕同 scenario 的重疊 execute，status 回傳也沒有 job id 供 client 指定／比對。

可達順序：J1/a1 進入受控 transport 等待；J2/a2 開始並完成；J1 尚未完成時呼叫 cancel，再呼叫 status。真 SQLite 觀察值：

```text
cancel response     {cancelled:true}
J1 DB state         running
J1 DB cancel        1
status job_state    done
status per_action   [a2]       # J2 的結果，並沒有混入 J1
```

兩個巢狀確定交錯 cases 及一個**真正兩個執行緒**的 case 都重現。thread case 用 Event 保持 J1 不返回，主執行緒完成 J2、cancel、讀取 snapshot 後才 release J1；不是靠 sleep 猜競態。

GUI `stop` 接受 `{cancelled:true}` 後，收到 `done` 就 `setStopped(true)`。因此它會把 J2 的完成當成 J1 已停止的 confirmation。此處不是指控 cancel flag 遺失，也不是舊的跨 job run 混批再現；是**取消對象和停止確認對象不同**。可拒絕 overlap，或讓 cancel/status/client 共同追蹤同一組工作與 terminal completion。

重現：`test_status_cannot_announce_terminal_while_older_execute_is_running`（2 cases）、`test_real_threads_newer_done_does_not_hide_older_active_from_cancel_confirmation`，共 **3 failures**。另一個雙執行緒控制測試在兩個 jobs 都 active 時取消，確認兩者 cancel flags 均為 1、最終均 cancelled、status 仍只含正確最新 job，**通過**。

風險界線：目前真 transport 仍封閉，這是可用 mock 確認的 job/UI 停止確認缺陷；沒有證明真實 helper 取消後仍繼續執行，也沒有把它併成 deploy #5。

### 3. R4-04 / P2 — 最新 execute 零結果就 cancelled/error 時，chain/report 回退舊批次 PASS

位置：`apps/api/app/poc/chain/validation.py:27`、`:176`；`apps/api/app/poc/chain/report.py:24`、`:77`；`apps/api/app/poc/runner/runner.py:334`；`apps/api/app/poc/service.py:338`。

先用真 runner + artifact/hash/SQLite 產生同批次兩個可獨立 verify 的算術 PASS（僅 delivery 模擬，未替換 verifier）。再建立新 execute job，測兩種正常應誠實處理的路徑：

1. 新 job 剛插入 pending row，就經真正 `cancel_execution` 設取消，第一個 action 尚未開始；execute 回 `[]`，job 終態 cancelled。
2. 第一個 action 的 ownership inspection 丟出合成 OSError；execute 報錯，新 job 終態 error，沒有任何新 run row。

兩種路徑都確認新 job id 與舊 job 不同、零 transport。接著真正 `service.chain` 和 `service.report` 卻回：

```text
latest job:            cancelled / error, no runs
chain.per_action:      a1 PASS, a2 PASS   # 都是舊 job
fidelity.reproduced:   [a1,a2]
```

`_select_runs` 只由 runs 中的最新 started_at 找 job；沒有 run 的新 job 完全不參與選取，故無法阻止回退。report 又給出新的 `run_at`，沒有指出這是較早執行的歷史結果。GUI 即使清掉舊 snapshot，再依這次 report refresh，也會得到 reproduced=2／unverified=0；這與 R4-02 的晚到 response 是不同的後端原因。

**舊 artifacts 本身是真實可驗的歷史合成傳輸證據，不是被偽造或竄改。**問題是它們無標示地充當新 cancelled/error 批次的目前成果；沒有證成新批次 PASS。整鏈仍 false，未發現這條路徑能把無 transfer 的完整鏈改成 PASS。歷史成果可以保留，但最新批次的狀態／provenance 必須明確，不能靜默用舊 PASS 補空。

重現：`test_new_empty_terminal_job_never_reuses_older_verified_passes`（2 cases），**2 failures**。舊 R3 的「最新批次確實有 FAIL/BLOCKED runs」案例仍全過。

### 4. R4-02 / P2 — GUI 清 chain/report 仍留 raw PASS；晚到的舊 callback 也能恢復 PASS

位置：`apps/web/src/pages/PocPage.tsx:352`、`:353`、`:356`、`:454`、`:468`；`apps/web/src/lib/hooks.ts:40`。

新 CJS 直接執行現有 `execAct`、`chainAct`、`reportAct` callback，以及原本 `fid` 和 `statusByAction` 計算。用 deferred Promise 安排 HTTP 完成順序；沒有改寫公式、沒有 React/browser/network，也沒有以 regex 字串存在取代行為檢查。

- **重跑尚在等待**：只清 chain/report，不清 results；舊 raw `[PASS,PASS]` 留在 state。實際 vuln=2/2、scenario=2/2、action badges=PASS/PASS，unverified=2/2，互相矛盾。
- **重跑 fetch reject/abort**：`setResults(d)` 沒有機會執行，以上舊 PASS 長期保留；useAction 只設 error/清 busy，不清資料。舊 R3 測試只覆蓋 execute 已回傳新的 FAIL results，故未抓到這條路徑。
- **新 chain 已 BLOCKED，舊 report 尚在等刷新**：原 chain callback 先 setChain，再非同步 report；unverified 改為 2/2，但 scenario 仍直接取舊 reproduced=2/2。
- **舊 report 回應晚到**：新 execute FAIL、新 report 已取得後，先前 GET /report 才回來；無 generation/snapshot guard，舊 report 覆蓋新 state，scenario=2/2、unverified=0/2，raw results 明明 FAIL/FAIL。
- **舊 chain 回應晚到**：先前 chain request 在新 FAIL execute 之後才 resolve；setChain 放回舊 per_action PASS。action badges 再變 PASS/PASS，unverified=0/2，即使 report 已是新的 not_reproduced。

五個動態情境產生 **8 個 failed checks**；2 個正向控制（重跑前有效單步證據、已回 FAIL 且刷新沒有回來）通過。這不是重新發現已修好的「單純 completed failing rerun 沒清 chain」：舊案例 9/9 全過。現在缺的是 pending/error 的 raw results 失效化與不同請求之間的回應身分。

這些 PASS fixture 代表前輪已證實可由正式 artifact 協定驗證的單步成果；本輪沒有宣稱目前封閉的真 transport 曾發動攻擊。新測試也沒有把 independent 單步 PASS 轉成 full-chain PASS。

## 前三輪 28 項逐一回歸核對

「原案例保持修正」不等於「整類問題再無缺口」。下表全數使用**未修改**的舊測試與前端腳本；#5 原本就沒有完成，不列成已修正。沒有觀察到其餘舊案例被 un-fix。

| R1 finding | 本輪核對 |
|---|---|
| #1 error marker 假 PASS | 舊例與 R2 12 種成功通道變異均過；新 10 種控制字元／JSON 包裝／錯誤／timeout spoof 也無 PASS。 |
| #2 export secrets | 舊 URL/default、R2 與 R3 原格式均過；新格式仍有 R4-01，不能擴大宣稱整類完成。 |
| #3 D6 local attack 禁令 | 原兩類 vulnerable 標記 cases、原 wrapper 的 public batch case 均 BLOCKED、零 launch；本輪亦確認。 |
| #4 額外非 lab network | 舊例及 R2 多網路／non-isolated／member 檢查全過，未見只恢復「存在一張」判斷。 |
| #5 保證取消 | **仍未完成；真 transport 誠實 fail-closed。**唯一舊 failure，詳見下節。GUI 原 terminal polling cases 保持綠，新多 job 確認問題另列 R4-03。 |
| #6 independent/keyword/time order 假全鏈 PASS | 舊例與真 artifacts 的 R2 控制全過；無 production transfer verifier 被放寬加入，整鏈仍不因單步成功變 PASS。 |
| #7 predecessor FAIL propagation | 舊 FAIL/BLOCKED、uncited/transitive、缺選等全過；新五動作 root→兩分支→merge 均阻擋、獨立 sibling 保留 PASS，只有兩次模擬 delivery。 |
| #8 discovery/IR service→compose host | R1 非 canonical fixture 與 R2 canonical host.service_refs 的 discover/plan/execute cases 均過。 |
| #9 artifact/hash/pin/run identity | 舊及 R2 17 種 integrity cases 全過；各 run 仍有獨立 artifacts。最新**有 runs**的批次不拼舊結果；最新零 run job 缺口見 R4-04。 |
| #10 no-verifier upfront／exploit by name | 舊分類與 R2 disabled/substitute cases 均過，沒有以無 verifier 製造 PASS。 |
| #11 BLOCKED/schema | 舊例及 R2 獨立鎖回 nonnullable integer/string 的 public serialization 均過；不是只靠 schema nullable 過關。 |
| #12 discover/chain persistence | 舊 spies 與 R2 真 SQLite 空／非空 discovery、chain、gated BLOCKED 均過。 |
| #13 五個 GUI metrics | R1 4/4、R2 6/6 均過，整鏈 0/1；跨請求與 pending/error 顯示仍有 R4-02。 |
| #14 helper caps | 原 PVE command case 與 R3 local benign helper mock 均過；兩處有 memory=256m、cpus=1、pids-limit=128，已完成。 |
| #15 version ranking | 原 before/through、R2 邊界與 discovery operator 保留 cases 全過。 |

| R2 finding | 本輪核對 |
|---|---|
| R2-01 新 secret formats | 原 8 cases 全過；不表示 R4-01 新格式安全。 |
| R2-02 漏選／not_executable／substitute predecessor | 原三類全過；R3 self/cycle/missing/diamond/prior-job 全過，未以歷史 PASS 滿足當批 required predecessor。 |
| R2-03 cancel transport/batch/GUI | 3a 仍屬 #5；3b 單 job 後續 actions 不啟動；3c reject/error/nonterminal/terminal 原動態 checks 均過。新 overlap confirmation 是 R4-03。 |
| R2-04 one execute one job | 原合法多 action 保留全部結果，R3 FAIL/BLOCKED+sibling 全過；新 diamond 五筆同 job、全部保存也通過。 |
| R2-05 canonical host.service_refs | 原 discover 與 execution-plan cases 均過。 |
| R2-06 helper caps | 原 assertion 全過；#14 不再是待解的 deploy blocker。 |
| R2-07 discovery range operators | 原真正 metadata→ranking 四 cases 與直接 ranking 邊界均過。 |
| R2-08 unverified uses verified evidence | 原「raw PASS 已失效」case 全過；新 request race 尚會重新放回過期 verification，見 R4-02。 |
| R2-09 empty discovery／gated result persistence | 原兩類均過；不是再把 BLOCKED row 遺漏。R4-04 是新 job 尚未產生任何 row 的另一種邊界。 |

| R3 finding | 本輪核對 |
|---|---|
| R3-01 引號／encoded query key／secret map key | 原 builder/checker 15 cases 全過；fresh encoded keys、nested secret map 也過。新 quoted **key**／Basic 等缺口為 R4-01。 |
| R3-02 failing rerun stale chain | 原 3 個負向前端 checks 全過；不再只執行一般已回 FAIL case。新 pending/error/late-response 缺口為 R4-02。 |
| R3-03 overlapping status rows／cancel hidden active job | 原兩 cases 全過；job rows 不混批、active jobs 均可設取消。不同 scope 的停止確認仍有 R4-03。 |
| R3-04 live per_action stage render | 原實際 backend shape 動態檢查通過，liveResults 有一筆可供 ResultCard 顯示的 stage 資料，沒有又改回 live.results-only。 |

## #5 確實 fail-closed，但不是唯一產品缺口

原 `test_cancel_does_not_allow_delayed_launch_after_cleanup_returns` 的唯一 failure 是 `finished.wait(1)`；它仍期待那個已停用的 transport 執行。本輪沒有將它誤報為又發生晚到 helper delivery。

`runner.py:172` 的原 `_probe_with_cancel` 沒有 daemon thread、沒有呼叫 `manager.probe_in_service`。本輪 6 種 backend/already-cancelled 組合，在 ownership 已接受的條件下，恢復原 wrapper 並把真正 launch 設為「一被呼叫即 fail」，全部 BLOCKED／零 launch、零 delivered/responded/vuln_behavior/state_change、只有 log evidence。未修改的 R2/R3 public batch fail-closed cases 也全部通過。這是實際可重跑的封閉證據，不是只看文案。

deploy API 缺口本身也仍存在：`deploy/manager.py:377` 只有同步 `probe_in_service`；`deploy/backends/proxmox.py:949` 在 placement lock 中等待 `_guest_exec`，`:968` 的 QGA pid 留在函式內，逾時只丟例外，沒有供 runner 使用的 start/wait/cancel/join handle 或 pending-launch fence。helper 三個資源 cap 已補，不能替代生命週期保證。這部分是靜態 API 流程確認，**沒有實機 cleanup/timeout 保證實測**。

因此可以確認「#5 是誠實的既有 deferred gap，沒有用假 cancel 過測」，**不能確認「ONLY gap is #5」**：R4-01/02/03/04 都是額外、可在本輪禁部署限制下確認的問題。

## FIX-ROUND-STATUS.md 的宣稱核對

- `:43` 的 review1 **57/1**、review2 **89/0**、review3 **34/0**，這輪逐檔與合跑都重現。268 為實際 suite 總收集數；本輪只執行 266，不替未執行的 2 個 Docker tests 作 PASS 背書，也沒有證據指控 Lead 的歷史 268-pass 記錄是造假。
- `:41–42` 的四項「all fixed」在**原案例**範圍成立；若用來表示秘密掃描、stale verification、多 job cancel/status 整類完整完成，則被 R4-01/02/03 反證。
- `:44`「Sole remaining failure: #5」對三份舊 Python 檔的失敗數仍精確；若用來表示整個產品只剩一項缺口，則不成立。新 Python 27 failures 與前端 8 failures 不能因舊檔綠燈被忽略。
- #14 caps DONE、#5 runner fail-closed 兩點有程式與動態證據，成立；不應把這兩項混成「都只能等 PVE 實機」。
- 真實多服務 exploit E2E 與隔離主機 rebuild 仍未驗收，不能由本輪測試推導已完成。production registry 目前只有 arithmetic proof，沒有 production state-transfer verifier；synthetic chain unit positive 不等於實際多服務 credential/session transfer 的證據。這些既有界線沒有被本輪新列為文件造假。

## 重跑

從本工作樹 `apps/api` 執行，明確載入本工作樹 contracts，關閉 bytecode／pytest cache。暫存目錄只放 review4，報告完成後已清除；下次執行會重建。

```sh
cd /home/tyc4d/cr-project/.worktrees/m9-review4/apps/api
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/tyc4d/cr-project/.worktrees/m9-review4/packages/contracts

/home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider -k 'not test_two_container_up_status_validate_down and not test_container_on_generated_lab_network_cannot_reach_a_host_service' --basetemp=../../reports/overnight/m9/review4/.suite-tmp --tb=short

/home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider ../../reports/overnight/m9/review/test_m9_review.py --basetemp=../../reports/overnight/m9/review4/.r1-tmp --tb=short
/home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider ../../reports/overnight/m9/review2/test_m9_review2.py --basetemp=../../reports/overnight/m9/review4/.r2-tmp --tb=short
/home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider ../../reports/overnight/m9/review3/test_m9_review3.py --basetemp=../../reports/overnight/m9/review4/.r3-tmp --tb=short

/home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider ../../reports/overnight/m9/review/test_m9_review.py ../../reports/overnight/m9/review2/test_m9_review2.py ../../reports/overnight/m9/review3/test_m9_review3.py --basetemp=../../reports/overnight/m9/review4/.prior-all-tmp --tb=short

/home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider ../../reports/overnight/m9/review4/test_m9_review4.py --basetemp=../../reports/overnight/m9/review4/.final-tmp --tb=short
```

```sh
cd /home/tyc4d/cr-project/.worktrees/m9-review4
/home/tyc4d/.nvm/versions/node/v22.23.3/bin/node reports/overnight/m9/review/check_web_behavior.cjs
/home/tyc4d/.nvm/versions/node/v22.23.3/bin/node reports/overnight/m9/review2/check_web_review2.cjs
/home/tyc4d/.nvm/versions/node/v22.23.3/bin/node reports/overnight/m9/review3/check_web_review3.cjs
/home/tyc4d/.nvm/versions/node/v22.23.3/bin/node reports/overnight/m9/review/check_web_typecheck.cjs
/home/tyc4d/.nvm/versions/node/v22.23.3/bin/node reports/overnight/m9/review4/check_web_review4.cjs
```

新腳本目前應失敗；這些普通 failures 是本報告的可重跑證據，沒有標 xfail、刪除舊 assertions 或以一律 BLOCKED 的 verifier 取巧。
