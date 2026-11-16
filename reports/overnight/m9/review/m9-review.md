# Module 9 獨立 QA

**判定：CHANGES REQUESTED**

- 檢查基準：`97ae105ad02c83a9718c2ada02ed0c4c5f1045e5`，本工作樹分支 `agent/m9-review`。
- 日期：2026-11-16（Asia/Taipei）。規格：同目錄上層 `PLAN.md`（含 Acceptance）、`CONTRACT.md`、`docs/approved-scope.md` 的 D6。
- 已讀根目錄 `AGENTS.md`；未修改產品原始碼，未 add/commit，未啟動其他 Agent，未呼叫 LLM API。新增內容僅本 review 目錄的報告與檢查腳本。
- 本次沒有另行執行漏洞部署、真實 payload 或 Proxmox 實機操作。新增檢查全部使用模擬傳輸、記憶體內 ZIP／artifact 寫入替身；不讀取或展示真實憑證。後端既有全套測試依任務指定命令執行。
- 原有測試全綠，**不代表驗收通過**：新增負向案例重現了錯誤 PASS、秘密外洩、本機攻擊路徑、隔離與中止缺口。

## 實際執行結果與重跑方式

| 檢查 | 實際結果 |
|---|---|
| `apps/api` 全套既有測試 | **171 passed、0 failed，7 subtests passed**；84.49 秒；2 個 `jsonschema.RefResolver` 棄用警告 |
| 本次獨立 Python 契約／負向案例（58 cases） | **32 passed、26 failed**；0.23 秒；同樣 2 個警告；失敗保留為修正證據，沒有標成 xfail |
| 本工作樹前端 TypeScript 檢查 | **34 個來源檔、0 diagnostics** |
| 執行既有前端純 fidelity 計算（4 checks） | **1 passed、3 failed** |
| 真實多動作／多服務 M9 exploit E2E | **未執行，未取得驗收證據**；任務明令禁止真實部署與 exploit |
| 匯出後在乾淨隔離主機重建 | **未執行，未取得實機重建證據** |

後端命令（已明確覆蓋 editable `cr_contracts`，警告路徑也確認載入的是本工作樹）：

```sh
cd /home/tyc4d/cr-project/.worktrees/m9-review/apps/api
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/tyc4d/cr-project/.worktrees/m9-review/packages/contracts /home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider
```

原有全套輸出結尾：

```text
171 passed, 2 warnings, 7 subtests passed in 84.49s (0:01:24)
```

