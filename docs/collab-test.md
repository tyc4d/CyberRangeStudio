# 多 Agent 協作測試紀錄（2026-11-14）

測試方式：Lead（Claude Code）透過 `hc` 啟動一個 Codex 與一個 Claude Code Worker，
各自在獨立 Worktree（`agent/codex-test`、`agent/claude-test`）執行同一個小任務：
讀 `AGENTS.md`、列出研究資料夾、寫一個檔案、提交、用 `hc send` 回報。

| 項目 | Codex | Claude Code |
|---|---|---|
| 讀取 Repository 與研究資料夾 | 可以 | 可以 |
| 在自己的 Worktree 寫檔 | 可以 | 可以 |
| 寫到 Worktree 以外 | 被沙盒擋下（預期行為） | 未測 |
| 自行提交 | **不行**（`.git` 唯讀，`index.lock` 無法建立） | 可以（`5212b02`） |
| 用 `hc send` 主動回報 Lead | 可以（回報了失敗原因） | 可以 |
| Lead 收到結果 | 收到 | 收到 |
| 兩個 Worktree 互不干擾、`main` 未被更動 | 是 | 是 |

## 遇到的問題與處理

1. Codex 沙盒預設要建立隔離網路，在此主機失敗
   （`bwrap: loopback: Failed RTM_NEWADDR`，系統限制非特權 user namespace）。
   加上 `-c sandbox_workspace_write.network_access=true` 後正常，檔案寫入保護仍有效。
   代價：Codex 的指令可以連網。
2. Codex 無法提交。`--add-dir <主 Repo>/.git` 無效。改為由 Lead 代為提交。
3. Codex 首次啟動跳出信任資料夾對話框，需 Lead 按 Enter。
4. Claude Code 放在啟動指令裡的任務沒有送達，改為就緒後 `hc send`。

測試用的 Worktree、分支與檔案已清除，未併入 `main`。
