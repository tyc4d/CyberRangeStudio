# GUI 瀏覽器端到端測試結果（Task 3，frontend worker）

日期：2026-11-14　分支：`wt-frontend`　範圍：只改 `apps/web/**`

## 結論

Playwright 開真的 Chromium、只靠點 UI，把整條流程走完並通過：
上傳情資 → 分析 → 補充缺失 → 編輯流程（確認依賴關係）→ 軟體依賴 → 拓樸 → IaC 預覽 →
（確認未核准時不能部署）→ 核准拓樸 → 部署 → 驗證 → 報告 → 清理。沒有任何 mock。

| 執行方式 | 結果 |
|---|---|
| 預設（沿用已在 8077 的後端） | 2 passed，約 31 秒 |
| 由本 worktree 自己啟動後端（`CR_E2E_API_PORT=8177`，真實 LLM 呼叫，未命中快取） | 2 passed，約 42 秒 |
| 模擬 Docker 不可用（假的 `docker` 指令回傳失敗） | 前半 passed；部署段 **skipped**（不是 passed） |

驗證層級（由後端回報、頁面顯示一致）：`env_build=PASS`、`behavior_repro=PARTIAL`、`full_chain=PASS`。
`PARTIAL` 是後端的誠實結果（db 的行為檢查為「未測」），測試只要求 env_build 為 PASS 且沒有任何 FAIL。
清理後以 `docker ps -a` 確認沒有殘留的 `cr-demo-<scenario>` 容器。

## 重跑指令

```bash
cd apps/web
export PATH=$HOME/.nvm/versions/node/v22.23.3/bin:$PATH
npm install && npx playwright install chromium     # 只需一次
npm run e2e                                        # 跑完整流程
npm run e2e:report                                 # 看 HTML 報告（含失敗時的 trace／影片）
```

- 前端：測試自己在 `127.0.0.1:5184` 起 Vite（5173/5174 在這台機器常被別的 dev server 占用，可能是別的程式碼）。
  改埠：`CR_E2E_WEB_PORT`。
- 後端：`127.0.0.1:8077` 已有後端就沿用；沒有就用 `e2e/start-api.sh` 啟動，需要 venv 與含 `OPENAI_API_KEY` 的 env 檔。
  在 worktree（沒有自己的 `.venv`／`.env`）裡要指定：
  `CR_VENV=$HOME/cr-project/.venv CR_ENV_FILE=$HOME/cr-project/.env npm run e2e`
  想強制用這個 checkout 的後端程式：再加 `CR_E2E_API_PORT=8177`（任一空埠）。
- 部署段需要 Docker；沒有 Docker 時該段標記 skipped 並寫明原因。
- 只連 localhost；baseURL 不是 localhost 時測試會直接拒絕執行。

## 證據位置

- 截圖（每一步一張，成功失敗都拍；失敗的檔名帶 `-FAILED`）：`apps/web/e2e/artifacts/screenshots/01…14-*.png`
- 逐步紀錄（每步耗時、scenario id、驗證層級、瀏覽器 console 錯誤、失敗的 API 呼叫）：`apps/web/e2e/artifacts/run-log.json`
- Playwright 原始結果：`apps/web/e2e/artifacts/results.json`
- 失敗時的 trace／影片與 HTML 報告：`apps/web/e2e/artifacts/test-results/`、`html-report/`（不進 git，每次執行重新產生）
- 測試腳本：`apps/web/e2e/full-flow.spec.ts`；設定：`apps/web/playwright.config.ts`

目前 commit 的截圖與 run-log 來自最後一次「預設」執行（沿用 8077 的後端）。

## 失敗／異常紀錄

- 最終執行沒有失敗的步驟。
- run-log 裡有 4 筆 404（`GET /api/iac/{id}`、`GET /api/validate/{id}/report` 各 2 筆，StrictMode 下重複）。
  這是「還沒生成 IaC／還沒有報告」的預期回應，頁面顯示空狀態，不是錯誤。
- 另外，側欄為了顯示驗證進度，載入情境時也會讀一次報告，尚無報告時同樣是 404。

