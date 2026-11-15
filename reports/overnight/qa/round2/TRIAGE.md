# Round 2 問題分派（Lead）

Round 2（凍結版 qa-round2）：講師 45／管理者 54／UX 62。原始報告在本目錄；截圖與 trace 在 `/home/tyc4d/cr-project/.worktrees/qa-{instructor,admin,ux}-r2/reports/overnight/evidence/`。
**每位負責人請完整讀三份報告中與自己模組有關的所有問題（含 Medium／Low 與評分表的每一項扣分理由），不只下列 High。**

## 共同目標（Round 3 必須成立的主線）
講師用 GUI 匯入 `fixtures/cti-candidates/equifax-2017-struts-db/report.md` → 分析 → 補件 → 流程 → 依賴 → 拓樸核准 → IaC 生成成功 → 隔離部署（catalogue 的 Struts 漏洞練習映像＋資料庫）→ 站台的驗證功能對「Struts 弱點利用」這個攻擊行為執行動作專屬的真實檢查（poc-eng Phase 3 已證明可行）→ 報告把每個行為分成 真實重現／教學替代／部分／未驗證／無法重現。全程不需要使用者繞路或懂內部結構。四位工程師的修復要能串起這條線，最後由 frontend-eng 補一支真實瀏覽器 e2e 走完它。

## scenario-eng（模組 1–5 後端）
- [High] 協定／加密通道被當成軟體，替代後同主機多元件，IaC 被擋（AR2-02、QA-I-R2-01）——@1739165 已部分修，需完整測試＋真 LLM 驗證。
- [High] 使用者自由補充（含「僅可替代、不等於真實重現」這類限制說明）被標成「原文」來源／原文版本，並產生無主機歸屬的服務（AR2-01、QA-I-R2-02、UXR2-02）。USER_SUPPLIED 絕不可顯示成 SOURCE_SUPPORTED。
- [High] 同一句原文在行為中引文成立，在關係中全部失配；CISA 15 條關係 unresolved:empty（QA-I-R2-03）。
- [High] 「可重現」能力預估只看映像是否存在，沒看行為條件（QA-I-R2-04）。
- [High] 引文逐字成立但主張語意有錯（UXR2-01）；Clop 帳號 username 與原文不符、核心行為缺漏。
- 其他：RDP 回答只記錄不套用；漏 DB 服務／版本結構；缺失清單不足（負向情資沒問關鍵弱點與工具；Java/DB/憑證／外傳資料流）；CVE→產品未帶入缺失分析；重新分析後替代補件失去原問題參照（UXR2-10）；XMRig ATT&CK 配對；行為缺明確結果欄（成功／失敗／能力）。

## poc-eng（模組 8）
- [High] 核心攻擊行為沒有動作專屬驗證（AR2-04）；只確認 nginx 首頁 HTTP 200，摘要卻寫「行為重現通過」，與分析頁「0/5 可重現」口徑矛盾（UXR2-03）。behavior_repro 不得因健康檢查／首頁回應而 PASS；把 Phase 3 的動作專屬探針（Struts OGNL 求值、Log4Shell 回呼）接進產品驗證流程：部署的是對應漏洞映像時真的測該動作，否則該動作 NOT_TESTED／SUBSTITUTED，摘要文字如實。執行前守門（隔離檢查）要保留。

## infra-eng（模組 6–7）
- 重複 up 會重建 DB／gateway 並改埠（應冪等或明確告知）；過程中埠資訊不一致。
- 配合主線：Equifax 計畫經 GUI 產生的 Environment Plan 必須能生成可部署的 IaC（漏洞映像只在隔離網路、不發布埠）；IaC 失敗訊息要指出是哪個主機／服務／埠以及使用者可以怎麼改。

## frontend-eng（GUI）
- [High] 多分頁時重新整理 /deploy 會無提示切換成另一分頁選的情境（AR2-03）——部署目標必須由網址決定並在畫面明示；清除後頂部殘留「容器執行中」。
- 依賴頁顯示「全部已對應」但 IaC 被擋——要讀後端新的 blocker／placement（scenario-eng@1739165）；不可部署時要有可執行的修正迴路（服務無歸屬、多服務映像衝突的修正入口）。
- 來源分級顯示：USER_SUPPLIED／ASSUMED／SUBSTITUTED 與原文明確區分；「可重現」理由不能只在 hover；英文欄位名與錯誤狀態不一致；報告摘要與分析頁口徑一致。
- 完成後補「共同目標」的真實瀏覽器 e2e。
