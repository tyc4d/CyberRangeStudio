# 模組 6／7 基礎設施實測（INFRA-VALIDATION）— 最終版

作者：infra-eng（分支 `agent/infra-eng`）。所有結論都來自本機實際執行，證據在
`reports/overnight/evidence/infra-eng/`。沒有實測的項目一律標 NOT_TESTED，不推測。

狀態用語：**可用**＝實測通過；**部分**＝能跑但有明確缺口；**無**＝程式沒有這個能力；
**BLOCKED**＝被主機層級條件或外部條件擋住；**NOT_TESTED**＝沒有實測。

閱讀順序：§1 現在的能力 → §2 隔離設計 → §3 跨服務相依 → §4 catalogue → §5 放寬的安全設定（請產品負責人知悉）
→ §6 Windows VM → §7 BLOCKED 與需主機層級（sudo）決定的事項 → §8 其他需產品決定與已知限制 → 附錄 A 修復前基準。

測試：`PYTHONPATH=apps/api /home/tyc4d/cr-project/.venv/bin/python -m pytest apps/api tests -q` → **108 passed, 2 warnings, 3 subtests passed**
（我開始時：54 passed、1 failed）。

## 1. 能力矩陣（現況，修復後）

### 1.1 模組 6：IaC 生成（Resolver／Compiler）

| 能力 | 狀態 | 現在的實際行為 |
|---|---|---|
| 輸出格式 | 部分 | 只產生 Docker Compose YAML＋`report.json`。沒有 Terraform／Ansible；VM 不由生成檔描述（見 §6）。 |
| 計畫檢查 | 可用 | schema、ID、連線需有共同網路、連線埠需對到目標已宣告的服務；`edge`、`cr-gateway` 為保留名稱；不合格回 422 並逐項列錯。 |
| 元件解析 | 可用 | 只認 catalogue ID；任意映像字串不會進入 Compose。真實釘版映像 11 個（§4）。無對應元件＝不可部署，不會偷換成替身。 |
| 工具可解析 | 可用 | `docker compose config --quiet` 回 0（每個實測計畫都有此步驟）。 |
| 容器加固 | 可用（有列明的例外） | 預設唯讀根檔案系統、`cap_drop: ALL`、`no-new-privileges`、非 root、tmpfs。例外逐項列在 §5。 |
| 映像釘版 | 可用 | 每個映像必須帶 `@sha256:`，否則生成即失敗（有測試）。 |
| 網路拓樸 | 可用（有限制） | 每個計畫網路＝一個 internal bridge，宿主機側無位址。不支援固定 IP／子網；同網段內不做逐埠管制（§8.2）。 |
| 服務相依 | 可用 | 計畫 connections → `depends_on`（目標有 healthcheck 時等它 healthy；會成環的邊略過）。 |
| 相依設定注入 | 可用（僅 WordPress） | catalogue `wiring`：WordPress 連到 MySQL／MariaDB 時自動帶入 DB 位址與部署時產生的密碼；缺連線則不可部署。 |
| 健康檢查 | 可用 | 每個服務元件都有，由 catalogue 定義。 |
| 資源配置 | 可用 | 每個服務都有 `mem_limit`／`cpus`／`pids_limit`；缺任何一項生成即失敗。 |
| 對外開埠 | 可用 | 只有接在「非 internal」計畫網路的主機；漏洞映像永不開埠；一律經 `cr-gateway`。 |
| 機密 | 可用 | 生成檔不含任何密碼字面值；密碼為部署時產生的參照（有測試會拒絕字面值）。 |
| UDP 服務 | 無 | 計畫檢查直接拒絕。 |
| VM 主機 | 無 | 計畫中含 VM 主機 → 判為不可部署，並說明原因（§6.4）。 |

### 1.2 模組 7：部署執行

| 能力 | 狀態 | 現在的實際行為 |
|---|---|---|
| 部署（up） | 可用 | 核准閘門 → 隔離預檢 → pull 釘版映像 → 挑空的主機埠 → `up --wait`（全部 healthy 才算成功）→ 部署後複查 bridge 無宿主機位址。 |
| 並行部署 | 可用 | 同一計畫 3 個情境同時部署皆成功；撞埠自動換埠重試最多 3 次。 |
| 失敗處理 | 可用 | 收集每個容器的狀態／結束碼／log／healthcheck 輸出後，自動清除所有已建立的資源。 |
| 狀態／健康 | 可用 | 以容器 healthcheck 為準；修掉兩個「假健康」（§4）。 |
| 清除（down） | 可用 | 容器／網路／volume 皆無殘留（每個實測計畫都檢查）。 |
| 重新部署 | 可用 | 每個計畫都跑兩輪，結果一致。 |
| 停止（保留狀態） | 無 | 只有 down。需產品決定（§8.1 D2）。 |
| 重置 | 無（容器）／可用（VM） | 容器端只能手動 down＋up；VM 端實測通過（§6）。 |
| 稽核紀錄 | 可用 | up／down／被拒絕／VM 操作皆寫入；status／health 不寫。 |
| LAN 曝露（`expose=lan`） | NOT_TESTED | 無人值守不對區網開埠；只有單元測試。 |
| Windows VM | 可用（單台、僅後端函式） | 建立→開機→原生健康檢查→關機→重置→銷毀無殘留，全部實測（§6）。尚未接到情境部署流程。 |