## A. 拓樸核准 UI

- 拓樸頁新增「部署前，由你確認這份拓樸」區塊：左欄列出**會開通的連線**，右欄列出**必須保持阻擋的路徑**
  （`environment_plan.verify_blocked`，含原因），下方「核准並繼續」呼叫 `POST /api/planning/{id}/topology/approve`
  （`approved_by: "user"`，可填備註），成功後前往 IaC 預覽。已核准時顯示核准人、時間、備註。
- 拓樸圖上也畫出必須阻擋的路徑（紅色虛線、✕ 標籤）。
- 部署頁：未核准時「啟動」停用，並顯示提示與「前往拓樸頁」按鈕。側欄與首頁的拓樸站顯示「待核准／已核准」。
- 重新規劃拓樸後，後端會把核准重設，畫面會回到「尚未核准」。

## C. 修掉的 GUI 問題

1. **流程頁沒有「確認依賴關係」的操作**：後端只對 `confirmed=true` 的依賴關係開通連線，但前端完全沒有這個欄位。
   新增「確認全部依賴關係」與單條關係的確認勾選，連線標籤顯示已確認／未確認，儲存後會保留。
2. **部署紀錄永遠是 0**：原本讀 IR 裡不存在的 `deployments`。改讀 `GET /api/deploy/{id}/records`，
   列出每次啟動／關閉（含被拒絕的）與原因；動作失敗時也會刷新。
3. **健康檢查停在 starting**：啟動後不會自動更新，要手動按。現在跟狀態一起每 5 秒輪詢，並在標題顯示狀態。
4. **側欄進度不準**：部署、驗證兩站永遠空白（後端不把這些寫進 IR）。改用即時的部署狀態與最新驗證報告。
5. `npm run typecheck`、`npm run build` 都通過。

## 設計（依 Lead 指示套用 frontend-design）

原本是常見的「近黑底＋藍色強調」儀表板。改成刻意的方向：**工程圖紙**——
冷色淺底的圖面、墨色線條，左側是深色儀表列。顏色只用來表達意義：
青＝開通的路徑、紅＝必須阻擋、琥珀＝等人決定。

- 色盤：圖面 `#e8edee`、面板 `#f7f9f8`、墨 `#14242e`、路徑 `#0f6e8c`、阻擋 `#c2331f`、等待 `#a8690a`。
- 字體：Barlow／Barlow Semi Condensed（標題與數字）、IBM Plex Mono（只用在 ID 與程式碼）；中文走系統黑體。
  字體由 npm 套件打包在本機，瀏覽器不會連外。
- 首頁 hero：一條「靶場路線」，畫出目前情境走到九站中的哪一站；拓樸那一站畫成橫在線上的閘門。
- 唯一的重點元素是核准閘門區塊；其餘維持安靜。移除了全大寫的表頭與小標。

## 沒做／需要 Lead 知道的事

- 沒有改 `apps/api`、`packages/contracts`。`verify_blocked`、`approval`、relation 的 `confirmed`
  在共用 TS 型別（`packages/contracts/src/types.ts`）裡還沒有，前端先在 `src/lib/plan.ts` 自行補型別；建議契約層補上。
- 觀察（後端行為，未處理）：示範報告分析出的依賴關係只有 1 條（Discovery → Collection），確認後拓樸仍只開通
  attacker → web:80，web → db:5432 被列在「必須阻擋」。這與報告內容（攻擊者經 web 連 db）方向相反，
  也是 `behavior_repro=PARTIAL` 的原因。是否要開通屬於後端／產品判斷。
- 前端無法判斷「核准已過期」（digest 由後端計算）；此時部署會回 409，畫面顯示後端的錯誤訊息。未另做專門提示。
- 流程頁的拖線新增關係、刪除節點等編輯操作沒有納入自動測試（只測了點選節點、確認依賴、儲存新版本）。
- 手機寬度沒有逐頁檢查。
- `apps/web/vite.config.ts` 沒動（主 checkout 有未提交的修改，避免衝突）；e2e 用命令列參數指定埠。
