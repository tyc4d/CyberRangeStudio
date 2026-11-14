# Worker Brief — Codex Backend

你負責「情資輸入解析 / Scenario IR 來源多樣化」。只改以下檔案，其他一律不碰：

- `apps/api/app/cti/parser.py`、`apps/api/app/cti/citations.py`、`apps/api/app/cti/missing.py`（必要時）
- `fixtures/`（新增真實 STIX 2.1 與第二份公開情資）
- `tests/unit/test_cti_parser.py`、`tests/unit/test_cti_citations.py`（可新增 `tests/unit/test_*.py`）

**不要改**：`cti/analysis.py`（LLM 分析主流程，Lead 會協調）、`routers/`、`planner/`、`iac/`、`deploy/`、`validator/`、`apps/web`、任何 schema。

## 任務（Task 5）

1. **真實 STIX 2.1 輸入**：現在 `fixtures/sample-scenarios/demo-intrusion.stix.json` 是自製的。新增至少一份**真實、公開**的 STIX 2.1 bundle（例如公開 CTI 或 ATT&CK 匯出；`~/attack-flow/corpus` 與 `~/cr-research-m1` 可唯讀參考，但不是正確答案）。確保 `parser.py` 能解析真實 STIX 2.1 bundle 的結構（objects、relationships、attack-pattern、indicator 等），抽出 action/relation/host/service 候選，並正確標 `source=stix`、`epistemic_status`。temporal 與 dependency 關係要分開，不可把 STIX relationship 一律當依賴。

2. **第二份不同的公開情資**：再加一份與原 demo 不同主題的公開報告（markdown 或文字），讓流程不是只對單一樣本有效。可逐字引用、可核對 locator。

3. 解析要誠實：找得到出處 ≠ 解讀正確。區分「明文事實 / 推論 / 未知」。沒有的欄位就標缺失，不要編造 CVE、版本、主機名。

4. 單元測試：對新 STIX 與新情資各寫測試，驗證解析結果結構正確、引用可核對、未知不被當成已知。

## 規則
- 讀 `AGENTS.md`。只在你的 worktree 工作。你不能 git commit，改好留檔，Lead 檢查後提交。
- `PYTHONPATH=apps/api python -m pytest tests -q`（及你改到的部分）必須全綠。
- 不得把金鑰、個資或敏感資料送到外部；下載的情資樣本當不可信資料處理（放獨立目錄、不要從該目錄執行直譯器）。
- 正式 A/B/C 方法比較研究**暫緩**；可順手整理評估資料，但不要讓研究擋住開發。
- 完成或卡住時回報：詳細結果寫成檔案，只傳路徑。
