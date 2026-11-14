# 預期結果（人工標準答案）— Equifax 2017：Apache Struts Web RCE → 明文憑證 → 資料庫查詢 → 加密通道外洩

- 匯入檔：`report.md`（GAO-18-559 第 10–16 頁入侵敘述，原文措辭）或 `source.pdf`（官方 PDF 全文 40 頁，SHA-256 `7f352448…45f8`）
- 整理日期：2026-11-15　整理者：cti-research（人工閱讀原文後整理，非系統輸出）
- 技術特性：Linux/Java Web 應用 RCE → 資料庫，與 AA22-320A（Windows AD 橫向移動）不同。

## 來源分級說明

| 分級 | 意義 |
|---|---|
| SOURCE_SUPPORTED | 匯入的 GAO 報告原文直接寫明 |
| EXTERNAL_ENRICHMENT | GAO 沒寫，由 NVD／Apache 公告／美國眾議院監督委員會報告／vulhub 補充；**匯入 GAO 文件時，系統不應把這些當成原文事實** |
| ASSUMED·SUBSTITUTED | 教學環境的假設或替代 |
| BLOCKED·UNKNOWN | 公開來源未提供 |

注意：GAO 的敘述多為「Equifax officials stated…」的轉述，屬於受害者自述經 GAO 整理，不是鑑識原始資料。

## 1. 事件摘要（SOURCE_SUPPORTED）

2017 年 3 月 10 日，不明人士掃描到 Equifax 線上爭議入口網站（online dispute portal）的伺服器跑著有弱點的 Apache Struts，並確認可以執行指令（當時未取走資料）。5 月 13 日起，攻擊者再度進入該入口網站，對其他資料庫下查詢，找到含 PII 與**未加密帳號密碼**的資料儲存區，藉此把存取範圍從入口網站相關的 3 個資料庫擴大到另外 48 個不相關的資料庫，共執行約 9,000 次查詢，並以標準加密 Web 協定小量分批把資料帶出。因檢查加密流量的設備憑證過期，約 76 天後（7 月 29 日）才被發現。

> "The attack lasted for about 76 days before it was discovered." (p.12)

## 2. 資產／主機

| ID | 資產 | 角色 | 分級 | 依據 |
|---|---|---|---|---|
| H1 | 線上爭議入口網站伺服器（Web 應用，Apache Struts） | 初始入侵點；之後下指令與查詢的跳板 | SOURCE_SUPPORTED | "a server housing Equifax’s online dispute portal that was running a version of the software that contained the vulnerability" (p.11) |
| D1 | 入口網站相關的 3 個資料庫 | 入口網站原本就會存取 | SOURCE_SUPPORTED | "the 3 databases associated with the online dispute portal" (p.12) |
| D2 | 含 PII 與未加密帳密的資料儲存區（data repository／database） | 憑證來源 | SOURCE_SUPPORTED | "a data repository containing PII, as well as unencrypted usernames and passwords" (p.11) |
| D3 | 另外 48 個不相關資料庫 | 擴大存取、PII 查詢目標 | SOURCE_SUPPORTED | "an additional 48 unrelated databases" (p.12) |
| N1 | 網路流量檢查設備（憑證過期，未檢查加密流量） | 偵測失效的原因 | SOURCE_SUPPORTED | "a misconfiguration allowed encrypted traffic to pass through the network without being inspected" (p.14) |
| A1 | 攻擊者端（數個 Internet 位址） | 下指令、接收資料 | SOURCE_SUPPORTED（存在）／BLOCKED·UNKNOWN（位址） | "Equifax then blocked several Internet addresses from which the requests were being executed" (p.14) |

外部補充（EXTERNAL_ENRICHMENT，眾議院監督委員會 2018-12 報告，<https://oversight.house.gov/wp-content/uploads/2018/12/Equifax-Report.pdf>，存檔 `reports/overnight/evidence/cti-research/enrichment/`）：
- 該系統稱為 ACIS（Automated Consumer Interview System）；"The ACIS environment was comprised of two web servers and two application servers, with firewalls set up at the perimeter of the web servers."
- 舊式 Sun/Solaris 環境："The Sun servers run the Solaris operating system"。
- 憑證來源是掛載的檔案分享上的設定檔，而不是 GAO 說的「資料庫」："the attackers accessed a mounted file share containing unencrypted application credentials (i.e., username and password) stored in a configuration file database"。**兩份來源對憑證存放處的描述不同**，應並列而非擇一。

