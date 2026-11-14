# Worker Brief — Codex Infrastructure

你負責「部署 / IaC / 驗證執行」子系統。只改以下檔案，其他一律不碰：

- `apps/api/app/planner/catalogue/__init__.py`、`apps/api/app/planner/catalogue/components.json`
- `apps/api/app/iac/generator.py`、`apps/api/app/iac/test_generator.py`
- `apps/api/app/deploy/manager.py`、`apps/api/app/deploy/test_local_compose_integration.py`
- `apps/api/app/validator/runner.py`（可新增 `apps/api/app/validator/test_*.py`）
- `infra/templates/`（demo-app 等樣板）

**不要改**：任何 schema（`packages/contracts`）、`planner/topology.py`、`routers/`、`apps/web`、`cti/`。這些是別人的。schema 與 topology 已由 Lead 改好、已提交，你直接依賴即可。

## 任務

### A. 真正支援真實開源服務（最重要）
目前 generator 一律把主機換成無害 demo 替身。現在要讓它能部署**真實** nginx / PostgreSQL（Apache httpd 也支援），同時**保留替身**作測試用。

判斷依據：`environment_plan.hosts[].component_mode`（Lead 已在 topology 產出）。
- `component_mode == "real"`：用 catalogue 的真實映像部署真軟體。
- `component_mode == "substitute"`：維持現在的 demo-api / demo-client 行為。
- 缺 `component_mode`：沿用現行 image_hint 推論（`demo-*` → 替身、`oss-*` → 真實），保持舊測試不破。

**先驗證 catalogue 映像標籤是真的存在且可拉取**（你的 worktree 有網路）。現在 `components.json` 寫的 `nginx:1.31.8`、`httpd:2.4.71`、`postgres:16.16-alpine3.23`、`alpine:3.22` 很可能是編造的版本。請 `docker pull` 實測，改成**真實存在**的穩定版，並**釘選 digest**（`image@sha256:...`）。pull 不到就不要寫進去。

真實服務的安全強化（務必遵守專案安全界線）：
- 只接內部網路；對外埠一律 `127.0.0.1` 且落在 42000-42999；釘 digest；pinned 版本。
- `cap_drop: ALL`、`no-new-privileges`、非必要不給權限；不得 `privileged`。
- PostgreSQL 用 `POSTGRES_HOST_AUTH_METHOD=trust`（隔離 lab，避免任何密碼/機密字串進 compose）。**不得**寫入任何密碼、token、金鑰。
- nginx/httpd/postgres 需要可寫目錄的，用 `tmpfs` 或具名 volume（compose down -v 清掉）；真實服務可放寬 `read_only`，但其餘硬化保留。
- `_assert_compose_safe` 的禁用字串檢查要相容真實服務（用 trust auth 本就不會出現 password 等字）。版本要可被檢查（report 要能看出用的是哪個 pinned 映像與 digest）。

compose 產出的 `report.json` / `inspect_plan` 要清楚標示：每台主機是 real 還是 substitute、實際映像與 digest、版本。**不能把替身當成原始服務**；substitute 一定要在 fidelity/報告標明差異。

`deploy/manager.py`：目前 `do_up` 用 `--pull never`。真實服務需要映像在本機存在。做法：部署前確保 pinned digest 映像已在本機（可在 up 前對 real 映像做 `docker pull`，或 compose 用 `pull_policy: missing`）。仍只限本機、cr-demo- 前綴、專案範圍。

### B. 修正驗證判定邏輯（Task 4，關鍵正確性）
`validator/runner.py`：現在三個 level 各自由獨立 check 清單 `_aggregate`，導致 **full_chain 可能 PASS 但某攻擊步驟 NOT_TESTED**。修正定義，並寫進 report 的 `level_criteria`：

- `env_build` = PASS 只有在**每個** service_up 都 PASS。
- `behavior_repro` = 各 benign 行為檢查的彙總（可獨立）。
- `full_chain` = **絕不**在任何「必要攻擊步驟」為 NOT_TESTED 或 FAIL 時 PASS；且不得優於 env_build 與 behavior_repro。亦即 full_chain 是「所有必要步驟鏈」的最弱環節；只要有必要步驟沒測到，就不是 PASS（應為 PARTIAL 或 NOT_TESTED）。
- 「必要攻擊步驟」要對應 Scenario IR 的 action（用 `action_ref`），並讓 `fidelity.reproduced/partial/not_tested` 真正反映哪些 action 被證實、哪些沒測。
- 每個 check 的 `status` 必須對應實際證據（docker exec 輸出 / HTTP 回應），不可只憑容器 health 或模型回答。

### C. 網路連線驗證（Task 2 的驗證端）
`environment_plan.verify_blocked`（Lead 已產出）列出「必須仍無法連線」的路徑。runner 要對每條 `verify_blocked` 實際探測：**能連上就 FAIL**（category `segmentation`），連不上才 PASS。同時對 `connections` 的允許路徑做正向連線檢查（已有部分，補齊）。這樣「該通的通、不該通的不通」都有證據。

## 規則
- 讀 `AGENTS.md`。只在你的 worktree 工作。你不能 git commit，改好留檔，Lead 檢查後提交。
- 跑 `source ../../.venv/bin/activate`（或專案 venv）後 `PYTHONPATH=apps/api python -m pytest apps/api -q` 必須全綠；你改動的測試要反映新語意（例如整合測試的 full_chain 斷言要符合新規則）。
- 真實部署只在本機隔離環境；不得碰其他專案容器（frame-os / lensguard / attack-flow 等），不得改全機設定，不得對外攻擊。
- 完成或卡住時回報：把詳細結果寫成檔案，只傳路徑。
