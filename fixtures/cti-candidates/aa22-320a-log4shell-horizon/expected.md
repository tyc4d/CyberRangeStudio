# 預期結果（人工標準答案）— CISA AA22-320A：Log4Shell → VMware Horizon → 橫向移動至 DC

- 匯入檔：`report.md`（本目錄；原文措辭）或 `source.pdf`（官方 PDF，SHA-256 `beacab7d…09e2`）
- 整理日期：2026-11-15　整理者：cti-research（人工閱讀原文後整理，非系統輸出）
- 用途：驗收模組 1（情資分析）、2（缺失補齊）、3（流程）、4（軟體相依）之輸出是否與原文一致。

## 來源分級說明

| 分級 | 意義 |
|---|---|
| SOURCE_SUPPORTED | 公告原文直接寫明，附原文引句 |
| EXTERNAL_ENRICHMENT | 公告沒寫，由 NVD／廠商公告／vulhub 等外部來源補充；**不是此事件的事實** |
| ASSUMED·SUBSTITUTED | 教學環境為了能重現而做的假設或替代 |
| BLOCKED·UNKNOWN | 公告未提供，也無法由外部可靠來源得知 |

頁碼為官方 PDF 頁碼。

## 1. 事件摘要（SOURCE_SUPPORTED）

疑似伊朗政府支持的 APT 於 2022 年 2 月利用 Log4Shell 入侵某 FCEB 機關未修補的 VMware Horizon 伺服器，安裝 XMRig 挖礦程式，以 RDP 橫向移動到 VDI-KMS 主機與網域控制站，竊取憑證、建立惡意網域管理員帳號，並在多台主機植入 Ngrok 反向代理維持存取。

> "cyber threat actors exploited the Log4Shell vulnerability in an unpatched VMware Horizon server, installed XMRig crypto mining software, moved laterally to the domain controller (DC), compromised credentials, and then implanted Ngrok reverse proxies on several hosts to maintain persistence." (p.1)

## 2. 資產／主機

| ID | 資產 | 角色 | 分級 | 依據 |
|---|---|---|---|---|
| H1 | VMware Horizon 伺服器 | 初始入侵點；對外提供 HTTPS | SOURCE_SUPPORTED | "the organization’s unpatched VMware Horizon server" (p.2) |
| H2 | VMware VDI-KMS 主機 | 第一個橫向移動目標；工具落地、Mimikatz 執行處 | SOURCE_SUPPORTED | "move laterally [TA0008] to a VMware VDI-KMS host" (p.3) |
| H3 | 網域控制站（DC／Active Directory） | 橫向移動終點；列舉網域電腦 | SOURCE_SUPPORTED | "moved laterally to the domain controller" (p.4) |
| H4 | 「several hosts」（數量、名稱不明） | 以惡意網域管理員帳號 RDP 登入、關閉 Defender、植入 Ngrok | SOURCE_SUPPORTED（存在）／BLOCKED·UNKNOWN（數量與身分） | "leveraged RDP to propagate to several hosts within the network" (p.3) |
| A1 | 攻擊者下載／回連伺服器 182.54.217[.]2 | 提供 mdeploy.text、file.zip | SOURCE_SUPPORTED | p.2–3 |
| A2 | 攻擊者 LDAP 伺服器 51.89.181[.]64（us-nation-ny[.]cf） | Log4Shell LDAP 回呼目的地（port 443） | SOURCE_SUPPORTED | "a suspected LDAP callback on port 443 to this IP address" (p.2) |
| A3 | transfer[.]sh（144.76.136[.]153） | 下載 PsExec／Mimikatz／Ngrok | SOURCE_SUPPORTED | p.3 |
| A4 | Ngrok 通道 tunnel.us.ngrok[.]com、korgn.su.lennut[.]com | RDP 代理出口（對外 HTTPS 443） | SOURCE_SUPPORTED | p.3–4 |

H1–H4 的作業系統：公告沒有直接寫「Windows」，但所有行為（PowerShell、Windows Defender、排程工作、RDP、DefaultAccount、LSASS）都是 Windows 行為 → 「Windows」可標為由原文推得；**Windows 版本為 BLOCKED·UNKNOWN**。

## 3. 軟體與版本

