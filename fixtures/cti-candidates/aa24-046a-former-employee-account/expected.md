# 預期結果（人工標準答案）— CISA AA24-046A：離職員工帳號 → VPN → 憑證取得 → LDAP 列舉 → SMB 驗證

- 匯入檔：`report.md`（原文措辭）或 `source.pdf`（官方 PDF，SHA-256 `55534abb…1649`）
- 整理日期：2026-11-15　整理者：cti-research（人工閱讀原文後整理，非系統輸出）
- 技術特性：**完全沒有漏洞利用、沒有 CVE、沒有惡意程式**；全程是有效帳號濫用與目錄列舉。用來測系統遇到「無 CVE 的憑證濫用鏈」時不會硬找漏洞。

分級定義同其他候選（SOURCE_SUPPORTED／EXTERNAL_ENRICHMENT／ASSUMED·SUBSTITUTED／BLOCKED·UNKNOWN）。頁碼為官方 PDF 頁碼。

## 1. 事件摘要（SOURCE_SUPPORTED）

某州政府機關得知含主機與使用者資訊的文件被貼到暗網交易站。調查發現不明攻擊者使用一名離職員工（仍有管理權限、未停用）的帳號 USER1，經由機關的 VPN 進入內部網路，從 USER1 管理的虛擬化 SharePoint 伺服器取得本機儲存的第二組帳密 USER2（全域網域管理員），對網域控制站執行 LDAP 查詢（疑似 AdFind），並以兩個帳號對多個端點做 CIFS/SMB 驗證。沒有跡象顯示攻擊者橫向移動到 Azure 環境。

## 2. 資產／主機

| ID | 資產 | 角色 | 分級 | 依據 |
|---|---|---|---|---|
| H1 | VPN 存取點（內部 VPN） | 進入點 | SOURCE_SUPPORTED | "successfully authenticate to an internal virtual private network (VPN) access point" (p.1) |
| A1 | 攻擊者的不明 VM（取得內部 VPN 位址範圍內的 IP） | 所有後續動作的來源 | SOURCE_SUPPORTED | "the threat actor first connected from an unknown virtual machine (VM) to the victim’s on-premises environment via internet protocol (IP) addresses within their internal VPN range." (p.2) |
| H2 | 虛擬化 SharePoint 伺服器（USER1 管理） | USER2 帳密的存放處 | SOURCE_SUPPORTED | "the administrator credentials for USER2 were stored locally on this server" (p.3) |
| H3 | 離職員工的工作站（以 Veeam P2V 虛擬化） | USER1 可存取；**原文沒說攻擊者對它做了什麼** | SOURCE_SUPPORTED（存在） | "USER1 had access to two virtualized servers including SharePoint and the workstation of the former employee." |
| H4 | 網域控制站／Active Directory（網域 `[REDACTED].local`） | LDAP 查詢對象 | SOURCE_SUPPORTED | "execute various lightweight directory access protocol (LDAP) queries against a domain controller" (p.1) |
| H5 | 「various endpoints」：USER1 驗證 4 個服務、USER2 驗證 12 個服務 | CIFS 驗證對象 | SOURCE_SUPPORTED（數量）／BLOCKED·UNKNOWN（身分） | p.4 |
| C1 | Azure 環境／Azure AD | USER2 有權限，但**未被入侵** | SOURCE_SUPPORTED | "the threat actor did not move laterally from the compromised on-premises network to the Azure environment" (p.2) |

## 3. 軟體與版本

| 軟體 | 版本 | 分級 | 備註 |
|---|---|---|---|
| VPN 產品 | 未提供 | BLOCKED·UNKNOWN | — |
| Microsoft SharePoint（地端） | 未提供 | 名稱 SOURCE_SUPPORTED；版本 BLOCKED·UNKNOWN | — |
| Active Directory／DC 作業系統 | 未提供 | BLOCKED·UNKNOWN | — |
| Veeam（P2V 功能） | 未提供 | 名稱 SOURCE_SUPPORTED；版本 BLOCKED·UNKNOWN | 只是工作站虛擬化的背景，不是攻擊工具 |
| AdFind.exe | 未提供 | SOURCE_SUPPORTED，但原文是「likely」 | "likely using the open source tool AdFind.exe, based on the format of the output" |
| CVE | **無** | SOURCE_SUPPORTED（原文完全沒有 CVE） | 系統不應產生任何 CVE |

## 4. 攻擊行為（依原文敘述順序）

