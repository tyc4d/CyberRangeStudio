# CTI 候選事件研究（cti-research）

整理日期：2026-11-15。所有候選檔在 `fixtures/cti-candidates/<slug>/`：
`report.md`（可匯入，來源原文措辭）、`expected.md`（人工標準答案）、`source.pdf`（官方 PDF）、`source.pdf.txt`（pdftotext 全文）。

## 1. 候選一覽

| slug | 來源（皆為官方公開文件） | 技術特性 | 有無 CVE | Linux Docker 重現 | 標準答案 |
|---|---|---|---|---|---|
| `aa22-320a-log4shell-horizon` | CISA/FBI AA22-320A | Log4Shell → Windows/AD 橫向移動、憑證竊取、反向代理 | CVE-2021-44228（原文有） | 教學替代＋部分（Windows 專屬行為需 Windows VM） | 有 |
| `equifax-2017-struts-db` | GAO-18-559（第 10–16 頁） | Web 應用 RCE → 明文憑證 → 多資料庫查詢 → 加密通道外洩 | 原文**沒寫** CVE；CVE-2017-5638 為外部補充 | **可完整重現技術行為** | 有 |
| `aa24-046a-former-employee-account` | CISA/MS-ISAC AA24-046A | 離職員工帳號 → VPN → 本機儲存憑證 → LDAP 列舉 → SMB 驗證 | **無 CVE** | 部分（Samba AD 替代） | 有 |
| `aa23-158a-clop-moveit` | FBI/CISA AA23-158A | 檔案傳輸產品 SQLi → web shell → 資料庫竊取（活動層級公告，含大量歷史背景） | CVE-2023-34362（原文有） | 教學替代（商業 Windows 軟體，無可用映像） | 有 |
| `aa23-289a-confluence-cve-2023-22515` | CISA/FBI/MS-ISAC AA23-289A | 存取控制缺陷 → 未授權管理員 → 雲端儲存外洩 | CVE-2023-22515（原文有） | 可（vulhub 有同版本映像，但安裝需人工填試用授權碼） | **未完成**（見 §6） |
| `negative-insufficient-intel` | 自撰虛構通知（非真實事件） | 刻意資訊不足 | 無 | 無法重現（正確結果是 BLOCKED） | 有 |

## 2. 建議的 E2E 測試鏈

1. **`equifax-2017-struts-db`（首選）**：全程可在 Linux 容器內重現；而且原文不含 CVE 與版本，能同時測「缺失補齊」與「外部補充不得冒充原文」。
2. **`aa22-320a-log4shell-horizon`**：技術特性不同（Windows/AD 橫向移動），行為最多（17 項），測「替代與誠實標示」；Linux 上多數後段行為只能替代或標 NOT_TESTED。
3. 備選：`aa24-046a-former-employee-account`（無漏洞的憑證濫用鏈，測系統不硬找 CVE）。
4. 負向：`negative-insufficient-intel`（任何 CVE、產品名、工具名或 PASS 出現即失敗）。

## 3. 每份標準答案的內容

每個 `expected.md` 都含：資產／主機、軟體與版本、依序的攻擊行為（附原文引句與 ATT&CK）、時間順序與相依關係（分開列）、預期缺失項、逐行為重現可行性、外部資源、驗收檢查點（應該／不應該出現的輸出）。每一項都標來源分級。

## 4. 各候選的重點陷阱（驗收時最容易出錯的地方）

| 候選 | 陷阱 |
|---|---|
| AA22-320A | Horizon 與 Windows 版本原文沒有；PsExec 只有「下載」沒有「使用」；LSASS 傾印是**失敗**；RuntimeBroker.exe 的建帳號是「能力」；「自訂 Ngrok 網域」原文明說未觀察到；挖礦→橫向移動只有時間先後、沒有相依。 |
| Equifax | 3 月與 5 月是兩次獨立存取（原文 "a separate incident"），不可畫成相依；GAO 沒有 CVE、web shell、作業系統；GAO 與眾議院報告對「憑證過期多久」（10 vs 19 個月）與「帳密放哪裡」說法不同，應並列。 |
| AA24-046A | 多數行為是 likely／assessed／believed；Azure 橫向移動**沒有發生**；Untitled Goose Tool 是應變工具；B2–B5 之間的先後原文沒寫。 |
| AA23-158A | GoAnywhere、Accellion、Truebot、Cobalt Strike 等是歷史背景／工具箱，不屬於本鏈；版本是「受影響版本線」不是受害者版本；web shell 功能多為「能力」。 |
| 負向 | 原文只有模糊語句；勒索集團關聯是未證實傳言且明說未加密。 |

