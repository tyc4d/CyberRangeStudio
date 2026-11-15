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
  - Lead 採用的預設（負責人未反對）：VMID 區間 900000–900999；先限制同時一個情境、工作 VM 2 核／4 GiB（節點記憶體僅剩約 7.8 GiB）；TLS 釘選憑證指紋；Windows 評估版接受定期重建範本。
