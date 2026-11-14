# frontend-eng 過夜報告（持續更新）

分支 `agent/frontend-eng`。自己的站台：API 127.0.0.1:8131、Vite 127.0.0.1:5181、`CR_DATA_DIR=<worktree>/.data`。未動共用 QA 站台。

## 批次 1（commit 09fd549）

| QA 編號 | 問題 | 修法 | 驗證 |
|---|---|---|---|
| EI-04／admin M1 | 缺失頁「接受未知」備註標選填，留白送出回 422 | 留白時前端送出明確文字「接受未知（使用者未填寫備註）」（後端要求 text 至少 1 字，且會把它存成 resolution）；表單下方加一行說明哪種模式必填／選填 | e2e 通過；截圖 `evidence/frontend-eng/01-accept-unknown-blank-note.png` |
| EI-04 附帶 | 422 以原始 `string_too_short / body.text` 顯示 | `ApiNotice` 把 FastAPI 欄位驗證錯誤轉成白話（「內容」不能留白），並說明資料未儲存 | 只有 typecheck；**沒有 e2e 覆蓋**（介面已無會送空白的路徑） |
| EI-11／admin M2 | 拓樸核准後、IaC 未生成時「啟動」可按，按了才失敗並留下 failed 紀錄 | 部署頁讀取 IaC 狀態：未生成或報告判定不可部署時停用「啟動」，顯示原因與「前往 IaC 預覽」 | e2e 通過；截圖 `02-deploy-blocked-no-iac.png` |

改動檔：`apps/web/src/pages/MissingPage.tsx`、`DeployPage.tsx`、`components/ui.tsx`；新增 `apps/web/e2e/qa-fixes.spec.ts`、`e2e/seed-scenario.py`、`e2e/fixtures/seed-scenario.json`。

測試指令（在 `apps/web`）：

```sh
CR_E2E_API_PORT=8131 CR_E2E_WEB_PORT=5181 CR_DATA_DIR=<worktree>/.data CR_VENV=/home/tyc4d/cr-project/.venv \
CR_ENV_FILE=/home/tyc4d/cr-project/.env CR_BUDGET_HARD_CAP_USD=5 CR_BUDGET_STOP_NEW_USD=4 npx playwright test qa-fixes
```

實際輸出：`3 passed (3.5s)`；`npx tsc --noEmit` 通過。完整 `npm run e2e`（含真實 LLM 的 full-flow）**尚未跑**。

測試方式說明：`qa-fixes` 不呼叫 LLM。情境由 `seed-scenario.py` 透過後端 `store.create` 寫入，內容是一份真實分析結果的第 1 版（CL0P MOVEit，缺失項全為待補）。只略過分析步驟，其餘都打真實 API，沒有 mock。

## 批次 2（commit 見 git log「explain blocked states…」）

| QA 編號 | 問題 | 修法 | 驗證 |
|---|---|---|---|
| EI-09 | 導覽列缺失數比缺失頁多 1 | 導覽改用與頁面相同的「卡片」計數（相同問題合併） | e2e 通過。注意：測試用情境沒有可合併的重複問題，只驗證兩數相等，未實際重現「多 1」 |
| admin M3 | 已選情境時「＋ 新建情境」只開啟現有匯入內容 | 首頁按鈕明確要求空白表單 | e2e 通過 |
| EI-06／ux M | 依賴頁初次進入看不出尚未分析 | 未分析時顯示「尚未執行依賴分析」警告，按鈕為主要按鈕「執行依賴分析」 | e2e 通過 |
| Lead 轉達／ux High／admin | 行為與主機參照不一致→服務被排除、零連線、IaC 拒絕 | 依賴／拓樸／IaC 頁顯示「主機參照不一致」說明：哪些行為指向未指明主機、哪些服務沒有主機、能在哪裡改；拓樸零連線另有警告；規劃備註中文化（保留英文原文） | e2e 通過；截圖 03、04 |
| EI-10 | IaC 錯誤是多層英文原始欄位 | 生成被拒時顯示白話原因清單＋每台主機對應表，原始報告收合 | e2e 通過；截圖 05 |
| EI-10／admin M5 | 部署紀錄失敗原因只有「—」 | 由紀錄的 reason／error／stderr／結束代碼取原因 | **未以真實失敗紀錄驗證**（只有 typecheck）|
| EI-11 | 無資源時 down 可按、未部署時驗證可按 | 沒有 IaC 也沒有容器時停用 down；部署狀態非 running 時停用「執行驗證」並引導到部署頁 | e2e 通過；截圖 06 |

`npx playwright test qa-fixes` 實際輸出：`6 passed (10.9s)`；`npm run build` 成功。

