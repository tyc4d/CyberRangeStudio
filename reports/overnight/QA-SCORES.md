# QA 評分紀錄

門檻：總分 ≥90、Instructor ≥90、Administrator ≥90、無未解 Critical/High、連續兩輪通過。

## Round 1（基準：修復前的 main `d99957e`；真實 Chromium、Codex gpt-6.1-sol Ultra、Fast 關閉）
| 測試者 | 分數 | 結論 | 主要 High | 報告 |
|---|---:|---|---|---|
| qa-instructor（講師，CISA AA22-320A） | 43 | 未達標；部署／PoC BLOCKED | 未編輯關係被改標「使用者」；多主機被合併成一個資產；Horizon/AD 無可部署條件 | `qa/round1/qa-instructor-round1.md`（49 截圖＋trace 在該 worktree evidence） |
| qa-admin（管理者） | 54 | 未達標；原情資部署阻塞，最小場景生命週期實測可行 | 主機↔服務對應遺失；固定埠 42000 並行衝突留殘骸；（共 3 High／9 項） | `qa/round1/qa-admin-round1.md` |
| qa-ux（UX/QA） | 53 | 未達標；部署／PoC BLOCKED | 主機／服務關聯錯誤導致零連線（1 High／8 項） | `qa/round1/qa-ux-round1.md`（251 截圖＋trace） |

三位測試者皆回報：系統沒有假 PASS、不支援的元件被如實拒絕部署。

## Round 2（凍結版 tag `qa-round2` = main 43ba325；全新測試者、真實 Chromium、Codex gpt-6.1-sol Ultra、Fast 關閉）
| 測試者 | 分數 | 結論 | High | 報告 |
|---|---:|---|---|---|
| qa-instructor-r2（講師：Equifax＋CISA AA22-320A） | 45 | 未達標；Equifax 卡 IaC，PoC／全鏈／最終報告未測（該項 0/15） | 4 High／2 Medium／1 Low | `qa/round2/qa-instructor-r2.md`（74 截圖＋trace） |
| qa-admin-r2（管理者：Equifax 教學替代＋Demo 同時部署） | 54 | 未達標；雙場景真實部署、逐一清除重建通過；完整攻擊鏈仍 PARTIAL | 4 High／5 Medium／1 Low | `qa/round2/qa-admin-r2.md` |
| qa-ux-r2（UX：Clop MOVEit＋負向情資） | 62 | 未達標；原始 MOVEit 與不足情資正確阻擋；nginx 教學替代真實部署／驗證／清除 | 3 High／6 Medium／1 Low | `qa/round2/qa-ux-r2.md`（251 截圖＋3 trace） |

與 Round 1 相比：講師 43→45、管理者 54→54、UX 53→62。Round 1 的 High（關係被洗成使用者、主機合併、撞埠）已不再出現；Round 2 換了更嚴格的情資（可部署的 Equifax 鏈）後暴露新的 High，見 `qa/round2/TRIAGE.md`。**門檻未達，持續修復。**

## Round 3
2026-11-16 已執行範圍受限的 Round 3。測試版本的產品程式凍結點為 `be4947e`；QA 服務實際來自候選 worktree `agent/acceptance-lead@a033c53`（後續提交只改文件）。

| 測試者 | 可觀測分項 | 結論 | 報告 |
|---|---:|---|---|
| Instructor（Equifax PDF） | 14/100（非有效總分） | BLOCKED：分析服務金鑰過期，無法建立情境；未完成到 IaC 的主流程。另發現 PDF 匯入成功訊息切英文後仍為中文（Medium）。 | [qa-instructor-r3-round3.md](/home/tyc4d/cr-project/.worktrees/qa-instructor-r3/reports/overnight/worker-reports/qa-instructor-r3-round3.md) |
| Administrator（Demo benign） | 16/100（非有效總分） | BLOCKED/PARTIAL：新分析失敗；既有情境只作唯讀 UI 呈現檢查。另發現過期認證錯誤只建議重試（Medium）及英文狀態殘留中文（Low）。 | [qa-admin-r3-round3.md](/home/tyc4d/cr-project/.worktrees/qa-admin-r3/reports/overnight/worker-reports/qa-admin-r3-round3.md) |
| UX（CL0P＋不足情資） | 無有效總分；局部 GUI 7/10、證據 5/5 | BLOCKED：分析服務金鑰過期；完成 100 組雙語／五尺寸空狀態檢查。發現草稿離頁遺失與認證錯誤引導（Medium），手機深連結的目前步驟不在導覽視窗內（Low）。 | [qa-ux-r3-round3.md](/home/tyc4d/cr-project/.worktrees/qa-ux-r3/reports/overnight/worker-reports/qa-ux-r3-round3.md) |

本輪**沒有有效整體分數，不算一輪通過**。分析服務回覆上游 401「API key has expired」，候選 API 使用的本機 `.env` 只有目前這把已失效的 `OPENAI_API_KEY`；未讀出或記錄金鑰內容，也未用錯誤金鑰重試。各 QA 均未部署、未跑 probe，依 R3 範圍標記 NOT TESTED。報告與完整 trace／截圖保留在各 QA worktree 的 `reports/overnight/worker-reports/` 及 `evidence/`。

