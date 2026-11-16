# Module 9 第二輪獨立 QA

**CHANGES REQUESTED**

受測版本：`638f32464b57c9f0b83b45a5cee3c8b97b956ffc`，工作樹／分支 `m9-review2`／`agent/m9-review2`。日期：2026-11-16（Asia/Taipei）。已先讀根目錄 `AGENTS.md`，並讀第一輪報告、原始重現腳本、`FIX-ROUND.md`、`FIX-ROUND-STATUS.md`、`CONTRACT.md`、`PLAN.md` 與 approved scope D6。

第一輪的錯誤文字製造 PASS、M9 本機攻擊路徑、額外網路、鏈驗證的獨立成功／文字關鍵字／錯誤時序、artifact 與身分驗證，確實有實質改善。但 **56/58 舊重現測試通過，不能等同 15 項已全部修妥**。新探針仍重現秘密外洩、漏選前置動作卻得到 dependent PASS、公開流程拆 job 導致結果遺失，以及 GUI 取消／未驗證數字的過度宣稱。

未編輯既有來源檔、產品程式或第一輪測試；最終 tracked diff 為空。未 add/commit、未啟動其他 Agent、未呼叫 LLM，未操作 Proxmox 或送出真實 exploit。永久新增檔案只有本報告與本目錄兩份獨立腳本。新增探針全部使用合成資料、模擬傳輸、暫存 SQLite 與真正的 runner artifact 寫入器，沒有把 PASS 全部替換成手填字典。

**測試執行限制的例外必須揭露：**我依指定命令執行完整後端 suite，但未先排除它包含的既有無攻擊 Docker 整合測試（`test_two_container_up_status_validate_down`、`test_container_on_generated_lab_network_cannot_reach_a_host_service`）。它們會執行本機 Docker runtime 操作，且此次均 PASS；這與任務「不部署」限制衝突。沒有另行啟動部署或真實 exploit；不能把本次完整 suite 描述成完全沒有 runtime 操作。套件測試內含 teardown，但我沒有再操作 runtime 來獨立確認殘留情形。這些既有無攻擊測試也不是 M9 真實 exploit E2E 證據。

**實際測試結果**

| 檢查 | 結果 |
|---|---|
| `apps/api` 完整既有後端 suite | **242 passed、0 failed、46 subtests passed**；84.96 秒；2 個既有 RefResolver 棄用警告 |
| 未修改的第一輪 `test_m9_review.py` | **56 passed、2 failed**；1.26 秒；失敗仍是 #5 與 #14 |
| 指定的 `app/poc/runner/test_chain_integration.py` | **10 passed**；0.35 秒；傳輸為 mock，artifact 與驗證器是真實實作 |
| 新增 `test_m9_review2.py`（89 cases） | **75 passed、14 failed**；1.84 秒；失敗沒有改成 xfail |
| 第一輪前端行為腳本 | **4 passed、0 failed** |
| 新增 `check_web_review2.cjs` | **2 passed、4 failed** |
| 第一輪唯讀 TypeScript 檢查器 | 本工作樹 **34 個來源檔、0 diagnostics** |
| 真實多動作／多服務 exploit、Proxmox cancel／timeout、乾淨隔離主機重建 | **本次未執行，也沒有取得驗收證據** |

`FIX-ROUND-STATUS.md` 的 228 passed 是中間版本數字；此次基準實際為 242 passed。完整 suite 沒有涵蓋新增獨立 review2 cases，也不會自動收集 repo `tests/e2e/` 下的實機腳本。

**15 項逐一裁定**

