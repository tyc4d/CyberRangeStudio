# eval-cti — 11 new threat-report fixtures with answer keys (2026-11-16)

Brief: `reports/eval/BRIEF-eval-cti.md`. Branch `agent/eval-cti`. Result: **11 of 12** fixtures added under `fixtures/cti-candidates/`. Each has `report.md` (verbatim excerpt with source header), `source.pdf`, `source.pdf.txt` (pdftotext) and `expected.md` (hand-made key, same sections and grading labels as the existing keys).

## Fixtures

| id | title | publisher | date | download URL (actually fetched) | category | # steps in key | vulhub path |
|---|---|---|---|---|---|---|---|
| aa23-347a-svr-teamcity-cve-2023-42793 | Russian Foreign Intelligence Service (SVR) Exploiting JetBrains TeamCity CVE Globally | FBI, CISA, NSA, SKW, CERT.PL, NCSC (AA23-347A) | 2023-12-13 | https://www.ic3.gov/CSA/2023/231213.pdf | web / vulhub (same product, same CVE) | 17 | `teamcity/CVE-2023-42793` |
| aa24-016a-androxgh0st | Known Indicators of Compromise Associated with Androxgh0st Malware | FBI, CISA (AA24-016A) | 2024-01-16 | https://www.ic3.gov/CSA/2024/240116.pdf | web / vulhub (2 of 3 CVEs) | 12 | `phpunit/CVE-2017-9841`, `httpd/CVE-2021-41773` (CVE-2018-15133: none) |
| aa24-249a-gru-confluence-cve-2022-26134 | Russian Military Cyber Actors Target U.S. and Global Critical Infrastructure | FBI, CISA, NSA + partners (AA24-249A) | 2024-09-05 | https://www.ic3.gov/CSA/2024/240905.pdf | web / vulhub (same product, same CVE) | 3 core + 10 independent observations | `confluence/CVE-2022-26134` |
| aa22-257a-irgc-log4j-horizon | Iranian IRGC-Affiliated Cyber Actors Exploiting Vulnerabilities for Data Extortion and Disk Encryption for Ransom Operations | FBI, CISA, NSA, USCC-CNMF, Treasury, ACSC, CCCS, NCSC (AA22-257A) | 2022-09-14 | https://www.ic3.gov/CSA/2022/220914.pdf | web / vulhub (same CVE, "likely"; different product → substitute) | 5 (+5 activity-level TTPs) | `log4j/CVE-2021-44228` |
| aa22-074a-russia-mfa-printnightmare | Russian State-Sponsored Cyber Actors Gain Network Access by Exploiting Default MFA Protocols and “PrintNightmare” Vulnerability | FBI, CISA (AA22-074A) | 2022-03-15 | https://www.ic3.gov/CSA/2022/220316.pdf | multi-host / AD | 10 | none |
| aa24-290a-iran-bruteforce | Iranian Cyber Actors’ Brute Force and Credential Access Activity Compromises Critical Infrastructure Organizations | FBI, CISA, NSA, CSE, AFP, ASD’s ACSC (AA24-290A) | 2024-10-16 | https://www.ic3.gov/CSA/2024/241016.pdf | multi-host / AD | 17 | none |
| aa23-144a-volt-typhoon-lotl | People's Republic of China State-Sponsored Cyber Actor Living off the Land to Evade Detection | NSA, CISA, FBI, ACSC, CCCS, NCSC-NZ, NCSC-UK (AA23-144A; PDF Ver. 1.1, Jun 2023) | 2023-05-24 | https://www.ic3.gov/CSA/2023/230524.pdf | multi-host / AD | 13 | none |
| aa23-250a-manageengine-fortinet | Multiple Nation-State Threat Actors Exploit CVE-2022-47966 and CVE-2022-42475 | CISA, FBI, CNMF (AA23-250A) | 2023-09-07 | https://www.ic3.gov/CSA/2023/230907.pdf | closed-source / appliance → not reproducible | 29 | none |
| aa25-022a-ivanti-csa-chain | Threat Actors Chained Vulnerabilities in Ivanti Cloud Service Applications | CISA, FBI (AA25-022A) | 2025-01-22 | https://www.ic3.gov/CSA/2025/250122.pdf | closed-source / appliance → not reproducible | 15 | none |
| weak-aa21-042a-water-facility | Compromise of U.S. Water Treatment Facility | FBI, CISA, EPA, MS-ISAC (AA21-042A) | 2021-02-11 | https://www.ic3.gov/CSA/2021/210212.pdf | weak / incomplete → must block | 0 (≤2–3 abstract, low-confidence) | none |
| weak-pin-20221104-hacktivist-ddos | Hacktivists Use of DDoS Activity Causes Minor Impacts | FBI PIN 20221104-001 | 2022-11-04 | https://www.ic3.gov/CSA/2022/221104.pdf | weak / incomplete → must block | 0 (≤1–2 abstract) | none |

