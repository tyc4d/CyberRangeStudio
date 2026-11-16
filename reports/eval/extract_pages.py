#!/usr/bin/env python3
"""Helper used by eval-cti to draft verbatim report.md text from a source PDF.

Usage: extract_pages.py SOURCE.pdf FIRST_PAGE LAST_PAGE [--drop REGEX] [--h HEADING] ...

--drop REGEX   drop whole lines that match (repeatable)
--h HEADING    if a paragraph starts with HEADING, split it out as "### HEADING"

It runs `pdftotext -f N -l N` per page, removes page furniture (TLP banners,
"Page x of y" footers, agency header lines), joins wrapped lines into
paragraphs, and turns bullet glyphs into "- " list items. It does not change
words. Output is a draft: the worker then checks it against the PDF and fixes
layout problems (sidebars, tables, code blocks) by hand.
"""
import re
import subprocess
import sys

FURNITURE = [
    r"^TLP:\s?(CLEAR|WHITE|AMBER|GREEN)$",
    r"^Page \d+ of \d+( \|.*)?$",
    r"^.*\| Product ID: .*$",
    r"^(FBI|CISA|NSA|US FBI)( \| [A-Z’' -]+)+$",
    r"^International Partnership$",
    r"^Co-Authored by:$",
]
BULLETS = "▪•●o"


def page_text(pdf, p):
    return subprocess.run(["pdftotext", "-f", str(p), "-l", str(p), pdf, "-"],
                          capture_output=True, text=True, check=True).stdout


def main():
    pdf, first, last = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    args = sys.argv[4:]
    drops, heads = [], []
    for flag, val in zip(args[0::2], args[1::2]):
        (drops if flag == "--drop" else heads).append(re.compile(val) if flag == "--drop" else val)
    furn = [re.compile(x) for x in FURNITURE] + drops
    paras, cur = [], []
    pending_bullet = False
    for p in range(first, last + 1):
        for raw in page_text(pdf, p).replace("\f", "\n").split("\n"):
            line = raw.strip()
            if any(f.match(line) for f in furn):
                continue
            if not line:
                if cur:
                    paras.append(" ".join(cur)); cur = []
                continue
            if line in BULLETS or (len(line) == 1 and line in BULLETS):
                if cur:
                    paras.append(" ".join(cur)); cur = []
                pending_bullet = True
                continue
            if line[0] in BULLETS and len(line) > 1 and line[1] == " ":
                if cur:
                    paras.append(" ".join(cur)); cur = []
                line = line[2:].strip(); pending_bullet = True
            if pending_bullet:
                cur = ["-", line]; pending_bullet = False
                continue
            cur.append(line)
    if cur:
        paras.append(" ".join(cur))
    out = []
    for para in paras:
        for h in heads:
            if para == h or para.startswith(h + " "):
                out.append("### " + h)
                para = para[len(h):].strip()
                break
        if para:
            out.append(para)
    print("\n\n".join(out))


if __name__ == "__main__":
    main()
