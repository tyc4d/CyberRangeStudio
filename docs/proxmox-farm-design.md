# Proxmox VM Farm 執行環境設計（v3，已核准）

> 狀態：**設計已獲產品負責人核准**（決定記於 `docs/approved-scope.md`，摘要見 §11.2）。**P0（唯讀探測）已完成**，結果見 §12。
> 在 Lead 明確通知之前：**不對 PVE 做任何寫入（POST／PUT／DELETE）**，也不開始 P1 的程式重構。
> 作者：infra-eng。日期：2026-11-15。v3 納入核准的決定、跳板機設計（§4.5）、給負責人的 pveum 指令（§5.5）與 P0 結果（§12）。
>
> **本文件的事實來源**
> - 「已實測」＝我用 token 以**唯讀 GET** 取得（工具 `tools/pve-probe/readonly_probe.py`，程式裡只有 GET 這一種方法；結果 `reports/overnight/evidence/infra-eng/pve/readonly-probe.json`，不含密值）。
> - 「官方文件」＝Proxmox VE 管理手冊的 User Management、SDN、Cloud-Init Support 章節。
> - 「API 規格」＝這台 PVE 自己提供給內建 API 檢視器的規格檔（`/pve-docs/api-viewer/apidoc.js`，靜態檔、不需認證），與安裝版本完全一致；我用它逐支核對了權限檢查與參數上限（`tools/pve-probe/apidoc_extract.py`，結果 `evidence/infra-eng/pve-p0/api-permissions.json`）。
> - 「〔待核對〕」＝還沒有證據；P0 之後剩下的集中列在 §11.3。

> **2026-11-16 狀態更新：** 本文件是 2026-11-15 核准的 v3 設計快照。後續已核准把工作 VM 硬上限提高到 5，但目前 pool 預算含範本後最多約能容納 3 台 worker；請以 `docs/approved-scope.md` 和 `apps/api/app/deploy/backends/PROXMOX_RUNTIME.md` 為目前容量與執行行為準。現行程式讓所有 worker VM 保持零網卡，跳板機到 worker 的學員連線路徑尚未實作或驗收；P4/P5 尚未通過。本文件的跳板機方案是目標設計，不表示入口已可用。

## 0. 一頁結論

1. 這台 PVE 上有既有機器，絕對不能動到。記憶體是首要約束：工作 VM 政策上限為 5 台；目前核准的資源池預算為 16 GiB，且包含 4 GiB 範本，因此 pool memory gate 最多容納 3 台 worker。建立前仍以即時剩餘容量為準，不足即拒絕（§6、`docs/approved-scope.md`）。
2. 模型不變：每個情境一台由範本 clone 的拋棄式 Linux 工作 VM，容器在 VM 內跑；Windows 主機是另一台 VM。
3. **現行工作 VM 不接任何網卡**。管理一律走 guest agent（經 PVE API），實驗環境沒有通往 PVE 管理介面、區網、既有服務的網路路徑。若要讓跳板機連入情境，必須先核准並實作新的隔離路徑，再完成 P4/P5 驗收。
4. **保護既有機器靠三層，不靠單一判斷**：PVE 的 ACL（token 根本看不到既有 VM，已實測）→ 程式送出前的攔截（保留 VMID 區間＋內建拒絕清單＋可寫路徑白名單）→ 破壞性操作前的三重擁有權驗證。
5. 我方 VMID 用 **900000–900999**（已核准；理由見 §5.1）；建立前以 `GET /cluster/nextid?vmid=N` 確認未被占用——已實測它對 token 看不到的 VM 也會回報「已存在」。
6. 提供**乾跑模式**：列出將要送出的每一個寫入呼叫而不執行。第一階段只做唯讀探測，已完成大半。
7. 空間或記憶體不足時一律**拒絕並回報需通知產品負責人**；絕不刪除任何不是我方建立的東西來騰空間。

---

## 1. 硬性約束（產品負責人指定）與對應的設計

| # | 約束 | 設計如何保證 | 章節 |
|---|---|---|---|
| H1 | 只在專屬資源池 `cr-range` 內操作；token 範圍限於該池＋指定儲存＋指定 bridge；不改節點網路／儲存／叢集設定、不重開機、不碰其他 VM／CT | token 的 ACL 就是這樣（已實測）；程式另有「可寫路徑白名單」，節點、叢集、存取控制、儲存內容刪除、LXC 的寫入路徑在程式裡**不存在** | §5.3、§7 |
| H2 | 破壞性操作前驗證擁有權：資源池成員＋我方標記＋保留 VMID 區間，三者皆符才做 | §5.2 的三重檢查；任何一項不符即拒絕並記錄 | §5.2 |
| H3 | 資源上限可設定；建立前檢查節點剩餘容量，不足即拒絕，不擠壓既有服務 | 以記憶體為首要約束；扣掉「保留給既有服務」的餘量後才是我們的預算 | §6 |
| H4 | 實驗網路用不接實體網卡的專用 bridge；由產品負責人自己建立，我們不經 API 改節點網路 | 使用既有的 `vmbr990`（已實測：無實體埠、無位址）；程式沒有任何寫入節點網路的路徑 | §4 |
| H5 | 唯讀的乾跑／預檢模式：列出將要做的每個 API 呼叫而不執行 | §8 | §8 |
| H6 | 第一階段只做唯讀探測 | §10 P0；本文件 §2 即為其結果 | §2、§10 |
| H7 | **保護清單**（不得刪除／停止／修改／重設）：節點 `pve4-bbf` 上 VMID 501、2001、2002、3001、3002、3003、3004、80001、80000（範本） | 內建拒絕清單＋保留區間不重疊＋ACL 看不到；測試以 mock 驗證「對這些 VMID 的任何寫入在送出前被拒絕」，**不對真機嘗試** | §5、§9 |
| H8 | 不使用也不修改既有範本 80000；Windows 範本另建於我方資源池 | 範本一律是我方區間內、我方池內、由我方建立的 VM | §7.4 |
| H9 | ISO 放 `local`、VM 磁碟放 `local-lvm`；建立前檢查兩者剩餘空間，低於門檻就拒絕並回報；絕不刪除非我方的 ISO、磁碟、快照 | 程式不呼叫任何「刪除儲存內容」的 API；只會透過「刪除我方 VM」釋放自己的磁碟 | §6.3、§7.2 |

---

## 2. 現況（已實測，唯讀）

### 2.1 Proxmox 節點

| 項目 | 實測值 | 對設計的意義 |
|---|---|---|
| 版本 | Proxmox VE 9.2.2 | 權限名稱依 PVE 9（`VM.GuestAgent.*` 系列） |
| 節點 | `pve4-bbf`（單一節點） | 不考慮跨節點 |
| CPU | 32 執行緒（Ryzen 9 9950X），負載 0.2–0.5 | CPU 不是限制 |
| 記憶體 | 共 30.4 GiB。第一次探測：已用 22.6、可用約 7.8 GiB（當時已用到 swap）。**負責人釋出記憶體後：已用約 6.9、可用約 23.5 GiB** | 首要約束。可用量取決於負責人開了哪些既有機器，**會變動**；所以每次建立前都即時檢查，並另設我方的總上限 |
| `local-lvm` | LVM-thin，共 338 GiB、可用約 85 GiB，內容類型 `images,rootdir` | 支援 linked clone 與快照；但 thin pool 寫滿會影響**池上所有 VM（含既有服務）**，必須設門檻 |
| `local` | token 目前讀不到（403）；節點根檔案系統可用僅 **13.7 GiB** | ISO 放這裡要非常小心：根檔案系統寫滿會影響 PVE 本身 |
| `vmbr990` | Linux bridge、啟用中、**無實體埠、無位址**；不是 VLAN-aware | 符合 H4 的隔離前提；但目前不能用 VLAN 區分多個情境 |
| SDN | 沒有任何區域／VNet | 不使用 SDN |
| 既有 VM／CT | 對 token **完全不可見**（`/cluster/resources`、`/nodes/…/qemu`、`/nodes/…/lxc` 皆為空） | ACL 這一層已經成立 |
| 資源池 | `/pools` 回空、`/pools/cr-range` 403（缺 `Pool.Audit`，Lead 已請負責人補） | 清點需要這個權限 |
| VMID 探測 | `GET /cluster/nextid` 回 `100`；`?vmid=501`、`?vmid=80000` 回「VM … already exists」；`?vmid=900000`、`?vmid=900999` 回該值（可用）；`?vmid=1000000000` 回格式錯誤 | 見 §5.1：可用來偵測衝突，即使看不到那台 VM |
| TLS | 自簽憑證；本次探測全程釘選同一張憑證的 SHA-256 指紋（記錄於證據檔） | 產品程式也用指紋釘選 |

### 2.2 token 目前的權限（已實測）

token：`root@pam!crs-dev`，權限分離。

| 路徑 | 角色 | 實際擁有的權限 |
|---|---|---|
| `/pool/cr-range` | PVEVMAdmin | `VM.Allocate`、`VM.Clone`、`VM.Audit`、`VM.PowerMgmt`、`VM.Config.*`（CPU／Memory／Network／Disk／CDROM／Cloudinit／Options／HWType）、`VM.Snapshot`、`VM.Snapshot.Rollback`、`VM.GuestAgent.*`（Audit／FileRead／FileWrite／FileSystemMgmt／Unrestricted）、`VM.Console`、`VM.Backup`、`VM.Migrate`、`VM.Replicate` |
| `/storage/local-lvm` | PVEDatastoreUser | `Datastore.AllocateSpace`、`Datastore.Audit` |
| `/sdn/zones/localnetwork/vmbr990` | PVESDNUser | `SDN.Use`、`SDN.Audit` |
| `/nodes/pve4-bbf` | PVEAuditor | **唯讀**：`Sys.Audit`、`Datastore.Audit`、`SDN.Audit`、`Pool.Audit`、`Mapping.Audit`、`VM.Audit`、`VM.GuestAgent.Audit` |

