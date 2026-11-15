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