## 3. 軟體與版本

| 軟體 | 版本 | 分級 | 依據／備註 |
|---|---|---|---|
| Apache Struts Web Framework | **GAO 未提供版本，也沒寫 CVE 編號** | 名稱 SOURCE_SUPPORTED；版本 BLOCKED·UNKNOWN | "The vulnerability involved the Apache Struts Web Framework and would allow an attacker to execute commands on affected systems." (p.11) |
| 弱點識別 | CVE-2017-5638（Apache S2-045） | EXTERNAL_ENRICHMENT | 眾議院報告："The vulnerability was assigned the identifier CVE-2017-5638."；GAO 只說是 US-CERT「just 2 days earlier」公告的弱點。 |
| CVE-2017-5638 影響範圍 | Struts 2.3.x < 2.3.32、2.5.x < 2.5.10.1 | EXTERNAL_ENRICHMENT | NVD <https://nvd.nist.gov/vuln/detail/CVE-2017-5638>："The Jakarta Multipart parser in Apache Struts 2 2.3.x before 2.3.32 and 2.5.x before 2.5.10.1 has incorrect exception handling and error-message generation during file-upload attempts, which allows remote attackers to execute arbitrary commands via a crafted Content-Type, Content-Disposition, or Content-Length HTTP header"；CVSS 3.1 9.8。Apache S2-045 <https://cwiki.apache.org/confluence/display/WW/S2-045>：受影響 "Struts 2.3.5 - Struts 2.3.31, Struts 2.5 - Struts 2.5.10"，建議升級 2.3.32 或 2.5.10.1。 |
| Equifax 實際安裝的 Struts 版本 | 不明 | BLOCKED·UNKNOWN | 兩份公開報告都沒寫確切版本。 |
| 資料庫產品／版本 | 不明 | BLOCKED·UNKNOWN | GAO 只說 "databases"。 |
| 入口網站伺服器作業系統 | GAO 未提供 | BLOCKED·UNKNOWN（GAO）；Solaris 為 EXTERNAL_ENRICHMENT（眾議院報告） | — |
| 攻擊者使用的利用程式 | "software they obtained from an unknown source" | BLOCKED·UNKNOWN | p.11 |

## 4. 攻擊行為（依原文敘述順序）

| # | 主機 | 行為 | ATT&CK | 結果 | 分級 | 原文引句 |
|---|---|---|---|---|---|---|
| B1 | A1→H1 | 2017-03-10 掃描 Equifax 系統，找有特定弱點的主機 | T1595.002 | 成功 | SOURCE_SUPPORTED | "on March 10, 2017, unidentified individuals scanned the company’s systems to determine if the systems were susceptible to a specific vulnerability" |
| B2 | A1→H1 | 利用 Apache Struts 弱點取得未授權存取，確認可執行指令（未取資料） | T1190 | 成功 | SOURCE_SUPPORTED | "the unidentified individuals subsequently gained unauthorized access to the Equifax portal and confirmed that they could run commands. No data was taken at this time." |
| B3 | A1→H1 | 2017-05-13 起（另一起事件）再度取得入口網站存取，可下系統層級指令 | T1190、T1059 | 成功 | SOURCE_SUPPORTED | "beginning on May 13, 2017, in a separate incident following the initial unauthorized access, attackers gained access to the online dispute portal" |
| B4 | H1→其他系統 | 利用入口網站既有的加密通道對其他系統送查詢與指令，混入正常流量 | T1573／T1071.001 | 成功 | SOURCE_SUPPORTED | "the attackers leveraged existing encrypted communication channels connected to the online dispute portal to send queries and commands to other systems" |
| B5 | H1→D1/D2 | 對其他資料庫下查詢搜尋敏感資料，找到含 PII 與未加密帳密的資料儲存區 | T1213（資料儲存庫）、T1552.001（明文憑證） | 成功 | SOURCE_SUPPORTED | "the attackers issued queries to other databases to search for sensitive data. This search led to a data repository containing PII, as well as unencrypted usernames and passwords" |
| B6 | H1→D3 | 用取得的帳密把存取擴大到另外 48 個不相關資料庫 | T1078 | 成功 | SOURCE_SUPPORTED | "the attackers were able to leverage these credentials to expand their access beyond the 3 databases associated with the online dispute portal, to include an additional 48 unrelated databases." |
| B7 | H1→D3 | 執行約 9,000 次查詢擷取 PII（部分成功） | T1213、T1005 | 部分成功 | SOURCE_SUPPORTED | "Altogether, the attackers ran approximately 9,000 queries, a portion of which successfully returned data containing PII." |
| B8 | H1→A1 | 以標準加密 Web 協定小量分批帶出資料 | T1048／T1041、T1030（分批） | 成功 | SOURCE_SUPPORTED | "the attackers removed the data in small increments, using standard encrypted web protocols to disguise the exchanges as normal network traffic." |

