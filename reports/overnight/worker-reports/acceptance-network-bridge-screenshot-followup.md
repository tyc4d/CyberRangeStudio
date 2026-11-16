# PVE 網路截圖與即時 API 清單差異

日期：2026-11-16。使用者提供 PVE Network 畫面截圖，顯示：

- `vmbr0` 是 Linux bridge，連接 `nic0`，CIDR `192.168.16.214/24`，gateway `192.168.16.1`。
- `vmbr1` 是 Linux bridge，comment `ctf1`；截圖的 Ports/Slaves、CIDR、Gateway 欄為空。
- `vmbr990` 的 Ports/Slaves、CIDR、Gateway 欄也為空。

我隨後用 repo root `.env` 內 runtime token 和 build token，分別透過釘選 TLS 的 PVE client 對 `https://192.168.16.214:8006/api2/json/nodes/pve4-bbf/network` 執行 GET。兩次都回 HTTP 200，介面清單都是 `nic0`、`nic1`、`wlp7s0`、`vmbr990`；都沒有 `vmbr0`、`vmbr1`。原始篩選後結果見 `reports/overnight/evidence/pve-network-screenshot-reconcile-20261116.json`。

截圖上方的 node 標題沒有入鏡；因此目前不能證明截圖與 API 查詢是同一個 node 或同一份已套用設定。也不能由截圖推定 `vmbr1` 已接到任何實體網路或可讓學員連入。`vmbr0` 顯示的是管理 LAN，不能直接作為靶場服務入口。既有 runtime/build token 審查沒有 `Sys.Modify`／`SDN.Modify`，且應用程式目前仍禁止 worker NIC；我沒有嘗試新增 NIC、修改 bridge、套用防火牆或啟動 VM。

目前處理：保留 P5 阻塞，不把截圖單獨當作橋接可用或入口可達的驗收證據。需要先讓畫面所示 node/config 與釘選 API 回應一致，再確認既有 bridge 的權限和隔離用途；之後才能決定是否可沿用，而不是新增外部 bridge。
