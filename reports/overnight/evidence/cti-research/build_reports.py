#!/usr/bin/env python3
"""Rebuild fixtures/cti-candidates/<slug>/report.md from the pdftotext output.

The report body is the source's own wording. The only edits are mechanical:
page headers/footers and margin side-headings are dropped, layout indentation is
removed, and hard-wrapped lines are re-joined into paragraphs. No sentence is
added, reworded or reordered. Each entry lists the exact line ranges taken from
`source.pdf.txt` (1-indexed, inclusive) so the result can be re-checked.

Usage: python build_reports.py <fixtures/cti-candidates dir>
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

RETRIEVED = "2026-11-15"

# (start, end, left-column cut, mode)
#   mode "p"   : prose, re-join wrapped lines into paragraphs
#   mode "pre" : keep lines as-is (commands, tables)
#   a bare string is emitted verbatim as a markdown line (headings we add are
#   limited to the source's own section titles)
SPECS = {
    "aa22-320a-log4shell-horizon": {
        "title": "CISA AA22-320A — Iranian Government-Sponsored APT Actors Compromise Federal Network, Deploy Crypto Miner, Credential Harvester",
        "meta": [
            "Publisher: CISA and FBI, Joint Cybersecurity Advisory, Product ID AA22-320A, November 16, 2022 (TLP:CLEAR)",
            "Web page: https://www.cisa.gov/news-events/cybersecurity-advisories/aa22-320a",
            "PDF: https://www.cisa.gov/sites/default/files/publications/aa22-320a_joint_csa_iranian_government-sponsored_apt_actors_compromise_federal%20network_deploy_crypto%20miner_credential_harvester.pdf",
            "PDF SHA-256: beacab7d0ed36ddc4e51b3e7a00e24ac9c612bfb29dffde3ffef01597b4109e2 (`source.pdf`, 14 pages)",
            "License: U.S. Government work, TLP:CLEAR",
            "Scope of this file: SUMMARY and TECHNICAL DETAILS (advisory pages 1–4), verbatim. The ATT&CK table, incident-response and mitigation sections are in `source.pdf.txt`.",
        ],
        "parts": [
            "## SUMMARY",
            (11, 31, 0, "p"),
            "## TECHNICAL DETAILS",
            (46, 48, 0, "p"),
            "### Overview",
            (51, 73, 0, "p"),
            "### Threat Actor Activity",
            (76, 80, 0, "p"),
            (81, 83, 0, "pre"),
            (92, 96, 0, "p"),
            (97, 108, 0, "list"),
            (110, 110, 0, "p"),
            (111, 116, 0, "p"),
            (117, 123, 0, "list"),
            (126, 133, 0, "pjoin"),
            (140, 145, 0, "p"),
            (146, 147, 0, "pre"),
            (148, 152, 0, "p"),
        ],
    },
    "equifax-2017-struts-db": {
        "title": "GAO-18-559 — Data Protection: Actions Taken by Equifax and Federal Agencies in Response to the 2017 Breach (breach narrative excerpt)",
        "meta": [
            "Publisher: U.S. Government Accountability Office, report GAO-18-559, August 2018",
            "Web page: https://www.gao.gov/products/gao-18-559",
            "PDF: https://www.gao.gov/assets/gao-18-559.pdf",
            "PDF SHA-256: 7f352448054fd5c5faabf799e5895ae2a6780edc1136e22ca9e300cfca6245f8 (`source.pdf`, 40 pages)",
            "License: U.S. Government work (GAO reports are not subject to U.S. copyright)",
            "Scope of this file: the breach narrative, report pages 10–16, verbatim. Margin headings are kept as section titles; footnotes 24–27 are kept as notes; unrelated footnotes and the figure are omitted. Superscript footnote numbers appear inline as plain digits (e.g. \"portal25\"), as extracted from the PDF.",
        ],
        "parts": [
            "## Attackers Exploited Vulnerabilities That Equifax Subsequently Reported Taking Actions to Address",
            (611, 622, 23, "p"),
            "## Attackers Identified and Exploited Vulnerabilities to Steal Data",
            (640, 672, 31, "pjoin"),
            (689, 706, 0, "p"),
            "## After Becoming Aware of the Attack, Equifax Took Steps to Block the Attackers",
            (717, 719, 42, "pjoin"),
            (721, 730, 42, "pjoin"),
            (734, 754, 29, "p"),
            "## Equifax Identified Several Factors That the Attacker Exploited During the Breach",
            (757, 759, 29, "pjoin"),
            (761, 769, 29, "pjoin"),
            (783, 817, 0, "pjoin"),
            (831, 851, 26, "p"),
            "## Notes (report footnotes 24–27)",
            (678, 680, 31, "p"),
            (681, 683, 31, "p"),
            (771, 777, 29, "p"),
            (820, 825, 0, "p"),
        ],
    },
}

FURNITURE = re.compile(r"^\s*(Page \d+( of \d+)?\b.*|TLP: ?CLEAR.*|``)\s*$")
BULLET = re.compile(r"^\s*([•●]|o\s)")


def paragraphs(lines: list[str], cut: int) -> list[str]:
    out: list[str] = []
    cur: list[str] = []
    for raw in lines:
        line = raw[cut:] if cut else raw
        if FURNITURE.match(line):
            continue
        text = line.strip()
        if not text:
            if cur:
                out.append(" ".join(cur))
                cur = []
            continue
        if BULLET.match(text) and cur:
            out.append(" ".join(cur))
            cur = []
        if BULLET.match(text):
            text = "- " + re.sub(r"^([•●]|o)\s*", "", text)
        cur.append(text)
    if cur:
        out.append(" ".join(cur))
    return out


def build(slug: str, spec: dict, root: Path) -> None:
    src = (root / slug / "source.pdf.txt").read_text(encoding="utf-8").split("\n")
    body: list[str] = []
    carry = ""  # paragraph continuing across a page break
    for part in spec["parts"]:
        if isinstance(part, str):
            body.append(part)
            continue
        start, end, cut, mode = part
        lines = src[start - 1 : end]
        if mode == "pre":
            block = [l.strip() for l in lines if l.strip()]
            body.append("```\n" + "\n".join(block) + "\n```")
            continue
        paras = paragraphs(lines, cut)
        if carry:
            paras[0] = carry + " " + paras[0]
            carry = ""
        if mode == "pjoin":
            carry = paras.pop()
        body.extend(paras)
    if carry:
        body.append(carry)
    head = [f"# {spec['title']}", ""]
    head += [f"> - {m}" for m in spec["meta"]]
    head += [
        f"> - Retrieved: {RETRIEVED}",
        "> - Wording: the text below is the source's own wording; only page furniture, layout "
        "indentation and line wrapping were removed (see `reports/overnight/evidence/cti-research/build_reports.py`).",
        "",
    ]
    text = "\n".join(head) + "\n" + "\n\n".join(body) + "\n"
    # collapse the runs of spaces pdftotext leaves inside a line
    text = re.sub(r"(?<=\S) {2,}(?=\S)", " ", text)
    (root / slug / "report.md").write_text(text, encoding="utf-8")
    print(slug, len(text), "chars")


if __name__ == "__main__":
    root = Path(sys.argv[1])
    for slug, spec in SPECS.items():
        build(slug, spec, root)