ATT&CK 編號全部是本檔整理者的對應（**EXTERNAL_ENRICHMENT**）；GAO 報告沒有任何 ATT&CK 編號。系統若產出編號，應標為推論而非原文。

GAO **沒有**寫、但眾議院報告有寫的行為（EXTERNAL_ENRICHMENT；只匯入 GAO 時系統不應產出，或須標為非原文）：
- 上傳 web shell（約 30 個）："Approximately 30 unique web shells were used to perform the attack."（T1505.003）
- 查詢資料表中繼資料後再取資料："The attackers queried the metadata from a specific table to discover the type of information contained within the table."
- 壓縮結果、放到可由 Web 存取的目錄、用 Wget 傳出："The attackers compressed these files and placed them into a web accessible directory. Then, the attackers issued commands through the tool Wget"（T1560、T1074.001）
- 9,000 次查詢中 265 次成功；約 35 個 IP。

## 5. 行為間關係

### 5.1 時間順序（temporal）

B1（2017-03-10）→ B2（3 月，日期未明）→〔約兩個月空窗〕→ B3（2017-05-13）→ B4/B5 → B6 → B7 → B8 → 發現（2017-07-29）→ 入口網站下線（2017-07-30）。

- B4 是貫穿 B5–B8 的手法（持續性），不是單一時間點。
- B7 與 B8 原文各自成段，但實際上在 76 天內交錯進行（原文未給細部時間）。

### 5.2 相依關係（dependency）

| 後項 | 需要 | 類型 | 分級 |
|---|---|---|---|
| B2 | B1（掃描結果找到有弱點的伺服器） | 偵察結果 | SOURCE_SUPPORTED（"as a result of this scanning"） |
| B2、B3 | H1 的 Struts 未修補 | 前置條件（弱點存在） | SOURCE_SUPPORTED（"the Apache Struts vulnerability was not properly identified as being present on the online dispute portal when patches…were being installed"） |
| B3 | **不相依於 B2 的存取**：原文明說是 "a separate incident"，只是同一個弱點 | 僅時間先後＋共同前置條件 | SOURCE_SUPPORTED |
| B5 | B3（"after gaining the ability to issue system-level commands on the online dispute portal"） | 立足點 | SOURCE_SUPPORTED |
| B6 | B5（取得未加密帳密）＋資料庫之間沒有分段 | 憑證＋網路可達 | SOURCE_SUPPORTED（"Because individual databases were not isolated or “segmented” from each other"） |
| B7 | B6；且查詢頻率沒有限制 | 存取權 | SOURCE_SUPPORTED（"the lack of restrictions on the frequency of database queries"） |
| B8 | B7（有資料可帶）＋對外加密連線未被檢查 | 資料＋偵測失效 | SOURCE_SUPPORTED（"the attacker was able to run commands and remove stolen data over an encrypted connection without detection"） |

陷阱：B2→B3 **不是**相依（系統若畫成「3 月的存取被 5 月沿用」即為錯誤）。

### 5.3 來源間矛盾（系統若同時取得兩份來源，應並列）

| 項目 | GAO-18-559 | 眾議院報告 |
|---|---|---|
| 檢查設備憑證過期多久 | "about 10 months before the breach occurred" | "The certificate was expired for 19 months."（並註明 GAO 寫 10 個月） |
| 未加密帳密位置 | "a database that contained unencrypted credentials" | "a mounted file share…stored in a configuration file database" |

## 6. 預期缺失項（模組 2 應提出）

