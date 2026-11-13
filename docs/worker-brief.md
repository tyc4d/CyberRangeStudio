# Worker 共用須知（開工前讀這份 + AGENTS.md + packages/contracts/README.md + docs/decisions/0001）

你在自己的 git worktree 裡。只改你被指派的檔案，**不要改**：
`packages/contracts/`、`apps/api/app/main.py`、`apps/api/app/config.py`、
`apps/api/app/store.py`、`apps/api/app/llm/`、以及其他 Worker 負責的 router 檔。
需要改契約就停下來回報 Lead，不要自己改。

## 環境

- Python venv 已建好在 repo 根 `.venv`（所有 worktree 共用同一個 repo 的 .venv：用 `source /home/tyc4d/cr-project/.venv/bin/activate`）。
- 已安裝：fastapi、uvicorn、openai、tiktoken、jsonschema、stix2、pyyaml、httpx、cr-contracts（editable）。
- 需要新套件：先裝進該 venv，並把套件名加到 `apps/api/requirements.txt`，回報 Lead。
- 啟動 API 自測（挑**沒被占用**的埠，8000/8080 已被別的程式占用，用 8077 或更高）：
  `cd apps/api && CR_DATA_DIR=$PWD/data OPENAI_API_KEY=... uvicorn app.main:app --port 8077`
- 跑測試：`cd /home/tyc4d/cr-project && source .venv/bin/activate && python -m pytest tests -q`

## 資料契約

- 中央結構 Scenario IR 定義在 `packages/contracts/schemas/scenario-ir.schema.json`。
- 用 `from cr_contracts import iter_errors; iter_errors('scenario-ir', ir)` 驗證你的輸出（空清單=通過）。
- 你產生或修改 IR 後，**必須**自測通過 schema 驗證。
- 關鍵不變量：`epistemic_status`(supported/inferred/absent/insufficient)、relation `kind`(temporal/dependency 不可混)、
  每項有 `source`(llm/user/stix/program)、LLM 項目要帶 `evidence_refs`。

## LLM 與預算（硬規則）

- **只能**透過 `from app.llm.client import complete` 呼叫模型。不要自己 import openai、不要碰金鑰。
- `complete(messages, purpose=..., model=None, tier='task', response_format=..., agent='你的名字')`。
  便宜任務用預設（gpt-4.1-mini）；困難分析傳 `model='gpt-5.1'`。
- 開發自測**最多**跑 1 份短報告、少量呼叫，避免燒預算。超過會被 Budget guard 擋下（BudgetExceeded），這是預期行為，不要繞過。
- 呼叫失敗要保留錯誤、可重試，**絕不**偽造模型結果。

## 隔離部署（模組 6/7/8 專用）

- 只用本機 Docker。容器、網路、volume 名稱一律加前綴 `cr-demo-`，方便辨識與清理。
- 對外埠用 42000–42999 範圍，避免衝突。內部網路設 `internal: true`。
- **禁止**：關閉主機安全機制、動別的容器、`docker system prune`、對外部目標掃描或攻擊。
- 模組 8 只做**無害檢查**：服務是否起來、主機間預期連線是否通、依賴是否存在、無害示範行為（如容器間一次 HTTP 請求拿到預期回應）。不寫、不跑真正的漏洞利用。

## 完成條件

- 你的部分有可執行的真實功能（不是空殼），自測通過，並寫幾行怎麼測、結果如何。
- Codex：你不能 commit（沙盒），改完檔案後回報 Lead 代為提交。
- Claude：在自己的分支 commit。
- 回報用 `hc send <Lead>`，長內容寫檔案只給路徑。
