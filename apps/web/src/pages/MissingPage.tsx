import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { joinList, live, t, t as tr, type MsgKey } from "../i18n";
import type { MissingItem, ScenarioIR } from "@contracts";
import { api, ApiError } from "../lib/api";
import { useAction } from "../lib/hooks";
import { useScenario } from "../lib/scenario";
import { ApiNotice, Empty, NextStep, Notice, PageHead, ScenarioGate, SourceTag } from "../components/ui";
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
        <span className="name" title={title}>{title || t("imp.sourceTitle")}</span>
        <span className="spacer" />
        <span className="pageno">{t("ms.chars", { n: text.length.toLocaleString() })}</span>
      </div>
      <div className="pdfv-scroll" ref={scrollRef} tabIndex={0} aria-label={t("imp.sourceTitle")}>
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
/** Internal kind codes. Labels come from the locale (kind.host / kind.service / kind.step). */
type Kind = "host" | "service" | "step";
const AFFECT_KIND: Record<string, Kind> = { host: "host", hosts: "host", service: "service", services: "service", action: "step", actions: "step", step: "step", steps: "step" };
const kindLabel = (k: string) => (k === "host" || k === "service" || k === "step" ? t(`kind.${k}`) : k);
const escRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
/** The analysis sometimes names a host literally "unknown"; never show that word as if it were a name. */
const hostName = (n: string) => (/^unknown$/i.test(n) ? t("ms.unknownHost") : n);

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
  const steps = (ids: string[]) => {
    const nums = [...new Set(ids)].map((id) => no.get(id)).filter((n) => n !== undefined).sort((a, b) => a! - b!);
    return t("ms.steps", { list: joinList(nums.map(String)), n: nums.length });
  };
  const text = (t: string) => {
    let out = t.replace(/\b(hosts?|actions?|services?)\s*:\s*([\w-]+)(?:\.\w+)?(?:\s+[—–]\s+)?/gi, (m, kind: string, id: string) => {
      const k = AFFECT_KIND[kind.toLowerCase()];
      if (k === "step") return no.has(id) ? `${steps([id])} ` : m;
      const hit = (k === "host" ? hosts : services).find((e) => e?.id === id);
      return hit ? `${hostName(str(hit.name) || str(hit.role) || id)} ` : m;
    });
    if (runSrc) out = out.replace(runs(), (run) => steps(splitRun(run)));
    // Wording fixes inside backend sentences (data stays as written apart from these terms).
    out = out.replace(/^unknown(?=\s)/i, tr("ms.unknownHost")).replace(/\bIR\b/g, tr("an.title"));
    return out.replace(/替身/g, "替代方案").trim(); // i18n-ignore: rewrites a term inside Chinese backend text
  };
  return {
    stepNo: (id) => no.get(id),
    text,
    idRuns: (t) => (runSrc ? t.match(runs()) ?? [] : []),
    replaceRun: (t, ids) => (runSrc ? t.replace(runs(), ids.join(", ")) : t),
  };
}

interface KnownFact { field: string; value: string; /** False when the backend marks the fact as not backed by the source (a program placeholder, an inference). */ fromSource: boolean; /** Evidence quote behind this fact, when the backend cited one. */ anchor?: Anchor }
const showValue = (v: unknown): string =>
  Array.isArray(v) ? v.map(showValue).filter(Boolean).join("、")
  : typeof v === "boolean" ? (v ? t("data.yes") : t("data.no"))
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
    // "原文已知" is a source claim: only make it when the backend says supported, or (older data without a status) cites a quote.
    const status = o ? str(o.epistemic_status) : "";
    const fromSource = status ? status === "supported" : anchors.length > 0;
    return { field, value, fromSource, anchor: anchors.find((a) => a.quote!.toLowerCase().includes(needle)) ?? anchors[0] };
  }).filter((x): x is KnownFact => !!x);
}

