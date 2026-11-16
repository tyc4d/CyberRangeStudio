# m9-runner — R4-03 工作身分與停止確認

基準 `c527d2d`，Lead 已同步此 worktree；沒有 git merge/add/commit、未啟動其他 Agent。
只修改 runner 的 `execution_status`、同套件 regression tests 與 requests；未修改 GUI、service、
store、chain、deploy 或任何 review 斷言。重疊 execute 繼續允許，沒有加 409。

## Status 介面（已通知 Lead 轉交 GUI owner）

| 欄位 | 意義 |
| --- | --- |
| `job_id` | 選定的最新 execute job id；無工作時為 null |
| `selected_job_state` | 該 job 在 SQLite 的實際 state；無工作時 idle |
| `job_state` | 相容既有 client 的情境活動摘要：任何 running → running；只有 pending → pending；全部工作已終止才回最新 job 的終態 |
| `jobs` | 此 scenario 全部 execute jobs，最新在前；每筆 `{job_id, state, cancel_requested}`，保留已終止工作的身分供 client 確認特定取消對象 |
| `active_jobs` | 上列 jobs 中實際仍為 pending/running 者；即使 cancel_requested=true 也不會提早移除 |
| `per_action`、`logs_tail` | 維持 R3 規則，只屬於 job_id 指定的最新 job，不混入舊 active job 的 actions/logs |

`jobs` 只含同 scenario、kind=execute，其他 scenario 或 discovery 工作不會混入。
選定工作、所有工作狀態及 results rows 在同一個短 SQLite read transaction 取得；artifact hash
驗證在資料庫關閉後進行。沒有用不同時間的查詢拼出「最新 job 已完成、舊工作卻消失」的快照。

GUI 可記住欲取消的 job ids，取消接受後逐筆比對 `jobs` 裡那些 ids 的實際 state；只要仍有
pending/running、或目標 id 狀態未知，就不確認 stopped。`cancel_requested` 只是已提出取消，
不是終態；`selected_job_state=done` 也不能代表另一個 job 已結束。`cancel_execution` 的原本
`{cancelled:true/false}` 回應保持不變，不破壞既有精確契約斷言。

這只確認 orchestration job 狀態；deploy-layer guaranteed-cancel handle/cleanup 仍是原本待辦，
真實 M9 transport 保持 fail-closed，沒有把旗標當成實機清理證據。

## 驗證

從本 worktree 的 `apps/api` 執行：

```sh
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=/home/tyc4d/cr-project/.worktrees/m9-runner/packages/contracts \
/home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider
```

| 範圍 | 結果 |
| --- | --- |
| 指定 R4-03 原案例（修正前） | **3 failed**；包含 Event 控制的真執行緒案例 |
| 指定 R4-03 原案例（修正後） | **3 passed**，56 deselected，0.23 秒 |
| Runner tests＋既有非實機 execution_job_status case | **54 passed**，0.84 秒 |
| 完整後端 suite | **271 passed，89 subtests passed**，87.84 秒 |
| 未修改 review1/2/3 合併執行 | **180 passed / 1 failed**，4.37 秒；維持 57/1、89/0、34/0 |
| 未修改 review4 完整 Python | **35 passed / 24 failed**，2.38 秒；較基準 32/27 修好 runner 3 cases |
| `git diff --check` | 通過 |

新增 3 個 runner cases 檢查無工作時的明確 identity，以及 older job 分別為 pending/running 時，
在較新 job 已 done 的狀態下，接受取消仍維持 active；只有該 older id 真正進入 cancelled 後，
client 才能以其保存的終態確認完成。也檢查 selected id/actual state 不變、results 仍只屬最新 job，
其他 scenario/kind 的 running job 不影響此情境快照。

新增與 review cases 使用真正 SQLite、artifact writer、runner 與 verifier，只 mock delivery／
部署身分；既有 review 的巢狀與真執行緒交錯完全未修改。沒有以拒絕 overlap 或改斷言製造 PASS。

review4 其餘 24 個失敗：export R4-01 的 22 cases、chain R4-04 的 2 cases，未越界處理。
舊 review1 唯一失敗仍是 guaranteed-cancel 舊案例；沒有 xfail。

輸出：`requests/m9-runner-r4-backend-tests.txt`、`m9-runner-r4-prior-review-tests.txt`、
`m9-runner-r4-review4-tests.txt`。每次 invocation 有相同 2 個既有 RefResolver 警告。
完整後端包含原有非攻擊 Docker QA；本次新增與 review 測試只用 mock delivery，未另行操作 PVE、
真實 M9 exploit 或實機停止／清理驗收。
