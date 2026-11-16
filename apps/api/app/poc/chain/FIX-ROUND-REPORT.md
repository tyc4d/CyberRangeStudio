# m9-chain Fix Round 1

日期：2026-11-16（Asia/Taipei）。工作樹：`agent/m9-chain`。

## 判定

**本分工修正與本地回歸通過；尚非整體 M9／實機 E2E 驗收。**

- 指定 6 個 chain 負向案例、timeout/BLOCKED 案例及 not_executable 控制案例：**8 passed**，原 QA 檔案完全未改。
- 最終後端全套：**195 passed, 2 warnings, 11 subtests passed in 84.53s**。
- 修正前基線：**171 passed, 2 warnings, 7 subtests passed in 84.53s**。
- 原 7 個 chain 測試方法保留，新增 24 個測試方法。正向 fixture 換成實際暫存檔、正確 SHA、部署與批次身分、結構化產生／消費收據；前置失敗的預期由 PARTIAL 收緊為 BLOCKED。
- 本地整份獨立 QA：**39 passed / 19 failed**。剩餘 19 個皆屬 runner／discovery／export／GUI／Lead 的檔案分工，未誤報成整體全綠。
- `git diff --check` 通過。未執行 git add/commit；Lead 已代提交中間版本 `8becd85`，其後最終補強留在本工作樹交由 Lead 收取。

原始測試輸出保存在 `qa/baseline-tests.txt`、`qa/final-tests.txt`；完整 QA 失敗項目與摘要保存在 `qa/review-summary.txt`。

## 修正內容

1. **#6 鏈成立條件**：獨立 PASS 不代表整鏈 PASS；需有被 IR 證據引用的已宣告依賴、完整有向無環圖、實際時間順序，以及已驗證狀態傳遞。以 timezone-aware started_at/ended_at 確認前步結束不晚於後步開始；陣列順序無法替代時間證據。缺時間、重疊、反向、循環、未知端點、分離的圖均不會令整鏈 PASS。
2. **#6 傳遞證據**：不再從 note/precondition 關鍵字產生驗證結果。註冊 verifier 必須明確支援該類狀態；產生與消費收據須匹配狀態 id、值 SHA、來源 action/run，以及實際被消費的來源 artifact 路徑與 SHA。生產／消費紀錄各自綁定所屬 log 與執行，且同一批次、正確時序、兩步皆 PASS。現有 Struts 算術 verifier 沒有憑證傳遞能力，不能拿來證明 cred transfer。
3. **#7 傳遞阻擋**：依 IR 已宣告 dependency/causal 進行拓樸處理；任何未 PASS 前置步驟會讓其 dependent 變為 BLOCKED，傳遞至後續動作。未引用 citation 的已宣告依賴仍可阻擋。僅有 plan.required_predecessors、但 IR 沒宣告關係時會保守阻擋該要求，不憑空建立可通過的 edge。執行前 gate 仍由 Lead 的 service.execute 負責。
4. **#9 證據完整性**：artifact 必須存在於 DATA_DIR/poc-runs 之內、為檔案、SHA 相符，且不能經符號連結或跨 run 路徑重用。PASS 必須使用 registry 內的 verifier、來源與 payload SHA 相符、成功輸出精確行與 effect artifact 相符；log/result/action/time/payload/evidence 均互相綁定。log.context 的情境 SHA 與部署紀錄 id 需符合目前 IR 與健康部署。缺檔、舊情境、重部署、未註冊 payload、篡改或身分不足均不會 PASS。
5. **#9 批次一致性**：以最新 attempt 所在 job 的 immutable run 身分挑選結果；不將歷史不同批次依 action 最後一列拼在一起。新批次未執行的動作為 NOT_TESTED；同批次重複 attempt、損壞的中途／最新 attempt 不會讓舊成功被沿用。
6. **#11 BLOCKED 語意**：取消／逾時等 BLOCKED 優先保留，不因 delivered/responded 改判 exploit FAIL。
7. **#13 backend 指標**：維持既有 ChainValidation schema，`passes` 與 `objective_reached` 是獨立整鏈判定。FidelityReport 增加 category=chain 檢查，清楚列出這兩個值、order_ok 與 verified transfers；兩步個別 PASS 但鏈未驗證時 full_chain=PARTIAL。環境 FAIL 優先，不會被 PARTIAL 覆蓋。原五項 fidelity bucket 仍分開。

## 指定 QA 案例

以下均通過：

- `test_chain_independent_action_passes_do_not_prove_full_chain`
- `test_chain_transfer_requires_consumed_state_not_note_keywords`
- `test_chain_checks_actual_time_order_not_list_position`
- `test_chain_failure_propagates_transitively`
- `test_chain_uncited_failed_predecessor_cannot_leave_dependent_pass`
- `test_verification_rejects_missing_artifact_and_unregistered_payload`
- `test_timeout_blocked_is_not_reinterpreted_as_exploit_fail`
- `test_control_not_executable_never_passes`

QA 原檔 SHA-256：`1daa50fc2eb7532e5fdac257337f60f4fb7559671866581bb4630f4c5ad7ec71`。

## 重跑

在本工作樹 `apps/api`：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/tyc4d/cr-project/.worktrees/m9-chain/packages/contracts /home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/tyc4d/cr-project/.worktrees/m9-chain/packages/contracts /home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider ../../reports/overnight/m9/review/test_m9_review.py --tb=short
```

## 整合需求與驗證限制

詳細協定見 `reports/overnight/m9/requests/m9-chain.md`，已透過 hc 回報 Lead。

最終自查唯讀檢視當時 `agent/m9-base` 的 runner，仍使用 scenario/action/run_id 路徑，log 缺頂層 started_at/ended_at/payload_sha256/proof_id/evidence，與已約定協定尚未對齊。**這類紀錄目前會保持 PARTIAL；負向 QA 全綠不能證明合法 runner 結果已可 roll-up PASS。** 請 runner／Lead 依 request 補齊，並用實際 SandboxRunner 寫出暫存 artifact + mock transport 的整合測試證明 verify_execution 能接受合法 run，且仍拒絕錯誤身分；不需真部署即可驗證這個介面。

正向完整傳遞測試使用明確標記的 test-only verifier 與合成收據，未修改生產 registry，也未聲稱真實憑證消費或多服務攻擊鏈驗收。未執行真實 payload、部署、Proxmox 操作、LLM API 或乾淨主機重建。
