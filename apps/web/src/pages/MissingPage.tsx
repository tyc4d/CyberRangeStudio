import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { MissingItem, ScenarioIR } from "@contracts";
import { api, ApiError } from "../lib/api";
import { useAction } from "../lib/hooks";
import { useScenario } from "../lib/scenario";
import { ApiNotice, Empty, NextStep, PageHead, ScenarioGate, SourceTag } from "../components/ui";
import { PdfViewer, usePdfSource, type PdfAnchor, type PdfLocateResult } from "../components/PdfViewer";

/* ---------- defensive readers (backend fields may still be changing) ---------- */

const str = (v: unknown): string => (typeof v === "string" ? v.trim() : typeof v === "number" ? String(v) : "");
const obj = (v: unknown): Record<string, unknown> | null => (v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null);
const pick = (o: Record<string, unknown>, ...keys: string[]): string => { for (const k of keys) { const v = str(o[k]); if (v) return v; } return ""; };
const hasCJK = (t: string) => /[\u3400-\u9fff]/.test(t);

/* ---------- anchor: where the report actually talks about this item ---------- */

/**
 * The passage the backend is confident this item relates to. Only `anchor` is trusted;
 * there is deliberately no keyword search fallback — an item without an anchor is shown
 * as "no clear passage" instead of highlighting something loosely related.
 */
interface Anchor { page?: number; quote?: string; evidenceRef?: string; /** Source wording the backend matched the evidence quote to, when it recorded one. */ matched?: string }

function readAnchor(item: MissingItem, ir: ScenarioIR): Anchor | null {
  const a = obj((item as unknown as Record<string, unknown>).anchor);
  if (!a) return null;
  const pageN = Number(a.page);
  const page = Number.isFinite(pageN) && pageN >= 1 ? Math.floor(pageN) : undefined;
  const evidenceRef = str(a.evidence_ref) || undefined;
  const ev = evidenceRef ? (ir.evidence ?? []).find((e) => e.id === evidenceRef) : undefined;
  const quote = str(a.quote) || str(ev?.quote);
  if (!quote && !page) return null;
  return { page, quote: quote || undefined, evidenceRef, matched: str((ev as unknown as Record<string, unknown> | undefined)?.matched_text) || undefined };
}

type Located =
  | { itemId: string; state: "searching" }
  /** Quote found and highlighted. `page` is where it was found; `claimed` is the page the backend named. */
  | { itemId: string; state: "found"; where: string; partial: boolean; mismatch?: string }
  /** Jumped to the page the backend named, but the quote itself could not be highlighted. */
  | { itemId: string; state: "page-only"; page: number }
  | { itemId: string; state: "notfound" };

/* ---------- plain-text original (scenarios imported without a PDF) ---------- */

const QUOTES_1 = "‘’‚‛′`´", QUOTES_2 = "“”„‟″«»", DASHES = "‐‑‒–—―−";
function fold(ch: string): string {
  let out = "";
  for (const c of ch.normalize("NFKC").toLowerCase()) {
    if (/\s/.test(c) || c === "\u00ad" || c === "\u200b" || c === "\ufeff") continue;
    out += QUOTES_1.includes(c) ? "'" : QUOTES_2.includes(c) ? '"' : DASHES.includes(c) ? "-" : c;
  }
  return out;
}
/** Inline ATT&CK annotations such as [T1190] / [TA0001]; ignored on both sides, like the backend's verbatim check. */
const ATTACK_TAG = /\s*\[TA?\d{4}(?:\.\d{3})?\]/g;
/**
 * Whole-quote match only (ignoring case, whitespace, quote/dash variants and ATT&CK tags).
 * No partial or keyword matching: a quote that is not in the text is reported as not found.
 */
