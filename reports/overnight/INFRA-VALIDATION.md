# 模組 6／7 基礎設施實測（INFRA-VALIDATION）

作者：infra-eng（分支 `agent/infra-eng`）。所有結論都來自本機實際執行，證據在
`reports/overnight/evidence/infra-eng/`。未實測的項目一律標 NOT_TESTED，不推測。

狀態用語：**可用**＝實測通過；**部分**＝能跑但有明確缺口；**無**＝程式沒有這個能力；
**BLOCKED**＝被主機層級條件擋住。

> 本文件分兩段：§1–§3 是「修復前」的盤點（里程碑 1）；§4 之後是修復與重測結果，隨工作進度更新。

## 1. 能力矩陣（修復前基準，commit f545757）

### 1.1 模組 6：IaC Generation／Resolver／Compiler

| 能力 | 狀態 | 實際行為 | 證據 |
|---|---|---|---|
| 輸出格式 | 部分 | 只產生一份 Docker Compose YAML（`infra/generated/<id>/docker-compose.yml`）＋ `report.json`。沒有 Terraform／Ansible／libvirt XML 等其他 IaC。 | `iac/generator.py` |
| 計畫檢查（Resolver） | 可用 | schema 檢查、主機／網路 ID、連線必須有共同網路、連線埠必須對到目標已宣告服務；不合格回 422 並逐項列錯。 | `lifecycle-real-3tier-before.json` step `generate` |
| 元件解析 | 部分 | 只認 catalogue ID。真實映像只有 4 個：nginx 1.31.8、httpd 2.4.71、postgres 16.16、alpine 3.22（全部釘 digest）。任意映像字串不會被帶進 Compose（好）。其他軟體一律「不可部署」或落到無害 Python 替身。 | `catalogue/components.json` |
| 工具可解析 | 可用 | `docker compose config --quiet` 對生成檔回傳 0。注意：必須提供 `CR_PG_PASSWORD`，否則 postgres 的 `${CR_PG_PASSWORD:?}` 會讓 config 失敗（部署流程有自動帶入）。 | 同上 step `docker_compose_config` |
| 容器加固 | 可用 | 每個服務 `read_only`、`cap_drop: ALL`、`no-new-privileges`、非 root user、tmpfs。 | 生成檔 |
| 網路拓樸 | 部分 | 計畫內每個 network → 一個 `internal: true` 的 bridge。**但任何宣告了服務埠的主機都會被額外接到同一個非隔離的 `edge` 網路**（見問題 P2）。不支援固定 IP／子網、不支援同網段內的逐埠管制（Docker 同一 bridge 內全通）。 | `segmentation-hole-before.*` |
| 服務相依 | **無** | 沒有 `depends_on`、沒有啟動順序、沒有把「A 依賴 B」轉成任何設定（例如 DB 連線字串）。計畫的 `connections` 只被拿來檢查，不影響生成內容。 | 生成檔無 `depends_on` |
| 健康檢查 | 部分 | 只有替身（demo-api／demo-client）有 healthcheck。**真實元件（nginx／httpd／postgres）沒有 healthcheck**，catalogue 裡的 `health_check` 欄位沒被使用。 | 生成檔；`health_1` 中 health 皆為空字串 |
| 資源配置 | **無** | 沒有 CPU／記憶體／PID 上限。唯一的限制是 tmpfs 大小。 | 生成檔 |
| VM | **無（僅描述）** | `runtime: vm` 的主機只會被寫進報告的 `vms` 清單並一律標「不可部署」；不產生任何 VM 定義檔。 | `generator.py:159-192,290` |
| 主機埠配置 | 有缺陷 | 每個情境都從 42000 開始依序配埠 → 兩個情境同時部署必撞埠（P1）。 | 基準測試失敗輸出 |

### 1.2 模組 7：Deployment Runtime

| 能力 | 狀態 | 實際行為 | 證據 |
|---|---|---|---|
| 部署（up） | 可用 | 核准閘門（test_approved＋拓樸核准）→ 先 pull 釘版映像 → `compose up -d`。三層真實環境約 11 秒。 | `lifecycle-real-3tier-before.json` `up_1` |
| 狀態／健康 | 部分 | `status` 準確。`health` 對沒有 healthcheck 的容器只要「在跑」就回 healthy——postgres 還沒開始收連線時也會是 healthy。 | `health_1` |
| 清除（down） | 可用 | `compose down -v`；實測後容器／網路／volume 皆無殘留。 | `leftovers_1/2` |
| 重新部署 | 可用 | down 之後再 up，結果一致，驗證再次全過。 | `up_2`、`validate_2` |
| 停止（保留資料） | **無** | 沒有 stop／start；唯一的停止就是整個清掉。 | `routers/deploy.py` |
| 重置 | **無** | 沒有 reset 端點；只能手動 down＋up。資料都在 tmpfs，所以 down＋up 等同重置，但沒有單一操作也沒有紀錄「重置」。 | 同上 |
| 失敗處理 | 有缺陷 | up 失敗時回 503 並附 compose 的 stderr（資訊足夠判斷原因），**但不會清理**：已建立的容器與網路留在主機上（P3）。沒有收集失敗容器的 log。 | 基準測試失敗後的 `docker ps`（見 §2 P3） |
| 稽核紀錄 | 可用 | up／down／被拒絕都寫入 sqlite；status／health 不寫。 | step `records` |
| LAN 曝露 | NOT_TESTED | `expose=lan` 會把埠綁到 LAN IP。本次未實測（會對區網開埠，過夜無人值守不做）。 | — |
| VM 生命週期 | **無（未接線、從未開機）** | `manager.py` 有 `vm_create/boot/readiness/stop/destroy`，但沒有任何 API 路由呼叫它們；而且 `vm_preflight` 在所有條件都滿足時仍回 `ok: False`。詳見 §3。 | `grep vm_ apps/api/app/routers` 無結果 |