節點上只有唯讀的稽核權限，沒有 `Sys.Modify`／`Sys.PowerMgmt`／`Sys.Console`——符合 H1。與最小權限的差距見 §5.4。

### 2.3 開發主機上的現況（引用 reviewer 的獨立重測）

`reports/overnight/evidence/reviewer/host-isolation-retest.md`（reviewer，main `e1d4d26`，只做 TCP 連線探測、不送 exploit）：
- 三個計畫（Struts、Log4Shell Solr＋`cr-listener`、有發布埠的 nginx）中的所有實驗容器，對宿主機所有真實位址（docker0、區網、tailscale、其他 bridge；IPv4 與 IPv6）× 所有在聽的埠：**全部連不到**；公網也連不到。
- 殘餘只有 `cr-gateway`（發布埠用的轉發容器）：它連得到宿主機的 22／4000／8000。

也就是說，現有 Docker 路徑的容器層隔離已成立；搬到 farm 要解決的是另外三件事：漏洞映像不該跑在共用的開發主機上、VM 與容器互通在開發主機上需要 sudo、以及 `cr-gateway` 這個殘餘（farm 上不生成它，§3.3）。

---

## 3. 可抽換的執行後端

### 3.1 介面

一個情境對應一個「環境」。上層（路由、驗證器）不知道底下是 Docker 還是 Proxmox。

| 方法 | 用途 | `local-docker`（現有行為搬入） | `proxmox` |
|---|---|---|---|
| `preflight` | 部署前唯讀檢查 | 現有隔離預檢＋容量預檢 | 權限自檢、範本存在、記憶體／儲存餘量、VMID 可用、bridge 仍無位址 |
| `plan` | **乾跑**：回傳將要送出的呼叫清單 | 將執行的 compose 指令 | §8 |
| `up` | 建立並啟動；冪等 | 現有 `do_up` | clone → 設定 → 開機 → 等 agent → 送入 Compose → `up --wait` → 驗證 → 快照 |
| `status`／`health` | 各主機狀態 | 現有 | VM 狀態＋VM 內 `docker compose ps`＋Windows 原生檢查 |
| `down` | 清除 | 現有 | 只刪我方 VM |
| `reset` | 回到乾淨狀態 | down＋up | 回滾快照 |
| `exec`／`probe`／`addresses` | 驗證器用的三個動作 | 現有 `exec_in_service`／`probe_in_service`／`container_ipv4_addresses` | 經 agent 在 VM 內做同樣的事 |
| `platform_events` | 平台元件證據（回呼 listener） | 現有 `callback_events` | 經 agent 讀容器輸出 |
| `isolation_evidence` | 部署後的隔離事實 | 現有 `host_isolation_report` | §4.4 |
| `inventory` | 我方在後端上的全部資源 | 名稱前綴 | 資源池成員＋標記 |
| `describe` | 後端名稱、是否允許漏洞映像與攻擊探針 | 不允許 | 守門通過時允許 |

選擇：`CR_RUNTIME_BACKEND=local-docker|proxmox`（預設 `local-docker`）。**不做自動退回**：Proxmox 不可用時回報「未設定／不可用」，不會把漏洞映像悄悄改跑在開發主機上。

### 3.2 現有程式要改的接點

| 檔案 | 現在綁死本機 Docker 的地方 | 改法 |
|---|---|---|
| `deploy/manager.py` | `_docker_context_preflight`（只接受本機 socket）、`_compose_command`（在 API 主機跑 compose）、`probe_in_service`、`container_ipv4_addresses`、`callback_events`、`host_isolation_report`（讀本機 bridge）、`capacity_preflight`（讀本機記憶體）、`allocate_host_ports` | 原封搬進 `deploy/backends/local_docker.py`；`manager.py` 留下選擇後端、稽核紀錄、冪等指紋；新增 `deploy/backends/proxmox.py` 與 `deploy/pve_client.py`（HTTP、TLS、攔截、乾跑、遮蔽機密） |
| `iac/generator.py` | 產物只有 Compose；`cr-gateway`＋`edge` 是為了把埠開在 API 主機 | Compose 生成不變（在工作 VM 內照跑）；新增「環境清單」（工作 VM 規格、需要的 Windows VM、需要的映像 digest）；`proxmox` 後端下不生成 `cr-gateway`／`edge` |
| `validator/runner.py`（poc-eng） | 直接呼叫 manager 的 Docker 函式；VM 分支自己組 `virsh` 指令 | 改走介面的 `exec`／`probe`／`addresses`／`platform_events`；守門改問 `isolation_evidence`；**後端不允許攻擊時，動作專屬探針一律 NOT_TESTED 並寫明原因** |
| `routers/deploy.py` | 不綁 Docker | 回應加 `backend` 與 `vms[]`（VMID、狀態；不含任何連線資訊或憑證）；`/preflight` 的容量改由後端提供；新增乾跑參數 |
| `deploy/vm.py`（libvirt） | 本機 KVM | 無人值守應答檔產生器與 agent 健康檢查可重用；本身的去留見 §11.2 D7 |

### 3.3 模型比較與建議（結論不變）

| 面向 | A. 容器跑在每情境一台工作 VM 內 | B. 每台情境主機一台 VM | C. 每台情境主機一個 LXC |
|---|---|---|---|
| 與漏洞映像的隔離邊界 | VM（獨立核心） | VM | 與 PVE 主機共用核心 |
| 重用現有成果 | catalogue、Compose、healthcheck、探針全部照用 | 幾乎不能，每種軟體要另做 VM 映像 | 部分，需重做 |
| **記憶體**（本環境的首要限制） | 一台 VM 的固定開銷（約 0.5–0.8 GiB）＋容器實際用量 | 每台主機各一份固定開銷；5 台主機的情境放不進 7.8 GiB | 最省 |
| 重置 | 一個快照 | 多台要協調 | 同 B |
| 主要缺點 | 多一層；映像要預置在範本 | 維護成本與記憶體都負擔不起 | 漏洞工作負載跑在 hypervisor 的核心上 |

**建議採 A。** 在這台記憶體吃緊、且有既有服務的 PVE 上，B 放不進去，C 讓刻意含弱點、以 root 執行的映像直接共用 hypervisor 核心——與「絕對不能動到既有服務」衝突，不建議。

---

## 4. 隔離

### 4.1 目標

實驗環境必須連不到：PVE 管理介面（192.168.16.214 的 8006／22）、區網與網際網路、**節點上的既有服務**（保護清單內的機器）、其他情境。

### 4.2 網路

- 使用產品負責人已建好的 `vmbr990`（已實測：無實體埠、無位址）。**我們不建立、不修改任何節點網路**；程式裡沒有對應的寫入路徑（§5.3）。
- 既有機器接在別的 bridge 上，與 `vmbr990` 沒有任何 L2／L3 相連；只要沒有人把既有機器的網卡接到 `vmbr990`、也沒有 VM 同時橫跨兩邊並開啟轉送，流量就碰不到既有服務。我方 VM **只會有 `vmbr990` 一張網卡或沒有網卡**，建立後由程式讀回設定核對（§4.4 V7）。
- `vmbr990` 不是 VLAN-aware，所以目前無法用 VLAN 區分多個情境。處理方式：

| 情境類型 | 工作 VM 網卡 | 多個情境並存時的隔離 |
|---|---|---|
| 純 Linux、不開放學員連入 | **零張** | 完全沒有網路；不需要 bridge |
| 純 Linux、開放學員經跳板連入（§4.5） | 一張，接 `vmbr990` | `vmbr990` 上只有這個情境的工作 VM 與跳板機 |
| 含 Windows VM | 工作 VM 與 Windows VM 各一張，接 `vmbr990` | **同一時間只允許一個**這類情境使用 `vmbr990`（由程式的配額強制）。記憶體也只容得下一個（§6） |

  P0 實測 `vmbr990` 仍不是 VLAN-aware（Lead 已請負責人勾選）。在它變成 VLAN-aware 之前，**`vmbr990` 上同一時間只放一個情境**（不分 VLAN）：兩個純 Linux 情境並行時，只有一個能接 `vmbr990`（開放學員連入），另一個不接網卡；勾選之後每個情境用一個 VLAN 編號（網卡加 `tag=`），程式以唯讀方式讀到 VLAN-aware 才會啟用並行。我們不經 API 改這個設定。
- 含 Windows 的情境裡，工作 VM 內把需要與 Windows 互通的計畫網段做成接在那張網卡上的 Docker `ipvlan`／`macvlan` 網路，位址由我們靜態指派（bridge 上沒有 DHCP、沒有閘道）。〔待實測〕

### 4.3 管理通道

