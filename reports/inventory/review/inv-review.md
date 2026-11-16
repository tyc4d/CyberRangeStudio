# Inventory 獨立 QA：CHANGES REQUESTED

- 日期：2026-11-16；檢查 commit：`b7cd3a5`（工作分支 `agent/inv-review`）。
- 依據：根目錄 `AGENTS.md`、`docs/inventory/DESIGN.md` 的 Resolution contract／Acceptance、`docs/approved-scope.md`、`reports/inventory/POLISH-NOTES.md`。
- 角色：只測試與回報，未修產品程式、未啟動 Agent、未執行 `git add`／commit。
- 新增檔案：本報告及 `review/qa_inventory.py`；既有 tracked 檔案 `git diff --name-only` 為空。

## 結果

既有完整 app＋unit 套件為 **253 passed、3 subtests passed、2 warnings，83.78 秒**。但獨立驗收有 **27 項檢查，18 PASS、9 FAIL**，失敗歸納為以下 **7 項發現**。目前不能通過 Inventory 驗收。

`resolve()` 單獨呼叫對 Horizon／Log4Shell 的輸出正確，問題主要發生於分析與依賴規劃的整合：真正送往拓樸的結果沒有選好的 Log4Shell 替代元件，且 CVE 與來源可信度存在實質錯誤。

## 依嚴重度排序的發現

### 1. P1：依賴規劃取消已解析的 Log4Shell 替代元件，核心驗收未達成

位置：`apps/api/app/planner/dependencies.py:774`、`:778`、`:808`；漏洞暱稱另在 `:515` 被改成 `Log4j`。

重現：`review/qa_inventory.py` 的 `owner:substitute-survives-dependency-topology`。

輸入是一台 `role="VMware Horizon server"` 的 `h1`，兩個有來源的服務 `VMware Horizon`、`Log4j`，各帶 `cve=["CVE-2021-44228"]`，動作為 `Exploit Log4Shell CVE-2021-44228 in VMware Horizon`／`T1190`。

- 直接 `resolve("VMware Horizon", cves=["CVE-2021-44228"])` 正確回傳 `vuln-log4shell-solr`、`is_substitute=true`、`version_basis=substituted`、不問版本。
- `plan_dependencies()` 卻因舊 matcher 命中 `unsupported-*`，無條件清掉新 resolver 選定的 component 與 substitute flag。
- 輸出兩個原服務均為 `no_component=true`、`is_substitute=false`、`tier=unavailable`，卻殘留 `version_basis=substituted` 及 `reproduces_cve=["CVE-2021-44228"]`。
- 拓樸只留下 `image_hint=unsupported-vmware-horizon`、`runtime=external_platform`、`deployable=false`，外加 attacker；沒有可部署的 Solr 替代目標，故無法沿此輸出完成替代品部署＋探針驗證。

另以既有 `fixtures/sample-scenarios/cisa-aa22-320a.md`＋`tests/fixtures/recorded/cisa-aa22-320a.single_pass.llm.json` 離線重播，亦無 `vuln-log4shell-solr` 可部署目標。該 fixture 僅寫 Log4Shell 暱稱，未含數字 CVE；它驗證的是暱稱路徑，前述合成案例另驗證明寫 CVE 的路徑。兩者均失敗。

預期：保留原 Horizon 的未重現紀錄，同時保留一個明確標記、實際指向 `vuln-log4shell-solr` 的替代目標，讓既有部署與對應探針可以使用它；不可用舊 unsupported sentinel 覆蓋此決策。

### 2. P1：來源 CVE 被配給無關產品，進而把 PostgreSQL 換成 Struts

位置：`apps/api/app/cti/analysis.py:1027`、`:1039`。

重現：`analysis:CVE-does-not-leak-to-unrelated-product`。輸入來源：

```text
Apache Struts was exploited using CVE-2017-5638.

Separately, PostgreSQL stored application data without being exploited.
```

離線 extraction 只提供 `Apache Struts` 與 `PostgreSQL` 兩個服務，各引用自己的句子，兩者都未預先填 CVE。

實際結果：

```text
PostgreSQL.cve = ["CVE-2017-5638"]
PostgreSQL.field_sources.cve = "source_quote"
PostgreSQL.epistemic_status = "supported"
```

繼續規劃後，`PostgreSQL.catalogue_component=vuln-struts2-s2-045`、`is_substitute=true`，拓樸將其列為 8080 服務。來源並未指出 PostgreSQL 有這個 CVE，也未要求替換資料庫。

原因：條件只測 `resolve_inventory(...).component_id` 是否存在；對可重現的已知 CVE，resolver 可為任意不同產品提出 substitute，因此這不是「CVE 屬於該服務」的證據。此處也沒有檢查該 CVE 句子是否為此服務所引用。

