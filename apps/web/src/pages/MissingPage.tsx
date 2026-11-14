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
 * A passage of the report tied to this item. Two sources, both stated by the backend:
 * the item's own `anchor`, or — when it has none — the evidence quote behind one of its
 * `known` facts (`via: "known"`). There is deliberately no keyword search fallback: an item
 * with neither is shown as "no passage" instead of highlighting something loosely related.
 */
interface Anchor {
  page?: number; quote?: string; evidenceRef?: string;
  /** Source wording the backend matched the evidence quote to, when it recorded one. */
  matched?: string;
  via?: "anchor" | "known";
}

const pageNo = (v: unknown): number | undefined => { const n = Number(v); return Number.isFinite(n) && n >= 1 ? Math.floor(n) : undefined; };

/** Quote + locator of one `ir.evidence` entry. A page is only claimed when the locator is a page locator. */
function evidenceAnchor(ref: string, ir: ScenarioIR): Anchor | null {
  const ev = obj((Array.isArray(ir.evidence) ? ir.evidence : []).find((e) => e?.id === ref));
  const quote = ev ? str(ev.quote) : "";
  if (!ev || !quote) return null;
  const loc = obj(ev.locator);
  return { quote, evidenceRef: ref, matched: str(ev.matched_text) || undefined, page: loc && str(loc.kind) === "page" ? pageNo(loc.ref) : undefined };
}

