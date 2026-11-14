# Claude B — Scenario / Intelligence Engineer（名稱 scenario-eng）
先讀 `reports/overnight/briefs/COMMON.md`。埠段 8101–8109。
檔案所有權：`apps/api/app/cti/**`、`apps/api/app/scenario/**`、`apps/api/app/planner/**`（**不含** `planner/catalogue/**`，那屬 infra-eng）、對應 `apps/api/app/routers/` 中模組 1–5 的 router、相關測試。`packages/contracts/**` 由你主責（其他人要改會找 Lead）。前端 `apps/web/**` 不歸你，發現前端問題寫進報告。

任務：檢查並修復模組 1–5 後端（情資解析、缺失分析與補件、攻擊流程編輯、軟體依賴、拓樸）。
1. 先盤點：讀程式與現有測試，用真實情資實跑（`fixtures/sample-scenarios/cisa-aa22-320a.md`、clop-moveit、STIX 範例；cti-research 稍後會在 `fixtures/cti-candidates/` 提供更多與 expected.md 標準答案）。把實際輸出和情資原文逐項比對，列出問題：行為順序錯、漏節點、無根據的 AI 推論被標成事實、引句對不上原文、temporal/dependency 混淆、相依錯誤、缺失項不具體、補件後沒有正確回寫、Scenario IR 與 Environment Plan（依賴／拓樸）不一致。
2. 依嚴重度修復，做根因修正而非針對單一案例硬編碼。每個修復補單元／整合測試（LLM 用錄製／mock 輸入，不在測試中打真 API）。
3. 真實 LLM 驗證至少跑兩份不同情資，保存輸入、輸出、比對結果為證據。
4. 第一個里程碑：盤點問題清單（含嚴重度與重現方式）→ 回報；之後每修完一批回報一次。
