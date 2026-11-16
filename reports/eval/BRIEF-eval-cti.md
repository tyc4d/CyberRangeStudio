# Brief: eval-cti — collect 12 more threat reports with answer keys (2026-11-16)

Owner request: the poster results use only 4–6 reports. Add more real reports so the system can be evaluated on a larger set.

## Your task
Add **12 new** threat-report fixtures under `fixtures/cti-candidates/<id>/`, in exactly the same format as the existing ones (read all six existing folders first, especially `equifax-2017-struts-db/expected.md` and `negative-insufficient-intel/`).

Each folder:
- `report.md` — the incident narrative in the source's original wording (no paraphrase), with source URL, publisher, date, and page/section.
- `source.pdf` or `source.html` (+ `.txt` extraction) when downloadable, with SHA-256 in `expected.md`.
- `expected.md` — hand-made answer key from reading the source only: hosts/assets, attack steps (each with verbatim quote + ATT&CK ID), dependency relations vs. pure time order, missing information, and the expected reproducibility of each step (reproducible / substitute / needs VM / not reproducible) — same sections and grading labels as the existing keys.

## Mix (12 total)
- 5 × web/server vulnerability exploitation where a **vulhub image exists for the exact CVE** (check github.com/vulhub/vulhub; name the vulhub path in `expected.md`). These let us deploy and probe later.
- 3 × multi-host / Active Directory / lateral-movement intrusions.
- 2 × closed-source or appliance products (no distributable image), expected result = not reproducible.
- 2 × deliberately weak or incomplete reports (short advisories with little technical detail), expected result = system must block or mark gaps.

## Rules
- Sources: **US government public-domain only** (CISA/FBI/NSA joint advisories, GAO, US-CERT). No vendor blogs (copyright).
- **Do not run the CyberRange system or call any LLM API.** Do not read system outputs under `reports/overnight/evidence/`. The keys must be independent of the system.
- Do not invent facts. If the source does not say it, mark it UNKNOWN, exactly like the existing keys.
- Do not change product code. Only add files under `fixtures/cti-candidates/` and `reports/eval/`.
- Write `reports/eval/eval-cti-summary.md`: table of the 12 reports (id, title, publisher, date, URL, category, #steps in key, vulhub path or "none").
- Commit on your branch `agent/eval-cti` (small commits are fine). Do not merge, do not push, do not start other agents.
- When done or blocked: `hc send t31 "<one-line status + path to summary>"`.
