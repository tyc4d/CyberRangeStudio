# GUI 瀏覽器端到端測試結果（Task 3，frontend worker）

日期：2026-11-14　分支：`wt-frontend`　範圍：只改 `apps/web/**`

## 結論

Playwright 開真的 Chromium、只靠點 UI，把整條流程走完並通過：
上傳情資 → 分析 → 補充缺失 → 編輯流程（確認依賴關係）→ 軟體依賴 → 拓樸 → IaC 預覽 →
（確認未核准時不能部署）→ 核准拓樸 → 部署 → 驗證 → 報告 → 清理。沒有任何 mock。

| 執行方式 | 結果 |
|---|---|
| 預設（沿用已在 8077 的後端） | 第一輪 2 passed；改版後含動態測試共 4 passed，約 38 秒 |
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

- 截圖（每一步一張，成功失敗都拍；失敗的檔名帶 `-FAILED`）：`apps/web/e2e/artifacts/screenshots/01…14-*.png`（已是改版後的畫面）
- 逐步紀錄（每步耗時、scenario id、驗證層級、瀏覽器 console 錯誤、失敗的 API 呼叫）：`apps/web/e2e/artifacts/run-log.json`
- Playwright 原始結果：`apps/web/e2e/artifacts/results.json`
- 失敗時的 trace／影片與 HTML 報告：`apps/web/e2e/artifacts/test-results/`、`html-report/`（不進 git，每次執行重新產生）
- 測試腳本：`apps/web/e2e/full-flow.spec.ts`（全流程）、`apps/web/e2e/motion.spec.ts`（動態契約）；設定：`apps/web/playwright.config.ts`

目前 commit 的截圖與 run-log 來自改版後最後一次執行（8077 上沒有後端，由測試從本 worktree 啟動）。

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

## 視覺與動態改版（第二輪：對齊 RTSS Red Team Studio）

依 Lead 指示，直接對齊 `~/text2redteamscenario/apps/studio` 的設計系統（DESIGN.md、`tokens.css`、`style.css`），
套在我們自己的頁面與 Scenario IR 上。後端、契約、核准規則都沒動。第一輪的淺色「工程圖紙」方向已整個換掉。

**設計系統**
- 色彩、間距、動態 token 的數值照 RTSS：冷黑底 `#070b11`、表面 `#101923`、酸綠 `#beff3b`（選取與主要操作）、
  冰青 `#3bf4ff`（technique、handles）、依賴線 `#4ea6b3`、1px 邊框、2px 微圓角、節點右上 12px 切角。
- 字體：Manrope，檔案放在 `apps/web/public/fonts/`（連同 OFL 授權），瀏覽器不連外。移除了第一輪的 Barlow／Plex。
- 圖示：lucide-react（RTSS 用的同一套），打包在本機。

**版面**
- 頂列 64px：品牌字標、情境名稱、版本、真實狀態 badge（拓樸待核准／已核准、容器執行中）、各頁自己的操作、API 花費。
- 頂列下方是 1–9 的流程站點列（我們有九個階段，RTSS 沒有；用編號是因為它真的是順序）。
- 流程編輯頁（模組 3）改成 RTSS 的三欄工作區：
  左「元件」（資產＝IR 的主機與服務埠；步驟＝攻擊行為，可點選、可新增）、
  中央 React Flow 畫布（32px 細網格、左上工具列、左下縮放、右下 minimap、空狀態「尚無攻擊步驟」）、
  右側「設計工作台」（摘要、訓練資產、1 編排設計／2 設計檢查／3 人工核准、下一步按鈕；選取物件後同一位置變成屬性編輯）、
  底部可收合的「設計檢查」console。儲存、版本備註、設計檢查開關在頂列。
- 節點照 RTSS 的 step node：圖示、STEP 編號、technique、名稱、目標主機、前置數量；選取後上方出現複製／刪除／檢查工具列。

**動態（都可被 reduced-motion 關掉）**
- 依賴連線：只在「建立的當下」用 stroke-dashoffset 畫一次，之後靜止；載入既有情境時完全不動。畫布上沒有任何循環動畫。
- 節點新增：只動內層 article（scale .98 + 6px），不碰 React Flow 的定位 wrapper。
- 選取：邊框與圖示 120ms 變色；右側工作台／屬性 320ms 入場；選取、關閉屬性都不會重新取景。
- 換頁：內容 320ms 淡入 + 6px；通知 220ms；按鈕按下 scale .98；console 用 grid-rows 展開（不動畫 height）。
- 首頁「靶場路線」：GSAP 做一次性的線條延伸與站點依序出現，只反映後端已回報的進度。
- 拓樸核准成功後，核准區塊閃一次確認底色。
- 毛玻璃只用在畫布左上的浮動工具列一處，附 `@supports` 與 reduced-transparency 的不透明退路。
- 只動 transform／opacity／顏色；沒有動畫 width／height／top／left。

**reduced-motion 分級**（`theme.css` 最末段）
- 拿掉：所有位移、縮放、連線描繪、GSAP 時間軸、按下縮放。
- 保留但縮短到 80ms：顏色與透明度變化，避免狀態瞬間跳變。
- 保留：spinner（放慢）與進度條（改靜態），因為它們代表真的有請求在跑。

**誠實鐵則的落實**
- 連線只代表設計依賴或規劃的網路規則；畫布狀態列寫明「設計圖，不是執行紀錄」。
- 節點右下顯示的是「原文支持／推測」或設計問題數，不是執行結果。
- spinner／進度條只綁在真實的 Promise 上；頂列 badge 只顯示後端回報的狀態。
- 「設計檢查」是前端依畫布內容即時算的（未命名、懸空或重複關係、依賴循環、依賴未確認、孤立行為、推測項目），
  console 標題旁寫明它不代表部署或驗證結果。

**新增的自動測試**：`apps/web/e2e/motion.spec.ts`（2 項，皆通過）
- 既有連線載入時沒有任何動畫；拉出一條新依賴後，動畫 iterations 恰為 1、結束後 dashoffset 為 0、畫布上沒有無限循環動畫。
- 模擬 `prefers-reduced-motion: reduce`：沒有描繪動畫、節點與工作台入場改為純淡入、首頁時間軸不啟動。

**最新執行結果**：`npm run e2e` → 4 passed（約 38 秒）；`npm run typecheck`、`npm run build` 通過。
截圖已全部更新為新設計（`e2e/artifacts/screenshots/`，14 張）。

**這一輪沒做到的**
- 沒有引入 Radix 元件（Tabs／Popover／Dialog／Tooltip）：我們目前沒有需要它們的互動，提示用原生 title。
- 沒有做 RTSS 的「拖線放到整個節點」命中（只把 handle 的吸附半徑加大到 48px）、節點／連線的退出動畫、登入頁。
- 沒有錄互動影片；60fps 是依「只動 transform／opacity」的做法推定，沒有實際做效能量測。
- 四個以上的步驟在 1440px 寬會自動縮到約 0.7 倍才放得下，節點字會偏小（可用縮放或拖曳）。
- 最小寬度 1040px（同 RTSS）；手機版面沒有處理。
- JS bundle 由約 392 kB 增加到 496 kB（gzip 168 kB），來自 GSAP 與 lucide 圖示。
- 複製行為是照 RTSS 加的小功能（複製欄位、不複製連線）；若不在核准範圍，可以直接拿掉工具列上那一顆按鈕。

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
