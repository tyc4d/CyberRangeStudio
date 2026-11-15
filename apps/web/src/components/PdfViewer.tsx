// PDF viewer for the original uploaded report (pdf.js). Renders pages lazily with a text
// layer, and can locate a passage: search the PDF text, highlight the match and scroll to it.
import { t } from "../i18n";
import { useEffect, useRef, useState } from "react";
import type { PDFDocumentProxy, PDFPageProxy } from "pdfjs-dist";
import { api } from "../lib/api";
import "./PdfViewer.css";

type PdfJs = typeof import("pdfjs-dist");
type TextContent = Awaited<ReturnType<PDFPageProxy["getTextContent"]>>;

let pdfjsPromise: Promise<PdfJs> | null = null;
/** pdf.js is loaded on demand (own chunk) with its bundled worker; nothing comes from a CDN. */
function loadPdfjs(): Promise<PdfJs> {
  return (pdfjsPromise ??= Promise.all([
    import("pdfjs-dist"),
    import("pdfjs-dist/build/pdf.worker.min.mjs?url"),
  ]).then(([lib, worker]) => {
    lib.GlobalWorkerOptions.workerSrc = worker.default;
    return lib;
  }));
}

/* ---------- source loading ---------- */

/** loading = asking the backend; none = scenario has no PDF original; error = could not ask. */
export type PdfSourceState = "loading" | "ready" | "none" | "error";

/** Fetch /api/scenario/{id}/source/file. `data` is set only when the scenario really has a PDF. */
export function usePdfSource(scenarioId: string | null | undefined): { state: PdfSourceState; data: ArrayBuffer | null } {
  const [s, setS] = useState<{ state: PdfSourceState; data: ArrayBuffer | null }>({ state: scenarioId ? "loading" : "none", data: null });
  useEffect(() => {
    if (!scenarioId) { setS({ state: "none", data: null }); return; }
    let live = true;
    setS({ state: "loading", data: null });
    api.getSourceFile(scenarioId)
      .then((f) => {
        if (!live) return;
        const head = f ? new TextDecoder("latin1").decode(new Uint8Array(f.data, 0, Math.min(5, f.data.byteLength))) : "";
        const isPdf = !!f && (f.contentType.includes("pdf") || head === "%PDF-");
        setS(isPdf ? { state: "ready", data: f!.data } : { state: "none", data: null });
      })
      .catch(() => { if (live) setS({ state: "error", data: null }); });
    return () => { live = false; };
  }, [scenarioId]);
  return s;
}

/* ---------- text search ---------- */

const QUOTE_SINGLE = "‘’‚‛′`´";
const QUOTE_DOUBLE = "“”„‟″«»";
const DASHES = "‐‑‒–—―−";

/** Fold one character for matching: NFKC, lower-case, unify quotes/dashes, drop whitespace and soft hyphens. */
function foldChar(ch: string): string {
  let out = "";
  for (const c of ch.normalize("NFKC").toLowerCase()) {
    if (/\s/.test(c) || c === "­" || c === "​" || c === "﻿") continue;
    out += QUOTE_SINGLE.includes(c) ? "'" : QUOTE_DOUBLE.includes(c) ? '"' : DASHES.includes(c) ? "-" : c;
  }
  return out;
}
function foldText(s: string): string {
  let out = "";
  for (const ch of s) out += foldChar(ch);
  return out;
}

/** Folded page text plus, per folded character, where it came from (text item, offset, length). */
interface PageIndex { text: string; item: number[]; off: number[]; len: number[] }

function buildIndex(strs: string[]): PageIndex {
  const idx: PageIndex = { text: "", item: [], off: [], len: [] };
  const parts: string[] = [];
  strs.forEach((str, i) => {
    let o = 0;
    for (const ch of str) {
      const f = foldChar(ch);
      for (let k = 0; k < f.length; k++) { idx.item.push(i); idx.off.push(o); idx.len.push(ch.length); }
      parts.push(f);
      o += ch.length;
    }
  });
  idx.text = parts.join("");
  return idx;
}

