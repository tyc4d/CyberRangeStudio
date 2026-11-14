# Worker 報告 — cti-research（進行中）

## 里程碑 1（已完成）

兩條候選攻擊鏈的匯入檔與標準答案：

| slug | 來源 | 技術特性 | 檔案 |
|---|---|---|---|
| `aa22-320a-log4shell-horizon` | CISA AA22-320A（官方 PDF） | Log4Shell → Windows/AD 橫向移動、憑證、Ngrok | `report.md`、`expected.md`、`source.pdf`、`source.pdf.txt` |
| `equifax-2017-struts-db` | GAO-18-559（官方 PDF） | Struts Web RCE → 明文憑證 → 多資料庫查詢 → HTTPS 外洩（Linux Docker 可完整重現） | 同上 |

路徑：`fixtures/cti-candidates/<slug>/`。`report.md` 由 `reports/overnight/evidence/cti-research/build_reports.py` 從官方 PDF 文字機械式產生（只去頁首頁尾與斷行，不改寫）。

## 進行中

- AA24-046A（離職員工帳號／憑證濫用）、AA23-158A（MOVEit 檔案傳輸）、負向測試情資、總報告 `reports/overnight/CTI-POC-RESEARCH.md`。