function readAnchor(item: MissingItem, ir: ScenarioIR, known: KnownFact[]): Anchor | null {
  const a = obj((item as unknown as Record<string, unknown>).anchor);
  if (a) {
    const page = pageNo(a.page);
    const evidenceRef = str(a.evidence_ref) || undefined;
    const ev = evidenceRef ? evidenceAnchor(evidenceRef, ir) : null;
    const quote = str(a.quote) || ev?.quote;
    if (quote || page) return { page: page ?? ev?.page, quote: quote || undefined, evidenceRef, matched: ev?.matched, via: "anchor" };
  }
  // No anchor of its own: fall back to the first quote behind a "原文已知" fact.
  const k = known.find((x) => x.anchor?.quote);
  return k?.anchor ? { ...k.anchor, via: "known" } : null;
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

type Named = { id?: string; name?: string; role?: string; evidence_refs?: unknown };
const list = <T,>(v: unknown): T[] => (Array.isArray(v) ? (v as T[]) : []);
const AFFECT_KIND: Record<string, string> = { host: "主機", hosts: "主機", service: "服務", services: "服務", action: "步驟", actions: "步驟", step: "步驟", steps: "步驟" };
const escRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
/** The analysis sometimes names a host literally "unknown"; never show that word as if it were a name. */
const hostName = (n: string) => (/^unknown$/i.test(n) ? "未指明的主機" : n);

/**
 * Turns internal ids into words the user can recognise. Steps are numbered by their order in
 * the scenario ("步驟 7"), the same order the impact list spells out with the step's name.
 */
interface Namer {
  /** 1-based position of an action id, if it is one. */
  stepNo: (id: string) => number | undefined;
  /** Rewrite ids/jargon inside a sentence written by the backend. */
  text: (t: string) => string;
  /** Runs of bare step ids ("a8, a9, a10") inside a sentence, for merging duplicate questions. */
  idRuns: (t: string) => string[];
  replaceRun: (t: string, withIds: string[]) => string;
}
function makeNamer(ir: ScenarioIR): Namer {
  const actions = list<Named>(ir.actions), hosts = list<Named>(ir.hosts), services = list<Named>(ir.services);
  const no = new Map<string, number>();
  actions.forEach((a, i) => { if (typeof a?.id === "string") no.set(a.id, i + 1); });
  // Only code-like ids (a7, s12) are rewritten in running text; a word-like id could collide with prose.
  const codes = [...no.keys()].filter((id) => /^[A-Za-z]{1,3}\d{1,4}$/.test(id)).sort((a, b) => b.length - a.length);
  const alt = codes.map(escRe).join("|");
  const runSrc = alt ? `(?<![\\w:.\\-/])(?:${alt})(?:\\s*[,、，]\\s*(?:${alt}))*(?![\\w\\-])` : "";
  const runs = () => new RegExp(runSrc, "g");
  const splitRun = (run: string) => run.split(/\s*[,、，]\s*/).filter(Boolean);
  const steps = (ids: string[]) => `步驟 ${[...new Set(ids)].map((id) => no.get(id)).filter((n) => n !== undefined).sort((a, b) => a! - b!).join("、")}`;
  const text = (t: string) => {
    let out = t.replace(/\b(hosts?|actions?|services?)\s*:\s*([\w-]+)(?:\.\w+)?(?:\s+[—–]\s+)?/gi, (m, kind: string, id: string) => {
      const k = AFFECT_KIND[kind.toLowerCase()];
      if (k === "步驟") return no.has(id) ? `${steps([id])} ` : m;
      const hit = (k === "主機" ? hosts : services).find((e) => e?.id === id);
      return hit ? `${hostName(str(hit.name) || str(hit.role) || id)} ` : m;
    });
    if (runSrc) out = out.replace(runs(), (run) => steps(splitRun(run)));
    return out.replace(/^unknown(?=\s)/i, "未指明的主機").replace(/\bIR\b/g, "分析結果").replace(/替身/g, "替代方案").trim();
  };
  return {
    stepNo: (id) => no.get(id),
    text,
    idRuns: (t) => (runSrc ? t.match(runs()) ?? [] : []),
    replaceRun: (t, ids) => (runSrc ? t.replace(runs(), ids.join(", ")) : t),
  };
}

interface KnownFact { field: string; value: string; /** Evidence quote behind this fact, when the backend cited one. */ anchor?: Anchor }
const showValue = (v: unknown): string =>
  Array.isArray(v) ? v.map(showValue).filter(Boolean).join("、")
  : typeof v === "boolean" ? (v ? "是" : "否")
  : obj(v) ? pick(obj(v)!, "name", "label", "value", "id") || JSON.stringify(v)
  : str(v);
/** Evidence ids behind a known fact: its own `evidence_refs`, else those of the IR entity `source_ref` points at. */
function knownRefs(o: Record<string, unknown>, ir: ScenarioIR): string[] {
  const own = list<unknown>(o.evidence_refs).map(str).filter(Boolean);
  if (own.length) return own;
  const m = /^\s*(\w+)\s*:\s*([^.\s]+)/.exec(str(o.source_ref));
  if (!m) return [];
  const kind = m[1].toLowerCase();
  if (kind === "evidence") return [m[2]];
  const pool = /^hosts?$/.test(kind) ? ir.hosts : /^actions?$/.test(kind) ? ir.actions : /^services?$/.test(kind) ? ir.services : null;
  const hit = list<Named>(pool).find((e) => e?.id === m[2]);
  return list<unknown>(hit?.evidence_refs).map(str).filter(Boolean);
}
/** `known`: [{ field, value, source_ref?, epistemic_status?, evidence_refs? }] — facts the report does give. */
function readKnown(raw: unknown, ir: ScenarioIR): KnownFact[] {
  const seen = new Set<string>();
  return list<unknown>(raw).map((v): KnownFact | null => {
    const o = obj(v);
    const value = o ? showValue(o.value) : showValue(v);
    if (!value) return null;
    const field = o ? str(o.field) : "";
    if (seen.has(`${field}\u0000${value}`)) return null;
    seen.add(`${field}\u0000${value}`);
    const anchors = (o ? knownRefs(o, ir) : []).map((r) => evidenceAnchor(r, ir)).filter((a): a is Anchor => !!a);
    // Among the quotes the backend cited, prefer one that literally contains the fact; otherwise the first.
    const needle = value.toLowerCase();
    return { field, value, anchor: anchors.find((a) => a.quote!.toLowerCase().includes(needle)) ?? anchors[0] };
  }).filter((x): x is KnownFact => !!x);
}

interface Affect { kind: string; text: string; step?: number }
/** Resolve `affects` entries (ids, names, "action:a7 — name" strings or {kind,id,name} objects) to hosts / steps from the IR. */
function readAffects(raw: unknown, ir: ScenarioIR, namer: Namer): Affect[] {
  const pools: [string, Named[]][] = [["主機", list<Named>(ir.hosts)], ["服務", list<Named>(ir.services)], ["步驟", list<Named>(ir.actions)]];
  const lookup = (key: string, kindHint?: string): Affect | null => {
    for (const [kind, pool] of pools) {
      if (kindHint && kind !== kindHint) continue;
      const hit = pool.find((e) => e?.id === key || e?.name === key);
      if (hit) return { kind, text: str(hit.name) || str(hit.role) || str(hit.id) || key, step: kind === "步驟" ? namer.stepNo(str(hit.id)) : undefined };
    }
    return null;
  };
  const out: Affect[] = [];
  const seen = new Set<string>();
  const push = (a: Affect) => {
    const fixed = a.kind === "主機" ? { ...a, text: hostName(a.text) } : a;
    const key = `${fixed.kind}\u0000${fixed.step ?? ""}\u0000${fixed.text}`;
    if (!seen.has(key)) { seen.add(key); out.push(fixed); }
  };
  for (const v of list<unknown>(raw)) {
    const o = obj(v);
    if (!o) {
      const t = str(v);
      if (!t) continue;
      // "action:a7 — Use RDP …": a kind, an internal id and the display name.
      const m = /^(\w+)\s*:\s*(\S+)(?:\s+[—–-]+\s+(.+))?$/.exec(t);
      const kind = m ? AFFECT_KIND[m[1].toLowerCase()] : undefined;
      if (m && kind) {
        const found = lookup(m[2], kind);
        push({ kind, text: found?.text || str(m[3]) || m[2], step: found?.step });
      } else push(lookup(t) ?? { kind: "", text: t });
      continue;
    }
    const ref = pick(o, "id", "ref", "host_ref", "action_ref", "service_ref");
    const found = ref ? lookup(ref) : null;
    const text = pick(o, "name", "label", "title") || found?.text || ref;
    if (text) push({ kind: AFFECT_KIND[pick(o, "kind", "type").toLowerCase()] ?? found?.kind ?? "", text, step: found?.step });
  }
  return out;
}
const AFFECT_UNIT: Record<string, string> = { 主機: "台主機", 服務: "個服務", 步驟: "個步驟" };
/** "影響 1 台主機、6 個步驟" */
function affectSummary(affects: Affect[]): string {
  const parts = ["主機", "服務", "步驟"].map((k) => [affects.filter((a) => a.kind === k).length, AFFECT_UNIT[k]] as const).filter(([n]) => n > 0).map(([n, u]) => `${n} ${u}`);
  const other = affects.filter((a) => !AFFECT_UNIT[a.kind]).length;
  if (other) parts.push(`${other} 個其他項目`);
  return `影響 ${parts.join("、")}`;
}

/**
 * One row of things the user can click to fill the answer box. Suggestions ("替代方案") and
 * examples are the same kind of help, so they share a row; nothing is saved until 送出.
 */
interface Choice {
  label: string;
  /** Text put into the answer box. Empty for "leave unknown". */
  value: string;
  mode: Resolution;
  /** The backend's caveat on this option (e.g. "請核對原文或資產清單") or its stated clue. */
  note?: string;
}
/** A parenthetical that instructs the user rather than being part of the answer. */
const NOTE_RE = /請|待確認|候選|才選|核對|例如/;
/** An option that is only a prompt ("請填確切版本"); adopting it would save the prompt as the answer. */
const HINT_RE = /^(請|其他|其它)|請填|請依|請補|補上具體值|^從.*填/;
const UNKNOWN_RE = /保留為未知|保留未知|接受未知|標記為?未知/;
function readChoices(item: MissingItem): { choices: Choice[]; hints: string[]; ranked: boolean } {
  const sugg: unknown[] = Array.isArray(item.suggestions) && item.suggestions.length ? item.suggestions : item.suggestion ? [item.suggestion] : [];
  const choices: Choice[] = [], hints: string[] = [];
  const seen = new Set<string>();
  let ranked = false;
  const add = (v: unknown, mode: Resolution) => {
    const o = obj(v);
    const raw = o ? pick(o, "value", "label", "name", "text") : str(v);
    const basis = o ? pick(o, "basis", "reason", "why", "because", "clue") : "";
    if (!raw) return;
    const m = /^(.*?)\s*[（(]([^（()）]*)[)）]$/.exec(raw);
    const split = m && m[1].trim() && NOTE_RE.test(m[2]);
    const value = split ? m![1].trim() : raw;
    const caveat = split ? m![2].replace(/^候選[；;，,\s]*/, "").trim() : "";
    if (UNKNOWN_RE.test(raw)) {
      if (!seen.has("\u0000unknown")) { seen.add("\u0000unknown"); choices.push({ label: raw, value: "", mode: "accepted_unknown" }); }
      return;
    }
    if (HINT_RE.test(value)) { if (!hints.includes(raw)) hints.push(raw); return; }
    if (seen.has(value)) return;
    seen.add(value);
    if (basis && hasCJK(basis)) ranked = true;
    choices.push({ label: value, value, mode, note: [caveat, basis && hasCJK(basis) ? `線索：${basis}` : ""].filter(Boolean).join("；") || undefined });
  };
  for (const s of sugg) add(s, "substitute_chosen");
  for (const e of list<unknown>(item.examples)) add(e, "user_supplied");
  // "Leave unknown" goes last: it is the fallback, not a candidate answer.
  choices.sort((a, b) => Number(a.mode === "accepted_unknown") - Number(b.mode === "accepted_unknown"));
  return { choices, hints, ranked };
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
type Resolution = "user_supplied" | "substitute_chosen" | "accepted_unknown";
const RESOLUTIONS: { v: Resolution; label: string; needText: boolean; placeholder: string }[] = [
  { v: "user_supplied", label: "我知道答案", needText: true, placeholder: "填入實際資訊，例如：Windows Server 2019、Exchange 2016 CU19" },
  { v: "substitute_chosen", label: "用替代方案", needText: true, placeholder: "說明要用什麼替代，以及與原本的差異" },
  { v: "accepted_unknown", label: "接受未知", needText: false, placeholder: "（選填）備註為何可以不補" },
];
/** The API stores a non-empty resolution text for every answer. When the optional note is left blank we record that fact, not an invented reason. */
const UNKNOWN_DEFAULT_NOTE = "接受未知（使用者未填寫備註）";

/** Priority shown on a card. `rank` orders the list (lower first). */
interface Tier { rank: number; label: string; cls: string; why?: string }
/**
 * The backend's severity is used whenever it actually distinguishes items. When every item
 * carries the same value (so it ranks nothing), priority falls back to how many steps the gap
 * touches — stated as such in the tooltip, never presented as the backend's judgement.
 */
function tierOf(items: MissingItem[], steps: number, backendDistinguishes: boolean): Tier {
  const sevs = items.map((m) => str(m.severity));
  if (sevs.includes("blocker")) return { rank: 0, label: SEVERITY.blocker, cls: "blocker" };
  if (backendDistinguishes) {
    const sev = sevs.includes("major") ? "major" : sevs.find(Boolean) ?? "";
    return sev ? { rank: sev === "major" ? 1 : sev === "minor" ? 3 : 2, label: SEVERITY[sev] ?? sev, cls: sev } : { rank: 3, label: "", cls: "" };
  }
  const why = `依影響的步驟數排序（${steps} 個步驟）；分析沒有為各項區分嚴重度。`;
  return steps >= 5 ? { rank: 1, label: "優先處理", cls: "major", why } : steps >= 2 ? { rank: 2, label: "重要", cls: "", why } : { rank: 3, label: "次要", cls: "", why };
}

/** One card. Usually one missing item; several when the backend asked the very same question more than once. */
interface Group { id: string; items: MissingItem[]; title: string; reason: string; affects: Affect[]; tier: Tier }

function buildGroups(ir: ScenarioIR, namer: Namer): Group[] {
  const all = list<MissingItem>(ir.missing_items).filter((m) => m && typeof m.id === "string");
  const buckets = new Map<string, MissingItem[]>();
  for (const m of all) {
    const q = str(m.question);
    // Same question apart from the step it names, same options, same state → one card.
    const mergeable = !!q && namer.idRuns(q).length <= 1;
    const key = mergeable
      ? JSON.stringify([m.category, m.status, namer.replaceRun(str(m.field), ["§"]), namer.replaceRun(q, ["§"]), m.suggestions ?? m.suggestion ?? null, m.examples ?? null, m.resolution ?? null])
      : `id:${m.id}`;
    buckets.set(key, [...(buckets.get(key) ?? []), m]);
  }
  /** Members differ only in the step id they name: name all of those steps in one sentence. */
  const merged = (texts: string[]): string => {
    const runs = texts.map((t) => namer.idRuns(t));
    return texts.length > 1 && runs.every((r) => r.length === 1) ? namer.replaceRun(texts[0], runs.map((r) => r[0])) : texts[0] ?? "";
  };
  const distinct = new Set(all.map((m) => str(m.severity))).size > 1;
  const groups = [...buckets.values()].map((items): Group => {
    const affects = readAffects(items.flatMap((m) => list<unknown>(m.affects)), ir, namer);
    const steps = affects.filter((a) => a.kind === "步驟").length;
    const reason = merged(items.map((m) => str(m.reason)));
    return {
      id: items[0].id, items, affects,
      title: namer.text(merged(items.map(itemTitle))),
      // The rationale is shown only when it is in Chinese; raw English field names / reasons stay out of the UI.
      reason: hasCJK(reason) ? namer.text(reason) : "",
      tier: tierOf(items, steps, distinct),
    };
  });
  const stepCount = (g: Group) => g.affects.filter((a) => a.kind === "步驟").length;
  // Stable: ties keep the backend's order.
  return groups.sort((a, b) => a.tier.rank - b.tier.rank || stepCount(b) - stepCount(a));
}

const clip = (q: string, n = 160) => (q.length > n ? `${q.slice(0, n)}…` : q);

function ItemCard({ group, ir, scenarioId, onDone, hasPdf, locate, located }: {
  group: Group; ir: ScenarioIR; scenarioId: string; onDone: (resp: unknown) => Promise<void>;
  hasPdf: boolean;
  /** Present only when there is an original (PDF or text) to show beside the list. */
  locate?: (a: Anchor) => void;
  located?: Located | null;
}) {
  const item = group.items[0];
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<Resolution>("user_supplied");
  const [text, setText] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const res = RESOLUTIONS.find((r) => r.v === mode)!;
  const isOpen = item.status === "open";

  const submit = useAction(async () => {
    let last: unknown;
    try {
      // A merged card answers every item it stands for.
      for (const it of group.items) last = await api.supplement(scenarioId, { text: text.trim() || (mode === "accepted_unknown" ? UNKNOWN_DEFAULT_NOTE : ""), targets_missing_item: it.id, status: mode });
    } finally {
      if (last !== undefined) await onDone(last);
    }
    setOpen(false);
    setText("");
    setNote(null);
  });

  const { choices, hints, ranked } = readChoices(item);
  /** Every option only fills the form; the user reviews (and can edit) before pressing 送出. */
  const choose = (c: Choice) => { setMode(c.mode); setText(c.value); setNote(c.note ?? null); setOpen(true); };
  const known = readKnown(group.items.flatMap((m) => list<unknown>(m.known)), ir);
  const needsDecision = group.items.some((m) => m.needs_user_decision === true);
  const { affects, reason } = group;
  /** Only a passage the current original can actually show counts: a text original needs a quote. */
  const usable = (a: Anchor | null | undefined): Anchor | null => (a && locate && (a.quote || (hasPdf && a.page)) ? a : null);
  const anchor = readAnchor(item, ir, known);
  const canLocate = usable(anchor);
  const quote = anchor?.quote;

  return (
    <div
      className={`card${canLocate ? " locatable" : ""}${located ? " located" : ""}`}
      style={{ display: "flex", flexDirection: "column", gap: 8 }}
      data-testid="missing-item"
      // Clicking the card (not its controls) locates the item's passage in the original.
      onClick={canLocate ? (e) => { if (!(e.target as HTMLElement).closest("button, textarea, input, select, a, summary, details")) locate!(canLocate); } : undefined}
    >
      <div className="row" style={{ gap: 8 }}>
        {/* Lead with a plain-language question so the user need not read the whole report. */}
        <span style={{ fontWeight: 600 }}>{group.title}</span>
        <span className="tag">{CATEGORY[item.category] ?? "其他"}</span>
        {group.tier.label && <span className={`tag ${group.tier.cls}`} title={group.tier.why} data-testid="item-priority">{group.tier.label}</span>}
        <span style={{ marginLeft: "auto", fontSize: 12 }} className={isOpen ? "status-PARTIAL" : item.status === "llm_suggested" ? "muted" : "status-PASS"}>
          {STATUS[item.status] ?? item.status}
        </span>
      </div>

      {reason && <div className="muted" style={{ fontSize: 12 }}>為何需要：{reason}</div>}

      {affects.length > 0 && (
        <details style={{ fontSize: 12 }} data-testid="item-affects">
          <summary className="muted" style={{ cursor: "pointer", width: "fit-content" }}>{affectSummary(affects)}</summary>
          <ul style={{ margin: "6px 0 0", paddingLeft: 18, display: "flex", flexDirection: "column", gap: 2 }}>
            {affects.map((a, i) => (
              <li key={i}><span className="muted">{a.kind === "步驟" && a.step ? `步驟 ${a.step}` : a.kind}{a.kind ? "　" : ""}</span>{a.text}</li>
            ))}
          </ul>
        </details>
      )}

      {(known.length > 0 || needsDecision) && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 13 }} data-testid="known-vs-decide">
          {known.length > 0 && (
            <div style={{ borderLeft: "2px solid var(--ok, var(--accent))", paddingLeft: 10, display: "flex", flexDirection: "column", gap: 2, alignItems: "flex-start" }}>
              {known.map((k, i) => {
                const a = usable(k.anchor);
                const body = <><span className="muted">原文已知：</span>{hasCJK(k.field) ? `${k.field}　` : ""}{k.value}</>;
                // The row itself is the locate control when the backend cited a quote for this fact.
                return a ? (
                  <button key={i} className="link" data-testid="known-locate" onClick={() => locate!(a)}
                    title={`在右側原文中標示這段引文：「${clip(a.quote ?? "", 200)}」`}
                    style={{ textAlign: "left", whiteSpace: "normal", height: "auto", color: "inherit", fontWeight: "inherit" }}>
                    {body}<span style={{ color: "var(--accent)", marginLeft: 8, fontSize: 12, whiteSpace: "nowrap" }}>在原文中定位 ›</span>
                  </button>
                ) : (
                  <div key={i} title={k.anchor?.quote ? `原文：「${k.anchor.quote}」` : undefined}>{body}</div>
                );
              })}
            </div>
          )}
          {needsDecision && (
            <div style={{ borderLeft: "2px solid var(--warn)", paddingLeft: 10 }}>
              <span className="tag" style={{ marginRight: 8 }} data-testid="needs-decision">需你決定</span>
              <span className="muted">報告沒有寫，這項要由你選定。</span>
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

      {/* Grounding: say plainly whether the report has a passage for this item. */}
      <div className="pdf-hint" data-testid="item-anchor">
        {quote ? (
          <>{anchor?.via === "known" ? "「原文已知」的原文引文" : "原文引文"}{anchor?.page ? `（第 ${anchor.page} 頁）` : ""}：「{clip(quote)}」</>
        ) : anchor?.page ? (
          <>後端指出相關內容在第 {anchor.page} 頁，但沒有附上原文引文。</>
        ) : (
          <>此項沒有原文引文：報告沒有寫到這項資訊，所以不在原文中標示。</>
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

      {/* One row of options (substitutes + examples). Clicking fills the form below; nothing is saved until 送出. */}
      {(isOpen || open) && (choices.length > 0 || hints.length > 0) && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 12 }} data-testid="item-choices">
          {choices.length > 0 && (
            <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
              <span className="muted">可帶入的選項{ranked ? "（最相符的在前）" : ""}：</span>
              {choices.map((c) => (
                <button key={`${c.mode}:${c.label}`} className="small" disabled={submit.busy} onClick={() => choose(c)}
                  title={`帶入輸入框，確認後再送出${c.note ? `（${c.note}）` : ""}`}>{c.label}</button>
              ))}
            </div>
          )}
          {hints.length > 0 && <div className="muted">填寫提示：{hints.join("；")}</div>}
        </div>
      )}

      {!open ? (
        <div className="row" style={{ gap: 6 }}>
          <button className="small" onClick={() => setOpen(true)}>{isOpen ? "補充" : "修改"}</button>
          {canLocate && <button className="small" onClick={() => locate!(canLocate)} title="在右側原文中標示上面的原文引文並跳過去">在原文中定位</button>}
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, borderTop: "1px solid var(--border)", paddingTop: 10 }}>
          <div className="seg" style={{ alignSelf: "flex-start" }}>
            {RESOLUTIONS.map((r) => <button key={r.v} className={mode === r.v ? "on" : ""} onClick={() => setMode(r.v)} disabled={submit.busy}>{r.label}</button>)}
          </div>
          <textarea rows={2} value={text} onChange={(e) => setText(e.target.value)} placeholder={res.placeholder} disabled={submit.busy}
            aria-label={res.needText ? `${res.label}（必填）` : `${res.label}備註（選填）`} aria-required={res.needText} />
          <div className="muted" style={{ fontSize: 12 }} data-testid="resolution-hint">
            {res.needText
              ? (text.trim() ? "送出後會標示為使用者來源，不會當成原文證據。" : "必填：請先填寫內容，「送出」才會啟用。")
              : "備註選填。留白送出會記錄為「接受未知（使用者未填寫備註）」，此項目維持未知，不會被當成已知事實。"}
          </div>
          {note && <div className="muted" style={{ fontSize: 12 }}>提醒：{note}</div>}
          {group.items.length > 1 && <div className="muted" style={{ fontSize: 12 }}>這張卡片合併了 {group.items.length} 個內容相同的問題，送出後會一併套用。</div>}
          <div className="row">
            <button className="primary small" disabled={submit.busy || (res.needText && !text.trim())} onClick={() => submit.run()}>
              {submit.busy ? <><span className="spinner" /> 送出中…</> : "送出"}
            </button>
            <button className="small" onClick={() => { setOpen(false); submit.clearError(); }} disabled={submit.busy}>取消</button>
            {canLocate && <button className="small" onClick={() => locate!(canLocate)} title="在右側原文中標示上面的原文引文並跳過去">在原文中定位</button>}
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
  const namer = useMemo(() => makeNamer(ir), [ir]);
  const groups = useMemo(() => buildGroups(ir, namer), [ir, namer]);
  const openGroups = groups.filter((g) => g.items[0].status === "open");
  const blockers = openGroups.filter((g) => g.tier.cls === "blocker").length;
  const shown = show === "open" ? openGroups : groups;
  const supplements = ir.supplements ?? [];
  const titleOf = new Map(groups.flatMap((g) => g.items.map((m) => [m.id, g.title] as const)));

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

  const locateItem = (itemId: string, a: Anchor) => {
    const seq = ++seqRef.current;
    pending.current = { itemId, seq, page: a.page };
    if (hasPdf) {
      if (a.quote) {
        // One group = one passage: the backend-matched source wording (if any) and the quote itself.
        setPdfAnchor({ groups: [[a.matched, a.quote].filter((q): q is string => !!q)], seq });
        setLocated({ itemId, state: "searching" });
      } else {
        setPdfAnchor(null);
        setLocated(a.page && jumpToPage(a.page) ? { itemId, state: "page-only", page: a.page } : { itemId, state: "notfound" });
      }
    } else if (a.quote) {
      setTextTarget({ quote: a.quote, alts: a.matched ? [a.matched] : undefined, seq });
      setLocated({ itemId, state: "searching" });
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

  const paneHint = "點左側卡片上的「原文已知」那一行，或「在原文中定位」按鈕，會在這裡標示對應的原文引文。寫著「此項沒有原文引文」的項目不會標示，也不會跳頁。";
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
      <PageHead title="缺失補充" desc="報告沒寫清楚、但重建環境需要的資訊。每一項都標出原文已知的部分、需要你決定的部分與影響的步驟；你可以直接填答案、點選項帶入輸入框後送出，或明確接受未知。補充內容一律標示為使用者來源，不會與原文證據混淆。" />
      {!hasOriginal && src.state === "loading" && <div className="pdf-hint"><span className="spinner" /> 載入原文…</div>}
      {!hasOriginal && src.state === "none" && <div className="pdf-hint">此情境沒有保存原文（PDF 或文字），無法在旁對照。</div>}
      {!hasOriginal && src.state === "error" && <div className="pdf-hint">無法載入此情境的原文（後端未回應）。</div>}

      <div className={hasOriginal ? "pdf-split" : undefined} style={hasOriginal ? undefined : { display: "contents" }}>
      <div className={hasOriginal ? "pdf-col" : undefined} style={hasOriginal ? undefined : { display: "contents" }}>

      <div className="row">
        <div className="seg">
          <button className={show === "open" ? "on" : ""} onClick={() => setShow("open")}>待補充 {openGroups.length}</button>
          <button className={show === "all" ? "on" : ""} onClick={() => setShow("all")}>全部 {groups.length}</button>
        </div>
        {blockers > 0 && <span className="status-FAIL" style={{ fontSize: 13 }}>{blockers} 項會阻擋部署</span>}
      </div>

      {groups.length === 0 ? (
        <div className="card"><Empty>分析沒有列出缺失項目。若你知道報告以外的背景資訊，仍可在下方自由補充。</Empty></div>
      ) : shown.length === 0 ? (
        <div className="card"><Empty>所有缺失項目都已處理。</Empty></div>
      ) : (
        shown.map((g) => (
          <ItemCard key={g.id} group={g} ir={ir} scenarioId={ir.id} onDone={absorb} hasPdf={hasPdf}
            locate={hasOriginal ? (a) => locateItem(g.id, a) : undefined}
            located={located?.itemId === g.id ? located : null} />
        ))
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
