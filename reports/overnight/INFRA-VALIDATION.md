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

---

## 4. 修復後的能力矩陣（commit 227a74c 之後）

所有項目都以真實 Docker 部署重測。指令：
`CR_DATA_DIR=$PWD/.data PYTHONPATH=apps/api python tools/infra-validation/lifecycle_probe.py <plan> <out.json>`
（走與 GUI 相同的 API 路由：generate → approve → up → status → health → validate → down → 再 up → down）。

| 能力 | 修復前 | 修復後 | 證據（`evidence/infra-eng/`） |
|---|---|---|---|
| 工具可解析 | 可用 | 可用（`docker compose config --quiet` rc=0） | 各 `lifecycle-*.json` step `docker_compose_config` |
| 主機埠 | 固定 42000，並行必撞 | 部署時挑空埠（42000–42999），撞埠自動換埠重試 3 次；同計畫 3 個情境同時部署皆成功 | `concurrent-deploy-after.txt` |
| 失敗處理 | 留下容器與網路 | 先收集每個容器的狀態／結束碼／最後 40 行 log／healthcheck 輸出，再整個清掉；回應含 `diagnostics`、`cleanup.clean` | `lifecycle-wordpress-mysql-failed-first-attempt.json`（真實失敗案例，清理後無殘留） |
| 健康檢查 | 真實元件沒有 | catalogue 每個服務元件都有；`up` 用 `--wait`，全部 healthy 才算部署成功 | `lifecycle-real-3tier-after.json` |
| 服務相依 | 無 | 計畫的 connections → `depends_on`（目標有 healthcheck 時等它 healthy；會成環的邊略過） | `test_generator.py::ExposureAndDependencyTests` |
| 相依設定注入 | 無 | catalogue `wiring`：WordPress 連到 MySQL／MariaDB 主機時自動帶入 DB 位址與部署時產生的密碼；沒宣告連線則判定不可部署 | `final-wordpress-mysql.json` |
| 資源配置 | 無 | 每個服務都有 `mem_limit`／`cpus`／`pids_limit`（預設 512m／1 CPU／256，catalogue 可覆寫）；實測 `docker inspect` 生效 | `vulnerable-target-isolation.txt` |
| 計畫網段隔離 | 有破口（共用 edge） | 實驗服務不接 edge；不同網段互連全數被擋 | `edge-isolation-after.txt` |
| 對宿主機隔離 | 容器可連宿主機 0.0.0.0 服務 | 計畫網路用 Docker `gateway_mode_ipv4=isolated`，bridge 在宿主機沒有位址；實測連不到 | `host-reachability.txt`、`final-host-isolation.txt` |
| 對外連線 | 有埠的主機可上網 | 實驗容器沒有 default route | `vulnerable-target-isolation.txt` |
| 對外開埠 | 所有有埠的主機 | 只有接在「非 internal」計畫網路的主機；漏洞映像永不開埠；一律經 `cr-gateway` 轉發 | `test_generator.py`、`final-host-isolation.txt` |
| 重新部署 | 可用 | 可用（每個計畫都跑兩輪，結果一致） | 各 `lifecycle-*.json` 的 `up_2`／`validate_2` |
| 清除 | 可用 | 可用（容器／網路／volume 皆無殘留） | 各 `leftovers_*` |
| 停止（保留資料）／重置 | 無 | **仍無**（見 §7 需產品決定） | — |
| LAN 曝露 | NOT_TESTED | **NOT_TESTED**（無人值守不對區網開埠；程式路徑有單元測試） | — |

測試：`PYTHONPATH=apps/api python -m pytest apps/api tests -q` → **77 passed**（基準 54 passed／1 failed）。
其中兩項是真實 Docker 整合測試（原有的 up/validate/down，以及新增的「容器連不到宿主機」）。

### 4.1 隔離設計（現在的樣子）

```
宿主機 127.0.0.1:42xxx ──(publish)── cr-gateway ──┐           （唯一接 edge 的容器；釘版 python 轉發程式）
                                                  │
        計畫網路（internal、宿主機側無位址、無 default route）
        ┌─────────────┬──────────────┬───────────┴──┐
     attacker        web            db            漏洞映像（永不 publish）
```

- 修復前實測：`dmz` 的 web 可經 edge 連到 `internal` 的 db（`segmentation-hole-before.txt`）；
  root 容器可連宿主機 sshd 並讀到 `SSH-2.0-OpenSSH_9.6p` banner（`host-reachability.txt` A 段）。
- 修復後實測：Equifax（含以 root 執行的 Struts 映像）與 WordPress 兩套部署中，所有實驗容器對宿主機
  **全部 20 個 IPv4 位址**的 :22 都連不到（`final-host-isolation.txt`）。
- 部署前預檢：Docker Engine < 28 不支援此模式 → 計畫含漏洞映像時**拒絕部署**；不含時放行但回報風險。
- 部署後複查：逐一檢查各計畫網路的 bridge 在宿主機上是否有位址；有且計畫含漏洞映像 → 自動拆除。
- 殘餘風險（如實列出）：
  1. `cr-gateway` 本身接在一般 bridge，連得到宿主機（實測 20 個位址可達）。它跑的是我們自己的轉發程式、
     只轉到固定目標、不是漏洞映像；但若要連它也擋，只能靠宿主機防火牆（需 sudo，見 §7）。
  2. 同一網段內的容器彼此全通（Docker 不做同 bridge 的逐埠管制）。計畫的 `access_rules` 目前只是宣告。
  3. 容器隔離不是 VM 隔離；核心層級的容器逃逸不在這層防護範圍內。

