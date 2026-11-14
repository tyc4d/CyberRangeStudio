# 預期結果（人工標準答案）— CISA AA23-158A：CL0P 利用 MOVEit Transfer SQL injection → LEMURLOOT web shell → 資料庫竊取

- 匯入檔：`report.md`（原文措辭）或 `source.pdf`（官方 PDF，SHA-256 `f9b23261…518e`，2026-11-15 擷取的版本）
- 整理日期：2026-11-15　整理者：cti-research（人工閱讀原文後整理，非系統輸出）
- 技術特性：檔案傳輸（MFT）產品零時差 → web shell → 資料庫。這是**活動（campaign）層級**的公告，不是單一受害者的事件應變報告，而且混入大量 TA505 的歷史背景。用來測系統能否把「本次 MOVEit 行為」和「歷史背景／工具能力描述」分開。

分級定義同其他候選。頁碼為官方 PDF 頁碼。

## 1. 事件摘要（SOURCE_SUPPORTED）

> "beginning on May 27, 2023, CL0P Ransomware Gang, also known as TA505, began exploiting a previously unknown SQL injection vulnerability (CVE-2023-34362) in Progress Software's managed file transfer (MFT) solution known as MOVEit Transfer. Internet-facing MOVEit Transfer web applications were infected with a web shell named LEMURLOOT, which was then used to steal data from underlying MOVEit Transfer databases." (p.1)

注意原文開頭是 "According to open source information" — 公告本身是轉述。

## 2. 資產／主機

| ID | 資產 | 角色 | 分級 | 依據 |
|---|---|---|---|---|
| H1 | 對外的 MOVEit Transfer Web 應用（受害者泛稱，非特定主機） | 初始入侵點、web shell 所在 | SOURCE_SUPPORTED | "Internet-facing MOVEit Transfer web applications" |
| D1 | MOVEit Transfer 底層資料庫（MySQL／Microsoft SQL Server／Azure SQL 其一） | 資料竊取對象 | SOURCE_SUPPORTED（存在與支援的引擎）／BLOCKED·UNKNOWN（特定受害者用哪一種） | "has a web application that supports MySQL, Microsoft SQL Server, and Azure SQL database engines" (p.4) |
| A1 | 攻擊者端 | 送 HTTP 請求給 web shell | SOURCE_SUPPORTED（IOC 在公告 Table 2，未納入 report.md） | — |

沒有特定受害者的主機名稱、作業系統、網路位置 — 全部 BLOCKED·UNKNOWN。（平台：公告 YARA 規則寫 `platform = "windows"`，另有 `.aspx`、C# 可佐證是 Windows/ASP.NET；IIS 與 Windows 版本為 BLOCKED·UNKNOWN。）

## 3. 軟體與版本

| 軟體 | 版本 | 分級 | 依據／備註 |
|---|---|---|---|
| Progress MOVEit Transfer | 受影響：2023.0.0、2022.1.x、2022.0.x、2021.1.x、2021.0.x、2020.1.x、2020.0.x | SOURCE_SUPPORTED（**受影響版本線**，不是某個受害者的安裝版本） | "This MOVEit Transfer critical vulnerability exploit impacts the following versions of the software [2]" (p.4) |
| 特定受害者安裝的版本 | 未提供 | BLOCKED·UNKNOWN | — |
| CVE-2023-34362 | SQL injection | SOURCE_SUPPORTED | p.1、p.4 |
| CVE-2023-34362 修補版 | 2021.0.6 (13.0.6)、2021.1.4 (13.1.4)、2022.0.4 (14.0.4)、2022.1.5 (14.1.5)、2023.0.1 (15.0.1) | EXTERNAL_ENRICHMENT | NVD <https://nvd.nist.gov/vuln/detail/CVE-2023-34362>："In Progress MOVEit Transfer before 2021.0.6 (13.0.6), 2021.1.4 (13.1.4), 2022.0.4 (14.0.4), 2022.1.5 (14.1.5), and 2023.0.1 (15.0.1), a SQL injection vulnerability has been found in the MOVEit Transfer web application that could allow an unauthenticated attacker to gain access to MOVEit Transfer's database."；CVSS 3.1 9.8（`reports/overnight/evidence/cti-research/nvd/CVE-2023-34362.json`） |
| LEMURLOOT web shell | C#；初見檔名 human2.aspx | SOURCE_SUPPORTED | "LEMURLOOT is a web shell written in C#"／"initially observed with the name human2.aspx" |
| 資料庫引擎 | MySQL／MSSQL／Azure SQL（支援清單） | SOURCE_SUPPORTED | 同上 |

