# m9-discovery — Fix Round 1 修正與整合需求

日期：2026-11-16（Asia/Taipei）。工作樹：`/home/tyc4d/cr-project/.worktrees/m9-discovery`。

本輪由 Lead t31 明確確認為 FIX 任務並授權修改 discovery 子套件及其測試。
產品碼僅修改 `apps/api/app/poc/discovery/`；未修改獨立 QA 測試、其他模組，未 add/commit，未啟動其他 Agent。

## 已修正

- **#8 discovery half**：有 `action.service_ref` 時維持明確選擇；沒有時，依
  `action.target_host_ref → host.service_refs` 找服務，亦支援既有 enriched IR 的
  `service.host_ref`。多個服務各自建立查找／評分上下文，保留各自的 CVE 和版本；同一服務
  同時有兩種連結時不重複查找。找不到目標／明確服務時，不借用其他主機的服務。
- **#15**：以整數版本元組比較區間。`before`／`prior to` 不包含上界；
  `A through B`／`A to B`／破折號區間包含兩端；同時處理單邊上／下界、明確版本與 `.x`／`.*` family。
  未支援的語法與預發行版保持未知分數，不抽取數字端點宣稱相容；不變更五項分數權重。
- 補上 6 個測試方法及 35 個 subtests，覆蓋區間內外、上下端點、數值排序、未知語法、兩種主機／服務連結、
  重複連結、多服務隔離、明確 service_ref 優先及不存在引用。

## 驗證證據

所有後端測試都在本工作樹的 `apps/api` 執行，明確將 `PYTHONPATH` 指向本工作樹的
`packages/contracts`，警告輸出也確認 contracts 載入自此工作樹。

完整後端測試重跑命令：

```sh
cd /home/tyc4d/cr-project/.worktrees/m9-discovery/apps/api
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/tyc4d/cr-project/.worktrees/m9-discovery/packages/contracts /home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider
```

結果：**177 passed、42 subtests passed，2 warnings，84.57s**。
原有 171 項全部通過；新增 6 項通過。兩個警告為既有 `jsonschema.RefResolver` 棄用警告。

修正前指定案例：**3 failed、55 deselected**。實際重現空 manifest、`before 2.15.0` 對
`2.15.0` 給 1.0，以及 `2.0.0 through 2.14.1` 對 `2.10.0` 給 0.05。

修正後指定案例加 discovery 子套件：

```sh
cd /home/tyc4d/cr-project/.worktrees/m9-discovery/apps/api
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/tyc4d/cr-project/.worktrees/m9-discovery/packages/contracts /home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider app/poc/discovery/test_discovery.py ../../reports/overnight/m9/review/test_m9_review.py::test_discovery_resolves_service_through_normal_target_host_ref ../../reports/overnight/m9/review/test_m9_review.py::test_discovery_version_range_means_range_not_endpoint --tb=short
```

結果：**18 passed、35 subtests passed，2 warnings，0.12s**。包括全部 3 個指定 review cases。
獨立 QA 測試未修改、未減弱、未 xfail。

`git diff --check`：通過。

## Lead 整合需求（未越界修改）

1. **#8 mapping half**：`poc/service.py` 仍須將 IR service 對應實際 compose/environment host；本輪只修 discovery。
2. **#12 persistence**：`poc/service.discover` 仍須呼叫 `poc_store.save_manifest`。第一次選取測試時，
   `-k 'Discovery or Ranking or ...'` 額外選到 `test_discovery_is_persisted_for_export`，結果該項仍失敗
   （save spy 呼叫 0 次；其餘 18 項通過）。已用上方明確 node IDs 獨立確認本輪全部指定案例。

本輪測試只使用固定／mock metadata，沒有呼叫 live discovery、LLM、部署、漏洞執行或 PVE 實機。
未執行完整 58-case 跨模組 review 或實機多服務 E2E；由 Lead 整合後驗證。