### 1.3 實測過的部署（每個都跑 up → 驗證 → down → 再 up → down，並檢查殘留）
| 計畫（`tools/infra-validation/plan-*.json`） | 結果 | 證據 |
|---|---|---|
| nginx＋PostgreSQL＋attacker | 兩輪成功、無殘留 | `lifecycle-real-3tier-after.json` |
| WordPress＋MySQL＋attacker | 成功；第一次嘗試失敗（健康檢查設計錯誤，已修） | `final-wordpress-mysql.json`、`lifecycle-wordpress-mysql-failed-first-attempt.json` |
| Equifax：Struts 2.3.30＋MySQL＋PostgreSQL＋MariaDB＋attacker | 兩輪成功、無殘留 | `lifecycle-equifax-struts-db.json`、`final-equifax-struts-db.json` |
| Solr 8.11.0＋Tomcat＋Redis＋httpd＋attacker | 成功；第一次嘗試抓到「假健康」（已修） | `lifecycle-log4shell-misc.json` |
| 同一計畫 3 個情境同時部署 | 皆成功、埠不衝突 | `concurrent-deploy-after.txt` |
| reviewer 的跨網段情境（web@outer、web2@inner） | 互相連不到；`cr-gateway` 不可被利用 | `edge-isolation-after.txt`、`gateway-no-hop.txt` |


### 1.4 修復前後對照

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
| 停止（保留資料）／重置 | 無 | **仍無**（見 §8.1） | — |
| LAN 曝露 | NOT_TESTED | **NOT_TESTED**（無人值守不對區網開埠；程式路徑有單元測試） | — |

## 2. 隔離設計

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
- **只有單元測試、無法在本機真實觸發的兩條路徑**（reviewer G3）：「Docker < 28 時拒絕部署漏洞映像」與
  「部署後發現未隔離就自動拆除」。本機是 Docker 29.5.2，網路一定會被正確隔離，所以這兩條防線只用
  mock 驗證過邏輯（`IsolationPreflightTests`），沒有真實環境證據。
- **轉發容器不可被實驗容器利用**（reviewer G1，已修）：第一版 `cr-gateway` 監聽 0.0.0.0，實驗容器可經它
  跨網段（outer 的 web 連 `cr-gateway:20001` 拿到 inner 的 web2）。現在轉發程式只監聽它在 edge 網路上的
  位址（以擁有 default route 的介面判定；找不到就不啟動），並拒絕來源位址屬於實驗網段的連線。
  實測：web／web2／attacker 對 `cr-gateway` 的名稱與全部位址、兩個轉發埠共 24 次嘗試全部失敗，
  宿主機端兩個 published port 仍回 200（`gateway-no-hop.txt`）；整合測試也加了同樣的真實檢查。
- 殘餘風險（如實列出）：
  1. `cr-gateway` 本身接在一般 bridge，連得到宿主機（實測 20 個位址可達）。它跑的是我們自己的轉發程式、
     只轉到固定目標、不是漏洞映像；但若要連它也擋，只能靠宿主機防火牆（需 sudo，見 §7.1 S1）。
  2. 同一網段內的容器彼此全通（Docker 不做同 bridge 的逐埠管制）。計畫的 `access_rules` 目前只是宣告。
  3. 容器隔離不是 VM 隔離；核心層級的容器逃逸不在這層防護範圍內。

## 3. 跨服務真實相依（Web → Database）

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

## 4. Catalogue

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
| **oss-wordpress** | wordpress:7.1.4-php8.3-apache | 真的依賴 DB 的 Web 應用 | healthy、版本符、相依實測（§3） |
| **vuln-struts2-s2-045** | vulhub/struts2:2.3.30 | **漏洞練習標的** CVE-2017-5638 | healthy、jar 為 `struts2-core-2.3.30`、attacker 可連、未開埠、連不到宿主機 |
| **vuln-log4shell-solr** | vulhub/solr:8.11.0 | **漏洞練習標的** CVE-2021-44228 | healthy、`log4j-core-2.14.1.jar`、attacker 可連、未開埠 |

對照 cti-research 的兩條候選鏈（`fixtures/cti-candidates/*/expected.md`）：

- **Equifax 2017**：建議拓樸 `attacker ─ dmz ─ portal(vulhub/struts2:2.3.30) ─ data ─ 3 個 DB` 已用
  `plan-equifax-struts-db.json` 真實部署：5 個容器全 healthy，portal 可連三個 DB，attacker 連不到 data 網段。
  Struts 版本 2.3.30 是練習用的選擇（來源分級 ASSUMED·SUBSTITUTED），不是 Equifax 的事實；資料庫產品同樣是假設。
- **AA22-320A**：Solr 8.11.0（Log4j 2.14.1）只是 Log4Shell 的**教學替代**，不是 VMware Horizon。
  catalogue 內以 `exercise_for` 記載差異；我**沒有**把 `log4j`／`CVE-2021-44228` 的別名改指到 Solr，
  現行分析仍會把它標成無對應元件——是否改成「自動建議 Solr 替代」屬模組 4 的行為，交由 Lead 決定（§8.1 D3）。

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

