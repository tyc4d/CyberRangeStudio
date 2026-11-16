#!/usr/bin/env python3
"""eval-200 corpus step 1 (no LLM): list and download IC3 CSA PDFs.
Plain curl, default curl User-Agent, 1 request per >= 1.1 s. Index pages: https://www.ic3.gov/CSA/<year>.
Writes fixtures/cti-corpus/_index.json (all links found) and fixtures/cti-corpus/<id>/source.pdf.
Usage: fetch_corpus.py [CSA|PSA] [years...]"""
import html, json, pathlib, re, subprocess, sys, time
ROOT = pathlib.Path(__file__).resolve().parents[2]
C = ROOT / "fixtures/cti-corpus"
kind = sys.argv[1] if len(sys.argv) > 1 else "CSA"
years = sys.argv[2:] or [str(y) for y in range(2020, 2027)]
last = [0.0]
def curl(url, out):
    wait = 1.1 - (time.time() - last[0])
    if wait > 0: time.sleep(wait)
    r = subprocess.run(["curl", "-sS", "-L", "--max-time", "120", "-o", str(out), "-w", "%{http_code}", url], capture_output=True, text=True)
    last[0] = time.time()
    return r.stdout.strip(), r.stderr.strip()
idxf = C / "_index.json"
index = json.loads(idxf.read_text()) if idxf.exists() else []
seen = {e["url"] for e in index}
pat = re.compile(r'<a [^>]*href="(/%s/(\d{4})/[^"]+\.pdf)"[^>]*>(.*?)</a>.*?datetime="([0-9-]{10})' % kind, re.S)
for y in years:
    tmp = C / f"_idx-{kind}-{y}.html"
    code, err = curl(f"https://www.ic3.gov/{kind}/{y}", tmp)
    print(kind, y, code, err, flush=True)
    for href, yy, title, date in pat.findall(tmp.read_text(errors="replace")):
        url = "https://www.ic3.gov" + href
        if url in seen: continue
        seen.add(url)
        stem = href.rsplit("/", 1)[1][:-4]
        index.append({"id": f"{kind.lower()}-{yy}-{stem}", "kind": kind, "url": url,
                      "title": html.unescape(re.sub(r"<[^>]+>", "", title)).strip(), "date": date})
    tmp.unlink()
idxf.write_text(json.dumps(index, indent=1, ensure_ascii=False))
print("links", len(index), flush=True)
for e in index:
    d = C / e["id"]; pdf = d / "source.pdf"
    if pdf.exists() and pdf.stat().st_size > 0: continue
    d.mkdir(parents=True, exist_ok=True)
    code, err = curl(e["url"], pdf)
    e["http"] = code
    print(e["id"], code, pdf.stat().st_size if pdf.exists() else 0, err, flush=True)
    if code != "200" and pdf.exists(): pdf.rename(d / "fetch-error.bin")
idxf.write_text(json.dumps(index, indent=1, ensure_ascii=False))
