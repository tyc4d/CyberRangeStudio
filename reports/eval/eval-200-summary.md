# eval-200: the system on 228 eligible real threat reports, one run each (2026-11-16, revised after review)

This revision applies the review `eval-200-review.md` (R1–R4) and the Lead's rulings on it. **No new LLM calls were made for this revision, and no product code was changed.** The eligible-set numbers are recomputed from the existing run files.

All numbers below are computed from files by `reports/eval/summarize_eval200.py` (it makes no LLM calls). The corpus and eligibility rules are applied by `reports/eval/build_corpus.py`. `expected.md` files were not opened.

## Corpus and eligibility (Part 1, no LLM)
- **Source and download**
  - The FBI IC3 Cybersecurity Advisory listings `https://www.ic3.gov/CSA/<year>`, 2020–2026.
  - `reports/eval/fetch_corpus.py` downloads them with plain `curl`, the default User-Agent, and at least 1.1 s between requests. `www.cisa.gov` was not used.
  - **265 PDF links** were found.
- **What is counted:** works, not PDF files (Lead ruling on R2). One report is one work. Works that carry a non-US copyright or licence notice are excluded (Lead ruling on R1). All exclusions are in `fixtures/cti-corpus/excluded.csv` (37 items):

| reason | items | rule |
|---|---|---|
| download failed | 7 | HTTP 500 on the first try and again on one retry |
| no text | 1 | fewer than 500 characters after extraction (csa-2025-250507: 48 characters) |
| duplicate | 10 | 1 has the same SHA-256 as another item. 9 have the same own advisory id (`Product ID: X`, or the id after `Alert Number`); ids that the text only cites do not count. The item earlier in index order is kept. |
| **non-US copyright notice** (R1) | 15 | the text has `©`, "Crown copyright", "Commonwealth of Australia", "King in Right of Canada", "Creative Commons Attribution" or "Open Government Licence" (`RIGHTS_FOREIGN` in build_corpus.py). The first matching line is quoted in the reason. |
| companion part (R1/R2) | 1 | `csa-2024-241001-quick_reference_guide` is part of the excluded `csa-2024-241001` (© Commonwealth of Australia). Its own text says "This publication was developed by the Australian Signals Directorate's ACSC". |
| translation (R2) | 1 | `csa-2026-260918-ja` (listing title 日本語版) is the Japanese edition of `csa-2026-260918` |
| superseded version (R2) | 2 | the rule: items with the same normalised title, where the latest item has its own change record or version history. The earlier items are excluded. Hits: #StopRansomware Guide (`230523` v2.0 → kept `231019` v3.0) and Product Security Bad Practices (`241016-2` v1.0 → kept `250117` v2.0). |

- **R1 notice scan, my own check**
  - Over all 247 previously used items, every line that mentions copyright, licence, ©, Crown, Commonwealth or "His Majesty" was listed. The TLP sentence "Subject to standard copyright rules" was left out.
  - `RIGHTS_FOREIGN` hits exactly the same 15 items as the reviewer's `rights-flags.json`. My scan found no other document-level non-US notice.
- **Third-party code inside kept items** (kept; noted in the manifest column `rights_note` and in the `report.md` header)
  - `csa-2023-230509` contains a Volatility plugin ("This file is Copyright 2019 Volatility Foundation and licensed under ... VSL").
  - `csa-2024-240301` contains Volexity YARA rules ("See license at ...").
  - The headers say that this code carries its own licence.