| 第一輪項目 | 第二輪裁定與證據 |
|---|---|
| #1 錯誤文字 marker 製造 PASS | **已修正受測路徑。**payload 不再印出 attacker-controlled error reason；成功須 exact stdout marker、空 stderr、exit 0。新測試用 12 種錯誤／混合／重複 marker／非零退出組合全部 FAIL；正向 runner artifact 可 verify PASS。不是只擋第一輪那個 HTTPError 字串。 |
| #2 ZIP 秘密外洩 | **部分修正，仍阻擋。**舊 URL 與 `:-` defaults cases 綠；新格式有 4 個仍洩漏，且 `contains_secrets=false`、`verify_bundle=[]`。見 R2-01。 |
| #3 D6 本機攻擊路徑 | **M9 runner 已封鎖。**本機不分映像分類都不會進 `manager.probe_in_service`；舊兩種映像控制案例及新零 launch 檢查通過。結論只涵蓋 M9 runner，沒有宣稱共享 manager 已全面辨識任意 attack script。 |
| #4 額外非 lab 網路 | **已修正受測路徑。**逐張檢查實際連線；額外 external／edge／其他情境 lab，以及 Internal=false／缺容器成員都拒絕。不是只修第一輪的網路名稱。 |
| #5 取消／晚到 launch | **危險 runner 路徑安全封閉，功能未完成。**原測試失敗是現在根本不呼叫 transport，並非又發生 late delivery；新四種 backend/cancel 組合都零 launch、BLOCKED。真正可取消 handle 尚不存在；公開批次取消與 GUI 仍有缺口，見 R2-03。 |
| #6 independent／keyword／時間順序造鏈 PASS | **鏈演算法受測項目已修正。**以真正可逐步 verify PASS 的同 job artifacts 重測 independent／dependency／temporal；整鏈均 false。反向時間、重疊時間、無時區、缺時間均不通過 order。額外偽造 produced/consumed receipt 檔也不能把 production arithmetic verifier 升成 credential verifier。 |
| #7 FAIL 前置動作 | **部分修正，仍阻擋。**完整選取時 FAIL/BLOCKED 的後續執行有阻擋；同 job 真實可驗 artifact 的 3 步鏈，不論 citation 是否存在，都沿 DAG 得到 FAIL/BLOCKED/BLOCKED。但漏選／not_executable／substitute predecessor 仍讓 dependent 執行並 PASS，見 R2-02。 |
| #8 service／host 對應 | **部分修正。**舊 fixture 的 service.host_ref→compose host 路徑修好，discovery 能讀 canonical host.service_refs；但同一份 canonical IR 到 plan/execute 仍被判 not_executable。見 R2-05。 |
| #9 artifact、pin、run 身分 | **證據驗證有實質修正，公開多動作整合仍有回歸。**17 種 missing/hash/bytes/symlink/cross-run/pin/identity 等變異不再 PASS；重跑不覆寫舊 attempt。單步 runner→chain 10 cases 全過。但 service.execute 為每個 action 建新 job，chain 只採最新 job，丟棄同次 execute 的其他成功動作。見 R2-04。 |
| #10 no_verifier／exploit-by-name | **受測分類已修正。**無 verifier 的正常可部署 nginx exploit upfront not_executable 且有 reason；無 technique 的 Struts exploit 為 poc_exec；disabled service 不執行。substitute 明確為 config_check、poc_required=false，execute 回空結果，沒有把它說成已驗證 exploit。這只證明分類誠實，不證明 benign config_check 已實作執行。 |
| #11 BLOCKED 語意／schema | **公開輸出已實質修正，但舊測試也受 schema 放寬影響。**BLOCKED 沒有被 reinterpret 成 FAIL。當前 schema 已把 exit_code/failure_reason 放寬成 nullable，因此舊 asdict case 本身不足以證明 frozen contract 合規；新測試獨立鎖回原本 integer/string，實際 run_job 的 PASS 與 BLOCKED JSON 仍通過，因 to_dict 會省略 None。 |
| #12 discover／chain 保存 | **部分修正。**非空 discovery 與 chain 真正入 SQLite，export 也包含；但零候選 discovery 無法保存，前置失敗產生的 dependent BLOCKED 也未寫入 runs。見 R2-09。 |
| #13 五個指標 | **部分修正。**失敗整鏈不再顯示逐動作 2/2，而是 0/1；pending/skipped 舊 cases 全綠。但已失效的 raw PASS 仍會讓 unverified=0/2，忽略 chain/report 的未驗證結果。見 R2-08。 |
| #14 helper CPU／memory／PID caps | **未修正，但 M9 runner 目前不會啟動此 helper。**PVE manager 與 local backend 的 helper command 都缺三個限制。這確實位於 deploy 層，但補旗標本身沒有需要實機才能處理的技術阻礙；是跨檔案權責／整合待辦。見 R2-06。 |
| #15 version range | **直接 ranking 已改善，discovery 整合仍高估。**before／through／比較符／wildcard／rc／unknown 10 個額外直接 ranking cases 通過；但 metadata extraction 會丟掉 `after` 或 `<`，把排除的 endpoint 當 exact version，得 version=1.0。見 R2-07。 |