### 重要：這一項前端只能說明，不能解決（需後端）

用測試情境（CL0P MOVEit 第 1 版）在自己的 API 實測：

1. 執行依賴分析後，主機由 1 台（`host-target`）變 3 台（多出 `unknown`、`host_target`），服務 `svc1` 仍不屬於任何主機。
2. 把 4 個行為的目標主機全部改成 `host-target` 並儲存，再重新分析：結果相同，`svc1` 仍未歸屬；拓樸 0 連線。

也就是說，**目前沒有任何畫面操作能把服務歸到主機**，使用者照著改也到不了可部署。前端提示已如實寫出這個限制，沒有寫成「照做就會好」。

## 給 Lead／後端的事項

- 「接受未知」的 text 契約：目前由前端代填固定備註。若後端改成 `accepted_unknown` 可不帶 text，前端可移除代填（`UNKNOWN_DEFAULT_NOTE`）。
- 關係來源被洗成使用者（EI-01）：Lead 告知根因在後端且已修，前端未改。
- 依賴分析會產生重複主機（`host-target`／`host_target`／`unknown`），且不會把服務歸到主機；修正行為的目標主機後重新分析也無效（重現步驟見批次 2）。需要 scenario-eng／planner 處理，或提供「指定服務所在主機」的 API，前端才能做對應操作。
- 流程儲存新版本後，舊拓樸仍顯示「已核准」、啟動可用（admin 里程碑 5）。前端無法判斷規劃是否過期：`environment_plan` 沒有記錄它是由哪個 `ir_version` 產生的。若後端在規劃上加這個欄位，前端可顯示「規劃已過期，請重新規劃」。**此項未修。**
- EI-05（補件沒有套用到主機規格）、EI-02（主機角色被合併）、EI-07／EI-08（關係無依據、引句逐字標示）屬分析／後端資料問題，前端未遮掩、未處理。

## 批次 3（commit 1935a6d）

- 缺失卡片沒有中文問題時，標題改為「類別相關資訊：<原始欄位名>（後端未提供中文問題…）」，不再只顯示看不出在問什麼的佔位字（qa-ux 里程碑二）。未 e2e 驗證（測試情境沒有這種項目）。
- 缺失頁在尚未執行依賴分析時提示「清單可能還不完整」（qa-ux Medium）。
- 部署 up／down 失敗時只顯示一次原因＋結束代碼，完整輸出收合（qa-admin 里程碑 9：同一段 stderr 重複多次把目前狀態擠到下面）。**未以真實失敗驗證**。

## 批次 4

- 部署頁：從未生成 IaC 的情境，狀態原本顯示紅色 `error`＋英文 `compose file has not been generated`，第一次使用的人會以為壞了。改為灰色「未部署（尚未生成 IaC）」與一句中文說明；健康檢查顯示「未檢查（未部署）」，不寫成健康也不寫成故障。只在後端回報的正是這個原因且沒有任何容器時才套用，其他 error 照原樣顯示。
- 部署紀錄原因：以**真實失敗紀錄**驗證通過（對自己的 API 送出一次真的會失敗的 down，頁面顯示「尚未生成 IaC（沒有 compose 檔）」）。截圖 07。批次 2 表中該項「未驗證」已補上。
- 流程頁 1280×720 展開設計檢查的重疊（qa-ux）：設計檢查清單改為依內容高度、矮螢幕上限 18vh，並在展開時隱藏小地圖。**部分改善**：圖例與縮放列不再蓋住節點（截圖 08），但畫布縮小後不會自動重新置中，節點可能被上方工具列遮到一部分，需按「適合畫面」；發現很多筆時清單仍會佔 18vh。
- `qa-fixes`＋`motion`：10 passed；`tsc`、`npm run build` 通過。

觀察到但沒有處理（列給 Lead 判斷）：流程頁的設計檢查對「4 個行為的目標主機都是 unknown」顯示「沒有發現問題／通過」。加一條檢查規則屬於新增檢查項目，我沒有自行加。

## 批次 5（commit 12bdad5）