| 軟體 | 版本 | 分級 | 依據／備註 |
|---|---|---|---|
| VMware Horizon | **未提供** | BLOCKED·UNKNOWN | 公告只說 "unpatched"。系統應列為缺失項，不可自行填版本。 |
| Apache Log4j 2（Horizon 內含） | 未提供 | BLOCKED·UNKNOWN | 公告只給 CVE 編號。 |
| CVE-2021-44228 影響範圍 | Log4j2 2.0-beta9 至 2.15.0（不含 2.12.2、2.12.3、2.3.1） | EXTERNAL_ENRICHMENT | NVD：<https://nvd.nist.gov/vuln/detail/CVE-2021-44228> — "Apache Log4j2 2.0-beta9 through 2.15.0 (excluding security releases 2.12.2, 2.12.3, and 2.3.1) JNDI features used in configuration, log messages, and parameters do not protect against attacker controlled LDAP and other JNDI related endpoints."；CVSS 3.1 10.0（原始 JSON：`reports/overnight/evidence/cti-research/nvd/CVE-2021-44228.json`） |
| 受影響的 Horizon 版本 | 廠商公告 VMSA-2021-0028、KB 87073 | EXTERNAL_ENRICHMENT（**未逐字驗證**） | 公告 Mitigations 段僅指向 KB 87073。VMSA 頁面：<https://support.broadcom.com/web/ecx/support-content-notification/-/external/content/SecurityAdvisories/0/23618>。本次只取得二手摘要（修補版為 Horizon 2111／7.13.1／7.10.3），未讀到原始表格，不得當作事件事實。 |
| XMRig（wuacltservice.exe、WinRing0x64.sys、config.json） | 版本未提供 | SOURCE_SUPPORTED（檔名）／BLOCKED·UNKNOWN（版本） | p.3 |
| RuntimeBroker.exe（攻擊者檔案） | — | SOURCE_SUPPORTED | p.3；詳見 MAR 10387061-1.v1（公告引用，未納入本檔） |
| PsExec、Mimikatz、Ngrok | 版本未提供 | SOURCE_SUPPORTED（名稱）／BLOCKED·UNKNOWN（版本） | p.3 |
| Windows Defender | — | SOURCE_SUPPORTED | p.2 |
| 「additional anti-virus」 | 產品不明 | BLOCKED·UNKNOWN | p.4 |

## 4. 攻擊行為（依原文敘述順序）

「結果」欄：成功／失敗／僅具備能力（原文寫 can，未說實際發生）。