- **Follow-up products are separate works.** Example: `csa-2026-260915` says it is an "update to previously published FLASH-20260320-001" with "a more detailed malware analysis with additional IOCs". It shares only 13 of the 63 long sentences of `csa-2026-260320`, so both are kept. The yearly "Top Routinely Exploited Vulnerabilities" reports (2021, 2022, 2023 data) are also kept as separate works.
- **Joint US + foreign advisories (Lead ruling: kept, with no public-domain claim).** Many kept items are joint advisories that US and foreign agencies wrote together, and they carry no non-US notice.
  - A rough regex for authorship statements that name non-US agencies hits 14 kept items: 211117, 211019, 221021, 220914, 220706, 220420-2, 220224, 220217, 230803, 230209, 230208, 240626, 260902, 260918 (all `csa-20xx-`).
  - In 260918, the Japanese NPA is named first.
  - I did not check by hand which of them are co-authored works and which only cite another document.
  - The Lead ruled to keep them and not to claim public domain. The rights statement for **all 228 kept items** is therefore: "Rights: published by U.S. government agencies (FBI IC3 copy); rule scan found no non-US copyright or licence notice. Some are joint advisories with non-US co-authors; public-domain status of co-authored parts not determined."
- **Later re-issues that were not run (Lead ruling: accepted as is).** Same advisory id means the same work, and the run item is a valid issue of it. **For 6 kept works, IC3 later published a re-issue under the same advisory id, and that re-issue was not run.** They are listed in the manifest column `later_reissue_not_run`:

| kept (run) | later re-issue, not run |
|---|---|
| csa-2023-231218 | csa-2025-250604 |
| csa-2023-231116 | csa-2025-250729 |
| csa-2023-231113 | csa-2024-240807 |
| csa-2023-230516 | csa-2024-241120 |
| csa-2024-240418 | csa-2025-251113 |
| csa-2025-250312 | csa-2026-260818 |

  No new runs were made for them.
- **Eligible: 228 works**, dated 2020-07-07 to 2026-11-13, with 225.3 MB of PDFs. The PDFs are committed.
- Excluded items keep their folders and run outputs on disk, out of git (`fixtures/cti-corpus/.gitignore`, `reports/eval/runs-200/.gitignore`). The branch history was rebuilt so that no commit on `agent/eval-200` contains the 15 non-US-notice PDFs, texts, `report.md` files or run inputs.
  - Note: the old commits (0e7b00c, 7193a38) still exist on the reviewer's branch `agent/eval-200-review`. I did not touch it.
- **Files for each report** (`fixtures/cti-corpus/<id>/`)
  - `source.pdf`
  - `source.pdf.txt`: the output of `pdftotext -layout`, unchanged.
  - `report.md`: a header (title, publisher, date, URL, SHA-256, rights line), then `source.pdf.txt` with page furniture removed by rules only (TLP / page-number lines, and running headers and footers that recur on at least 50% of pages).
  - **The header changed after the runs; the body did not.** The runs used the old header line "License: U.S. Government work (public domain)". That line has been replaced by the "Rights:" statement above, following the Lead's ruling. The run inputs were not re-run.
    - **Exact difference between each run input `runs-200/<id>/00-input.txt` and the current `report.md`** (line diff): for all 228 items, only that one header line differs. For 2 items (csa-2023-230509, csa-2024-240301), the header also has a new "Note: contains third-party code with its own licence notice …" line that the run input did not have.
    - No body line differs, and the summarizer checks that the bodies are identical for 228/228.
    - So the model saw a public-domain claim in the header that is no longer made. Header lines are metadata; whether this changed any output was not tested.
- **Category rule** (on `source.pdf.txt`): `has_cve` = the text contains a `CVE-yyyy-n`. `has_attack` = the text contains at least 3 distinct `T####[.###]` ids. The category is cve+attack 49, attack 37, cve 27, or advisory-only 115 (neither).
- **Overlap with the 17 hand-keyed `fixtures/cti-candidates/`**: 13 items match one of them by the same SHA-256 or the same own advisory id. The match is in the column `overlap_hand_keyed`.

## Runs (Part 2)
- **Product code:** `git diff 4c2c5fa HEAD -- apps packages` is empty.
- **Entry point and settings:** the same as `run_eval.py`.
  - Modules 1, 2, 4 and 5 run as `run_real.py <report.md> markdown single_pass` with `gpt-4.1-mini`.
  - Then the module-6 check `inspect_plan` / `compose_document` runs.
  - The wrapper is `run_eval200.py`. The batch is run by `batch_eval200.py` with 4 parallel workers.
  - Nothing was deployed.
