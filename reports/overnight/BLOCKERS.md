# 阻塞與待決事項

| # | 項目 | 狀態 | 說明 / 下次重試條件 |
|---|---|---|---|
| 1 | Codex 預設模型不支援 Ultra | 已解決 | 改用 gpt-6.1-sol ultra；全域 config 的 daybreak=true 與該模型不相容，範本以 `-c daybreak=false` 關閉 |
| 2 | 無 sudo 密碼 | 開放 | 需主機層級變更（例如讓 libvirt-qemu 讀家目錄）時無法自行處理；infra-eng 會回報是否真的需要 |
| 3 | **隔離界線：internal Docker 網路的容器可連到宿主機 0.0.0.0 服務**（reviewer 實測 22、4000、8000 可連） | 開放（高） | 既有問題，非本輪引入。infra-eng 正在找不需 sudo 的緩解；修好並經審查前，**禁止對真實漏洞映像執行實際 exploit**（相關步驟標 NOT_TESTED）。若只能靠主機防火牆（需 sudo）解決 → 需產品負責人決定 |
| 4 | infra-eng 新增以 root 執行的 vulhub 漏洞映像與放寬的 capability | 需產品負責人知悉 | 清單與理由由 infra-eng 寫入 INFRA-VALIDATION.md |
| 5 | Claude Worker 曾因 5 小時用量上限停工（約 6am 恢復） | 已恢復 | 各 Worker 從最後 commit 接續 |
| 6 | Claude 用量上限再次觸發（2026-11-15 約 07:25，11am 恢復） | 開放 | Lead 與所有 Claude Worker 停工；Codex 第二輪 QA（qa-*-r2）不受影響、持續執行。恢復後：(1) 收第二輪 QA 三份報告並寫入 QA-SCORES.md；(2) scenario-eng 從 @1739165 接續（待辦已 hc send 給它：完整測試、Clop 真 LLM 重跑、AA22 15 條關係 unresolved:empty、說明文字被當服務、CVE→產品未帶入）；(3) frontend-eng 讓依賴頁讀新的 blocker／placement；(4) reviewer 審 poc-eng@ac88b44 與 scenario-eng@1739165；(5) 併入後凍結 qa-round3 再測。影片階段尚未啟動 |