- 唯一通道：PVE API → QEMU guest agent（執行指令、寫檔、讀檔）。這是 hypervisor 的 virtio-serial 通道，不是網路；實驗環境拿不到它的另一端，也不需要在 VM 裡放任何憑證。
- 不用 SSH、不放管理網卡、不開主控台給實驗環境。
- 後端主機 → PVE：HTTPS 8006，**憑證指紋釘選**；不接受關閉驗證。
- 已知限制（API 規格，已核對）：agent 寫檔單次內容上限 **61,440 字元**；指令的標準輸入上限 65,536；讀檔單次上限 16 MiB（超過會標示被截斷）；指令輸出可能被截斷（回應有 `out-truncated` 旗標）。因此：Compose 檔分段寫入；映像預置在範本裡、不經 agent 傳；長輸出在 VM 內寫檔後以讀檔取回並檢查截斷旗標。

### 4.4 部署後自動驗證（結果進 `isolation_evidence`）

| # | 檢查 | 方法 | 通過條件 |
|---|---|---|---|
| V1 | `vmbr990` 仍無位址、無實體埠 | 唯讀讀取節點網路設定（已用此法實測過一次） | 與 §2.1 相同；**每次部署前後都檢查**，一旦有人改了它就拒絕部署 |
| V2 | 工作 VM → PVE 管理介面 | 經 agent 在 VM 內對 192.168.16.214 的 8006／22 與節點其他位址連線 | 全部失敗 |
| V3 | 每個容器 → PVE／區網／後端主機／公網 | 沿用現有的宿主可達性探針，從每個容器的網路命名空間發出 | 全部失敗 |
| V4 | Windows VM → 同上 | 經 agent 在 Windows 內測（libvirt 版已有做法） | 全部失敗 |
| V5 | 實驗環境 → 既有服務 | 對區網位址範圍中「不是我方」的位址抽樣連線。**只做 TCP 連線嘗試、不送內容**；目標清單需產品負責人提供或同意（§11.2 D10），未同意前此項標 NOT_TESTED | 全部失敗 |
| V6 | 情境內的預期路徑 | 計畫的 connections | 連通（避免把「全部不通」誤當成隔離成功） |
| V7 | 我方 VM 的網卡 | 讀 VM 設定 | 工作 VM、Windows VM：零張，或只有一張且 bridge＝`vmbr990`。跳板機：恰好兩張（指定的連入 bridge、`vmbr990`）。沒有多出來的 |
| J1 | 跳板機不轉送 | 經 agent 讀轉送設定與封包過濾規則 | 轉送關閉；規則與範本一致 |
| J2 | 學員金鑰的權限 | 後端用該情境的金鑰實際連線測試 | 能進到攻擊端容器；在跳板機上要求 shell／執行指令被拒；要求轉接到 PVE 管理介面、後端主機、區網閘道、`vmbr990` 上其他位址全部被拒 |
| J3 | 跳板機 → PVE／區網 | 經 agent 在跳板機內主動連 PVE 的 8006／22 與區網閘道 | 全部失敗 |
| J4 | 實驗側 → 跳板機 | 從工作 VM 與攻擊端容器連跳板機實驗側位址的所有常用埠 | 全部失敗 |
| J5 | 登入方式 | 經 agent 讀 sshd 有效設定 | 密碼登入與 root 登入關閉；只聽連入側 |
| J6 | 清除後 | 讀跳板機狀態 | 已回滾、已關機；舊金鑰連不上 |

守門：V1–V4、V7、J1–J5 任一不通過 → 不執行任何攻擊探針、不發出學員金鑰；情境含漏洞映像時自動拆除（與現在 Docker 版一致）。

---

### 4.5 跳板機（已核准的學員連入方式）

**目的**：讓講師／學員從區網進到「這個情境的攻擊端主機」，而且只能到那裡。

**放在哪裡**

```
講師／學員（區網，限定來源）
      │ SSH（金鑰）
      ▼
 ┌──────────── 跳板機 VM（我方，cr-range，VMID 900002）────────────┐
 │ 連入側網卡：負責人指定的 bridge（區網）    實驗側網卡：vmbr990     │
 │ 不轉送封包；sshd 只聽連入側；學員帳號沒有 shell                    │
 └───────────────────────────────────────────────────────────────┘
                                                   │ 只允許到「工作 VM 的實驗側位址:22」
                                                   ▼
                              工作 VM（實驗側網卡在 vmbr990）
                              sshd 只聽實驗側；學員帳號被強制進入攻擊端容器
                                                   │
                                                   ▼
                                     攻擊端容器（非 root、無 capability）
```

- 跳板機是唯一同時接「區網」與「實驗 bridge」的 VM，所以它是整個設計裡最需要收緊的一台。
- **常駐一台、由建置階段建立**（接上區網 bridge 需要該 bridge 的 `SDN.Use`，這個權限只給建置用角色，建完可撤銷；見 §5.5）。執行期 token 只對它做開機／關機／回滾／經 agent 設定，不需要碰區網 bridge。
- 每個情境結束後**回滾到乾淨快照**再關機；沒有情境在跑時它是關機狀態（不占記憶體、不在區網上聽任何埠）。

**如何連入與存取控制**

| 項目 | 作法 |
|---|---|
| 驗證 | 只接受金鑰。每次部署由後端產生一組**該情境專用**的金鑰，公鑰經 guest agent 寫入跳板機與工作 VM，私鑰只提供給啟動部署的講師（由 GUI 下載一次；它是實驗環境的憑證，與 PVE token 無關） |
| 學員在跳板機上能做什麼 | **沒有 shell**。該金鑰在跳板機上被限制為：不配置終端機、不執行指令、只允許轉接到「工作 VM 的實驗側位址:22」這一個目的地（sshd 的 `permitopen` 與 `restrict`），其他轉接一律拒絕 |
| 學員在工作 VM 上能做什麼 | **沒有 shell**。同一把金鑰在工作 VM 上被強制執行一個固定指令：進入攻擊端容器的互動式 shell。學員落地的位置就是攻擊端容器（與平台探針使用的同一個容器） |
| 使用方式 | 講師拿到一行指令（`ssh -J <跳板> <工作VM>` 的形式）與私鑰檔 |
| 來源限制 | 跳板機連入側只接受負責人指定的來源網段（跳板機內的封包過濾；若負責人已啟用 PVE 防火牆，再加一層網卡層級的規則，見下） |
| 失效 | 情境清除時：刪除金鑰、跳板機回滾並關機。金鑰另有到期時間 |
| root／密碼登入 | 全部關閉 |

**如何確保學員只能到該情境**

| 要擋的路徑 | 靠什麼擋 |
|---|---|
| 學員 → PVE 管理介面／區網其他主機（經跳板） | 學員在跳板機上沒有 shell、不能執行指令；轉接目的地被鎖死為工作 VM 一個位址一個埠；跳板機不轉送封包 |
| 學員 → 其他情境 | `vmbr990` 上同一時間只有一個情境的 VM（另一個並行的純 Linux 情境沒有網卡，網路上不存在）；日後多情境時跳板機的實驗側網卡以 VLAN 區分，或每個情境各自回滾並重新綁定 |
| 攻擊端容器 → 跳板機 → 區網／PVE | 容器在工作 VM 的內部網路裡，沒有通往 `vmbr990` 的路由（Docker 內部網路無對外路由）；跳板機的 sshd 不聽實驗側；跳板機不轉送 |
| 工作 VM（若被攻破）→ 跳板機 → 區網 | 跳板機實驗側沒有任何在聽的服務、不轉送封包；實驗側進來的封包一律丟棄 |
| 跳板機本身 → PVE 管理介面／區網 | 跳板機內的封包過濾：連入側只允許「已建立連線的回應」出去，不允許主動連出；實驗側只允許主動連到工作 VM 的 22 |

**誠實的殘餘風險**：跳板機在區網上開了一個 SSH 埠。若 sshd 本身有可利用的弱點，攻擊者會在一台接著區網的 VM 上取得立足點，而 VM 內的封包過濾可以被 VM 內的 root 改掉。要把這一點也關起來，需要 **hypervisor 層級**的規則（PVE 防火牆套在跳板機的連入側網卡：只進 22、只允許回應封包出去）——它在 VM 之外，VM 內改不到。設定 VM 層級規則只需要該 VM 的 `VM.Config.Network`（API 規格），但**前提是資料中心層級的防火牆已啟用**；那是叢集設定、會影響既有機器，只能由負責人決定與操作（§11.2 D13）。我讀不到資料中心防火牆的狀態（需要 `/` 的 `Sys.Audit`）。

---

## 5. 保護既有機器：VMID、攔截、擁有權

### 5.1 保留的 VMID 區間與衝突偵測

**我方區間：900000–900999。**

| 子區間 | 用途 |
|---|---|
| 900000–900009 | 我方範本（Linux 工作 VM、Windows） |
| 900010–900099 | 範本建置用的暫時 VM |
| 900100–900999 | 情境 VM |

選擇理由：
- 與保護清單（501、2001–2002、3001–3004、80000–80001）**完全不重疊**，而且隔了一個數量級以上，不會因為打錯一位數而落進去。
- 既有機器用三到五位數（最大 80001）；`9xxxxx` 是六位數、9 開頭，一眼可辨識為另一群。
- 已實測（P0）：區間兩端與中間共 19 個取樣號碼目前全部可用；保護清單的 9 個號碼全部回報「已存在」；API 規格載明 VMID 上限為 999999999。
- 區間做成設定（`CR_PVE_VMID_RANGE`），但**程式拒絕任何與內建拒絕清單重疊、或下限小於 100000 的設定**。

