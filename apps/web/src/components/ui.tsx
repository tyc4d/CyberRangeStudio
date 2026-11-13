// Shared presentational pieces used by every page.
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { CheckStatus, EpistemicStatus, Source } from "@contracts";
import type { ApiError } from "../lib/api";
import { useScenario } from "../lib/scenario";

export const EPISTEMIC: Record<EpistemicStatus, { label: string; hint: string }> = {
  supported: { label: "原文支持", hint: "supported：原文明確寫出" },
  inferred: { label: "推測", hint: "inferred：由原文推論，原文未明講" },
  absent: { label: "原文未提", hint: "absent：原文沒有提供" },
  insufficient: { label: "證據不足", hint: "insufficient：證據不足以判斷" },
};
export const EPISTEMIC_ORDER: EpistemicStatus[] = ["supported", "inferred", "absent", "insufficient"];

export function EpistemicBadge({ status }: { status?: EpistemicStatus }) {
  if (!status) return <span className="badge" title="後端未提供 epistemic_status">未標示</span>;
  const e = EPISTEMIC[status];
  if (!e) return <span className="badge">{String(status)}</span>;
  return <span className={`badge ${status}`} title={e.hint}>{e.label}</span>;
}

const SOURCE_LABEL: Record<Source, string> = { llm: "LLM", user: "使用者", stix: "STIX", program: "程式" };
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

export function Metric({ k, v, hint }: { k: string; v: ReactNode | undefined | null; hint?: string }) {
  const na = v === undefined || v === null;
  return (
    <div className="metric" title={hint}>
      <div className="k">{k}</div>
      <div className={`v ${na ? "na" : ""}`}>{na ? "—" : v}</div>
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
