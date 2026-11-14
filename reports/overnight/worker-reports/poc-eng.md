# poc-eng 報告（模組 8：PoC／攻擊鏈驗證）

分支 `agent/poc-eng`。基準測試（開工前）：`PYTHONPATH=apps/api /home/tyc4d/cr-project/.venv/bin/python -m pytest apps/api tests -q` → `55 passed`。

## 里程碑 1：現況盤點＋假 PASS 風險清單

依據：`apps/api/app/validator/runner.py`、`apps/api/app/routers/validate.py`、`apps/api/app/deploy/manager.py`（probe/exec）、既有證據 `docs/e2e-evidence/07-validation.json`、`docs/e2e-evidence-cisa/07-validation.json`。

### 三層實際檢查的內容

| 層級 | 實際做的事 | 性質 |
|---|---|---|
| env_build | 每個主機 `docker compose ps` 的 `state == running`（VM：hypervisor state） | 啟動檢查。不看 health，`unhealthy`／`starting` 也 PASS |
| behavior_repro | 目標是 nginx/httpd：來源容器網路命名空間內 `GET /` 回 200；demo-api：`GET /demo` 回固定字串 `cr-demo-demo-ok`；postgres：**在目標容器內**對 127.0.0.1 跑 `pg_isready` | **全部是健康檢查／簡單 HTTP 回應**，沒有任何一項是攻擊行為 |
| full_chain | 取 env_build、behavior_repro、每條宣告連線的 `chain-N`（＝TCP 連通＋上述健康檢查）、每個 IR 動作 的最低值 | 動作本身**從不執行**；動作最高只會是 PARTIAL |

其他類別：`dependency_present` 只驗 demo 容器能 `import` Python 標準函式庫（與模組 4 的軟體依賴無關）；`version` 用 `nginx -v` 等比對字串；`segmentation` 從來源命名空間對目標 IP 做一次 TCP 連線。

好的部分（保留）：探測確實從來源容器的網路命名空間發出（`--network container:<src>`）；名稱解析失敗不算「已封鎖」；動作無證據時不會標 PASS；有動作時 full_chain 不可能 PASS。

### 假 PASS／誤導風險清單（依嚴重度）

| # | 風險 | 位置 | 說明 | 狀態 |
|---|---|---|---|---|
| R1 | **無動作時 full_chain 可 PASS** | runner.py `required_steps = ... if actions else declared_chain_checks` | IR 沒有 actions（或 actions 缺 id）時，只要 TCP 連得上＋`GET /` 200，full_chain 就是 PASS——零攻擊步驟卻宣稱完整攻擊鏈通過 | 確認（讀碼） |
| R2 | **behavior_repro 可因健康檢查而 PASS** | runner.py behavior 區塊 | 「行為重現」層全由 `GET /`=200、固定字串、`pg_isready` 組成；前端卻以「個別攻擊行為對應的條件，能在環境中觀察到嗎？」呈現。任何 HTTP 服務回 200 即通過，不驗 Server／版本 | 確認（`docs/e2e-evidence/07-validation.json`：behavior-1 PASS＝nginx 歡迎頁） |
| R3 | **動作被浮報為 PARTIAL** | `_action_refs_for_connection` | 只要動作的 `target_host_ref` 等於某條連線的目標主機，就算有「前置條件證據」。既有證據中 a2、a3、a4 僅因目標同為 victim_web 就全標 PARTIAL，實際只驗了 attacker→web:80 | 確認（同上證據檔） |
| R4 | **替代品行為被算成行為重現** | behavior 區塊 demo-api 分支 | 以 demo-api 替代真實軟體（如 Horizon）時，`/demo` 回固定字串即 behavior PASS；報告層級上看不出這是「教學替代」而非「真實重現」 | 確認（讀碼） |
| R5 | **postgres 行為檢查不經過攻擊路徑** | behavior 區塊 postgres 分支 | `pg_isready` 在 DB 容器內對 loopback 執行，卻掛在 `source→db` 連線的 behavior／chain 上；不證明來源能對 DB 做任何事，也沒有認證／查詢 | 確認（讀碼） |
| R6 | **segmentation 把「連線被拒」當成「網路隔離」** | `_probe_status` | 任何 `OSError` 都算 BLOCKED→PASS，包含 `ConnectionRefused`（主機可達、只是該埠沒服務）。目標服務沒起來或埠寫錯時，隔離檢查會假 PASS；沒有正向對照（確認該埠真的有在聽） | 確認（讀碼） |
| R7 | env_build 忽略 health | service_up 區塊 | 只看 `state == running`，`health=unhealthy` 仍 PASS | 確認（讀碼） |
| R8 | 證據是自我參照 | `evidence_path` | 每個 check 的 `evidence` 都指向報告本身的 JSON；沒有保存原始指令、exit code、stdout/stderr、時間、目標端痕跡。無法事後獨立稽核 | 確認（讀碼） |
| R9 | version 用子字串比對 | `_version_matches` | `expected in observed`：例如期望 `1.2` 會吻合 `1.21.3`。只驗執行檔版本，不驗映像 digest | 確認（讀碼），低 |
| R10 | 含 VM 的計畫會直接報錯／誤判 | run() | (a) VM 檢查用 category `os_identity`，不在 schema enum 內 → 報告 schema 驗證失敗丟 RuntimeError；(b) 只要有任一 VM 主機就跳過 `compose ps`，同計畫內的容器全部被判 FAIL。屬假 FAIL／當機，不是假 PASS | 讀碼推定，未實跑 |
| R11 | 狀態列舉沒有 BLOCKED，也沒有動作層級的「教學替代」 | `validation-report.schema.json` | COMMON 要求 PARTIAL／NOT_TESTED／BLOCKED，且報告要能分「真實重現／教學替代／部分／未驗證／無法重現」；現行 schema 做不到 | 需小幅擴充共用契約（見後續） |
| R12 | `_zh()` 會改寫 observed 內容 | `_zh` | 對原始輸出做字串取代與路徑遮蔽，證據文字不再是原始輸出 | 確認（讀碼），低 |

