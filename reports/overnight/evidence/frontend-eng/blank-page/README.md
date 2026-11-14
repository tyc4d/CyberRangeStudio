# e2e 偶發「整頁空白」：根因與證據

- `failed-run-with-diagnostics.log`、`failed-run-trace.zip`：在原始條件下重現到的一次失敗。trace 的 network 記錄顯示
  `/src/pages/*.tsx` 九個模組請求全部 `net::ERR_NETWORK_CHANGED`，應用程式沒有啟動，所以畫面是白的。
- `repro-network-change.mjs`：重現腳本。一邊重複載入首頁，一邊建立／移除一個自己的 Docker 網路（`cr-fe-netprobe`）。
  用法 `node repro-network-change.mjs <載入次數> <是否擾動 0|1> <是否啟用 relay 0|1> [chromium 參數…]`（在 apps/web 下執行）。

| 條件 | 載入次數 | 白頁 |
|---|---:|---:|
| 不擾動（主機上其他專案仍可能動 Docker） | 40 | 1 |
| 擾動 | 40 | 4 |
| 擾動 | 60 | 7 |
| 擾動 + `--disable-ipv6` | 40 | 5 |
| 擾動 + `--disable-features=NetworkChangeNotifier,AsyncDns` | 40 | 2 |
| 擾動 + `--host-resolver-rules=MAP * 127.0.0.1` | 40 | 4 |
| 擾動 + GET relay（e2e/net-relay.ts） | 60 | 0 |

每一次白頁都伴隨 ERR_NETWORK_CHANGED。relay 那組載入較慢，同樣 60 次載入期間網路只變動 27 輪（對照組 65 輪）。
