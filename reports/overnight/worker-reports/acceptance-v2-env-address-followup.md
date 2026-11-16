# V2 節點位址來源檢查

2026-11-16 只讀檢查 repo root `.env`，依產品負責人先前指示確認是否列有完整 PVE 節點位址。只輸出白名單設定欄位；沒有列印或核對 token、token secret 或 `OPENAI_API_KEY` 的值。

可用的非密值設定為：

- `CR_PVE_URL=https://192.168.16.214:8006`
- `CR_PVE_NODE=pve4-bbf`
- `CR_PVE_STORAGE=local-lvm`
- `CR_PVE_BRIDGE=vmbr990`
- `CR_PVE_POOL=cr-range`

`.env` 沒有其他節點位址清單。`CR_PVE_URL` 只是先前已測的管理位址，不能代替「所有節點介面位址」清單。沒有對其他 IP 掃描、沒有新增 PVE API 請求或網路探測。V2 仍需權威的完整位址來源，之後只能測該清單內的目標。
