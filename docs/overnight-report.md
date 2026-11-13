# CyberRange 夜間建置報告（2026-11-14）

T0 04:55 CST 起。以下只講事實，沒驗證過的不寫成已驗證。

## 現在能做什麼（一句話）

從一份情資報告，一路跑到**在本機隔離環境真的把三個容器部署起來、做無害驗證、產出三層忠實度報告**，全程經過預算管控的 LLM，花費約 **US$0.01**。

## 四個最重要的答案

**能做什麼**：情資匯入 → LLM 分析（攻擊行為、時間/依賴關係、原文引用、缺失項目）→ 依賴與拓樸規劃 → 生成 Docker Compose → 本機隔離部署 → 無害驗證 → 報告。八個模組的後端都接得起來，資料用同一份 Scenario IR 串連。

**哪些真的測試成功**：整條後端流程用真實資料與真實 LLM 跑通了（證據在 `docs/e2e-evidence/`）。25 項自動化測試全過，含一個「真的開 Docker 容器再關掉」的整合測試。

**怎麼打開試用**：見下方「啟動方式」。前端 10 頁都做好、能連上後端，但我**還沒**在瀏覽器逐頁點過，所以前端標為「已實作、未完整驗證」。

**還有哪些明顯問題**：見「尚未完成/已知問題」。最重要三點：(1) 攻擊者→Web 的連線與無害行為驗證通過，但 Web→DB 的橫向移動這一段標記為 NOT_TESTED（沒造假）；(2) 部署的是**無害 HTTP 替身**，不是真的 nginx/postgres，忠實度報告有明講；(3) 前端未做瀏覽器逐頁測試。

## 八個模組狀態

| # | 模組 | 狀態 | 證據 |
|---|---|---|---|
| 1 | 情資報告分析 | ✅ 已實作且實際驗證 | 真實 LLM 跑出 4 個 supported 攻擊行為、temporal+dependency 關係、引文核對、缺失清單 |
| 2 | 缺失項目補齊 | ✅ 已實作且實際驗證 | 缺失清單程式算出；補充端點（指定項目與自由補充）皆通過 |
| 3 | 攻擊流程編輯 | 🟡 後端已驗證，GUI 未逐頁測 | action/relation CRUD、版本遞增、關係可人工確認（API+單元測試通過）；前端編輯器已做未browser測 |
| 4 | 軟體依賴分析 | ✅ 已實作且實際驗證 | 由主機角色長出服務、對應開源映像 catalogue、替代元件標記 |
| 5 | 拓樸分析 | ✅ 已實作且實際驗證 | 內/外網段、連線理由、預設 deny；attacker 只連對外主機，內網 DB 不被直連 |
| 6 | IaC 生成 | ✅ 已實作且實際驗證 | 由環境計畫生成固定版本、非 privileged、無密鑰的 compose |
| 7 | 部署 | ✅ 已實作且實際驗證 | 真的 `docker compose up/down`，3 容器健康，cr-demo- 前綴、僅限本機 |
| 8 | PoC 驗證 | ✅ 已實作且實際驗證 | 三層 env_build=PASS / behavior_repro=PARTIAL / full_chain=PASS，忠實度標出替身 |
| — | GUI (10 頁) | 🟡 已實作、未完整驗證 | typecheck/build 通過、dev server 經 proxy 連得上後端；未做瀏覽器逐頁點擊 |

「實際驗證」指後端用 curl/API 真的跑過；不代表每個功能都經過 GUI 操作。

## 使用的架構

- 後端 Python + FastAPI + SQLite（`apps/api`）。前端 React + TS + Vite（`apps/web`）。
- 共用契約 `packages/contracts/schemas`，中央結構 Scenario IR 串連模組 1–8。
- 所有 OpenAI 呼叫經 `apps/api/app/llm` 預算管控（硬上限 $50，估到 $45 停新任務，保守估價提早硬停）。
- 細節：`docs/decisions/0001-architecture.md`、`docs/api-contract.md`、`docs/demo-scenario.md`。

## 啟動方式

```bash
cd ~/cr-project
# 1. 後端（需 .env 內的 OPENAI_API_KEY；8000/8080 被其他程式占用，用 8077）
bash scripts/setup.sh                      # 建 venv、裝依賴（只需一次）
source .venv/bin/activate && set -a && . ./.env && set +a
cd apps/api && CR_DATA_DIR=$PWD/data uvicorn app.main:app --port 8077
# 2. 前端（另一個終端；5173 被占用時自動用 5174）
cd ~/cr-project/apps/web
export PATH=$HOME/.nvm/versions/node/v22.23.3/bin:$PATH
npm install && npm run dev                 # 開 http://localhost:5174
# 3. 一鍵跑完整後端示範（需 Docker）
cd ~/cr-project && API=http://localhost:8077 bash scripts/e2e_demo.sh
```

GUI 操作位置：左側工作流由上到下 10 頁（首頁→匯入→分析→缺失→流程→依賴→拓樸→IaC→部署→報告）。

## 完整操作示範（已實際跑過，證據 `docs/e2e-evidence/`）

情資匯入 → 分析（4 行為、關係、引用、缺失）→ 確認依賴關係 → 依賴分析（Web/DB 替身）→ 拓樸（內外網段、attacker→web）→ IaC（3 服務 compose）→ 部署（3 容器健康）→ 驗證（三層）→ 報告 → 清理。

## 測試結果

- `source .venv/bin/activate && PYTHONPATH=apps/api python -m pytest apps/api tests -q` → **25 passed**（含 Docker 整合測試）。
- 端到端：`scripts/e2e_demo.sh` 全程通過，證據已存檔。

## 真實 LLM 測試結果

- 模型 gpt-4.1-mini（便宜檔），`single_pass` 與 `staged` 都跑過真實呼叫。
- `single_pass` 在示範報告上較乾淨（引文核對 1.0、無未支持主張）；`staged` 多抓關係但多出未支持主張。這是**非正式**觀察，不是完成了正式 A/B/C 實驗（參考答案仍只有一人、provisional）。

## OpenAI API 使用量與估計支出

- 估計 **約 US$0.012**，7 次呼叫，全部 gpt-4.1-mini。離線保守估算，非供應商帳單。
- 即時查詢：`GET /api/budget`。此金鑰若也被其他專案使用，那部分無法由本系統控制。

## 尚未完成 / 已知問題

1. **Web→DB 橫向移動**在驗證中為 NOT_TESTED（連線未在計畫中開通）；behavior_repro 因此為 PARTIAL。這是誠實結果，非失敗。
2. **部署的是無害 HTTP 替身**，非真實 nginx/postgres；真實 exploit 完全未執行（忠實度報告標明）。
3. **前端未做瀏覽器逐頁測試**；pages 能連後端，但互動流程未人工走過。
4. 模組 1 的方法比較只有非正式試跑，**沒有**完成正式、雙人標註的基準實驗。
5. 仍是單機、公開英文報告的示範；STIX 1.x、中文、掃描檔、真實 STIX 輸入未測。

## 需要你決定的產品問題

1. 要不要把「真實軟體替身」升級成真的跑某些開源服務（例如真 nginx），還是維持最小無害替身？
2. Web→DB 這類多跳橫向移動，要做到自動開通＋驗證，還是維持「人工確認後才開」？
3. 下一步優先：把前端逐頁打磨到可用，還是先把模組 1 的正式方法比較實驗做完？