衝突偵測（因為 token 看不到既有 VM，不能靠列表）：
- 建立前對候選 VMID 送 `GET /cluster/nextid?vmid=<N>`。已實測：VMID 已被占用時回 400「VM N already exists」（對 token 看不到的 501、80000 也是），可用時回 `N`。這是唯讀查詢，不會保留或改變任何東西。
- **不使用不帶參數的 `GET /cluster/nextid`**：已實測它回 `100`（全域最小的可用號碼），落在我方區間之外。
- 這個檢查與實際建立之間有時間差；PVE 在建立／clone 時若 VMID 已存在會拒絕，程式以那次拒絕為準、換下一個號碼重試（上限次數）。
- 我方區間內若出現「不是我方建立」的 VM（不在池內或沒有我方標記）：視為異常，跳過該號碼、記錄並回報，**不碰它**。

### 5.2 三重擁有權驗證（破壞性操作前）

破壞性操作＝刪除、停止、關機、重設、回滾、改設定、在 VM 內執行指令或寫檔、轉為範本。執行前**即時**向 PVE 讀取並確認以下全部成立：

1. **VMID 在我方區間內**，且不在拒絕清單。
2. **是資源池 `cr-range` 的成員**（讀資源池成員清單；需要 `Pool.Audit`）。
3. **帶有我方標記**：標籤含 `cyberrange`，且說明欄是我方寫入的 JSON、其中的 `scenario_id`／`host_id`／`created_by` 與後端資料庫的紀錄一致。

任何一項不成立 → 拒絕、不送出任何請求、寫一筆稽核紀錄（誰、想對哪個 VMID 做什麼、哪一項不符）。標記在建立當下就寫入（clone 時帶 `pool`、`name`、`description`，緊接著設定標籤）；若建立後寫標記失敗，該 VM 立即走失敗清理（此時它仍符合第 1、2 項，且有 clone 時寫入的說明）。

### 5.3 送出前的攔截（HTTP 用戶端層，與 5.2 互相獨立）

所有對 PVE 的請求都經過同一個用戶端；**GET 以外的請求必須同時通過下列檢查，否則在送出前拒絕並記錄**：

1. **內建拒絕清單**（寫死在程式裡，設定只能增加、不能移除）：`501, 2001, 2002, 3001, 3002, 3003, 3004, 80000, 80001`。路徑或參數中出現這些 VMID 的任何寫入請求一律拒絕——包含把它們當成 clone 來源（H8：不使用既有範本 80000）。
2. **區間檢查**：路徑中的 VMID、以及參數中的 `newid`／`vmid`，都必須在我方區間內。clone 的來源必須在我方的範本子區間內。
3. **可寫路徑白名單**：只有下列形式存在；其他寫入路徑在程式裡沒有對應的呼叫，白名單也會擋下：

| 允許的寫入 | 用途 |
|---|---|
| `POST /nodes/{node}/qemu/{我方範本}/clone` | 建立情境 VM |
| `POST`／`PUT /nodes/{node}/qemu/{我方VM}/config` | 規格、網卡、標籤、說明 |
| `POST /nodes/{node}/qemu/{我方VM}/status/{start,shutdown,stop}` | 電源 |
| `POST`／`DELETE /nodes/{node}/qemu/{我方VM}/snapshot…`、`…/rollback` | 快照與重置 |
| `POST /nodes/{node}/qemu/{我方VM}/agent/{exec,file-write}` | VM 內操作 |
| `DELETE /nodes/{node}/qemu/{我方VM}` | 銷毀 |
| （僅範本建置，另一個開關）`POST /nodes/{node}/qemu`（VMID 在範本建置子區間、`pool=cr-range`）、`POST …/template`、`POST /nodes/{node}/storage/local/upload` | 見 §7 |

4. `{node}` 必須等於設定的節點名稱。
5. **程式裡不存在、白名單也不允許**：`/nodes/{node}/network`（節點網路）、`/nodes/{node}/status`（重開機／關機）、`/cluster/*`、`/access/*`、`/pools` 的寫入、`/storage` 的寫入、任何儲存內容的 `DELETE`、`/nodes/{node}/lxc/*`、遷移、備份、複寫。

這一層不依賴 PVE 的回應，所以可以用 mock 完整測試（§9）。

### 5.4 權限：現況與最小集合

權限名稱已依 PVE 9 官方文件核對，並與 §2.2 的實測一致。

| 路徑 | 現況 | 設計實際需要 | 建議 |
|---|---|---|---|
| `/pool/cr-range` | PVEVMAdmin | `VM.Allocate`、`VM.Clone`、`VM.Audit`、`VM.PowerMgmt`、`VM.Config.CPU`／`Memory`／`Network`／`Options`／`CDROM`／`Cloudinit`／`Disk`、`VM.Snapshot`、`VM.Snapshot.Rollback`、`VM.GuestAgent.Audit`／`FileRead`／`FileWrite`／`Unrestricted`；範本建置另需 `VM.Config.HWType` | 現況多出 `VM.Migrate`、`VM.Backup`、`VM.Replicate`、`VM.Console`、`VM.GuestAgent.FileSystemMgmt`，我們用不到。可接受（範圍仍只在池內）；若要收緊，改成只含上列權限的自訂角色 |
| `/pool/cr-range` | 缺 `Pool.Audit` | `Pool.Audit`（擁有權驗證第 2 項、清點都需要） | **必須補**（Lead 已請負責人加 PVEPoolUser） |
| `/storage/local-lvm` | PVEDatastoreUser | `Datastore.AllocateSpace`、`Datastore.Audit` | 剛好；**不需要也不應給 `Datastore.Allocate`**（那可以刪除別人的磁碟） |
| `/sdn/zones/localnetwork/vmbr990` | PVESDNUser | `SDN.Use` | 剛好 |
| `/nodes/pve4-bbf` | PVEAuditor（唯讀） | `Sys.Audit`（讀記憶體餘量、讀 bridge 設定） | 可接受：全部是唯讀。若要更小，改成只含 `Sys.Audit` 的自訂角色 |
| `/storage/local` | 無 | 見 §7.2 | 視 D4 而定 |

**明確不需要、請勿授予**：`Sys.Modify`、`Sys.PowerMgmt`、`Sys.Console`、`Permissions.Modify`、`User.Modify`、`SDN.Allocate`、`Datastore.Allocate`、`Pool.Allocate`、`Mapping.*` 的寫入，以及任何落在 `/`、`/vms`、`/nodes`（寫入類）上的 ACL。

備註：token 掛在 `root@pam` 之下。權限分離的 token 只擁有被授予的 ACL（官方文件），所以實際權限就是 §2.2；但若日後有人關掉它的權限分離，它會變成 root 的完整權限。建議長期改掛在專用使用者（例如 `cyberrange@pve`）之下，並設定到期日（§11.2 D11）。

---

### 5.5 給產品負責人的 pveum 指令

下列指令**請負責人在 PVE 上自行檢視後執行**；我沒有執行過，也沒有權限執行。每個權限對應的 API 檢查都依這台 PVE 的 API 規格核對過（`evidence/infra-eng/pve-p0/api-permissions.json`）。

#### a. 執行用 token 還缺的最小權限

目前只缺一項（P0 實測 `GET /pools/cr-range` 仍回 403）：

```
pveum acl modify /pool/cr-range -token 'root@pam!crs-dev' -role PVEPoolUser
```

| 角色 | 帶來的權限 | 用途 |
|---|---|---|
| PVEPoolUser | `Pool.Audit` | 讀取資源池成員：三重擁有權驗證的第 2 項、殘留清點都靠它（API 規格：`GET /pools/{poolid}` 檢查 `/pool/{poolid}` 的 `Pool.Audit`） |

不需要再加其他東西。**不要**加 `Pool.Allocate`（可改資源池成員）、`Datastore.Allocate`、任何 `Sys.*` 的寫入權限。

（選用，收緊）現在 `/pool/cr-range` 上的 PVEVMAdmin 比需要的多。若要換成最小角色：

```
pveum role add CRRuntime -privs "VM.Allocate VM.Clone VM.Audit VM.PowerMgmt VM.Config.CPU VM.Config.Memory VM.Config.Network VM.Config.Options VM.Config.CDROM VM.Config.Cloudinit VM.Config.Disk VM.Snapshot VM.Snapshot.Rollback VM.GuestAgent.Audit VM.GuestAgent.FileRead VM.GuestAgent.FileWrite VM.GuestAgent.Unrestricted Pool.Audit"
pveum acl modify /pool/cr-range -token 'root@pam!crs-dev' -role CRRuntime
pveum acl delete /pool/cr-range -token 'root@pam!crs-dev' -role PVEVMAdmin
pveum acl delete /pool/cr-range -token 'root@pam!crs-dev' -role PVEPoolUser
```

| 權限 | 用途（對應的 API 檢查） |
|---|---|
| `VM.Allocate` | 以 clone 建立 VM（檢查 `/pool/{pool}`）、刪除我方 VM |
| `VM.Clone` | 從我方範本 clone（檢查來源範本） |
| `VM.Audit` | 讀 VM 設定與狀態（擁有權驗證、V7） |
| `VM.PowerMgmt` | 開機、關機、停止 |
| `VM.Config.CPU`／`Memory` | 套用規格 |
| `VM.Config.Network` | 設定網卡接 `vmbr990`（另需該 bridge 的 `SDN.Use`，已有） |
| `VM.Config.Options` | 寫入標籤與說明（我方標記） |
| `VM.Config.CDROM`、`VM.Config.Cloudinit` | 掛載唯讀映像包、設定主機名稱 |
| `VM.Config.Disk` | clone 會建立磁碟（另需 `local-lvm` 的 `Datastore.AllocateSpace`，已有） |
| `VM.Snapshot`、`VM.Snapshot.Rollback` | 建立重置點、重置 |
| `VM.GuestAgent.Audit` | agent 的 ping、OS 資訊、網卡資訊 |
| `VM.GuestAgent.FileWrite`／`FileRead` | 送入 Compose、取回輸出 |
| `VM.GuestAgent.Unrestricted` | 在 VM 內執行指令（API 規格：`agent/exec` 與 `exec-status` 只接受這一個權限） |
| `Pool.Audit` | 讀資源池成員 |