## 5. 來源與取得方式

| 檔案 | URL | SHA-256 |
|---|---|---|
| AA22-320A PDF | https://www.cisa.gov/sites/default/files/publications/aa22-320a_joint_csa_iranian_government-sponsored_apt_actors_compromise_federal%20network_deploy_crypto%20miner_credential_harvester.pdf | `beacab7d0ed36ddc4e51b3e7a00e24ac9c612bfb29dffde3ffef01597b4109e2` |
| GAO-18-559 PDF | https://www.gao.gov/assets/gao-18-559.pdf | `7f352448054fd5c5faabf799e5895ae2a6780edc1136e22ca9e300cfca6245f8` |
| AA24-046A PDF | https://www.cisa.gov/sites/default/files/2024-02/aa24-046a-threat-actor-leverages-compromised%20account-of%20former-employee.pdf | `55534abb402001e831734b065f78d5c8ba6dcaec599fd458c5b3745304261649` |
| AA23-158A PDF | https://www.cisa.gov/sites/default/files/2023-06/aa23-158a-stopransomware-cl0p-ransomware-gang-exploits-moveit-vulnerability.pdf | `f9b23261a8c29328879fd37dcb8241aedfc2af13bc06042a0f90e927aeb7518e` |
| AA23-289A PDF（IC3 鏡像） | https://www.ic3.gov/CSA/2023/231016.pdf | `01e2c14d4fd5480aa2195489b237fcd4ebe67d4b0a077b1bd3a426babaaf95f6` |
| 眾議院監督委員會 Equifax 報告（僅作外部補充） | https://oversight.house.gov/wp-content/uploads/2018/12/Equifax-Report.pdf | `d59b6463f2c3e197836946e72112e69dcc896a055e900cf0138729192851fc17` |

- PDF 皆以平台 WebFetch 取得原始位元組（CISA 會擋 curl，沿用既有 `fixtures/sample-scenarios/sources/PROVENANCE.md` 的做法）；AA22-320A 的雜湊與既有 fixture 相同。
- `report.md` 由 `reports/overnight/evidence/cti-research/build_reports.py` 從 `source.pdf.txt` 依行號範圍機械式產生：只去頁首頁尾、側欄、縮排與斷行，不改寫、不增句。可重跑驗證。
- NVD 原始 JSON 在 `reports/overnight/evidence/cti-research/nvd/`；vulhub 的 README 與 compose 存檔在 `…/vulhub/`；眾議院報告在 `…/enrichment/`。

## 6. 未完成與限制（如實）

- **`aa23-289a-confluence-cve-2023-22515` 沒有 `expected.md`**：`report.md` 與官方 PDF 已備妥可匯入，但標準答案撰寫中途被中止，未完成的草稿已刪除，沒有重寫。此候選目前只能當匯入素材，不能當驗收依據。
- **沒有實際部署或執行任何練習映像**（任務範圍是研究，不改產品程式碼）。重現可行性都是依文件判斷，未經實測。
- 未逐字驗證的外部資料已在各 `expected.md` 標明：VMware VMSA-2021-0028 的 Horizon 受影響版本表、MOVEit 公告引用的 Progress／Mandiant 文章、Samba AD 作為替代的可行性。
- AA22-320A 的 STIX（1.1.1 XML）與 MAR 10387061-1.v1 未擷取。
- `report.md` 只含各公告的摘要與技術細節段；ATT&CK 對照表、緩解建議在 `source.pdf.txt`。若要測整份 PDF 匯入，請直接上傳 `source.pdf`。
- GAO 節錄保留了 PDF 擷取出的行內註腳數字（如 "portal25"）。
- 負向測試情資是自撰的虛構文字，不是真實事件（檔尾有一行標示）。

## 7. 需產品負責人決定

1. 教學替代的接受程度：AA22-320A 的初始入侵若用「同 CVE、不同產品」的映像取代 VMware Horizon，是否可接受作為正式教材（需在畫面上標示替代）。
2. Windows 專屬行為（Defender 排除、Mimikatz、RDP）是否要用 Windows VM 真實重現，或在 Linux 上標 NOT_TESTED 即可。
3. 是否接受以 GAO（政府稽核報告，受害者自述的轉述）作為情資來源類型，或只收 CISA 這類技術公告。
4. 需要人工取得授權碼的練習映像（Confluence）是否納入。