以上「已修正」限定受測路徑；本次沒有實機隔離、並行 filesystem race、真正 callback/state-transfer 或清理保證的實證。沒有把單一 failure fixture 的否定結果當成完整驗證。

**仍需修正的排序清單**

1. **R2-01 / P1 — 匯出仍洩漏合成秘密，而且掃描器回正常（第一輪 #2）。**

   位置：`apps/api/app/poc/export/bundle.py:81`、`:99`、`:102`、`:162`、`:173`。fresh case：`test_bundle_fresh_secret_syntax_does_not_escape_redaction` 的 `quoted-url`、`url-token-username`、`query-token`、`default-error-message`。

   只使用合成值 `round2-qa-only-credential-Z483`。可重現：URL 密碼包含單引號，例如 `https://qa-user:<合成值>'ok@example.invalid/private`；URL 使用 token 作 username、沒有冒號，例如 `https://<合成值>@example.invalid/private`；query 的 `?access_token=<合成值>`。這些值都出現在 `scenario/scenario.json` 與 `.yaml`，manifest 仍為 `contains_secrets=false`，`verify_bundle(data)==[]`。

   第四個 case 是把合成秘密放在 secret-named `password` 欄位的 `${DB_PASSWORD:?<合成值>}`：`:?` 是錯誤訊息分支，**不是密碼 default**；但目前任何匹配 runtime-ref 的 secret 欄位都先原樣放行，這個 literal 也因此出包。此案例不表示所有錯誤訊息都是秘密；它證明 secret 欄位的內容仍可繞過消除與 final scan。巢狀 `:-`、一般 URL、secret-named `:-` 與 generic secret-field default 的控制案例則安全處理。

   原因是 redaction 與最終掃描共用相同窄 regex，兩者一起漏。需按欄位與 URL 結構清理、涵蓋 userinfo/query 與插值各分支；無法確認安全就明確拒絕匯出，不能保留假保證。

2. **R2-02 / P1 — 前置條件只檢查「有加入 reqs 的 action」，可以漏選或跳過前置動作（#7）。**

   位置：`apps/api/app/poc/service.py:319`。`unmet = [... if p in reqs and status.get(p) != 'PASS']` 忽略不在這次執行 requests 的 predecessor。

   新 case `test_predecessor_cannot_be_bypassed_by_selection_or_strategy` 的三種有效情境都失敗：A→B dependency 但只選 B；A upfront not_executable；A 為 substitute config_check。三者 transport 均嘗試 B 一次，回傳 `[('a2','PASS')]`。PASS 是 genuine runner 產物配模擬成功傳輸，不是直接捏造 ExecutionResult。

   全選且 A FAIL/BLOCKED 的案例確實不再執行 B；chain roll-up 也會擋 dependent。因此**沒有證明整條鏈會錯誤 PASS**，但 execution API 與畫面仍可回報前提未成立的單步 PASS，且取消安全封鎖解除後會真的嘗試該動作。必須針對所有宣告的 required_predecessors 驗證同批次可用成功，未滿足就記錄 BLOCKED；不能用「沒選到」視作滿足。

