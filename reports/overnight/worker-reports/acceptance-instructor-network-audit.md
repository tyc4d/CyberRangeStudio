# 講師入口網路盤點

日期：2026-11-16  
環境：PVE `pve4-bbf`，API 位址 `192.168.16.214:8006`  
操作：僅使用 `.env` 中既有 runtime/build token 做 TLS 指紋釘選的 GET；沒有送出 PVE 寫入、啟動/停止 VM、或碰觸網路設定。

## 結果

- PVE 9.2.2；`cr-range` 目前只有停止狀態的範本 VMID 900000，沒有情境 worker。
- `local-lvm` 可用空間約 78.9 GiB；節點報告可用記憶體約 23.6 GiB。這不會改變程式的 16 GiB pool 預算、保留值或單台 worker 規格。
- 節點目前列出的網路介面是 `vmbr990`、`nic0`、`nic1`、`wlp7s0`。只有 `vmbr990` 是 bridge；它 `active=1`、`bridge_ports=""`、IPv4/IPv6 `manual`，符合現有無上行實驗網路。沒有列出外部 bridge。
- PVE 的 SDN zone 與 VNet 清單均為空。
- runtime token 權限只有節點 `Sys.Audit`，以及 `vmbr990` 的 `SDN.Use`/`SDN.Audit`；build token 只有節點 `Sys.Audit` 與 `vmbr990` 的 `SDN.Use`，兩者都沒有 `Sys.Modify` 或 `SDN.Modify`。它們不能建立 node bridge、SDN zone/VNet 或套用節點網路設定。
- 目前工作 VM 一律零網卡，`attach_lab_network` 仍 fail closed；拓樸和部署 UI 不會提供虛構的講師端點。

## 已採用的連入範圍

產品負責人已明確授權 Lead 自行建置講師入口。預設來源限縮為主機上實際觀察到的本地子網 `192.168.16.0/20`。這是根據 host `192.168.16.213/20` 與 PVE 管理位址 `192.168.16.214` 的同網段位址推定；它比先前預覽頁所允許的 `/16` 窄。此範圍可作為跳板入口的 source allowlist，不能直接套用在實驗服務上。

目標仍依已核准的跳板設計：外側只允許來源 allowlist 到跳板的明確講師端口；內側連 `vmbr990`，並只轉送該情境明確發布且經測試的服務端口。跳板不得路由到 PVE 管理網、其他情境或區網任意位址。所有 V1–V7/J1–J6 隔離驗證通過前，漏洞映像和攻擊探針維持封鎖。

## 阻塞與處理界線

現有 API 權限不能新增外部 bridge、SDN zone/VNet 或 firewall rule。直接修改 PVE 節點網路需要 `Sys.Modify`，而錯誤套用可能讓節點失聯；Proxmox 管理指南也明確提示網路配置錯誤可能使節點無法連線（[PVE Administration Guide](https://pve.proxmox.com/pve-docs/pve-admin-guide.pdf)）。目前無具備此權限且可安全映射到外側實體網路的既有 bridge，因此不能以建立未連線的第二個隔離 bridge 假稱完成講師入口。

我沒有用 runtime/build token 嘗試寫入，也沒有建立無法實際連外的跳板 VM。入口的安全需求與預設 source range 已記錄在 `docs/approved-scope.md`；需先配置受控的外側 bridge/SDN 並授予最小必要 ACL，之後才能部署跳板、指定 firewall allowlist、再驗收外部可達性。這是 P5 的明確阻塞，不影響目前唯讀 QA 預覽。
