# M9 export R6-01 修正與驗證

日期：2026-11-16，Asia/Taipei。工作樹：`/home/tyc4d/cr-project/.worktrees/m9-export`；分支：`agent/m9-export`；起始與完成 HEAD 均為 `5cf0264285e6993388ebbeb24b9816ffbce9d426`，修正留在工作樹，未 add／commit／merge。

**R6-01 指定的四項 builder 案例與全部 review6 verifier controls 已通過；歷輪 export 案例未回歸。這是修正者的驗證報告，仍由 Lead 整合與最終獨立審查。**

已先讀根目錄 AGENTS、approved scope、FIX-ROUND-6、review6 報告與 acceptance。Lead 以訊息明確解除任務範本的唯讀 QA 限制，授權修改 `apps/api/app/poc/export/**`，並同意既有自有單元測試從舊 span 排版比對改為 parser 語意與無洩漏斷言；輸入案例皆保留。未啟動其他 Agent，未修改任何 `reports/overnight/m9/review*/` acceptance、其他產品檔案或唯讀研究參考資料。未部署、未呼叫 LLM、HTTP、PVE 或真實 exploit。

## 修正內容與安全邊界

僅兩份產品／測試檔案變更：

- `apps/api/app/poc/export/bundle.py`。
- `apps/api/app/poc/export/test_export.py`。

`_parse_embedded`（bundle.py:398）先用真正的 `json.loads`／`yaml.safe_load` 解析 description 等字串中的文件；YAML tag、引號、block scalar、alias 與 merge 先解析成值，再交由遞迴 redactor 處理。支援「簡短前言＋完整 YAML suffix」，前言另外掃描。文件候選無法解析時丟出 `ExportError`，不再回傳 None 假裝沒有結構。辨識文件候選的語法檢查只用來區分一般散文與損壞文件，不決定秘密值的 span／長度。

`_redact_free_string`（:451）從清理後的物件重新序列化 JSON／YAML，重新解析即將寫入的字串並掃描解析結果。清理後結構損壞、仍有秘密或不能證明安全都拒絕匯出；不再只把 `!!str`／`!!binary` 的 tag 換成 marker。未解析成文件的普通散文仍沿用既有 URL、header、shell／label 清理，結果也要通過重新檢查。

`redact`／`_scalar_leaves`（:488、:514）另核對已知 secret subtree 的原始字串／bytes 值，避免 YAML alias 在另一個 public 欄位留下同一秘密副本；有不能證明已移除的副本便拒絕。循環、超過 64 層的結構，以及不支援的 YAML collection 都拒絕，不略過。非空 bytes 秘密值會清理；bytes 型別的秘密鍵名也按 UTF-8 解碼後辨識。

`_file_secrets`（:663）仍由 builder final scan 與 `verify_bundle` 共用：對實際 emitted scenario JSON 使用 `json.loads`，對 YAML 使用 `yaml.safe_load`，再以 `find_field_secrets`（:605）檢查解析後欄位及內嵌文件。非空秘密欄位字串／bytes 都會被抓到；內嵌解析失敗變成 unsafe hit，因此 verifier 回報 `secret material in <path>`，builder 丟 `ExportError`。非法 UTF-8 不再用 replacement character 吞掉。原本允許的空值、redaction marker、布林／null 與安全 runtime reference 規則保留。

產品行為會刻意改變：內嵌 YAML 的引號、縮排與排版可能被 serializer 正規化；損壞／未知 tag／循環／過深文件以及秘密副本會收到匯出拒絕。一般公開文字、合法公開 JSON／YAML、日期、正常 merge、`${DB_PASSWORD}` 與既有 marker 均有成功匯出控制案例。這不把沒有秘密結構上下文的任意散文或任意 opaque encoding 宣稱為可辨識秘密。

## 永久回歸測試

`test_export.py:496` 新增七個 test methods，共 37 個 subtests：

- 對 ZIP 內兩份 emitted scenario 分別實際 parse，再用獨立於 production checker 的遞迴 YAML parser oracle 確認秘密值已移除；涵蓋四種 R6 tag、escaped key、bytes key、alias／merge、set／omap、JSON 裡的 YAML、YAML 裡的 JSON，以及雙重序列化。
- string／bytes secret alias 的正反鍵順序都必須拒絕 public 副本。
- 損壞結構、未知 tag、舊版半清理產物、循環與過深結構：builder 拒絕；另重算正確 SHA-256 後，verifier 仍拒絕，不能靠 hash mismatch 通過測試。
- 透過 serializer 故障注入證明「重新序列化仍損壞」及「重新序列化仍帶 bytes 秘密」都會拒絕。只有這個防線測試替換 serializer；其餘使用真正的 builder、serializer、redactor 與 verifier。
- 合法公開內容保留 decoded 語意；舊未加引號 marker 可正規化後再匯出。