interface Affect { kind: string; text: string; step?: number }
/** Resolve `affects` entries (ids, names, "action:a7 — name" strings or {kind,id,name} objects) to hosts / steps from the IR. */
function readAffects(raw: unknown, ir: ScenarioIR, namer: Namer): Affect[] {
  const pools: [Kind, Named[]][] = [["host", list<Named>(ir.hosts)], ["service", list<Named>(ir.services)], ["step", list<Named>(ir.actions)]];
  const lookup = (key: string, kindHint?: string): Affect | null => {
    for (const [kind, pool] of pools) {
      if (kindHint && kind !== kindHint) continue;
      const hit = pool.find((e) => e?.id === key || e?.name === key);
      if (hit) return { kind, text: str(hit.name) || str(hit.role) || str(hit.id) || key, step: kind === "step" ? namer.stepNo(str(hit.id)) : undefined };
    }
    return null;
  };
  const out: Affect[] = [];
  const seen = new Set<string>();
  const push = (a: Affect) => {
    const fixed = a.kind === "host" ? { ...a, text: hostName(a.text) } : a;
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
const KINDS: Kind[] = ["host", "service", "step"];
/** "Affects 1 host, 6 steps" */
function affectSummary(affects: Affect[]): string {
  const parts = KINDS.map((k) => [k, affects.filter((a) => a.kind === k).length] as const).filter(([, n]) => n > 0).map(([k, n]) => t(`ms.unit.${k}`, { n }));
  const other = affects.filter((a) => !KINDS.includes(a.kind as Kind)).length;
  if (other) parts.push(t("ms.unit.other", { n: other }));
  return t("ms.affects", { list: joinList(parts) });
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
const NOTE_RE = /請|待確認|候選|才選|核對|例如/; // i18n-ignore: parses backend text
/** An option that is only a prompt ("請填確切版本"); adopting it would save the prompt as the answer. */
const HINT_RE = /^(請|其他|其它)|請填|請依|請補|補上具體值|^從.*填/; // i18n-ignore: parses backend text
const UNKNOWN_RE = /保留為未知|保留未知|接受未知|標記為?未知/; // i18n-ignore: parses backend text
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
    const caveat = split ? m![2].replace(/^候選[；;，,\s]*/, "").trim() : ""; // i18n-ignore: parses backend text
    if (UNKNOWN_RE.test(raw)) {
      if (!seen.has("\u0000unknown")) { seen.add("\u0000unknown"); choices.push({ label: raw, value: "", mode: "accepted_unknown" }); }
      return;
    }
    if (HINT_RE.test(value)) { if (!hints.includes(raw)) hints.push(raw); return; }
    if (seen.has(value)) return;
    seen.add(value);
    if (basis && hasCJK(basis)) ranked = true;
    choices.push({ label: value, value, mode, note: [caveat, basis && hasCJK(basis) ? t("ms.clue", { basis }) : ""].filter(Boolean).join(" · ") || undefined });
  };
  for (const s of sugg) add(s, "substitute_chosen");
  for (const e of list<unknown>(item.examples)) add(e, "user_supplied");
  // "Leave unknown" goes last: it is the fallback, not a candidate answer.
  choices.sort((a, b) => Number(a.mode === "accepted_unknown") - Number(b.mode === "accepted_unknown"));
  return { choices, hints, ranked };
}

const FIELD_TITLE: Record<string, MsgKey> = {
  "target host identity": "ms.f.identity", "target host operating system": "ms.f.os", "target host os version": "ms.f.osVersion",
  "target network placement": "ms.f.placement", "target service name": "ms.f.service", "target service version": "ms.f.serviceVersion",
  "attacker access precondition": "ms.f.access",
};
/** Chinese title for an item. When the backend gave neither a question nor a known field, its original field name is shown, labelled as such, so the user can still tell what is being asked. */
function itemTitle(item: MissingItem): string {
  const q = str(item.question);
  if (q) return q;
  const f = str(item.field);
  if (hasCJK(f)) return f;
  const known = FIELD_TITLE[f.toLowerCase()];
  if (known) return t(known);
  const cat = CATEGORY[item.category] ?? CATEGORY.other;
  return f ? t("ms.fieldFallbackRaw", { cat, f }) : t("ms.fieldFallback", { cat });
}

const CATEGORY: Record<MissingItem["category"], string> = live(() => ({
  host: t("ms.cat.host"), software: t("ms.cat.software"), version: t("ms.cat.version"), network: t("ms.cat.network"), account: t("ms.cat.account"),
  dependency: t("ms.cat.dependency"), precondition: t("ms.cat.precondition"), proprietary: t("ms.cat.proprietary"), other: t("ms.cat.other"),
}));
const STATUS: Record<MissingItem["status"], string> = live(() => ({
  open: t("ms.st.open"), user_supplied: t("ms.st.user"), llm_suggested: t("ms.st.llm"), substitute_chosen: t("ms.st.sub"), accepted_unknown: t("ms.st.unknown"),
}));
const SEVERITY: Record<string, string> = live(() => ({ blocker: t("ms.sev.blocker"), major: t("ms.sev.major"), minor: t("ms.sev.minor") }));
type Resolution = "user_supplied" | "substitute_chosen" | "accepted_unknown";
const RESOLUTIONS: { v: Resolution; label: string; needText: boolean; placeholder: string }[] = live(() => [
  { v: "user_supplied", label: t("ms.res.user"), needText: true, placeholder: t("ms.res.user.ph") },
  { v: "substitute_chosen", label: t("ms.res.sub"), needText: true, placeholder: t("ms.res.sub.ph") },
  { v: "accepted_unknown", label: t("ms.res.unknown"), needText: false, placeholder: t("ms.res.unknown.ph") },
]);
/** The API stores a non-empty resolution text for every answer. When the optional note is left blank we record that fact, not an invented reason. */
// Stored in the scenario data, so it stays the same in every UI language (API data is not localized).
const UNKNOWN_DEFAULT_NOTE = "接受未知（使用者未填寫備註）"; // i18n-ignore: stored value

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
  const why = t("ms.tier.why", { n: steps });
  // Every item carries the same backend severity: keep the backend's word on the label, use the step count only for ordering.
  const same = sevs.find(Boolean);
  if (same && SEVERITY[same]) return { rank: steps >= 5 ? 1 : steps >= 2 ? 2 : 3, label: SEVERITY[same], cls: same, why: t("ms.tier.whySame", { sev: same, n: steps }) };
  return steps >= 5 ? { rank: 1, label: t("ms.sev.first"), cls: "major", why } : steps >= 2 ? { rank: 2, label: t("ms.sev.major"), cls: "", why } : { rank: 3, label: t("ms.sev.minor"), cls: "", why };
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
    const steps = affects.filter((a) => a.kind === "step").length;
    const reason = merged(items.map((m) => str(m.reason)));
    return {
      id: items[0].id, items, affects,
      title: namer.text(merged(items.map(itemTitle))),
      // An English-only rationale is still shown, labelled as the backend's original, so the card never hides what is being asked.
      reason: hasCJK(reason) ? namer.text(reason) : reason ? t("ms.reasonEn", { reason }) : "",
      tier: tierOf(items, steps, distinct),
    };
  });
  const stepCount = (g: Group) => g.affects.filter((a) => a.kind === "step").length;
  // Stable: ties keep the backend's order.
  return groups.sort((a, b) => a.tier.rank - b.tier.rank || stepCount(b) - stepCount(a));
}

