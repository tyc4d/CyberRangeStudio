#!/usr/bin/env python3
"""eval-200 corpus step 2 (no LLM): text, report.md, dedupe, manifest.
For each fixtures/cti-corpus/<id>/source.pdf:
- source.pdf.txt = `pdftotext -layout source.pdf` (unchanged).
- report.md = header + source.pdf.txt with page furniture removed by RULES ONLY:
  (a) lines matching FURNITURE regexes (TLP banners, "Page x of y", bare page numbers);
  (b) repeated running headers/footers: a line (digits masked) that is among the first 3 or last 3
      non-empty lines of a page and recurs in that position on >= 50% of pages (only for PDFs with >= 3 pages).
  Form feeds are dropped; runs of > 2 blank lines are squeezed to 2. No other change to words.
- duplicates: same SHA-256, or same own advisory id (own_id(): 'Product ID: X' or the id after 'Alert Number') as an earlier item
  (index order) -> listed in excluded.csv, not in the manifest; folder kept out of git.
- category rule (on source.pdf.txt): has_cve = any CVE-yyyy-n; has_attack = >= 3 distinct T#### ids;
  category = "cve+attack" | "attack" | "cve" | "advisory-only".
- eligibility (eval-200 review R1/R2, Lead rulings 2026-11-16):
  * RIGHTS_FOREIGN: the text has a non-US copyright/licence notice (©, Crown copyright, Commonwealth of Australia,
    King in Right of Canada, Creative Commons Attribution, Open Government Licence) -> excluded "non-US copyright notice".
  * translation: the listing title has no Latin letters, or the id ends in -<2-letter language code> -> excluded.
  * superseded version: items with the same normalised title where the latest one has its own change record /
    version history -> the earlier ones are excluded "superseded version (latest: <id>)". A follow-up product that
    only refers to an earlier one ("update to previously published ...") and adds new content is a separate work.
  * companion part: an id of the form <base>-<word> (e.g. -quick_reference_guide) whose <base> item is excluded
    for rights -> excluded as part of that work.
  * THIRD_PARTY: code inside the document that carries its own licence notice -> kept, noted in rights_note and header.
- overlap_hand_keyed = SHA-256 equals a fixtures/cti-candidates/*/source.pdf, or same advisory id.
"""
import collections, csv, hashlib, json, pathlib, re, subprocess
ROOT = pathlib.Path(__file__).resolve().parents[2]
C = ROOT / "fixtures/cti-corpus"
FURN = [re.compile(x, re.I) for x in [
    r"^TLP:\s?(CLEAR|WHITE|AMBER|GREEN)\s*$", r"^Page \d+ (of|/) \d+\b.*$", r"^.*\|\s*Page \d+( of \d+)?\s*$",
    r"^\d{1,3}\s*$", r"^\d+\s*\|\s*Page\s*$", r"^\|\s*TLP:\s?(CLEAR|WHITE)\s*$"]]
PRODID = re.compile(r"Product ID:?\s*([A-Z]{1,2}\d{2}-\d{3}[A-Z]?)\b")
ALERTNO = re.compile(r"Alert Number.{0,400}?\b([A-Z]{2}-\d{6}-[A-Z]{2,3}|I-\d{6}-(?:CSA|PSA))\b", re.S)
def own_id(txt):
    """The document's OWN id only: 'Product ID: X' or the id printed after 'Alert Number'.
    Ids merely referenced in the text are not used."""
    m = PRODID.search(txt) or ALERTNO.search(txt[:8000])
    return m.group(1) if m else ""
RIGHTS_FOREIGN = re.compile(r"©|crown copyright|commonwealth of australia|king in right of canada|"
                            r"creative commons attribution|open government licen[cs]e", re.I)