原 R4 十一種與 R5 六種 raw 輸入全部保留；JSON／YAML 改比解析結果，散文與 shell 仍保留既有精確輸出檢查，另加原秘密／編碼值不得留下與最後欄位掃描斷言。未刪案例、未改獨立驗收 assertions、無新增 xfail／skip。

## 最後一版實跑結果

全部 invocation 均使用本工作樹的 `PYTHONPATH=/home/tyc4d/cr-project/.worktrees/m9-export/packages/contracts`、`PYTHONDONTWRITEBYTECODE=1`、`-p no:cacheprovider`，runtime data 與 basetemp 各自隔離於 `/tmp`。

| 檢查 | 結果 |
|---|---|
| 自有 export unit ＋完整 review6 | **86 passed，37 subtests passed**，5.63 秒；其中 export unit 37 項、review6 49 項 |
| review1 原 acceptance | **57 passed，1 failed**；failure 僅既有 #5 |
| review2 原 acceptance | **89 passed** |
| review3 原 acceptance | **34 passed** |
| review4 原 acceptance | **59 passed** |
| review5 原 acceptance | **24 passed** |
| review6 原 acceptance | **49 passed**，四個指定 tagged-YAML builder 參數全過 |
| 六份 review acceptance 合併 invocation | **312 passed，1 failed，0 skipped**，10.02 秒 |
| apps/api suite | **283 passed，2 deselected，131 subtests passed**，6.62 秒 |
| `git diff --check` | 通過 |

兩項 deselected 是需要 Docker 部署的既有 integration：

1. `app/deploy/test_local_compose_integration.py::LocalComposeIntegrationTests::test_two_container_up_status_validate_down`
2. `app/deploy/test_local_compose_integration.py::HostIsolationIntegrationTests::test_container_on_generated_lab_network_cannot_reach_a_host_service`

既有 #5 `review/test_m9_review.py::test_cancel_does_not_allow_delayed_launch_after_cleanup_returns` 未排除、未修改，仍在 `finished.wait(1)` 失敗，與本次 export 無關。沒有宣稱整個 M9 final gate 全綠。前端與 R6-02 未測、未改，由其他工作樹負責。每次 invocation 原有兩個 `jsonschema.RefResolver` deprecation warnings，沒有新增 warning 類別。

## 證據與重跑

同目錄證據：

- `baseline-review6.log`：修正前 **4 failed，45 passed**，重現兩份 emitted scenario 含秘密且 verifier 回空列表。
- `final-export-and-review6.log`：最後一版的 export＋R6 結果。
- `final-reviews.log`、`final-reviews.xml`：六輪 acceptance 最後一版完整結果；上表逐檔數量由 JUnit XML 解析核對。
- `final-api-suite.log`：最後一版 API suite 結果。

`.log` 是 repository 忽略檔，但本工作樹內實體檔均保留，可直接讀；JUnit XML 與此報告是新增檔。沒有建立或提交任何 ZIP 產品匯出成品。

```sh
cd /home/tyc4d/cr-project/.worktrees/m9-export/apps/api
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/tyc4d/cr-project/.worktrees/m9-export/packages/contracts

CR_DATA_DIR=/tmp/m9-export-r6-reproduce-unit-data /home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider app/poc/export/test_export.py ../../reports/overnight/m9/review6/test_m9_review6.py --basetemp=/tmp/m9-export-r6-reproduce-unit-tmp --tb=short

CR_DATA_DIR=/tmp/m9-export-r6-reproduce-reviews-data /home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider ../../reports/overnight/m9/review/test_m9_review.py ../../reports/overnight/m9/review2/test_m9_review2.py ../../reports/overnight/m9/review3/test_m9_review3.py ../../reports/overnight/m9/review4/test_m9_review4.py ../../reports/overnight/m9/review5/test_m9_review5.py ../../reports/overnight/m9/review6/test_m9_review6.py --basetemp=/tmp/m9-export-r6-reproduce-reviews-tmp --tb=short

CR_DATA_DIR=/tmp/m9-export-r6-reproduce-suite-data /home/tyc4d/cr-project/.venv/bin/python -m pytest -q -p no:cacheprovider --basetemp=/tmp/m9-export-r6-reproduce-suite-tmp --deselect=app/deploy/test_local_compose_integration.py::LocalComposeIntegrationTests::test_two_container_up_status_validate_down --deselect=app/deploy/test_local_compose_integration.py::HostIsolationIntegrationTests::test_container_on_generated_lab_network_cannot_reach_a_host_service
```

可供 Lead 檢查、代為提交；本工作樹沒有任何跨檔修正需求。
