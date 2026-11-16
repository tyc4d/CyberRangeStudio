# Module 9 — Fix Round 1 (after independent QA CHANGES REQUESTED)

Independent QA (`reports/overnight/m9/review/m9-review.md`) found 15 issues (8 P1). Acceptance bar =
`reports/overnight/m9/review/test_m9_review.py` (26 failing now) + `review/check_web_behavior.cjs` (3 failing).
**Make YOUR assigned cases pass WITHOUT weakening the test and without breaking the 171 existing tests.** These
are real "fake-success"/safety holes — the owner's #1 rule is no manufactured PASS. Run backend tests with
`PYTHONPATH=<this-worktree>/packages/contracts` (editable cr_contracts resolves to main otherwise).

Several fixes touch BOTH a worker subpackage AND `poc/service.py` (Lead-owned). The Lead owns service.py and the
IR→compose-host mapping; workers own their subpackage. Do not edit outside your set — note cross-cutting needs.

## m9-runner (cr-codex-ultra) — owns apps/api/app/poc/runner/**
- #1 `test_registered_payload_error_containing_marker_must_not_pass`: the pinned payload prints exception text;
  verifier does `marker in output`, so an HTTP 500 whose body/err echoes the marker PASSES. Bind success to a
  verified success signal (distinct success token the target only emits on real exploitation, and explicitly
  reject REQUEST_ERROR/error paths). Keep `test_control_registered_effect_can_pass_with_mocked_transport` +
  `test_control_liveness_or_failed_payload_never_passes` green.
- #3 `test_d6_blocks_attack_payload_even_for_non_vulnerable_image`: a registered attack payload on local-docker
  must be BLOCKED (zero execution) regardless of image vuln-classification. D6 = "local Docker is non-attack QA";
  gate M9 attack execution on the backend, not on image class. Keep `test_control_d6_known_vulnerable_image_...`.
- #4 `test_guard_rejects_any_additional_non_lab_network`: guard accepts a target that has a lab net AND an extra
  non-lab external network (helper shares the whole netns). Reject if ANY attached network is not an approved
  isolated lab net — check all connections, not "exists one".
- #5 (backend half) `test_cancel_does_not_allow_delayed_launch_after_cleanup_returns`: cancel/timeout must
  guarantee the helper cannot launch/continue after cleanup returns (cancellable handle + finally-kill + join;
  handle the 127/timeout path; parallel same-action cleanup must still kill). GUI half is m9-gui.
- #11 `test_timeout_blocked_is_not_reinterpreted_as_exploit_fail` + `test_runner_output_matches_execution_result_schema`:
  a timeout/BLOCKED must stay BLOCKED (don't let delivered/responded flip it to FAIL in the runner); and
  `asdict` emits nulls for optional fields but the frozen schema allows omission, not null — omit None fields so
  ExecutionResult JSON validates.
- #14 `test_pve_helper_has_explicit_cpu_memory_pid_caps`: the sandbox helper needs its own --memory/--cpus/
  --pids-limit (CONTRACT requires per-sandbox caps). If the exact flags live in deploy/manager.py (Lead-owned),
  implement what you can in poc/runner and leave the precise manager line in requests/m9-runner.md.

## m9-chain (cr-codex-ultra) — owns apps/api/app/poc/chain/**
- #6 three cases: `test_chain_independent_action_passes_do_not_prove_full_chain` (two independent PASSes with no
  edges must NOT give passes=true/objective_reached=true), `test_chain_transfer_requires_consumed_state_not_note_keywords`
  (a transfer is "verified" only with traceable produced→carried→consumed state evidence, not note/precondition
  keyword overlap), `test_chain_checks_actual_time_order_not_list_position` (use started_at/ended_at, not array
  index). A chain with no chain-evidence stays unverified.
- #7 `test_chain_failure_propagates_transitively` + `test_chain_uncited_failed_predecessor_cannot_leave_dependent_pass`:
  FAIL/BLOCKED must propagate along the DAG; a declared dependency's failed predecessor blocks the dependent even
  without a citation. Do NOT invent dependencies absent from the IR.
- #9 `test_verification_rejects_missing_artifact_and_unregistered_payload`: `proves_effect`/`verify_execution`
  must check artifact exists under the allowed root, payload is a registered verifier with matching SHA, and the
  run ties to the deployment — not just non-empty kind/path. Use run identity (not scenario+action last-row) so
  stale/overwritten runs aren't reused.
- #13 (backend half): expose a concrete chain/metrics shape so the GUI can show end-to-end chain by
  chain.passes/objective_reached, not a per-action PASS ratio (GUI does the display; you provide the data).

## m9-discovery (cr-codex-ultra) — owns apps/api/app/poc/discovery/**
- #8 (discovery half) `test_discovery_resolves_service_through_normal_target_host_ref`: resolve a service via the
  action's target_host_ref → host.service_refs when service_ref is absent, so normal IR actions get CVEs/PoCs.
- #15 `test_discovery_version_range_means_range_not_endpoint`: parse version ranges ("before X", "A through B")
  as ranges, not string endpoints; a version inside/outside the range must score accordingly.

## m9-export (cr-claude) — owns apps/api/app/poc/export/**
- #2 `test_export_removes_synthetic_credentials[url-userinfo]` + `[compose-default]`: strip/redact credentials in
  URL userinfo (`https://user:pass@host`) and in `${VAR:-<literal-default>}` where the default is itself a
  secret; final-bundle scan must catch them so contains_secrets/verify_bundle are truthful. Keep the 20 green.

## m9-gui (cr-claude) — owns apps/web/src/pages/PocPage.tsx (+ i18n)
- #5 (GUI half) + #13 `test_gui_stop_calls_backend_cancel_and_polls_job` and check_web_behavior.cjs 3 fails:
  Stop must call POST /execute/cancel and poll GET /execute/status (not just abort the fetch); fix the stale copy
  that says there is no cancel route. End-to-end chain metric must read chain.passes/objective_reached (a failed
  chain must NOT show 2/2). Count not-yet-executed and skipped actions as unverified in the readiness/unverified
  metric. Keep "five metrics separate" (already passing).

## Lead / integration — poc/service.py (I own these)
- #8 (mapping half) `test_service_maps_ir_service_to_actual_compose_host`: service.execute must map the IR
  service id to the ACTUAL compose/environment host id (via the environment plan / iac generator) so guard gets a
  real target, instead of passing the raw IR service id.
- #10 `test_plan_marks_no_verifier_not_executable_before_execution` + `test_exploit_named_action_without_technique_still_requires_real_payload`:
  plan() must mark an exploit action with no vetted verifier as not_executable (with reason), and recognise an
  exploitation step by name (reuse classifier), not only by attack_technique; execute must not silently return [].
- #12 `test_discovery_is_persisted_for_export` + `test_chain_is_persisted_for_export`: service.discover/chain must
  persist via save_manifest/save_chain so export sees them.
- #7 orchestration: service.execute must not run a dependent whose required predecessor FAILed/BLOCKED
  (`test_real_batch_orchestration_blocks_dependent_after_fail`).

After each worker reports, the Lead merges, re-runs the FULL review test file + the 171 suite, and only then
re-dispatches the reviewer. Real multi-service E2E on PVE remains a separate owner-gated step.
