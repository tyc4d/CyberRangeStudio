# m9-runner integration request

The required real-payload execution path cannot currently run against a vulnerable
target without changing shared deployment code owned by Lead:

1. `deploy.manager.isolation_preflight()` rejects plans containing vulnerable hosts,
   so the current `manager.up()` cannot deploy the required Struts / Log4Shell target.
2. `deploy.manager.probe_in_service()` delegates to `local_docker.probe_in_service()`,
   which calls `vulnerable_hosts()` and returns code 2 for every deliberately vulnerable
   target. Consequently the runner cannot deliver a payload to a successfully deployed
   vulnerable target through the mandated API.
3. `probe_in_service()` uses `docker run --rm`, but does not expose a container name or
   cancellation handle for an explicit finally-kill if its client times out.

Please provide a Lead-owned, guard-authorized vulnerable-target deployment/probe path.
The narrow option is a separate method that accepts verified scenario/service identity
from `poc.runner.guard.assert_target_owned`, retains the pinned helper image and
non-root/read-only/cap-drop/no-host-mount restrictions, assigns a deterministic
ephemeral container name, and guarantees kill/remove on timeout/cancel. It must not
weaken the existing module-8/D6 behavior for ordinary callers. Then m9-runner can call
that method only after its guard passes and the real Struts/Log4Shell e2e can use the
normal deployment record flow.

No alternate Docker invocation was added here because the task explicitly requires
reuse of `manager.probe_in_service` and forbids edits to manager.py.