interface Hit { page: number; start: number; end: number; group: number; partial: boolean }

const MIN_QUERY = 3;
const CHUNK = 32;

/**
 * Find the first candidate that occurs in the PDF. Groups are in priority order; inside a
 * group a whole-string match of any candidate wins over a partial one. A partial match is a
 * 32-character window of the candidate found verbatim, then grown as far as the text agrees —
 * it covers quotes that were re-wrapped, hyphenated or lightly edited between PDF and analysis.
 */
function locate(pages: PageIndex[], groups: string[][]): Hit | null {
  for (let g = 0; g < groups.length; g++) {
    const qs = [...new Set(groups[g].map(foldText))].filter((q) => q.length >= MIN_QUERY);
    for (const q of qs) {
      for (let p = 0; p < pages.length; p++) {
        const at = pages[p].text.indexOf(q);
        if (at >= 0) return { page: p, start: at, end: at + q.length, group: g, partial: false };
      }
    }
    for (const q of qs) {
      if (q.length <= CHUNK + 8) continue;
      for (let k = 0; k + CHUNK <= q.length; k += CHUNK / 2) {
        const chunk = q.slice(k, k + CHUNK);
        for (let p = 0; p < pages.length; p++) {
          const t = pages[p].text;
          const at = t.indexOf(chunk);
          if (at < 0) continue;
          let s = at, qs0 = k;
          while (s > 0 && qs0 > 0 && t[s - 1] === q[qs0 - 1]) { s--; qs0--; }
          let e = at + CHUNK, qe = k + CHUNK;
          while (e < t.length && qe < q.length && t[e] === q[qe]) { e++; qe++; }
          return { page: p, start: s, end: e, group: g, partial: !(qs0 === 0 && qe === q.length) };
        }
      }
    }
  }
  return null;
}

/** Map a folded-text range back to [from, to) offsets inside each text item it touches. */
function hitRanges(idx: PageIndex, start: number, end: number): Map<number, [number, number]> {
  const m = new Map<number, [number, number]>();
  for (let i = start; i < end; i++) {
    const it = idx.item[i], from = idx.off[i], to = idx.off[i] + idx.len[i];
    const cur = m.get(it);
    if (!cur) m.set(it, [from, to]);
    else { cur[0] = Math.min(cur[0], from); cur[1] = Math.max(cur[1], to); }
  }
  return m;
}

/* ---------- component ---------- */

/** What to locate. `groups` are candidate strings in priority order; bump `seq` to locate again. */
export interface PdfAnchor { groups: string[][]; seq: number }
export type PdfLocateResult =
  | { seq: number; found: true; group: number; page: number; partial: boolean }
  | { seq: number; found: false };

interface PageModel { page: PDFPageProxy; w: number; h: number; content: TextContent; strs: string[]; index: PageIndex }
interface Model { doc: PDFDocumentProxy; pages: PageModel[] }
interface View {
  pageEls: HTMLDivElement[];
  renderPage: (i: number) => Promise<void>;
  applyHit: (i: number) => void;
}

const ZOOMS = [0.75, 1, 1.25, 1.5, 2];

