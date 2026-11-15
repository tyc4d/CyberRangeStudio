# m9-runner integration note

Lead ruling accepted: local-docker intentionally returns `BLOCKED` for vulnerable
targets under D6; the Runner preserves that result. Real exploitation is only attempted
through `manager.probe_in_service` on a scenario-owned Proxmox worker after its isolation
evidence passes. No shared deployment code was changed.

Nice-to-have Lead follow-up: expose a deterministic ephemeral helper-container handle
from `manager.probe_in_service` so runner-level timeout/cancel cleanup can target that
exact helper without best-effort container discovery. Runner currently applies a bounded
wrapper and removes a uniquely matched helper when it can prove its identity.

`routers/poc.py` is outside m9-runner's owned file set, so please wire these two routes
to the implemented runner functions (`from app.poc.runner import runner`):

```python
@router.get("/{scenario_id}/execute/status")
def poc_execute_status(scenario_id: str): return runner.execution_status(scenario_id)
@router.post("/{scenario_id}/execute/cancel")
def poc_execute_cancel(scenario_id: str): return runner.cancel_execution(scenario_id)
```

Frozen response shapes: status returns `{job_state, per_action:[{action_id,stages}], logs_tail?}`;
cancel returns `{cancelled: bool}`. `run_job()` creates and updates the existing `poc_jobs`
row, persists `poc_runs`, publishes live stages, and polls the job's cooperative cancel flag.
