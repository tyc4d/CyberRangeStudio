# B4 Windows／VM 支援設計（提案）

> 狀態：設計稿，等待 Lead 與產品負責人確認；本階段不代表已支援 Windows。本文依目前指定模組的程式行為整理，不修改程式或 IR schema。

## 1. 現況與設計原則

目前環境建置主線是 Linux Docker Compose：`catalogue/components.json` 只列 NGINX、Apache HTTP Server、PostgreSQL、Alpine attacker toolbox，並以 digest 固定 image；`dependencies.py` 依別名、角色與文字推元件，無法對應時會留 missing item 或走替身；`topology.py` 以 host/service/port 建連線計畫。`generator.py` 將每個 host 解成 Compose image、網路、port mapping，且安全檢查假設所有服務都能丟棄 Linux capabilities、設 `no-new-privileges`。`deploy/manager.py` 僅允許本機 Unix Docker endpoint，提供 compose up/down/ps/exec 與同 network probe。`validator/runner.py` 以 Compose 容器狀態、Linux 命令、容器內 Python probe 驗證，攻擊行為本身不執行。

Windows VM 不是可直接塞入現有 image 欄位的另一種容器。應把部署目標明確分成 runtime（OCI container／VM）及平台，並讓分析與驗證回報每個步驟的保真度。下列元件是候選清單，不是已核准映像或已確認可散布版本；實作前需核實授權、取得方式、供應鏈與離線/網路安裝需求。

設計原則：

- 不把 Linux 替身描述成 Windows、AD、Horizon 或 Log4Shell 的重現。
- 元件解析結果需保留「精確命中、替身、未支援」的差別；沒有對應項就明示無法重現，部署與驗證不得偷偷退回 Python sleep/demo。
- 「容器可跑」只代表元件服務可跑，不等於可重現作業系統、網域、桌面虛擬化或漏洞鏈。
- VM 是高成本、長啟動時間、需授權與隔離的執行目標，應有資源上限、生命週期清理與明確使用者核准。

## 2. Catalogue 候選元件及執行方式

Catalogue 應在每個元件記錄穩定 ID、名稱/別名、版本與來源、授權/散布限制、所需 runtime、VM 規格、服務/管理埠、健康檢查、支援平台、可用的安全驗證能力，以及替身和保真度說明。不得只用 `image` 一欄代表所有類型。

| 候選項目 | 建議 runtime | 容器適用範圍 | 必須 VM／限制 |
|---|---|---|---|
| Windows Server（明確版本/評估映像） | Windows VM | Windows Server Core 的個別應用服務可另評估 Windows container；不能當成完整 Windows 主機 | OS 行為、登入/本機政策、Windows 網路堆疊需 VM；Windows container 需 Windows host/kernel 相容性，不可假定 Linux host 可執行 |
| Active Directory Domain Services（網域控制站） | Windows Server VM | 不以一般 Linux container 替代 DC | 網域、LDAP/Kerberos、GPO、信任關係及多機互動需一或多台 Windows VM；另需 DNS、時間同步與隔離網路 |
| Windows 用戶端/成員伺服器 | Windows VM | 可有獨立客戶端工具容器，但不能證明 Windows 身分與端點行為 | 網域加入、Windows 驗證/事件記錄/端點行為需 VM；須定義映像授權和重置方式 |
| VMware Horizon Connection Server／Agent／桌面 | 專用 VMware vSphere/Horizon 環境；本地 PoC 可研究 Vagrant provider 或直接 API 佈署 | 不以容器替代 Horizon 控制平面、Agent、虛擬桌面或 vSphere 整合 | 需相容的 vCenter/ESXi/Horizon、授權與多 Windows VM；一般 libvirt/QEMU 不等於 VMware Horizon，不能宣稱等價重現 |
| Log4Shell（Log4j 2 易受影響版本）應用 | Linux OCI container 或 Linux VM，視目標應用需求 | 對明確 pinned 的教學服務，可用 container 重現特定 Java/Log4j 版本與無害觸發條件 | 若情境依賴 Windows/JVM/服務整合，則需 Windows VM；僅提到 CVE 而沒有對應應用、版本、設定、觸發步驟時應標「無法重現」 |
| LDAP/DNS/Kerberos/SMB 等配套 | 各協定的 Linux 容器可作協定層替身 | Samba/OpenLDAP/DNS 可能提供有限協定或服務替身，必須標明不等於 AD | Windows AD 身分/策略及 Windows SMB 客戶端特性需 Windows VM；只有網路可達性時才可用替身 |

