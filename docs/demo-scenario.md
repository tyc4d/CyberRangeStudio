# 端到端示範場景（Lead 指定，所有模組對齊這個）

第一版的唯一完整示範。選它因為：全開源可容器化、無商業/企業內部系統、Docker Compose 可部署、可在隔離環境安全做**無害**驗證。

## 故事（供情資報告描述）

「對外的脆弱 Web 應用 → 取得立足點 → 橫向到內部資料庫」

- 攻擊者主機（attacker）在外部網段。
- 受害 Web 主機（victim-web）對外開 80，跑一個開源 Web 服務。
- 內部資料庫（db）只在內部網段，Web 主機可連、外部不可連。

攻擊步驟（報告會描述、供模組 1 抽取）：
1. **偵察**：攻擊者存取對外的 Web 服務（80）。
2. **初始存取**：利用 Web 服務一個已公開的 CVE 取得執行能力（web shell）。
3. **探索**：從 Web 主機發現內部資料庫（內部網段）。
4. **蒐集**：Web 主機存取資料庫取得資料。

## 範圍與誠實界線（非常重要）

- 我們重現的是**環境與連線路徑**，不是真正跑漏洞利用程式。
- 模組 8 三層分開記錄：
  - `env_build`：三個容器都起來、服務健康 → 可做 PASS。
  - `behavior_repro`：**無害示範行為**，例如 attacker 對 web:80 發一次 HTTP 請求拿到預期回應、web 容器對 db:5432 連得上、內部網段對外隔離 → 可做 PASS。
  - `full_chain`：上述無害步驟依序完成 → 可做 PASS。
  - 真正的 CVE 利用：標 `NOT_TESTED`，fidelity 明確寫「初始存取的實際 exploit 未執行，只驗證服務與路徑存在」。
- Web 服務用開源映像；若非事件原始軟體，標 `is_substitute=true` 並在 fidelity 說明差異。

## 對齊的技術形狀

- 拓樸：3 host、2 network（external、internal:true）、connections: attacker→web:80、web→db:5432。
- compose：web、db、attacker 三個 service，cr-demo- 前綴，對外埠 42080（web）。
- catalogue：web=開源映像、db=postgres:16（固定版本）、attacker=alpine+curl。