#### b. 建置用權限（建範本與跳板機時才需要，建完即可撤銷）

建議另開一個 token 專做建置，與執行用 token 分開，這樣撤銷時不影響執行：

```
# 1. 建置用 token（權限分離）
pveum user token add root@pam crs-build -privsep 1

# 2. 只含必要權限的自訂角色
pveum role add CRBuildVM      -privs "VM.Allocate VM.Audit VM.PowerMgmt VM.Config.CPU VM.Config.Memory VM.Config.Network VM.Config.Options VM.Config.CDROM VM.Config.Cloudinit VM.Config.Disk VM.Config.HWType VM.Snapshot VM.GuestAgent.Audit VM.GuestAgent.FileRead VM.GuestAgent.FileWrite VM.GuestAgent.Unrestricted Pool.Audit"
pveum role add CRBuildUpload  -privs "Datastore.AllocateTemplate Datastore.Audit"
pveum role add CRBuildDisk    -privs "Datastore.AllocateSpace Datastore.Audit"
pveum role add CRBuildNet     -privs "SDN.Use"
pveum role add CRBuildAudit   -privs "Sys.Audit"

# 3. 授權（<建置用bridge> 與 <跳板機連入bridge> 請填實際名稱，可以是同一座）
pveum acl modify /pool/cr-range                               -token 'root@pam!crs-build' -role CRBuildVM
pveum acl modify /storage/local                               -token 'root@pam!crs-build' -role CRBuildUpload
pveum acl modify /storage/local-lvm                           -token 'root@pam!crs-build' -role CRBuildDisk
pveum acl modify /sdn/zones/localnetwork/vmbr990              -token 'root@pam!crs-build' -role CRBuildNet
pveum acl modify /sdn/zones/localnetwork/<建置用bridge>        -token 'root@pam!crs-build' -role CRBuildNet
pveum acl modify /nodes/pve4-bbf                              -token 'root@pam!crs-build' -role CRBuildAudit
```

| 路徑 | 權限 | 用途（對應的 API 檢查） |
|---|---|---|
| `/pool/cr-range` | `VM.Allocate` | 建立建置用 VM（`POST /nodes/{node}/qemu` 帶 `pool=cr-range`）、轉成範本（`…/template` 檢查 `VM.Allocate`）、刪除建置失敗的我方 VM |
| | `VM.Config.HWType` | 設定機型、SCSI 控制器、序列埠等硬體類型（Windows 範本需要 q35／SATA／e1000e） |
| | `VM.Config.Disk`、`CDROM`、`Cloudinit`、`CPU`、`Memory`、`Network`、`Options` | 建立系統碟（含由上傳的雲端映像匯入）、掛安裝 ISO、cloud-init 光碟、規格、網卡、標記 |
| | `VM.PowerMgmt` | 建置期間開機／關機 |
| | `VM.Snapshot` | 跳板機的乾淨快照 |
| | `VM.GuestAgent.*`（Audit／FileRead／FileWrite／Unrestricted） | 以 agent 確認安裝完成、在範本內安裝套件與預先載入映像 |
| | `VM.Audit`、`Pool.Audit` | 讀設定、確認池成員 |
| `/storage/local` | `Datastore.AllocateTemplate` | 上傳 ISO 與雲端映像（`POST …/upload` 只檢查這一個；內容類型 `iso` 或 `import`） |
| | `Datastore.Audit` | 讀 `local` 的剩餘空間與現有檔案（上傳前的門檻檢查、沿用既有 ISO） |
| `/storage/local-lvm` | `Datastore.AllocateSpace`、`Datastore.Audit` | 建立範本磁碟 |
| `/sdn/zones/localnetwork/vmbr990` | `SDN.Use` | 範本與跳板機的實驗側網卡 |
| `/sdn/zones/localnetwork/<建置用bridge>` | `SDN.Use` | **建置期間暫時上網**（裝套件、拉映像）；以及跳板機的連入側網卡 |
| `/nodes/pve4-bbf` | `Sys.Audit` | 唯讀：建置前檢查記憶體餘量 |

**刻意不含**：
- `Datastore.Allocate`——API 規格載明「刪除儲存內容」需要它；不給它，建置用 token 就**刪不掉 `local` 上任何既有的 ISO 或磁碟**。代價是我們上傳的檔案事後也只能由負責人刪除（檔名一律以 `cr-` 開頭）。
- `Sys.AccessNetwork`／`Sys.Modify`——「由 PVE 自己從網址下載」需要它們（API 規格），而且等於讓 token 能間接探測節點所在的網路。我們改成由後端主機下載、驗證雜湊後再上傳，所以不需要。
- `VM.Clone`（建置不 clone 任何東西）、`VM.Migrate`、`VM.Backup`、`VM.Console`、`Pool.Allocate`、`SDN.Allocate`、`Permissions.Modify`。

**負責人另需做的一件事**：`local` 要允許內容類型 `import`（上傳雲端映像用；只是在既有清單上**加**一項，不要取代原清單）。我讀不到 `local` 目前的設定。若不想開 `import`，Linux 範本改用安裝 ISO 做無人值守安裝（較慢，但只需要 `iso`）。

**建完之後撤銷**（執行用 token 不受影響）：

```
pveum user token remove root@pam crs-build
pveum role delete CRBuildVM ; pveum role delete CRBuildUpload ; pveum role delete CRBuildDisk
pveum role delete CRBuildNet ; pveum role delete CRBuildAudit
```

建置期間的風險（請負責人知悉）：建置用 VM 暫時接在有上行的 bridge 上，期間它在區網上；它只執行官方套件安裝與映像下載，不含任何實驗工作負載，建完就移除該網卡。重建範本時要再授權一次。

---

## 6. 容量：以記憶體為首要約束

### 6.1 預算

```
本次可用 = min( 資源池記憶體上限 − 我方已配置 ,  節點即時可用 − 保留餘量 )
```

- **資源池記憶體上限**（`CR_PVE_POOL_MEM_MIB`）：**16 GiB**（Lead／負責人指定）。這是我方所有執行中 VM 設定記憶體的加總上限，用意是留餘裕給負責人日後重新開機的既有機器。
- **節點即時可用**：每次建立前唯讀讀取（目前約 23.5 GiB；既有機器全開時曾低到 7.6 GiB）。
- **保留餘量**（`CR_PVE_MEM_RESERVE_MIB`）：建議 3 GiB。即使在上限內，只要「即時可用 − 保留餘量」不夠，就拒絕。也就是說：負責人把既有機器開回來之後，我們能用的量會自動變小，不需要改設定。
- 我方 VM 一律固定記憶體、不依賴 ballooning、不超賣；估算用「設定的記憶體」。

### 6.2 規格與可行組合

| 規格 | vCPU／記憶體 | 用途 |
|---|---|---|
| **worker（預設）** | **2／4 GiB** | 情境的容器。主線 Equifax（容器上限合計 1.75 GiB）、Log4Shell（約 1.9 GiB）、WordPress＋MySQL（約 2.2 GiB）都放得下。容器上限合計超過約 3.2 GiB 的情境不建立（回報需要更大的規格） |
| **windows** | **2／4 GiB** | Windows Server 2022（與本機 libvirt 已驗證的規格相同） |
| jump | 1／0.5 GiB | 跳板機（§4.5），只跑 sshd |

| 組合 | 記憶體合計 | 上限 16 GiB 下 |
|---|---|---|
| 一個純 Linux 情境＋跳板機 | 4.5 GiB | 可行 |
| **兩個純 Linux 情境**（＋一台跳板機） | 8.5 GiB | **可行（上限）** |
| **一個含 Windows 的情境**：worker＋Windows＋跳板機 | 8.5 GiB | **可行（上限）** |
| 含 Windows 的情境再加任何其他情境 | — | 不允許（配額） |
| Windows 範本建置（安裝階段 4 GiB） | 4 GiB | 可行；與執行中的情境合計不得超過上限 |

配額（已指定）：**同時最多兩個純 Linux 情境，或一個含 Windows 的情境**。

與網路的交互限制（在 `vmbr990` 變成 VLAN-aware 之前）：`vmbr990` 上同一時間只能有**一個**情境的 VM。所以「兩個純 Linux 情境並行」時，最多只有其中一個能開放學員經跳板連入（它的工作 VM 接 `vmbr990`）；另一個的工作 VM 不接任何網卡，只有平台自己的驗證。P0 實測 `vmbr990` 仍非 VLAN-aware。

### 6.3 其他上限與檢查（全部可設定；建立前逐項檢查，任何一項不足即拒絕）

