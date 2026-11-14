// Shared presentational pieces used by every page.
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { CheckStatus, EpistemicStatus, Evidence, Source } from "@contracts";
import type { ApiError } from "../lib/api";
import { useScenario } from "../lib/scenario";

export const EPISTEMIC: Record<EpistemicStatus, { label: string; glyph: string; hint: string }> = {
  supported: { label: "原文", glyph: "✓", hint: "原文明確寫出" },
  inferred: { label: "推論補全", glyph: "＋", hint: "原文未寫，依攻擊鏈推論補上，讓流程能接起來" },
  absent: { label: "原文未提", glyph: "○", hint: "原文沒給，待你補充" },
  // The backend sets this when the cited quotes could not be matched to the source — not when the source is silent.
  insufficient: { label: "證據不足", glyph: "?", hint: "附的引文沒有對上原文，需要人工對照原文確認" },
};
/** Content taken from an imported STIX / Attack Flow file was never checked against a report text, so it must not read as "原文". */
export const IMPORTED = { label: "來自匯入檔", glyph: "⇩", hint: "內容取自匯入的 STIX／Attack Flow 檔，沒有可對照的原文引文" };
export const isImported = (source?: Source | string) => source === "stix";
/** Badge text for a claim: its epistemic status, except that imported items say where they came from instead of "原文". */
export const claimLabel = (status?: EpistemicStatus | string, source?: Source | string) =>
  isImported(source) && status === "supported" ? IMPORTED.label : EPISTEMIC[status as EpistemicStatus]?.label ?? String(status ?? "—");
export const EPISTEMIC_ORDER: EpistemicStatus[] = ["supported", "inferred", "absent", "insufficient"];

export function EpistemicBadge({ status, source }: { status?: EpistemicStatus; source?: Source }) {
  if (isImported(source) && status === "supported")
    return <span className="badge validated" title={IMPORTED.hint}><span aria-hidden>{IMPORTED.glyph}</span> {IMPORTED.label}</span>;
  if (!status) return <span className="badge" title="後端未提供 epistemic_status">—</span>;
  const e = EPISTEMIC[status];
  if (!e) return <span className="badge">{String(status)}</span>;
  return <span className={`badge ${status}`} title={e.hint}><span aria-hidden>{e.glyph}</span> {e.label}</span>;
}

// ---- citation quality: how well the quotes behind a claim match the source. Independent of the claim's own status. ----
export type QuoteLevel = "exact" | "strong" | "partial" | "none";
export const QUOTE_LEVEL: Record<QuoteLevel, { cls: string; mark: string; word: string; desc: string }> = {
  exact: { cls: "status-PASS", mark: "✓", word: "逐字", desc: "與原文逐字相符（比對時忽略空白、換行與破折號寫法，並忽略 ATT&CK 編號標記，例如 [T1190]）" },
  strong: { cls: "status-PASS", mark: "✓", word: "相符", desc: "與原文高度相符" },
  partial: { cls: "status-PARTIAL", mark: "～", word: "片段", desc: "僅關鍵字／片段相符，非原文原句（常見於把兩句接成一句，或中間省略）" },
  none: { cls: "status-FAIL", mark: "✗", word: "沒對上", desc: "原文中找不到此引文" },
};
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
export const CITATION: Record<CitationState, { label: string; cls: string; hint: string }> = {
  all: { label: "引文全部成立", cls: "approved", hint: "附的每一句引文都能在原文找到" },
  some: { label: "引文未完全對上", cls: "pending", hint: "有引文只對上片段（關鍵字或片段在原文裡，但不是原文原句），或有引文在原文找不到；請對照原文" },
  none: { label: "引文都沒對上", cls: "insufficient", hint: "附的引文沒有一句能在原文找到，需要人工對照原文" },
  empty: { label: "沒有附引文", cls: "absent", hint: "這個項目沒有附任何原文引文" },
  ungraded: { label: "引文未核對", cls: "", hint: "後端沒有提供這些引文的核對結果" },
};
/** Says exactly what was found, e.g. "2 句都只對上片段" — a fragment match is never worded as "沒對上". */
export function citationText(s: CitationSummary): string {
  if (s.state !== "some" && s.state !== "none") return CITATION[s.state].label;
  const partial = s.partial ?? 0;
  const missing = s.missing ?? 0;
  const ungraded = Math.max(0, s.total - s.ok - partial - missing);
  if (s.ok === 0 && ungraded === 0) {
    if (missing === 0) return s.total === 1 ? "這句引文只對上片段" : `${partial} 句都只對上片段`;
    if (partial === 0) return s.total === 1 ? "這句引文沒對上" : `${missing} 句引文都沒對上`;
  }
  const bits = [
    s.ok > 0 && `${s.ok} 句成立`,
    partial > 0 && `${partial} 句只對上片段`,
    missing > 0 && `${missing} 句沒對上`,
    ungraded > 0 && `${ungraded} 句未核對`,
  ].filter(Boolean);
  return bits.length ? `${s.total} 句中 ${bits.join("、")}` : CITATION[s.state].label;
}
export const INFERRED_BASIS = {
  label: "推論依據（非直接證據）",
  hint: "這個項目是推論補全：原文沒有直接寫出。這裡列的句子是推論時參考的上下文，不是直接證據，所以不套用「成立／沒對上」的判定。",
};
/** The worst-case quality of the quotes behind one claim. Shown NEXT TO the claim status, never merged into it.
 *  `basis` = the claim is inferred: its quotes are context for the inference, not proof, so no verdict is shown. */
