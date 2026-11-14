# Claude A — CTI Researcher（名稱 cti-research）
先讀 `reports/overnight/briefs/COMMON.md`。你不改產品程式碼。
檔案所有權：`reports/overnight/CTI-POC-RESEARCH.md`、`fixtures/cti-candidates/**`、`reports/overnight/evidence/cti-research/**`。

任務：
1. 用網路搜尋權威公開的真實攻擊事件報告。優先 CISA AA22-320A（Log4Shell→VMware Horizon，伊朗 APT），並另找至少 2–3 個適合轉成教學實驗、**能在本機 Docker/Linux 隔離重現主要技術行為**的事件（技術特性要不同，例如 Web RCE→DB、憑證濫用橫向移動、供應鏈／檔案傳輸漏洞等）。
2. 每個事件擷取：攻擊行為（依序）、資產／服務、軟體與精確版本、前置條件、行為間相依關係（temporal 與 dependency 分開）、ATT&CK 技術、CVE（查 NVD／官方公告）、公開 PoC 或可取得的易受影響練習映像（例如 vulhub）之來源。
3. 每一項都標來源分級（SOURCE_SUPPORTED / EXTERNAL_ENRICHMENT / ASSUMED·SUBSTITUTED / BLOCKED·UNKNOWN），附 URL 與原文引句。外部 PoC 的內容不得寫成原始事件事實。
4. 評估每個行為的重現可行性（真實重現／教學替代／部分／無法重現）與原因。
5. 選出**至少兩條**技術特性不同的候選攻擊鏈供 E2E 測試，另備**一份刻意資訊不足的負向測試情資**。把每份情資原文存成系統可匯入的檔案（`fixtures/cti-candidates/<slug>/report.md`，保留原文措辭、附來源 URL 與擷取日期；有官方 PDF 也一併下載），並附 `expected.md`（人工整理的預期行為、相依、缺失項——作為後續驗收的標準答案）。
6. 第一個里程碑（優先，約 30–40 分鐘內）：先交出 AA22-320A 與另一個事件的 report.md + expected.md，立即回報，讓其他人能開始測；之後再補齊其餘。