| 項目 | 檢查 | 建議預設 |
|---|---|---|
| 記憶體 | 所需 ≤ min（資源池上限 − 我方已配置，節點即時可用 − 保留餘量） | 資源池上限 16 GiB；保留 3 GiB |
| 同時情境數／VM 台數 | 計數我方池內的執行中 VM | 兩個純 Linux 情境，或一個含 Windows 的情境；最多 4 台執行中的 VM |
| 每台 VM 的 vCPU／記憶體／磁碟 | 規格表以外的尺寸不建立 | 上表 |
| `local-lvm` 剩餘 | 建立後預估剩餘 ≥ 門檻 | **保留 40 GiB**。這是 thin pool：寫滿時池上所有 VM（含既有服務）都會出錯，所以門檻要寬 |
| 我方磁碟總量 | 我方所有 VM 的虛擬磁碟大小加總（含範本） | ≤ 120 GiB（thin；實際寫入遠小於此，仍受上一列門檻約束） |
| `local` 剩餘 | 上傳後預估剩餘 ≥ 門檻 | **保留 8 GiB**（節點根檔案系統目前只有 13.7 GiB 可用） |
| CPU | 我方 vCPU 合計 | ≤ 8（節點 32 執行緒，負載低，不是瓶頸） |

**不足時的行為（H9）**：拒絕建立，回應與稽核紀錄寫明「哪一項不足、差多少、需要通知產品負責人」。程式**不會**為了騰出空間或記憶體而刪除、停止、縮小任何東西；它唯一會釋放的資源是「使用者明確要求清除的我方情境 VM」。孤兒只列出、不自動刪（§7.6）。

---

## 7. 生命週期

### 7.1 命名與標記

| 項目 | 規則 |
|---|---|
| 資源池 | `cr-range`（情境 VM 與我方範本都在這裡；範本以標籤 `cr-template` 區分，程式不對帶此標籤的 VM 做電源／刪除操作，範本建置流程除外） |
| VM 名稱 | `cr-<情境短碼>-worker`、`cr-<情境短碼>-<主機id>`、`cr-tpl-<種類>-<日期>` |
| 標籤 | `cyberrange`、`cr-scn-<情境短碼>`、`cr-role-worker|windows|template`、`cr-inst-<後端實例碼>` |
| 說明 | 一行 JSON：`created_by`、`scenario_id`、`host_id`、`created_at`、`template`、`compose_sha256`、`backend_instance` |

### 7.2 `local` 上的 ISO／雲端映像（D4 已決定：由我方自動建範本）

- 權限：只需要 `Datastore.AllocateTemplate`＋`Datastore.Audit`（建置用角色，§5.5 b）。API 規格已核對：
  - 上傳（`POST /nodes/{node}/storage/local/upload`）只檢查 `Datastore.AllocateTemplate`；可帶 `checksum` 讓 PVE 核對雜湊。
  - **刪除儲存內容需要 `Datastore.Allocate`**——我們不要這個權限，所以建置用 token 刪不了 `local` 上任何東西，包含既有的 ISO。
  - 「由 PVE 從網址下載」另需節點層級的 `Sys.AccessNetwork`——不使用。
- 檔案由後端主機下載、核對 sha256 後上傳；檔名一律 `cr-` 開頭。上傳前先列出 `local` 的內容：同名或同雜湊的檔案已存在就沿用、不重複上傳，也絕不覆寫不是 `cr-` 開頭的檔案。
- cloud-init 光碟建立在 `local-lvm`，不需要 `local`。我們不使用自訂 cloud-init 片段。

所需空間：Windows Server 2022 評估版 ISO 約 5.0 GiB、virtio-win ISO 約 0.9 GiB、Linux 雲端映像約 0.6 GiB、應答媒體不到 1 MiB，合計約 6.5 GiB。節點根檔案系統目前可用 13.7 GiB；全部上傳後剩約 7.2 GiB，**低於門檻 8 GiB → 依規則會拒絕並回報**。可行的順序：
1. 先只做 Linux 範本（0.6 GiB，上傳後剩約 13 GiB，通過）。
2. Windows 範本需要再 5.9 GiB：若 `local` 上已有 Windows Server 2022 評估版與 virtio 的 ISO 就沿用；否則需要負責人決定（清出空間、調低門檻、或另指定存放位置，§11.2 D9）。我們不會自己騰空間。

### 7.3 Linux 工作 VM 範本

依官方 Cloud-Init 文件的做法（建立 VM → 匯入雲端映像為系統碟 → 加 cloud-init 光碟 → 設開機順序 → 轉為範本），加上：

1. VMID 900000，放在 `cr-range`，標籤 `cyberrange`、`cr-template`。
2. 啟用 QEMU guest agent；裝 `qemu-guest-agent`、Docker Engine 28 以上、Compose 外掛。
3. 預先拉取 catalogue 的所有釘 digest 映像，並把 digest 清單寫進 VM 內固定位置，供部署前比對。
4. **建置階段需要上網一次**（裝套件、拉映像），但 `vmbr990` 沒有上行。做法：建置用 VM 暫時接一張網卡到負責人指定的建置用 bridge（需要該 bridge 的 `SDN.Use`，屬建置用權限）；建置完成後移除這張網卡再轉成範本。執行期 token 永遠沒有這座 bridge 的權限。
5. 收尾：移除網卡、清除機器識別與 cloud-init 狀態、關機、轉為範本。

磁碟：系統約 3 GiB＋映像約 4 GiB，虛擬大小設 20 GiB（thin）。由範本做 linked clone（`local-lvm` 是 LVM-thin，支援）。

### 7.4 Windows Server 2022 Evaluation 範本

- **不使用、不 clone、不修改既有範本 80000**（拒絕清單會擋下以它為來源的 clone）。
- 我方範本 VMID 900001，放在 `cr-range`。
- 建議做法：在 PVE 上用官方評估版 ISO 重新做無人值守安裝，重用已在本機驗證過的應答檔產生器（隨機管理員密碼只存在暫時的應答媒體中）與硬體組合（q35、SATA 磁碟、e1000e 網卡、建置期間不接網路），以 guest agent 回報完成為準，然後轉為範本。
- 不建議匯入本機 libvirt 的 qcow2：Windows 對虛擬硬體變更敏感，且傳檔需要 PVE 的檔案存取。
- 應答媒體是一個很小的 ISO（不到 1 MiB），由建置用 token 上傳到 `local`，建置完成後不再使用（我們無權刪除，請負責人擇時移除 `cr-unattend-*.iso`）。注意它含有一次性的隨機管理員密碼。
- Windows 範本定期重建（評估版授權，已核准）。
- 評估版授權：180 天，且要求 10 天內上網啟用；隔離環境不上網（§11.2 D5）。

### 7.5 部署流程

```
預檢（權限、範本、記憶體、儲存、vmbr990 無位址）
 → 挑 VMID（nextid?vmid=N 確認未被占用）
 → clone 我方範本（linked；帶 pool=cr-range、name、description）
 → 設標籤、規格、（含 Windows 時）網卡 bridge=vmbr990
 → 開機 → 等 guest agent
 → 經 agent 送入 Compose → VM 內 docker compose up --wait
 → 隔離驗證（§4.4）→ 快照 "deployed" → 回報
```

| 操作 | 作法 |
|---|---|
| 建立 | linked clone。每個 PVE 動作回傳工作識別碼，輪詢到結束並檢查結果 |
| 重置 | 停止 → 回滾到 `deployed` 快照 → 開機 → 健康檢查 |
| 停止（保留） | 關機不刪除（記憶體即釋放） |
| 銷毀 | 三重驗證 → 停止 → 刪除該 VM（PVE 會一併移除設定中引用的磁碟與快照）→ 清點確認。不使用 `purge`（那會改動備份／HA 等叢集設定）、不使用 `skiplock`（API 規格：僅 root 可用）、不使用 `destroy-unreferenced-disks` |
| 冪等 | 沿用現有指紋：同一份產物已在執行且健康 → 不動 |
| 逾時 | 每步各自逾時；整體逾時走失敗清理 |
| 並行 | 每情境一把鎖；配額：兩個純 Linux 情境或一個含 Windows 的情境；`vmbr990` 同時只給一個情境 |

### 7.6 失敗清理與殘留清點

- 任一步失敗：先收集（VM 狀態、工作紀錄、agent 可用時的容器狀態與輸出）→ 只刪除**本次流程建立、且通過三重驗證**的 VM。
- 殘留清點：列出 `cr-range` 的成員，凡帶我方標記而後端資料庫沒有對應紀錄者列為孤兒。**只列出**；刪除需要管理者在介面上明確操作，且仍要通過三重驗證。
- 我方區間內出現沒有我方標記的 VM、或池內出現不在我方區間的 VM：列為「異常、未處理」，不碰。

---

## 8. 乾跑模式（H5）

- 用戶端有三種模式：`probe`（只允許 GET，其他一律拒絕——第一階段使用）、`dry-run`、`live`。預設不是 `live`；要執行寫入必須明確設定（`CR_PVE_MODE=live`）且通過預檢。
- `dry-run`：GET 照常送出（唯讀，用來讓計畫內容是真實的：實際可用的 VMID、實際的記憶體餘量）；**每一個非 GET 請求都不送出**，改為記入計畫清單，後續步驟需要的回傳值以占位符表示。
- 計畫清單每一筆包含：順序、方法、路徑、參數（密值遮蔽）、目的、會影響的 VMID、它通過了哪些攔截檢查。清單末尾列出「預估占用」（記憶體、磁碟）與預檢結果。
- 入口：`GET /api/deploy/{id}/preflight?plan=1`（或等效的指令列工具），回傳清單；不寫入稽核以外的任何東西。
- 乾跑與實跑走**同一段程式**，差別只在最後「送出」那一步，避免「乾跑說的」與「實際做的」不一致。測試會比對兩者的呼叫序列（mock）。

範例（示意，主線 Equifax）：

