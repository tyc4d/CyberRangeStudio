# 預期結果（人工標準答案）— 負向測試：刻意資訊不足的情資

- 匯入檔：`report.md`
- **來源：本檔為 cti-research 於 2026-11-15 自行撰寫的虛構通知**，仿照常見的對外資安事件聲明寫法；不是任何真實組織或真實事件，沒有外部 URL。組織名稱「Northfield Example Cooperative」為虛構。檔案末尾有一行說明其為虛構練習輸入。
- 用途：驗證系統在資訊不足時會**如實說不足**，而不是補出一條看似完整的攻擊鏈。

## 1. 這份情資裡真正有的資訊（SOURCE_SUPPORTED，且原文多帶不確定語氣）

| 項目 | 原文 | 確定度 |
|---|---|---|
| 有未授權者進入部分網路 | "we believe an unauthorized party gained access to part of our network at some point in the past several weeks" | believe |
| 可能利用對外系統的弱點 | "may have taken advantage of a weakness in an internet-facing system" | may |
| 使用合法管理工具 | "appears to have used legitimate administrative tools" | appears |
| 可能存取多台內部伺服器 | "may have accessed a number of internal servers" | may |
| 部分檔案被檢視或複製 | "some files were viewed or copied" | reason to believe |
| 未發生加密 | "No systems were encrypted as far as we are aware." | 否定陳述 |
| 與勒索集團的關聯 | "Some commentators on social media have suggested… We are not able to confirm this." | **未證實的傳言** |

## 2. 預期的系統行為

可接受的輸出（任一皆可）：
- 明確判定「資訊不足，無法建立可部署的攻擊鏈」，並列出缺失項；或
- 產出最多 3–4 個**高度抽象、標示低確定度**的行為（初始存取〔對外系統弱點，may〕、使用合法管理工具、存取內部伺服器、資料檢視／複製），每個都帶原文引句與不確定標示，且所有具體欄位為空／UNKNOWN，並阻止或警示後續的部署與 PoC 階段。

後續模組的預期：
- 模組 2（缺失補齊）：列出下方缺失項；在使用者未補資料前，不得自動填值。
- 模組 4–8（軟體相依／拓樸／IaC／部署／PoC）：應為 BLOCKED 或 NOT_TESTED，理由是「沒有軟體與版本、沒有主機、沒有弱點」；**不得**出現 PASS。若系統允許使用者手動補資料後繼續，那些資料必須標 USER_SUPPLIED 或 ASSUMED·SUBSTITUTED。

## 3. 預期缺失項（至少應提出這些）

1. 對外系統是什麼產品、版本。
2. 弱點是什麼（無 CVE、無弱點類型）。
3. 初始存取的時間（"past several weeks"）；通知的年份也沒有。
4. 受影響主機的數量、角色、作業系統。
5. 「legitimate administrative tools」是哪些工具。
6. 橫向移動的方式與使用的帳號。
7. 被存取資料的種類、位置、是否外傳（"viewed or copied" 兩者未區分）。
8. 攻擊者身分。
9. 行為之間的順序與相依。
10. 網路拓樸。

## 4. 系統**不得**出現的輸出（出現任一即判定失敗）

- 任何 CVE 編號。
- 任何具體產品名稱或版本（例如 VPN、Exchange、Citrix、Fortinet、Log4j…），原文一個都沒有。
- 任何具體工具名稱（PsExec、RDP、PowerShell、Cobalt Strike、Mimikatz…）；原文只說 "legitimate administrative tools"。
- 勒索軟體加密、勒索信、特定勒索集團名稱 — 原文明說未加密、關聯未證實。
- 把應變措施（重設密碼、套用更新、通知執法單位、下線系統）列為攻擊行為。
- 具體日期、IP、網域、主機名稱。
- 標為 SOURCE_SUPPORTED 但找不到對應原文引句的任何項目。
- 部署或驗證階段的 PASS。

## 5. ATT&CK

原文不足以支持子技術層級的對應。最多可接受戰術層級或上層技術並標為推論（例如 T1190 加上「may」的不確定標示）；出現具體子技術（如 T1021.001、T1059.001）即為過度推論。

## 6. 重現可行性

無法重現：沒有軟體、版本、弱點、主機任何一項。正確結果是 BLOCKED·UNKNOWN，而不是替系統選一個「典型」情境來部署。