## 5. 放寬的安全設定（請產品負責人知悉）

預設每個容器都是：非 root、唯讀根檔案系統、丟掉全部 Linux capabilities、`no-new-privileges`、
可寫位置只有不可執行的 tmpfs、有 CPU／記憶體／行程數上限、只接 internal 網路。
下表是**偏離預設的全部項目**（資料來源：`catalogue/components.json`，由程式的安全檢查強制）。

### 5.1 以 root 執行、根檔案系統可寫的映像（只有兩個，都是漏洞練習標的）

| 元件 | 放寬了什麼 | 為什麼 | 用什麼圍住 |
|---|---|---|---|
| `vuln-struts2-s2-045`（vulhub/struts2:2.3.30） | 以 root 執行；根檔案系統可寫 | 映像本身就這樣設計（以 root 跑 `mvn jetty:run`，啟動時要寫入多處目錄）；要改必須自己重建映像，就不再是公開可核對的 vulhub 映像 | 只接 internal 網路、永不開埠、不接 edge；`cap_drop: ALL`（root 也沒有任何 capability）；`no-new-privileges`；1 GB／2 CPU／512 行程上限；實測連不到宿主機、沒有 default route |
| `vuln-log4shell-solr`（vulhub/solr:8.11.0） | 同上 | 啟動腳本以 root 建立範例資料並寫入 `/opt/solr` | 同上（1.5 GB／2 CPU／512 行程） |

這兩個是**刻意含有可被遠端執行程式碼的弱點**的映像：學員的攻擊成功後，會在容器內取得 root。
目前的防線是「網路隔離＋沒有 capability＋資源上限」，不是 VM 等級的隔離；核心層級的容器逃逸不在防護範圍內。
要更嚴的選項與代價見 §8.1 D4。

### 5.2 可以加回的 capability（白名單）

程式允許 catalogue 加回的 capability 只有 6 個：`NET_BIND_SERVICE`、`CHOWN`、`SETUID`、`SETGID`、`DAC_OVERRIDE`、`FOWNER`
（都不涉及網路管理、原始封包或宿主機）。其他一律被安全檢查拒絕（有測試：`NET_ADMIN` 會被擋）。

**實際有用到的只有一個**：

| capability | 用在 | 理由 |
|---|---|---|
| `NET_BIND_SERVICE` | `oss-nginx`、`oss-httpd`、`oss-wordpress` | 以非 root 身分監聽 80 埠。這是我接手前就有的設定；在目前的 Docker 上容器內本來就允許非 root 綁低埠，所以這項實際上是多餘的保險，拿掉也能跑（我沒有拿掉，避免不必要的變動）。 |

`CHOWN`／`SETUID`／`SETGID`／`DAC_OVERRIDE`／`FOWNER` 目前**沒有任何元件使用**，是為了日後需要「先以 root 啟動再降權」的映像預留的。
若產品負責人希望白名單只留實際用到的，可以直接縮成 `NET_BIND_SERVICE` 一項。

### 5.3 可執行的可寫目錄

| 元件 | 目錄 | 理由 |
|---|---|---|
| `oss-tomcat` | `/usr/local/tomcat/work`、`/usr/local/tomcat/temp` | Tomcat 在這裡編譯與載入 JSP／原生程式庫 |
| `oss-wordpress` | `/var/www/html` | WordPress 啟動時把程式複製到這裡並由 PHP 執行 |

其餘元件的可寫 tmpfs 一律 `noexec`。

### 5.4 不是放寬、但值得知道的

- `cr-gateway`（轉發容器）接在一般 bridge 上，是唯一連得到宿主機的容器。它是我們自己的程式、非 root、唯讀、
  沒有 capability、只監聽 edge 位址、只轉到固定目標（§2）。
- Redis 沒有設密碼（映像預設）；只在 internal 網路內可達。
- VM 的 guest agent 以 SYSTEM 身分在 Windows 內執行指令；後端的 `guest_exec` 是內部函式，沒有任何 API 路由會呼叫它，
  而且只接受 `powershell.exe`／`cmd.exe`。

## 6. Windows VM（B4 Phase 1）真實驗證

目標：本機 libvirt/KVM 開一台 Windows Server 2022 Evaluation VM、隔離網路、可靠清理、原生健康檢查。
全程**沒有使用 sudo**。實作在 `apps/api/app/deploy/vm.py`，實測腳本 `tools/infra-validation/vm_e2e.py`，
證據在 `evidence/infra-eng/vm/`。

### 6.1 原本的疑點與處理

