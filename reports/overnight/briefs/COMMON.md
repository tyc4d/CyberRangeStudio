# 過夜任務共同規則（所有 Worker 必讀）

Lead 位址：見任務訊息中的 `hc send <位址>`。產品定位：把真實攻擊事件轉成**可審核、可部署、可驗證**的資安教學實驗。使用者是資安講師與 CyberRange 管理者。

## 範圍
- 只做既有八模組（1 情資分析、2 缺失補齊、3 攻擊流程編輯、4 軟體依賴、5 拓樸、6 IaC、7 部署、8 PoC 驗證）及其整合、測試、修復。不新增第九模組、不改產品定位、不改安全隔離界線。遇到這類決策：寫進你的報告「需產品負責人決定」，繼續其他工作。
- `~/cr-research-m1` 唯讀參考。不得刪除未提交工作、不得動不屬於本專案的 Docker 容器／埠（主機上 fm26-*、attack-flow-*、8000/8080/5173 是別的專案）。

## 誠實規則（違反即退件）
- 不得為單一測試案例硬編碼結果；不得把驗證邏輯改成固定回傳成功；不得用 mock 冒充真實部署／驗證。
- 來源分級必須分開：SOURCE_SUPPORTED / EXTERNAL_ENRICHMENT / USER_SUPPLIED / ASSUMED·SUBSTITUTED / BLOCKED·UNKNOWN。
- 驗證結果做不到就標 PARTIAL / NOT_TESTED / BLOCKED，不假裝 PASS。容器啟動 ≠ 攻擊鏈可用。
- 安全：PoC 只能在本機隔離容器／VM 內、對本地實驗目標執行；不掃公網、不打外部主機、不在宿主機直接跑不可信漏洞程式、不用真實外洩憑證。
- 回報如實：測試沒過就說沒過，沒做就說沒做。

## 工作方式
- 只改自己 Worktree；只改「檔案所有權」列出的路徑。需要改別人的檔案或共用檔（`packages/contracts/**`、`apps/api/app/store.py`、`apps/api/app/main.py`）時：做最小修改並在報告中逐一列出，或回報 Lead 協調。
- Claude Worker 在自己分支 commit（小步、訊息清楚）。Codex 不能 commit，留檔案即可。
- Python：用主庫 venv `/home/tyc4d/cr-project/.venv/bin/python`（不要另建）。測試：在 worktree 根目錄 `PYTHONPATH=apps/api /home/tyc4d/cr-project/.venv/bin/python -m pytest apps/api tests -q`（基準：39 passed）。
- Node：`export PATH=$HOME/.nvm/versions/node/v22.23.3/bin:$PATH`；worktree 沒有 node_modules，前端相依可用 `/home/tyc4d/cr-project/apps/web/node_modules`（symlink 進 worktree 的 apps/web 即可，勿 commit）。
- 共用 QA 站台（main 分支程式，Lead 維護，**不要重啟或關閉**）：前端 http://127.0.0.1:5177 ，API http://127.0.0.1:8077 。
- 要測自己分支的程式就自己起 instance，用分配給你的埠段，並設 `CR_DATA_DIR=<你的 worktree>/.data`。結束時關掉自己起的程序與容器。
- **OpenAI 費用**：全專案硬上限 $50 不得解除。自己的 instance 若載入真金鑰（`/home/tyc4d/cr-project/.env`），必須同時設 `CR_BUDGET_HARD_CAP_USD=5 CR_BUDGET_STOP_NEW_USD=4`。單元測試不得呼叫真實 LLM。
- KVM／libvirt：使用者已在 kvm、libvirt 群組，但現有 shell 尚未生效，需用 `sg libvirt -c "<cmd>"`／`sg kvm -c "<cmd>"`。Windows Server 2022 Evaluation ISO 已在 `/home/tyc4d/cr-images/windows-server-2022-eval.iso`（官方來源，sha256 3e4fa6d8…5325）。
- 不要啟動其他 Agent。

## 回報
- 報告寫到你 worktree 的 `reports/overnight/worker-reports/<你的名稱>.md`（含：做了什麼、改了哪些檔、commit、測試指令與實際輸出、未解問題、需產品決定事項）。證據（log、截圖、trace）放 `reports/overnight/evidence/<你的名稱>/`。
- 完成一個可驗收的里程碑或卡住時：`hc send <Lead> "<一兩句結果> 報告：<路徑>"`。不要等全部做完才回報；每個里程碑回報一次後繼續下一項。
