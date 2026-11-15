# PVE worker limit 2 live smoke — 2026-11-15

## Result

Verified the second PVE worker slot with a real, previously approved synthetic scenario. The first worker remained running. The second worker was removed after the check; the original worker remains running and the second slot is available again.

## Cutover

- Candidate branch: `agent/trapa-deploy-ui`, merge commit `5acd13b`.
- Runtime change: `MAX_WORKER_VMS = 2` (`bbfaab7`); reservation-table migration and the no-mixed-version cutover requirement are documented in `docs/approved-scope.md` and `apps/api/app/deploy/backends/PROXMOX_RUNTIME.md`.
- Both API processes that shared the reservation DB (ports 8077 and 8283) were stopped cleanly and restarted from the same candidate worktree. Their `CR_DATA_DIR`, PVE mode/backend, target, and reservation DB settings were checked without printing credentials.
- The old singleton reservation table was migrated on the first placement-lock operation. After cleanup, read-only SQLite inspection showed the new per-VMID table, no legacy table, and one active reservation for VMID 900100.

## Live verification

1. Before deployment, `scn_2acb1b9c902c` was confirmed approved with a current topology digest, deployable IaC, `not_created` status, and ready PVE preflight. One worker was present: VMID 900100.
2. `POST /api/deploy/scn_2acb1b9c902c/up` with `test_approved=true` returned HTTP 200 and created VMID 900101. Both workers were simultaneously running. The new worker had zero NICs, its isolation report was checked and passed, and its two containers were running; the web container was healthy. No host ports were published.
3. With both workers running, live preflight reported `worker_vmid_count=2`, `running_workers=2`, 4096 MiB pool memory available, and refused a third worker with `cr-range runtime VM quota is exhausted`.
4. `POST /api/deploy/scn_2acb1b9c902c/down` returned HTTP 200 and removed the test deployment. Afterwards, VMID 900100 remained running with zero NICs, `scn_2acb1b9c902c` returned to `not_created`, and preflight reported one worker and capacity ready.

## Browser verification

- Before the quota increase, the real browser showed the new scenario's Start button disabled with the PVE quota reason; the already-running scenario was not misreported as blocked by the quota it itself occupied.
- After the increase, both scenarios showed the Start button enabled while the real PVE preflight reported capacity ready.
- Browser requests were GET-only; no page errors or failed API responses were recorded. The actual deployment and cleanup were the explicit API POSTs above.

## Limits

- This verifies two concurrent non-vulnerable synthetic workers and cleanup of the second worker only.
- No attack or vulnerability probes ran. No host Docker deployment was used.
- The third-worker limit was verified through the live preflight refusal, not by attempting a third deployment.
- No change was merged to `main` or pushed. The preview runs from `agent/trapa-deploy-ui`.