| 疑點 | 根因 | 處理 |
|---|---|---|
| `qemu:///system` 下 QEMU 進不了家目錄 | QEMU 以 `libvirt-qemu` 身分執行，家目錄是 0750 | 改用 libvirt **儲存池**：ISO 與磁碟都透過 libvirtd 上傳／建立（`vol-upload`），不再引用家目錄路徑。池目錄由 libvirtd 建在 `/var/lib/libvirt/images/<pool>`。 |
| 現有 shell 沒有 libvirt 群組 | 群組在登入後才生效 | 後端偵測到「使用者在群組名單內但行程尚未生效」時，自動改用 `sg libvirt -c` 執行 virsh。 |
| `vm_preflight` 永遠回 `ok: False` | 程式沒有成功路徑 | 重寫：分別回報工具缺失／無 KVM／連不到 libvirt／範本不存在／未確認授權／ready。 |
| domain XML 缺 acpi/apic、guest-agent channel | 未實作 | 新 XML：q35、acpi/apic、Hyper-V 加速選項、guest-agent virtio-serial channel。 |
| 磁碟／網卡用 virtio，Windows 安裝程式沒有驅動 | 設計錯誤 | 改用 Windows 內建就支援的 SATA 磁碟與 e1000e 網卡；只有 guest agent 用的 virtio-serial 需要另裝驅動。 |
| 接 `default` NAT 網路（不隔離） | 設計錯誤 | 每個情境自建網路：沒有 `<forward>`、沒有 `<ip>`（宿主機側無位址、無 DHCP、無 DNS）。建立後實際檢查 bridge 沒有位址，否則拒絕建立 VM。 |
| 沒有可開機的 qcow2 | 只有安裝 ISO | 無人值守安裝：自動產生 `autounattend.xml` 媒體（磁碟分割、選版本、接受授權、設定電腦名稱、自動登入一次並安裝 guest agent）。建置期間 VM **沒有網卡**。 |
| 清理可能刪到別人的 VM | 只用名稱比對字串 | 以 XML 解析 ownership metadata（owner＋scenario＋vmid）；不符就拒絕動作。只刪自己建立的 overlay，不刪範本。 |
| hypervisor running 被當成 ready | 判定錯誤 | ready／healthy 一律以 guest agent 回應為準。 |

### 6.2 實測過程（含失敗，照實記錄）

| 嘗試 | 結果 | 原因與處置 |
|---|---|---|
| 第 1 次 | 安裝第一階段 135 秒完成後 VM 斷電，程式誤以為「安裝完成」 | Windows Setup 階段間的重啟在這裡表現為斷電。**把「斷電」當完成訊號是錯的**。改為：斷電就再開機，直到 guest agent 回應且 guest 內的首次開機紀錄寫出 done 才算完成。證據：`vm-e2e-attempt1-premature-poweroff.log` |
| 第 2 次 | Windows Server 2022 Standard Evaluation 安裝完成並自動登入（畫面可見 SConfig），但 guest agent 沒裝起來 | 主機上的 `/home/tyc4d/cr-images/virtio-win.iso` 是**下載中斷的殘檔**（89 MB／應為 877 MB）：目錄看得到、檔案內容讀不到（`pnputil: cannot read from the specified device`、`msiexec 1620`）。處置：從 Fedora 官方來源重新下載完整 ISO；並新增檢查——ISO 宣告大小大於實際檔案大小就拒絕匯入。證據：`attempt2-truncated-virtio-media.png`、`vm-e2e-attempt2-truncated-virtio-media.log` |
| 第 3 次 | **全部通過** | 用完整的 virtio-win 0.1.302 ISO（877,373,440 bytes，sha256 `303f7ae4…949d`，Fedora 官方來源）。 |

### 6.3 最終結果（第 3 次，全部為真實執行）

指令：`CR_VM_POOL=cr-infra-eng PYTHONPATH=apps/api python tools/infra-validation/vm_e2e.py reports/overnight/evidence/infra-eng/vm`
證據：`vm/vm-e2e.json`（每一步的完整回傳）、`vm/vm-e2e.log`、`vm/*.png`（畫面）、`vm/vm-manager-wrappers.txt`。

| 步驟 | 狀態 | 實際觀察 |
|---|---|---|
| 預檢 | PASS | 工具齊全、KVM 可用、libvirt 可連（經 `sg libvirt`）、儲存池就緒 |
| 無人值守建置範本 | PASS | 從官方評估版 ISO 安裝「Windows Server 2022 Standard Evaluation」（Server Core，build 20348）。完成判定＝guest agent 回應＋guest 內紀錄寫出 done。紀錄顯示：Red Hat 憑證加入、`vioser.inf` 安裝成功、`qemu-ga msi exit: 0`、`service: Running`。主機時鐘量到約 134 秒。 |
| 隔離網路 | PASS | 網路沒有 forward、沒有 ip；bridge 在宿主機上**沒有任何位址** |
| 建立 VM（範本的 overlay） | PASS | 2 vCPU／4 GB；只接上述隔離網路 |
| 開機後立刻問健康 | PASS（預期為不健康） | hypervisor 顯示 running，但健康檢查回 `healthy: false`（guest agent 尚未回應）——**running 不等於 ready** |
| 等待就緒 | PASS | guest agent 回應後才算 ready |
| 原生健康檢查 | PASS | 由 Windows 自己回報：`Windows Server 2022 Standard Evaluation`、版本 10.0.20348、主機名稱 `CR-WS2022`、網卡資訊、`EventLog／LanmanServer／Winmgmt = Running` |
| guest 眼中的網路 | PASS | 網卡只有自動配置位址（169.254.x.x），沒有閘道、default route 數量 0 |
| guest 連宿主機／外部 | PASS（皆連不到） | 從 Windows 內對宿主機區網位址、libvirt 預設 bridge 位址、一個公網位址的 :22 做 TCP 連線，全部 unreachable（`vm-manager-wrappers.txt`） |
| 正常關機（停止） | PASS | 經 guest agent 要求關機，等到 `shut off` |
| 再次開機 | PASS | 同一顆磁碟再開機並就緒 |
| 重置 | PASS | 先在 VM 內寫入標記檔 → 銷毀 → 由範本重建 → 開機 → 標記檔**已不存在**；健康檢查再次通過 |
| 銷毀 | PASS | domain 移除、overlay 磁碟刪除、網路移除 |
| 無殘留 | PASS | 後端清點為空；另用 virsh 獨立核對：domain 0 個、網路只剩系統原有的 `default`、磁碟池只剩範本與兩個 ISO；主機上沒有殘留的 bridge 介面 |
| 授權確認閘門 | PASS | 未明確確認評估版授權 → 拒絕建立；範本不存在 → 回報 `image_missing` |
| 稽核紀錄 | PASS | create／boot／stop／destroy 與被拒絕的嘗試都有紀錄 |

