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

## Lead 啟動 Worker 的方式

控制指令以 `hc --skill` 為準。這台機器上 Codex 需要以下參數才能正常運作
（沙盒預設的網路隔離在此主機無法啟動；開啟網路後檔案保護仍然有效）：

```sh
hc run --bg --name <名稱> --cwd <worktree 路徑> \
  codex --no-daemon -s workspace-write -a never \
  -c sandbox_workspace_write.network_access=true \
  --add-dir <主 Repo>/.git \
  "<任務；結尾註明用 hc send $HC_TERMINAL_ID 回報>"
```

`--add-dir <主 Repo>/.git` 是為了讓 Codex 能在自己的 Worktree 裡提交。

## 紀錄

- 測試紀錄與技術細節保留在 Repository（`docs/` 或各模組內），不要整份貼給產品負責人。
- 對產品負責人的回報：繁體中文、白話、簡短，只說做了什麼、結果如何、需要決定什麼。