產品修正後，需在本機更新有效分析服務憑證、重啟候選 API，重新跑成功分析的完整情境流程，才可開始有效評分。整體驗收仍要求連續兩輪總分／Instructor／Administrator ≥90 且無未解 High/Critical。

### Round 3 UI finding follow-up（不構成新一輪 QA）

Round 3 的 ImportPage、手機導覽與部署核准狀態 findings 已在候選 `agent/acceptance-lead` 修正，並整合為 `13589ab`、`d4ab84f`。這些是針對 findings 的修正與聚焦檢查，沒有重跑成功分析或完整 QA，因此 Round 3 仍為 BLOCKED，沒有新增有效分數。

| Finding | 修正與驗證 | 限制 |
|---|---|---|
| UX-01 認證錯誤只建議重試 | 只辨識已觀察到的 502／上游 401／AuthenticationError／API key expired 組合；用中英文說明請管理員更新憑證，再重新分析。折疊診斷不顯示任意錯誤細節或金鑰。 | 未更新憑證，也未重送分析。 |
| UX-02 導覽返回遺失草稿 | ImportPage 草稿在 SPA 頁面切換後保留；「新增情境」會清空舊草稿；成功分析後清除。真實瀏覽器確認返回保留草稿、新增情境清空。 | 草稿存在頁面工作階段記憶體；重新整理或關閉分頁不保證保留。 |
| UX-03 手機深連結目前步驟在導覽視窗外 | 路由、語言或視窗尺寸變更後，水平步驟導覽會把目前步驟捲入可見範圍；390px 手機直接連結及站內導覽檢查通過。 | 未重跑所有五種尺寸與十頁矩陣。 |
| Instructor PDF 成功提示未翻譯 | PDF 擷取提示保存翻譯鍵與參數；真實 extract endpoint + Chromium 確認切換英文後同一提示更新為英文。 | 只執行 PDF extract，沒有分析。 |
| Admin 英文部署狀態殘留中文 | Deploy 核准狀態改按固定後端 code 翻譯；未知訊息保留原文。stale 409 需 status 或 preflight 後續成功確認可部署，且沒有任一目前拒絕，才解除按鈕與隱藏錯誤。獨立只讀複審 APPROVE。 | 未呼叫部署 API；核准恢復只做純狀態檢查。 |

修正報告：`reports/overnight/worker-reports/ui-import-draft-r3.md`、`reports/overnight/worker-reports/ui-nav-status-r3.md`。整合後候選的 `typecheck`、`i18n:check` 與 production build 通過；i18n 檢查為 1411 keys、0 hard-coded strings，另列 3 個既有無 literal reference 的 keys。Vite build 有一個大於 500 kB 的 chunk 警告。ImportPage 有真實瀏覽器局部檢查；Deploy gate 沒有呼叫 API，並經純狀態檢查及獨立只讀複審。最新候選後端／單元回歸為 538 passed、2 warnings、160 subtests；未包含 local Compose integration 或 full E2E。這些結果只完成 UI findings 的聚焦驗證與程式回歸；完整 QA 仍須等分析服務憑證恢復。

## UI 專項：講師部署與連線資訊（Round 3c candidate；獨立於整體 QA）

目標：本 UI 專項至少 70/100。版本：`agent/acceptance-lead` 的未發布候選；三位評分者使用真實介面及情境 `scn_fa2301161837`，以 zh-TW/en、1440px 桌面與 390px 手機盲測。所有 API 請求均為 GET；沒有部署、清除、探針或 PVE 寫入。

| 評分者 | 分數 | 結論 | 主要觀察 |
|---|---:|---|---|
| 講師 | 91 | 達 UI 專項門檻 | 能找到「目前無講師入口」及管理員下一步；可辨識主機、服務、埠、規劃連線與預定放置位置 |
| UX | 88 | 達 UI 專項門檻 | 手機無橫向溢位、正文 16px、主要控制項至少 44px；導覽列有更多步驟但滑動提示不明顯 |
| 管理者 | 88 | 達 UI 專項門檻 | 能區分目前位置與規劃；重複主機已註明仍是一台，規劃連線不再像已啟用 |

平均 89/100；最低分 88，三位皆超過 70。獨立靜態複審裁決 `APPROVE`。手機 RWD、字級、i18n、部署狀態語意及講師連線資訊完成 UI 專項驗收。

限制：此分數不表示講師現在能實際連入靶場。PVE 執行環境尚無外部講師入口；畫面如實顯示尚未提供。位置只到 Proxmox provider/node/pool，沒有機房、機櫃資料。整體 QA Round 3 尚未通過：本輪因分析服務金鑰過期而阻塞，沒有有效總分。總分 ≥90 與連續兩輪整體驗收門檻仍有效。