SHA-256 of every `source.pdf` is in its `report.md` header and `expected.md` header.

## Mix vs. brief

| category | brief | delivered | note |
|---|---|---|---|
| web + vulhub exact CVE | 5 | **4** | Only 4 FBI/NSA-hosted advisories with an incident narrative and a vulhub path for the named CVE were found. AA22-257A names the CVE as "likely", and the product is VMware Horizon, not Solr. So the vulhub image is a substitute that has the same CVE but runs a different product. AA24-016A covers 2 of its 3 CVEs. |
| multi-host / AD | 3 | 3 | AA23-144A replaces the planned AA22-277A (see below). |
| closed-source / appliance | 2 | 2 | AA23-250A (ManageEngine + FortiOS), AA25-022A (Ivanti CSA). |
| weak / incomplete | 2 | 2 | FBI products replace the planned CISA Sisense/Snowflake alerts (not downloadable). |

## Sourcing (owner decision 2026-11-16, via Lead)

- `www.cisa.gov` returns 403 (Akamai) from this host. It was not retried, and no browser User-Agent and no web.archive.org were used.
- All 11 PDFs were fetched with plain `curl` from `www.ic3.gov` (FBI co-publisher copies). The CSA index pages `https://www.ic3.gov/CSA/<year>` were used to find them.
- `media.defense.gov` (NSA) also returned "Access Denied" for AA22-277A. **AA22-277A was dropped.**
- Dropped from the first plan because no FBI/NSA copy exists or vulhub has no path: AA25-266A GeoServer, AA23-339A ColdFusion, AA22-174A (CISA-only); PaperCut CVE-2023-27350, Telerik CVE-2019-18935, ManageEngine CVE-2022-47966 / CVE-2021-40539, Zimbra CVE-2022-27925 (no vulhub path, 404 on 2026-11-16).

## How the keys were made

- I read each PDF myself. I did not run the CyberRange system or call any LLM API, and I did not read anything under `reports/overnight/evidence/`. The keys are independent of system output.
- `report.md` is the source wording. Only page furniture, sidebars, table layout, line wrapping and line-break hyphenation were removed. Draft text for long PDFs came from `reports/eval/extract_pages.py` and was then checked by hand. Omitted tables are named in each header.
- Every English quote in the 11 `expected.md` files was checked against `source.pdf.txt` + `report.md` with `reports/eval/check_quotes.py`. All source quotes were found. The only quotes not found are vulhub README lines (external, labelled EXTERNAL_ENRICHMENT) and two false hits where the regex spans two table cells.
- vulhub paths and image tags were read from the vulhub GitHub tree and `docker-compose.yml`/README on 2026-11-16.

## Points to watch when grading (common traps across the set)

- Many sources combine several victims into one advisory (AA23-347A, AA24-290A, AA24-249A, AA22-257A, AA25-022A, AA23-144A). The keys mark the scope of each step. The system must not join steps from different victims into one chain.
- Some steps are explicit failures or attempts in the source: AA23-250A B1, B14 and PsExec; AA24-290A Zerologon; AA25-022A VPN login and chain 2; AA21-042A TeamViewer ("cannot be confirmed").
- Some CVEs were only obtained, not exploited (AA24-249A: CVE-2021-26084). Some CVEs are explicitly unrelated (AA25-022A: CVE-2025-0282/0283).
