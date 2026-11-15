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
尚未開始——待 Round 2 問題修復、審查、整合後凍結新版本。

## UI 專項：講師部署與連線資訊（Round 3c candidate；獨立於整體 QA）

目標：本 UI 專項至少 70/100。版本：`agent/acceptance-lead` 的未發布候選；三位評分者使用真實介面及情境 `scn_fa2301161837`，以 zh-TW/en、1440px 桌面與 390px 手機盲測。所有 API 請求均為 GET；沒有部署、清除、探針或 PVE 寫入。

| 評分者 | 分數 | 結論 | 主要觀察 |
|---|---:|---|---|
| 講師 | 91 | 達 UI 專項門檻 | 能找到「目前無講師入口」及管理員下一步；可辨識主機、服務、埠、規劃連線與預定放置位置 |
| UX | 88 | 達 UI 專項門檻 | 手機無橫向溢位、正文 16px、主要控制項至少 44px；導覽列有更多步驟但滑動提示不明顯 |
| 管理者 | 88 | 達 UI 專項門檻 | 能區分目前位置與規劃；重複主機已註明仍是一台，規劃連線不再像已啟用 |

平均 89/100；最低分 88，三位皆超過 70。獨立靜態複審裁決 `APPROVE`。手機 RWD、字級、i18n、部署狀態語意及講師連線資訊完成 UI 專項驗收。

限制：此分數不表示講師現在能實際連入靶場。PVE 執行環境尚無外部講師入口；畫面如實顯示尚未提供。位置只到 Proxmox provider/node/pool，沒有機房、機櫃資料。整體 QA Round 3 尚未開始，總分 ≥90 與連續兩輪整體驗收門檻仍有效。
