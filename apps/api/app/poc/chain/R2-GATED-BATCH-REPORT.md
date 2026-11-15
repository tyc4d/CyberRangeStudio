# R2：未執行的 BLOCKED 不得讓同批次 FAIL 遺失

日期：2026-11-16。修正基準：Lead 同步的 `agent/m9-base b4ee402`。
產品修正與 6 個新增測試已由 Lead 代提交為 `15df414`；本 Worker 未執行 git add/commit/merge。

## 結果

- **完整後端：263 passed, 2 warnings, 89 subtests passed in 85.62s**；原始輸出見 `qa/r2-gated-batch-full-tests.txt`。
- **第二輪獨立 QA：89 passed, 2 warnings in 1.86s**，原測試檔未改。
- **chain 子套件：37 passed, 2 warnings, 9 subtests passed in 0.48s**。
- 新測試修正前為 **3 failed / 3 passed**，修正後全數通過，確實重現同批次前一步被誤丟棄。
- 舊第一輪 QA 另跑得到 **57 passed / 1 failed**：`test_cancel_does_not_allow_delayed_launch_after_cleanup_returns` 等待 mock transport 完成，但目前 runner 的 fail-closed 路徑完全不啟動 transport，所以 `finished.wait(1)` 未成立。此測試不經過 chain，本次未修改 runner 或 QA；已回報 Lead，沒有聲稱舊第一輪 QA 全綠。
- `git diff --check` 通過。

## 最小修正

只調整 `chain/evidence.py:execution_log` 的 ownership 要求：當紀錄為 BLOCKED、ownership=None、target_ownership_verified=false、六個 execution stages 全為 false，且 log 無 effect evidence、result 只有 log evidence 時，接受它的已雜湊執行身分供批次分組。

該紀錄仍需通過 artifact 存在／根目錄／SHA、run/job id、情境命名路徑、action/status/payload/time 與 log/result 一致性檢查。已執行紀錄與 PASS 的 ownership／effect／部署驗證規則保留。`verify_execution` 對這種未執行紀錄仍回 BLOCKED。

因此 `_select_runs` 能保留同一 job 的 `[a1=FAIL, a2=BLOCKED]`，不再因 a2 合法地沒有 ownership 而丟掉 a1。`[BLOCKED, BLOCKED]` 及合法獨立 `[PASS, BLOCKED]` 的 sibling 結果也正確保留；完整 chain 仍不會 PASS。

## 回歸測試

`test_gated_batch.py` 使用真正的 runner、artifact writer 與暫存 SQLite，只 mock ownership 與傳輸；未執行真實 payload、部署、HTTP 或 PVE。

1. `[FAIL, BLOCKED]` 同 job，前一步保留 FAIL。
2. `[BLOCKED, BLOCKED]` 同 job，兩步均保留 BLOCKED。
3. gate 不會丟掉已獨立驗證的 PASS sibling；整鏈仍未通過。
4. 改寫 gated BLOCKED 為 PASS 並重新計算 log SHA，仍不能取得 PASS。
5. ownership 豁免不得用於已有 started stage 或 effect evidence 的紀錄。
6. BLOCKED 批次成員仍須有正確 log SHA、job id 與 action id。

前兩案也確認 transport 與 ownership 只對前一步各呼叫一次，後一步確實未執行；gated log 的 ownership=None、evidence=[]、context 無 deployment_record_id，符合 runner 實際格式。

## 重跑

在本工作樹 `apps/api` 使用：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/tyc4d/cr-project/.worktrees/m9-chain/packages/contracts /home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/tyc4d/cr-project/.worktrees/m9-chain/packages/contracts /home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider ../../reports/overnight/m9/review2/test_m9_review2.py --tb=short
```

R2 QA 原檔 SHA-256：`5a5136b13f7f8dcc0418a725c6b51f61a5d7f01b781517cb71a53d3ac08531bb`。