| # | 主機 | 行為 | ATT&CK（公告標註） | 結果 | 分級 | 原文引句 |
|---|---|---|---|---|---|---|
| B1 | H1 | 利用 Log4Shell（CVE-2021-44228）取得初始存取 | T1190 | 成功 | SOURCE_SUPPORTED | "In February 2022, the threat actors exploited Log4Shell [T1190] for initial access [TA0001] to the organization’s unpatched VMware Horizon server." |
| B2 | H1→A2 | 受害伺服器對攻擊者 LDAP 伺服器回呼（port 443），並查詢 us-nation-ny[.]cf | 公告未標 | 成功 | SOURCE_SUPPORTED | "Following HTTPS activity, CISA observed a suspected LDAP callback on port 443 to this IP address." |
| B3 | H1 | 以 PowerShell 將 `C:\` 加入 Windows Defender 排除清單 | T1059.001、T1562.001 | 成功 | SOURCE_SUPPORTED | "The actors’ exploit payload ran the following PowerShell command [T1059.001] that added an exclusion tool to Windows Defender [T1562.001]" |
| B4 | H1←A1 | 下載 mdeploy.text 存成 `C:\users\public\mde.ps1` | T1105 | 成功 | SOURCE_SUPPORTED | "The exploit payload then downloaded mdeploy.text from 182.54.217[.]2/mdepoy.txt to C:\users\public\mde.ps1 [T1105]." |
| B5 | H1←A1 | 執行 mde.ps1：下載 file.zip，並刪除 mde.ps1 | T1070.004 | 成功 | SOURCE_SUPPORTED | "When executed, mde.ps1 downloaded file.zip from 182.54.217[.]2 and removed mde.ps1 from the disk [T1070.004]." |
| B6 | H1 | 安裝 XMRig 挖礦程式 | 公告未標（T1496 為 EXTERNAL_ENRICHMENT 的分析者對應） | 成功 | SOURCE_SUPPORTED | "file.zip contained XMRig cryptocurrency mining software and associated configuration files." ／ "After obtaining initial access and installing XMRig on the VMWare Horizon server" |
| B7 | H1 | 建立排程工作 RuntimeBrokerService.exe，每日以 SYSTEM 執行 RuntimeBroker.exe（偽裝成正常工作） | T1053.005（偽裝 T1036.004 為 EXTERNAL_ENRICHMENT） | 成功 | SOURCE_SUPPORTED | "The exploit payload created a Scheduled Task [T1053.005] that executed RuntimeBroker.exe daily as SYSTEM." |
| B7a | H1 | RuntimeBroker.exe **可**建立本機帳號、ping 8.8.8.8 測連線 | T1136.001、T1016.001 | 僅具備能力 | SOURCE_SUPPORTED | "This file can create a local user account [T1136.001] and tests for internet connectivity by pinging 8.8.8.8 [T1016.001]." |
| B8 | H1→H2 | 以 RDP 與內建帳號 DefaultAccount 橫向移動到 VDI-KMS | T1021.001、T1078.001 | 成功 | SOURCE_SUPPORTED | "the actors used RDP [T1021.001] and the built-in Windows user account DefaultAccount [T1078.001] to move laterally [TA0008] to a VMware VDI-KMS host." |
| B9 | H2←A3 | 從 transfer[.]sh 下載約 30 MB：PsExec、Mimikatz、Ngrok | 公告此句未標（T1105 為合理對應） | 成功 | SOURCE_SUPPORTED | "CISA observed the actors download around 30 megabytes of files from transfer[.]sh server associated with 144.76.136[.]153." |
| B10 | H2 | 執行 Mimikatz 竊取憑證 | T1555（公告表格） | 成功 | SOURCE_SUPPORTED | "The threat actors then executed Mimikatz on VDI-KMS to harvest credentials" |
| B11 | H2（對網域） | 建立惡意網域管理員帳號 | T1136.002 | 成功 | SOURCE_SUPPORTED | "and created a rogue domain administrator account [T1136.002]." |
| B12 | H2→H4 | 用新帳號以 RDP 擴散到多台主機 | T1021.001 | 成功 | SOURCE_SUPPORTED | "Using the newly created account, the actors leveraged RDP to propagate to several hosts within the network." |
| B13 | H4 | 登入後以 GUI 手動關閉 Windows Defender | T1562.001 | 成功 | SOURCE_SUPPORTED | "the actors manually disabled Windows Defender via the Graphical User Interface (GUI)" |
| B14 | H4→A4 | 植入 Ngrok 執行檔與設定，代理 RDP（對外 HTTPS 443） | T1090 | 成功 | SOURCE_SUPPORTED | "implanted Ngrok executables and configuration files." ／ "The actors were able to proxy [T1090] RDP sessions" |
| B15 | H3 | 橫向移動到 DC 後，以 PowerShell `get-adcomputer` 列出網域所有電腦 | T1018、T1059.001 | 成功 | SOURCE_SUPPORTED | "they executed the following PowerShell command on the Active Directory to obtain a list of all machines attached to the domain [T1018]" |
| B16 | H4 | 變更多台主機的本機 administrator 密碼作為備援 | T1098 | 成功 | SOURCE_SUPPORTED | "The threat actors also changed the password for the local administrator account [T1098] on several hosts" |
| B17 | 主機未指明 | 嘗試用工作管理員傾印 LSASS，**被額外防毒軟體阻擋** | T1003.001 | **失敗** | SOURCE_SUPPORTED | "attempting to dump the Local Security Authority Subsystem Service (LSASS) process [T1003.001] with task manager but this was stopped by additional anti-virus" |

公告明確寫「可能但未觀察到」者（**不得**列為行為）：自訂 Ngrok 網域／其他通道網域 — "It is possible, but was not observed, that the threat actors configured a custom domain".

## 5. 行為間關係

### 5.1 時間順序（temporal；原文敘述順序，多數沒有時間戳）

B1 →(B2) → B3 → B4 → B5 → B6 → B7 → B8 → B9 → B10 → B11 → B12 → B13 → B14；B15、B16、B17 的相對時間原文未交代（只知道 B15 在「到達 DC 之後」）。

- 有日期者只有：2022 年 2 月（B1 與初始入侵）、2022 年 4 月（CISA 回溯分析）、2022 年 6 月中至 7 月中（事件應變）。
- B2 的時間有歧義：LDAP 回呼與 51.89.181[.]64 是 CISA 在 2022 年 4 月之後觀察到的流量（Overview 段），而 2 月的初始入侵連的是 182.54.217[.]2。**預期系統應標示時間不確定，而不是把 B2 硬排在 B1 之後幾秒。**
- B13 與 B14 原文寫在同一句（"Upon logging into each host…"），是每台主機重複的一組動作。

### 5.2 相依關係（dependency；A 必須成功，B 才做得到）

| 後項 | 需要 | 類型 | 分級 |
|---|---|---|---|
| B3、B4、B7 | B1（都是 exploit payload 的內容） | 執行權限 | SOURCE_SUPPORTED（"The actors’ exploit payload ran…"、"The exploit payload then downloaded…"、"The exploit payload created a Scheduled Task"） |
| B4 不被掃描 | B3（C:\ 排除） | 防禦規避 | SOURCE_SUPPORTED（"enabling threat actors to download tools to the c:\drive without virus scans"） |
| B5 | B4（mde.ps1 已落地） | 檔案 | SOURCE_SUPPORTED |
| B6 | B5（file.zip 內含 XMRig） | 檔案 | SOURCE_SUPPORTED |
| B8 | B1（已在 H1 立足）＋ DefaultAccount 可用於 RDP | 立足點＋憑證 | 立足點 SOURCE_SUPPORTED；**DefaultAccount 如何被啟用／取得密碼：BLOCKED·UNKNOWN** |
| B9、B10 | B8（已在 H2） | 立足點 | SOURCE_SUPPORTED（"Once the threat actor established themselves on the VDI-KMS host"） |
| B10 | B9（Mimikatz 已下載） | 工具 | SOURCE_SUPPORTED |
| B11 | B10（公告表格："The actors used Mimikatz to create a rogue domain administrator account."） | 憑證／權限 | SOURCE_SUPPORTED |
| B12 | B11（"Using the newly created account"） | 憑證 | SOURCE_SUPPORTED |
| B13、B14、B16 | B12（已登入各主機） | 立足點 | SOURCE_SUPPORTED |
| B14 | B9（Ngrok 已下載） | 工具 | SOURCE_SUPPORTED（工具來源）；如何搬到 H4：BLOCKED·UNKNOWN |
| B15 | 抵達 DC（途徑未寫，推定用 B11 的帳號） | 立足點 | 「在 DC 上」為 SOURCE_SUPPORTED；**用哪個帳號／哪條路徑到 DC：BLOCKED·UNKNOWN** |
| B17 | 無明確前置（主機未指明） | — | BLOCKED·UNKNOWN |

只有時間先後、**沒有**相依的例子（系統不應畫成相依）：B6（挖礦）→ B8（橫向移動）；B7（排程）→ B8；B16 ↔ B15。

## 6. 預期缺失項（模組 2 應提出）

1. VMware Horizon 的版本／元件（Connection Server？UAG？）— 未提供。
2. 各主機的 Windows 版本 — 未提供。
3. H1 的網路位置與對外開放埠（只知有 HTTPS 流量）— 未明確。
4. DefaultAccount 如何可用於 RDP（預設為停用帳號；啟用與密碼設定過程未寫）。
5. 「several hosts」的數量與角色。
6. 抵達 DC 所用的帳號與方式（RDP？PsExec？）— PsExec 有下載但**沒有任何一句說它被使用**。
7. 惡意網域管理員帳號名稱。
8. `powershell -enc` 的實際內容（原文以佔位字串代替）。
9. Log4Shell 觸發的 HTTP 請求位置／標頭 — 未提供。
10. 多數行為的時間戳。
11. 網域名稱、網段、主機名稱。

## 7. 重現可行性評估

| 行為 | 評估 | 原因與教學替代 |
|---|---|---|
| B1 Log4Shell on Horizon | **教學替代** | VMware Horizon 為商業授權軟體，無公開可散佈映像。替代：vulhub `log4j/CVE-2021-44228`（Apache Solr 8.11.0，內含 Log4j 2.14.1），同一個 CVE、同樣的 JNDI/LDAP 觸發方式，但**產品不同、Linux 容器而非 Windows**（ASSUMED·SUBSTITUTED）。若有 Windows VM，可在其上跑含弱點 Log4j 的 Java 服務以保留 Windows 後續行為。 |
| B2 LDAP 回呼 | 真實重現 | 在隔離網路內自架 LDAP 參照伺服器（攻擊者容器），不連外。 |
| B3 Defender 排除 | Windows VM 才能真實重現；Linux 為無法重現 | `Add-MpPreference` 僅 Windows。Linux 替代不建議硬湊；標 NOT_TESTED 或用 Windows VM。 |
| B4、B5 下載／自刪 | 真實重現（技術行為）／教學替代（Linux 用 shell 腳本） | 下載來源改為實驗網內的 HTTP 伺服器。 |
| B6 XMRig | **教學替代** | 不部署真的挖礦；用無害的 CPU 佔用程式＋同名設定檔模擬，並明確標示替代。 |
| B7 排程工作 | Windows VM 真實重現；Linux 以 cron 教學替代 | — |
| B8、B12 RDP 橫向移動 | Windows VM 真實重現；Linux 以 xrdp 或 SSH 教學替代 | DefaultAccount 的啟用方式原文沒寫 → 實驗需 ASSUMED（預先啟用並設密碼）。 |
| B9 工具下載 | 部分 | 來源改實驗網內檔案伺服器；Mimikatz／PsExec 為 Windows 工具。 |
| B10 Mimikatz | Windows VM 真實重現；Linux 無法重現 | Linux 可用「讀取明文憑證檔」做教學替代，但技術不同，須標示。 |
| B11 建立網域管理員 | Windows AD 真實重現；Samba AD DC 為教學替代（`samba-tool user create` + 加入 Domain Admins） | — |
| B13 GUI 關閉 Defender | 部分 | GUI 操作難以自動驗證；可用等效指令替代並標示。 |
| B14 Ngrok 代理 | **教學替代** | 不得連到真實 ngrok.com。用實驗網內的反向通道（如 chisel／ssh -R 到攻擊者容器）模擬「內部 RDP 經 443 對外」。 |
| B15 get-adcomputer | Windows AD 真實重現；Samba AD + ldapsearch 教學替代 | — |
| B16 改本機管理員密碼 | 真實重現（Windows `net user`）／Linux `passwd` 替代 | — |
| B17 LSASS 傾印被擋 | 部分／無法完整重現 | 需要會阻擋的 AV；產品不明。可驗證「嘗試→被拒」但 AV 為 ASSUMED。 |

整體：**Linux Docker 可重現的主幹是 B1→B2→B4→B5→(B6 替代)→橫向移動替代→帳號建立替代**；Windows 專屬行為（B3、B10、B13、B17）要 Windows VM 才是真實重現。此鏈適合測「替代與誠實標示」能力。

## 8. 外部 PoC／練習映像（EXTERNAL_ENRICHMENT，非事件事實）

- vulhub `log4j/CVE-2021-44228`：<https://github.com/vulhub/vulhub/tree/master/log4j/CVE-2021-44228> — 映像 `vulhub/solr:8.11.0`，README："Execute following command to start a Apache Solr 8.11.0, which use Log4j 2.14.1"；觸發點 `GET /solr/admin/cores?action=${jndi:ldap://…}`。（存檔：`reports/overnight/evidence/cti-research/vulhub/log4j_CVE-2021-44228.*`）
- CISA 另有惡意程式分析報告 MAR 10387061-1.v1（公告引用），本次未擷取。

## 9. 驗收檢查點

系統輸出**應該**：
- 抓到 H1、H2、H3 三類主機與 B1、B3–B8、B10–B12、B14、B15 這些核心行為，且每個行為附得到原文引句。
- CVE-2021-44228 標為原文支持（Overview 段有寫）。
- Horizon 版本、Windows 版本列為缺失，不自行填值。
- B17 標為失敗／被阻擋；B7a 標為能力而非已發生。
- 時間順序與相依分開；B6→B8 不畫成相依。

系統輸出**不應該**：
- 把 Solr、Log4j 2.14.1、vulhub 寫成事件事實（只能是替代／外部補充）。
- 把 PsExec 寫成「已用於橫向移動」（原文只說下載）。
- 把「自訂 Ngrok 網域」列為已發生行為。
- 編造網域名稱、主機名稱、帳號名稱、Horizon 版本。