| QA 編號 | 問題 | 修法 | 驗證 |
|---|---|---|---|
| UX-03 | 後端 severity=major，畫面一律顯示「次要」 | 所有項目嚴重度相同時，標籤沿用後端的字，只用影響步驟數排序 | e2e 通過；截圖 09 |
| UX-04 | 程式放的佔位主機被寫成「原文已知」 | 後端標 supported 才寫「原文已知」，否則寫「系統推定（原文未證實）」 | e2e 通過；截圖 09 |
| UX-02 | 英文的缺失原因被藏起來 | 英文原因照樣顯示，標明是後端英文原文 | 無 e2e |
| UX-05 | 按下一步後停在前一頁的捲動位置 | 換頁時主內容捲回頂端 | e2e 通過 |
| UX-06 | 矮視窗展開設計檢查後控制項蓋住節點 | 視窗高度 ≤ 800 時，設計檢查開合後自動重新置中 | 截圖 08 人工檢視：節點不再被圖例或工具列遮住。**只測了「1280×720 進頁後展開」，沒測 QA 的「先展開再縮小視窗」** |
| ADM-06 | 部署歷史點列看不到細節 | 紀錄列可展開「完整輸出」（stderr／stdout 原文） | 無 e2e（測試用的失敗紀錄沒有輸出內容） |
| ADM-07B | healthy 的意思不清楚 | 健康檢查下方說明：只代表容器在執行、未回報不健康，服務是否可用看驗證報告 | 無 e2e（需要已部署的環境） |

## 批次 6（配合 scenario-eng 後端新欄位；本分支已合併 agent/scenario-eng 887ef7b，merge 080e381）

- 缺失卡片：回答前說明「你填的內容會原樣寫入〈主機 X 的作業系統〉」，回答後顯示「已寫入情境資料：…」或「只保留為文字，沒有寫入」及後端給的原因（對應 EI-05）。e2e 通過並比對後端實際儲存值；截圖 11、12。
- 依賴頁：目錄沒有的軟體標「目錄無此元件」並有整頁提示；服務的所在主機也讀後端新的 `host_ref`。e2e 通過；截圖 10。
- 拓樸：新增 5 種規劃備註的中文（推定入口主機、無外部可達主機、目錄無法部署、VM 尚不可部署、行為路徑無目的埠）。無 e2e。
- 分析頁關係表：顯示後端的 `epistemic_reason`（為何不標成原文支持）。無 e2e。
- scenario-eng 列的前端待辦中**尚未做**：`source_certainty=hedged`、`exposure_basis`、`quality.excluded_non_attacker_actions` 的顯示。

`qa-fixes`＋`motion`：13 passed；`tsc`、`npm run build` 通過。

## 完整 `npm run e2e` 歷程（第 1～3 次未通過；最新結果見「批次 7」）

| 執行 | 後端 | 結果 |
|---|---|---|
| 第 1 次 | 本分支原本的後端（= main d4a5482） | 8 passed／1 failed／1 未執行 |
| 第 2 次 | 依 Lead 指示合併 `agent/scenario-eng`（8aa5246）後，merge commit ec09258 | 7 passed／2 failed／1 未執行 |
| 修正自己的測試後只跑 `qa-fixes motion` | 同上 | 8 passed |

- 兩次都失敗的是 `full-flow` 的 `topology-plan`：斷言「開通連線 > 0」，實際 0。合併後原因變了：不再是「服務沒有主機歸屬」，而是規劃備註寫「服務 web service (s1)、database service (s2) 埠號未知，預設不通」「已確認依賴 r4、r5 無法唯一對應目的服務埠」。IR 中 `h1`、`h2` 的 `service_refs` 仍是空的，兩個服務沒有 port。情境 `scn_9da8286ecc8f`（在我的 `.data`）。因此「部署、驗證、報告、清理」那一段**沒有執行**。
- 我沒有修改 `full-flow.spec.ts` 的斷言。
- 第 2 次多出的失敗是我自己的測試：新後端在補件回應裡會新增一筆後續問題（`missing-service-svc1-version`），所以「待補充數 −1」不成立。已改成比對後端實際狀態（該項為 accepted_unknown、頁面數字等於後端 open 數），不是放寬成功條件。
- 合併後後端單元測試：`93 passed`。
- **第 3 次**（合併 scenario-eng 887ef7b 後）：12 passed／1 failed／1 未執行。full-flow 這次通過拓樸（2 條連線），改在 IaC 步驟失敗：後端拒絕生成，`h1`、`h2` 找不到可用映像，因為 demo 報告裡的「web service／database service」在目錄中沒有對應元件（`no_component`），新後端不再自動用 nginx／postgres 頂替。部署段仍未執行。
- 我用 API 試了「選替代方案」這條路：對 `planner_dep_software-web-service`／`-database-service` 送出 substitute_chosen（nginx、PostgreSQL）後重新分析，會多出 `svc-oss-nginx`、`svc-oss-postgres` 兩個使用者服務，但它們沒有歸屬主機、`is_substitute=false`，原本的 s1／s2 仍是 `no_component`；重新規劃後備註寫「沒有主機歸屬的服務被排除」，IaC 照樣 422。**也就是目前 demo 情境沒有任何畫面操作能走到可部署**，full-flow e2e 在這個後端上無法通過，需要後端決定替代方案如何掛回原主機。我沒有改 full-flow 的斷言。
- 合併後後端單元測試：122 passed／**1 failed**（`tests/unit/test_planning_consistency.py::DifferentProductsAreNotAliases::test_vendor_word_inside_another_product_name_does_not_match`，`no_component` 為 None）。這是合併後在我的分支上的結果，沒有在 scenario-eng 自己的分支上重跑確認。
- 另外觀察到：full-flow 測試把第一張缺失卡（作業系統題）填了一句無關的說明文字，新後端照樣把整句寫進 `h1.os`。前端已加上「內容會原樣寫入該欄位」的提示，但後端不檢查內容是否像作業系統。
- 證據：`reports/overnight/evidence/frontend-eng/full-e2e/`（兩次的輸出、run-log、失敗截圖）。
- 注意：本分支現在含 scenario-eng 的提交（merge ec09258），整合時請留意。

