# 部署管理的放置位置視圖

## 參考與設計邊界

TrapA 公開產品頁的截圖呈現暗色 SOC Room：左側是垂直事件時間線，右側是所選事件的詳細面板。產品頁文字提及可模擬 DMZ、防火牆、AD、郵件伺服器與檔案伺服器，但沒有公開伺服器放置管理畫面。

- 產品頁：<https://trapa.tw/en/products>
- 公開截圖：<https://trapa.tw/static/images/tcr.png>

CRS 部署頁採用分區明確、選取項目後查看細節的呈現方式，並依 CRS 已有資料顯示兩種位置：

1. **執行資源位置**：PVE provider → node → resource pool → worker VM。這些欄位來自 PVE runtime 設定與實際 VM config/status。
2. **情境邏輯位置**：核准環境計畫中的 network segment → scenario host/service。這表示隔離實驗網路的歸屬，不代表實體機房位置。

目前沒有 site、datacenter、rack、row 或 U 座標資料，不顯示推測的實體位置。要調整情境伺服器的網段歸屬，使用者仍從部署頁連到「拓樸」頁操作，避免在部署畫面修改已核准計畫。

## API 資料

- PVE `preflight` 帶 `placement_target`：provider、node、pool、template VMID、worker VMID 範圍和核准 worker 規格。未部署時用它呈現目標位置。
- PVE `status` 帶 `placement.worker_vm`：VMID/name/state、CPU、記憶體、磁碟與 NIC 數量。部署狀態 API 將資料傳至前端。
- 情境 host 與 network 資料來自 `environment_plan`；每台主機可列在多個 network segment 下。前端重複顯示多網段主機，並標示這是網段歸屬，不是多台 VM。
- 容器明細、health、published ports 與 audit 輸出收在展開區，主視圖先保留放置位置、運行狀態與伺服器細節。