export function findQuote(text: string, quote: string): [number, number] | null {
  let q = "";
  for (const ch of quote.replace(ATTACK_TAG, "")) q += fold(ch);
  if (q.length < 3) return null;
  const skipTo = new Map<number, number>();
  for (const m of text.matchAll(ATTACK_TAG)) skipTo.set(m.index ?? 0, (m.index ?? 0) + m[0].length);
  const parts: string[] = [], at: number[] = [], len: number[] = [];
  let o = 0, skipUntil = 0;
  for (const ch of text) {
    const end = skipTo.get(o);
    if (end !== undefined) skipUntil = Math.max(skipUntil, end);
    if (o >= skipUntil) {
      const f = fold(ch);
      for (let k = 0; k < f.length; k++) { at.push(o); len.push(ch.length); }
      parts.push(f);
    }
    o += ch.length;
  }
  const i = parts.join("").indexOf(q);
  if (i < 0) return null;
  const j = i + q.length - 1;
  return [at[i], at[j] + len[j]];
}

/** `alts` are other wordings of the same passage (e.g. the source text the backend matched the quote to). */
export interface TextTarget { quote: string; alts?: string[]; seq: number }
export type TextLocateResult = { seq: number; found: boolean; line?: number };

/** Read-only view of the imported text; highlights and scrolls to one exact quote. */
export function SourceTextViewer({ text, title, mono, target, onLocated }: {
  text: string; title?: string; mono?: boolean;
  target?: TextTarget | null;
  onLocated?: (r: TextLocateResult) => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const markRef = useRef<HTMLElement>(null);
  const cb = useRef(onLocated);
  cb.current = onLocated;
  const quote = target?.quote, seq = target?.seq, alts = target?.alts?.join("\u0000") ?? "";
  const range = useMemo(() => {
    for (const q of [quote, ...alts.split("\u0000")]) { const r = q ? findQuote(text, q) : null; if (r) return r; }
    return null;
  }, [text, quote, alts]);

  useEffect(() => {
    if (seq === undefined) return;
    cb.current?.({ seq, found: !!range, line: range ? text.slice(0, range[0]).split("\n").length : undefined });
    const sc = scrollRef.current, mark = markRef.current;
    if (!range || !sc || !mark) return;
    const top = mark.getBoundingClientRect().top - sc.getBoundingClientRect().top + sc.scrollTop - sc.clientHeight * 0.3;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    sc.scrollTo({ top: Math.max(0, top), behavior: reduce ? "auto" : "smooth" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seq, range]);

  return (
    <div className="pdfv" data-testid="source-text-viewer">
      <div className="pdfv-bar">
        <span className="name" title={title}>{title || "匯入的原文"}</span>
        <span className="spacer" />
        <span className="pageno">{text.length.toLocaleString()} 字元</span>
      </div>
      <div className="pdfv-scroll" ref={scrollRef} tabIndex={0} aria-label="匯入的原文">
        <pre className={mono ? "mono" : undefined} style={{ margin: 0, whiteSpace: "pre-wrap", overflowWrap: "anywhere", fontFamily: mono ? undefined : "inherit", fontSize: 13, lineHeight: 1.7, color: "var(--text)", background: "none", border: 0, padding: 0 }}>
          {range ? (
            <>
              {text.slice(0, range[0])}
              <mark ref={markRef} data-testid="source-text-hit" style={{ background: "color-mix(in srgb, var(--warn) 45%, transparent)", color: "inherit", borderRadius: 2, padding: "1px 0" }}>{text.slice(range[0], range[1])}</mark>
              {text.slice(range[1])}
            </>
          ) : text}
        </pre>
      </div>
    </div>
  );
}

type SourceDoc = { input_kind: string; source_name: string | null; content: string };
/** The imported text of a scenario. Only fetched when `enabled` (i.e. there is no PDF to show). */
export function useSourceText(scenarioId: string | null | undefined, enabled: boolean) {
  const [s, setS] = useState<{ state: "idle" | "loading" | "ready" | "none" | "error"; doc: SourceDoc | null }>({ state: "idle", doc: null });
  useEffect(() => {
    if (!scenarioId || !enabled) { setS({ state: "idle", doc: null }); return; }
    let live = true;
    setS({ state: "loading", doc: null });
    api.getSource(scenarioId)
      .then((d) => {
        if (!live) return;
        const content = typeof d?.content === "string" ? d.content : "";
        setS(content.trim() ? { state: "ready", doc: { input_kind: str(d.input_kind), source_name: d.source_name ?? null, content } } : { state: "none", doc: null });
      })
      .catch((e: unknown) => {
        if (live) setS({ state: e instanceof ApiError && (e.status === 404 || e.kind === "unimplemented") ? "none" : "error", doc: null });
      });
    return () => { live = false; };
  }, [scenarioId, enabled]);
  return s;
}

/* ---------- item structure: known facts / decisions / affects / suggestions ---------- */

interface KnownFact { field: string; value: string; quote?: string }
const showValue = (v: unknown): string =>
  Array.isArray(v) ? v.map(showValue).filter(Boolean).join("、")
  : typeof v === "boolean" ? (v ? "是" : "否")
  : obj(v) ? pick(obj(v)!, "name", "label", "value", "id") || JSON.stringify(v)
  : str(v);
/** `known`: [{ field, value, source_ref?, epistemic_status?, evidence_refs? }] — facts the report does give. */
function readKnown(raw: unknown, ir: ScenarioIR): KnownFact[] {
  if (!Array.isArray(raw)) return [];
  const quoteOf = (ref: string) => (ref ? str((ir.evidence ?? []).find((e) => e.id === ref)?.quote) : "");
  return raw.map((v): KnownFact | null => {
    const o = obj(v);
    const value = o ? showValue(o.value) : showValue(v);
    if (!value) return null;
    const refs = o && Array.isArray(o.evidence_refs) ? o.evidence_refs.map(str).filter(Boolean) : [];
    return { field: o ? str(o.field) : "", value, quote: refs.map(quoteOf).find(Boolean) || undefined };
  }).filter((x): x is KnownFact => !!x);
}

type Named = { id?: string; name?: string; role?: string };
const AFFECT_KIND: Record<string, string> = { host: "主機", hosts: "主機", service: "服務", services: "服務", action: "步驟", actions: "步驟", step: "步驟", steps: "步驟" };
/** Resolve `affects` entries (ids, names or {kind,id,name} objects) to concrete hosts / steps from the IR. */
function readAffects(raw: unknown, ir: ScenarioIR): { kind: string; text: string }[] {
  const pools: [string, Named[]][] = [["主機", (ir.hosts ?? []) as Named[]], ["服務", (ir.services ?? []) as Named[]], ["步驟", (ir.actions ?? []) as Named[]]];
  const lookup = (key: string) => {
    for (const [kind, list] of pools) {
      const hit = list.find((e) => e.id === key || e.name === key);
      if (hit) return { kind, text: hit.name || hit.role || hit.id || key };
    }
    return null;
  };
  const out: { kind: string; text: string }[] = [];
  for (const v of Array.isArray(raw) ? raw : []) {
    const o = obj(v);
    if (!o) { const t = str(v); if (t) out.push(lookup(t) ?? { kind: "", text: t }); continue; }
    const ref = pick(o, "id", "ref", "host_ref", "action_ref", "service_ref");
    const found = ref ? lookup(ref) : null;
    const text = pick(o, "name", "label", "title") || found?.text || ref;
    if (text) out.push({ kind: AFFECT_KIND[pick(o, "kind", "type").toLowerCase()] ?? found?.kind ?? "", text });
  }
  return out;
}

interface Suggestion { value: string; basis: string }
/** Suggestions in the order the backend sent them (it ranks by known clues); `basis` is its stated reason, if any. */
function readSuggestions(item: MissingItem): Suggestion[] {
  const raw: unknown[] = Array.isArray(item.suggestions) && item.suggestions.length ? item.suggestions : item.suggestion ? [item.suggestion] : [];
  const seen = new Set<string>();
  return raw.map((v) => {
    const o = obj(v);
    return o ? { value: pick(o, "value", "label", "name", "text"), basis: pick(o, "basis", "reason", "why", "because", "clue") } : { value: str(v), basis: "" };
  }).filter((x) => x.value && !seen.has(x.value) && !!seen.add(x.value));
}

const FIELD_ZH: Record<string, string> = {
  "target host identity": "受害主機的身分或角色", "target host operating system": "受害主機的作業系統", "target host os version": "作業系統版本",
  "target network placement": "主機的網路位置", "target service name": "被攻擊的服務", "target service version": "服務版本",
  "attacker access precondition": "攻擊者的初始存取條件",
};
/** Chinese title for an item. Raw English field names are never shown to the user. */
function itemTitle(item: MissingItem): string {
  const q = str(item.question);
  if (q) return q;
  const f = str(item.field);
  if (hasCJK(f)) return f;
  return FIELD_ZH[f.toLowerCase()] ?? `${CATEGORY[item.category] ?? "其他"}相關資訊（後端未提供中文問題）`;
}

const CATEGORY: Record<MissingItem["category"], string> = {
  host: "主機", software: "軟體", version: "版本", network: "網路", account: "帳號",
  dependency: "依賴", precondition: "前置條件", proprietary: "專有元件", other: "其他",
};
const STATUS: Record<MissingItem["status"], string> = {
  open: "待補充", user_supplied: "使用者已補充", llm_suggested: "LLM 建議", substitute_chosen: "已選替代方案", accepted_unknown: "接受未知",
};
const SEVERITY: Record<string, string> = { blocker: "阻擋部署", major: "重要", minor: "次要" };
const SEV_RANK: Record<string, number> = { blocker: 0, major: 1, minor: 2 };
type Resolution = "user_supplied" | "substitute_chosen" | "accepted_unknown";
const RESOLUTIONS: { v: Resolution; label: string; needText: boolean; placeholder: string }[] = [
  { v: "user_supplied", label: "我知道答案", needText: true, placeholder: "填入實際資訊，例如：Windows Server 2019、Exchange 2016 CU19" },
  { v: "substitute_chosen", label: "用替代方案", needText: true, placeholder: "說明要用什麼替代，以及與原本的差異" },
  { v: "accepted_unknown", label: "接受未知", needText: false, placeholder: "（選填）備註為何可以不補" },
];

function ItemCard({ item, ir, scenarioId, onDone, anchor, onLocate, located }: {
  item: MissingItem; ir: ScenarioIR; scenarioId: string; onDone: (resp: unknown) => Promise<void>;
  /** The passage the backend tied this item to; null when it has no clear passage. */
  anchor: Anchor | null;
  /** Present only when there is an original to show and this item has a usable anchor. */
  onLocate?: () => void;
  located?: Located | null;
}) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<Resolution>("user_supplied");
  const [text, setText] = useState("");
  const res = RESOLUTIONS.find((r) => r.v === mode)!;
  const isOpen = item.status === "open";

  const send = async (statusV: Resolution, textV: string) => {
    const resp = await api.supplement(scenarioId, { text: textV.trim(), targets_missing_item: item.id, status: statusV });
    await onDone(resp);
    setOpen(false);
    setText("");
  };
  const submit = useAction(() => send(mode, text));
  // One click: accept a benign substitute (never recorded as a report fact).
  const accept = useAction((value: string) => send("substitute_chosen", value));

  const prefill = (example: string) => { setMode("user_supplied"); setOpen(true); setText(example); };
  const suggestions = readSuggestions(item);
  const ranked = suggestions.some((s) => s.basis);
  const known = readKnown(item.known, ir);
  const needsDecision = item.needs_user_decision === true;
  const affects = readAffects(item.affects, ir);
  const reason = str(item.reason);
  const examples = (Array.isArray(item.examples) ? item.examples : []).map(str).filter(Boolean);
  const quote = anchor?.quote;

  return (
    <div
      className={`card${onLocate ? " locatable" : ""}${located ? " located" : ""}`}
      style={{ display: "flex", flexDirection: "column", gap: 8 }}
      data-testid="missing-item"
      // Clicking the card (not its controls) locates the item's anchor in the original.
      onClick={onLocate ? (e) => { if (!(e.target as HTMLElement).closest("button, textarea, input, select, a, summary")) onLocate(); } : undefined}
    >
      <div className="row" style={{ gap: 8 }}>
        {/* Lead with a plain-language question so the user need not read the whole report. */}
        <span style={{ fontWeight: 600 }}>{itemTitle(item)}</span>
        <span className="tag">{CATEGORY[item.category] ?? "其他"}</span>
        {item.severity && <span className={`tag ${item.severity}`}>{SEVERITY[item.severity] ?? item.severity}</span>}
        <span style={{ marginLeft: "auto", fontSize: 12 }} className={isOpen ? "status-PARTIAL" : item.status === "llm_suggested" ? "muted" : "status-PASS"}>
          {STATUS[item.status] ?? item.status}
        </span>
      </div>

      {affects.length > 0 && (
        <div className="row" style={{ gap: 6, flexWrap: "wrap", fontSize: 12 }}>
          <span className="muted">影響範圍：</span>
          {affects.map((a, i) => <span key={i} className="tag">{a.kind ? `${a.kind}　${a.text}` : a.text}</span>)}
        </div>
      )}
      {/* The rationale is shown only when it is in Chinese; raw English field names / reasons stay out of the UI. */}
      {reason && hasCJK(reason) && <div className="muted" style={{ fontSize: 12 }}>為何需要：{reason}</div>}

      {(known.length > 0 || needsDecision) && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 13 }} data-testid="known-vs-decide">
          {known.length > 0 && (
            <div style={{ borderLeft: "2px solid var(--ok, var(--accent))", paddingLeft: 10, display: "flex", flexDirection: "column", gap: 2 }}>
              {known.map((k, i) => (
                <div key={i} title={k.quote ? `原文：「${k.quote}」` : undefined}>
                  <span className="muted">原文已知：</span>{hasCJK(k.field) ? `${k.field}　` : ""}{k.value}
                </div>
              ))}
            </div>
          )}
          {needsDecision && (
            <div style={{ borderLeft: "2px solid var(--warn)", paddingLeft: 10 }}>
              <span className="tag" style={{ marginRight: 8 }} data-testid="needs-decision">需你決定</span>
              {str(item.question) || "報告沒有寫，這項要由你選定。"}
            </div>
          )}
        </div>
      )}

      {item.resolution && (
        <div style={{ fontSize: 13 }}>
          <span className="muted">處理內容：</span>{item.resolution} <SourceTag source={item.resolution_source} />
          {item.status === "llm_suggested" && <span className="muted" style={{ fontSize: 12 }}>（LLM 的建議，尚未經你確認）</span>}
        </div>
      )}

      {/* Benign substitutes the user can accept in one click. Each is clearly a substitute, not a report fact. */}
      {suggestions.length > 0 && isOpen && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 13, padding: "8px 10px", border: "1px solid var(--border)", borderRadius: "var(--radius)", background: "var(--bg-elev2, transparent)" }}>
          <span className="muted" style={{ fontSize: 12 }}>
            建議替身{ranked ? "（依已知線索排序，最相符的在前）" : known.length > 0 ? "（依後端提供的順序）" : ""}，點一下直接採用，會記為「已選替代方案」：
          </span>
          {ranked ? (
            <ol style={{ margin: 0, paddingLeft: 20, display: "flex", flexDirection: "column", gap: 6 }}>
              {suggestions.map((s) => (
                <li key={s.value}>
                  <button className="small" disabled={accept.busy} onClick={() => accept.run(s.value)} title="以此替身補上，並標記為『已選替代方案』">{s.value}</button>
                  {s.basis && hasCJK(s.basis) && <span className="muted" style={{ fontSize: 12, marginLeft: 8 }}>線索：{s.basis}</span>}
                </li>
              ))}
            </ol>
          ) : (
            <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
              {suggestions.map((s) => (
                <button key={s.value} className="small" disabled={accept.busy} onClick={() => accept.run(s.value)} title="以此替身補上，並標記為『已選替代方案』">{s.value}</button>
              ))}
            </div>
          )}
        </div>
      )}
      <ApiNotice error={accept.error} what="採用建議" />

      {/* Grounding: say plainly whether the report has a passage for this item. */}
      <div className="pdf-hint" data-testid="item-anchor">
        {quote ? (
          <>依據：原文引文{anchor?.page ? `（第 ${anchor.page} 頁）` : ""}「{quote.length > 160 ? `${quote.slice(0, 160)}…` : quote}」</>
        ) : anchor?.page ? (
          <>依據：後端指出第 {anchor.page} 頁，但沒有附上引文。</>
        ) : (
          <>此項無明確對應段落：報告沒有寫到這項資訊，所以不在原文中標示。</>
        )}
      </div>

      {located && (
        <div className="pdf-hint" role="status" data-testid="item-located">
          {located.state === "searching" ? "在原文中尋找引文…"
            : located.state === "found"
              ? <>已在{located.where}標示這段引文{located.partial ? "（僅部分文字相符）" : ""}。{located.mismatch}</>
              : located.state === "page-only"
                ? <>已跳到第 {located.page} 頁（後端指出的頁碼），但在該份 PDF 中找不到這段引文的文字，未標示。</>
                : "在原文中找不到這段引文，未跳轉也未標示。"}
        </div>
      )}

      {!open ? (
        <div className="row" style={{ gap: 6 }}>
          <button className="small" onClick={() => setOpen(true)}>{isOpen ? "補充" : "修改"}</button>
          {onLocate && <button className="small" onClick={onLocate} title="在右側原文中標示上面的引文並跳過去">在原文中定位</button>}
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, borderTop: "1px solid var(--border)", paddingTop: 10 }}>
          <div className="seg" style={{ alignSelf: "flex-start" }}>
            {RESOLUTIONS.map((r) => <button key={r.v} className={mode === r.v ? "on" : ""} onClick={() => setMode(r.v)} disabled={submit.busy}>{r.label}</button>)}
          </div>
          {/* Example answers make an abstract field concrete; click to fill. Examples only, not report claims. */}
          {mode === "user_supplied" && examples.length ? (
            <div className="row" style={{ gap: 6, flexWrap: "wrap", fontSize: 12 }}>
              <span className="muted">範例：</span>
              {examples.map((ex) => (
                <button key={ex} className="small" onClick={() => prefill(ex)} disabled={submit.busy}>{ex}</button>
              ))}
            </div>
          ) : null}
          <textarea rows={2} value={text} onChange={(e) => setText(e.target.value)} placeholder={res.placeholder} disabled={submit.busy} />
          <div className="row">
            <button className="primary small" disabled={submit.busy || (res.needText && !text.trim())} onClick={() => submit.run()}>
              {submit.busy ? <><span className="spinner" /> 送出中…</> : "送出"}
            </button>
            <button className="small" onClick={() => { setOpen(false); submit.clearError(); }} disabled={submit.busy}>取消</button>
          </div>
          <ApiNotice error={submit.error} what="補充" />
        </div>
      )}
    </div>
  );
}