3. **R2-03 / P1 — 保證取消仍待 deploy handle；公開批次取消範圍與 GUI 的停止宣稱也不完整（#5）。**

   `runner/runner.py:172` 現在固定拒絕真實 attack transport。新 `test_real_transport_is_fail_closed_without_launch` 四種組合證明零 `probe_in_service` 呼叫、沒有 delivered/responded/effect evidence。原 #5 的 `finished.wait(1)` 失敗，是它還期待已停用的 transport thread 執行，**不能把這個 failure 重報成 late-launch 漏洞**。

   真正缺口可由 shared deploy API 直接確認：`manager.py:377` 只有同步 `probe_in_service`→`_pve_guest_exec`；`proxmox.py:949` 在 placement lock 內等 `_guest_exec`；`:968` 的 QGA PID 只留在函式內；`:993` timeout 丟例外，沒有 handle、launch fence、cancel/join/finally-kill。這是確實的 deploy API 能力缺口，包 daemon thread 或掃描 helper 無法補出保證；此處的 fail-closed 做法誠實且必要。目前不能把 real execution/cancel 功能列為完成。

   另外兩個跨層問題不必等實機才能修：

   - `test_cancel_public_batch_stops_later_independent_actions` 經真正 `service.execute`／SQLite jobs／`cancel_execution`：第一個 action 收到 `{cancelled:true}` 並回 BLOCKED 後，第二個獨立 action 仍啟動新 job、進入模擬 transport。兩次 transport、兩次成功提出取消。這是 service 為每個 action 新建 job 的取消範圍問題，**沒有在目前封閉 transport 下證明真實 helper 繼續執行**。
   - 前端新腳本直接執行原 `stop` 函式：cancel request 丟錯、回 `{cancelled:false}`、或僅接受取消但未達 terminal 三種情況，一律 `abort` 並 `setStopped(true)`。`PocPage.tsx:385` 的 polling 依賴 `execAct.busy`；abort 讓 `lib/hooks.ts:66` 清 busy 後就停止 polling。`:527` 顯示的 `zh-TW.ts:1213` 卻說「已停止…持續輪詢…直到停止並完成清理」。後端沒有回任何 cleanup 證明，文字不成立。

   需要一個 execute request 對應一個可取消 job，取消涵蓋所有未開始 actions；GUI 保留 polling 到確認 terminal，取消失敗時誠實顯示失敗。這些修正完成前仍需保持真實 attack launch 封閉。

4. **R2-04 / P2 — 公開多動作流程拆成不同 job，chain 丟掉前面的真實有效結果（#9 整合回歸）。**

   位置：`service.py:324` 每次 `run_job(scenario_id,[reqs[aid]])` 都生新 job；`chain/validation.py:27` 的 `_select_runs` 則只取最新 job，避免拼接不同執行批次。

   `test_public_execute_and_chain_keep_each_valid_action_verified`：同一次 `service.execute` 的兩個獨立 Struts 動作，回 `[PASS,PASS]`，各自 `verify_execution==PASS`，兩套 artifacts 與 log 均完整。但兩個 job_id 不同，隨後 `service.chain` 回 `[NOT_TESTED,PASS]`。`run_job` 直接接收兩個 requests 的控制組則保留兩個 per_action PASS，整鏈仍 false。

   不應放寬 chain 去跨任意 job 拼舊 PASS；應讓公開批次的身分、predecessor gating、取消、保存共用同一 job。修好後算術-only 仍必須整鏈未驗證，不能用全鏈 false 掩蓋 per_action 的資料遺失。

5. **R2-05 / P2 — canonical host.service_refs 可 discover，仍無法通過 plan/execute（#8）。**

   `service.py:68` 的 `_service_for` 只讀 `service.host_ref`，既有 `planner/reproducibility.py` 也用同樣過濾；schema 的正式關聯是 `hosts[].service_refs`（`scenario-ir.schema.json:256`），services properties 沒有要求 host_ref。

   `test_normal_ir_host_service_refs_reach_discovery_and_execution_plan` 把舊 fixture 的額外 `service.host_ref` 移除，在 web host 設 `service_refs=['svc-struts']`。Discovery 正常得到候選；plan 卻回 `not_executable`、找不到 service_ref，後續無法執行。沒有把這個誠實 BLOCKED／未執行說成假 PASS；問題是合法 happy path 仍不通。需共用 canonical service resolution，不能只在 discovery 補好。

