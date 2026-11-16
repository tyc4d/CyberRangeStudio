# Inventory — design & approved scope (owner-approved 2026-11-16)

## Why
Today the analysis extracts products "blind," then the planner/missing-item step discovers it has no exact
version and raises blocking "give me the version" questions — even when (a) the named vuln already determines a
usable vulnerable image (e.g. Log4Shell → CVE-2021-44228 → the vulhub image is a known-vulnerable pinned
version), or (b) the product is unsupported (VMware Horizon) so the version is moot. Scenario
`scn_6ad6ad85538c` showed both: it asked for the Horizon version AND the Log4j version although the report
clearly identifies Log4Shell as the entry, and the extracted CVE-2021-44228 was never attached to the service
or mapped to the deployable vulhub Log4Shell image.

## Owner decisions
- **Full inventory** (services + OS base images + tools), with "obtainable" sources modelled.
- **Auto-propose a substitute + flag it, user-overridable** when a product is unavailable.
- Approved to build now via Herdr workers (Lead coordinates, does not implement).

## The concept
An **Inventory** = the single source of truth for "what this platform can actually stand up," queried BEFORE the
analysis/planner decide anything, and used to resolve each extracted component against reality.

Three availability tiers per entry:
- **have** — already deployable now (current catalogue components: pinned OSS images, `vuln-*` images).
- **obtainable** — pullable/downloadable within the $50 budget on the Docker/PVE runtime (vulhub images by
  path, OS eval images, base images) — recorded with its source + cost, not yet local.
- **unavailable** — no image and cannot be faked (`unsupported-*`: Horizon, AD-DS-as-exact, closed-source).

Each inventory entry carries: product/software, aliases, pinned version(s), the **CVE(s) it reproduces**,
runtime (docker|vm), **substitute_for** links (which products/CVEs/techniques it can stand in for), obtainability
(source, pullable?, est. cost), and role_keywords.

## Resolution contract (the heart of the feature)
`inventory.resolve(product_name, version?, cves?, attack_technique?) -> Resolution`:
```
Resolution = {
  tier: "have"|"obtainable"|"unavailable",
  component_id: <deployable or substitute component> | null,
  is_substitute: bool,           # true when standing in for a different product
  version_basis: "stated"|"assumed"|"substituted"|"user_supplied",
  reproduces_cve: [cve,...],      # CVEs the chosen component actually reproduces
  substitute_of: <original product> | null,
  reason: <human-readable>,
  needs_question: bool,          # true only for a GENUINE, resolvable ambiguity
  question?: {field, text, suggestions}
}
```
Rules:
- A named vuln/CVE that maps (via the CVE→component index) to a `have`/`obtainable` component → offer it as a
  proposal (same product or `is_substitute=true`, `version_basis=substituted`) and **do NOT raise a version
  question** — the component's pinned version IS the vulnerable version. A cross-product substitute stays out of
  the deployable plan until the user accepts or replaces it. After confirmation, mark the ORIGINAL product
  not-reproducible and probe only the selected component. (Owner: propose + flag + require confirmation.)
- `unavailable` with NO substitute → `needs_question=false` for version (moot); the host/step is marked
  not_reproducible with the reason. Don't ask the version of something we can't deploy.
- `needs_question=true` ONLY when the product is deployable AND a real version choice changes the lab (e.g. two
  distinct deployable versions with different behaviour) — then ask, as today, with suggestions.
- Never claim the original product was reproduced when a substitute was used; `epistemic_status`/`version_basis`
  and the substitute flag stay truthful.

## Pre-LLM grounding
Module 1 analysis receives a COMPACT inventory availability summary (what's deployable / substitutable / known
CVEs), so extraction maps to reality instead of guessing. The authoritative mapping is still the deterministic
`inventory.resolve` applied after extraction (the LLM hint improves recall; `resolve` decides).

## Build breakdown (file ownership — disjoint)
| Worker | Template | Owns |
|---|---|---|
| inv-catalogue | cr-claude | `apps/api/app/planner/catalogue/**` (extend components.json: tier, cve-reproduced, substitute_for, obtainability, OS base images) + new `apps/api/app/planner/inventory.py` (`resolve`, `inventory_summary`, CVE→component index) + tests |
| inv-map | cr-codex | `apps/api/app/cti/analysis.py` (propagate report-level CVEs onto the service/action that cites them) + `apps/api/app/planner/dependencies.py` (use `inventory.resolve` to set catalogue_component / substitute / version_basis / cve) + tests. Imports inventory; does not edit it. |
| inv-missing | cr-codex | `apps/api/app/cti/missing.py` (substitute-first: suppress moot/auto-resolved version questions, keep genuine ones; reflect inventory resolution) + tests |
| inv-gui | cr-claude | a Module-1/2 UI surface showing each component's inventory status + chosen substitute + an override control (reuse existing web components) + its method in `apps/web/src/lib/api.ts` |
| inv-review | cr-codex-ultra | read-only QA |

**Lead owns at integration:** any cross-module contract, `service`/router wiring, and edits to shared files not
in a worker's set. A worker needing a change outside its set writes `reports/inventory/requests/<worker>.md`.

## Acceptance (Lead verifies)
On `scn_6ad6ad85538c`-like input: Log4Shell/CVE-2021-44228 offers the vulhub Log4Shell component as a flagged
substitute (no version question). It is not part of the deployable plan until the user confirms it; after
confirmation, the original Horizon host is marked not-reproducible and the selected substitute can be probed.
Genuine deployable-version ambiguities still raise a question; substitutes are always flagged and never claimed
as the original product; no regression in existing module 1/2/4 tests. Honest degradation + epistemic_status/
version_basis are preserved throughout.