### 結論
目前模組 8 是誠實的「環境與連通性檢查」，**不是攻擊鏈驗證**：沒有任何攻擊端動作被執行。最危險的是 R1（可真的出現 full_chain=PASS）與 R2/R3/R4（健康檢查與替代品被歸到「行為重現」「部分重現」）。

### 下一步（進行中）
1. 修 R1–R7（判定邏輯收緊＋單元測試）。
2. 建立隔離實驗的行為驗收測試（Log4Shell JNDI/LDAP 回呼、Web→DB），攻擊端從攻擊者容器發出、listener 在實驗網路內、網路 `internal: true` 不連外。
3. 對候選鏈逐步標註可重現性。

## 里程碑 2：收緊判定邏輯，消除假 PASS（已修 R1/R3/R6/R7）

改的檔案：
- `apps/api/app/validator/runner.py`
- `apps/api/app/validator/test_runner.py`（我的所有權）
- `apps/api/app/deploy/test_local_compose_integration.py`（**非我所有權，deploy/infra-eng**；僅改 1 行斷言＋註解，原本斷言把「無攻擊動作的環境」判為 full_chain=PASS，正是 R1。已請 Lead 知會 infra-eng。）

修正內容：
- **R1**：`full_chain` 現在結構上不可能為 PASS。有 actions 時取各動作（最高 PARTIAL）的最低值；**無 actions 時 = NOT_TESTED**（沒有攻擊鏈可宣稱重現），plumbing 只能下拉不能上拉。另加保險：若算出 PASS 一律降為 PARTIAL。
- **R3**：動作要被標 PARTIAL，必須有連線在 `reason` 內**明確引用該動作 id**；僅「目標主機相同」不算（新 `_explicit_action_refs`）。既有證據中 a2/a3/a4 之類只因同目標就浮報 PARTIAL 的情況，現改為 NOT_TESTED。
- **R6**：區隔檢查（segmentation）只有在**真正無路由**（Network unreachable／No route to host／timeout）時才 PASS。`ConnectionRefused` 代表主機可達、只是埠關著＝兩端在同一網路，**不能**當成隔離成功，改標 NOT_TESTED（新 `_segmentation_status`）。
- **R7**：`running` 但 `unhealthy` 的容器 env_build 判 FAIL；`starting` 判 NOT_TESTED；healthy／無 healthcheck 才 PASS。

新增測試（`test_runner.py`）：
- `test_full_chain_is_never_pass_without_declared_attack_actions`（R1）
- `test_refused_connection_is_not_a_segmentation_pass`（R6）
- `test_unhealthy_container_fails_env_build`（R7）
- `test_action_without_explicit_mapping_is_not_tested_not_partial`（R3）

測試：`PYTHONPATH=apps/api /home/tyc4d/cr-project/.venv/bin/python -m pytest apps/api tests -q` → **59 passed**（原 55，+4）。

### 仍待處理 / 需產品或他人決定
- **R2/R4（跨模組，需 Lead 協調前端）**：「行為重現」層目前全由健康檢查／固定字串組成，前端 `apps/web/src/pages/ReportPage.tsx` 卻以「個別攻擊行為…能觀察到嗎？」呈現，且替代品（demo-api 代真實軟體）的 behavior PASS 看不出是「教學替代」。建議：前端在 behavior_repro 區塊標示「這是無害服務探測／教學替代，非攻擊行為重現」，或在 schema 加動作層級 fidelity 標記。
- **R8（證據可稽核性）**：每個 check 的 evidence 指向報告自身。建議另存每次探測的原始指令／exit code／stdout／時間到 `validation-runs/<scenario>/<run>/`。屬較大改動，未動。
- **R10（含 VM 計畫）**：`os_identity` 不在 schema enum → 會丟 RuntimeError；有 VM 主機時整個 compose ps 被跳過致容器假 FAIL。需與 infra-eng／contracts 協調（schema 屬共用契約），未自行改。
- **R11**：schema 狀態列舉無 BLOCKED、無動作層級教學替代標記。需改 `packages/contracts`（共用），回報 Lead。
