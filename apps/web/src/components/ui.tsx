// Shared presentational pieces used by every page.
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { CheckStatus, EpistemicStatus, Evidence, Source } from "@contracts";
import type { ApiError } from "../lib/api";
import { useScenario } from "../lib/scenario";
import { getLocale, live, t, useT, type MsgKey } from "../i18n";
import { knownErrorKey } from "../lib/errors";

export const EPISTEMIC: Record<EpistemicStatus, { label: string; glyph: string; hint: string }> = live(() => ({
  supported: { label: t("epi.supported"), glyph: "✓", hint: t("epi.supported.hint") },
  inferred: { label: t("epi.inferred"), glyph: "＋", hint: t("epi.inferred.hint") },
  absent: { label: t("epi.absent"), glyph: "○", hint: t("epi.absent.hint") },
  // The backend sets this when the cited quotes could not be matched to the source — not when the source is silent.
  insufficient: { label: t("epi.insufficient"), glyph: "?", hint: t("epi.insufficient.hint") },
}));
/** Content taken from an imported STIX / Attack Flow file was never checked against a report text, so it must not read as "原文". */
export const IMPORTED = live(() => ({ label: t("epi.imported"), glyph: "⇩", hint: t("epi.imported.hint") }));
export const isImported = (source?: Source | string) => source === "stix";
/** Badge text for a claim: its epistemic status, except that imported items say where they came from instead of "原文". */
export const claimLabel = (status?: EpistemicStatus | string, source?: Source | string) =>
  isImported(source) && status === "supported" ? IMPORTED.label : EPISTEMIC[status as EpistemicStatus]?.label ?? String(status ?? "—");
export const EPISTEMIC_ORDER: EpistemicStatus[] = ["supported", "inferred", "absent", "insufficient"];

export function EpistemicBadge({ status, source }: { status?: EpistemicStatus; source?: Source }) {
  if (isImported(source) && status === "supported")
    return <span className="badge validated" title={IMPORTED.hint}><span aria-hidden>{IMPORTED.glyph}</span> {IMPORTED.label}</span>;
  if (!status) return <span className="badge" title={t("epi.noStatus")}>—</span>;
  const e = EPISTEMIC[status];
  if (!e) return <span className="badge">{String(status)}</span>;
  return <span className={`badge ${status}`} title={e.hint}><span aria-hidden>{e.glyph}</span> {e.label}</span>;
}

// ---- citation quality: how well the quotes behind a claim match the source. Independent of the claim's own status. ----
export type QuoteLevel = "exact" | "strong" | "partial" | "none";
export const QUOTE_LEVEL: Record<QuoteLevel, { cls: string; mark: string; word: string; desc: string }> = live(() => ({
  exact: { cls: "status-PASS", mark: "✓", word: t("quote.exact"), desc: t("quote.exact.desc") },
  strong: { cls: "status-PASS", mark: "✓", word: t("quote.strong"), desc: t("quote.strong.desc") },
  partial: { cls: "status-PARTIAL", mark: "～", word: t("quote.partial"), desc: t("quote.partial.desc") },
  none: { cls: "status-FAIL", mark: "✗", word: t("quote.none"), desc: t("quote.none.desc") },
}));
/** Reads the graded match level; falls back to the older boolean. undefined = the backend did not grade this quote. */
export function quoteLevel(e?: Evidence | null): QuoteLevel | undefined {
  const raw = (e as any)?.quote_match ?? (e as any)?.match_level;
  if (typeof raw === "string" && raw in QUOTE_LEVEL) return raw as QuoteLevel;
  if (e?.quote_verified === true) return "exact";
  if (e?.quote_verified === false) return "none";
  return undefined;
}
const holds = (l?: QuoteLevel) => l === "exact" || l === "strong";