6. **R2-06 / P2 — per-helper caps 仍沒有落實；屬 deploy 層待辦，不是必須等實機的技術阻礙（#14）。**

   原測試仍重現 `missing ['--memory','--cpus','--pids-limit']`。準確位置是 `deploy/manager.py:387` 的 PVE helper `docker run` 與 `deploy/backends/local_docker.py:250` 的另一條 helper launch command。require_isolation=true、read-only、non-root、cap-drop 等都有；target Compose limits 不會套到另一個 helper。

   #5 需要改 transport lifecycle；#14 的三個限制則能在建構命令時加入並用 mock 斷言確認，不需要執行 payload、取得硬體，或先完成取消 handle。worker 原權責不含 deploy 檔案，能解釋為何交給 Lead，**不能因此宣稱是無法完成的部署環境障礙**。本版真實 M9 helper 不啟動，所以這次沒有資源耗盡實證；外層 worker VM 也有自身上限。

7. **R2-07 / P2 — metadata 範圍解析會先丟掉運算子，再交給修好的 ranking（#15）。**

   位置：`discovery/engine.py:137` `_version_hint`。`test_discovery_preserves_range_operators_before_ranking` 經真正 DiscoveryEngine、模擬 metadata client：目標 `2.3.30`，描述 `versions after 2.3.30` 或 `versions < 2.3.30`，兩者都被抽成 `' 2.3.30'`，version score **1.0**。同 endpoint 的 before 控制組與包含 endpoint 的 through 控制組正確。

   直接呼叫 `score_candidate` 的原始兩個 cases 與額外十個邊界都綠，但不代表真正 discovery 會保留範圍語意。需要完整保留運算子；不能辨識的語法應未知、不可回 exact-match 高分。這是候選 compatibility 過度宣稱，沒有證明會自動執行第三方 PoC。

8. **R2-08 / P2 — unverified 指標仍只看 raw runner PASS，忽略證據失效（#13）。**

   `PocPage.tsx:446` 的 passedIds 只取 `results.status=='PASS'`，沒有讀 chain.per_action 或 report.fidelity。新前端腳本輸入兩筆 raw PASS，但 chain 兩動作為 PARTIAL、report reproduced=[]/partial=[a1,a2]（例如已改 IR、重部署、artifact 被改而失效）。實際輸出：chain **0/1**、scenario **0/2**，unverified 卻 **0/2**，應為 2/2。

   五項仍分開，整鏈 0/1 已正確；剩下的是證據驗證被 GUI 漏用，而不是又把 independent PASS 當整鏈成功。需以目前有效的驗證結果計數，不能讓舊 raw PASS 把失效／未驗證項目移出分母。

9. **R2-09 / P2 — 空 discovery 與編排產生的 BLOCKED 沒有完整保存（#12）。**

   `poc/store.py:157` 只從候選 rows 還原 manifest，`:168` 沒 rows 就回 None。`save_manifest(items=[])` 先刪舊資料後沒有任何記錄，完成過零候選 discovery 也被 export 說成「no PoC discovery recorded」。fresh case `test_empty_but_completed_discovery_is_preserved_for_export` 失敗。

   `test_blocked_dependent_result_is_persisted_for_export` 則得到 API `[('a1','FAIL'),('a2','BLOCKED')]`，SQLite 只有 `[('a1','FAIL')]`。`service.py:319` 產生 `_blocked_result` 後未 save_run；只有真的進 run_job 的結果會保存，export 遺失畫面已看到的 B 阻擋原因。非空 manifest 與已呼叫的 chain 結果確實已存且可在 bundle 讀回，正向控制通過。

**runner↔chain 協定的正向證據與界限**

