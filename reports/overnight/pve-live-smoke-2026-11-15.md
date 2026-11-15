# PVE live smoke verification — 2026-11-15

## Scope

Validated one approved, non-vulnerable synthetic deployment through the official application API from the `agent/pve-integration` worktree. The scenario was `scn_2acb1b9c902c`; its existing topology approval note limits it to an internal HTTP/80 lifecycle lab. The API process used `CR_DEPLOY_BACKEND=proxmox`, `CR_PVE_MODE=live`, an explicit live-enable flag, and the shared absolute reservation database. Credentials were loaded from the existing environment and were not printed.

No mock tests, local Docker deployment, vulnerability image, exploit probe, external publishing, or direct PVE write outside the product API was used.

## Result

- Read-only live preflight passed against PVE 9.2.2. The template was stopped, owned, 20 GiB on `scsi0`, had the exact `ide2=local-lvm:vm-900000-cloudinit,media=cdrom` disk, had QGA enabled, and had no NIC. Capacity checks passed.
- The first `/api/deploy/{id}/up` returned PVE HTTP 400 before clone creation: PVE rejected the generated VM name because the scenario ID contained `_`, which is invalid in a DNS name. The worker count remained zero. The PVE pool listed only template VMID 900000. A read-only config query for the absent worker VMID was denied by the current PVE ACL (403). The exact `reconcile` reservation row was removed under an exclusive SQLite transaction after confirming the PVE parameter-validation response and zero-worker pool state.
- Fixed pending/final PVE VM names and the matching owner tag by mapping scenario-ID underscores to hyphens. The original scenario ID remains in VM description metadata. Also made an explicit PVE HTTP 400 plus absent provisional clone a definitive rejected-clone outcome; unknown transport outcomes remain reserved for manual reconciliation.
- Retried through `/api/deploy/{id}/up` with `test_approved=true` and `expose=internal`: HTTP 200, `state=running`, worker VMID 900100. QGA started NGINX and Alpine inside the guest. The API reported no published host ports, zero VM NICs, and both scenario networks as internal bridge networks with isolated gateway mode.
- Called `/api/deploy/{id}/down`: HTTP 200, `state=stopped`. Compose removed both containers and both networks; the owned VM was shut down and deleted.
- Post-cleanup status was `not_created`; live preflight reported `worker_vmid_count=0`; the shared reservation table had no rows.

## Code changes in this validation branch

- PVE VM pending/final names and scenario ownership tags normalize `_` to `-`; client-side identity guards use the same normalization.
- A clone request recorded as HTTP 400 and followed by an absent provisional clone clears its exact reservation. Network/timeout ambiguity continues to retain a `reconcile` reservation.
- Runtime documentation records the actual limited live verification.

## Verification boundary

`py_compile` and `git diff --check` passed after the code changes. No automated tests were run. This is one single-worker internal deployment lifecycle; it does not establish concurrent API-worker safety, external client access, vulnerability-image deployment/probe behavior, or general production readiness. Live mode remains explicitly gated. Uncertain clone outcomes require manual reconciliation.