/** all = every quote holds · some = anything in between (a quote only matched as a fragment, or some hold and some do not) ·
 *  none = every graded quote is truly missing from the source — the ONLY state that is red / ✗ ·
 *  empty = no quotes attached · ungraded = quotes exist but the backend gave no match result for any of them.
 *  A fragment match is not "not found": a step whose quotes are all fragments is `some`, never `none`. */
export type CitationState = "all" | "some" | "none" | "empty" | "ungraded";
export interface CitationSummary {
  state: CitationState; total: number; ok: number; bad: number; worst?: QuoteLevel;
  /** Quotes that only matched as a fragment / keywords. */
  partial?: number;
  /** Quotes that could not be found in the source at all. */
  missing?: number;
}
export function summarizeCitations(refs: string[] | undefined | null, byId: Map<string, Evidence>): CitationSummary {
  const ids = Array.isArray(refs) ? refs : [];
  if (ids.length === 0) return { state: "empty", total: 0, ok: 0, bad: 0 };
  // A ref to an evidence record that does not exist is a quote that cannot be shown, i.e. not matched.
  const levels = ids.map((id) => (byId.has(id) ? quoteLevel(byId.get(id)) : "none"));
  const graded = levels.filter((l): l is QuoteLevel => l !== undefined);
  if (graded.length === 0) return { state: "ungraded", total: ids.length, ok: 0, bad: 0 };
  const ok = graded.filter(holds).length;
  const bad = graded.length - ok;
  const partial = graded.filter((l) => l === "partial").length;
  const missing = graded.filter((l) => l === "none").length;
  const order: QuoteLevel[] = ["none", "partial", "strong", "exact"];
  const worst = order.find((l) => graded.includes(l));
  return { state: bad === 0 ? "all" : missing === graded.length ? "none" : "some", total: ids.length, ok, bad, worst, partial, missing };
}
export const CITATION: Record<CitationState, { label: string; cls: string; hint: string }> = live(() => ({
  all: { label: t("cite.all"), cls: "approved", hint: t("cite.all.hint") },
  some: { label: t("cite.some"), cls: "pending", hint: t("cite.some.hint") },
  none: { label: t("cite.none"), cls: "insufficient", hint: t("cite.none.hint") },
  empty: { label: t("cite.empty"), cls: "absent", hint: t("cite.empty.hint") },
  ungraded: { label: t("cite.ungraded"), cls: "", hint: t("cite.ungraded.hint") },
}));
/** Says exactly what was found, e.g. "2 句都只對上片段" — a fragment match is never worded as "沒對上". */
export function citationText(s: CitationSummary): string {
  if (s.state !== "some" && s.state !== "none") return CITATION[s.state].label;
  const partial = s.partial ?? 0;
  const missing = s.missing ?? 0;
  const ungraded = Math.max(0, s.total - s.ok - partial - missing);
  if (s.ok === 0 && ungraded === 0) {
    if (missing === 0) return s.total === 1 ? t("cite.oneFragment") : t("cite.allFragments", { n: partial });
    if (partial === 0) return s.total === 1 ? t("cite.oneMissing") : t("cite.allMissing", { n: missing });
  }
  const bits = [
    s.ok > 0 && t("cite.bitOk", { n: s.ok }),
    partial > 0 && t("cite.bitPartial", { n: partial }),
    missing > 0 && t("cite.bitMissing", { n: missing }),
    ungraded > 0 && t("cite.bitUngraded", { n: ungraded }),
  ].filter((x): x is string => !!x);
  return bits.length ? t("cite.summary", { total: s.total, bits: bits.join(getLocale() === "en" ? ", " : "、") }) : CITATION[s.state].label;
}
export const INFERRED_BASIS = live(() => ({ label: t("basis.label"), hint: t("basis.hint") }));
/** The worst-case quality of the quotes behind one claim. Shown NEXT TO the claim status, never merged into it.
 *  `basis` = the claim is inferred: its quotes are context for the inference, not proof, so no verdict is shown. */