獨立檢查（同樣在 `apps/api`）：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/tyc4d/cr-project/.worktrees/m9-review/packages/contracts /home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider ../../reports/overnight/m9/review/test_m9_review.py --tb=short
```

```text
26 failed, 32 passed, 2 warnings in 0.23s
```

原始 `npm run typecheck` 因 PATH 沒有 npm 而無法啟動；工作樹也沒有 `node_modules`。隨後使用主 checkout 已安裝的 Node/TypeScript/依賴，透過唯讀 CompilerHost 檢查**本工作樹**來源及本工作樹 `@contracts`，不安裝、不複製、不修改來源或 tsconfig：

```sh
cd /home/tyc4d/cr-project/.worktrees/m9-review
/home/tyc4d/.nvm/versions/node/v22.23.3/bin/node reports/overnight/m9/review/check_web_typecheck.cjs
/home/tyc4d/.nvm/versions/node/v22.23.3/bin/node reports/overnight/m9/review/check_web_behavior.cjs
```

```text
Checked 34 worktree source files; 0 diagnostics.
PASS five metrics remain separate
FAIL failed full chain is not shown as 2/2 passed: passes=false, display={n:2,total:2}
FAIL not yet executed actions are counted as unverified: {n:0,total:2}
FAIL skipped actions remain visible as unverified: {n:0,total:2}
1 passed, 3 failed
```

## 排序後問題

以下順序為建議修正優先序。P1 是驗收／安全阻擋；P2 是必須修正的契約、完整性或介面缺陷。每項皆列出可重跑的獨立 case；來源行號以受測 commit 為準。

### 1. P1 — 已釘選的真實 payload 發生 HTTP 錯誤，也能被判為 PASS

- 位置：`apps/api/app/poc/runner/payloads.py:17`、`runner/runner.py:232`、`:247`。
- payload 把 `HTTPError` 例外文字印出；verifier 在合併的 stdout/stderr 中做 `marker in output`，沒有區分成功 header 與錯誤訊息。
- 重現：用標準庫 `HTTPError(..., 500, 'VULHUB_HEADER=54289', ...)` 建立**合成錯誤文字**，模擬 pinned payload 的輸出 `REQUEST_ERROR=HTTPError:HTTP Error 500: VULHUB_HEADER=54289`。原 payload、source、proof_id、SHA 均未更改，執行器卻回 **PASS**，並產生宣稱 exploit effect 的證據。未送任何真實 HTTP 請求。
- case：`test_registered_payload_error_containing_marker_must_not_pass`。
- 必須把成功判斷綁定於已驗證的成功回應欄位，排除錯誤路徑；不能只搜尋任意輸出中的固定字串。

### 2. P1 — ZIP 會帶出密碼，仍宣稱 contains_secrets=false、verify_bundle 無錯誤

- 位置：`apps/api/app/poc/export/bundle.py:95`、`:123`、`:143`、`:153`、`:481`、`:495`。
- 兩個獨立合成輸入都外洩：IR 自由文字內的 `https://qa-user:<合成密碼>@example.invalid/private`；以及 secret 欄位內的 `${DB_PASSWORD:-<合成密碼>}`。
- 前者沒有處理 URL userinfo；後者被 `_RUNTIME_REF_RE` 當成安全引用原樣保留，忽略預設值本身就是密碼。最後掃描沒有抓到，`scenario/scenario.json` 與 `.yaml` 都保留值，`contains_secrets=false`，`verify_bundle(data)==[]`。
- cases：`test_export_removes_synthetic_credentials[url-userinfo]`、`[compose-default]`。測試值完全合成，沒有接觸真實密碼。
- 必須處理 URL credentials 與秘密引用的 literal default，並用成品掃描覆核。現有「包內不含任何真實密碼」保證過度。

### 3. P1 — D6 只擋漏洞映像，未硬擋本機 Docker 的攻擊 payload

- 位置：`apps/api/app/poc/runner/runner.py:220`、`apps/api/app/deploy/manager.py:385`、`deploy/backends/local_docker.py:235`。
- `SandboxRunner` 沒有針對 local-docker 的攻擊執行禁令；底層只看 generated report 的 `vulnerable` 標記。
- 同一個已註冊 Struts 真實 payload，當目標報告是非漏洞映像時，穿過真正的 manager/local-docker 控制邏輯，呼叫 Docker transport 一次，結果 `FAIL`、`delivered=true`，而非應有的 **BLOCKED／零執行**。本次 transport 是 mock，沒有開容器。
- case：`test_d6_blocks_attack_payload_even_for_non_vulnerable_image`。控制 case `test_control_d6_known_vulnerable_image_blocks_before_docker_run` 有通過，證明現有 gate 只涵蓋部分路徑。
- D6 的「本機 Docker 只做非攻擊類 QA」應直接約束 M9 payload 執行，不能依映像分類推定是否為攻擊。

### 4. P1 — ownership guard 只要求至少一張隔離網路，忽略額外外部網路

- 位置：`apps/api/app/poc/runner/guard.py:112`、`:118`、`:129`。
- 容器同時連接已驗證 lab network 與額外 `non-experiment-external-network` 時，guard 跳過額外網路，只要找到一張合格網路就回傳 owned。
- case：`test_guard_rejects_any_additional_non_lab_network`，預期拒絕但沒有丟出 `TargetBlocked`。
- helper 分享的是 target 整個 netns，因此額外介面仍可使用。這是本機 guard 的隔離繞過；結合上一項非漏洞映像 D6 缺口，控制流程可以放行攻擊 payload。沒有對外連線實測，也沒有證明可繞過 Proxmox 的 VM pool guard。
- 必須檢查所有實際連線與外連路徑，不能只確認「存在一張」合格網路。

