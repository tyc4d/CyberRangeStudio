# Runner ↔ chain 證據格式對齊

日期：2026-11-16。只修改 runner owned product files 與 requests；沒有改 chain、shared models、
deploy 層或 review tests；沒有啟動 Agent、執行真實部署／HTTP 攻擊／PVE 操作、git add/commit。

## 已對齊

- Artifact 路徑改為 `poc-runs/<sha256(scenario_id)[:16]>/<run_id>/...`，每次 attempt 唯一。
- 成功、失敗與 ownership BLOCKED 都使用同一個 log writer。Log 頂層含 action_id、status、
  started_at、ended_at、payload_sha256、proof_id、context、ownership、evidence；時間與 result 完全一致。
- Context 只放 run_id、job_id、scenario_id、scenario_sha256 及可取得的真實 deployment_record_id。
  情境 SHA 直接呼叫 chain 的 `scenario_digest(ir)`。情境／部署身分在 transport 前固定。
- 先將 effect evidence 寫入 JSON log，再計算真實 log SHA，最後把 log 自己加入 result.evidence，
  不造成自我雜湊循環。缺少／無效 deployment id 直接省略，不推測或補造。
- 本機 Docker 攻擊阻擋、guard-first 與缺 guaranteed-cancel handle 時的 fail-closed 保持不變。

## 新增整合測試

`apps/api/app/poc/runner/test_chain_integration.py` 共 10 cases。執行真正 run_job/SandboxRunner，
把 log、effect 與 SHA 寫進暫存 DATA_DIR；只有 transport、情境／部署狀態及 ownership 回應是替身。
**沒有 mock verifier、artifact reader、digest 或 chain roll-up。**

正向案例由真實 chain `execution_log`、`verify_execution` 及 `validate_chain` 讀取 runner 檔案：
單次 action 驗證為 PASS，chain.per_action 也是 PASS。算術 exploit 不提供 state-transfer 證據，
所以整條 chain.passes/objective_reached 正確保持 false；沒有為了測試捏造 transfer。

負向案例驗證：改 IR、換 deployment、改 effect/log bytes 都不能沿用 PASS；缺少、字串型或 bool
deployment id 會省略且維持 PARTIAL；執行途中變更 IR／deployment 時，log 仍綁定舊快照並在
roll-up 保持未驗證；ownership BLOCKED 不呼叫 transport，仍寫出一致且 hash 正確的 log。

## 本地驗證與限制

本 worktree 的 shared chain 比 `agent/m9-base` 舊，沒有 scenario_digest。依 Lead 明確指示，
沒有 merge/sync 或修改跨 owner 檔案，而使用 `requests/check-m9-runner-alignment.py` 的唯讀
import overlay：runner 與 contracts 從本 worktree 載入，chain/shared models 從 m9-base 載入。
腳本列出實際來源檔與 SHA，沒有改寫 verifier 行為或斷言。權威驗證仍由 Lead 合併後在 m9-base 執行。

從本 worktree 的 `apps/api` 執行：

```sh
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=/home/tyc4d/cr-project/.worktrees/m9-runner/packages/contracts \
/home/tyc4d/cr-project/.venv/bin/python ../../requests/check-m9-runner-alignment.py \
  -q -p no:cacheprovider --import-mode=importlib app/poc/runner \
  /home/tyc4d/cr-project/.worktrees/m9-base/apps/api/app/poc/chain/test_chain.py --tb=short
```

**69 passed，4 subtests passed，0 failures**（runner 38 cases＋新版 chain 31 cases），0.42 秒。
完整輸出含來源 SHA：`requests/m9-runner-chain-overlay-tests.txt`。`git diff --check` 通過。

另以 overlay 執行此舊分支的整套測試（原 chain test file 保持未修改）：**206 passed / 3 failed，
7 subtests passed**，84.67 秒。三個失敗都是本分支舊 `app/poc/chain/test_chain.py` 的 legacy fixtures：
非時間戳的 started/ended、未存在的 artifact、`sha256="abc"`、note 關鍵字 transfer，與新版 strict
chain 協定不相容。它們在 m9-base 已由 chain owner 更新；上列 31 個新版 chain tests 全數通過。
沒有改、跳過或 xfail 這三個舊案例；完整輸出在 `requests/m9-runner-alignment-tests.txt`。
因此本地 overlay 全套並非全綠，不冒稱原分支所有舊斷言通過；由 Lead 在整合版執行權威全套。

## 仍由其他 owner 處理

PVE manager 仍需提供 active up record id；runner 有 id 才記錄，缺漏時無法 roll-up PASS。
Guaranteed-cancel handle／helper resources 屬 deploy-layer #5/#14；本次沒有啟用不安全的真實攻擊路徑。