export function CitationBadge({ summary, source, basis }: { summary: CitationSummary; source?: Source; basis?: boolean }) {
  if (basis)
    return <span className="badge absent" title={INFERRED_BASIS.hint}>{summary.total > 0 ? INFERRED_BASIS.label : t("basis.none")}</span>;
  if (summary.state === "empty" && isImported(source)) return <span className="muted" style={{ fontSize: 11 }} title={IMPORTED.hint}>{t("cite.importNoQuotes")}</span>;
  const c = CITATION[summary.state];
  const onlyFragments = summary.state === "some" && summary.ok === 0 && (summary.missing ?? 0) === 0;
  const hint = onlyFragments ? t("cite.onlyFragments.hint") : c.hint;
  return <span className={`badge ${c.cls}`} title={hint}>{citationText(summary)}</span>;
}
/** Human-readable position of a quote: "第 7 段" instead of "paragraph 7". Null when the backend gave none. */
export function locatorText(locator?: { kind?: string; ref?: unknown } | null): string | null {
  const ref = locator?.ref === undefined || locator?.ref === null ? "" : String(locator.ref).trim();
  if (!ref) return null;
  const num = /^\d+$/.test(ref);
  if (locator?.kind === "page") return t(num ? "loc.page" : "loc.pageRaw", { ref });
  if (locator?.kind === "paragraph") return t(num ? "loc.para" : "loc.paraRaw", { ref });
  if (locator?.kind === "stix_path") return t("loc.stix", { ref });
  return t("loc.other", { ref });
}
/** One quote, shown as its match mark plus its first words — never as a bare "evidence-1" code. */
export function QuoteSnippet({ evidence, id, max = 26, basis }: { evidence?: Evidence | null; id: string; max?: number; basis?: boolean }) {
  if (!evidence) return <span className="status-FAIL" title={t("quote.notFound.title", { id })}>✗ {t("quote.notFound")}</span>;
  const level = quoteLevel(evidence);
  const m = level ? QUOTE_LEVEL[level] : undefined;
  const text = (evidence.quote ?? "").replace(/\s+/g, " ").trim();
  // Basis for an inference: context, not proof — no match mark, so it cannot read as a pass/fail verdict.
  if (basis)
    return (
      <span title={`${INFERRED_BASIS.label}\n${text}\n(${id})`}>
        <span className="muted" aria-label={t("basis.aria")}>·</span>{" "}
        {text.length > max ? `${text.slice(0, max)}…` : text || id}
      </span>
    );
  return (
    <span title={`${m ? `${m.desc}\n` : ""}${text}\n(${id})`}>
      <span className={m?.cls ?? "muted"} aria-label={m?.word ?? t("quote.unchecked")}>{m?.mark ?? "·"}</span>{" "}
      {text.length > max ? `${text.slice(0, max)}…` : text || id}
    </span>
  );
}

const SOURCE_LABEL: Record<Source, string> = live(() => ({ llm: t("source.llm"), user: t("source.user"), stix: t("source.stix"), program: t("source.program") }));
export function SourceTag({ source }: { source?: Source }) {
  if (!source) return null;
  return <span className={`tag ${source === "user" ? "user" : ""}`} title={t("source.title", { source })}>{SOURCE_LABEL[source] ?? source}</span>;
}

const CHECK_LABEL: Record<CheckStatus, string> = live(() => ({ PASS: t("check.PASS"), FAIL: t("check.FAIL"), PARTIAL: t("check.PARTIAL"), NOT_TESTED: t("check.NOT_TESTED") }));
export function StatusPill({ status }: { status?: CheckStatus | string }) {
  const s = status ?? "NOT_TESTED";
  return <span className={`pill status-${s}`}>{CHECK_LABEL[s as CheckStatus] ?? s}</span>;
}

export function PageHead({ title, desc, children }: { title: string; desc?: ReactNode; children?: ReactNode }) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {desc && <p className="desc">{desc}</p>}
      </div>
      {children && <div className="actions">{children}</div>}
    </div>
  );
}

