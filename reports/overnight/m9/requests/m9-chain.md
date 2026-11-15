# m9-chain integration request

The chain implementation is in `apps/api/app/poc/chain/` and exposes
`validate_chain(scenario_id, ir, plan, executions)` and
`build_fidelity_report(scenario_id, ir, plan, executions, chain, validation_report=None)`.

Please wire `poc.service.chain()` and `poc.service.report()` to these helpers and the
existing `poc.store` / Scenario IR store. The service file is outside the m9-chain owned
file set, so this worker did not edit it. `report()` should pass the latest module 8
validation report through as `validation_report` to preserve its independent
`env_build` and `behavior_repro` levels.