1. Struts 的確切版本與 CVE 編號（GAO 兩者皆無）。
2. 入口網站伺服器的作業系統、應用伺服器（Tomcat？WebLogic？）、Java 版本。
3. 資料庫產品與版本；D1／D2／D3 的網路位置。
4. 利用程式的來源與形式（"obtained from an unknown source"）。
5. 取得 RCE 後維持存取的方式（GAO 未提 web shell）。
6. 未加密帳密的確切存放位置與格式。
7. 外洩通道的協定細節、目的地位址、每批大小。
8. 3 月那次存取的確切日期與執行的指令。
9. 網路拓樸（入口網站與資料庫之間的區段）。

## 7. 重現可行性評估

| 行為 | 評估 | 原因與教學替代 |
|---|---|---|
| B1 掃描 | 真實重現 | 只掃實驗網內的目標容器。 |
| B2／B3 Struts RCE | **真實重現（同一 CVE）** | vulhub `struts2/s2-045`（映像 `vulhub/struts2:2.3.30`，Linux 容器）。CVE 與版本來自外部補充，非 GAO 原文；Equifax 實際版本不明 → 版本為 ASSUMED·SUBSTITUTED，作業系統（Solaris→Linux）為 SUBSTITUTED。 |
| B4 沿用既有加密通道 | 部分 | 可重現「經由 Web 應用的 HTTPS 下指令」；「既有通道」的實際形態不明。 |
| B5 找到未加密帳密 | 教學替代 | 在 Web 容器可讀的位置放一份含資料庫帳密的設定檔（位置與格式為 ASSUMED；兩份來源說法不同）。 |
| B6 存取其他資料庫 | 真實重現（技術行為） | 同一網段放 2–3 個 MySQL/PostgreSQL 容器代表「不相關資料庫」（產品為 ASSUMED；48 個縮成少數幾個為 SUBSTITUTED）。 |
| B7 大量查詢 | 真實重現 | 用假造的 PII 測試資料；驗證點：查詢成功回傳資料列。 |
| B8 分批經 HTTPS 外洩 | 真實重現（隔離網內） | 外洩目的地為實驗網內的攻擊者容器；不得連外。 |
| 憑證過期導致未檢查（N1） | 部分／可選 | 可用一台 TLS 檢查代理＋過期憑證示範，屬防禦面教學，非攻擊鏈必要。 |

整體：**這是最適合在 Linux Docker 完整重現的鏈**（Web RCE → 憑證 → DB → 外洩，全程容器內）。

建議的最小實驗拓樸（ASSUMED·SUBSTITUTED）：`attacker` ─ `dmz` 網段 ─ `portal`（vulhub/struts2:2.3.30）─ `data` 網段 ─ `db-dispute`、`db-other-1`、`db-other-2`。

## 8. 外部 PoC／練習映像（EXTERNAL_ENRICHMENT，非事件事實）

- vulhub `struts2/s2-045`：<https://github.com/vulhub/vulhub/tree/master/struts2/s2-045> — `image: vulhub/struts2:2.3.30`，README："Affected Version: Struts 2.3.5 - Struts 2.3.31, Struts 2.5 - Struts 2.5.10"；驗證方式為在 `Content-Type` 標頭放 OGNL 表達式。（存檔：`reports/overnight/evidence/cti-research/vulhub/struts2_s2-045.*`）
- Metasploit：眾議院報告註腳引用 <https://github.com/rapid7/metasploit-framework/issues/8064>（"Metasploit Framework: CVE-2017-5638 – Apache Struts 2 S2-045"）；本次未驗證模組內容。

## 9. 驗收檢查點

系統輸出**應該**：
- 抓到 B2（或 B3）、B5、B6、B7、B8 五個核心行為，附原文引句。
- 區分 3 月與 5 月兩次存取，且不把它們畫成相依。
- 把 Struts 版本、CVE 編號、資料庫產品、作業系統列為缺失（只匯入 GAO 時）。
- 把「資料庫未分段」「查詢頻率無限制」「加密流量未檢查」辨識為前置條件／促成因素，而不是攻擊行為。
- 9,000 次查詢標為「部分成功」。

系統輸出**不應該**：
- 在只匯入 GAO 的情況下，把 CVE-2017-5638、web shell、Wget、Solaris、ACIS 標為 SOURCE_SUPPORTED。
- 把 vulhub 的 Struts 2.3.30 寫成 Equifax 的版本。
- 把事後應變（封鎖 IP、下線入口網站、通知 FBI）列為攻擊行為。
- 編造資料庫產品名稱或 IP。