/** Open cards as the page shows them (identical questions are merged). The stage nav uses this so both numbers agree. */
export function openCardCount(ir: ScenarioIR): number {
  return buildGroups(ir, makeNamer(ir)).filter((g) => g.items[0].status === "open").length;
}

/** Fields the backend added to missing items that the shared TS type may not list yet. */
type Where = { collection?: string; id?: string; field?: string };
const itemX = (m: MissingItem) => m as MissingItem & { target?: Where; applied_to?: Where; write_back?: string };
const WHERE_FIELDS = ["os", "os_version", "network_placement", "version", "port", "name", "role"];
/** "主機 victim-web 的作業系統" for a write-back location; empty when there is none. */
function whereText(w: Where | undefined, ir: ScenarioIR): string {
  if (!w || !w.id) return "";
  const isHost = w.collection === "hosts";
  const rec: any = (isHost ? ir.hosts : ir.services)?.find((x) => x.id === w.id);
  const label = rec ? (isHost ? rec.name || rec.role : rec.name) || w.id : w.id;
  const field = WHERE_FIELDS.includes(w.field ?? "") ? t(`ms.wf.${w.field}` as MsgKey) : w.field ?? t("ms.wf.field");
  return t("ms.where", { kind: isHost ? t("kind.host") : t("kind.service"), label, field });
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
        <span className="tag">{CATEGORY[item.category] ?? CATEGORY.other}</span>
        {group.tier.label && <span className={`tag ${group.tier.cls}`} title={group.tier.why} data-testid="item-priority">{group.tier.label}</span>}
        <span style={{ marginLeft: "auto", fontSize: 12 }} className={isOpen ? "status-PARTIAL" : item.status === "llm_suggested" ? "muted" : "status-PASS"}>
          {STATUS[item.status] ?? item.status}
        </span>
      </div>

      {reason && <div className="muted" style={{ fontSize: 12 }}>{t("ms.why", { reason })}</div>}

      {affects.length > 0 && (
        <details style={{ fontSize: 12 }} data-testid="item-affects">
          <summary className="muted" style={{ cursor: "pointer", width: "fit-content" }}>{affectSummary(affects)}</summary>
          <ul style={{ margin: "6px 0 0", paddingLeft: 18, display: "flex", flexDirection: "column", gap: 2 }}>
            {affects.map((a, i) => (
              <li key={i}><span className="muted">{a.kind === "step" && a.step ? t("ms.steps", { list: a.step, n: 1 }) : kindLabel(a.kind)}{a.kind ? " · " : ""}</span>{a.text}</li>
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
                const body = <><span className="muted" title={k.fromSource ? undefined : t("ms.guess.hint")}>{k.fromSource ? t("ms.known") : t("ms.guess")}</span> {hasCJK(k.field) ? `${k.field} · ` : ""}{k.value}</>;
                // The row itself is the locate control when the backend cited a quote for this fact.
                return a ? (
                  <button key={i} className="link" data-testid="known-locate" onClick={() => locate!(a)}
                    title={t("ms.locateTitle", { q: clip(a.quote ?? "", 200) })}
                    style={{ textAlign: "left", whiteSpace: "normal", height: "auto", color: "inherit", fontWeight: "inherit" }}>
                    {body}<span style={{ color: "var(--accent)", marginLeft: 8, fontSize: 12, whiteSpace: "nowrap" }}>{t("ms.locate")} ›</span>
                  </button>
                ) : (
                  <div key={i} title={k.anchor?.quote ? t("ms.srcQuote", { q: k.anchor.quote }) : undefined}>{body}</div>
                );
              })}
            </div>
          )}
          {needsDecision && (
            <div style={{ borderLeft: "2px solid var(--warn)", paddingLeft: 10 }}>
              <span className="tag" style={{ marginRight: 8 }} data-testid="needs-decision">{t("ms.decide")}</span>
              <span className="muted">{t("ms.decide.body")}</span>
            </div>
          )}
        </div>
      )}

      {item.resolution && (
        <div style={{ fontSize: 13 }}>
          <span className="muted">{t("ms.resolution")}</span> {item.resolution} <SourceTag source={item.resolution_source} />
          {item.status === "llm_suggested" && <span className="muted" style={{ fontSize: 12 }}>{t("ms.llmPending")}</span>}
          {whereText(itemX(item).applied_to, ir) && <div className="muted" style={{ fontSize: 12 }} data-testid="applied-to">{t("ms.applied", { where: whereText(itemX(item).applied_to, ir) })}</div>}
          {!itemX(item).applied_to && itemX(item).write_back && <div className="muted" style={{ fontSize: 12 }} data-testid="write-back">{t("ms.textOnly", { text: itemX(item).write_back })}</div>}
          {!itemX(item).applied_to && !itemX(item).write_back && item.status !== "open" && item.status !== "accepted_unknown" && <div className="muted" style={{ fontSize: 12 }}>{t("ms.textOnlyNote")}</div>}
        </div>
      )}

      {/* Grounding: say plainly whether the report has a passage for this item. */}
      <div className="pdf-hint" data-testid="item-anchor">
        {quote ? (
          <>{anchor?.via === "known" ? t("ms.anchorKnown") : t("ms.anchor")}{anchor?.page ? t("ms.anchorPage", { page: anchor.page }) : ""}: 「{clip(quote)}」</>
        ) : anchor?.page ? (
          <>{t("ms.pageOnly", { page: anchor.page })}</>
        ) : (
          <>{t("ms.noAnchor")}</>
        )}
      </div>

      {located && (
        <div className="pdf-hint" role="status" data-testid="item-located">
          {located.state === "searching" ? t("ms.searching")
            : located.state === "found"
              ? <>{t(located.partial ? "ms.foundPartial" : "ms.found", { where: located.where })} {located.mismatch}</>
              : located.state === "page-only"
                ? <>{t("ms.pageNoText", { page: located.page })}</>
                : t("ms.notFound")}
        </div>
      )}

      {/* One row of options (substitutes + examples). Clicking fills the form below; nothing is saved until 送出. */}
      {(isOpen || open) && (choices.length > 0 || hints.length > 0) && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 12 }} data-testid="item-choices">
          {choices.length > 0 && (
            <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
              <span className="muted">{ranked ? t("ms.optionsRanked") : t("ms.options")}:</span>
              {choices.map((c) => (
                <button key={`${c.mode}:${c.label}`} className="small" disabled={submit.busy} onClick={() => choose(c)}
                  title={`${t("ms.optionTitle")}${c.note ? ` (${c.note})` : ""}`}>{c.label}</button>
              ))}
            </div>
          )}
          {hints.length > 0 && <div className="muted">{t("ms.hints", { hints: hints.join(" · ") })}</div>}
        </div>
      )}

      {!open ? (
        <div className="row" style={{ gap: 6 }}>
          <button className="small" onClick={() => setOpen(true)}>{isOpen ? t("ms.answer") : t("ms.edit")}</button>
          {canLocate && <button className="small" onClick={() => locate!(canLocate)} title={t("ms.locate.hint")}>{t("ms.locate")}</button>}
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, borderTop: "1px solid var(--border)", paddingTop: 10 }}>
          <div className="seg" style={{ alignSelf: "flex-start" }}>
            {RESOLUTIONS.map((r) => <button key={r.v} className={mode === r.v ? "on" : ""} onClick={() => setMode(r.v)} disabled={submit.busy}>{r.label}</button>)}
          </div>
          <textarea rows={2} value={text} onChange={(e) => setText(e.target.value)} placeholder={res.placeholder} disabled={submit.busy}
            aria-label={res.needText ? t("ms.required", { label: res.label }) : t("ms.optional", { label: res.label })} aria-required={res.needText} />
          {mode !== "accepted_unknown" && whereText(itemX(item).target, ir) && (
            <div className="muted" style={{ fontSize: 12 }} data-testid="write-target">
              {t("ms.writeTarget", { where: whereText(itemX(item).target, ir) })}
            </div>
          )}
          <div className="muted" style={{ fontSize: 12 }} data-testid="resolution-hint">
            {res.needText
              ? (text.trim() ? t("ms.userSource") : t("ms.needText"))
              : t("ms.unknownNote")}
          </div>
          {note && <div className="muted" style={{ fontSize: 12 }}>{t("ms.note", { note })}</div>}
          {group.items.length > 1 && <div className="muted" style={{ fontSize: 12 }}>{t("ms.merged", { n: group.items.length })}</div>}
          <div className="row">
            <button className="primary small" disabled={submit.busy || (res.needText && !text.trim())} onClick={() => submit.run()}>
              {submit.busy ? <><span className="spinner" /> {t("ms.sending")}</> : t("ms.send")}
            </button>
            <button className="small" onClick={() => { setOpen(false); submit.clearError(); }} disabled={submit.busy}>{t("ms.cancel")}</button>
            {canLocate && <button className="small" onClick={() => locate!(canLocate)} title={t("ms.locate.hint")}>{t("ms.locate")}</button>}
          </div>
          <ApiNotice error={submit.error} what={t("ms.what")} />
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
        itemId: p.itemId, state: "found", where: t("ms.pdfWhere", { page: r.page }), partial: r.partial,
        mismatch: p.page && p.page !== r.page ? t("ms.pageMismatch", { p: p.page, r: r.page }) : undefined,
      });
    } else {
      setLocated(p.page && jumpToPage(p.page) ? { itemId: p.itemId, state: "page-only", page: p.page } : { itemId: p.itemId, state: "notfound" });
    }
  }, []);
  const onTextLocated = useCallback((r: TextLocateResult) => {
    const p = pending.current;
    if (!p || p.seq !== r.seq) return;
    setLocated(r.found ? { itemId: p.itemId, state: "found", where: r.line ? t("ms.srcWhereLine", { line: r.line }) : t("ms.srcWhere"), partial: false } : { itemId: p.itemId, state: "notfound" });
  }, []);

  const addFree = useAction(async () => {
    const resp = await api.supplement(ir.id, { text: free.trim() });
    await absorb(resp);
    setFree("");
  });

  const paneHint = t("ms.paneHint");
  const pane = hasPdf ? (
    <div className="pdf-pane" ref={paneRef}>
      <span className="pdf-hint">{paneHint}</span>
      <PdfViewer data={pdf.data!} filename={t("pdf.original")} anchor={pdfAnchor} onLocated={onPdfLocated} />
    </div>
  ) : hasText ? (
    <div className="pdf-pane" ref={paneRef}>
      <span className="pdf-hint">{t("ms.textImport")} {paneHint}</span>
      <SourceTextViewer text={src.doc!.content} title={src.doc!.source_name || t("imp.sourceTitle")} mono={src.doc!.input_kind === "stix2.1"} target={textTarget} onLocated={onTextLocated} />
    </div>
  ) : null;

  return (
    <div className="page" style={{ maxWidth: hasOriginal ? 1640 : 980 }}>
      <PageHead title={t("ms.title")} desc={t("ms.desc")} />
      {!hasOriginal && src.state === "loading" && <div className="pdf-hint"><span className="spinner" /> {t("ms.srcLoading")}</div>}
      {!hasOriginal && src.state === "none" && <div className="pdf-hint">{t("ms.noSrc")}</div>}
      {(ir as { fidelity?: unknown }).fidelity === undefined && (
        <Notice kind="info" title={t("ms.incomplete")}>
          {t("ms.incomplete.body")}
        </Notice>
      )}
      {!hasOriginal && src.state === "error" && <div className="pdf-hint">{t("ms.srcError")}</div>}

      <div className={hasOriginal ? "pdf-split" : undefined} style={hasOriginal ? undefined : { display: "contents" }}>
      <div className={hasOriginal ? "pdf-col" : undefined} style={hasOriginal ? undefined : { display: "contents" }}>

      <div className="row">
        <div className="seg">
          <button className={show === "open" ? "on" : ""} onClick={() => setShow("open")}>{t("ms.tab.open", { n: openGroups.length })}</button>
          <button className={show === "all" ? "on" : ""} onClick={() => setShow("all")}>{t("ms.tab.all", { n: groups.length })}</button>
        </div>
        {blockers > 0 && <span className="status-FAIL" style={{ fontSize: 13 }}>{t("ms.blockers", { n: blockers })}</span>}
      </div>

      {groups.length === 0 ? (
        <div className="card"><Empty>{t("ms.none")}</Empty></div>
      ) : shown.length === 0 ? (
        <div className="card"><Empty>{t("ms.allDone")}</Empty></div>
      ) : (
        shown.map((g) => (
          <ItemCard key={g.id} group={g} ir={ir} scenarioId={ir.id} onDone={absorb} hasPdf={hasPdf}
            locate={hasOriginal ? (a) => locateItem(g.id, a) : undefined}
            located={located?.itemId === g.id ? located : null} />
        ))
      )}

      <div className="card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <h2 style={{ margin: 0 }}>{t("ms.free")}</h2>
        <div className="muted" style={{ fontSize: 13 }}>{t("ms.free.desc")}</div>
        <textarea rows={3} value={free} onChange={(e) => setFree(e.target.value)} placeholder={t("ms.free.ph")} disabled={addFree.busy} />
        <div><button className="primary small" disabled={!free.trim() || addFree.busy} onClick={() => addFree.run()}>
          {addFree.busy ? <><span className="spinner" /> {t("ms.sending")}</> : t("ms.free.add")}
        </button></div>
        <ApiNotice error={addFree.error} what={t("ms.what")} />
      </div>

      {supplements.length > 0 && (
        <div className="card flush">
          <div className="card-head"><h2>{t("ms.added")}</h2><span className="muted" style={{ fontSize: 12 }}>{supplements.length}</span></div>
          <table className="tbl">
            <thead><tr><th>{t("ms.col.text")}</th><th>{t("ms.col.item")}</th><th>{t("ms.col.source")}</th></tr></thead>
            <tbody>
              {supplements.map((s) => (
                <tr key={s.id}>
                  <td style={{ whiteSpace: "pre-wrap" }}>{s.text}</td>
                  <td className="muted">{s.targets_missing_item ? titleOf.get(s.targets_missing_item) ?? t("ms.itemGone") : "—"}</td>
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

      <NextStep prev={{ to: "/analysis", label: t("stage.analysis") }} next={{ to: "/flow", label: t("stage.flow") }} />
    </div>
  );
}

export function MissingPage() {
  const { ir } = useScenario();
  return <ScenarioGate title={t("ms.title")}>{ir && <Body key={ir.id} ir={ir} />}</ScenarioGate>;
}
