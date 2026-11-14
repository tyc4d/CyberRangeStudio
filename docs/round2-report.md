# CyberRange 第二輪報告（2026-11-14）

目標:提高實際可用性與驗證可信度,不增加功能數量。只記事實,沒驗證過的不寫成已驗證。

## 本輪驗收對照

| 要求 | 狀態 | 證據 |
|---|---|---|
| 1. 正式支援真實開源服務(保留替身供測試) | ✅ | `component_mode=real` 部署 **nginx:1.31.8 / postgres:16.16-alpine3.23 / alpine:3.22**,全部 digest 釘選;`docs/e2e-evidence/05-docker-compose.yml` 可見真實映像,部署後 3 容器 healthy。替身模式保留(demo-api/demo-client)供測試。 |
| 2. 自動規劃網路 + 人工核准 | ✅ | topology 依場景規劃連線(確認依賴才開 lateral);`POST /api/planning/{id}/topology/approve` 人工核准閘,綁連線摘要,拓樸一改就失效;部署前強制核准。 |
| 3. GUI 真實端到端(Playwright) | ✅ | `apps/web/e2e/full-flow.spec.ts` 開真 Chromium 走完上傳→…→部署→驗證→清理,4 passed;截圖 `apps/web/e2e/artifacts/screenshots/`;Docker 不在時部署段誠實 skip。 |
| 4. 修正驗證判定 | ✅ | full_chain **不再**於必要步驟 NOT_TESTED/FAIL 時 PASS;三層各有 `level_criteria`;每個 action 對應 chain/fidelity;良性連線不被當成攻擊重現。CISA 示範實測 full_chain=**PARTIAL**(不是假 PASS)。 |
| 5. 真實資料測試 | ✅ | 真實 **CISA AA22-320A**(伊朗 APT,25 個 action、逐字引用)跑完整條;backend 另加真實 STIX 2.1(MITRE ATT&CK APT29)與 CISA CL0P/MOVEit 公告並有解析測試。 |
| 6. 平行工作 + Lead 整合 | ✅ | Herdr 分派 Claude Frontend / Codex Infra×2 / Codex Backend / Codex QA,各自 worktree 不重疊檔案,Lead 檢查後提交。 |
| 7. 清楚 README 啟動與驗收 | ✅ | `README.md` 更新:啟動、雙示範(內建 + 真實報告)、LAN 暴露模式、測試指令。 |

## 兩個實際示範(都真的跑過)

1. **內建情資 → 真實服務**(`docs/e2e-evidence/`):分析出 web+db,`component_mode=real` → 部署真 nginx + postgres + attacker,3 容器 healthy。驗證 `env_build=PASS`,behavior_repro/full_chain=**PARTIAL**(真實服務沒有良性 /demo 行為可測,誠實不宣稱重現)。
2. **真實 CISA 報告 → 誠實替身**(`docs/e2e-evidence-cisa/`):25 個真實 action、關係全標 temporal(模型沒亂推依賴);目標軟體(VMware Horizon、DC)不在開源 catalogue → 服務標替身、部署通用 alpine/python;`env_build=PASS`、full_chain=**PARTIAL**。這就是「真實報告 → 誠實揭露能/不能重現什麼」。

## LAN 暴露模式(本輪新增,預設關閉)

- `expose=lan`:web 與 DB 對同網段開;只綁指定/偵測到的 LAN IPv4(拒絕 0.0.0.0/loopback)。
- DB 改 scram-sha-256 + 每次部署隨機密碼,只走環境變數注入,**不入 compose/git**,API 回應回傳一次,record 只記 `password_set`。
- 兩道閘(test_approved + 拓樸核准)保留。

## 尚未完成 / 已知限制

1. **真實服務的「行為重現」仍有限**:目前對真 nginx/postgres 只驗到服務起來、版本、連線;沒有良性的應用層行為腳本,所以 behavior_repro 多為 PARTIAL/NOT_TESTED(誠實)。
2. **web→db 橫向連線在內建示範未開通**:該場景的確認依賴未唯一指出目的服務埠,拓樸保守維持 deny(寧可少開)。需要更精確的依賴→埠對應。
3. **真實報告多為 temporal 關係**:模型對 CISA 報告沒推出 dependency,所以不會自動開 lateral 路徑;符合「時間順序 ≠ 真依賴」的誠實原則,但也代表真實報告目前較難自動長出多跳拓樸。
4. **A/B/C 正式方法比較**:仍未做(本輪刻意延後)。
5. LAN 模式的對外連線尚未在「真的從另一台電腦」驗證過(需你的實機);指令範例在 README。

## QA 獨立審查與修正

Codex QA 獨立審查(只讀)抓到問題,已修的重點:
- **分段驗證誤判(High)**:DNS 解析失敗被當成「已封鎖」而給 PASS。改成**用目的容器 IP 直接探測**,`gaierror` 標為 UNRESOLVED/NOT_TESTED(絕不 PASS);連不到(Network unreachable)才算封鎖。並修正 `verify_blocked` 只斷言**不同網段**的路徑(同網段容器 Docker 不做 port 級隔離,本就互通)。證據:`attacker→db:5432` 分段 PASS 是真的打不到。
- **前端報告過時宣稱 full_chain=PASS(High)**:那是整合前(demo-api 替身)的舊結果。已對整合後後端重跑,更正為 PARTIAL,並在 Playwright 加上「full_chain 不得為 PASS」斷言(以後假 PASS 會讓測試紅)。
- 仍待補強(Medium,已知):驗證報告可再附上執行中容器的實際 image digest/原始 probe artifact,讓第三方能完全獨立核對(目前靠摘要 observed 字串 + 容器內版本輸出)。

## 測試

- 後端:`PYTHONPATH=apps/api python -m pytest apps/api tests -q` → **41 passed**(含分段 DNS/無 IP 兩個回歸測試)。
- 前端:Playwright 全流程 + 動態契約測試通過。
- OpenAI 用量:gpt-4.1-mini,十餘次呼叫,估計遠低於 $1(即時查 `GET /api/budget`)。
