# Worker Brief — Codex Infrastructure (LAN exposure mode)

產品負責人已核准:新增一個**明確 opt-in、預設關閉**的「LAN 暴露模式」,讓同網段其他電腦能存取演練靶機(含 DB)。預設行為**完全不變**(最小暴露:回環)。

只改這些檔案,其他不要碰:
- `apps/api/app/iac/generator.py`
- `apps/api/app/deploy/manager.py`
- `apps/api/app/validator/runner.py`
- `apps/api/app/routers/deploy.py`（只加 expose 選項的傳遞）
- 對應測試：`apps/api/app/iac/test_generator.py`、`apps/api/app/deploy/test_local_compose_integration.py`、`apps/api/app/validator/test_runner.py`

**不要改**：schema、topology.py、cti/、planner/、apps/web。此功能用部署時選項實作,不改 environment-plan schema。

## 設計（務必照做）

### 1. 部署選項
`POST /api/deploy/{id}/up` 的 body 新增：
- `expose`: `"internal"`（預設）或 `"lan"`。
- `lan_host`: 字串,選填。`expose=lan` 時要綁的 host IP（例如這台的 192.168.x.x）。省略則自動偵測主機主要 LAN IPv4;偵測不到就回 400 要求明指,**不要**預設綁 0.0.0.0。

兩道既有閘全部保留：`test_approved=true` 與拓樸人工核准（topology approval）。

### 2. 綁定位址（解掉目前 Docker 限制）
目前 compose 把所有網路設成 `internal: true`,這台 Docker（29.5.2）**不會**啟用 host 埠對應,所以連回環都打不開。修法:
- **有對外服務埠的主機**（published ports）放到一個 `internal: false` 的 edge 網路（名稱仍 `cr-demo-<id>-` 前綴),讓埠能 publish;其餘純內部主機維持 `internal: true` 網路。web↔db 的內部流量走內部網路。
- published 埠的 `host_ip` 改用環境變數佔位：`${CR_BIND_IP:-127.0.0.1}`。**compose 檔內預設就是回環**;`manager` 在 `up` 時依 expose 決定：`internal`→`127.0.0.1`、`lan`→`lan_host`（或偵測到的 LAN IP）。
- 埠範圍仍限 `42000-42999`。`expose=internal` 時只綁 127.0.0.1,行為等同現在（但現在至少打得開了）。

### 3. 哪些主機對外
- `expose=internal`：維持現狀語意（只回環）。
- `expose=lan`：負責人選 **(b)**，web 與 **DB 都**對 LAN 開。亦即所有有服務埠的主機都 publish。

### 4. DB 認證（關鍵安全）
PostgreSQL 現在用 `POSTGRES_HOST_AUTH_METHOD=trust`。**一旦可能對 LAN 開，就不能再 trust。**
- compose 檔**不得**出現任何字面密碼。改成參照環境變數：`POSTGRES_PASSWORD: ${CR_PG_PASSWORD:?set at deploy time}`，並移除 trust。
- `manager.do_up` 在 `expose=lan` 時**隨機產生**一個強密碼（例如 `secrets.token_urlsafe(24)`），以環境變數注入 `docker compose up`（`env` 傳給 subprocess 或 `--env-file` 一個只在執行期存在、不落 git 的暫存檔;用完刪除）。**不要**把密碼寫進產生的 compose 檔、report、或任何 git 追蹤檔。
- 密碼只在 `up` 的 API 回應回傳一次給使用者,並在 deploy record 以遮罩記錄（例如只記 `password_set: true`,不記明文）。
- `expose=internal` 時維持 trust（純回環、無密碼,安全）；只有 LAN 模式才需要密碼。两種模式 compose 檔可共用同一份（env 佔位），由 manager 決定注入 trust 或密碼。
- `_assert_compose_safe` 的禁用字串檢查要調整：允許 `POSTGRES_PASSWORD: ${CR_PG_PASSWORD...}` 這種**環境變數參照**,但仍禁止任何字面密碼/token/金鑰。小心別因為放行而讓真正的字面祕密溜過。

### 5. 驗證（runner）
`expose=lan` 時,segmentation/連線檢查邏輯不變（仍在內部網路探測容器對容器）。另外可加一項：確認對外埠確實綁在預期位址。但**不要**在測試裡真的對 LAN 開（CI/測試用 internal/回環即可）。

## 安全界線（硬性）
- 預設關閉;只有明確 `expose=lan` 才對外。只綁指定/偵測到的這台 LAN IP,**不要**無條件 0.0.0.0。
- 只操作本專案 `cr-demo-<id>` 資源;不碰其他專案容器/網路,不改全機防火牆。
- 密碼不入 git、不入 log 明文、不入 compose 檔。

## 規則
- 讀 `AGENTS.md`。只在你的 worktree。你不能 git commit,改好留檔,Lead 檢查後提交。
- `source /home/tyc4d/cr-project/.venv/bin/activate && PYTHONPATH=apps/api python -m pytest apps/api -q` 必須全綠。預設模式的既有測試不可退化。
- 完成或卡住回報:結果寫成檔案,只傳路徑,並在回報附上「如何從另一台電腦實際連上 web 與 db」的指令範例。