export function CitationBadge({ summary, source, basis }: { summary: CitationSummary; source?: Source; basis?: boolean }) {
  if (basis)
    return <span className="badge absent" title={INFERRED_BASIS.hint}>{summary.total > 0 ? INFERRED_BASIS.label : "推論補全，未附推論依據"}</span>;
  if (summary.state === "empty" && isImported(source)) return <span className="muted" style={{ fontSize: 11 }} title={IMPORTED.hint}>匯入檔無引文</span>;
  const c = CITATION[summary.state];
  const onlyFragments = summary.state === "some" && summary.ok === 0 && (summary.missing ?? 0) === 0;
  const hint = onlyFragments ? "每一句引文的關鍵字或片段都在原文裡，但都不是原文原句（常見於把兩句接成一句，或中間省略）；沒有找不到的引文。建議對照原文確認。" : c.hint;
  return <span className={`badge ${c.cls}`} title={hint}>{citationText(summary)}</span>;
}
/** Human-readable position of a quote: "第 7 段" instead of "paragraph 7". Null when the backend gave none. */
export function locatorText(locator?: { kind?: string; ref?: unknown } | null): string | null {
  const ref = locator?.ref === undefined || locator?.ref === null ? "" : String(locator.ref).trim();
  if (!ref) return null;
  const num = /^\d+$/.test(ref);
  if (locator?.kind === "page") return num ? `第 ${ref} 頁` : `頁 ${ref}`;
  if (locator?.kind === "paragraph") return num ? `第 ${ref} 段` : `段落 ${ref}`;
  if (locator?.kind === "stix_path") return `匯入檔位置 ${ref}`;
  return `位置 ${ref}`;
}
/** One quote, shown as its match mark plus its first words — never as a bare "evidence-1" code. */
export function QuoteSnippet({ evidence, id, max = 26, basis }: { evidence?: Evidence | null; id: string; max?: number; basis?: boolean }) {
  if (!evidence) return <span className="status-FAIL" title={`找不到這筆證據（${id}）`}>✗ 找不到引文</span>;
  const level = quoteLevel(evidence);
  const m = level ? QUOTE_LEVEL[level] : undefined;
  const text = (evidence.quote ?? "").replace(/\s+/g, " ").trim();
  // Basis for an inference: context, not proof — no match mark, so it cannot read as a pass/fail verdict.
  if (basis)
    return (
      <span title={`${INFERRED_BASIS.label}\n${text}\n（${id}）`}>
        <span className="muted" aria-label="推論依據">·</span>{" "}
        {text.length > max ? `${text.slice(0, max)}…` : text || id}
      </span>
    );
  return (
    <span title={`${m ? `${m.desc}\n` : ""}${text}\n（${id}）`}>
      <span className={m?.cls ?? "muted"} aria-label={m?.word ?? "未核對"}>{m?.mark ?? "·"}</span>{" "}
      {text.length > max ? `${text.slice(0, max)}…` : text || id}
    </span>
  );
}