### 5. P1 — 取消／逾時沒有保證終止 helper，晚到的執行仍可繼續

- 位置：`apps/api/app/poc/runner/runner.py:90`、`:121`、`:127`、`:139`、`:143`；`apps/api/app/deploy/backends/proxmox.py:949`、`:993`；`apps/web/src/pages/PocPage.tsx:377`。
- `_probe_with_cancel` 啟動 daemon thread，取消時只掃描一次 helper 後返回，沒有可取消的程序 handle、join 或保證性的 finally-kill。若掃描當下 helper 尚未出現，底層呼叫稍後仍可建立 helper。
- case：`test_cancel_does_not_allow_delayed_launch_after_cleanup_returns`，用 threading Events 模擬「啟動未完成→收到取消→清理找不到→原呼叫繼續」；回傳 125 後，模擬 transport 仍到達 delivery。
- 多個相同 action/payload 並行會讓清理匹配數不等於一，`:121` 明確放棄移除。PVE guest timeout 只丟例外，manager 將其變成 127；runner 對 127 路徑未嘗試清理。`--rm` 只有程序結束時才生效。
- PVE `guest_exec` 在 placement lock 內執行整段 polling；清理也經 `guest_exec`，可能等待同一把鎖，並非及時 emergency stop。這點為靜態流程分析，未在實機壓測。
- GUI 只 abort fetch，沒有呼叫已存在的 `/execute/cancel` 或 poll `/execute/status`。文案坦承只是「停止等待」，但仍未提供驗收需要的真正中止；文案還過時地稱沒有取消路由。case：`test_gui_stop_calls_backend_cancel_and_polls_job`。

### 6. P1 — 攻擊鏈可由獨立 PASS、文字關鍵字或錯誤時序得到 PASS

- 位置：`apps/api/app/poc/chain/validation.py:43`、`:67`、`:73`、`:112`、`:135`。
- 無任何 relation/transfer 的兩個獨立 PASS，`all([])` 及 `len(transfers)==len(edges)==0` 讓整條鏈 `passes=true`、`objective_reached=true`。case：`test_chain_independent_action_passes_do_not_prove_full_chain`。
- dependency 有 citation 時，只要前一步 evidence.note 含 `cred`、下一步 precondition 含 `cred`，就標 `verified=true`。沒有證明哪個憑證被產生、傳遞、消費；單純 Struts 算術 proof 配上這個文字也可讓鏈通過。case：`test_chain_transfer_requires_consumed_state_not_note_keywords`。
- `order_ok` 只看 results 陣列位置，不看 started_at/ended_at；下一步實際早於前一步一小時，仍 `order_ok=true`、`passes=true`。case：`test_chain_checks_actual_time_order_not_list_position`。
- 必須驗證可追蹤的執行狀態傳遞與實際時序；沒有鏈證據時保留未驗證。

### 7. P1 — predecessor FAIL 不能可靠阻擋 dependents

- 位置：`apps/api/app/poc/runner/runner.py:300`、`poc/service.py:209`、`chain/validation.py:124`。
- 執行批次沒有讀取 `required_predecessors` 或前一步結果。真實 service→run_job 流程中，把 sandbox 替換為受控結果，A=FAIL 後仍執行 B，回傳 B=PASS。case：`test_real_batch_orchestration_blocks_dependent_after_fail`；觀察 attempts=`['a1','a2']`，結果=`[('a1','FAIL'),('a2','PASS')]`。
- roll-up 只做一次、只對 cited edges 的 FAIL/BLOCKED 降級：A FAIL→B PARTIAL→C PASS；未引用 citation 的已宣告 dependency，或 plan.required_predecessors，也不阻擋 B 的 PASS。
- cases：`test_chain_failure_propagates_transitively`、`test_chain_uncited_failed_predecessor_cannot_leave_dependent_pass`。
- 必須在執行前阻擋不滿足的前置條件，並讓報告沿 DAG 傳遞阻擋，不能把降級後的中間步驟視為可用前提。此修正不應憑空新增原文沒有的 dependency。