export function Notice({ kind = "info", title, children, action }: { kind?: "info" | "warn" | "err"; title?: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className={`notice ${kind}`} role={kind === "err" ? "alert" : "status"}>
      <div className="body">
        {title && <div className="title">{title}</div>}
        {children}
      </div>
      {action}
    </div>
  );
}

/** FastAPI request-validation errors ([{type, loc, msg}]) in plain language; null when the payload is something else. */
const FIELDS = ["text", "name", "content", "input_kind", "note"];
const FIELD_ERRORS = ["string_too_short", "missing", "string_too_long", "int_parsing", "literal_error"];
export function validationMessages(data: unknown): string[] | null {
  if (!Array.isArray(data) || data.length === 0) return null;
  const out: string[] = [];
  for (const e of data) {
    if (!e || typeof e !== "object" || typeof (e as any).type !== "string" || !Array.isArray((e as any).loc)) return null;
    const loc = ((e as any).loc as unknown[]).filter((x) => x !== "body").map(String);
    const field = loc[loc.length - 1] ?? "";
    const type = (e as any).type as string;
    const why = FIELD_ERRORS.includes(type) ? t(`fieldErr.${type}` as MsgKey) : t("fieldErr.literal_error");
    const name = FIELDS.includes(field) ? t(`field.${field}` as MsgKey) : field || t("field.generic");
    out.push(t("fieldErr.line", { field: name, why }));
  }
  return out;
}

/** Raw request facts for an operator. Collapsed, so the page body keeps only the plain message. */
function TechDetails({ error }: { error: ApiError }) {
  const tr = useT();
  const raw = error.data !== undefined ? error.data : error.detail;
  if (!error.path && (raw === undefined || raw === "")) return null;
  return (
    <details className="tech-details">
      <summary>{tr("notice.techDetails")}</summary>
      {error.path && <div className="mono muted">{error.method} {error.path}{error.status ? ` · ${error.status}` : ""}</div>}
      {raw !== undefined && raw !== "" && <div style={{ marginTop: 4 }}><DataView data={raw} /></div>}
    </details>
  );
}

/** Turns an API failure into a plain-language notice. `what` names the feature. Known server messages are shown in the
 *  current language. Anything else gets a short generic line, and the raw text stays in the collapsed details. */
export function ApiNotice({ error, what, onRetry }: { error: ApiError | null; what: string; onRetry?: () => void }) {
  const tr = useT();
  if (!error) return null;
  const retry = onRetry ? <button className="small" onClick={onRetry}>{tr("notice.retry")}</button> : undefined;
  const details = <TechDetails error={error} />;
  if (error.kind === "unimplemented")
    return <Notice kind="info" title={tr("notice.unimpl.title", { what })} action={retry}>{tr("notice.unimpl.body")}{details}</Notice>;
  if (error.kind === "offline")
    return <Notice kind="warn" title={tr("notice.offline.title", { what })} action={retry}>{tr("notice.offline.body")}{details}</Notice>;
  const invalid = error.status === 422 ? validationMessages(error.data) : null;
  if (invalid)
    return (
      <Notice kind="err" title={tr("notice.invalid.title", { what })} action={retry}>
        <ul style={{ margin: "4px 0", paddingLeft: 18 }}>{invalid.map((m, i) => <li key={i}>{m}</li>)}</ul>
        {tr("notice.invalid.body")}{details}
      </Notice>
    );
  const known = knownErrorKey(error);
  return (
    <Notice kind="err" title={tr("notice.failed", { what })} action={retry}>
      <div>{known ? tr(known) : tr("notice.generic")}</div>
      {details}
    </Notice>
  );
}