「確定度」欄反映原文用語（observed／assessed／likely）。

| # | 主機 | 行為 | ATT&CK（公告標註） | 確定度 | 分級 | 原文引句 |
|---|---|---|---|---|---|---|
| B0 | 事件前、環境外 | 從另一起資料外洩取得 USER1 帳密 | T1589.001 | likely | SOURCE_SUPPORTED | "The threat actor likely obtained the USER1 account credentials in a separate data breach due to the credentials appearing in publicly available channels containing leaked account information [T1589.001]." |
| B1 | A1→H1 | 用 USER1（離職員工、具管理權限、未停用、無 MFA）通過 VPN 驗證進入地端環境 | T1133、T1078.002 | assessed | SOURCE_SUPPORTED | "CISA and MS-ISAC assessed that the threat actor connected to the VM through the victim’s VPN [T1133]"／"The threat actor gained initial access through the compromised account of a former employee with administrative privileges (USER1) [T1078.002]" |
| B2 | A1→H2 | 從 USER1 管理的 SharePoint 伺服器取得本機儲存的 USER2 管理員帳密 | T1213.002、T1552.001 | likely | SOURCE_SUPPORTED | "The threat actor likely obtained the USER2 account credentials from the virtualized SharePoint server managed by USER1 [T1213.002]. The victim confirmed that the administrator credentials for USER2 were stored locally on this server [T1552.001]." |
| B3 | A1→H4 | 對 AD 執行 LDAP 查詢，蒐集使用者、主機、信任關係、網域管理員與服務主體（08:39:43–08:40:56 UTC） | T1087.002、T1018、T1482 | observed（查詢）；likely（工具 AdFind） | SOURCE_SUPPORTED | "the threat actor conducted LDAP queries of the AD"／"Table 1 lists all queries that were conducted between 08:39:43-08:40:56 Coordinated Universal Time (UTC)." |
| B4 | A1→H5 | 以 USER1 對多個端點的 CIFS 驗證（4 個服務） | T1078.002、T1021.002、T1083、T1046 | observed | SOURCE_SUPPORTED | "the threat actor authenticated to the Common Internet File Service (CIFS) on various endpoints [T1078.002],[T1021.002]"／"USER1 authenticated to four services, presumably for the purpose of network and service discovery [T1046]." |
| B5 | A1→H5 | 以 USER2（全域網域管理員）對 12 個服務驗證 | T1078.002、T1021.002（T1021.007、T1078.004 為公告對該帳號權限的標註） | observed | SOURCE_SUPPORTED | "USER2 authenticated to twelve services. Note: This account had administrative privileges to both the on-premises network and Azure tenant." |
| B6 | 環境外 | 將 LDAP 輸出檔 ad_users.txt、ad_computers.txt、trustdmp.txt 貼到暗網交易站販售 | 公告未標 | believed | SOURCE_SUPPORTED | "It is also believed the LDAP queries generated the text files the threat actor posted for sale on the dark web brokerage site: ad_users.txt, ad_computers.txt, and trustdmp.txt." |

**明確沒有發生**（系統不得列為行為）：橫向移動到 Azure、入侵敏感系統 — "there were no indications the threat actor further compromised the organization by moving laterally from the on-premises environment to the Azure environment."

## 5. 行為間關係

### 5.1 時間順序（temporal）

B0（事件前）→ B1 → {B2、B3、B4、B5}→ B6。

- 唯一的時間戳是 B3 的 08:39:43–08:40:56 UTC（**沒有日期**）。
- B2、B3、B4、B5 之間的先後原文沒有交代；唯一可確定的是 B5 在 B2 之後（因為相依）。**預期系統應把這幾項的時間順序標為不明，而不是照段落順序排死。**

### 5.2 相依關係（dependency）

| 後項 | 需要 | 類型 | 分級 |
|---|---|---|---|
| B1 | B0（有 USER1 帳密）＋帳號未停用＋無 MFA | 憑證＋前置條件 | SOURCE_SUPPORTED（"this account was not disabled immediately following the employee’s departure"、"Neither of the administrative accounts had multifactor authentication (MFA) enabled."） |
| B2、B3、B4 | B1（經 VPN 取得內部連線） | 網路可達 | SOURCE_SUPPORTED（"Through connection from the VM"） |
| B2 | USER1 對 SharePoint 伺服器有存取權；USER2 帳密明文存於該機 | 權限＋前置條件 | SOURCE_SUPPORTED |
| B5 | B2（取得 USER2） | 憑證 | SOURCE_SUPPORTED（likely） |
| B3 | 有效網域帳號（USER1 或 USER2；**用哪一個原文未寫**） | 憑證 | BLOCKED·UNKNOWN（哪個帳號） |
| B6 | B3（查詢輸出） | 資料 | SOURCE_SUPPORTED（believed） |