預期：只有來源明確關聯，或可證明是同產品的對應，才傳遞 CVE；不能把「能找替代品」當作原產品受該漏洞影響的來源證據。

### 3. P1：來源沒有 CVE，planner 卻新增具體 CVE 並維持 supported

位置：`apps/api/app/planner/dependencies.py:852`、`:916`；資料來自 `apps/api/app/planner/inventory.py:144` 的元件能力清單。

重現：`honesty:no-new-source-CVE-from-catalogue`。

```text
來源：The public-facing Apache Struts application was exploited.
分析輸出：name="Apache Struts", epistemic_status="supported"，沒有 cve
規劃輸出：cve=["CVE-2017-5638"], epistemic_status="supported"
           version_basis="assumed", catalogue_component="vuln-struts2-s2-045"
```

`reproduces_cve` 表示所選實驗元件能重現的漏洞，這個能力資料本身合理；錯誤是將它直接聯集進描述來源的服務 `cve`。版本有標 assumed，卻沒有任何對 CVE 的假設／非來源標記。既有可信服務紀錄因而新增原文未寫的 CVE，違反任務要求「only source CVEs propagated」。

預期：元件的重現能力與來源宣稱分開；新增的推定漏洞不得被保留成有來源支持的服務事實。

### 4. P2：使用者明確選擇會被重新規劃覆蓋，且仍宣稱是使用者選的

位置：`apps/api/app/planner/dependencies.py:792`、`:796`、`:844`。

重現：`honesty:explicit-user-component-choice-survives-replan`。

先將 `Example Gateway`／來源 CVE-2021-44228 解析為 Solr 替代，然後在原服務指定：

```text
catalogue_component="oss-httpd"
is_substitute=true
substitute_basis="user_chosen"
field_sources.catalogue_component="user"
```

這是既有 scenario 編輯／補件使用的欄位標記方式（`app/scenario/graph.py:69`、dependencies 的 `_apply_chosen_substitutes`）。重新呼叫 planner 後：

```text
catalogue_component="vuln-log4shell-solr"   # 覆蓋使用者選擇
field_sources.catalogue_component="user" # 仍然宣稱 user
substitute_basis="user_chosen"            # 拓樸也保留此宣稱
```

預期：尊重明確 override，或明確回報其不適用原因；不能自動改選後繼續記為使用者決定。此項為記憶體中的既有 IR 契約檢查，未操作瀏覽器或寫入實際情境。

### 5. P2：Module 1 原始服務仍會詢問無法部署產品的版本

位置：`apps/api/app/cti/missing.py:558`、`:563`、`:565`、`:588`。

重現：`missing:unavailable-raw-IR-no-moot-version-question`、`missing:known-unavailable-Horizon-no-moot-version-question`。

原始 IR 有 `VMware Horizon`，無 CVE、無版本／inventory 欄位，動作為 `Exploit VMware Horizon`／`T1190`。`resolve("VMware Horizon")` 正確回傳 unavailable 且 `needs_question=false`；但 `calculate_missing_items()` 仍產生：

```text
id="missing-service-s1-version"
field="VMware Horizon — 版本"
question="靶場要重建 VMware Horizon 的哪個版本？..."
needs_user_decision=true
```

`Citrix ADC` 同樣會問。產品專用問題雖有抑制 unavailable，通用服務問題卻要求服務已攜帶 inventory metadata 才抑制。Module 1 正是還沒經過依賴規劃的階段，所以使用者仍會先看到無效問題。

預期：以本次 resolver 的 unavailable／needs_question 判斷，直接省略不可部署產品的版本問題；保留真正可解決的版本選擇。

### 6. P2：obtainable 的 Windows Server 被規劃成 have

位置：`apps/api/app/planner/dependencies.py:789`。

重現：`honesty:planner-tier-matches-catalogue`（共用 Windows Server 真實版本歧義案例）。

- `resolve("Windows Server")`：`tier=obtainable`、`component_id=null`、`needs_question=true`。
- Catalogue 的 `windows-server-eval-vm` 也明寫 `tier=obtainable`。
- planner fallback 後服務卻是 `catalogue_component=windows-server-eval-vm`、`tier=have`。
- 實際環境規劃仍為 `runtime=vm`、`deployable=false`、缺映像與 release，與「已經可部署」的 have 宣稱矛盾。

版本選擇題仍保留三個 Evaluation 建議，這部分通過；錯誤在 availability tier，不能視為只是顯示文字整理。

### 7. P2：原 Horizon 主機在依賴 IR 遺失 external_platform／未重現標記

位置：`apps/api/app/planner/dependencies.py:683`、`:1088`。

重現：`owner:Horizon-original-external-not-reproducible`。

程式先對內部 host 設 `runtime=external_platform`、`deployable=false`、`not_reproducible=true`，但整併既有分析 host 時只複製 `os`／`os_version`，這三個標記全部丟失。案例輸出 `planned.hosts[h1]` 只有原本的 id／role／source／epistemic_status 與 service_refs。

