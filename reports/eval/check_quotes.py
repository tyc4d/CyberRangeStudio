#!/usr/bin/env python3
"""Check that every English quote ("...") in each new expected.md appears in the
fixture's source text (source.pdf.txt and report.md), after normalising
whitespace, quotes and line-break hyphenation. Prints quotes that are not found."""
import re, sys, pathlib
def norm(s):
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-").replace("[.]", ".")
    s = re.sub(r"-\s*\n\s*", "", s)          # line-break hyphenation
    s = re.sub(r"\s+", "", s)                 # ignore all whitespace
    s = s.replace("-", "")
    return s.lower()
bad = 0
for d in sys.argv[1:]:
    d = pathlib.Path(d)
    src = norm((d / "source.pdf.txt").read_text() + (d / "report.md").read_text())
    exp = (d / "expected.md").read_text()
    quotes = re.findall(r'"([^"\n]{20,}?)"', exp.replace("“", '"').replace("”", '"'))
    miss = []
    for q in quotes:
        parts = [p for p in re.split(r"…|\.\.\.", q) if len(p.strip()) > 8]
        if not all(norm(p) in src for p in parts):
            miss.append(q)
    print(f"{d.name}: {len(quotes)} quotes, {len(miss)} not found")
    for m in miss:
        print("   MISSING:", m[:160]); bad += 1
sys.exit(1 if bad else 0)
