# 團隊工作規則

適用於所有在此 Repository 工作的 Agent（Claude Code、Codex）。

## 分工

- **產品負責人（使用者）**：決定開發範圍與產品方向。
- **Lead（Claude Code）**：在已核准範圍內負責技術決策、分工、開發、測試與整合。
- **Worker（Claude Code / Codex）**：只做 Lead 指派的任務，範圍以任務說明為準。

## 範圍

- 只有產品負責人明確核准的功能才能開發。核准項目記錄在 `docs/approved-scope.md`。
- 沒核准的功能不做，也不要「順手」多做。
- 技術問題自行解決；產品問題（要做什麼、給誰用、優先順序）一律回報 Lead，由 Lead 詢問產品負責人。
- `~/cr-research-m1` 是參考資料，不是結論，也不要修改它。
- 程式語言、框架、系統架構尚未決定，不要預設。

## 協作方式

- 每個 Agent 使用自己的 Git Worktree 與分支，不直接改 `main`：
  `git worktree add .worktrees/<名稱> -b agent/<名稱>`
- 只改自己 Worktree 裡的檔案。整合（合併進 `main`）由 Lead 負責。
- Worker 不自行啟動其他 Agent，除非任務明確要求。
- 完成或卡住時，用 `hc send <Lead 位址> "<結果或阻礙>"` 回報。長內容寫成檔案，只回報路徑。
- 回報要如實：測試沒過就說沒過，沒做的步驟就說沒做。

## 權限與啟動方式

- 日常工程決策由 Lead 決定，不必詢問產品負責人；產品功能與規劃變更才需要確認。
- Worker 以自動授權模式執行，不逐項詢問 Permission：
  - **Claude Code**：`--permission-mode auto`，可在自己的分支提交。
  - **Codex**：`-a never`（不詢問）＋ `-s workspace-write`（只能寫自己的 Worktree）。
    沙盒保留，不為了提交而關閉。**Codex 改完檔案後由 Lead 檢查並代為提交。**
- 啟動設定固定在 Herdr 範本 `cr-claude`、`cr-codex`
  （`~/.config/herdr-core/templates/`），Lead 一律用範本啟動，控制指令以 `hc --skill` 為準：

```sh
git worktree add .worktrees/<名稱> -b agent/<名稱>
hc run --bg --name <名稱> --cwd .worktrees/<名稱> cr-codex "<任務；結尾註明用 hc send $HC_TERMINAL_ID 回報>"
hc run --bg --name <名稱> --cwd .worktrees/<名稱> cr-claude "<任務；同上>"
```

- 啟動後 Lead 要確認：任務確實送達（`first_message.sent`）、畫面上的權限模式正確、
  沒有卡在對話框。Codex 首次進入新資料夾的「信任此資料夾」由 Lead 確認後按 Enter。
- Codex 的沙盒在此主機需開啟網路才能啟動（`network_access=true`），檔案寫入保護仍有效。
  實測紀錄見 `docs/collab-test.md`。

## 紀錄

- 測試紀錄與技術細節保留在 Repository（`docs/` 或各模組內），不要整份貼給產品負責人。
- 對產品負責人的回報：繁體中文、白話、簡短，只說做了什麼、結果如何、需要決定什麼。