- **Fresh data dirs:** each run has its own new `CR_DATA_DIR` (`.data-eval200/<id>`). The runner checks that `llm_cache.db` does not exist before the run. Result: **0 cached calls out of 646** (all 247 runs), and 0 out of 609 on the eligible set.
- **Pilot:** the first 10 reports cost $0.1877 ($0.0188 per report), which projected about $5 for the batch. The cap was $20.
- **Retries:** 0 runs were retried. The crashes are output-format errors from the product, not transient errors.
- **Actual spend of the whole batch: $9.1964.** This covers all 247 runs, including the 19 runs of items excluded later ($0.5259). It is the Budget Manager ledger estimate.
  - The ledger export is `reports/eval/eval-200-ledger.csv`: 646 rows, with timestamp, purpose, model, tokens, cost, cached flag and an `eligible` flag.
  - **The eligible-set cost is $8.6705** (228 runs).

## What was kept (R4)
- **Kept and committed**
  - The `run.log` of each eligible run, with the full stdout and stderr of `run_real.py`. It is sanitised: `/home/tyc4d/` is replaced by `~/`, and no key material was found.
  - The `meta.json` of each run.
  - The batch stdout logs, as `reports/eval/eval-200-logs/*.txt`. They were sanitised the same way; the original `.log` files are gitignored as `*.log`.
  - The LLM ledger, exported as CSV.
  - The `run.log` files show `ir schema errors: []` for every run that reached that line (225 of the 228 eligible; the 3 crashes stopped before it).
- **Not kept or not committed**
  - The raw SQLite files (`llm_ledger.db`, `llm_cache.db`). They are in `.data-eval200/` on this host only, and their ledger rows are exported to the CSV.
  - The state of each data dir before its run. It was not recorded; only the runner's assertion that `llm_cache.db` was absent exists.
  - The stderr of the module-6 subprocess. It is written only on error (`04-iac-error.txt`), and there was none.
  - The run outputs of the 19 excluded items. They are on disk only.

## Results (Part 3), eligible set n = 228 runs
Full table: `reports/eval/eval-200-aggregate.csv`. Per run: `eval-200-runs.csv`. Per step: `eval-200-steps.csv`. Per quote: `eval-200-quotes.csv`.

| metric | value | denominator |
|---|---|---|
| finished | 187 | 228 |
| system-blocked (≥ 1 open `severity=blocker` missing item after module 4) | 38 | 228 |
| crashed | 3 (csa-2021-211019, csa-2024-240628: LLM item missing `to_action`; csa-2023-231019: invalid JSON from the LLM) | 228 |
| finished with 0 steps (counted in "finished") | 36 (30 advisory-only, 6 cve) | 225 non-crashed |
| steps (IR actions): total / median / p90 / max | 2393 / 9 / 22 / 50 | 225 |
| IR hosts: total / median / p90 / max | 590 / 2 / 5 / 21 | 225 |
| env-plan hosts (includes attacker host): total / median / p90 | 779 / 3 / 6 | 225 |
| dependency edges (relations in 02-dependencies.json): total / median / p90 | 1838 / 7 / 18 | 225 |
| missing items after module 4: total / median / p90 / max | 3275 / 12 / 27 / 91 | 225 |
| **step quotes found verbatim in `source.pdf.txt`** (normalised, see below) | **1731/2817 (61.4%)** | 2817 quote uses |
| steps whose quotes are all found verbatim | 1471/2393 (61.5%) | 2393 steps |
| verbatim in `source.pdf.txt` or in non-layout `pdftotext` | 2002/2817 (71.1%) | 2817 |
| product `quote_verified=true` (**not** a verbatim rate; see the quote section) | 2204/2817 (78.2%) | 2817 |
| steps that have an ATT&CK id | 459/2393 (19.2%) | 2393 |
| **ATT&CK ids valid (active in Enterprise v20.1)** | **454/459 (98.9%)** | 459 |
| ATT&CK ids revoked or deprecated in v20.1 (T1070.001 ×4, T1574.002 ×1) | 5/459 | 459 |
| ATT&CK id string appears in the source text | 459/459 (100%) | 459 |
| step reproducibility: not_reproducible / needs_vm / reproducible / substitute_only | 1628 / 757 / 6 / 2 | 2393 steps |
| run fidelity: not_reproducible / needs_vm | 206 / 19 | 225 |
| module-6 deployable yes / no / no report (crashed) | 14 / 211 / 3 | 228 |
| module-6 blocker codes (runs): no_deployable_target / port_not_served_by_image / non_tcp_service / missing_backing_service | 204 / 6 / 1 / 1 | 228 |
| eligible-set LLM cost per report: median / p90 / max / total | $0.0297 / $0.0727 / $0.1667 / $8.67 | 228 |
| **modules 1/2/4/5 subprocess time** per report: median / p90 / max / sum | 35.3 s / 75.4 s / 137.2 s / 9593 s | 228 |