## 批次 7（commit 47dc5d2）＋最新完整 e2e

- 分析頁：行為若被後端標為 `hedged` 顯示「原文語氣不確定」；列出「未納入攻擊流程的行為」（防守方動作）與被丟棄的 unknown 佔位主機數。**這三項沒有用真實資料看過畫面**：我在自己的站台對 CISA 樣本做了一次真實分析（約 $0.06），結果 hedged、excluded 都是空的。
- 分析頁關係的「判定依據」：同一次真實分析有 7 條，畫面顯示 7 條（截圖 14，一次性檢查，沒有留成常駐測試）。
- 拓樸：推定入口主機顯示「推定入口・待確認」、不可部署主機顯示「不可部署」。前者 e2e 通過（截圖 13）；後者無 e2e。
- `full-flow.spec.ts` 的報告步驟原本找標題「擬真度（fidelity）」，頁面是「擬真度」；已把測試改成找「擬真度」（Lead 指示，字樣對齊，其餘斷言未動）。

### 合併 agent/scenario-eng e0484e8（含 df080a2）後，merge 4322fd6

| 執行 | 結果 |
|---|---|
| 後端 pytest | 126 passed |
| `npm run e2e` 第 4 次 | 15 passed／1 failed。full-flow 兩段都通過（真實部署、驗證、清理）。失敗的是我的「導覽列缺失數一致」：整頁空白、標題沒出現 |
| 該項單獨重跑 5 次 | 5 passed |
| `npm run e2e` 第 5 次 | **16 passed，exit 0** |

- 那一次空白頁**原因沒有查明**，只知道無法穩定重現（6 次中 1 次）。更早 `motion` 也出現過一次單次失敗、重跑通過。請當作已知的偶發問題，不是已解決。
- 第 5 次的驗證層級（後端回報）：`env_build=PASS`、`behavior_repro=PASS`、`full_chain=PARTIAL`。完整攻擊鏈不是 PASS。清理後沒有 `cr-demo-scn*` 容器。
- `motion.spec.ts` 取「最新的情境」來測；最新的若是大型情境（我那次 17 步的真實分析）它會失敗。這是測試對資料的依賴，我沒有改它。
- 第 1～3 次記錄的阻塞（替代方案無法掛回主機、1 項單元測試失敗）：demo 流程在這版後端已能部署、單元測試已全過；但「手動選替代方案」那條路我沒有在新版重測。
- 證據：`reports/overnight/evidence/frontend-eng/full-e2e/`（run4、run5 的輸出與 run-log）。

## 尚未完成

- 沒有 e2e、也沒用真實情況看過畫面的：422 白話訊息、部署 up／down 失敗的精簡顯示、部署紀錄「完整輸出」展開、健康檢查說明、hedged／被排除行為／丟棄佔位主機、主機「不可部署」標記、英文缺失原因、缺失卡片無中文問題時的標題。
- 流程儲存新版本後，舊拓樸仍顯示「已核准」：需後端在規劃上記錄來源版本，前端未修。
- 設計檢查對「目標主機是 unknown」不提醒：屬新增檢查項目，未自行加。
- UX-06 只測了「1280×720 進頁後展開設計檢查」，沒測「先展開再縮小視窗」。
- 需後端／產品：手動選替代方案後的服務歸屬（未在新版重測）、ADM-01 主機埠（main 已合 infra 動態埠，未重測）、ADM-02／03、ADM-08。

## 目前狀態

- 分支 `agent/frontend-eng` 含 scenario-eng 的提交（merge ec09258、080e381、4322fd6），整合時請留意。
- 自己的 API(8131)／Vite(5181) 收工時關閉；e2e 部署的容器已由測試清理。OpenAI 花費（自己站台的本地估計）約 $0.1，上限設 $5。
