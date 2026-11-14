# 任務清單

## 進行中
- [ ] A cti-research：候選事件、expected.md 標準答案、負向測試情資 → `CTI-POC-RESEARCH.md`、`fixtures/cti-candidates/`
- [ ] B scenario-eng：模組 1–5 盤點→修復→真實 LLM 兩份情資驗證
- [ ] C infra-eng：模組 6–7 能力矩陣→真實部署循環測試→catalogue 釘版本真實服務→Windows VM 真實開機
- [ ] D poc-eng：模組 8 假 PASS 風險盤點→隔離網路內行為驗收測試
- [ ] E/F/G：QA Round 1（基準評分，針對 main `d99957e`+briefs）

## 待辦（依賴上面）
- [ ] H Integration Reviewer：逐分支審查、跨模組契約、回歸測試（實作者不得自驗）
- [ ] 前端修復 Worker：依 QA Round 1 問題
- [ ] Lead 整合通過審查的分支 → 重啟 QA 站台 → QA Round 2
- [ ] Phase 3：至少兩個真實事件＋一個負向案例 E2E → `E2E-RESULTS.md`
- [ ] Phase 4：反覆 QA 直到 總分≥90、Instructor≥90、Admin≥90、無 Critical/High、連續兩輪通過
- [ ] `QA-SCORES.md`、`INFRA-VALIDATION.md`、`BLOCKERS.md`、`FINAL-REPORT.md`

## 最終交付（開發與 QA 全數通過後才啟動，不得搶占資源）
- [ ] 產品示範影片（5–8 分鐘，1080p30 草稿→最終），輸出 `artifacts/demo-video/`
  - 依賴：QA 門檻達成、完整 QA 報告與證據。
  - 角色：Technical Documentation / Product Demonstration（Playwright 真實錄影）/ Motion Design（OneTake skill：`~/.claude/skills/onetake`，已存在需先檢查不得覆寫；probe.py、verify_promo.py）/ Narration & Editing（繁中旁白字幕、FFmpeg 整合）/ Independent Video QA。
  - 需向產品負責人提三種視覺概念；未回覆前只能做標示「待確認」的草稿。
  - 交付檔：cyberrange-demo-final.mp4、-draft.mp4、script.md、storyboard.md、architecture.md、feature-coverage.md、video-qa-report.md、evidence-index.md、素材與製作腳本。
