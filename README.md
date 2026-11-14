# CyberRange

基於生成式 AI 的紅隊場景自動建置與驗證系統。一份情資報告 →（LLM）分析攻擊行為與引用 → 補齊缺失 → 編輯/確認攻擊流程 → 軟體依賴與拓樸規劃 →（人工核准）→ 生成 Docker Compose → 本機/區網隔離部署 → 無害驗證 → 三層忠實度報告。

誠實優先:區分「明文事實/推論/未知」(`epistemic_status`)、temporal 與 dependency 分開、三個驗證層級(env_build / behavior_repro / full_chain)不混淆、替身一定標明、**不跑真實 exploit**。

## 架構

- 後端 Python + FastAPI + SQLite(`apps/api`)。前端 React + TS + Vite(`apps/web`,RTSS studio 風)。
- 共用契約 `packages/contracts/schemas`,中央結構 **Scenario IR** 串連八個模組。
- 所有 OpenAI 呼叫經 `apps/api/app/llm` 預算管控(硬上限 $50,估到 $45 停新任務)。
- 架構決策:`docs/decisions/0001-architecture.md`。本輪變更見 `docs/round2-report.md`。

## 啟動

```bash
bash scripts/setup.sh                                   # 一次性:建 venv、裝依賴
source .venv/bin/activate && set -a && . ./.env && set +a   # 需 .env 內 OPENAI_API_KEY
cd apps/api && CR_DATA_DIR=$PWD/data uvicorn app.main:app --host 127.0.0.1 --port 8077
# 前端(另一個終端):
cd apps/web && export PATH=$HOME/.nvm/versions/node/v22.23.3/bin:$PATH && npm install && npm run dev  # → :5174
```
8000/8080 被其他專案占用,後端用 8077;前端 5173 被占用時自動退到 5174。

## 示範(需 Docker)

```bash
# 內建情資(會真的部署 nginx + postgres + alpine 三容器,再驗證、清理):
API=http://localhost:8077 bash scripts/e2e_demo.sh
# 換成真實公開報告(CISA AA22-320A):
REPORT=$PWD/fixtures/sample-scenarios/cisa-aa22-320a.md OUT=$PWD/docs/e2e-evidence-cisa \
  API=http://localhost:8077 bash scripts/e2e_demo.sh
```
證據分別存在 `docs/e2e-evidence/` 與 `docs/e2e-evidence-cisa/`。

### 部署暴露範圍(`POST /api/deploy/{id}/up`)
- 預設 `{"test_approved":true}`:只綁 `127.0.0.1`,PostgreSQL 用 trust(純內網無密碼)。
- 區網模式 `{"test_approved":true,"expose":"lan"}`:web 與 DB 對同網段開;回應給 `lan_host` 與一次性 `db_password`(scram-sha-256,不入 compose/git)。偵測不到 IP 時加 `"lan_host":"192.168.x.x"`。埠在 `report.host_port_mappings`(42000-42999)。
- 兩種模式都需先通過**拓樸人工核准**(`POST /api/planning/{id}/topology/approve`)。

## 測試

```bash
source .venv/bin/activate && PYTHONPATH=apps/api python -m pytest apps/api tests -q   # 後端 39 passed
cd apps/web && npm run e2e                                                            # 瀏覽器全流程 Playwright
```

## 八個模組與驗收

見 [`docs/progress.md`](docs/progress.md) 的狀態表與 [`docs/round2-report.md`](docs/round2-report.md) 的本輪驗收(真實服務、網路分段、驗證判定、真實報告、可重跑測試)。

## 團隊規則

人與 Agent 的分工見 [`AGENTS.md`](AGENTS.md)。`~/cr-research-m1`、`~/text2redteamscenario` 僅供唯讀參考,不視為正確結論。
