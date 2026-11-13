# 架構決策 0001：第一版技術選型（Lead，2026-11-14 T0）

本文件短，只記決定與理由，細節在各套件 README。

## 決定

- **Monorepo**，分 `apps/`（web、api）、`packages/`（共用邏輯）、`infra/`、`fixtures/`、`tests/`。
- **後端**：Python 3.12 + FastAPI + SQLite。理由：CTI / STIX / IaC 生態都是 Python；SQLite 零設定。
- **前端**：React + TypeScript + Vite，深色主題。圖形編輯用 React Flow（成熟開源）。
- **資料契約**：`packages/contracts/schemas/*.json`（JSON Schema）為唯一真相，Python 用 `jsonschema` 驗證，TS 端對應 interface。所有模組只透過契約交換資料。
- **IaC**：第一版只做 Docker Compose 生成；Terraform 有餘力再評估。
- **LLM**：所有 OpenAI 呼叫一律經 `apps/api` 的 Budget Manager，前端不碰金鑰。

## 核心資料結構

**Scenario IR**（`scenario-ir.schema.json`）是貫穿模組 1～8 的中央結構。
各模組只增補自己負責的欄位，不改別人的：

| 模組 | 寫入 Scenario IR 的部分 |
|---|---|
| 1 情資分析 | `actions`、`relations`、`target_context`、`artifacts`、`evidence`、`missing_items`、`quality` |
| 2 缺失補齊 | 補充 `missing_items` 狀態、`supplements`（使用者/LLM 補充，標來源） |
| 3 流程編輯 | 使用者對 `actions`/`relations` 的增修，`source: user`，存版本 |
| 4 依賴分析 | `hosts`、`services`、`components`（元件 catalogue 對應） |
| 5 拓樸 | `environment_plan`（networks、connections、access_rules） |
| 6 IaC | 由 `environment_plan` 生成 `infra/generated/<scenario>/`，不改 IR |
| 7 部署 | `deployments`（狀態、健康、紀錄） |
| 8 驗證 | `validation`（三層結果 + fidelity） |

## 關鍵不變量（所有 Worker 必守）

1. 每個 action/relation/service 帶 `epistemic_status`：
   `supported`（原文明講）/ `inferred`（推測）/ `absent`（原文沒寫）/ `insufficient`（證據不足）。
2. relation 的 `kind` 分 `temporal`（時間先後）與 `dependency`（真正依賴），不可混。
3. 每個 LLM 產生的項目帶 `source: llm` 與 `evidence`；使用者改的帶 `source: user`。
4. 三層驗證分開：`env_build` / `behavior_repro` / `full_chain`，不可互相冒充。
5. JSON 有效 ≠ 內容正確；LLM 不是正確性的唯一判準。

## 不做

- 不做微服務；單一 FastAPI 程序。
- 不引入多個前端框架。
- 不寫空 Controller / 假頁面。
