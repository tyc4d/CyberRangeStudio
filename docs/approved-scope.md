# 已核准範圍（產品負責人）

依 AGENTS.md：只有列在這裡的項目可以開發。由 Lead 維護；每筆註明核准日期。

## 八個模組（2026-11-14／15 核准）
1 情資報告分析、2 缺失項目補齊、3 攻擊流程編輯、4 軟體依賴分析、5 拓樸分析、6 IaC 生成、7 環境部署、8 PoC 驗證，以及其必要整合、測試、修復。不新增第九模組。

## Windows／VM 支援（B4 Phase 1，2026-11-15 核准）
本機 libvirt/KVM 開一台 Windows Server 2022 評估版 VM、隔離網路、可靠清理、原生健康檢查。已完成並驗證。

## 相同 CVE 有可用練習映像時的行為（2026-11-15，經 Codex Lead 記錄於 docs/product-questions.md）
主動提供給使用者確認的教學替代；不自動套用，不宣稱為原產品的真實重現。

## Proxmox VM Farm 執行環境（2026-11-15 核准）
設計：`docs/proxmox-farm-design.md`（infra-eng 分支 d2a1176 起）。
- 目標：PVE 9.2.2，`https://192.168.16.214:8006`，節點 `pve4-bbf`，磁碟 `local-lvm`，ISO／範本檔在 `local`，實驗 bridge `vmbr990`（無上行、無位址），資源池 `cr-range`。
- 模型：每情境一台拋棄式 Linux 工作 VM，容器跑在 VM 內；Windows 主機為同網段的另一台 VM。
- **硬性限制**：該 PVE 不是乾淨環境。不得刪除、停止、修改或重設既有機器：VMID 501 kaliatk、2001 Hill1-Docker、2002 Hill1-Docker-DMZ、3001 DEVCORE-DC01、3002 DEVCORE-DB01、3003 DEVCORE-WEBAP、3004 DEVCORE-DB02、80001 Win11、80000 WindowsServer2019（範本）。只操作自己建立、位於 `cr-range`、帶我方標記的 VM。空間不足時通知產品負責人，不得為騰空間刪除非我方資源。token 只放 `.env`。
- 決定：
  - D3 連入方式：**另建跳板機**（受控的連入通道；需納入隔離設計並重新驗證）。
  - D6：**禁止**在本機 Docker 後端部署漏洞映像與執行攻擊探針；本機 Docker 只做非攻擊類 QA。
  - D4 範本：**由我方自動建置**，產品負責人另給建置用權限。
  - D7：本機 libvirt 後端在 Proxmox 的 Windows 階段（P4）驗收後**移除**。
  - Lead 採用的預設（負責人未反對）：VMID 區間 900000–900999；初始預設為同時一個情境（已於 2026-11-15 核准調為 2、2026-11-16 再核准調為 5，此處僅為歷史紀錄）、工作 VM 2 核／4 GiB（節點記憶體僅剩約 7.8 GiB）；TLS 釘選憑證指紋；Windows 評估版接受定期重建範本。
  - **工作 VM 硬上限調為 5（2026-11-16 產品負責人明確核准）**：同時最多 5 台我方工作 VM（先前上限為 2）。這是硬上限，不代表現有資源可同時部署到 5 台。每台仍為 4096 MiB／20 GiB，保留 3072 MiB 與 40 GiB；目前 PVE `cr-range` 記憶體預算為 16384 MiB，且包含 4096 MiB 範本，因此 pool memory gate 最多容納 3 台 worker（範本 4 GiB＋worker 12 GiB）；節點記憶體與儲存檢查還可能進一步降低數量。節點／pool 記憶體、儲存、預留鎖的拒絕檢查全部保留；任何一項不足仍不建立，也不為騰出空間停止或刪除任何 VM。上線時須先停掉所有舊版 API 程序，再啟動新版（預留表一次性轉換，不可新舊版混跑）。若要讓 5 台同時通過 pool memory gate，需另行核定至少 24576 MiB pool 記憶體預算，並確認節點記憶體與儲存裕度；也可由產品負責人另核定降低單台規格。

## 驗證與規劃行為（2026-11-15 產品負責人決定）
- **探針一律實跑**：不論部署的是原產品還是替代品，驗證都要依「實際部署的服務」把對應的攻擊探針真的跑一遍；不再以假設或推論代替執行。（取代先前「不對替代靶標跑原產品探針」的做法。）報告如實寫明「在什麼上面實際測了什麼、結果如何」：同產品同漏洞＝該行為重現（版本為假設時註明）；跨產品替代＝在替代靶標上實測到該技術，不宣稱為原產品的重現。隔離守門仍須先通過。
- **情資未寫 CVE 編號**：產品名稱與目錄中的漏洞產品相符、且原文寫明該產品弱點被利用時，提出該產品的漏洞練習映像供使用者確認；不自動套用，CVE 與版本標為假設。
- **推定入口**：情資未寫對外主機時，依初始入侵步驟推定入口主機，標「推定入口・待確認」，核准前可改。

## Inventory feature (owner-approved 2026-11-16)
An **Inventory** concept: before analysis, check what OS/service versions are locally available or obtainable
within budget; when the report names something unavailable, auto-propose a same-CVE/technique substitute
(flagged, user-overridable) instead of blocking with version questions; keep genuine questions. Full scope
(services + OS + tools). Design: `docs/inventory/DESIGN.md`. Built via Herdr workers on branch `agent/inventory`.
Honesty rules unchanged (flag substitutes, epistemic_status/version_basis, never claim the original reproduced).