另有 30 項離線測試（`apps/api/app/deploy/test_vm.py`）釘住安全性質：網路 XML 不含位址／DHCP／轉送；
不是本產品建立的 domain 或網路即使同名也不會被刪；只刪 overlay 不刪範本；截斷的 ISO 會被拒絕；
running 但 agent 沒回應不算健康；沒有對外的 console 連接埠。

### 6.3.1 reviewer 後續事項（皆已處理）

| 事項 | 處理 | 驗證 |
|---|---|---|
| domain 不存在時，`vm_destroy` 會直接刪同名磁碟 | 只有在該磁碟確實是「本產品範本的 qcow2 overlay、且在同一個儲存池」時才刪；否則不動並回報 | 真實：手動建一顆同名但不是 overlay 的磁碟 → 後端拒絕、磁碟仍在（`vm/vm-ownership-real.txt`）；另有離線測試 |
| 「同名但非本產品建立的 domain／網路不會被刪」只有離線測試 | 補真實測試：用 virsh 直接建立沒有 ownership metadata 的同名 domain 與網路 | 真實：`vm_destroy`／`network_destroy` 皆回 `unverified`，兩者仍在；`vm_boot`／`vm_stop`／`guest_exec` 也都拒絕（同上檔案）。測試用的替身由腳本自己移除。 |
| `guest_exec` 說明寫「固定唯讀指令」但其實可執行任意指令 | 說明改為如實（是一般執行能力、僅供內部使用、沒有 API 路由呼叫）；程式只接受 `powershell.exe`／`cmd.exe` 並檢查參數型別 | 離線測試 |
| `vm_create` 失敗時會留下剛建立的網路 | 失敗時刪除磁碟，並只移除「這次呼叫才建立」的網路（原本就存在的不動） | 離線測試；修改後整個生命週期再真實跑一次全通過（`vm/rerun/vm-e2e.json`） |

### 6.4 BLOCKED／未做到（如實）

| 項目 | 狀態 | 原因 |
|---|---|---|
| 從「環境計畫」自動部署 VM（模組 5→6→7 流程） | **未實作** | 目前只能呼叫後端函式開 VM；`inspect_plan` 仍會把含 VM 的計畫判為不可部署（理由文字已更正）。屬 Phase 2，需另行核准。 |
| VM 與容器互通（混合拓樸） | **BLOCKED** | Docker bridge 與 libvirt bridge 是兩套網路；要接在一起需要主機層級的橋接設定（需 sudo）。 |
| 驗證器（模組 8）對 VM 的檢查 | **未驗證** | 驗證器裡既有的 VM 分支呼叫的函式名稱我保留相容，但沒有實際跑過（計畫層級無法部署 VM）。 |
| 評估版啟用 | **BLOCKED（設計使然）** | 微軟要求評估版在 10 天內上網啟用，否則會定時關機；隔離網路不會上網。目前做法＝VM 用完即丟、範本可在 2–3 分鐘內重建。長期需產品決定（§8.1 D6）。 |
| 多台 VM 各自的電腦名稱／SID | **未做** | 範本沒有 sysprep，複製出來的 VM 名稱都是 `CR-WS2022`。Phase 1 只要求單台。 |
| IIS、AD 等角色 | **未做** | 不在 Phase 1 範圍。 |
| 桌面版（Desktop Experience） | NOT_TESTED | 只測了 Server Core（映像索引 1）。 |
| `default` NAT 網路 | 未使用 | 系統原有、未啟用；本產品不使用也不修改它。 |

主機層級狀態變更（都不需 sudo，都可還原）：
- 新增 libvirt 儲存池 `cr-infra-eng`（`/var/lib/libvirt/images/cr-infra-eng`），內含 Windows ISO（5.0 GB）、
  virtio-win ISO（0.9 GB）、範本磁碟 `tpl-ws2022-eval-core.qcow2`（約 6 GB）。**我刻意保留**，讓 Lead／reviewer
  可以直接重跑 `vm_e2e.py --skip-build`。不需要時：`virsh vol-delete` 各檔後 `virsh pool-destroy`／`pool-undefine`。
- 正式環境的預設池名是 `cyberrange`（環境變數 `CR_VM_POOL` 可改）。

