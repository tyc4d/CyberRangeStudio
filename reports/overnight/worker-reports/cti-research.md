# Worker 報告 — cti-research

分支 `agent/cti-research`。總報告：`reports/overnight/CTI-POC-RESEARCH.md`。

## 做了什麼

- 找了 5 個官方公開的真實事件／活動報告，下載官方 PDF，產生可匯入的 `report.md`（原文措辭）。
- 其中 4 個寫了人工標準答案 `expected.md`（行為、資產、版本、時間順序與相依分開、缺失項、重現可行性、驗收檢查點，逐項標來源分級並附原文引句）。
- 寫了 1 份刻意資訊不足的負向測試情資（自撰虛構）與其標準答案。
- 建議 E2E 用：`equifax-2017-struts-db`（首選，Linux 容器可完整重現）＋ `aa22-320a-log4shell-horizon`；備選 `aa24-046a-former-employee-account`；負向 `negative-insufficient-intel`。

## 檔案（全部在檔案所有權範圍內，未改產品程式碼）

- `fixtures/cti-candidates/aa22-320a-log4shell-horizon/` — report.md、expected.md、source.pdf、source.pdf.txt
- `fixtures/cti-candidates/equifax-2017-struts-db/` — 同上
- `fixtures/cti-candidates/aa24-046a-former-employee-account/` — 同上
- `fixtures/cti-candidates/aa23-158a-clop-moveit/` — 同上
- `fixtures/cti-candidates/aa23-289a-confluence-cve-2023-22515/` — report.md、source.pdf、source.pdf.txt（**無 expected.md**）
- `fixtures/cti-candidates/negative-insufficient-intel/` — report.md、expected.md
- `reports/overnight/CTI-POC-RESEARCH.md`
- `reports/overnight/evidence/cti-research/` — build_reports.py、nvd/、vulhub/、enrichment/

## Commit

- `8099a10` AA22-320A 與 Equifax（里程碑 1）
- `dccce42` AA24-046A、AA23-158A、負向測試
- 最後一筆：Confluence 匯入素材、總報告、本報告

## 測試

沒有改程式碼。基準測試在本 worktree 執行：

```
PYTHONPATH=apps/api /home/tyc4d/cr-project/.venv/bin/python -m pytest apps/api tests -q
55 passed, 2 warnings, 3 subtests passed in 25.90s
```

（COMMON.md 寫的基準是 39 passed；此分支目前是 55。）

`report.md` 重建指令：`/home/tyc4d/cr-project/.venv/bin/python reports/overnight/evidence/cti-research/build_reports.py fixtures/cti-candidates`

## 沒做／未解

- Confluence 候選的 `expected.md` 沒有完成：撰寫中途被中止，草稿已刪除，未重寫。
- **沒有把任何 fixture 實際匯入系統測過**，也沒有部署任何練習映像；重現可行性都是依文件判斷。
- 部分外部補充未逐字驗證（VMware VMSA-2021-0028 版本表、Progress／Mandiant 文章），已在各 expected.md 標明。
- AA22-320A 的 STIX 與 MAR 報告未擷取。

## 需產品負責人決定

見 `reports/overnight/CTI-POC-RESEARCH.md` §7（替代映像是否可作正式教材、Windows 行為是否要用 VM、是否接受 GAO 類來源、需人工授權碼的映像是否納入）。
