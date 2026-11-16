# m9-discovery — Fix Round 2 / R2-07

工作樹：`/home/tyc4d/cr-project/.worktrees/m9-discovery`。
基準：`e27540f`（Lead 已同步 `agent/m9-base`；依 Lead 指示略過沙盒無法執行的 merge）。

## 修正

`engine.py:_version_hint` 不再從 metadata 描述抽取數字端點、拼成新範圍。現在只移除
`exploit [affects]`／`affects` 的描述前綴，完整保留後方版本子句；沒有明確前綴時保留原文。
`after`、`<`、`before`、`through`、比較符、wildcard、預發行尾碼與不支援的限定語都會交給既有 ranking。
無版本資訊仍為空 hint；不能解析的版本子句維持未知，不從其中某個端點推定相容。

本輪只修改 discovery 的 `engine.py` 與 `test_discovery.py`，不更動 ranking 權重、其他模組或獨立驗收腳本。
新增 3 個測試方法、38 個 subtests，包含真正 DiscoveryEngine → candidate → ranking 的正／負向檢查，
以及沒有 `versions` 標籤、未知限定語、複合比較語法與預發行版本的回歸案例。

## 測試證據

所有 pytest 在本工作樹 `apps/api` 執行，明確設定
`PYTHONPATH=/home/tyc4d/cr-project/.worktrees/m9-discovery/packages/contracts`。

- 修正前 R2-07 指定案例：**2 failed、2 passed**。`after` 與 `<` 被抽成 `2.3.30`，version=1.0。
- 修正後 discovery 子套件 + R2-07 指定 4 cases + 額外直接 ranking 10 cases：
  **32 passed、73 subtests passed、2 warnings，0.15s**。
- 完整後端 suite：**245 passed、84 subtests passed、2 warnings，85.09s**。
  基準 242 項保持全綠，加上本輪新增 3 項。
- 第一輪獨立 review：**56 passed、2 failed、2 warnings，1.25s**，維持指定基準；兩項失敗為：
  - `test_pve_helper_has_explicit_cpu_memory_pid_caps`：既有 deploy helper 缺 memory/cpus/pids flags，R2-06 由 Lead 處理。
  - `test_cancel_does_not_allow_delayed_launch_after_cleanup_returns`：目前 transport fail-closed，測試等待的 mock transport
    沒有啟動，故 `finished.wait(1)` 失敗。依 review2 報告，不能將此失敗宣稱為再次出現 late launch，
    也不能把取消功能說成完成。
- `git diff --check`：通過。

兩個警告均為既有 `jsonschema.RefResolver` 棄用警告；輸出路徑確認載入此 worktree 的 contracts。

指定案例／discovery 重跑命令：

```sh
cd /home/tyc4d/cr-project/.worktrees/m9-discovery/apps/api
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/tyc4d/cr-project/.worktrees/m9-discovery/packages/contracts /home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider app/poc/discovery/test_discovery.py ../../reports/overnight/m9/review2/test_m9_review2.py::test_discovery_preserves_range_operators_before_ranking ../../reports/overnight/m9/review2/test_m9_review2.py::test_version_range_extra_boundaries --tb=short
```

完整後端命令：

```sh
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/tyc4d/cr-project/.worktrees/m9-discovery/packages/contracts /home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider
```

第一輪 review 命令：

```sh
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/tyc4d/cr-project/.worktrees/m9-discovery/packages/contracts /home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider ../../reports/overnight/m9/review/test_m9_review.py --tb=short
```

## 範圍與限制

較複雜或帶未解析上下文的描述維持未知；本輪沒有擴充 range grammar、猜測不支援的語意或製造相容高分。
本輪沒有新增跨模組需求；其餘 R2 項目仍由 FIX-ROUND-2.md 各負責人處理。
完整 suite 包含既有本機 Docker 非攻擊整合測試；未額外啟動部署、真實 exploit、PVE 或 live metadata 查詢。
未啟動其他 Agent，未 add/commit，未修改兩輪的獨立 QA 測試。未執行全套跨模組 review2 或實機 E2E。
