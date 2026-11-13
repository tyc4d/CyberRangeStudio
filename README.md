# CyberRange

全新開始的 CyberRange 專案。目前在產品設計階段，尚未決定程式語言、框架與系統架構。

## 現況

- 產品目標與待確認問題：見 [`docs/product-questions.md`](docs/product-questions.md)
- 已核准的開發範圍：**無**（核准後才記錄於 `docs/approved-scope.md`）

## 參考資料

`~/cr-research-m1/research` 有兩份先前的研究（CTI 轉 STIX、LLM 輸入格式比較）。
只當參考，不視為正確結論：對照答案僅一人標註，LLM 實驗也沒有實際跑過。

## 團隊規則

人與 Agent 的分工、協作方式見 [`AGENTS.md`](AGENTS.md)。

## 啟動

完整說明見 [`docs/overnight-report.md`](docs/overnight-report.md)。速記：

```bash
bash scripts/setup.sh                                   # 一次性：建 venv、裝依賴
source .venv/bin/activate && set -a && . ./.env && set +a
cd apps/api && CR_DATA_DIR=$PWD/data uvicorn app.main:app --port 8077   # 後端
# 另一個終端：
cd apps/web && export PATH=$HOME/.nvm/versions/node/v22.23.3/bin:$PATH && npm install && npm run dev
# 完整後端示範（需 Docker）：
API=http://localhost:8077 bash scripts/e2e_demo.sh
```

目前進度：[`docs/progress.md`](docs/progress.md)。
