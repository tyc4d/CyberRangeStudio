# 阻塞與待決事項

| # | 項目 | 狀態 | 說明 / 下次重試條件 |
|---|---|---|---|
| 1 | Codex 預設模型不支援 Ultra | 已解決 | 改用 gpt-6.1-sol ultra；全域 config 的 daybreak=true 與該模型不相容，範本以 `-c daybreak=false` 關閉 |
| 2 | 無 sudo 密碼 | 開放 | 需主機層級變更（例如讓 libvirt-qemu 讀家目錄）時無法自行處理；infra-eng 會回報是否真的需要 |
| 3 | **隔離界線：internal Docker 網路的容器可連到宿主機 0.0.0.0 服務**（reviewer 實測 22、4000、8000 可連） | 開放（高） | 既有問題，非本輪引入。infra-eng 正在找不需 sudo 的緩解；修好並經審查前，**禁止對真實漏洞映像執行實際 exploit**（相關步驟標 NOT_TESTED）。若只能靠主機防火牆（需 sudo）解決 → 需產品負責人決定 |
| 4 | infra-eng 新增以 root 執行的 vulhub 漏洞映像與放寬的 capability | 需產品負責人知悉 | 清單與理由由 infra-eng 寫入 INFRA-VALIDATION.md |
| 5 | Claude Worker 曾因 5 小時用量上限停工（約 6am 恢復） | 已恢復 | 各 Worker 從最後 commit 接續 |
| 6 | Claude 用量上限再次觸發（2026-11-15 約 07:25，11am 恢復） | 開放 | Lead 與所有 Claude Worker 停工；Codex 第二輪 QA（qa-*-r2）不受影響、持續執行。恢復後：(1) 收第二輪 QA 三份報告並寫入 QA-SCORES.md；(2) scenario-eng 從 @1739165 接續（待辦已 hc send 給它：完整測試、Clop 真 LLM 重跑、AA22 15 條關係 unresolved:empty、說明文字被當服務、CVE→產品未帶入）；(3) frontend-eng 讓依賴頁讀新的 blocker／placement；(4) reviewer 審 poc-eng@ac88b44 與 scenario-eng@1739165；(5) 併入後凍結 qa-round3 再測。影片階段尚未啟動 |
| 7 | Claude 用量上限第三次觸發（2026-11-15 12:46，4pm 恢復） | 開放 | 停點：main = e1d4d26（已含 Round 2 全部已審修復：scenario-eng@83f3fc6、poc-eng@4908dea、infra-eng@ede047e）。**未併入**：frontend-eng@0f039e2（Round 2 GUI＋共同目標 e2e；reviewer 審到一半，尚無裁決）。恢復後：(1) reviewer 完成 frontend@0f039e2 審查＋三分支疊 main 的整體回歸（後端全測試＋npm run e2e）；(2) 通過即併入、tag `qa-round3`、由 `.worktrees/qa-site` 重啟站台（checkout 新 tag）、啟動三位全新 Codex Ultra 測試者（brief 沿用 *-r2.md，改 round3）；(3) 依結果續修，需連續兩輪 ≥90；(4) 之後寫 FINAL-REPORT.md，再啟動影片階段 |
| 8 | Codex Lead 接續（2026-11-16） | 進行中 | 主線仍是 `main=4c2c5fa`；驗收分支 `agent/acceptance-lead` 尚未推送或合併。Cap-5 候選 API 已切換，真 PVE up/reset/down 後已依負責人指示清除所有情境 worker；兩個 API 均確認 pool 只剩範本 900000、worker/reservation=0。實際 pool 記憶體仍最多約 3 台 worker。P4 未完：V2 需 PVE 管理員提供 `ip -j address show` 完整位址；各階段故障注入缺口仍在。P5 未驗收：缺跳板機外側 bridge／學員來源 CIDR／防火牆確認，V1–V7/J1–J6 與 Equifax PVE 攻擊探針未完成，未執行漏洞探針。並行工作：Claude `agent/claude-mobile-rwd` 做手機 RWD、全站 zh-TW/en i18n 與簡化文案；Codex `agent/eq-cve-precision` 修 EQ CVE 錯配並待獨立複審。`AGENTS.md` 已新增文案與 i18n 規則。後續：先審查與整合兩個分支，再跑凍結版完整回歸及 Round 3；仍需連續兩輪 ≥90，然後寫 FINAL-REPORT.md 並啟動影片階段。 |
