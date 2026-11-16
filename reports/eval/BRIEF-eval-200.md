# Brief: eval-200 — run the system on at least 200 real threat reports (2026-11-16)

Owner request: "至少要跑 200 份報告之後更新海報". The current poster evaluation uses 17 reports × 3 runs
(`reports/eval/eval-run-summary.md`). We need a corpus of **≥ 200 distinct real reports**, each run through
the system once, with metrics that can be computed and re-checked automatically.

## Part 1 — corpus (no LLM)
- Source: **US government public-domain only**. Use `https://www.ic3.gov/CSA/<year>` for 2020–2026
  (about 267 PDF links counted by the Lead). If fewer than 200 usable remain, add `https://www.ic3.gov/PSA/<year>`
  items. `www.cisa.gov` returns 403 from this host: do not work around it (no fake User-Agent, no archive.org).
- Plain `curl`, polite (≤ 1 request/second). Store under `fixtures/cti-corpus/<id>/`:
  `source.pdf`, `source.pdf.txt` (pdftotext -layout), `report.md` = the extracted text, unchanged except page
  headers/footers removed by a script (no hand paraphrase), with a header: title, publisher, date, URL, SHA-256.
- `fixtures/cti-corpus/manifest.csv`: id, title, date, url, sha256, pages, chars, category
  (category from the text by simple rules, e.g. has CVE / has ATT&CK table / advisory-only; say the rule in the summary).
- Keep duplicates out (same SHA or same advisory id). Large PDFs: commit them only if the total corpus is < 300 MB;
  otherwise commit manifest + txt + report.md and keep PDFs gitignored, with SHA-256 in the manifest.
- The 17 existing `fixtures/cti-candidates/` reports stay as the hand-keyed subset. Mark in the manifest which
  corpus items overlap them.

## Part 2 — runs
- Product code = this branch (main 4c2c5fa + eval tooling). **Do not change product code, prompts or settings.**
- Same entry point and settings as `reports/eval/run_eval.py` (read `eval-run-summary.md` first): modules 1, 2, 4, 5
  via `run_real.py ... markdown single_pass`, then the module-6 `inspect_plan` / `compose_document` check.
  Nothing is deployed: no Docker, VM, Proxmox or probe.
- One run per report. Each run gets its own new `CR_DATA_DIR`; check no LLM cache is reused (0 cached calls).
- **Cost:** first run a pilot of 10 reports and record cost per report. Hard cap for the whole batch **$20**
  (Budget Manager estimate). If the pilot projects more than $20, stop and report to the Lead with the numbers
  — do not shrink the corpus or switch models on your own. Run with modest parallelism (≤ 4).
- A failed or blocked run is a result, not something to hide or retry until it passes. One retry is allowed only
  for transient network/API errors; log it.

## Part 3 — metrics (automatic, from the files only)
Write `reports/eval/eval-200-summary.md` and CSVs `reports/eval/eval-200-*.csv`. Per run and in aggregate:
- finished / crashed / system-blocked (insufficient intel), with counts and denominators;
- number of steps, hosts, dependency edges, missing-info items;
- **quote grounding:** share of step quotes found verbatim (whitespace/hyphenation-normalised) in `source.pdf.txt`
  — say the normalisation rule;
- ATT&CK IDs: share that are valid technique IDs (use a pinned ATT&CK enterprise dataset; name its version/URL);
- per-step reproducibility label distribution (reproducible / substitute / needs VM / not reproducible);
- module-6 deployable yes/no and blocker types;
- cost and wall time per report (median, p90, total).
Say plainly what these metrics do NOT measure (no answer keys for the new reports, so no precision/recall on them;
accuracy against keys remains the 17-report subset). Do not invent or estimate numbers that were not measured.

## Rules
- Do not read `expected.md` files. Do not change product code. Only add files under `fixtures/cti-corpus/`,
  `reports/eval/`, and a `.gitignore` entry if needed.
- The OpenAI key is read from `/home/tyc4d/cr-project/.env` by run_real.py; never copy or print it.
- Commit on branch `agent/eval-200` (small commits). Do not merge, push, or start other agents.
- Report: `hc send t31 "<one line status + path to summary>"` when done, when the pilot shows > $20, or when blocked.