### 8. P1 — 正常 IR 的 service/host 對應讓 discovery 或 execute 無法走通

- 位置：`apps/api/app/poc/discovery/engine.py:38`、`:43`；`poc/service.py:86`、`:222`；`iac/generator.py:701`、`:706`。
- Discovery 只用 action.service_ref 找 service；既有 IR 的正常 action 使用 target_host_ref，沒有 service_ref 時不會查該 host 的 service/CVE。Struts fixture 即使提供匹配的 mock PoC，仍回傳空 manifest。case：`test_discovery_resolves_service_through_normal_target_host_ref`。
- execution 把 IR service.id 當成 Docker Compose service id，但 generator 用 environment host.id。真實 generator 的 fixture 產生 `services=['web']`，service.execute 建立的 request 卻是 `service_ref='svc-struts'`，guard 會拒絕不存在的服務。case：`test_service_maps_ir_service_to_actual_compose_host`。
- 既有 Struts e2e 直接手建 `ExecutionRequest(service_ref='web')`，繞過 service.execute，無法覆蓋此整合缺陷。需使用已存在的 IR→environment-plan mapping，並由公開 M9 API 驗證 happy path。

### 9. P2 — chain 的「證據驗證」不驗證 artifact、hash 或 PoC pin

- 位置：`apps/api/app/poc/chain/evidence.py:15`、`:20`、`:45`；`poc/store.py:204`；`chain/validation.py:91`。
- `proves_effect` 只檢查 kind 與非空 path/hash，沒有檔案存在、內容雜湊、允許根目錄、registered verifier、payload SHA 一致性或部署關聯驗證。
- case：`test_verification_rejects_missing_artifact_and_unregistered_payload`，不存在的 artifact，加上不在 registry 的 GitHub source、空 ref 與零 SHA，仍被 `verify_execution` 判 PASS。這是 aggregation 函式輸入／持久化完整性缺陷；**未發現可以直接由 HTTP 上傳任意 ExecutionResult 的入口**，不要誤解為已證明遠端注入。
- store 讀取同 scenario 所有歷史 runs，chain 以每 action 最後一筆拼接，沒有同一 job／IR version／deployment 的一致性 gate；重部署或改情境後，舊 action 成功仍可能被沿用。
- runner artifact 路徑只依 scenario+action，重跑會覆寫該 action 的 log，歷史 run 的 hash 可能失效（`runner/runner.py:165`）。需使用 run identity，並於 roll-up 確認 artifacts 與部署仍對得上。

### 10. P2 — 無 verifier 沒有 upfront not_executable，部分 exploitation 被降為 config_check

- 位置：`apps/api/app/poc/service.py:36`、`:107`、`:215`、`:232`。
- 對可部署 nginx 的 exploit action，沒有任何 registered verifier，plan 仍標 poc_exec/poc_required；execute 則默默略過，可能只回 `[]`，沒有 reason 或 job。case：`test_plan_marks_no_verifier_not_executable_before_execution`。
- 相同 Struts exploit action 若只缺 attack_technique，既有 classifier 能辨識名稱中的 exploit，但 M9 `_is_exploitation` 只看 technique，標成 config_check，execute 全略過。case：`test_exploit_named_action_without_technique_still_requires_real_payload`。
- needs_vm/not_reproducible 的既有 plan 與 `not_executable` aggregation 控制案例通過；缺口是沒有 compatible/vetted verifier 這一類沒有被誠實分類，以及名稱已明示 exploit 卻不執行。沒有觀察到這些 skipped items 直接被 runner 假造為 PASS。