安全注意：建置範本用的 Administrator 密碼是每次隨機產生、只存在暫時的安裝媒體中（建完即刪），
程式不回傳也不記錄；之後一律經 guest agent 存取。Windows 會把應答檔複本留在 guest 內，
因此**範本不應被當成有保密性的系統**——它只該存在於隔離網路。

## 7. BLOCKED 與需要主機層級（sudo）決定的事項（集中）

我全程沒有使用 sudo。下面每一項都是「不用 sudo 做不到」或「被外部條件擋住」，需要產品負責人決定要不要做。

### 7.1 需要 sudo 的事項

| # | 事項 | 現況 | 需要的指令 | 做了會怎樣 | 我的建議 |
|---|---|---|---|---|---|
| S1 | 讓 `cr-gateway` 也連不到宿主機 | 實驗容器已全部連不到宿主機（實測）。只剩轉發容器連得到（reviewer 標為殘餘、不擋合併）。 | `sudo iptables -I INPUT -i br-+ -m conntrack --ctstate NEW -j DROP`（重開機後要重新套用，或寫進持久化規則） | 擋掉所有 Docker bridge 進到宿主機的新連線。published port 不受影響。**副作用：這台主機上其他專案的容器也會連不到宿主機服務。** | 目前不必做。 |
| S2 | VM 與容器接在同一個實驗網路（混合拓樸） | BLOCKED。Docker 與 libvirt 是兩套 bridge。 | 需要以 root 建立共用 bridge 並把兩邊接上（例如 `ip link`／`nmcli` 建 bridge、設定 libvirt 與 Docker 都使用它），並自行確保該 bridge 沒有宿主機位址 | 才能做「Linux 容器攻擊端 → Windows VM」這類情境 | 屬 B4 Phase 2，需另行核准；建議到時由負責人在主機上一次設定好。 |
| S3 | 讓現有 shell 直接有 `kvm`／`libvirt` 群組 | 不影響功能：後端已自動改用 `sg libvirt`。 | 重新登入即可（不需 sudo）；或 `newgrp libvirt` | 少一層包裝 | 不必處理。 |
| S4 | 清掉 libvirt 儲存池目錄本身 | 池內檔案可用 virsh 刪除（不需 sudo）；空目錄 `/var/lib/libvirt/images/cr-infra-eng` 由 root 擁有 | `virsh pool-delete cr-infra-eng`（經 libvirtd，不需 sudo）即可移除目錄 | — | 不需 sudo；列在這裡只為完整。 |

### 7.2 被外部條件擋住（BLOCKED）

| 事項 | 原因 | 影響 | 需要的決定 |
|---|---|---|---|
| Windows 評估版啟用 | 微軟要求 10 天內上網啟用，否則定時關機；隔離網路不上網 | VM 只能短期使用；目前做法是用完即丟、範本可在數分鐘內重建 | 接受定期重建，或提供可離線啟用的授權（§8.1 D6） |
| VMware Horizon、MOVEit 等商用軟體 | 沒有可合法散佈的映像 | 相關情境只能用替代標的並明確標示 | 既有決定，維持 |
| 「Docker < 28 拒絕漏洞映像」「未隔離就自動拆除」的真實驗證 | 本機是 Docker 29.5.2，網路一定被正確隔離，無法觸發 | 這兩條防線只有單元測試 | 無需決定；如實揭露 |
| `expose=lan` 實測 | 無人值守時不對區網開埠 | NOT_TESTED | 需要時請在有人看著的情況下測 |

### 7.3 尚未實作（不是被擋，是範圍外）

- 從環境計畫自動部署 VM（模組 5→6→7）。
- 驗證器對 VM 與新 catalogue 元件的檢查。
- 容器端的「停止（保留狀態）」「重置」操作。
- 多台 VM 各自的電腦名稱／SID（範本未 sysprep）、Windows 角色（IIS／AD）、桌面版。

## 8. 其他需產品負責人決定的事項、已知限制、介面變更

### 8.1 需產品負責人決定（不需 sudo）

| # | 事項 | 背景 | 我的建議 |
|---|---|---|---|
| D2 | **是否要「停止（保留狀態）」與「重置」操作** | 現在只有 up／down。資料都在 tmpfs，down＋up 等同重置，但沒有單一按鈕與紀錄。VM 端已有 stop／destroy＋重建。 | 建議加「重置」（一個動作：down＋up，並記錄）；「停止保留資料」對教學價值低，可不做。 |
| D3 | **Log4Shell 是否自動建議 Solr 替代** | catalogue 已有可用的 Solr 8.11.0 標的，但分析階段遇到 Log4j／CVE-2021-44228 仍標「無對應元件」。改成自動建議替代會改變模組 4 的輸出。 | 建議做，但必須標為「教學替代，非事件軟體」。由 Lead 指派給模組 4 負責人。 |
| D4 | **漏洞映像以 root、可寫根檔案系統執行** | 兩個 vulhub 映像不改就只能這樣跑。已用隔離網路＋不開埠＋drop 全部 capabilities＋資源上限圍住。 | 可接受；若要更嚴，需自行重建映像（成本高）。 |
| D5 | **已對外開埠的範圍變了** | 修復後只有「接在非 internal 計畫網路」的主機才開埠（以前是所有有埠的主機）；內部資料庫不再能從宿主機／區網直接連。 | 這是把行為改成符合計畫語意（internal＝不對外）；若講師需要直接連內部 DB，請明確決定要不要開例外。 |
| D6 | **Windows 評估版授權與到期** | 見 §6／§7：評估版 180 天，且微軟要求 10 天內上網啟用；隔離網路的 VM 不會上網。 | 需決定：接受定期重建範本，或提供可啟用的授權。 |
| D7 | **VM 納入情境部署** | 見 §6／§7：目前只能用後端函式開單台 VM，尚未接到「環境計畫 → 部署」流程，也無法與容器網路互通。 | 屬 B4 Phase 2 範圍，需另行核准。 |

