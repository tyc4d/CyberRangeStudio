# 阻塞與待決事項

| # | 項目 | 狀態 | 說明 / 下次重試條件 |
|---|---|---|---|
| 1 | Codex 預設模型不支援 Ultra | 已解決 | 改用 gpt-6.1-sol ultra；全域 config 的 daybreak=true 與該模型不相容，範本以 `-c daybreak=false` 關閉 |
| 2 | 無 sudo 密碼 | 開放 | 需主機層級變更（例如讓 libvirt-qemu 讀家目錄）時無法自行處理；infra-eng 會回報是否真的需要 |
