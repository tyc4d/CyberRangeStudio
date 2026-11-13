# API 契約（前後端一致，Lead 鎖定 2026-11-14）

所有路徑集中於前端 `apps/web/src/lib/api.ts`。後端各 Worker **必須**符合下表。
多數寫入端點回傳「更新後的完整 Scenario IR」；若不回，前端會自動重抓 `GET /api/scenario/{id}`。

| 功能 | 方法/路徑 | Body | 回傳 | 負責 |
|---|---|---|---|---|
| 健康 | `GET /api/health` | — | `{status}` | Lead |
| 預算 | `GET /api/budget` | — | 預算摘要 | Lead |
| Scenario 清單 | `GET /api/scenario/list` | — | `[{id,name,created_at,updated_at}]` | sc-plan |
| 取得 IR | `GET /api/scenario/{id}` | — | Scenario IR | sc-plan |
| 存新版本 | `PUT /api/scenario/{id}` | `{ir, note}` | 更新後 IR（ir_version+1） | sc-plan |
| 版本清單 | `GET /api/scenario/{id}/versions` | — | `[{ir_version,note,ts}]` | sc-plan |
| action/relation 編輯 | `POST/PATCH/DELETE /api/scenario/{id}/action` 等 | 視操作 | 更新後 IR | sc-plan |
| 情資分析 | `POST /api/ingest/analyze` | `{input_kind,content,method,name}` | 完整 IR（含 id） | be-cti |
| 補充缺失 | `POST /api/ingest/{id}/supplement` | `{text,targets_missing_item?,status?}` | 更新後 IR | be-cti |
| 依賴分析 | `POST /api/planning/{id}/dependencies` | — | 更新後 IR | sc-plan |
| 元件 catalogue | `GET /api/planning/catalogue` | — | `[...]` 或 `{components:[...]}` | sc-plan |
| 拓樸規劃 | `POST /api/planning/{id}/topology` | — | 更新後 IR（含 environment_plan） | sc-plan |
| IaC 生成/讀取 | `POST /api/iac/{id}/generate`、`GET /api/iac/{id}` | — | `{compose:"<yaml>",report:{...}}` | infra |
| 部署 | `POST /api/deploy/{id}/up`、`/down`；`GET /api/deploy/{id}/status`、`/health` | — | JSON，含 `state`/`containers` | infra |
| 驗證 | `POST /api/validate/{id}/run`、`GET /api/validate/{id}/report` | — | validation-report 契約 | infra |

規則：寫入端點盡量回傳完整 IR。missing_items 直接在 IR 裡（缺失頁從 IR 讀）。
所有 IR 回傳前要通過 `iter_errors('scenario-ir', ir)`。
