# Claude C — Infrastructure / IaC Engineer（名稱 infra-eng）
先讀 `reports/overnight/briefs/COMMON.md`。埠段 8111–8119；你部署的容器／網路／VM 名稱要能辨識為你的測試並在結束時清掉。
檔案所有權：`apps/api/app/iac/**`、`apps/api/app/deploy/**`、`apps/api/app/planner/catalogue/**`、`infra/**`、`tools/**`、模組 6–7 的 router 與測試；`reports/overnight/INFRA-VALIDATION.md`。

任務：
1. 全面盤點模組 6、7 的**實際**能力：IaC Generation、Resolver、Compiler、Deployment Runtime；Docker Compose／VM／網路拓樸／服務相依／資源配置各自支援到哪。寫成 INFRA-VALIDATION.md（能力矩陣＋證據）。
2. 實測：生成的 IaC 能否被工具解析檢查（`docker compose config` 等）、部署、停止、清除、重新部署、重置；收集容器狀態、網路連通、健康檢查、失敗時的錯誤資訊。特別驗證跨服務真實相依（Web→Database 真的連得到、真的有對應行為），而非只有容器在跑。
3. 補足 catalogue 的真實服務與**釘版本**映像，減少「沒有對應行為的替身容器」。易受影響的練習映像（例如 vulhub 類）只能跑在隔離網路、不對外開埠。cti-research 會在 `fixtures/cti-candidates/` 給候選事件所需軟體與版本，請據此補 catalogue。
4. Windows VM（已核准的 B4 Phase 1）：`deploy/manager.py` 的 VM 後端從未真實開機。評估並完成「本機 libvirt/KVM 開一台 Windows Server 2022 Eval VM、隔離網路、可靠清理、原生健康檢查」的真實驗證；ISO 已下載（見 COMMON）。已知疑點：domain XML 沒有 guest-agent channel、沒有 acpi/apic、用 `default` NAT 網路（非隔離）、`qemu:///system` 下 libvirt-qemu 進不了家目錄、尚無可開機的 qcow2（需 unattended 安裝）。這項耗時，放在 1–3 之後做；做不到的部分如實標 BLOCKED 並寫明原因。不得用 sudo（沒有密碼）；需要主機層級變更時寫進報告由產品負責人決定。
5. 問題做根因分析與最小必要修復，補測試。第一個里程碑：能力矩陣＋問題清單 → 回報。
