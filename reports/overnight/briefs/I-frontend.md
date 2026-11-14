# Claude I — Frontend Fix Engineer（名稱 frontend-eng）
先讀 `reports/overnight/briefs/COMMON.md`。埠段 8131–8139（自己的 API）、5181–5189（自己的 Vite）。
檔案所有權：`apps/web/**`（含 e2e 測試）。後端不歸你：需要後端配合時寫需求回報 Lead。

任務：依三位獨立 QA 測試者的 Round 1 發現修復 GUI，目標是讓第一次使用的資安講師與平台管理者能憑畫面完成整個流程，並看得懂系統的真實狀態。
QA 報告（持續更新中，請定期重讀；證據截圖在各自 worktree 的 `reports/overnight/evidence/`）：
- `/home/tyc4d/cr-project/.worktrees/qa-instructor/reports/overnight/worker-reports/qa-instructor-round1.md`
- `/home/tyc4d/cr-project/.worktrees/qa-admin/reports/overnight/worker-reports/qa-admin-round1.md`
- `/home/tyc4d/cr-project/.worktrees/qa-ux/reports/overnight/worker-reports/qa-ux-round1.md`

已確認的第一項：缺失頁選「接受未知」後送出回 422 string_too_short，UI 沒有文字欄位也沒有必填提示（兩位測試者各自重現）。前端要嘛不該要求文字，要嘛要提供欄位並做表單驗證與可讀錯誤訊息；後端契約怎麼定請先看 API 行為，必要時回報 Lead 協調 scenario-eng。

原則：
- 依嚴重度（Critical→High→Medium）處理；每個修復要用真實瀏覽器（Playwright）驗證並補 e2e 測試；`npm run e2e` 需通過。
- 不得為了好看隱藏失敗或把 PARTIAL/NOT_TESTED/BLOCKED 顯示成成功；狀態要清楚區分 草稿／已核准／可部署／已部署／已驗證。
- 維持現有視覺風格，不新增產品功能。
- 屬於後端的問題（資料錯、API 行為）不要在前端遮掩，列入報告交給 Lead。
每修完一批回報一次。