### 1.3 跨服務真實相依（Web → Database）

| 項目 | 狀態 | 說明 |
|---|---|---|
| Web 容器到 DB 的 TCP 連線 | 可用 | 從 web 的網路命名空間連 `db:5432` 成功（`connectivity-2 PASS`）。 |
| DB 真的在服務 | 部分 | `pg_isready` 是**在 DB 容器內對 127.0.0.1** 執行，不是從 web 發起。 |
| Web **真的使用** DB | **無** | 目前 catalogue 的 web（nginx／httpd 預設頁）根本不連資料庫。所謂「web→db 相依」只有一條 TCP 可達性，沒有任何「web 查了 DB 才回得出內容」的行為。這是「容器在跑 ≠ 相依成立」的典型案例。 |
| 隔離：attacker 連不到 DB | 可用 | 以 DB 的 IP 直接探測，得到 `Network is unreachable`（`segmentation-1 PASS`）。 |

## 2. 問題清單（依嚴重度）

| # | 嚴重度 | 問題 | 根因 | 處置 |
|---|---|---|---|---|
| P1 | 高 | 兩個情境同時部署會撞主機埠（`Bind for 127.0.0.1:42000 failed`）。多個 Worker 同時跑整合測試時基準測試就會失敗（本次基準：54 passed, 1 failed）。 | `inspect_plan` 每個情境都從 42000 起算，寫死在 Compose 檔。 | 待修（§4） |
| P2 | 高 | **隔離破口**：所有有服務埠的主機共用一個非隔離 `edge` 網路。結果：(a) 計畫上不同網段、應該互不相通的主機，實際可經 edge 互連——實測 `dmz` 的 web 連得到 `internal` 的 db:5432，`segmentation-1 FAIL`；(b)「內部資料庫」拿到一條對外的 default route。 | 為了能 publish 埠，把每個有埠的主機都掛上同一個 `internal: false` 網路。 | 待修（§4） |
| P3 | 高 | up 失敗後留下容器與網路（主機上已累積多個 `cr-demo-infra-test-*` 的殘留）。 | `do_up` 失敗時沒有清理；整合測試的 `finally` 也只在成功後才 down。 | 待修（§4） |
| P4 | 中 | 真實元件沒有 healthcheck，`health` 會過早回報 healthy。 | generator 沒用 catalogue 的 `health_check`。 | 待修（§4） |
| P5 | 中 | 沒有服務相依／啟動順序，也沒有任何「web 真的用 DB」的元件。 | Compiler 不處理 `connections`；catalogue 沒有應用層元件。 | 待修（§4，catalogue 補真實應用） |
| P6 | 中 | 沒有資源上限。 | 未實作。 | 待修（§4） |
| P7 | 中 | Catalogue 只有 4 個真實映像；常見的 MySQL／MariaDB／Redis／Tomcat 會被直接判為「無對應元件」。候選事件需要的 Struts2、Log4Shell 練習標的也沒有。 | 未建置。 | 待修（§5） |
| P8 | 中 | 沒有 stop／reset 操作。 | 未實作。 | 需產品決定是否要（見 §7） |
| P9 | 高 | VM 後端無法使用（細節見 §3）。 | 多項缺陷。 | §6 |
| P10 | 低 | generator 的元件設定寫死在程式分支（每加一個映像就要改程式）。 | 設計。 | 隨 P7 改成由 catalogue 資料驅動 |

## 3. Windows VM 後端現況（修復前，程式閱讀＋主機檢查）

主機：QEMU 8.2.2、libvirt 10.0.0、`/dev/kvm` 存在、OVMF 有、32 核／30 GB RAM／80 GB 可用磁碟。
使用者在 `kvm`、`libvirt` 群組但目前 shell 未生效，需 `sg libvirt -c`。`default` 網路為 inactive。

| 項目 | 現況 |
|---|---|
| API 接線 | 沒有任何路由呼叫 VM 函式；`inspect_plan` 對 VM 主機一律加錯誤 → 整份計畫不可部署。 |
| preflight | `vm_preflight` 沒有任何回傳 `ok: True` 的路徑；`os.access('/dev/kvm')` 在群組未生效的 shell 會失敗。 |
| domain XML | 沒有 `<features><acpi/><apic/>`、沒有 guest-agent channel、沒有 UEFI／TPM、`graphics type='none'`、磁碟用 virtio（Windows 安裝程式沒有內建驅動）。Windows 無法正常開機與關機。 |
| 網路 | 接 `default` NAT（可上網、與主機其他 VM 共用），不是隔離網路。 |
| 磁碟 | 只做 qcow2 overlay，前提是已有可開機的基底映像；目前只有安裝 ISO，沒有無人值守安裝流程。 |
| 權限 | `qemu:///system` 的 QEMU 以 `libvirt-qemu` 身分執行，進不了 `/home/tyc4d`（750），讀不到 ISO 與資料目錄內的磁碟。 |
| 清理 | `undefine` 沒帶 `--nvram`，UEFI VM 會清不掉。 |
| 健康檢查 | `vm_readiness` 需要 guest agent，但 XML 沒有 channel，永遠不會 ready。 |

結論：**從未開機，現況下也不可能開機**。真實驗證結果見 §6。