function Body({ ir }: { ir: ScenarioIR }) {
  const { absorb } = useScenario();
  const [show, setShow] = useState<"open" | "all">("open");
  const [free, setFree] = useState("");
  const items = [...(ir.missing_items ?? [])].sort((a, b) => (SEV_RANK[a.severity ?? "minor"] ?? 3) - (SEV_RANK[b.severity ?? "minor"] ?? 3));
  const openItems = items.filter((m) => m.status === "open");
  const blockers = openItems.filter((m) => m.severity === "blocker").length;
  const shown = show === "open" ? openItems : items;
  const supplements = ir.supplements ?? [];
  const titleOf = new Map(items.map((m) => [m.id, itemTitle(m)]));

  // The original beside the list: the PDF when one was uploaded, otherwise the imported text.
  const pdf = usePdfSource(ir.id);
  const hasPdf = pdf.state === "ready" && !!pdf.data;
  const src = useSourceText(ir.id, pdf.state === "none" || pdf.state === "error");
  const hasText = !hasPdf && src.state === "ready" && !!src.doc;
  const hasOriginal = hasPdf || hasText;

  const paneRef = useRef<HTMLDivElement>(null);
  const seqRef = useRef(0);
  const pending = useRef<{ itemId: string; seq: number; page?: number } | null>(null);
  const [pdfAnchor, setPdfAnchor] = useState<PdfAnchor | null>(null);
  const [textTarget, setTextTarget] = useState<TextTarget | null>(null);
  const [located, setLocated] = useState<Located | null>(null);

  /** Scroll the PDF pane to a page the backend named, without highlighting anything. */
  const jumpToPage = (page: number): boolean => {
    const pane = paneRef.current;
    const sc = pane?.querySelector<HTMLElement>(".pdfv-scroll");
    const el = pane?.querySelector<HTMLElement>(`.pdfv-page[data-page="${page}"]`);
    if (!sc || !el) return false;
    sc.scrollTo({ top: Math.max(0, el.getBoundingClientRect().top - sc.getBoundingClientRect().top + sc.scrollTop), behavior: "auto" });
    return true;
  };

  /** Only an anchor the current original can actually show counts: text originals need a quote. */
  const usableAnchor = (item: MissingItem): Anchor | null => {
    const a = readAnchor(item, ir);
    return a && (hasPdf || a.quote) ? a : null;
  };

  const locateItem = (item: MissingItem, a: Anchor) => {
    const seq = ++seqRef.current;
    pending.current = { itemId: item.id, seq, page: a.page };
    if (hasPdf) {
      if (a.quote) {
        // One group = one passage: the backend-matched source wording (if any) and the quote itself.
        setPdfAnchor({ groups: [[a.matched, a.quote].filter((q): q is string => !!q)], seq });
        setLocated({ itemId: item.id, state: "searching" });
      } else {
        setPdfAnchor(null);
        setLocated(a.page && jumpToPage(a.page) ? { itemId: item.id, state: "page-only", page: a.page } : { itemId: item.id, state: "notfound" });
      }
    } else if (a.quote) {
      setTextTarget({ quote: a.quote, alts: a.matched ? [a.matched] : undefined, seq });
      setLocated({ itemId: item.id, state: "searching" });
    }
  };

  const onPdfLocated = useCallback((r: PdfLocateResult) => {
    const p = pending.current;
    if (!p || p.seq !== r.seq) return;
    if (r.found) {
      setLocated({
        itemId: p.itemId, state: "found", where: ` PDF 第 ${r.page} 頁`, partial: r.partial,
        mismatch: p.page && p.page !== r.page ? `後端標示的是第 ${p.page} 頁，實際文字在第 ${r.page} 頁找到。` : undefined,
      });
    } else {
      setLocated(p.page && jumpToPage(p.page) ? { itemId: p.itemId, state: "page-only", page: p.page } : { itemId: p.itemId, state: "notfound" });
    }
  }, []);
  const onTextLocated = useCallback((r: TextLocateResult) => {
    const p = pending.current;
    if (!p || p.seq !== r.seq) return;
    setLocated(r.found ? { itemId: p.itemId, state: "found", where: `原文${r.line ? `第 ${r.line} 行` : ""}`, partial: false } : { itemId: p.itemId, state: "notfound" });
  }, []);

  const addFree = useAction(async () => {
    const resp = await api.supplement(ir.id, { text: free.trim() });
    await absorb(resp);
    setFree("");
  });

  const paneHint = "點左側附有「依據」引文的缺失項目，會在這裡標示那段引文。沒有明確對應段落的項目不會標示，也不會跳頁。";
  const pane = hasPdf ? (
    <div className="pdf-pane" ref={paneRef}>
      <span className="pdf-hint">{paneHint}</span>
      <PdfViewer data={pdf.data!} filename="PDF 原檔" anchor={pdfAnchor} onLocated={onPdfLocated} />
    </div>
  ) : hasText ? (
    <div className="pdf-pane" ref={paneRef}>
      <span className="pdf-hint">此情境以文字匯入，沒有 PDF；右側是匯入的原文。{paneHint}</span>
      <SourceTextViewer text={src.doc!.content} title={src.doc!.source_name || "匯入的原文"} mono={src.doc!.input_kind === "stix2.1"} target={textTarget} onLocated={onTextLocated} />
    </div>
  ) : null;

  return (
    <div className="page" style={{ maxWidth: hasOriginal ? 1640 : 980 }}>
      <PageHead title="缺失補充" desc="報告沒寫清楚、但重建環境需要的資訊。每一項都標出原文已知的部分、需要你決定的部分與影響範圍；你可以直接填答案、點範例帶入、採用建議替身，或明確接受未知。補充內容一律標示為使用者來源，不會與原文證據混淆。" />
      {!hasOriginal && src.state === "loading" && <div className="pdf-hint"><span className="spinner" /> 載入原文…</div>}
      {!hasOriginal && src.state === "none" && <div className="pdf-hint">此情境沒有保存原文（PDF 或文字），無法在旁對照。</div>}
      {!hasOriginal && src.state === "error" && <div className="pdf-hint">無法載入此情境的原文（後端未回應）。</div>}

      <div className={hasOriginal ? "pdf-split" : undefined} style={hasOriginal ? undefined : { display: "contents" }}>
      <div className={hasOriginal ? "pdf-col" : undefined} style={hasOriginal ? undefined : { display: "contents" }}>

      <div className="row">
        <div className="seg">
          <button className={show === "open" ? "on" : ""} onClick={() => setShow("open")}>待補充 {openItems.length}</button>
          <button className={show === "all" ? "on" : ""} onClick={() => setShow("all")}>全部 {items.length}</button>
        </div>
        {blockers > 0 && <span className="status-FAIL" style={{ fontSize: 13 }}>{blockers} 項會阻擋部署</span>}
      </div>

      {items.length === 0 ? (
        <div className="card"><Empty>分析沒有列出缺失項目。若你知道報告以外的背景資訊，仍可在下方自由補充。</Empty></div>
      ) : shown.length === 0 ? (
        <div className="card"><Empty>所有缺失項目都已處理。</Empty></div>
      ) : (
        shown.map((m) => {
          const a = usableAnchor(m);
          return (
            <ItemCard key={m.id} item={m} ir={ir} scenarioId={ir.id} onDone={absorb}
              anchor={hasOriginal ? a : readAnchor(m, ir)}
              onLocate={hasOriginal && a ? () => locateItem(m, a) : undefined}
              located={located?.itemId === m.id ? located : null} />
          );
        })
      )}

      <div className="card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <h2 style={{ margin: 0 }}>自由補充</h2>
        <div className="muted" style={{ fontSize: 13 }}>不針對特定缺失項目的背景資訊，例如受害環境的已知配置。</div>
        <textarea rows={3} value={free} onChange={(e) => setFree(e.target.value)} placeholder="輸入補充說明" disabled={addFree.busy} />
        <div><button className="primary small" disabled={!free.trim() || addFree.busy} onClick={() => addFree.run()}>
          {addFree.busy ? <><span className="spinner" /> 送出中…</> : "加入補充"}
        </button></div>
        <ApiNotice error={addFree.error} what="補充" />
      </div>

      {supplements.length > 0 && (
        <div className="card flush">
          <div className="card-head"><h2>已加入的補充</h2><span className="muted" style={{ fontSize: 12 }}>{supplements.length}</span></div>
          <table className="tbl">
            <thead><tr><th>內容</th><th>對應缺失項目</th><th>來源</th></tr></thead>
            <tbody>
              {supplements.map((s) => (
                <tr key={s.id}>
                  <td style={{ whiteSpace: "pre-wrap" }}>{s.text}</td>
                  <td className="muted">{s.targets_missing_item ? titleOf.get(s.targets_missing_item) ?? "（該缺失項目已不存在）" : "—"}</td>
                  <td><SourceTag source={s.source} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      </div>
      {pane}
      </div>

      <NextStep prev={{ to: "/analysis", label: "分析結果" }} next={{ to: "/flow", label: "攻擊流程" }} />
    </div>
  );
}

export function MissingPage() {
  const { ir } = useScenario();
  return <ScenarioGate title="缺失補充">{ir && <Body key={ir.id} ir={ir} />}</ScenarioGate>;
}