```
#  方法   路徑                                                   影響VMID  目的
1  POST   /nodes/pve4-bbf/qemu/900000/clone  newid=900100 …      900100   由我方範本建立工作 VM
2  PUT    /nodes/pve4-bbf/qemu/900100/config  tags=… memory=3072  900100   標記與規格（無網卡）
3  POST   /nodes/pve4-bbf/qemu/900100/status/start                900100   開機
4  POST   /nodes/pve4-bbf/qemu/900100/agent/file-write            900100   送入 Compose
5  POST   /nodes/pve4-bbf/qemu/900100/agent/exec                  900100   docker compose up --wait
6  POST   /nodes/pve4-bbf/qemu/900100/snapshot  snapname=deployed 900100   建立重置點
預估占用：記憶體 3072 MiB（預算 4864 MiB）；local-lvm 新增至多 20 GiB（thin）
```

---

## 9. 測試計畫

**原則：凡是「應該被拒絕的危險操作」，一律用 mock／乾跑驗證，不對真機嘗試。**

### 9.1 以 mock API 驗證（不連線真機）

| 案例 | 預期 |
|---|---|
| 對保護清單內每一個 VMID（501、2001、2002、3001、3002、3003、3004、80000、80001）逐一嘗試：刪除、停止、關機、重設、改設定、建快照、回滾、agent 執行、agent 寫檔、轉範本 | **每一項都在送出前被拒絕**；mock 伺服器收到的寫入請求數為 0；各有一筆稽核紀錄 |
| 以 80000 為來源做 clone | 送出前被拒絕（H8） |
| clone 的目標 VMID 在保護清單內或在我方區間外 | 送出前被拒絕 |
| 設定檔把我方區間改成與保護清單重疊、或下限小於 100000 | 啟動即拒絕 |
| 設定檔嘗試從拒絕清單移除項目 | 無效；內建清單仍生效 |
| 對我方區間內、但不在 `cr-range` 的 VM 做破壞性操作 | 三重驗證第 2 項不符 → 拒絕 |
| 對 `cr-range` 內、但沒有我方標記的 VM | 第 3 項不符 → 拒絕 |
| 對 `cr-range` 內、有標記、但 VMID 不在我方區間的 VM | 第 1 項不符 → 拒絕 |
| 白名單以外的寫入路徑（節點網路、節點電源、叢集、存取控制、資源池寫入、儲存內容刪除、LXC、遷移、備份） | 送出前被拒絕；且以靜態檢查確認程式碼中沒有這些路徑字串 |
| `probe` 模式下的任何非 GET | 被拒絕 |
| `dry-run` 下跑完整部署 | mock 收到的非 GET 請求數為 0；計畫清單與 `live` 模式（對 mock）的呼叫序列一致 |
| 記憶體不足／`local-lvm` 低於門檻／`local` 低於門檻／超過台數 | 拒絕建立，訊息含差額與「需通知產品負責人」；mock 收到的寫入請求數為 0；**沒有任何刪除請求** |
| VMID 已被占用（`nextid?vmid=` 回 400） | 換下一個；重試有上限 |
| 建立途中各步驟失敗（clone、設定、開機、agent 逾時） | 只刪除本次建立的 VM；不碰其他 |
| 密值外流 | 請求紀錄、例外訊息、稽核紀錄、API 回應中搜尋不到 token 密值；送進 VM 的任何內容不含密值 |
| `vmbr990` 出現位址或實體埠 | 預檢拒絕部署 |

### 9.2 對真機、且只限唯讀

- 已完成：版本、節點容量、儲存餘量、bridge 設定、權限自檢、既有 VM 不可見、`nextid` 行為（§2）。
- 待補權限後：讀取 `cr-range` 成員（應為空）。

### 9.3 對真機的寫入（產品負責人確認設計之後才開始，且只在我方區間內）

依 §10 的階段，每一步先乾跑、把清單給負責人看過，再實跑。任何真機測試都**不包含**「嘗試操作保護清單內的機器」。

---

## 10. 分階段落地

| 階段 | 內容 | 退出條件（可驗收） | 是否寫入 PVE |
|---|---|---|---|
| **P0 唯讀探測（已完成，§12）** | §2 的全部項目；逐項核對〔待核對〕 | 探測結果與本文件一致；可用唯讀方式確認的項目全部確認；負責人確認設計。**尚餘一項**：補 `Pool.Audit` 後確認資源池為空 | **否** |
| **P1 抽出介面** | 現有 Docker 行為搬進 `local-docker` 驅動；驗證器改走介面；行為不變 | 現有測試全數通過；真實 Docker 主線結果不變；`proxmox` 未設定時回報「未設定」而非退回 | 否 |
| **P2 用戶端與攔截（僅 mock）** | `pve_client`：指紋釘選、三種模式、拒絕清單、區間、白名單、三重驗證、容量預檢、乾跑清單 | §9.1 全部通過；對真機只跑過 `probe` 模式 | 否 |
| **P3 範本與跳板機** | 我方以建置用 token 建置（D4）：先乾跑、清單經負責人確認後才實跑；Linux 範本（900000）、跳板機（900002） | `cr-range` 內有我方 Linux 範本（900000）；由它 clone 的 VM 在無網卡下 agent 可用、Docker ≥ 28、映像齊全；保護清單內機器的狀態與設定前後一致（由負責人確認） | 是（僅我方區間） |
| **P4 工作 VM 生命週期** | clone → 開機 → agent → 快照 → 重置 → 銷毀 → 清點 | 連續 10 次建立→重置→銷毀後池內零殘留；每步注入失敗後零殘留；節點可用記憶體在任何時刻不低於保留餘量；隔離 V1、V2、V7 通過；紀錄中搜尋不到密值 | 是（僅我方區間） |
| **P5 情境在工作 VM 內執行＋學員連入** | 送入 Compose、驗證器經後端、守門接 `isolation_evidence`；跳板機接上情境 | 主線（Equifax）在 farm 上部署成功並通過動作專屬探針；V1–V3、V6、V7、J1–J6 通過；以情境金鑰能進到攻擊端容器且到不了別處；`local-docker` 下漏洞映像被拒絕部署、攻擊探針為 NOT_TESTED 且理由正確（D6） | 是 |
| **P6 Windows VM** | Windows 範本（900001）；與工作 VM 同接 `vmbr990`；容器與 Windows 互通 | 記憶體上限內完成（worker＋Windows＋跳板機＝8.5 GiB）；Linux 容器能連到 Windows 服務；Windows 原生健康檢查通過；V4 通過；可重置、可銷毀且零殘留 | 是 |
| **P7 營運** | 配額畫面、孤兒清點、範本重建、token 更換；**移除本機 libvirt 後端**（D7：Windows 階段驗收後） | 配額超過時拒絕並說明；孤兒清點能列出刻意留下的殘留 | — |

---

## 11. 風險、需決定事項、待核對事項

### 11.1 風險

| 風險 | 影響 | 因應 |
|---|---|---|
| 記憶體被我方 VM 吃緊 | 既有服務變慢或被系統回收；或負責人重開既有機器時記憶體不夠 | 資源池上限 16 GiB；節點保留餘量；固定記憶體不超賣；建立前即時檢查。注意：我方 VM 已在執行時，負責人再開既有機器仍可能吃緊——我們不會自動關機讓位，只會在狀態頁顯示節點餘量低於保留值的警告 |
| `local-lvm` thin pool 寫滿 | **池上所有 VM 出錯** | 寬門檻（保留 40 GiB）；我方磁碟總量上限；linked clone 減少寫入 |
| `local`（根檔案系統）寫滿 | PVE 本身異常 | 門檻；優先由負責人放 ISO 或沿用既有檔案；我們不刪任何東西 |
| 程式錯誤對錯誤的 VMID 發出寫入 | 動到既有機器 | 三層：ACL 看不到 → 送出前攔截（拒絕清單＋區間＋白名單）→ 三重驗證；mock 測試涵蓋保護清單每一台 |
| token 外洩 | 可操作 `cr-range` 內的 VM、占用 `local-lvm` 空間 | 範圍僅限池內；四道防外流措施與測試；建議設到期日 |
| token 掛在 `root@pam`，權限分離若被關閉即為完整 root | 所有保護失效於 ACL 層 | 建議改掛專用使用者（D11）；程式的攔截層不依賴 ACL，仍然有效 |
| `vmbr990` 日後被改動（加了位址或實體埠） | 隔離失效 | 每次部署前後檢查，不符即拒絕 |
| `vmbr990` 非 VLAN-aware | 不能讓兩個情境同時使用它 | 程式以唯讀方式確認 VLAN-aware 之前，`vmbr990` 同時只配給一個情境 |
| agent 傳輸上限 | 大檔傳不進去 | 映像預置於範本；長輸出分段讀 |
| 範本與 catalogue 不同步 | 部署時缺映像 | 範本內放 digest 清單，部署前比對，缺就拒絕 |
| 兩個後端並存造成誤用 | 漏洞映像跑回開發主機 | 不自動退回；`local-docker` 拒絕漏洞映像與攻擊探針 |

### 11.2 產品負責人的決定

**已決定（2026-11-15，記於 `docs/approved-scope.md`）**