export function PdfViewer({ data, filename, anchor, onLocated }: {
  data: ArrayBuffer;
  filename?: string;
  anchor?: PdfAnchor | null;
  onLocated?: (r: PdfLocateResult) => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const pagesRef = useRef<HTMLDivElement>(null);
  const [model, setModel] = useState<Model | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [width, setWidth] = useState(0);
  const [zoom, setZoom] = useState(1);
  const [cur, setCur] = useState(1);

  const view = useRef<View | null>(null);
  const hit = useRef<{ page: number; ranges: Map<number, [number, number]> } | null>(null);
  const marked = useRef<{ el: HTMLElement; str: string }[]>([]);
  const onLocatedRef = useRef(onLocated);
  onLocatedRef.current = onLocated;

  // Load the document, then every page's size and text (needed for layout and for search).
  useEffect(() => {
    let live = true;
    let task: { destroy: () => Promise<void> } | null = null;
    setModel(null);
    setError(null);
    (async () => {
      const lib = await loadPdfjs();
      if (!live) return;
      // pdf.js takes ownership of the buffer it is given, so hand it a copy.
      const loading = lib.getDocument({ data: new Uint8Array(data.slice(0)) });
      task = loading;
      const doc = await loading.promise;
      const pages: PageModel[] = [];
      for (let n = 1; n <= doc.numPages; n++) {
        const page = await doc.getPage(n);
        const content = await page.getTextContent();
        if (!live) return;
        const vp = page.getViewport({ scale: 1 });
        const strs = content.items.map((it) => ("str" in it ? it.str : ""));
        pages.push({ page, w: vp.width, h: vp.height, content, strs, index: buildIndex(strs) });
      }
      if (live) setModel({ doc, pages });
    })().catch((e: unknown) => {
      if (live) setError(e instanceof Error ? e.message : String(e));
    });
    return () => { live = false; void task?.destroy(); };
  }, [data]);

  // Track the available width so pages fit the pane.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    let t: number | undefined;
    const measure = () => setWidth(el.clientWidth);
    measure();
    const ro = new ResizeObserver(() => { window.clearTimeout(t); t = window.setTimeout(measure, 150); });
    ro.observe(el);
    return () => { ro.disconnect(); window.clearTimeout(t); };
  }, []);

  const clearMarks = () => {
    for (const m of marked.current) m.el.textContent = m.str;
    marked.current = [];
  };

  const goToHit = async (smooth: boolean) => {
    const v = view.current, h = hit.current, sc = scrollRef.current;
    if (!v || !h || !sc) return;
    await v.renderPage(h.page);
    if (view.current !== v || hit.current !== h) return; // superseded while rendering
    const pageEl = v.pageEls[h.page];
    const mark = pageEl.querySelector<HTMLElement>("mark.pdfv-hit");
    const target = mark ?? pageEl;
    const top = target.getBoundingClientRect().top - sc.getBoundingClientRect().top + sc.scrollTop - (mark ? sc.clientHeight * 0.3 : 0);
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    sc.scrollTo({ top: Math.max(0, top), behavior: smooth && !reduce ? "smooth" : "auto" });
    pageEl.classList.remove("pdfv-flash");
    void pageEl.offsetWidth; // restart the animation
    pageEl.classList.add("pdfv-flash");
  };

  // Lay out page placeholders at the current scale and render pages as they come near the viewport.
  useEffect(() => {
    const sc = scrollRef.current, host = pagesRef.current;
    if (!model || !sc || !host || width <= 0) return;
    let live = true;
    const maxW = Math.max(...model.pages.map((p) => p.w));
    const scale = (Math.max(200, width - 26) / maxW) * zoom;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const tasks: { cancel: () => void }[] = [];
    const rendered: (Promise<void> | undefined)[] = [];
    const textDivs: (HTMLElement[] | undefined)[] = [];
    marked.current = []; // the old text layers are about to be discarded

    host.textContent = "";
    const pageEls = model.pages.map((p, i) => {
      const el = document.createElement("div");
      el.className = "pdfv-page";
      el.dataset.page = String(i + 1);
      el.style.width = `${Math.floor(p.w * scale)}px`;
      el.style.height = `${Math.floor(p.h * scale)}px`;
      el.style.setProperty("--total-scale-factor", String(scale));
      host.appendChild(el);
      return el;
    });

    const applyHit = (i: number) => {
      const h = hit.current, divs = textDivs[i];
      if (!h || h.page !== i || !divs) return;
      for (const [item, [from, to]] of h.ranges) {
        const el = divs[item], str = model.pages[i].strs[item];
        if (!el || str === undefined || from >= to) continue;
        const mark = document.createElement("mark");
        mark.className = "pdfv-hit";
        mark.textContent = str.slice(from, to);
        el.textContent = "";
        el.append(str.slice(0, from), mark, str.slice(to));
        marked.current.push({ el, str });
      }
    };

    const renderPage = (i: number): Promise<void> => (rendered[i] ??= (async () => {
      const lib = await loadPdfjs();
      const p = model.pages[i], el = pageEls[i];
      if (!live) return;
      const viewport = p.page.getViewport({ scale });
      const canvas = document.createElement("canvas");
      canvas.width = Math.floor(viewport.width * dpr);
      canvas.height = Math.floor(viewport.height * dpr);
      const layer = document.createElement("div");
      layer.className = "textLayer";
      el.append(canvas, layer);
      const task = p.page.render({ canvas, viewport, transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : undefined });
      tasks.push(task);
      const text = new lib.TextLayer({ textContentSource: p.content, container: layer, viewport });
      tasks.push(text);
      await Promise.all([task.promise, text.render()]);
      if (!live) return;
      textDivs[i] = text.textDivs;
      applyHit(i);
    })().catch((e: unknown) => {
      // A cancelled render (layout rebuilt) is expected; anything else leaves the page blank.
      if (live && (e as { name?: string })?.name !== "RenderingCancelledException") console.warn("PDF page render failed", e);
    }));

    const io = new IntersectionObserver((entries) => {
      for (const en of entries) if (en.isIntersecting) void renderPage(Number((en.target as HTMLElement).dataset.page) - 1);
    }, { root: sc, rootMargin: "800px 0px" });
    pageEls.forEach((el) => io.observe(el));

    let raf = 0;
    const onScroll = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        const line = sc.scrollTop + sc.clientHeight / 3;
        let n = 1;
        pageEls.forEach((el, i) => { if (el.offsetTop <= line) n = i + 1; });
        setCur(n);
      });
    };
    sc.addEventListener("scroll", onScroll, { passive: true });
    onScroll();

    const v: View = { pageEls, renderPage, applyHit };
    view.current = v;
    void goToHit(false); // keep the located passage in view across zoom / resize

    return () => {
      live = false;
      if (view.current === v) view.current = null;
      io.disconnect();
      sc.removeEventListener("scroll", onScroll);
      cancelAnimationFrame(raf);
      for (const t of tasks) { try { t.cancel(); } catch { /* already finished */ } }
    };
  }, [model, width, zoom]);

  // Locate the requested passage.
  const seq = anchor?.seq;
  useEffect(() => {
    if (!model) return;
    clearMarks();
    hit.current = null;
    if (!anchor) return;
    const found = locate(model.pages.map((p) => p.index), anchor.groups);
    if (!found) { onLocatedRef.current?.({ seq: anchor.seq, found: false }); return; }
    hit.current = { page: found.page, ranges: hitRanges(model.pages[found.page].index, found.start, found.end) };
    view.current?.applyHit(found.page);
    void goToHit(true);
    onLocatedRef.current?.({ seq: anchor.seq, found: true, group: found.group, page: found.page + 1, partial: found.partial });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model, seq]);

  const zi = ZOOMS.indexOf(zoom);
  return (
    <div className="pdfv" data-testid="pdf-viewer">
      <div className="pdfv-bar">
        <span className="name" title={filename}>{filename || t("pdf.original")}</span>
        <span className="spacer" />
        {model && <span className="pageno">{t("pdf.page", { cur, total: model.pages.length })}</span>}
        <button onClick={() => setZoom(ZOOMS[Math.max(0, zi - 1)])} disabled={!model || zi <= 0} aria-label={t("pdf.zoomOut")}>−</button>
        <span className="pageno">{Math.round(zoom * 100)}%</span>
        <button onClick={() => setZoom(ZOOMS[Math.min(ZOOMS.length - 1, zi + 1)])} disabled={!model || zi >= ZOOMS.length - 1} aria-label={t("pdf.zoomIn")}>＋</button>
      </div>
      <div className="pdfv-scroll" ref={scrollRef}>
        {error ? (
          <div className="pdfv-status">{t("pdf.error", { error })}</div>
        ) : !model ? (
          <div className="pdfv-status"><span className="spinner" /> {t("pdf.loading")}</div>
        ) : null}
        <div ref={pagesRef} />
      </div>
    </div>
  );
}
