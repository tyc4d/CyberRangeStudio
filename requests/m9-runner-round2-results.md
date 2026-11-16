# m9-runner — fix round 2

基準：Lead 已將此 worktree 同步至 `e27540f`（agent/m9-base）。我第一次依指示嘗試 merge 時，
因 `.git/worktrees/m9-runner/ORIG_HEAD.lock` 位於唯讀沙盒而失敗；Lead 隨後確認同步已完成。
沒有繞過沙盒、git add/commit 或另開 Agent。

## 已實作的 runner 機制

- `ExecutionRequest.required_predecessors: tuple[str, ...] = ()`，有預設值，現有 caller 相容。
- `run_job` 接受完整有序 requests，只建立一個 job_id，依輸入順序執行。用此 job 的已完成
  status map 檢查全部 required_predecessors；缺少、未執行、非 PASS 或其他 job 的 PASS
  都不能滿足前置條件。不自動發明、補跑或重排 dependencies。
- 未滿足者回 BLOCKED，全部 stages=false、沒有 effect evidence、不宣稱 ownership 已驗證，
  不呼叫 SandboxRunner／guard／adapter／transport。依既有協定寫出唯一 attempt JSON log 與真實 SHA，
  context 使用相同 job_id，再透過同一個 `save_run` 路徑保存。
- FAIL→BLOCKED→BLOCKED 可沿本批 requests 的宣告前置傳遞；不讀歷史 runs 拼接成功。
- `cancel_execution` 設定此批 job 的 SQLite cancel flag；run_job 每個 action 前檢查並停止
  所有後續未開始動作，包含獨立 actions；job 進入 cancelled，不另建下一個 job。
- 保留 transport fail-closed、local Docker D6、guard-first、exact success verifier、artifact/log
  identity protocol；沒有啟用缺少 guaranteed-cancel handle 的實際攻擊傳輸。

產品變更僅 `apps/api/app/poc/runner/models.py`、`runner.py`、`test_chain_integration.py`。
其他變更僅 requests 證據。沒有修改 service、chain、store、deploy 層或任一 review 測試。

## 測試

全部從本 worktree 的 `apps/api` 執行，明確指定：

```sh
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=/home/tyc4d/cr-project/.worktrees/m9-runner/packages/contracts \
/home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider
```

| 範圍 | 結果 |
| --- | --- |
| `app/poc/runner`（含本次 9 個批次機制 cases） | **47 passed**，0.59 秒 |
| 完整後端 suite | **251 passed，46 subtests passed**，85.38 秒；2 個既有 RefResolver 警告 |
| 未改動 review1 | **56 passed / 2 failed**，1.25 秒；仍為 guaranteed-cancel 舊案例與 deploy helper caps |
| 未改動 review2 | **75 passed / 14 failed**，1.80 秒；與整合前基準相同 |
| `git diff --check` | 通過 |

新增案例用真正 runner artifact writer、SQLite job/run persistence；只 mock ownership／transport，
沒有 mock result、verifier、save_run 或 cancellation store。涵蓋 PASS/FAIL/BLOCKED predecessor、
缺少 predecessor、前一個 job 的 PASS、任何一個未滿足 predecessor、傳遞失敗、給定執行順序，
以及取消後兩個獨立 actions 都不啟動。實際檢查單一 job row、每份 log 的相同 job_id 與保存結果。

原有全套包含既有非攻擊 Docker QA；新增 runner cases 全部使用 mocked transport。
本次沒有另行執行真實 M9 exploit、PVE 部署或實機取消驗收。

輸出：`requests/m9-runner-r2-backend-tests.txt`、`m9-runner-r2-review1-tests.txt`、
`m9-runner-r2-review2-tests.txt`。

## 等待 Lead 的 service 整合

Lead 已明確確認：先合併 runner 的 defaulted 欄位，再改 service.execute 一次呼叫 run_job，
傳入完整有序 requests 與所有宣告 required_predecessors（即使該前置不在 executable batch）。
本 worktree 的 service 目前仍逐 action 建 job，且不傳 required_predecessors。

因此下列公開驗收尚未通過，不能宣稱此次 runner-only 修正已讓它們 PASS：

- `test_predecessor_cannot_be_bypassed_by_selection_or_strategy`：3 cases。
- `test_public_execute_and_chain_keep_each_valid_action_verified`。
- `test_cancel_public_batch_stops_later_independent_actions`。
- `test_blocked_dependent_result_is_persisted_for_export`。

它們要在 Lead 完成 service single-call integration 後重跑；沒有修改／弱化原斷言。

## 另發現的 chain 整合邊界（已回報 Lead）

真實 runner 執行 A=FAIL、B 因 required_predecessors 被 gate 為 BLOCKED，兩筆都已保存為同一 job。
因 B 根本沒有檢查 ownership，其 log 誠實為 ownership=None。現有 chain.execution_log 拒絕此 log，
chain._select_runs 以最新 invalid log 為 anchor 後丟掉同批 A，造成 per_action=[NOT_TESTED,BLOCKED]，
而非 [FAIL,BLOCKED]。沒有錯誤 PASS，但會遺失失敗的診斷。

重現輸出：`requests/m9-runner-r2-chain-edge.txt`（真正 artifact、SQLite、mock transport，call_count=1）。
未捏造 ownership 讓 skipped action 通過驗證，也未越界改 chain；請 Lead／chain owner 在整合時讓
可信雜湊且明確 BLOCKED、未執行的 log 能保留批次身分，同時仍禁止該 action 得到 PASS。