| # | 事項 | 決定 |
|---|---|---|
| D2 | 我方 VMID 區間 | 900000–900999 |
| D3 | 講師／學員如何連入 | **另建跳板機**（§4.5） |
| D4 | 範本與 ISO 由誰準備 | **我方自動建**；負責人另給建置用權限（§5.5 b） |
| D5 | Windows 評估版授權 | 接受定期重建範本 |
| D6 | `local-docker` 是否可部署漏洞映像 | **禁止**漏洞映像與攻擊探針 |
| D7 | 本機 libvirt 後端 | Proxmox 的 Windows 階段驗收後**移除** |
| D8 | 容量預設 | 資源池記憶體上限 16 GiB；同時最多兩個純 Linux 情境或一個含 Windows 的情境；工作 VM 2 核／4 GiB、Windows VM 2 核／4 GiB；建立前以即時剩餘容量為準 |
| — | TLS | 釘選憑證指紋 |
| D1 | 多情境並行 | 兩個純 Linux 情境可並行，但 `vmbr990` 同時只給一個；負責人把 `vmbr990` 設為 VLAN-aware 之後才開放多個情境同時使用它 |

**仍需決定**

| # | 事項 | 我的建議 |
|---|---|---|
| D8′ | 保留餘量與儲存門檻的確切數字 | 節點記憶體保留 3 GiB、`local-lvm` 保留 40 GiB、`local` 保留 8 GiB |
| D9 | `local` 空間不足以放 Windows 所需的 ISO | 沿用 `local` 上既有的 ISO（若有）、清出空間、或另指定存放位置 |
| D10 | 是否主動驗證「實驗環境連不到既有服務」（V5） | 需要可測的位址清單或明確同意；否則標 NOT_TESTED，只有結構性證據 |
| D11 | token 是否改掛專用使用者並設到期日 | 建議改（目前掛在 `root@pam`） |
| D12 | `/pool/cr-range` 是否收緊為自訂的最小角色 | 可選（§5.5 a） |
| D13 | 跳板機連入側是否加 PVE 防火牆規則 | 建議加，但前提是資料中心防火牆已啟用——那是會影響既有機器的叢集設定，只能由負責人判斷。未啟用時只有 VM 內的封包過濾，殘餘風險見 §4.5 |
| D14 | 跳板機接哪一座 bridge、允許哪些來源網段連入 | 需要負責人指定（token 只看得到 `vmbr990`，我不知道區網 bridge 的名稱） |
| D15 | 建置期間用哪一座 bridge 上網 | 可與 D14 同一座 |
| D16 | `local` 是否開放內容類型 `import` | 建議開（只加不取代）；不開則 Linux 範本改走安裝 ISO |

### 11.3 P0 之後仍待核對

| 項目 | 為什麼還沒核對 | 何時、如何核對 |
|---|---|---|
| `cr-range` 目前的成員（應為空） | `GET /pools/cr-range` 仍回 403，缺 `Pool.Audit` | 負責人執行 §5.5 a 的指令後，唯讀讀取 |
| `local` 的內容類型、剩餘空間、是否已有可用的 ISO | token 對 `local` 沒有任何權限（403） | 授予建置用權限後，唯讀讀取 |
| 資料中心防火牆是否啟用 | 需要 `/` 的 `Sys.Audit`，我們不應有這個權限 | 請負責人告知（D13） |
| 區網 bridge 的名稱 | 節點網路清單只回 token 有權使用的 bridge | 請負責人告知（D14、D15） |
| 工作 VM 內 ipvlan／macvlan 與 `vmbr990` 的相容性 | 需要實際部署 | P6 |
| 以上傳的雲端映像匯入為系統碟（`import-from`）在建置用權限下是否足夠 | API 規格只寫「建立磁碟需要 `Datastore.AllocateSpace`」，沒有單獨說明匯入來源的檢查 | P3：以乾跑清單對照，第一次實跑若被拒，回應會指出缺少的權限 |
| 同名檔案上傳是否會覆寫 | API 規格未說明 | 不依賴它：上傳前先列出內容，同名即不上傳 |

---

## 12. P0 結果（2026-11-15，全程唯讀）

證據目錄：`reports/overnight/evidence/infra-eng/pve-p0/`
- `readonly-probe-p0.json`：45 個 GET 的原始回應（不含密值）；`get-paths.txt`：送出的路徑清單。
- `apidoc.js`：這台 PVE 提供的 API 規格（靜態檔，下載時未帶任何憑證）；`api-permissions.json`：從中擷取的權限檢查與參數上限。
- `P0-RESULTS.md`：下表的完整版。
- 工具：`tools/pve-probe/readonly_probe.py`（只會送 GET，沒有其他方法的程式路徑；憑證指紋全程釘選）、`tools/pve-probe/apidoc_extract.py`。

**送出的請求只有 GET；沒有任何 POST／PUT／DELETE。**

### 12.1 原先 12 處〔待核對〕的結果

| # | 項目 | 結果 | 依據 |
|---|---|---|---|
| 1 | 每支 API 實際檢查哪個權限 | **已核對**：clone、設定、電源、快照、回滾、轉範本、刪除、agent 各動作、上傳、刪除儲存內容、資源池——逐支列於 `api-permissions.json`，§5.5 的權限表即依此 | API 規格 |
| 2 | guest agent 的大小上限 | **已核對**：寫檔 61,440 字元；標準輸入 65,536；讀檔 16 MiB；輸出有截斷旗標 | API 規格 |
| 3 | 儲存類型是否支援 linked clone／快照 | **已核對**：`local-lvm` 是 LVM-thin（兩者皆支援）；clone 的 API 說明「對範本預設做 linked clone」 | 實測＋API 規格 |
| 4 | `SDN.Use` 的 ACL 路徑寫法 | **已核對**：`/sdn/zones/localnetwork/vmbr990`（即 token 現有的 ACL） | 實測 |
| 5 | VNet 名稱長度上限 | **不適用**：節點沒有任何 SDN 區域／VNet，設計不使用 SDN | 實測 |
| 6 | `/cluster/nextid` 的行為 | **已核對**：不帶參數回全域最小可用號碼（100）；帶 `vmid=N` 時，已占用回 400「VM N already exists」（對 token 看不到的 VM 亦然），可用則回 N；VMID 範圍 100–999999999；任何使用者皆可呼叫、不保留號碼 | 實測＋API 規格 |
| 7 | `Datastore.AllocateTemplate` 是否能刪除既有 ISO | **已核對：不能**。刪除儲存內容需要 `Datastore.Allocate` | API 規格 |
| 8 | 是否支援上傳 qcow2／雲端映像 | **已核對**：上傳的內容類型為 `iso`、`vztmpl`、`import`；雲端映像走 `import`（需 `local` 開放該內容類型，D16） | API 規格 |
| 9 | 工作 VM 內 macvlan／ipvlan 的相容性 | **未核對**（需實際部署） | §11.3 |
| 10 | PVE 9.1 的 OCI→LXC 功能 | **不再相關**：設計不使用 LXC | — |
| 11 | Windows Core 2 GiB | **不再需要**：負責人釋出記憶體後 Windows VM 用 4 GiB（已在本機 libvirt 驗證過的規格） | — |
| 12 | 由 PVE 從網址下載所需的權限 | **已核對**：另需 `Sys.AccessNetwork`（節點）或 `/` 的 `Sys.Audit`＋`Sys.Modify`；設計不使用此功能 | API 規格 |

### 12.2 P0 退出條件

| 條件 | 結果 | 實測內容 |
|---|---|---|
| 版本與節點 | 通過 | PVE 9.2.2；節點 `pve4-bbf`；32 執行緒；記憶體 30.4 GiB。三次讀取的可用量：7.8 → 7.6 → **23.5 GiB**（負責人釋出記憶體後；`readonly-probe-capacity.json`）——印證可用量會大幅變動，必須每次即時檢查 |
| token 權限與預期相符 | 通過 | 四條 ACL，內容同 §2.2；沒有任何節點層級的寫入權限 |
| 看不到、也讀不到池外的任何 VM | 通過 | `/cluster/resources` 只有節點與 `local-lvm`；`/nodes/pve4-bbf/qemu`、`…/lxc` 皆為空 |
| 保護清單的 VMID 確實存在、我方區間確實可用 | 通過 | 501、2001、2002、3001–3004、80000、80001 全部回「already exists」；900000–900999 取樣 19 個（含兩端）全部可用；區間外相鄰的 899999、901000 也可用 |
| 實驗 bridge 存在且無位址、無上行 | 通過 | `vmbr990`：啟用中、`bridge_ports` 為空、沒有位址、IPv4／IPv6 皆為 manual |
| 實驗 bridge 是否 VLAN-aware | **否**（尚未勾選；三次讀取皆同） | `vmbr990` 上同時只放一個情境 |
| 儲存餘量 | 通過（有門檻） | `local-lvm` 可用 85.4 GiB／338 GiB；節點根檔案系統可用 13.7 GiB |
| 能列出資源池（應為空） | **未通過：缺權限** | `GET /pools/cr-range` 回 403（缺 `Pool.Audit`）→ §5.5 a |
| 能讀 `local` | **未通過：尚無權限** | 403；待建置用權限 |
| 〔待核對〕逐項核對 | 12 項中 8 項已核對、3 項不適用或不再需要、1 項需實際部署才能核對 | §12.1 |
| 負責人確認設計 | 通過 | `docs/approved-scope.md` |

**P0 的結論**：設計的前提（ACL 範圍、既有 VM 不可見、VMID 衝突偵測、bridge 隔離、儲存能力）都以唯讀方式確認成立。進入寫入階段之前還需要：負責人執行 §5.5 a 的一行指令、決定 D14／D15（bridge）與 D9（`local` 空間），以及 Lead 的明確通知。
