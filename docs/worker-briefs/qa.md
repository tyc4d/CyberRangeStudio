# Worker Brief — QA（獨立審查，唯讀）

你**不改任何程式**，只做獨立驗證與回歸審查，找出「宣稱成功但證據不足」的地方。

審查重點：
1. **驗證判定正確性**：翻 `validator/runner.py` 與產出的 ValidationReport。確認
   - full_chain 不會在任何必要攻擊步驟 NOT_TESTED/FAIL 時 PASS；
   - 三個 level 定義不互相混淆，且 `level_criteria` 與實際算法一致；
   - 每個 check 的 status 都對應實際證據（docker exec 輸出 / HTTP 回應），不是只看容器 health 或模型回答。
2. **真實服務 vs 替身**：確認 `component_mode=real` 真的部署真實 nginx/postgres（pinned digest、版本可檢查），且 fidelity 不把替身說成真服務。
3. **網路分段**：確認 `verify_blocked` 的路徑驗證「真的連不上才 PASS、連得上就 FAIL」；允許路徑有正向連線證據。
4. **回歸**：`PYTHONPATH=apps/api python -m pytest apps/api tests -q` 全綠；GUI Playwright 測試可重跑、證據（截圖/log）存在。
5. 挑出任何**過度宣稱**或證據對不上的地方，列成清單（嚴重度排序）。

把審查結果寫成一個檔案（findings，嚴重度排序，每項附證據位置），`hc send t5 "<檔案路徑>"` 回報。只讀不改。