THIRD_PARTY = re.compile(r"This file is Copyright .{0,60}licensed under|See license at https?://\S+", re.I)
CHANGE = re.compile(r"change record|version history", re.I)
def first_line(rx, txt):
    for l in txt.split("\n"):
        if rx.search(l): return re.sub(r"\s+", " ", l.strip())[:160]
    return ""
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def mask(s): return re.sub(r"\d+", "#", s.strip())
def clean(txt):
    pages = txt.split("\f")
    if pages and not pages[-1].strip(): pages = pages[:-1]
    rep = set()
    if len(pages) >= 3:
        cnt = collections.Counter()
        for pg in pages:
            ne = [mask(l) for l in pg.split("\n") if l.strip()]
            for k in set(ne[:3] + ne[-3:]): cnt[k] += 1
        rep = {k for k, v in cnt.items() if v >= max(2, len(pages) / 2)}
    out, dropped = [], 0
    for pg in pages:
        lines = pg.split("\n")
        ne_idx = [i for i, l in enumerate(lines) if l.strip()]
        edge = set(ne_idx[:3] + ne_idx[-3:])
        for i, l in enumerate(lines):
            s = l.strip()
            if s and (any(f.match(s) for f in FURN) or (i in edge and mask(s) in rep)):
                dropped += 1; continue
            out.append(l.rstrip())
    body = re.sub(r"\n{4,}", "\n\n\n", "\n".join(out)).strip() + "\n"
    return body, dropped
def pdfpages(p):
    r = subprocess.run(["pdfinfo", str(p)], capture_output=True, text=True)
    m = re.search(r"^Pages:\s+(\d+)", r.stdout, re.M); return int(m.group(1)) if m else 0
cand = {}
for d in (ROOT / "fixtures/cti-candidates").iterdir():
    if (d / "source.pdf").exists():
        cand[sha(d / "source.pdf")] = d.name
        t = (d / "source.pdf.txt").read_text(errors="replace") if (d / "source.pdf.txt").exists() else ""
        a = own_id(t) or (re.search(r"AA\d{2}-\d{3}[A-Z]", d.name.upper()) or [""])[0]
        if a: cand[a] = d.name
index = json.loads((C / "_index.json").read_text())
seen, rows, excl = {}, [], []
later_reissue, kept_date, texts = collections.defaultdict(list), {}, {}
for e in index:
    d = C / e["id"]; pdf = d / "source.pdf"
    if not pdf.exists():
        excl.append({**e, "reason": "download failed: " + str(e.get("http"))}); continue
    h = sha(pdf)
    head = pdf.read_bytes()[:5]
    if head != b"%PDF-":
        excl.append({**e, "sha256": h, "reason": "not a PDF"}); continue
    txtp = d / "source.pdf.txt"
    subprocess.run(["pdftotext", "-layout", str(pdf), str(txtp)], check=True)
    txt = txtp.read_text(errors="replace")
    adv = own_id(txt)
    dup = seen.get(h) or (seen.get(adv) if adv else None)
    if dup and h not in seen and dup in later_reissue and e["date"] > kept_date.get(dup, ""):
        later_reissue[dup].append(e["id"])
    if dup:
        excl.append({**e, "sha256": h, "reason": f"duplicate of {dup} ({'same sha256' if h in seen else 'same advisory id ' + adv})"}); continue
    seen[h] = e["id"]
    if adv: seen[adv] = e["id"]
    kept_date[e["id"]] = e["date"]; later_reissue[e["id"]] = []
    body, dropped = clean(txt)
    if len(body.strip()) < 500:
        excl.append({**e, "sha256": h, "reason": f"too little extractable text ({len(body.strip())} chars; scanned/image PDF?)"}); continue
    cves = set(re.findall(r"CVE-\d{4}-\d{4,}", txt)); techs = set(re.findall(r"\bT\d{4}(?:\.\d{3})?\b", txt))
    cat = ("cve+attack" if cves and len(techs) >= 3 else "attack" if len(techs) >= 3 else "cve" if cves else "advisory-only")
    pages = pdfpages(pdf)
    foreign = first_line(RIGHTS_FOREIGN, txt)
    if foreign:
        lic = f"> - License: NOT U.S. public domain — the document carries a non-US notice: \"{foreign}\" (excluded, see excluded.csv)\n"
    else:
        lic = ("> - Rights: published by U.S. government agencies (FBI IC3 copy); rule scan in `reports/eval/build_corpus.py` found no non-US "
               "copyright or licence notice. Some are joint advisories with non-US co-authors; public-domain status of co-authored parts not determined.\n")
    tp = first_line(THIRD_PARTY, txt)
    if tp: lic += f"> - Note: contains third-party code with its own licence notice (\"{tp}\"); its licence applies to that code\n"
    if not re.search(r"[A-Za-z]", e["title"]) or re.search(r"-[a-z]{2}$", e["id"]):
        lic += f"> - Translation of {re.sub(r'-[a-z]{2}$', '', e['id'])} (excluded, see excluded.csv)\n"
    hdr = (f"# {e['title']}\n\n"
           f"> - Publisher: FBI Internet Crime Complaint Center (IC3), {e['kind']} listing{' — advisory id ' + adv if adv else ''}\n"
           f"> - Date: {e['date']}\n> - URL: {e['url']}\n> - PDF SHA-256: {h} (`source.pdf`, {pages} pages)\n"
           + lic +
           f"> - Text: `pdftotext -layout` output; only page furniture removed by `reports/eval/build_corpus.py` ({dropped} lines). No other edits.\n\n")
    (d / "report.md").write_text(hdr + body, encoding="utf-8")
    if foreign:
        excl.append({**e, "sha256": h, "reason": f'non-US copyright notice: "{foreign}"'}); continue
    if not re.search(r"[A-Za-z]", e["title"]) or re.search(r"-[a-z]{2}$", e["id"]):
        excl.append({**e, "sha256": h, "reason": f"translation of {re.sub(r'-[a-z]{2}$', '', e['id'])}"}); continue
    cm = re.match(r"(csa-\d{4}-\d{6})-[a-z_]{3,}$", e["id"])
    if cm and any(x["id"] == cm.group(1) and x["reason"].startswith("non-US") for x in excl):
        excl.append({**e, "sha256": h, "reason": f"companion part of {cm.group(1)} (same publication; excluded for non-US copyright notice)"}); continue
    texts[e["id"]] = txt
    ov = cand.get(h) or (cand.get(adv) if adv else "") or ""
    rows.append({"id": e["id"], "title": e["title"], "date": e["date"], "url": e["url"], "sha256": h, "pages": pages,
                 "chars": len(body), "category": cat, "advisory_id": adv, "n_cve": len(cves), "n_attack_ids": len(techs),
                 "furniture_lines_removed": dropped, "pdf_bytes": pdf.stat().st_size, "overlap_hand_keyed": ov,
                 "rights_note": ("third-party code licence: " + tp) if tp else "", "later_reissue_not_run": ""})