### 8.2 已知限制（不需決定，如實列出）

- 同一網段內沒有逐埠管制；`access_rules` 只是宣告，沒有被強制執行。
- UDP 服務／連線不支援（計畫檢查會直接拒絕）。
- `expose=lan` 沒有實測（NOT_TESTED）。
- 一個主機只能對應一個 catalogue 元件（計畫 schema 只有一個 `image_hint`）。
- 驗證器（模組 8）對新元件還沒有版本／行為檢查，會顯示 PARTIAL；資料已放進 catalogue 供其使用。
- 大型映像第一次部署要下載（Solr 342 MB、Struts 246 MB、MySQL 234 MB），之後走本機快取。
- Docker 預設位址池有限：每個情境的每個計畫網路各占一個 bridge 網段，同時部署很多情境可能耗盡
  （本次最多同時 3 個情境、約 10 個網路，未遇到）。
- 每次部署 `demo-api` 替身會在本機 build 一個映像；現在 down／失敗清理時會一併刪除該情境自己 build 的映像
  （catalogue 的共用映像保留作快取）。舊版留下的 `cr-demo-*:local` 映像不會自動消失。
- 主機上有其他 Worker 測試留下的 `cr-demo-infra-test-*` 容器與網路（舊版程式失敗時留下的，不是我這個分支產生的）。
  我沒有動它們；合併本分支後不會再產生新的殘留。
- 我想刪除三個多餘的證據檔（`evidence/infra-eng/lifecycle-*.stderr`，內容為空或只有警告），
  被權限檢查擋下，未刪除，留給 Lead／負責人處理。

### 8.3 共用檔案與對外介面

**沒有修改任何共用檔**（`packages/contracts/**`、`store.py`、`main.py`、驗證器）。
`apps/api/app/deploy/test_local_compose_integration.py` 我只在檔尾新增測試，沒有動 poc-eng 改過的那行斷言。

對外介面變更（其他模組需知道）：
- `manager.container_ipv4(sid, target, from_service=None)`：不再回傳 edge 位址；新增 `container_ipv4_addresses()`。
- `POST /api/deploy/{id}/up` 回應新增 `published_ports`、`attempts`、`isolation_preflight`、`host_isolation`、
  失敗時的 `diagnostics`／`cleanup`；`containers[]` 新增 `ports`、`exit_code`。
- 有開埠的情境會多一個容器 `cr-gateway`（出現在 status／health 的 containers 清單中）。
- `report.json`／`POST /api/iac/{id}/generate`：`host_port_mappings[].host_port` 只是預設值；
  每個 component 新增 `exposure`、`published`、`healthcheck`、`limits`、`vulnerable`、`cves`、`wired_to`。

---

# 附錄 A：修復前基準（里程碑 1，commit f545757）

以下是我開始時的盤點，保留作為對照；其中的問題除標明者外都已修復。

## A.1 能力矩陣（修復前）

### A.1.1 模組 6：IaC Generation／Resolver／Compiler

| 能力 | 狀態 | 實際行為 | 證據 |
|---|---|---|---|
| 輸出格式 | 部分 | 只產生一份 Docker Compose YAML（`infra/generated/<id>/docker-compose.yml`）＋ `report.json`。沒有 Terraform／Ansible／libvirt XML 等其他 IaC。 | `iac/generator.py` |
| 計畫檢查（Resolver） | 可用 | schema 檢查、主機／網路 ID、連線必須有共同網路、連線埠必須對到目標已宣告服務；不合格回 422 並逐項列錯。 | `lifecycle-real-3tier-before.json` step `generate` |
| 元件解析 | 部分 | 只認 catalogue ID。真實映像只有 4 個：nginx 1.31.8、httpd 2.4.71、postgres 16.16、alpine 3.22（全部釘 digest）。任意映像字串不會被帶進 Compose（好）。其他軟體一律「不可部署」或落到無害 Python 替身。 | `catalogue/components.json` |
| 工具可解析 | 可用 | `docker compose config --quiet` 對生成檔回傳 0。注意：必須提供 `CR_PG_PASSWORD`，否則 postgres 的 `${CR_PG_PASSWORD:?}` 會讓 config 失敗（部署流程有自動帶入）。 | 同上 step `docker_compose_config` |
| 容器加固 | 可用 | 每個服務 `read_only`、`cap_drop: ALL`、`no-new-privileges`、非 root user、tmpfs。 | 生成檔 |
| 網路拓樸 | 部分 | 計畫內每個 network → 一個 `internal: true` 的 bridge。**但任何宣告了服務埠的主機都會被額外接到同一個非隔離的 `edge` 網路**（見 A.2 P2）。不支援固定 IP／子網、不支援同網段內的逐埠管制（Docker 同一 bridge 內全通）。 | `segmentation-hole-before.*` |
| 服務相依 | **無** | 沒有 `depends_on`、沒有啟動順序、沒有把「A 依賴 B」轉成任何設定（例如 DB 連線字串）。計畫的 `connections` 只被拿來檢查，不影響生成內容。 | 生成檔無 `depends_on` |
| 健康檢查 | 部分 | 只有替身（demo-api／demo-client）有 healthcheck。**真實元件（nginx／httpd／postgres）沒有 healthcheck**，catalogue 裡的 `health_check` 欄位沒被使用。 | 生成檔；`health_1` 中 health 皆為空字串 |
| 資源配置 | **無** | 沒有 CPU／記憶體／PID 上限。唯一的限制是 tmpfs 大小。 | 生成檔 |
| VM | **無（僅描述）** | `runtime: vm` 的主機只會被寫進報告的 `vms` 清單並一律標「不可部署」；不產生任何 VM 定義檔。 | `generator.py:159-192,290` |
| 主機埠配置 | 有缺陷 | 每個情境都從 42000 開始依序配埠 → 兩個情境同時部署必撞埠（P1）。 | 基準測試失敗輸出 |

