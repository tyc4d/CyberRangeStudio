# 整合待辦（Lead 內部，整合階段逐一處理）

由 fe-gui 讀其他 Worker 程式後回報 + Lead 審查發現：

1. [be-cti] supplement 端點要與契約一致：`{text, targets_missing_item?, status?}`，
   需支援無對象的自由補充、以及 substitute_chosen / accepted_unknown 等狀態。
   （目前 missing_item_id 必填、不收 status。）
2. [infra] `GET /status` 每次查詢都寫稽核紀錄；前端每 5 秒輪詢會爆量。
   status 不應落紀錄，只有 up/down 落紀錄。
3. [infra] `up` 需 `{test_approved:true}`（安全閘，保留）。前端已配合。
4. [fe] 5173 被占用時 Vite 自動用 5174。啟動說明要寫清楚。
5. [fe] package.json typecheck 原為非法 `tsc -b --noEmit`，fe 已改 `tsc --noEmit`。
6. npm 需 PATH 加 ~/.nvm/versions/node/v22.23.3/bin。

處理方式：各後端 Worker 分支合併進 main 後，由 Lead 在 main 直接修整合膠水並跑全棧驗證。