### 11. P2 — BLOCKED 被改成 FAIL，runner JSON 也違反凍結 schema

- 位置：`apps/api/app/poc/chain/evidence.py:47`、`:49`；`runner/runner.py:233`、`:236`、`:276`；`poc/models.py:121`；`packages/contracts/schemas/poc-validation.schema.json:166`。
- 模擬 timeout 時，runner 正確回 BLOCKED；因 delivered/responded=true，roll-up 先走 FAIL 分支，把環境／中止問題當 exploit FAIL。case：`test_timeout_blocked_is_not_reinterpreted_as_exploit_fail`。
- `asdict` 將 optional 欄位序列化成 null，但 schema 只允許省略，不接受 null：ownership-blocked 的 `exit_code=None` 違反 integer；成功結果 `failure_reason=None` 違反 string。兩個 `test_runner_output_matches_execution_result_schema` case 均失敗。router 沒有 response validation 掩住此差異。
- 必須保留 BLOCKED 意義，並統一 JSON 與契約的 optional 表達方式。

### 12. P2 — discover/chain 成果沒有儲存，export 會漏掉已完成結果

- 位置：`apps/api/app/poc/service.py:189`、`:242`；`poc/store.py:133`、`:217`；`export/bundle.py:311`、`:317`。
- service.discover、service.chain 直接 return，沒有呼叫現成的 save_manifest/save_chain；subpackage 也沒有補存。畫面看到結果後 export 查 SQLite 仍無資料，PoC manifest 缺漏、results 中 chain_validation 為 null。
- cases：`test_discovery_is_persisted_for_export`、`test_chain_is_persisted_for_export`，兩個 save spy 均 0 次。
- 匯出的 fidelity report 雖重新推導 chain，但不會補回原本應存的 chain record 或 discovery manifest；不能宣稱完整保存已完成流程。

### 13. P2 — 五個 fidelity 指標有分開，但「端對端攻擊鏈」仍錯用逐 action PASS 比例

- 位置：`apps/web/src/pages/PocPage.tsx:402`、`:414`、`:420`；`:527`；`apps/web/src/i18n/zh-TW.ts:1272`。
- 沒有合併成單一成功率，這點通過；但 end-to-end chain 的顯示是 per_action PASS 數，完全沒看 chain.passes/objective_reached/transfers。當兩步獨立成功、transfer 未驗證、chain.passes=false 時，該指標仍顯示 **2/2 通過**，與旁邊鏈 FAIL 互相矛盾。
- 尚未執行的兩個 poc_exec action 顯示 unverified=0/2；被靜默 skipped、report.not_tested 有兩個時仍 0/2。deployment readiness 也把所有非 not_executable 視為可執行，放大第 10 項影響。
- 證據：`check_web_behavior.cjs` 直接抽取並執行既有 `fid` 純函式，不重寫計算公式；1 pass、3 fail。

### 14. P2 — sandbox helper 缺自己的資源上限

- 位置：`apps/api/app/deploy/manager.py:388`；`deploy/backends/local_docker.py:250`。
- helper 有 --rm、--pull=never、read-only、non-root、cap-drop、no-new-privileges、tmpfs，這些符合隔離模式；但沒有 --memory、--cpus、--pids-limit。目標 Compose 的 limits 不會自動套到另一個 docker run helper。
- case：`test_pve_helper_has_explicit_cpu_memory_pid_caps`，三個限制全部缺少；也確認傳到 guest_exec 的 require_isolation=true。
- Proxmox worker VM 本身的 CPU/記憶體仍有外層上限，因此本項不是宣稱主機完全無資源保護；問題是 CONTRACT 明訂的每次 sandbox 資源 cap 沒有落實。

### 15. P2 — version ranking 將區間當字串端點，會高估不相容版本