### A.1.2 模組 7：Deployment Runtime

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
| VM 生命週期 | **無（未接線、從未開機）** | `manager.py` 有 `vm_create/boot/readiness/stop/destroy`，但沒有任何 API 路由呼叫它們；而且 `vm_preflight` 在所有條件都滿足時仍回 `ok: False`。詳見 A.3。 | `grep vm_ apps/api/app/routers` 無結果 |

### A.1.3 跨服務真實相依（修復前）

| 項目 | 狀態 | 說明 |
|---|---|---|
| Web 容器到 DB 的 TCP 連線 | 可用 | 從 web 的網路命名空間連 `db:5432` 成功（`connectivity-2 PASS`）。 |
| DB 真的在服務 | 部分 | `pg_isready` 是**在 DB 容器內對 127.0.0.1** 執行，不是從 web 發起。 |
| Web **真的使用** DB | **無** | 目前 catalogue 的 web（nginx／httpd 預設頁）根本不連資料庫。所謂「web→db 相依」只有一條 TCP 可達性，沒有任何「web 查了 DB 才回得出內容」的行為。這是「容器在跑 ≠ 相依成立」的典型案例。 |
| 隔離：attacker 連不到 DB | 可用 | 以 DB 的 IP 直接探測，得到 `Network is unreachable`（`segmentation-1 PASS`）。 |

## A.2 問題清單與處置

| # | 嚴重度 | 問題 | 根因 | 處置 |
|---|---|---|---|---|
| P1 | 高 | 兩個情境同時部署會撞主機埠（`Bind for 127.0.0.1:42000 failed`）。多個 Worker 同時跑整合測試時基準測試就會失敗（本次基準：54 passed, 1 failed）。 | `inspect_plan` 每個情境都從 42000 起算，寫死在 Compose 檔。 | 已修（§1–§3） |
| P2 | 高 | **隔離破口**：所有有服務埠的主機共用一個非隔離 `edge` 網路。結果：(a) 計畫上不同網段、應該互不相通的主機，實際可經 edge 互連——實測 `dmz` 的 web 連得到 `internal` 的 db:5432，`segmentation-1 FAIL`；(b)「內部資料庫」拿到一條對外的 default route。 | 為了能 publish 埠，把每個有埠的主機都掛上同一個 `internal: false` 網路。 | 已修（§1–§3） |
| P3 | 高 | up 失敗後留下容器與網路（主機上已累積多個 `cr-demo-infra-test-*` 的殘留）。 | `do_up` 失敗時沒有清理；整合測試的 `finally` 也只在成功後才 down。 | 已修（§1–§3） |
| P4 | 中 | 真實元件沒有 healthcheck，`health` 會過早回報 healthy。 | generator 沒用 catalogue 的 `health_check`。 | 已修（§1–§3） |
| P5 | 中 | 沒有服務相依／啟動順序，也沒有任何「web 真的用 DB」的元件。 | Compiler 不處理 `connections`；catalogue 沒有應用層元件。 | 已修（§3、§5） |
| P6 | 中 | 沒有資源上限。 | 未實作。 | 已修（§1–§3） |
| P7 | 中 | Catalogue 只有 4 個真實映像；常見的 MySQL／MariaDB／Redis／Tomcat 會被直接判為「無對應元件」。候選事件需要的 Struts2、Log4Shell 練習標的也沒有。 | 未建置。 | 已修（§4） |
| P8 | 中 | 沒有 stop／reset 操作。 | 未實作。 | 需產品決定是否要（見 §8.1） |
| P9 | 高 | VM 後端無法使用（細節見 A.3）。 | 多項缺陷。 | 已修並真實驗證（§6） |
| P10 | 低 | generator 的元件設定寫死在程式分支（每加一個映像就要改程式）。 | 設計。 | 已修：generator 改由 catalogue 資料驅動 |

## A.3 Windows VM 後端（修復前）

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
