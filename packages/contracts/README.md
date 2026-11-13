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
