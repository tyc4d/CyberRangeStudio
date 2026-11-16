# m9-runner 修正回報

日期：2026-11-16（Asia/Taipei）

## 判定

**範圍內修正已完成，完整驗收尚未全過。** 不把仍失敗的 review cases 標成 PASS。
Lead 已明確核准修改 runner 子套件，並裁定底層沒有保證取消 handle 時採 fail-closed。

僅修改 `apps/api/app/poc/runner/**` 與 `requests/`；未修改 review tests、shared model、service、
manager、其他套件，未啟動其他 Agent，未 git add/commit。沒有執行真實部署、攻擊傳輸、PVE 操作或 LLM API。

## 修正

- #1：pinned payload 只在 HTTP 成功狀態且 arithmetic header 精確相符時輸出成功訊號；
  錯誤不再回印 target-controlled exception text。Verifier 必須同時滿足 exit=0、stdout 精確成功行、
  stderr 空白，拒絕錯誤路徑、marker substring、混入 stderr／多行錯誤及非零 exit。
- #3／#5：真實 transport 入口對 local-docker 無條件阻擋攻擊，不看映像 vulnerable 分類。
  因現有 manager 沒有 pending-launch fence／cancel handle，PVE 也不啟動 helper，誠實回 BLOCKED。
  移除 daemon thread 包裝，不會回覆取消後仍在背景啟動。沒有宣稱真實 exploit E2E 可用。
- #4：檢查全部實際附掛網路；任一非核准網路、edge、未確認 Internal／isolated／membership
  即拒絕。PVE 也會透過有 ownership/isolation gate 的 Docker inspect 檢查實際容器與網路。
- #5：保留的 emergency scan 能清理全部已驗證身分的同 action helpers，不再因多筆相符而放棄。
  此掃描不被當成 launch fence，也不作為放行攻擊的依據。
- #11：124／125／127 等安全錯誤不宣稱 confirmed delivery／response，timeout 在舊 chain verifier
  也能保留 BLOCKED。批次 API／DB 序列化優先使用 shared `to_dict()`，舊版相容路徑會省略 None。
- #9 整合：每個 attempt 使用唯一 artifact 目錄，重跑不覆寫歷史 log／effect。hashed JSON log
  的 `context` 包含 run_id、job_id、scenario_id、action_id、canonical scenario_sha256、payload_sha256、
  started_at、deployment_record_id 與 ownership；沒有的真實 identity 保持缺漏，不憑空補值。

payload 內容改變後 SHA 隨 pinned bytes 更新；舊 payload／舊 SHA 不會被當成新的 registered proof。

## 測試證據

所有後端命令皆從本 worktree 的 `apps/api` 執行，使用：

```sh
PYTHONDONTWRITEBYTECODE=1
PYTHONPATH=/home/tyc4d/cr-project/.worktrees/m9-runner/packages/contracts
/home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider
```

| 檢查 | 結果 |
| --- | --- |
| 新增 runner safety tests | **28 passed**，2 個既有 jsonschema 棄用警告 |
| 完整後端套件（既有 171 + 新增 28） | **199 passed，7 subtests passed**，2 個既有警告；84.47 秒 |
| 未修改的完整 review file | **36 passed / 22 failed**，2 個既有警告；1.37 秒 |
| 修正前完整 review file | **32 passed / 26 failed** |
| `git diff --check` | 通過 |

完整輸出：`requests/m9-runner-backend-tests.txt`、`requests/m9-runner-review-tests.txt`。

原 review 中下列四個原本失敗案例已 PASS：

- `test_registered_payload_error_containing_marker_must_not_pass`
- `test_d6_blocks_attack_payload_even_for_non_vulnerable_image`
- `test_guard_rejects_any_additional_non_lab_network`
- `test_timeout_blocked_is_not_reinterpreted_as_exploit_fail`

registered-success、liveness/error、pinned SHA／source／payload、guard-before-adapter、protected VMID、
known-vulnerable D6 等原有 controls 仍通過。新增 tests 使用 mocked transport；對 pinned Python
程式的協定測試也只用完全 mocked `urlopen`，沒有實際 HTTP 傳送。

## 尚未通過的 runner 驗收及跨檔需求

詳細說明在 `requests/m9-runner.md`。

1. **取消 review case 仍 FAIL**：Lead 核准採零啟動 fail-closed，但 unchanged test 要求 transport
   的 `finished` Event 必須被設定；未啟動的 mock 不可能完成。若讓原 mock 完成，它又會先無條件
   設定 `delivered`，和後續 `not delivered` 斷言矛盾。此次失敗位置是 `finished.wait(1)`；
   未操弄測試 Events，也未將此結果製造成 PASS。
2. **兩個 schema review cases 仍 FAIL**：原 test 直接呼叫 stdlib `asdict(result)`，不經
   `to_dict()`／批次 API 序列化；shared dataclass 的 None 仍會被 asdict 保留。真實 API／DB 路徑
   已以新增契約測試驗證省略 optional null。未改 schema，未捏造 exit_code 或 failure_reason。
3. **helper resource caps review case 仍 FAIL（Lead-owned）**：直接呼叫 manager 建構 argv，runner
   無法修改該結果；Lead 已承接 `--memory / --cpus / --pids-limit`。
4. **PVE deployment identity**：`_active_proxmox_deployment` 目前丟掉 lifecycle record id，需 Lead
   保留該值，guard 才能記錄真實 deployment_record_id；缺漏時 chain 應維持未驗證。

其餘 review failures 位於 chain、service、discovery、export、GUI，未越界修改。此 worktree 不含
其他 worker／Lead 的修正，22 failed 不能視為整合後的最終結果。