- **Subprocess time** is the wall time of the `run_real.py` subprocess only (`run_eval200.py` times that call). It does not include module 6 or the wrapper. The sum is a sum over runs, not elapsed time.
- **p90** is `sorted(values)[round(0.9 * (n - 1))]` (nearest index, Python `round`). The median is `statistics.median`.
- **Batch elapsed time, measured from ledger timestamps.** The ledger writes `ts` after each LLM call returns. So each span runs from the end of the first call to the end of the last call. It leaves out the first call's own duration and the work after the last call. Spans:

  | segment | runs | span |
  |---|---|---|
  | pilot | 10 | 68 s |
  | batch 1 | 75 | 839 s |
  | batch 2 | 162 | 1703 s |
  | first to last call, including the gaps while waiting for PDF downloads | all | 02:50:44–03:36:49 (2765 s) |
- **Results by category:**

  | category | runs | finished | blocked | crashed | deployable |
  |---|---|---|---|---|---|
  | advisory-only | 115 | 86 | 27 | 2 | 4 |
  | attack | 37 | 31 | 5 | 1 | 1 |
  | cve | 27 | 26 | 1 | 0 | 0 |
  | cve+attack | 49 | 44 | 5 | 0 | 9 |
- **Deployable (14):** csa-2020-200917-2, csa-2021-211117-2, csa-2021-210917, csa-2022-221020, csa-2023-230607, csa-2023-230315, csa-2024-240918, csa-2024-240905, csa-2024-240828, csa-2024-240116, csa-2025-250122, csa-2026-261113, csa-2026-261008, csa-2026-260810.
  - Their run fidelity is still mostly `not_reproducible`. Deployable means only that the plan passes the in-memory check.
- **Overlap subset** (13 hand-keyed items): 12 finished and 1 blocked; 3 are deployable. Each ran once, so this does not replace the 17×3 eval-run.

## Quotes: what each number means (R3)
**Primary check (61.4%).** Each `evidence[].quote` that a step cites through `evidence_refs` is counted once per use. It is searched in `source.pdf.txt` after `norm()`:
- curly quotes become straight quotes, en and em dashes become `-`, and `[.]` becomes `.`;
- line-break hyphenation is removed;
- **all** whitespace and all `-` characters are removed;
- the text is lower-cased.

A quote with `...` or `…` counts as found when every part longer than 8 characters is found. Nothing else is tolerated. This is the verbatim rate.

**What the product's `quote_verified` compares** (`apps/api/app/cti/citations.py`):
- It grades the quote against **the parsed source unit the model cited** (`00-units.json`), not against `source.pdf.txt`.
- Those units are the report's paragraphs, **plus rows that the parser adds for ATT&CK tables in `-layout` text** (`parser._split_layout_table_rows`: title + ID + Use put back together into one row).
- Before comparing, it **strips `[T####]` / `[TA####]` tags** from both the quote and the unit, turns dashes into spaces and collapses whitespace.
- `quote_verified = true` when the grade is **`exact`** (substring after that normalisation) **or `strong`**. Strong means:
  - the longest contiguous match is at least max(40 characters, 70% of the quote), **or** the SequenceMatcher ratio is at least 0.85;
  - and no unmatched content word is left.