# superseded versions: same normalised title, latest has its own change record / version history
fam = collections.defaultdict(list)
for r in rows: fam[re.sub(r"[^a-z0-9]", "", r["title"].lower())].append(r)
for g in fam.values():
    if len(g) < 2: continue
    g.sort(key=lambda r: r["date"]); latest = g[-1]
    if not CHANGE.search(texts[latest["id"]]): continue
    for r in g[:-1]:
        rows.remove(r)
        excl.append({**r, "reason": f"superseded version (latest: {latest['id']}, {latest['date']}; its change record lists earlier versions)"})
for r in rows: r["later_reissue_not_run"] = " ".join(later_reissue.get(r["id"], []))
with open(C / "manifest.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
with open(C / "excluded.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["id", "url", "title", "date", "sha256", "reason"], extrasaction="ignore"); w.writeheader(); w.writerows(excl)
print("usable", len(rows), "excluded", len(excl), "pdf MB", round(sum(r["pdf_bytes"] for r in rows) / 1e6, 1),
      collections.Counter(r["category"] for r in rows), "overlap", [r["overlap_hand_keyed"] for r in rows if r["overlap_hand_keyed"]])
# runs of excluded items stay on disk but out of git; run.log files of eligible items are kept (sanitised)
R = ROOT / "reports/eval/runs-200"
if R.exists():
    (R / ".gitignore").write_text("# generated by reports/eval/build_corpus.py: runs of excluded items (see excluded.csv)\n" +
                                  "".join(f"/{e['id']}/\n" for e in excl if (R / e["id"]).exists()) + "!/*/run.log\n")
# excluded folders (duplicates, no text) stay on disk for re-checking but out of git
(C / ".gitignore").write_text("# generated by reports/eval/build_corpus.py: excluded items (see excluded.csv)\n" +
                              "".join(f"/{e['id']}/\n" for e in excl if (C / e["id"]).exists()))