指定 integration 檔 10 cases 全通過，且我另寫的正向 fixture 也讓實際 `run_job` 產生 SQLite row、每次不同 run_id 的 effect/log 檔與正確 hash；沒有 monkeypatch `verify_execution`、registry 或 `_write_artifact`。log 包含 action/status/start/end/payload/proof/context/ownership/evidence，context 的 job/scenario digest/deployment id 能與當前資料相符，這種 artifact 可以得到單動作 PASS。

修改 IR、部署 id、effect bytes、log bytes、pin、path/hash、job/scenario 身分、failure_reason、exit code 等後，驗證不再 PASS。重跑也沒有覆寫舊 attempt。這些控制證明 #9 不是只靠把所有結果降成 PARTIAL 來通過負向測試。

同一批兩個合法算術 PASS 沒有 transfer verifier，因此整鏈 false；即使手工加入 hash 相符且相互引用的 produced/consumed state receipt，production proof 沒有 `state_transfer_types`，仍不能驗 credential transfer。現有 production registry 只有這個 arithmetic proof，因此**目前沒有 production state-transfer verifier 可證成多服務完整鏈**。`chain/test_chain.py` 的全鏈正向 case 使用測試專用 registry entry，檔首也坦承是 synthetic fixture；它可以驗演算法，不能當成實際攻擊鏈 E2E 已完成。

真實 transport 目前全部 fail-closed；以上正向 PASS 證明的是模擬成功 delivery 之後的合法 log/artifact 協定，**不是這版已完成一次真實 exploit**。`FIX-ROUND-STATUS` 的誠實封鎖說明成立，但舊 `requests/m9-runner.md`、runner report 的「real exploitation is attempted」／bounded wrapper 等敘述與現況已過時；GUI 的 finally-kill／已清理文案也不能引用為完成證據。

**重跑方式**

後端皆從此 worktree 的 `apps/api` 執行；指定本 worktree contracts，避免 editable package 載入主 checkout。新增 cases 的暫存目錄設在 review2，完成後可刪除。完整 suite 以下命令僅記錄已做的執行；**若仍維持禁止部署，重跑前應先排除前述兩個既有 Docker integration，並把實際 pass/skip 數另記，不能把排除後結果冒充本次 242 passed**。

```sh
cd /home/tyc4d/cr-project/.worktrees/m9-review2/apps/api
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/tyc4d/cr-project/.worktrees/m9-review2/packages/contracts /home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/tyc4d/cr-project/.worktrees/m9-review2/packages/contracts /home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider ../../reports/overnight/m9/review/test_m9_review.py --tb=short

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/tyc4d/cr-project/.worktrees/m9-review2/packages/contracts /home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider app/poc/runner/test_chain_integration.py --basetemp=../../reports/overnight/m9/review2/integration-tmp --tb=short

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/tyc4d/cr-project/.worktrees/m9-review2/packages/contracts /home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider ../../reports/overnight/m9/review2/test_m9_review2.py --basetemp=../../reports/overnight/m9/review2/pytest-tmp --tb=short
```

```sh
cd /home/tyc4d/cr-project/.worktrees/m9-review2
/home/tyc4d/.nvm/versions/node/v22.23.3/bin/node reports/overnight/m9/review/check_web_behavior.cjs
/home/tyc4d/.nvm/versions/node/v22.23.3/bin/node reports/overnight/m9/review/check_web_typecheck.cjs
/home/tyc4d/.nvm/versions/node/v22.23.3/bin/node reports/overnight/m9/review2/check_web_review2.cjs
```

最後一次獨立測試結果：`14 failed, 75 passed, 2 warnings in 1.84s`。前端新腳本的 failure 實際為：unverified 證據失效數字，以及 cancel failed/rejected/requested 三種情況都無 terminal confirmation 就顯示 stopped。沒有以型別全綠或原套件全綠覆蓋這些負向證據。

**CHANGES REQUESTED — 優先序：R2-01 秘密外洩 → R2-02 前置動作繞過 → R2-03 真正取消與批次／GUI 誠實性 → R2-04 job 協定 → R2-05 canonical service mapping → R2-06 helper caps → R2-07 範圍解析 → R2-08 未驗證數字 → R2-09 保存完整性。**
