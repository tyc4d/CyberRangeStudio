# packages/contracts — 共用資料契約

**唯一真相**：`schemas/*.json`（JSON Schema draft-07）。Python 與 TS 兩端都遵守這些 schema。
改契約要先在這裡改，並通知 Lead（會影響多個 Worker）。

## Schema

| 檔案 | 用途 | 誰寫 |
|---|---|---|
| `scenario-ir.schema.json` | 中央結構，貫穿模組 1–8 | 各模組增補自己欄位 |
| `environment-plan.schema.json` | 模組 5 輸出，模組 6 輸入 | 模組 5 |
| `validation-report.schema.json` | 模組 8 輸出，三層驗證分開 | 模組 8 |

模組 1 的輸出**就是一份 Scenario IR**（填了 actions / relations / evidence / missing_items / quality），
不另外定義 analysis schema。後續模組往同一份 IR 增補。

## 關鍵不變量

1. `epistemic_status` ∈ supported / inferred / absent / insufficient。
2. relation `kind` ∈ temporal / dependency，**不可把時間先後自動當依賴**。
3. 每個項目有 `source` ∈ llm / user / stix / program；LLM 項目要有 `evidence_refs`。
4. 驗證三層 env_build / behavior_repro / full_chain 分開，不可互相冒充。

## 使用

Python：
```python
from cr_contracts import load_schema, validate
validate("scenario-ir", my_dict)   # raises on invalid
```

TS：`src/types.ts` 有對應 interface（手寫，與 schema 對齊）。

## 2026-11-15 新增的選用欄位（皆為 additive，schema 允許額外欄位，舊資料不受影響）

Schema JSON 本身未改；下列欄位已加進 `src/types.ts`，由模組 1/2/4/5 後端寫入。

| 位置 | 欄位 | 意義 |
|---|---|---|
| action | `source_host_ref` | 原文明寫此步驟從哪台主機發動（`target_host_ref` 是作用的主機） |
| relation | `epistemic_reason` | 程式把狀態降級的原因（例如引句存在但沒有陳述先後／相依） |
| host | `name`、`network_placement` | 原文給的主機名稱；網路位置（可由補件寫入） |
| host／service | `field_sources` | 逐欄位來源：`user`（補件）或 `source_quote`（由已驗證引句讀出）；整筆的 `source`／`epistemic_status` 不因補件改變 |
| service | `host_ref`、`port`、`protocol` | 原文明寫的所在主機與連接埠 |
| service | `no_component`、`matched_text`、`supplement_ref` | catalogue 無對應；觸發比對的原文字眼；由哪則補件產生 |
| missing_item | `target`、`applied_to`、`write_back` | 答案應寫回的欄位；實際已寫回的欄位；未寫回的原因 |
| quality | `dropped_placeholder_hosts`、`excluded_non_attacker_actions` | 被丟棄的「unknown」假主機數；被排除在攻擊流程外的防守方行為 |
| environment_plan.hosts[] | `exposure_basis` | `stated`（原文或使用者指定）／`inferred_entry_point`（推論的入口，需人工確認） |
| environment_plan.hosts[] | `deployable: false`、`runtime` | catalogue 無法部署的元件，不標成 real／substitute |