export function Busy({ label, elapsed }: { label: string; elapsed?: number }) {
  return (
    <div role="status" aria-live="polite">
      <div className="row" style={{ marginBottom: 8, fontSize: 13 }}>
        <span className="spinner" /> <span>{label}</span>
        {elapsed !== undefined && <span className="muted mono">{t("busy.elapsed", { n: elapsed })}</span>}
      </div>
      <div className="progress" />
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Metric({ k, v, hint, placeholder = "—" }: { k: string; v: ReactNode | undefined | null; hint?: string; placeholder?: string }) {
  const na = v === undefined || v === null;
  return (
    <div className="metric" title={hint}>
      <div className="k">{k}</div>
      <div className={`v ${na ? "na" : ""}`}>{na ? placeholder : v}</div>
    </div>
  );
}

export function NextStep({ prev, next }: { prev?: { to: string; label: string }; next?: { to: string; label: string } }) {
  return (
    <div className="footer-nav">
      {prev ? <Link to={prev.to}>← {prev.label}</Link> : <span />}
      {next && <Link to={next.to}><button className="primary">{t("next.step", { label: next.label })} →</button></Link>}
    </div>
  );
}

/** Wraps pages that need a selected scenario; handles none-selected / loading / load-failure states. */
export function ScenarioGate({ title, children }: { title: string; children: ReactNode }) {
  const { id, ir, loading, error, reload } = useScenario();
  if (!id)
    return (
      <div className="page">
        <PageHead title={title} />
        <Notice title={t("gate.noScenario")} action={<Link to="/import"><button className="primary small">{t("gate.importBtn")}</button></Link>}>
          {t("gate.noScenario.body1")} <Link to="/">{t("gate.noScenario.home")}</Link>{t("gate.noScenario.body2")}
        </Notice>
      </div>
    );
  if (!ir)
    return (
      <div className="page">
        <PageHead title={title} />
        {loading ? <div className="card"><Busy label={t("gate.loading")} /></div> : <ApiNotice error={error} what={t("gate.loadWhat")} onRetry={reload} />}
      </div>
    );
  return <>{children}</>;
}

/** Renders JSON of unknown shape (backend reports/status) as readable key-value tables instead of guessing fields. */
export function DataView({ data, depth = 0 }: { data: unknown; depth?: number }) {
  if (data === null || data === undefined) return <span className="muted">—</span>;
  if (typeof data === "boolean") return <span className={data ? "status-PASS" : "status-FAIL"}>{data ? t("data.yes") : t("data.no")}</span>;
  if (typeof data !== "object") {
    const s = String(data);
    return s.includes("\n") ? <pre className="mono" style={{ margin: 0, maxHeight: 260 }}>{s}</pre> : <span>{s}</span>;
  }
  if (depth > 4) return <span className="mono">{JSON.stringify(data)}</span>;
  if (Array.isArray(data)) {
    if (data.length === 0) return <span className="muted">{t("data.empty")}</span>;
    const objs = data.every((x) => x && typeof x === "object" && !Array.isArray(x));
    if (objs) {
      const cols = Array.from(new Set(data.flatMap((x) => Object.keys(x as object)))).slice(0, 8);
      return (
        <div style={{ overflowX: "auto" }}>
          <table className="tbl">
            <thead><tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr></thead>
            <tbody>
              {data.map((x, i) => (
                <tr key={i}>{cols.map((c) => <td key={c}><DataView data={(x as any)[c]} depth={depth + 1} /></td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }
    return <ul style={{ margin: 0, paddingLeft: 18 }}>{data.map((x, i) => <li key={i}><DataView data={x} depth={depth + 1} /></li>)}</ul>;
  }
  const entries = Object.entries(data as object);
  if (entries.length === 0) return <span className="muted">{t("data.empty")}</span>;
  return (
    <dl className="kv">
      {entries.map(([k, v]) => (
        <div key={k} style={{ display: "contents" }}>
          <dt className="mono">{k}</dt>
          <dd><DataView data={v} depth={depth + 1} /></dd>
        </div>
      ))}
    </dl>
  );
}

export const fmtTime = (iso?: string) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleString(getLocale(), { hour12: false });
};
export const pct = (x?: number) => (typeof x === "number" ? `${Math.round(x * 100)}%` : undefined);
