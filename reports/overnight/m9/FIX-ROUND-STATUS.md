# Module 9 — Fix Round 1 status (2026-11-16)

After independent QA (CHANGES REQUESTED, 15 findings / 26 repro tests), fix round applied.

## State at agent/m9-base (73f792d, chain intermediate 8becd85 merged)
- Full backend suite: **228 passed, 46 subtests** (no regression).
- Review acceptance file (reports/overnight/m9/review/test_m9_review.py): **56 passed / 2 failed**.

## Fixed (24 of 26 cases)
- #1 marker-vs-error PASS, #2 secret leak (export), #3 D6 attack block, #4 guard extra-network,
  #6 chain independent/keyword/time-order, #7 predecessor gating (service.execute) + propagation (chain),
  #8 IR-service->compose-host mapping + discovery target_host_ref, #9 evidence/run-identity verification,
  #10 no-verifier->not_executable + exploit-by-name, #11 BLOCKED-not-FAIL + nullable schema, #12 persist
  discover/chain, #13 GUI end-to-end-chain metric + unverified counts, #15 version-range ranking.

## Still failing — deploy-layer, honestly deferred (NOT faked)
- #5 `test_cancel_does_not_allow_delayed_launch_after_cleanup_returns`: a guaranteed cancel needs a
  cancellable transport handle `manager.start_probe_in_service(...)->handle{wait/cancel/join, unique id,
  launch fence}` in the shared deploy layer (deploy/manager.py, deploy/backends/*). Runner is fail-closed
  (BLOCKED) meanwhile — honest, never a daemon-thread fake cancel. Needs coordination with the deploy/PVE
  lead; NOT built blind overnight.
- #14 `test_pve_helper_has_explicit_cpu_memory_pid_caps`: the sandbox helper needs its own
  --memory/--cpus/--pids-limit, added where manager/local_docker launch the helper (deploy layer).

## Pending
- m9-chain final hardening delta (symlink/read-race/env-FAIL) to merge on top.
- Then re-dispatch m9-review (round 2).
- Real multi-service PVE E2E remains the owner-gated step (see module9-realpayload-blocker).

## Fix round 2 complete (15df414)
- Round-2 QA (9 findings) fixed: R2-01 export secrets, R2-02 predecessor bypass, R2-03b batch-cancel scope,
  R2-04 one-job protocol (service.execute single run_job + chain keeps all), R2-05 canonical host.service_refs,
  R2-06 sandbox caps, R2-07 version-range operators, R2-08 unverified metric, R2-09 persistence; plus the
  runner-found [FAIL,BLOCKED] same-job chain edge.
- Full backend suite: **263 passed**. review2 file: **89/89**. review1 file: **57/1**.
- The sole remaining failure is #5 (guaranteed-cancel transport handle) — genuinely needs the shared deploy
  layer's cancellable execute API; runner is fail-closed BLOCKED (honest). #14 caps are now DONE.
- Pending: reviewer round 3; then owner decisions (PVE real run; deploy-layer #5 coordination); then demo video.

## Fix round 3 complete (9bf2b7d)
- R3-01 (P1) export fail-closed secret scan, R3-02 GUI stale-chain, R3-03 overlapping-job status/cancel,
  R3-04 live stage render — all fixed. Prior rounds hold.
- Full backend suite: **268 passed**. review1 **57/1**, review2 **89/0**, review3 **34/0**.
- Sole remaining failure: #5 deploy-layer guaranteed-cancel handle (honest fail-closed). Round-4 check pending.