實作時應將 Linux 容器、Windows container、VM guest、外部虛擬化管理平台分開標示。Horizon 特別依賴 VMware 產品組合；若沒有授權環境/映像，結果是「需外部 VMware/Horizon 環境」或「無法重現」，不可將 libvirt guest 冒稱 Horizon。

## 3. IaC 如何表達 Windows VM

現有 `environment_plan` host 欄位以 `image_hint`/`component_mode` 對 catalogue 映像解析，network/port/service 再生成 Compose YAML。VM 需要另一種具型別、可驗證的描述。建議未來 schema/IR 由 Lead 排程另案決定（本任務不改 schema）：

```yaml
runtime: vm
guest:
  os_family: windows
  os_release: windows-server-<validated-release>
  image_ref: <approved-local-image-or-builder-source>
  image_digest: <immutable-reference>
  cpu: 2
  memory_mib: 4096
  disk_gib: 50
  provisioning_ref: <versioned-provisioning-recipe>
networks:
  - id: isolated-lab
    mode: isolated
services:
  - protocol: tcp
    port: 445
```

上例為概念欄位，不是現行 schema。需支援 image 來源（本地既有映像、合法取得的安裝媒體/自動化建置 recipe）、digest/版本、CPU/RAM/disk 上限、網卡與隔離方式、初始化 recipe 版本、啟動探針、guest agent/WinRM 管理能力、銷毀及重建方式。秘密（本機管理密碼、域管理憑證）只能在部署時透過短期 secret channel 注入，不寫入 IR、生成檔、報告或日誌。

IaC 輸出應依 runtime 分出 Compose 與 VM 定義/recipe，並生成清楚的 manifest 與報告。對不支援 runtime 的 host，`inspect_plan` 應回 deployable=false 和逐 host 原因；不能由目前 `_resolved_component` 的預設 substitute 分支落成 `demo-client`，尤其不可用 sleep 假裝 Windows 已啟動。

## 4. Deploy 如何啟動 VM

建議分階段採可插拔 backend：

1. **本機 Linux PoC**：先評估 libvirt/QEMU 作為可選 VM backend，使用專用非 root 管理程序/受限 socket；每個 scenario 建隔離網路、磁碟與 VM，限定 vCPU/RAM/disk、啟動時間和 VM 數量。Host 上 QEMU/KVM 硬體加速及 libvirt 權限不是目前 Docker preflight 所涵蓋，必須獨立檢查，不可自動 sudo。
2. **跨平台開發者環境**：Vagrant 可作本機 provider 的包裝/可重現操作介面，但不是 hypervisor；底層 provider（libvirt、VirtualBox、VMware 等）能力和授權各異。不得讓 Vagrant 自動下載未驗證或未授權的 Windows box。
3. **Horizon**：獨立外部 backend/connector 對接既有 vCenter/Horizon API 或交付明確前置環境要求；不和一般本機 VM backend 混為一談。

Deploy lifecycle 至少要有 create/boot/readiness/stop/destroy、超時與取消、部分失敗清理、狀態查詢和稽核紀錄。資源須以 scenario ID/owner 標記，清理只能刪本產品建立且已驗證歸屬的 VM/磁碟/網路；不能依名稱模糊刪除使用者既有 VM。支援 idempotency、磁碟容量與主機可用資源檢查，並在 UI/API 回報需下載或匯入的映像及預估容量。預設使用 host-only/isolated network，對外連線採明確規則與批准；不要將管理介面（RDP、WinRM、SSH、vCenter）任意曝露至 LAN。

