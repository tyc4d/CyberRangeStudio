# infra-eng 過夜報告（模組 6 IaC／模組 7 部署／catalogue／Windows VM）

分支：`agent/infra-eng`。完整技術報告與證據：`reports/overnight/INFRA-VALIDATION.md`、
`reports/overnight/evidence/infra-eng/`。

## 做了什麼

1. **盤點**：模組 6、7 的實際能力矩陣（修復前／修復後各一份），每格附真實執行的證據。
2. **修掉的問題**（都有真實 Docker 重測）：
   - 兩個情境同時部署會撞主機埠 → 部署時挑空埠、撞埠自動重試。
   - 部署失敗留下容器與網路 → 先收集失敗原因（狀態、log、healthcheck 輸出），再自動清乾淨。
   - 共用 `edge` 網路讓應隔離的主機互通、內部主機可上網 → 實驗服務不再接 edge。
   - `container_ipv4` 取到 edge 位址，讓驗證器把「關閉的埠」誤判成「隔離成功」→ 只回計畫網路的位址。
   - 實驗容器連得到宿主機的服務（sshd 等）→ 計畫網路改用宿主機側沒有位址的模式；對外埠改由一個轉發容器負責。
   - 真實服務沒有健康檢查、沒有啟動順序、沒有資源上限 → 都補上，且由 catalogue 資料驅動。
3. **catalogue**：真實釘版映像從 4 個增加到 11 個（MySQL、MariaDB、Redis、Tomcat、WordPress，
   以及 Struts 2.3.30、Solr 8.11.0 兩個漏洞練習標的），每個都實際部署並核對版本。
4. **跨服務真實相依**：WordPress＋MySQL，實測「停掉 DB → Web 回 500 → DB 回來 → Web 恢復」。
5. **Windows VM（B4 Phase 1）**：不用 sudo，在本機 KVM 真實跑通——從官方評估版 ISO 無人值守安裝
   Windows Server 2022、隔離網路（宿主機側無位址；從 Windows 內連不到宿主機與外部）、由 Windows 自己回報的
   健康檢查、正常關機、再開機、重置（標記檔消失）、銷毀後無殘留。過程中兩次失敗都已查明並修正
   （把斷電誤當安裝完成；主機上的 virtio-win ISO 是下載中斷的殘檔）。細節與 BLOCKED 項目見 INFRA-VALIDATION §6。
6. **轉發容器不可被利用**（reviewer G1）：`cr-gateway` 只監聽 edge 位址，實驗容器連不到轉發埠。

## 改了哪些檔

- `apps/api/app/iac/generator.py`、`apps/api/app/iac/test_generator.py`
- `apps/api/app/deploy/manager.py`、`apps/api/app/deploy/vm.py`（新）、
  `apps/api/app/deploy/test_local_compose_integration.py`（只在檔尾新增）、`apps/api/app/deploy/test_vm.py`（新）
- `apps/api/app/planner/catalogue/components.json`
- `tools/infra-validation/*`（實測工具與測試用計畫，新）
- `reports/overnight/INFRA-VALIDATION.md`、`reports/overnight/evidence/infra-eng/**`、`.gitignore`（忽略 `/.data/`）

沒有修改共用檔（contracts、`store.py`、`main.py`）與驗證器。

## Commit

| commit | 內容 |
|---|---|
| b97568d | 修復前能力矩陣、實測工具、基準證據 |
| 5059c10 | edge 隔離破口、`container_ipv4`、動態主機埠、失敗清理、catalogue 驅動的 generator、新映像（已併入 main） |
| 227a74c | 實驗網路連不到宿主機、對外埠改走轉發容器、漏洞映像部署前預檢、真實隔離測試 |
| 3e3f0a9 | Windows VM 後端（libvirt/KVM）＋離線測試、報告 §4–§5 |
| 713aa43 | `cr-gateway` 只監聽 edge 位址（修 reviewer G1）＋真實測試 |
| 本次 | VM 真實驗證通過、ISO 完整性檢查、報告 §6–§7 |

## 測試

```
PYTHONPATH=apps/api /home/tyc4d/cr-project/.venv/bin/python -m pytest apps/api tests -q
104 passed, 2 warnings, 3 subtests passed
```

基準（我開始時）：54 passed, 1 failed（失敗的就是撞埠 42000）。
其中 2 項是真實 Docker 整合測試；VM 後端的 26 項是離線測試（不需要 hypervisor），
真實開機驗證另由 `tools/infra-validation/vm_e2e.py` 執行並留證據。

真實部署重測（每個計畫都跑 up → 驗證 → down → 再 up → down，並檢查殘留）：

| 計畫 | 結果 |
|---|---|
| nginx＋PostgreSQL＋attacker | 兩輪皆成功、無殘留 |
| WordPress＋MySQL＋attacker | 兩輪皆成功；第一次嘗試失敗（健康檢查設計錯誤），已修並保留失敗證據 |
| Equifax：Struts 2.3.30＋MySQL＋PostgreSQL＋MariaDB＋attacker | 兩輪皆成功 |
| Solr 8.11.0＋Tomcat＋Redis＋httpd＋attacker | 成功；第一次嘗試抓到「假健康」，已修並保留證據 |
| 同一計畫 3 個情境同時部署 | 皆成功、埠不衝突 |

## 沒做／沒測到的

- `expose=lan`（對區網開埠）：NOT_TESTED，無人值守不對區網開埠。
- 沒有對漏洞映像執行任何 exploit（那是模組 8 的範圍）；我只驗證標的為真、版本正確、隔離有效。
- 停止（保留狀態）與重置：容器端仍未實作（需產品決定）。
- 同網段內的逐埠管制：未實作（Docker 限制，列為已知限制）。
- 三個多餘的 `.stderr` 證據檔想刪但被權限檢查擋下，未刪。
- VM：尚未接到「環境計畫 → 部署」流程、不能與容器互通、評估版無法在隔離網路啟用（見 §6.4）。
- 「Docker < 28 拒絕漏洞映像」「未隔離就自動拆除」兩條防線只有單元測試，本機無法真實觸發。

## 主機上我留下的東西（刻意保留，可還原，不需 sudo）

- libvirt 儲存池 `cr-infra-eng`：Windows ISO、完整的 virtio-win ISO、範本磁碟（共約 12 GB），供重跑驗證用。
- `.worktrees/infra-eng/.data/media/virtio-win-0.1.302.iso`（877 MB，未進版控）。
- 我部署的容器、網路、VM、VM 網路皆已清除（最後一次檢查：`cr-demo-infra-eng*`／`infra-iso*` 為 0）。

## 需產品負責人決定

見 `INFRA-VALIDATION.md` §7.1（D1–D7）。最需要注意的：
- D5：只有「對外」網段的主機才會開埠，內部資料庫不再能從宿主機直接連。
- D6／D7：Windows 評估版授權到期，以及 VM 尚未納入情境部署流程。
