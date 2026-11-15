# m9-chain integration request

The chain implementation is in `apps/api/app/poc/chain/` and exposes
`validate_chain(scenario_id, ir, plan, executions)` and
`build_fidelity_report(scenario_id, ir, plan, executions, chain, validation_report=None)`.

Please wire `poc.service.chain()` and `poc.service.report()` to these helpers and the
existing `poc.store` / Scenario IR store. The service file is outside the m9-chain owned
file set, so this worker did not edit it. `report()` should pass the latest module 8
validation report through as `validation_report` to preserve its independent
`env_build` and `behavior_repro` levels.

## Fix round 1: runner identity required by strict evidence verification

No ExecutionResult/ChainValidation schema change is needed. The chain will fail closed
for old records without the following identity in their content-addressed JSON log.
Please have the runner emit:

```python
log = {
    "action_id": request.action_id,
    "status": status,
    "started_at": started_at,
    "ended_at": ended_at,
    "payload_sha256": payload_sha256,
    "proof_id": request.proof_id,
    "context": {
        "run_id": uuid.uuid4().hex,          # one immutable directory per attempt
        "job_id": job_id,                   # shared only within this execute batch
        "scenario_id": scenario_id,
        "scenario_sha256": scenario_digest(ir),
        "deployment_record_id": active_up_record["id"],
    },
    "ownership": ownership,                # includes scenario_id + service_ref
    "evidence": effect_evidence,           # kind/path/sha256 entries, before log entry
    # existing output/reason/cleanup fields may remain
}
```

Use `poc-runs/<sha256(scenario_id)[:16]>/<run_id>/...` for log and effect
paths. Include the log itself in `ExecutionResult.evidence` with its actual SHA.
`scenario_digest(ir)` will be exported by `app.poc.chain.evidence` (canonical sorted
JSON, ensure_ascii=False, separators=(",", ":")). Keep context tied to the IR/deployment
captured before execution; do not fetch a new deployment after execution and relabel
the old effect. PVE ownership currently returns deployment_record_id=None; resolve
the actual healthy active up record id. Local Docker remains non-attack QA.

The chain reads deployment audit records only (no runtime inspection/payloads), checks
the current healthy deployment id, checks the current IR digest, verifies all artifacts
are files inside DATA_DIR/poc-runs with matching hashes, and validates log/result identity.
Mixed batches are never combined: only the newest execution batch's runs are eligible.
Missing actions in that batch remain NOT_TESTED; duplicate attempts for one action in
one batch are rejected as ambiguous. Old overwritten or unverifiable records cannot PASS.

Strict transfer evidence is separate from arithmetic exploit proof. No current verifier
proves credential/session transfer, so current arithmetic-only chains stay unverified.
A future registered verifier may declare `state_transfer_types` and emit structured
`state_change` JSON receipts (produced/consumed) naming the opaque state id, value SHA,
source action/run, and the exact source artifact consumed. This is an artifact protocol,
not a request to implement a new payload in this fix round. See chain tests for synthetic
positive protocol fixtures; they are not real exploit or E2E evidence.

GUI #13: existing ChainValidation remains concrete and schema-valid: use BOTH `passes`
and `objective_reached` for the end-to-end metric. Per-action statuses only describe
individual actions. FidelityReport now also reports why full_chain remains unverified
in checks; no new frozen-schema fields are necessary.