- An ellipsis quote is strong when every fragment is exact or strong.
- So **78.2% is "the product accepts this quote as supported by the cited unit". It is not a verbatim rate.** Of the 2204 accepted quote uses, 2090 are `exact` and 114 are `strong`.

**Primary verbatim check × product flag** (2817 quote uses):

| | product true | product false | total |
|---|---:|---:|---:|
| found verbatim | 1708 | 23 | 1731 |
| not found verbatim | 496 | 590 | 1086 |
| total | 2204 | 613 | 2817 |

- The 23 "found but product false" are graded `partial` (19) or `none` (4). The product grades only against the cited unit (`evidence_record`), so a wrong citation would cause this. That was not checked for each of the 23.

**Causes of the 496 "product true, not found verbatim"** (first rule that applies; column `cause` in `eval-200-quotes.csv`):

| cause | uses |
|---|---:|
| the source has a single `[T####]`/`[TA####]` tag inside the quoted span; the quote leaves it out | 463 |
| the source has a multi-id tag (e.g. `[T1560, T1039]`) inside the span | 4 |
| quote cut mid-sentence with a period added (all graded `strong`) | 15 |
| found only in a parser-added ATT&CK table row (all in csa-2022-221121) | 12 |
| the source has a literal `&gt;` plus a tag in the span; the quote has `>` | 1 |
| ellipsis quote with a changed word between the fragments | 1 |
| total | 496 |

- The secondary check (non-layout `pdftotext`) explains almost none of this gap, because 467 of the 496 are tag omissions.
- **A real word change that the product accepts:**
  - `csa-2021-210318`, step `a6`, `evidence-6`: the quote is "These actors target SLTT victims with **...** **and** employee payroll direct deposit information".
  - The source has "…**or** employee payroll direct deposit information".
  - The product grades it `strong` (0.9362) and `quote_verified=true`.
  - The `strong` level allows small edits like this, which is why the product's rate must not be read as verbatim.

## Other metric rules
- **Outcome**:
  - crashed = `meta.status != ok`. This means a non-zero exit, no `03-topology.json`, or a module-6 error.
  - system-blocked = not crashed, and at least 1 missing item with `status=open` and `severity=blocker` in `02-dependencies.json`.
  - finished = every other run.
- **ATT&CK**:
  - The dataset is pinned to MITRE ATT&CK Enterprise v20.1, `https://raw.githubusercontent.com/mitre-attack/attack-stix-data/master/enterprise-attack/enterprise-attack-20.1.json`.
  - That file's SHA-256 is `539a843a7b53ed9749740b2123dddae3726b1a4831841c32aca740b011b910b5`.
  - `reports/eval/attack-enterprise-20.1-ids.json` holds 706 active ids and 161 ids that are only revoked or deprecated.
  - The product catalogue was built from the same file, so the validity rate is not an independent check of the product's filter.
  - The 5 inactive ids are not in the product catalogue, but they still reached the IR. This was not investigated.

## What these metrics do NOT measure
- **There are no answer keys for these reports.** So there is no precision or recall, and no measure of whether steps, hosts, edges or labels are correct or complete. Accuracy against keys is still only the hand-keyed 17-report subset.
- **Quote grounding (either number) shows only that text exists in the source.** It does not show that the quote supports the step it is attached to.
- **ATT&CK validity checks only that the id exists in v20.1.** It does not check that the technique fits the step.
- **"Deployable" is an in-memory plan check.** Nothing was deployed or probed.
- **Each report ran once.** The 17×3 eval-run showed variance between runs at temperature 0, and this batch does not measure it.
- **Cost is the Budget Manager ledger estimate.** It is not the provider invoice.
- **The corpus is mostly FBI/CISA advisories.** 115 of the 228 are advisory-only, and 36 runs produced 0 steps (30 of them advisory-only). Whether each report describes an intrusion chain at all was not checked.