## 4. 攻擊行為（本次 MOVEit 活動）

| # | 主機 | 行為 | ATT&CK | 性質 | 分級 | 原文引句 |
|---|---|---|---|---|---|---|
| B1 | A1→H1 | 利用 SQL injection 零時差弱點 CVE-2023-34362 | T1190（公告標註） | 已發生 | SOURCE_SUPPORTED | "In May 2023, the CL0P ransomware group exploited a SQL injection zero-day vulnerability CVE-2023-34362 to install a web shell named LEMURLOOT on MOVEit Transfer web applications [T1190]" |
| B2 | H1 | 安裝 LEMURLOOT web shell，檔名 human2.aspx，偽裝成合法的 human.aspx | T1505.003（公告偵測段的 YARA 規則中繼資料 `mitre = "T1505.003"`、`platform = "windows"`；report.md 節錄範圍內未出現）；T1036.005 為 EXTERNAL_ENRICHMENT 對應 | 已發生 | SOURCE_SUPPORTED | "The web shell was initially observed with the name human2.aspx in an effort to masquerade as the legitimate human.aspx file present as part of MOVEit Transfer software." |
| B3 | A1→H1 | 以 HTTP 標頭 `X-siLock-Comment` 帶密碼向 web shell 驗證 | — | 工具行為描述 | SOURCE_SUPPORTED | "awaiting HTTP requests containing a header field named X-siLock-Comment, which must have a value assigned equal to the password established upon the installation of the web shell" |
| B4 | H1→D1 | 取得 Azure 系統設定、列舉底層 SQL 資料庫 | — | **能力**（"commands…that can"） | SOURCE_SUPPORTED | "Retrieve Microsoft Azure system settings and enumerate the underlying SQL database." |
| B5 | H1 | 依操作者送來的字串取回同名檔案 | — | 能力 | SOURCE_SUPPORTED | "Store a string sent by the operator and then retrieve a file with a name matching the string from the MOVEit Transfer system." |
| B6 | H1→D1 | 建立管理員權限帳號（隨機使用者名稱，LoginName／RealName = "Health Check Service"） | T1136（對應為 EXTERNAL_ENRICHMENT） | 能力 | SOURCE_SUPPORTED | "Create a new administrator privileged account with a randomly generated username and LoginName and RealName values set to “Health Check Service.”" |
| B7 | H1→D1 | 刪除 LoginName／RealName 為 'Health Check Service' 的帳號 | T1070（對應為 EXTERNAL_ENRICHMENT） | 能力 | SOURCE_SUPPORTED | "Delete an account with LoginName and RealName values set to ‘Health Check Service.’" |
| B8 | H1→A1 | 從底層資料庫竊取資料；回應以 gzip 壓縮 | — | 已發生（摘要層級，無細節） | SOURCE_SUPPORTED | "which was then used to steal data from underlying MOVEit Transfer databases"／"the web shell returns data in a gzip compressed format" |

原文的內部不一致（系統應保留而非擇一）：
- Summary 說 "beginning on May 27, 2023"；技術段說 "In May 2023"。
- 一處說 web shell 密碼是 "hard-coded password"（工具清單），另一處說 "Upon installation, the web shell creates a random 36 character password"（弱點段）。

## 5. 不屬於本次 MOVEit 攻擊鏈的內容（**陷阱**；系統不應放進本鏈）

| 內容 | 原文定位 | 處理 |
|---|---|---|
| 2019 釣魚活動（Get2、SDBot、FlawedGrace）、CL0P 勒索加密 | 歷史背景 | 不是行為 |
| Accellion FTA／DEWMODE（2020–2021） | 歷史活動 | 不是行為 |
| GoAnywhere MFT CVE-2023-0669（2023-01）與勒索信 | 另一起活動；勒索信寫的是 "GoAnywhere MFT resource" | 不是行為 |
| FlawedAmmyy、SDBot、Truebot、Cobalt Strike 的能力與 ATT&CK 編號（T1071、T1105、T1059.001、T1546.011、T1113、T1055、T1574.002、T1129、T1070、T1018） | "CL0P’s toolkit contains several malware types" — 工具箱描述 | 不是本次行為；公告沒說 MOVEit 活動用了這些 |
| 橫向移動 | 公告對 GoAnywhere 說 "Lateral movement into the victim networks from the GoAnywhere MFT was not identified"；對 MOVEit **沒有**描述任何橫向移動 | 不得產生橫向移動行為 |

## 6. 行為間關係

### 6.1 時間順序（temporal）

B1 → B2 → B3 → {B4、B5、B6、B7}（能力，順序不明）→ B8。日期僅有「2023-05-27 起」。