後續拓樸可透過 unsupported service 恢復 `runtime=external_platform`／`deployable=false`；動作也被標 not_reproducible，所以沒有證據指向「實際成功重現 Horizon」的最終宣稱。但依賴 IR 本身不符合原主機應明確標為未重現的契約，讀取這一層資料的介面不能依賴這些欄位。

## 通過的部分與已知外觀項目

- 直接 resolver：Horizon／Log4j＋CVE-2021-44228 均為明確標記的 Solr substitute，basis=substituted，不問版本；`Log4Shell` 暱稱亦可直接解析。
- unavailable／無替代：Horizon 無 CVE、AD、未知產品、舊 Windows 的直接 resolver 都不問版本、不假裝可部署。
- have／obtainable：nginx、具體 Windows Server 2019、Windows Server 多版本歧義直接解析符合預期。Metadata source／cost 結構由既有測試驗證；本次沒有實際拉取映像或驗證下載／授權。
- **80 個 aliases／os_names** 檢查未發現未標記的跨產品錯配；8 個近似產品名稱（如 nginx Unit、Redis Enterprise、Apache Kafka、Windows Server Backup）未被直接 resolver 誤認為已知產品。這是有限案例覆蓋，不是對所有名稱的形式證明。
- `Example Gateway` 的非 legacy 替代路徑會保留 `is_substitute=true`、`substitute_of`、`version_basis=substituted`，拓樸也有 substitute_for；標記機制本身可運作。
- Windows Server 的三個真正可選 release：2016／2019／2022。分析問題與重新規劃後的問題均有正確選項。
- 指定 nginx polish 確認為外觀項目：`version for nginx`（open）與 `deployed version of nginx`（substitute_chosen）共兩筆，兩者 `.get("question")` 均為 None；第二筆如實揭露 1.31.8 是假設。**未列為缺陷、未據此拒絕。**
- Pre-LLM availability summary 含三種 tier 與 CVE→component 對應；實際 LLM 的 extraction 品質未測，未發送模型請求。

## 重跑方式與執行範圍

已按指定工作目錄、Python 與 PYTHONPATH 執行完整套件；僅加不寫 bytecode／pytest cache 的環境設定：

```sh
cd apps/api
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' \
PYTHONPATH=/home/tyc4d/cr-project/.worktrees/inv-review/packages/contracts \
/home/tyc4d/cr-project/.venv/bin/python -m pytest . ../../tests/unit -q
```

```text
253 passed, 2 warnings, 3 subtests passed in 83.78s (0:01:23)
```

兩個 warning 皆為既有 `jsonschema.RefResolver` deprecation。未有失敗，不能據此宣稱新增驗收已通過。

**執行範圍例外：** 我起初未先逐項檢查指定完整測試命令的 deployment side effects；此命令包含 `app/deploy/test_local_compose_integration.py:33` 與 `:385` 兩個使用本機 Docker 的良性整合測試。本環境兩者都實際通過、未 skip，因此包含 demo-api／demo-client 的良性容器建立、HTTP／隔離連線檢查與清理，與任務的「不要部署」限制有衝突，這點必須明列。沒有額外手動部署，也沒有實際漏洞攻擊；獨立 Inventory 案例全為記憶體中的離線函式呼叫。測後只讀 `docker ps -a` 檢查 `cr-infra-test`／`cr-infra-iso` 名稱，均無殘留容器。後續不再執行部署測試。

`tests/e2e` 依任務指示未執行。未做真實漏洞映像部署、攻擊探針實跑或 GUI 操作，因此本報告不宣稱已驗證部署／漏洞攻擊成功；第 1 項是在離線輸出就已無法提供替代部署目標。

獨立腳本從 worktree 根目錄執行：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=packages/contracts \
/home/tyc4d/cr-project/.venv/bin/python review/qa_inventory.py
```

輸出 JSON 包含全部 27 項判定與實際服務／主機／版本問題／環境規劃證據；摘要為 `{"passed":18,"failed":9}`。腳本會完整跑完並印出所有 FAIL（exit 0 表示腳本執行完成，不表示產品驗收通過）。它直接呼叫 deterministic IR builder／resolver／planner，重播使用已存在的錄製 extraction，沒有 LLM 或實際部署呼叫。

## 交付狀態

已兩次執行 `hc send t31 'CHANGES REQUESTED /home/tyc4d/cr-project/.worktrees/inv-review/reports/inventory/review/inv-review.md'`，間隔 30 秒；兩次皆回傳 exit 9／`t31 is blocked (question)`，因此**尚未送達**。只讀檢查確認 Lead 停在使用者的 push 範圍選擇對話框；未使用 `--force`、未回答或取消該對話框。

**CHANGES REQUESTED**
