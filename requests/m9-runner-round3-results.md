# m9-runner — R3-03 重疊工作 status/cancel

基準：`ca0b2ef`，Lead 已同步至本 worktree；未執行 git merge/add/commit、未啟動其他 Agent。
遵照 Lead 後續更正，**保留同情境重疊 execute，不新增 409 或 reject-overlap**。
產品變更只有 `apps/api/app/poc/runner/runner.py` 與同子套件的 `test_chain_integration.py`。

## 修正

- `execution_status` 明確選取最新 execute job，再依 hash-bound log.context 的 scenario_id、job_id
  精確篩選該 job 的 results。`poc_runs` 現行表與 frozen result 都沒有 job_id 欄位，所以使用既有
  `execution_log` 讀取、驗證真正 artifacts 與雜湊後取得持久化的批次身分；不修改 store/schema。
- 移除 `poc_runs.ts >= job.created_at` 判定。較舊 job 就算較晚完成／保存，也不會進入新 job 的
  per_action 或 logs_tail。created_at 相同時以 SQLite rowid 讓較新建立的 job 優先。
- logs_tail 直接從已驗證且 job 相符的 log 產生並 redaction，不再改讀另一個 result 的檔案。
  Live detail 也只取選定 job 的 detail，維持既有 `{job_state, per_action, logs_tail}` 介面。
- `cancel_execution` 使用單一原子 SQL UPDATE，僅對該 scenario、kind=execute、
  state=pending/running 的所有工作設 cancel=1；任一符合即回 `{cancelled:true}`。已完成的新 job
  不會遮住較舊 active job；其他情境、其他 kind、已終止的工作都不變。
- 沒有改動 runner transport fail-closed、ownership、predecessor gating、chain verifier 或證據格式；
  取消仍是 cooperative flag，不宣稱部署層 guaranteed-cancel/cleanup 已完成。

## 驗證

後端從此 worktree 的 `apps/api` 執行，指定：

```sh
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=/home/tyc4d/cr-project/.worktrees/m9-runner/packages/contracts \
/home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider
```

| 範圍 | 結果 |
| --- | --- |
| 指定兩個 R3-03 原案例（修正前） | **2 failed**，重現混入 a1、較舊 running job 無法取消 |
| 指定兩個 R3-03 原案例（修正後） | **2 passed**，32 deselected，0.19 秒 |
| Runner 全部＋既有非實機 execution_job_status 測試 | **51 passed**，0.76 秒 |
| 完整後端 suite | **266 passed，89 subtests passed**，87.10 秒 |
| 未改動 review1＋review2 | **146 passed / 1 failed**，2.91 秒；即 review1 57/1、review2 89/0 |
| 未改動 review3 完整 Python | **26 passed / 8 failed**，1.19 秒；較基準 24/10 修好兩個 R3-03 |
| `git diff --check` | 通過 |

新增 3 個 runner regressions 使用真正 SQLite、log/effect 寫入與 verifier，只 mock delivery：
相同 action 的巢狀重疊仍只能回最新 job 一筆、tail 的 job_id 也須精確相符；job 建立時間相同且
run row 被 backdate 時仍依 job identity；取消一次涵蓋全部 active execute jobs，且不碰其他 scenario、
kind 或已完成工作。原 R3 巢狀 service.execute 兩個案例完全未修改，也沒有用 409 避開測試。

剩餘 8 個 review3 failures 全在 export 的 R3-01（5 個 redaction、3 個 independent scan）；未越界改動。
review1 唯一舊 failure 仍為已停用 transport 的 guaranteed-cancel 舊案例，沒有 xfail 或偽造 PASS。

完整輸出：`requests/m9-runner-r3-backend-tests.txt`、`m9-runner-r3-prior-review-tests.txt`、
`m9-runner-r3-review3-tests.txt`。每個 pytest run 均只有 2 個既有 jsonschema RefResolver 警告。
完整後端包含既有非攻擊 Docker QA；本次新增／review 測試全部為 mock delivery，未另行執行 M9
真實 exploit、PVE 或實機停止／清理驗收。