- 位置：`apps/api/app/poc/discovery/ranking.py:24`、`:30`。
- target=2.15.0、range=`before 2.15.0` 卻得 version=1.0；target=2.10.0、range=`2.0.0 through 2.14.1` 卻得 0.05。
- 兩個 `test_discovery_version_range_means_range_not_endpoint` cases 均失敗。目前 discovery 不會直接執行第三方 code，因此這不是已證明的 arbitrary code execution；它是 compatibility 宣稱與候選排名錯誤。

## 八項指定驗證對照

| 指定項目 | 結果與證據 |
|---|---|
| 真 payload／具體證據／不捏造 PASS | 內建 registry + SHA + payload/source/method/marker 比對存在；unvetted code、改寫 payload、HTTP200/健康/LLM 文字、patched response 控制 cases 都擋住或 FAIL。**但 HTTPError 字串可造 PASS（#1），chain verifier 沒驗證檔案／pin（#9），no-verifier 無 upfront 分類（#10）。** |
| ownership、protected、pool、每次執行前守門 | runner 在 adapter/transport 前呼叫 assert_target_owned；9 個 protected VMID、無部署、錯 labels、非 cr-range 的控制 cases 通過。PVE backend 再驗 active reservation、pool、tags、description。**額外外部網路可繞過本機隔離檢查（#4）。** 沒有實機嘗試接觸非授權主機。 |
| local D6／PVE confirmed isolation | 漏洞映像 D6 控制通過；PVE 缺 checked/isolated/evidence 都在 guard 被拒，實際 manager command 帶 require_isolation=true。**非漏洞映像仍可送攻擊 payload（#3）**；PVE live path 未實跑。 |
| chain、predecessor、不可發明 dependency | 實作只挑 IR relations 中指定 kind 且有引用的 edges，沒有自動把 temporal 變成 dependency。**獨立 PASS／keyword transfer／時序／前置失敗均有缺陷（#6、#7）**；未引用的 dependency 並未讓整鏈 PASS，但其 dependent 仍可能單步 PASS。 |
| export 真 artifacts／不造 IaC／無秘密／重建誠實 | 真 generator compose bytes、per-file hashes、沒有捏造 terraform/ansible 的獨立控制通過；既有 missing VM/closed-source/stale IaC 測試通過。原始 evidence 只列 index，README 有坦承未夾帶。**合成憑證洩漏（#2）、持久化缺漏（#12）阻擋驗收；未作乾淨主機重建。** |
| 五 metrics 不合併 | backend buckets 與 GUI 五欄分開，沒有單一 combined success rate。**數值語意錯誤仍會高估鏈驗證（#13）。** |
| 後端全套／前端型別 | 原有全套 **171 pass / 0 fail + 7 subtests**；本工作樹前端 **0 diagnostics**。獨立負向測試 **26 fail / 32 pass**。 |
| 過度宣稱／危險預設 | 存在錯誤 PASS、contains_secrets=false 假保證、D6 路徑、清理「best-effort」未達 guaranteed cleanup、2/2 chain 假象。PLAN 的「無 Proxmox code」描述也已與本 commit 不符，應更新規格說明，不能當成 PVE 路徑已驗收。 |

## 尚未成立的實機驗收

- `tests/e2e/m9-runner/test_struts_proxmox_product_flow.py` 只有一動作、一服務，而且直接呼叫 SandboxRunner；不涵蓋公開 discovery→execute→chain→export 流程，也沒有真正驗證 state transfer。
- 該測試位於 repo `tests/e2e/`，不在從 `apps/api` 執行的預設全套收集範圍；不能把 171 passed 說成「真實 M9 exploit E2E 已過」。本次依禁止真實部署／exploit 的任務限制，沒有另行執行它。
- 模組至少一條多動作、多服務真實鏈、成功與失敗證據、cancel/timeout 無殘留、clean isolated box 重建，目前都沒有由本次 QA 證明。修正後仍需由獲准執行實機操作的 Lead 補驗。

**CHANGES REQUESTED — 先處理排序 #1–#8 的安全與主要流程問題，再補齊其餘契約修正與真實多服務驗收。**