const SOURCE_LABEL: Record<Source, string> = { llm: "LLM", user: "使用者", stix: "匯入檔", program: "程式" };
export function SourceTag({ source }: { source?: Source }) {
  if (!source) return null;
  return <span className={`tag ${source === "user" ? "user" : ""}`} title={`來源：${source}`}>{SOURCE_LABEL[source] ?? source}</span>;
}

const CHECK_LABEL: Record<CheckStatus, string> = { PASS: "通過", FAIL: "失敗", PARTIAL: "部分", NOT_TESTED: "未測" };
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

/** Turns an API failure into a plain-language notice. `what` names the feature, e.g. "依賴分析". */
export function ApiNotice({ error, what, onRetry }: { error: ApiError | null; what: string; onRetry?: () => void }) {
  if (!error) return null;
  const where = error.path ? <span className="mono muted"> {error.method} {error.path}</span> : null;
  const retry = onRetry ? <button className="small" onClick={onRetry}>重試</button> : undefined;
  if (error.kind === "unimplemented")
    return <Notice kind="info" title={`${what}：後端尚未提供`} action={retry}>這個功能的後端端點還沒上線，完成後這裡會顯示真實資料。{where}</Notice>;
  if (error.kind === "offline")
    return <Notice kind="warn" title={`${what}：無法連線到後端`} action={retry}>請確認 API 服務已啟動（預設 127.0.0.1:8077）。{where}</Notice>;
  return (
    <Notice kind="err" title={`${what}失敗`} action={retry}>
      {error.data !== undefined ? <div style={{ margin: "4px 0" }}><DataView data={error.data} /></div> : error.detail}
      {where}
    </Notice>
  );
}

export function Busy({ label, elapsed }: { label: string; elapsed?: number }) {
  return (
    <div role="status" aria-live="polite">
      <div className="row" style={{ marginBottom: 8, fontSize: 13 }}>
        <span className="spinner" /> <span>{label}</span>
        {elapsed !== undefined && <span className="muted mono">已 {elapsed} 秒</span>}
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
      {next && <Link to={next.to}><button className="primary">下一步：{next.label} →</button></Link>}
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
        <Notice title="尚未選擇情境" action={<Link to="/import"><button className="primary small">匯入情資</button></Link>}>
          先到<Link to="/">專案首頁</Link>開啟既有情境，或匯入一份情資報告建立新情境。
        </Notice>
      </div>
    );
  if (!ir)
    return (
      <div className="page">
        <PageHead title={title} />
        {loading ? <div className="card"><Busy label="載入情境中…" /></div> : <ApiNotice error={error} what="載入情境" onRetry={reload} />}
      </div>
    );
  return <>{children}</>;
}

/** Renders JSON of unknown shape (backend reports/status) as readable key-value tables instead of guessing fields. */
export function DataView({ data, depth = 0 }: { data: unknown; depth?: number }) {
  if (data === null || data === undefined) return <span className="muted">—</span>;
  if (typeof data === "boolean") return <span className={data ? "status-PASS" : "status-FAIL"}>{data ? "是" : "否"}</span>;
  if (typeof data !== "object") {
    const s = String(data);
    return s.includes("\n") ? <pre className="mono" style={{ margin: 0, maxHeight: 260 }}>{s}</pre> : <span>{s}</span>;
  }
  if (depth > 4) return <span className="mono">{JSON.stringify(data)}</span>;
  if (Array.isArray(data)) {
    if (data.length === 0) return <span className="muted">（空）</span>;
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
  if (entries.length === 0) return <span className="muted">（空）</span>;
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
  return isNaN(d.getTime()) ? iso : d.toLocaleString("zh-TW", { hour12: false });
};
export const pct = (x?: number) => (typeof x === "number" ? `${Math.round(x * 100)}%` : undefined);
