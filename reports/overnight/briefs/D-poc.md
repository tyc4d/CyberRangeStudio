# Claude D — PoC / Attack Chain Validation Engineer（名稱 poc-eng）
先讀 `reports/overnight/briefs/COMMON.md`。埠段 8121–8129。
檔案所有權：`apps/api/app/validator/**`、模組 8 的 router 與測試、`tests/e2e/**` 中驗證相關腳本；`reports/overnight/evidence/poc-eng/**`。

任務：
1. 盤點模組 8 現況：三層驗證（env_build / behavior_repro / full_chain）各自實際檢查什麼？哪些只是健康檢查或簡單 HTTP 回應卻被當成行為驗證？判定邏輯是否可能假 PASS？
2. 依候選攻擊鏈（先用 AA22-320A 的 Log4Shell 步驟與 Web→DB 類鏈；cti-research 會在 `fixtures/cti-candidates/` 補候選與 expected.md）確認公開 PoC／研究與軟體版本、設定、權限、OS 是否相符，判斷能否在**隔離容器內**安全驗證。
3. 建立可重複執行的行為驗收測試：攻擊端動作必須從隔離網路內的攻擊者容器發出、目標只能是實驗內的容器；記錄預期結果、實際結果與證據（指令、輸出、目標端可觀測痕跡）。回呼類驗證（如 JNDI/LDAP callback）用實驗網路內自建的無害 listener，不連外。
4. 找不到 PoC、版本不符或無法證明的步驟：標 PARTIAL / NOT_TESTED / BLOCKED 並寫原因，讓報告能清楚呈現「真實重現／教學替代／部分／未驗證／無法重現」。
5. 需要目標映像或 catalogue 變更時，寫需求給 Lead（infra-eng 擁有 catalogue 與 deploy），不要自己改他的檔案。
第一個里程碑：現況盤點＋假 PASS 風險清單 → 回報。