### 6.2 相依關係（dependency）

| 後項 | 需要 | 類型 | 分級 |
|---|---|---|---|
| B1 | H1 對外可達＋版本未修補 | 前置條件 | SOURCE_SUPPORTED |
| B2 | B1（"exploited…to install a web shell"） | 寫檔能力 | SOURCE_SUPPORTED；**SQL injection 如何變成寫入 .aspx 檔：BLOCKED·UNKNOWN（公告未說明）** |
| B3 | B2（密碼於安裝時產生） | 憑證 | SOURCE_SUPPORTED |
| B4–B7 | B3（"After authenticating with the web shell"） | 驗證 | SOURCE_SUPPORTED |
| B8 | B3（＋B4/B5 的能力） | 存取 | SOURCE_SUPPORTED |
| B7 | B6（刪的是 B6 建的帳號）— 原文未明說，屬合理推論 | 推論 | ASSUMED |

## 7. 預期缺失項（模組 2 應提出）

1. 特定目標的 MOVEit Transfer 安裝版本（公告只有受影響版本線）。
2. 作業系統、Web 伺服器、資料庫引擎與版本。
3. SQL injection 的注入點／請求路徑，以及從 SQLi 到落地 web shell 的中間步驟。
4. 被竊資料的種類與量、外洩目的地。
5. 網路拓樸（H1 與 D1 是否同機）。
6. 時間戳（僅有起始日期）。
7. 這不是單一事件：受害者、主機皆為泛稱。

## 8. 重現可行性評估

| 行為 | 評估 | 原因與教學替代 |
|---|---|---|
| B1 MOVEit SQLi（CVE-2023-34362） | **無法真實重現（在本專案條件下）→ 教學替代** | MOVEit Transfer 是需授權的 Windows 商業軟體，沒有可合法散佈的易受影響映像（vulhub 無此項）。替代：自製含 SQL injection 的檔案傳輸 Web 應用（Linux 容器＋MySQL），保留「SQLi → 寫入 web shell → 經 shell 查資料庫」的技術行為。產品、CVE、平台皆為 ASSUMED·SUBSTITUTED，**不得宣稱重現了 CVE-2023-34362**。 |
| B2 落地 web shell | 教學替代 | 用無害的自製 shell（只支援列出／下載實驗檔案），檔名可仿 human2 命名慣例以教偽裝。不使用真實 LEMURLOOT 樣本。 |
| B3 標頭密碼驗證 | 真實重現（機制） | 自製 shell 實作同樣的「特定標頭＝密碼」驗證，可教偵測（比對標頭）。 |
| B4–B7 | 部分 | 帳號建立／刪除、資料庫列舉可在替代應用上重現；Azure 設定無法重現。 |
| B8 資料竊取（gzip） | 真實重現（機制） | 隔離網內由攻擊者容器取回 gzip 回應。 |

整體：**教學替代為主**。這條鏈的價值在分析面（分辨活動 vs. 背景、能力 vs. 已發生），部署面只能做替代。E2E 測試優先序低於 Equifax 與 AA22-320A。

## 9. 外部資源（EXTERNAL_ENRICHMENT，非事件事實）

- 公告的參考資料 [1] "Zero-Day Vulnerability in MOVEit Transfer Exploited for Data Theft | Mandiant"、[2] "MOVEit Transfer Critical Vulnerability (May 2023) - Progress Community" — 本次只記錄標題，未擷取內容驗證。
- 公開技術分析與 PoC（例如 Horizon3.ai 的 CVE-2023-34362 分析與 PoC、Rapid7 分析）存在，但需要真實 MOVEit 安裝才有意義；本次**未**取得、未驗證，不列為可用資源。
- vulhub：無 MOVEit 項目（`goanywhere/CVE-2023-0669` 亦不存在，2026-11-15 檢查回 404）。

## 10. 驗收檢查點

系統輸出**應該**：
- 核心鏈只有 B1 → B2 →（B3）→ B8，CVE-2023-34362 標為原文支持。
- 版本列為「受影響版本線」，並把「目標實際版本」列為缺失。
- B4–B7 標為 web shell 能力或至少不寫成已確認發生。
- 明確指出這是活動層級公告、沒有特定受害主機。

系統輸出**不應該**：
- 把 GoAnywhere、Accellion、Truebot、Cobalt Strike、SDBot、FlawedAmmyy、釣魚、勒索加密放進本次攻擊鏈。
- 產生橫向移動、AD 存取行為。
- 把 CVE-2023-0669 標為本事件的弱點。
- 自行指定某個 MOVEit 版本號或資料庫引擎作為事實。