## 6. 預期缺失項（模組 2 應提出）

1. VPN 產品、版本、驗證方式。
2. 攻擊者 VM 如何取得內部 VPN 範圍 IP（原文只說 "unknown virtual machine"）。
3. USER2 帳密在 SharePoint 伺服器上的存放形式（檔案？設定？位置？）。
4. LDAP 查詢用的是哪個帳號；AdFind 只是推測。
5. CIFS 驗證的目標主機與是否真的讀取了檔案（原文只說 "likely used for file, folder, and directory discovery"）。
6. 外洩途徑：三個文字檔如何離開網路 — 完全未寫。
7. 所有軟體版本、網域名稱（已遮蔽）、IP、日期。
8. 離職員工工作站（H3）是否被使用。

## 7. 重現可行性評估

| 行為 | 評估 | 原因與教學替代 |
|---|---|---|
| B0 外洩帳密取得 | 無法重現／不重現 | 環境外行為，且不得使用真實外洩憑證。教學上直接把實驗帳密發給攻擊端（ASSUMED）。 |
| B1 VPN + 有效帳號 | 教學替代 | VPN 產品不明。可用 WireGuard/OpenVPN 容器，或簡化為「攻擊者容器加入內網」；帳號驗證用 Samba AD 的網域帳號。 |
| B2 從檔案伺服器取得明文帳密 | 教學替代 | SharePoint 為 Windows 商業軟體。替代：USER1 可讀的 SMB 分享／Web 目錄上放含 USER2 帳密的檔案（T1552.001 可真實重現；T1213.002 SharePoint 為 SUBSTITUTED）。 |
| B3 LDAP 列舉 | **真實重現（技術行為）** | Samba AD DC 容器＋`ldapsearch`，可直接使用公告 Table 1 的四條 filter（base DN 改成實驗網域）。AdFind.exe 為 Windows 工具 → 以 ldapsearch 替代並標示。 |
| B4、B5 SMB/CIFS 驗證 | 真實重現 | `smbclient`／`netexec` 對實驗網內多台 Samba 主機驗證；驗證點：兩個帳號各自的成功登入紀錄。 |
| B6 暗網販售 | 無法重現／不重現 | 環境外。可驗證到「產生 ad_users.txt 等三個輸出檔」為止。 |
| Azure 相關（C1） | 無法重現 | 需要雲端租戶；且原文說未被入侵，不需重現。 |

整體：**部分重現**。核心（有效帳號 → 明文憑證 → LDAP 列舉 → SMB 驗證）可用 Linux 容器（Samba AD DC）重現技術行為；VPN、SharePoint、Azure 為替代或略過。驗證重點是「以 USER2 身分成功、且停用 USER1 後失敗」這類帳號面檢查，而不是漏洞利用成功與否。

## 8. 外部資源（EXTERNAL_ENRICHMENT，非事件事實）

- Samba AD DC 可作為 Linux 上的 AD 替代（官方文件：<https://wiki.samba.org/index.php/Setting_up_Samba_as_an_Active_Directory_Domain_Controller>）。本次未實際建置驗證。
- AdFind 為 joeware 的免費工具（Windows）；公告僅依輸出格式推測。
- 本事件沒有 CVE，也沒有對應的漏洞練習映像。

## 9. 驗收檢查點

系統輸出**應該**：
- 抓到 B1、B2、B3、B4/B5，並保留 USER1／USER2 兩個帳號的區別。
- 不產生任何 CVE；初始存取技術為 T1078.002／T1133，而非 T1190。
- 對 likely／assessed／believed 的項目保留不確定性（至少不寫成已證實）。
- 把「帳號未停用」「無 MFA」「帳密存於本機」辨識為前置條件。
- 缺失項包含 VPN 產品、版本、時間、外洩途徑。

系統輸出**不應該**：
- 把 Azure 橫向移動列為已發生。
- 把 Untitled Goose Tool（應變工具）或 Veeam 列為攻擊工具。
- 把緩解建議（MFA、停用帳號）或應變動作（停用 USER1、改 USER2 密碼）列為攻擊行為。
- 編造網域名稱、日期或主機名稱。
