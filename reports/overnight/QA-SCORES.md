# QA 評分紀錄

門檻：總分 ≥90、Instructor ≥90、Administrator ≥90、無未解 Critical/High、連續兩輪通過。

## Round 1（基準：修復前的 main `d99957e`；真實 Chromium、Codex gpt-6.1-sol Ultra、Fast 關閉）
| 測試者 | 分數 | 結論 | 主要 High | 報告 |
|---|---:|---|---|---|
| qa-instructor（講師，CISA AA22-320A） | 43 | 未達標；部署／PoC BLOCKED | 未編輯關係被改標「使用者」；多主機被合併成一個資產；Horizon/AD 無可部署條件 | `qa/round1/qa-instructor-round1.md`（49 截圖＋trace 在該 worktree evidence） |
| qa-admin（管理者） | 54 | 未達標；原情資部署阻塞，最小場景生命週期實測可行 | 主機↔服務對應遺失；固定埠 42000 並行衝突留殘骸；（共 3 High／9 項） | `qa/round1/qa-admin-round1.md` |
| qa-ux（UX/QA） | 53 | 未達標；部署／PoC BLOCKED | 主機／服務關聯錯誤導致零連線（1 High／8 項） | `qa/round1/qa-ux-round1.md`（251 截圖＋trace） |

三位測試者皆回報：系統沒有假 PASS、不支援的元件被如實拒絕部署。

## Round 2
尚未開始——等修復分支通過審查並整合進 main、重啟 QA 站台後進行。