### 4.2 跨服務真實相依（Web → Database）

用 `plan-wordpress-mysql.json`（WordPress 7.1.4 ＋ MySQL 8.0.46，皆釘 digest），`tools/infra-validation/dependency_probe.sh`：

| 步驟 | 結果 |
|---|---|
| attacker 容器 → `http://web/wp-login.php`（DB 正常） | **302**（WordPress 要先連上 DB 才會回這頁） |
| web 容器內的 DB 設定 | `WORDPRESS_DB_HOST=db:3306`、帳號 `app`、密碼為部署時產生（不落檔） |
| DB 端用同一組密碼查詢 | `connected as app@% to schema app` |
| **停掉 DB 容器**後再請求 | **500**（Error establishing a database connection） |
| 重新啟動 DB、等它 healthy 後再請求 | **302** |

結論：這條相依是真的——DB 不在，Web 就壞；不是「兩個容器都在跑」而已。證據：`web-db-dependency.txt`。
限制：nginx／httpd 預設頁仍然不使用資料庫；要「真的用 DB 的 Web」請用 `oss-wordpress`。

## 5. Catalogue 補齊

修復前 4 個真實映像 → 現在 11 個，全部釘版本＋sha256 digest，且**每一個都實際部署並核對過版本**（`version-probes.txt`、`vulnerable-target-isolation.txt`）。

| ID | 映像（釘版） | 類型 | 實測 |
|---|---|---|---|
| oss-nginx | nginx:1.31.8 | Web | healthy、版本符 |
| oss-httpd | httpd:2.4.71 | Web | healthy、版本符 |
| oss-postgres | postgres:16.16-alpine3.23 | DB | healthy、版本符 |
| oss-attacker | alpine:3.22 | 攻擊端工具箱底座 | 執行中 |
| **oss-mysql** | mysql:8.0.46 | DB | healthy、版本符、WordPress 可用它 |
| **oss-mariadb** | mariadb:11.4.13 | DB | healthy、版本符 |
| **oss-redis** | redis:7.4.12-alpine3.22 | 快取 | healthy、版本符 |
| **oss-tomcat** | tomcat:9.0.124-jre25-temurin-noble | 應用伺服器（未部署任何 webapp） | healthy、版本符 |
| **oss-wordpress** | wordpress:7.1.4-php8.3-apache | 真的依賴 DB 的 Web 應用 | healthy、版本符、相依實測（§4.2） |
| **vuln-struts2-s2-045** | vulhub/struts2:2.3.30 | **漏洞練習標的** CVE-2017-5638 | healthy、jar 為 `struts2-core-2.3.30`、attacker 可連、未開埠、連不到宿主機 |
| **vuln-log4shell-solr** | vulhub/solr:8.11.0 | **漏洞練習標的** CVE-2021-44228 | healthy、`log4j-core-2.14.1.jar`、attacker 可連、未開埠 |

對照 cti-research 的兩條候選鏈（`fixtures/cti-candidates/*/expected.md`）：

- **Equifax 2017**：建議拓樸 `attacker ─ dmz ─ portal(vulhub/struts2:2.3.30) ─ data ─ 3 個 DB` 已用
  `plan-equifax-struts-db.json` 真實部署：5 個容器全 healthy，portal 可連三個 DB，attacker 連不到 data 網段。
  Struts 版本 2.3.30 是練習用的選擇（來源分級 ASSUMED·SUBSTITUTED），不是 Equifax 的事實；資料庫產品同樣是假設。
- **AA22-320A**：Solr 8.11.0（Log4j 2.14.1）只是 Log4Shell 的**教學替代**，不是 VMware Horizon。
  catalogue 內以 `exercise_for` 記載差異；我**沒有**把 `log4j`／`CVE-2021-44228` 的別名改指到 Solr，
  現行分析仍會把它標成無對應元件——是否改成「自動建議 Solr 替代」屬模組 4 的行為，交由 Lead 決定（§7）。

漏洞映像的處理規則（程式強制，有測試）：
- 只會接計畫內的 internal 網路，永不 publish、永不接 edge；即使計畫把它放在「對外」網段也一樣。
- 兩個 vulhub 映像無法在唯讀根檔案系統下執行（`read_only: false`），且以 root 執行；
  其餘加固照舊（`cap_drop: ALL`、`no-new-privileges`、資源上限）。這點寫在 catalogue 與 `report.json` 裡。
- **我沒有對這些映像執行任何 exploit**；只驗證「標的是真的、版本對、隔離有效」。攻擊驗證屬模組 8。

部署過程抓到並修掉的兩個「假健康」：
1. Solr 映像啟動時會先跑一個只綁 localhost 的暫時實例來載入範例資料；healthcheck 若打 127.0.0.1 會在這段
   期間誤報 healthy（當時 attacker 實際連不到，`lifecycle-log4shell-misc-false-healthy-first-attempt.json`）。
   改成檢查容器的對外位址與 demo core。
2. WordPress 安裝頁會連 api.wordpress.org，在沒有對外連線的實驗網路裡會卡到逾時；改用不對外的 `wp-login.php`。

給模組 8 的資料（只加資料，沒改驗證器）：每個元件有 `version_probe`（指令＋預期字串，皆已實測），
WordPress 有 `behavior_probe`。目前驗證器的版本／行為檢查寫死只認原本 4 個元件，新元件會顯示
「沒有適用的無害行為探測」（PARTIAL，不是假 PASS）。
