# inv-catalogue — done (branch agent/inv-catalogue, commit f4f8794 + this report)

## Tests
- Full suite `PYTHONPATH=apps/api pytest apps/api tests -q`: baseline 251 passed → after change **265 passed** (14 new, 0 regressions; includes Docker integration).
- New: `apps/api/app/planner/test_inventory.py` (same-product-have, CVE→substitute, unavailable-no-substitute, genuine version question, OS base resolution, shape checks, planner isolation of OS images, summary).

## API for inv-map / inv-missing / inv-gui  (`from app.planner.inventory import ...`)
- `resolve(product_name, version=None, cves=None, attack_technique=None, *, user_supplied=False) -> dict`
  Exact DESIGN keys: tier, component_id, is_substitute, version_basis, reproduces_cve, substitute_of, reason,
  needs_question, plus `question={field,text,suggestions}` only when needs_question. `user_supplied=True` → version_basis "user_supplied".
  CVE ids written inside product_name ("CVE-2021-44228") are also picked up.
- `cve_index() -> {CVE: (component_id,...)}` (have/obtainable reproducers only); `components_for_cve(cve)`; `technique_index()`.
- `inventory_summary() -> str` compact text for the Module-1 LLM prompt (~1.3 KB).
- `inventory_entries() -> list[dict]` structured per-entry tier/obtainability/substitute_for (for the GUI).

## Decision order inside resolve
1. Any requested CVE reproduced by a have/obtainable component → that component, no question.
   Same product → is_substitute=false, basis stated / substituted (stated version differs) / assumed (none stated).
   Different product → is_substitute=true, basis substituted, substitute_of=<original name>.
2. Named product deployable: 1 version → it (assumed, or substituted if stated version differs — no question,
   there is no choice). Several versions → stated version picks; else a `family_default` release if exactly one
   (Ubuntu 24.04, Debian 12, Windows 11); else **needs_question=true** (Windows Server 2016/2019/2022).
3. Not deployable → by-name stand-in (`substitute_for.products`, exact name only: IIS→nginx, Log4Shell→Solr)
   or a technique stand-in only if exactly ONE component lists that technique (T1190 has two → none chosen).
4. Else tier=unavailable, component_id=null, needs_question=false, reason says not reproducible.

## Examples (verified)
- `resolve("VMware Horizon", None, ["CVE-2021-44228"])` → have / vuln-log4shell-solr / is_substitute / substituted / no question.
- `resolve("VMware Horizon")`, `("Log4j")` (no CVE), `("Active Directory")` → unavailable, no question.
- `resolve("Windows Server")` → needs_question with 3 suggestions; `("Windows Server","2019")` → os-windows-server-2019-eval.

## Catalogue notes
- New fields on all 23 entries: tier, reproduces_cve, substitute_for{products,cves,techniques}, obtainability{source,pullable,est_cost_usd[,ref,note]}.
  Legacy `substitutes_for` left unchanged (match_software / dependencies.py behaviour unchanged).
- OS base images: `kind: "os_base"`, matched via `os_names` / `os_family_names`; `aliases`/`role_keywords` are empty on
  purpose so the dependency planner does not turn "Ubuntu" mentions into services.
- Honesty calls: Windows eval releases are tier **obtainable** (I could not verify a local template from this sandbox —
  libvirt socket permission denied; the protected PVE template 80000 is not ours). Solr substitute_for.products is
  only "log4shell"; Horizon reaches Solr only through the CVE, so a Horizon host with no Log4Shell context is never swapped.
- Not done (not in brief): no extra obtainable vulhub entries (container entries need verified digests).
