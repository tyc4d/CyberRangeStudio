# m9-runner fix-round integration needs

Owned product files: `apps/api/app/poc/runner/**`. No edits to the review tests.

## #5: cancellation needs a transport handle (Lead-owned manager/backend)

`manager.probe_in_service` is a synchronous, non-cancellable call; its PVE QGA PID is private to
`ProxmoxBackend._guest_exec`. Runner cannot stop a pending launch, kill that PID, or join the
remote process safely with only this API. `guest_exec` also holds `_placement_lock` throughout
polling, serializing emergency cleanup behind the running probe.

Future transport work needs a per-attempt cancellable handle, with a unique helper name/label, launch fence,
cancel/kill, and completion acknowledgement. Cancellation must prevent a pending launch and
kill a started helper; finally cleanup must cover 124/125/127 and exceptions. Keep ownership and
isolation checks; do not release the placement lock without a safe replacement for deletion races.

The unchanged review case `test_cancel_does_not_allow_delayed_launch_after_cleanup_returns`
uses a mock which *unconditionally* sets `delivered` then `finished` after waiting at most 1s.
It then requires `finished` true AND `delivered` false. A cooperative join alone cannot satisfy
this mock: if it finishes, `delivered` is already true; if it is killed, `finished` stays false.
I will not manipulate the mock's events or report a manufactured PASS. Please coordinate a
transport-handle test that can model cancellation while preserving the negative safety assertion.

Lead ruling received: do not build the shared handle subsystem in this round. Runner now fails
closed, creates no thread, and never calls `manager.probe_in_service`. PVE also stays BLOCKED.
The unchanged review test fails at `finished.wait(1)` because its transport is correctly never
started. This is not a claim that the unchanged named acceptance case passes.

## #11: aggregation must preserve BLOCKED (m9-chain)

`poc/chain/evidence.py:verify_execution` must check a runner BLOCKED status before its
`delivered && responded` FAIL branch. Runner will leave those stages false for safety/error paths
so it does not claim confirmed delivery from a wrapper return code.

Runner serialization now calls the shared `to_dict()` when present, with a compatibility
fallback that omits None dataclass fields. The two unchanged schema review cases directly call
stdlib `asdict(result)` instead of serializing the API result; `to_dict()` is never invoked by
those cases. They still fail on the shared model's optional None values. No schema weakening,
fake exit codes, or synthetic failure reasons have been introduced to satisfy this test seam.

## #14: resource limits are constructed in Lead-owned manager

`apps/api/app/deploy/manager.py:388` builds the actual PVE Docker helper argv. Add explicit
`--memory 128m --cpus 0.5 --pids-limit 64` to that fixed argv (and the local helper if appropriate).
The named review test calls manager directly, so runner-only changes cannot satisfy it. Lead
has agreed to make this change in the shared deploy layer.

## #9: artifact identity integration (m9-chain)

Updated by the runner/chain alignment follow-up: immutable paths are now
`poc-runs/<sha256(scenario_id)[:16]>/<run_id>/...` (no action directory).
The hashed JSON log emits action_id, status, started_at, ended_at, payload_sha256, proof_id,
context, ownership, and the effects' exact evidence records. Context holds run_id, job_id (when
run through run_job), scenario_id, scenario_sha256, and a real deployment_record_id when available.
The log itself is attached to ExecutionResult.evidence with its real SHA after the log is written.
No ExecutionResult schema change is needed; no evidence can be copied between attempts/jobs.

The runner imports `app.poc.chain.evidence.scenario_digest(ir)` directly. An absent scenario or deployment identity stays
absent/unverified in context; it is never synthesized. `_active_proxmox_deployment` currently
discards the lifecycle row's `id`; please retain it in the returned mapping so guard can emit
`deployment_record_id` without guessing which deployment it was.

The strict verifier now accepts real runner-written artifacts under mock transport; positive
and mutation tests are in `app/poc/runner/test_chain_integration.py`. See
`requests/m9-runner-alignment-results.md` for the authorized read-only import-overlay check.