現有 manager 僅檢查 Docker local Unix socket；VM backend 必須有不同 preflight，區分「工具未安裝」「硬體/權限不足」「映像缺失」「外部平台不可達」「授權或設定未完成」。記錄 backend、VM ID、映像 digest/recipe 版本、資源、生命週期時間與失敗清理結果，避免把憑證記入 audit details。

## 5. Validator 如何在 Windows 上測試

現有驗證呼叫 `compose_ps_result`、`exec_in_service`、`probe_in_service`，並使用 Linux CLI 或容器網路 namespace；這些介面不可直接套 Windows guest。建議 validator 依 runtime adapter 執行：

- **VM 存活與 OS**：透過 hypervisor 狀態及 VM console/受限 guest agent 確認啟動，再以 Windows 原生只讀命令取得版本/hostname/必要角色。VM 顯示 running 不代表 guest ready。
- **網路**：從指定來源 guest 或獨立 probe VM 測 TCP/UDP/DNS/HTTP；記錄來源/目標/埠/實際結果。分段檢查須確認目標位址可解析且 probe 確實執行，沿用現有「解析失敗不可算阻擋成功」原則。
- **AD**：只做安全、明確的健康/配置檢查（DNS SRV、LDAP bind/查詢、Kerberos 取得測試票據、網域成員狀態、GPO 套用狀態），每個檢查有前置條件和證據；不在一般驗證中執行憑證竊取、橫向移動或破壞性操作。
- **Horizon**：需 connector/API 和對應產品狀態檢查（Connection Server health、Agent/desktop pool 狀態）；若沒有合法測試平台，檢查為 NOT_TESTED/無法重現，而不是用 VM ping 冒充 Horizon 驗證。
- **Log4Shell**：僅對隔離、明確 vulnerable-version 的教學 fixture 進行無害 canary/安全觸發驗證；報告 fixture 的 Log4j/JVM/app 版本及命中證據。沒有相符 fixture 或版本證據則不執行，列明無法重現。
- **證據與狀態**：將命令、版本、時間、VM/backend/image identity、stdout/stderr 摘要與證據檔引用納入檢查；秘密遮罩。狀態至少沿用 PASS/FAIL/PARTIAL/NOT_TESTED，另記 fidelity/reproducibility，不能把「未測」算 PASS。

應把「測到連線」「測到服務行為」「驗證特定技術步驟」「完整情境攻擊鏈」分開。現有 validator 不執行攻擊 action；新增 Windows 支援不應藉機改變這項產品安全界線，若未來要測 action 本身需另核准明確、無害、可重現的 fixture 與檢查方法。

## 6. 分析頁逐步誠實降級

分析階段建立每個 action 的逐步矩陣，包含 `step_ref`、依據、目標 host、元件/版本命中、runtime 需求、狀態、差異及所需使用者輸入。狀態定義：

- **可重現**：有明確 catalogue 元件、版本/映像或固定 recipe，支援 runtime 存在；驗證器能檢查該步驟指定的安全行為。這不代表攻擊已執行。
- **只能替身**：可用不同實作驗證有限的協定/連線/一般服務概念；明列替身及差異（例如 Samba 對 AD 的限制、Linux Web 對 IIS/Windows 行為的限制）。不得宣稱原步驟被重現。
- **需 Windows VM**：步驟依賴 Windows OS、AD、Windows authentication/registry/GPO、Horizon 元件或特定 Windows 應用行為；目前環境沒有對應 VM/runtime/合法映像時，分析頁同時指出「本部署環境尚未具備，故目前無法重現」及前置條件。
- **無法重現**：catalogue 沒有該軟體/版本/操作映射，或其授權、映像、外部平台、驗證方法未知。直接說「目錄沒有對應元件，無法重現」，列出需要補充的目標資訊；不推成 demo-api/demo-client/Python sleep。

單一 action 可有多個步驟和不同狀態。整體 fidelity 取必要步驟中最低者；替身步驟不能提升成可重現，NOT_TESTED 不能等同成功。當分析推測而非來源明載時要標 inference，並提供原文依據；缺少 Windows 版本、AD 拓樸、Horizon 版本或 Log4j 版本時要求補資料或維持無法重現，不自行猜版本。

**介面例子**：

| 步驟 | 判定 | 顯示理由 |
|---|---|---|
| 對明確 Linux Log4j fixture 發送無害 canary | 可重現（條件式） | 需固定 fixture、Log4j 版本和隔離網路；只證明 canary 行為 |
| 用 Samba 提供一般 LDAP/SMB 練習端點 | 只能替身 | 不包含 Windows AD 的 GPO/Kerberos/網域控制站語義 |
| 查詢 AD 網域 GPO 並驗證 Windows 成員狀態 | 需 Windows VM | 無 Windows DC/member VM 時目前無法重現 |
| 建立 Horizon desktop pool | 無法重現（若無 Horizon backend） | catalogue/環境未提供對應 Horizon/vSphere 元件，禁止以普通 VM 替代 |

## 7. 分階段落地計畫

1. **契約與能力盤點**：定義 runtime/capability/fidelity 狀態及分析頁步驟矩陣；列出 schema/API 變更需求，由 Lead 另行排程（涉及 `scenario-ir.schema.json`、`types.ts`、`store.py` 的變更需先回報 Lead）。確認產品最小支援目標、合法 Windows 映像來源、執行平台和預算上限。
2. **Catalogue 與分析先行**：加入候選元件的 metadata 與明確 unsupported resolution；建立替身差異及無對應項回報。沒有核准映像/runtime 前不讓候選項 deployable。
3. **VM backend 原型**：先選一個 Windows Server 版本和一個本機 hypervisor，實作 preflight、隔離網路、VM lifecycle、資源配額與可靠清理；不含 AD/Horizon 全功能承諾。
4. **Windows guest provisioning/validator**：固定映像來源及初始化 recipe，加入 OS readiness、原生健康檢查、網路驗證與證據保存；用可拋棄 VM 測試失敗/中斷/重跑/清理。
5. **AD fixture**：在明確核准資源範圍內建立隔離 DC/member VM fixture，加入 DNS/Kerberos/LDAP/GPO 的無害檢查與一致重設。
6. **Log4Shell fixture**：獨立提供固定版本的易受影響練習服務和無害驗證案例；把 Linux fixture 與 Windows 依賴案例分開呈現。
7. **Horizon 評估/整合**：在確認產品授權、vSphere/Horizon 測試租戶、API 與資源後另開整合階段；未具備即維持「需外部環境/無法重現」。

每階段須設定退出條件：元件來源可驗證、重建結果可重複、資源/成本界線明確、失敗後無殘留 VM、報告不洩密、分析頁沒有將替身冒充原件。不得提高既定 $50 預算上限；若無法在上限內取得合法映像或測試平台，對應項保持未支援並回報產品決策。

## 8. 主要風險與待 Lead/產品確認

- **授權與映像散布**：Windows、VMware/Horizon 映像與授權條件各異；不可預設可放入公開 catalogue、下載或分享。需決定使用者自備映像、合法評估映像或專用測試環境。
- **宿主機相容性與成本**：libvirt/KVM 依賴 Linux host 與硬體虛擬化；Vagrant 不消除 provider 限制；Windows VM 資源和冷啟動時間遠高於現有容器。
- **安全隔離與憑證**：AD/Horizon 管理憑證具高權限；網域 VM 必須隔離、提供重置/銷毀，避免管理埠曝露或秘密落盤。
- **核心與多機語義**：Windows container 使用 Windows kernel 相容性限制，不能在 Linux Docker host 當完整 Windows VM；AD/Horizon 的多機互動不能被單容器表示。
- **驗證保真度**：VM boot/port open 不能證明 AD/Horizon 或漏洞步驟成功；需為每個 action 設定可觀測證據，否則維持 NOT_TESTED/無法重現。
- **介面/契約相容**：現有 schema 和 API 以 Compose/host/service 概念為主。新增 runtime 表達需要另案核准與遷移設計；本文件沒有修改契約或 `store.py`。
- **產品決策**：先選首個可交付範圍（Windows Server VM、AD fixture、Log4Shell fixture 或 Horizon 外部整合），確認支援平台/映像責任方及預算內資源。此設計稿不代替該決策。

