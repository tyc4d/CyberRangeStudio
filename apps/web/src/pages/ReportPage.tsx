import { useMemo } from "react";
import { live, t, type MsgKey } from "../i18n";
import { Link } from "react-router-dom";
import type { CheckStatus, ScenarioIR, ValidationCheck, ValidationReport } from "@contracts";
import { SubstituteCard, VersionBasisCard } from "../components/VersionBasis";
import { api } from "../lib/api";
import { useAction, useLoad } from "../lib/hooks";
import { useScenario } from "../lib/scenario";
import { ApiNotice, Busy, Empty, fmtTime, NextStep, Notice, PageHead, ScenarioGate, StatusPill } from "../components/ui";

type Level = "env_build" | "behavior_repro" | "full_chain";
const LEVELS: { key: Level; title: string; question: string; categories: ValidationCheck["category"][] }[] = live(() => [
  { key: "env_build", title: t("rp.l.env"), question: t("rp.l.env.q"), categories: ["service_up", "connectivity", "dependency_present"] },
  { key: "behavior_repro", title: t("rp.l.behavior"), question: t("rp.l.behavior.q"), categories: ["behavior"] },
  { key: "full_chain", title: t("rp.l.chain"), question: t("rp.l.chain.q"), categories: ["chain"] },
]);
const CATEGORIES = ["service_up", "version", "connectivity", "dependency_present", "behavior", "chain"];
const categoryLabel = (c: string) => (CATEGORIES.includes(c) ? t(`rp.c.${c}` as MsgKey) : c);

/* ---------- validator sentences in the UI language ----------
 * The validator writes check names, expectations and observations in English. Known sentence shapes are shown in the
 * UI language. The original text stays available as a tooltip. Unknown text is shown as written, never guessed at. */
const hasCJK = (x: string) => /[\u3400-\u9fff]/.test(x);
type Rule = [RegExp, (m: RegExpMatchArray) => string];
const NAME_RULES: Rule[] = [
  [/^(.+) is running$/, (m) => t("rp.n.running", { x: m[1] })],
  [/^(.+) has the Python runtime$/, (m) => t("rp.n.python", { x: m[1] })],
  [/^(.+) runs the pinned (.+) version$/, (m) => t("rp.n.pinned", { x: m[1], v: m[2] })],
  [/^(.+) reaches (.+)$/, (m) => t("rp.n.reaches", { x: m[1], y: m[2] })],
  [/^(.+) returns a benign service response$/, (m) => t("rp.n.benign", { x: m[1] })],
  [/^(.+) completes the declared path to (.+)$/, (m) => t("rp.n.path", { x: m[1], y: m[2] })],
  [/^unmapped behavior$/, () => t("rp.n.unmapped")],
];
const EXPECT_RULES: Rule[] = [
  [/^container state is running$/, () => t("rp.e.running")],
  [/^Python standard library imports successfully$/, () => t("rp.e.python")],
  [/^one TCP connection to declared service (.+)$/, (m) => t("rp.e.tcp", { svc: m[1] })],
  [/^pg_isready reports accepting connections$/, () => t("rp.e.pg")],
  [/^HTTP GET (\S+) returns status 200 from the pinned web server$/, (m) => t("rp.e.http200", { path: m[1] })],
  [/^HTTP GET (\S+) returns (\S+)$/, (m) => t("rp.e.http", { path: m[1], code: m[2] })],
  [/^HTTP service returns its expected benign response$/, () => t("rp.e.httpBenign")],
  [/^a mapped benign behavior$/, () => t("rp.e.mapped")],
  [/^declared TCP path and its benign service behavior pass$/, () => t("rp.e.chain")],
];
const OBSERVED_RULES: Rule[] = [
  [/^state=(\S+), health=(.+)$/, (m) => t("rp.o.state", { state: m[1], health: m[2] === "no health status" ? t("rp.o.noHealth") : m[2] })],
  [/^container not present in docker compose ps output$/, () => t("rp.o.missing")],
  [/^only declared TCP service ports are probed$/, () => t("rp.o.onlyTcp")],
  [/^source or target container is not running; this path was not probed$/, () => t("rp.o.notRunning")],
  [/^PostgreSQL container is not running$/, () => t("rp.o.pgDown")],
  [/^HTTP behavior was not probed because its path was unavailable$/, () => t("rp.o.httpSkipped")],
  [/^no benign behavior probe exists for the target service$/, () => t("rp.o.noProbe")],
  [/^(.*) \(target name did not resolve; inconclusive\)$/, (m) => t("rp.o.unresolved", { x: m[1] })],
];
/** A validator sentence in the UI language, or null when it is not a known shape. */
function render(text: string, rules: Rule[]): string | null {
  const x = text.trim();
  if (!x || hasCJK(x)) return null;
  for (const [re, f] of rules) { const m = x.match(re); if (m) return f(m); }
  return null;
}
/** Known sentences in the UI language, with the original as a tooltip. Unknown text is shown unchanged. */
function Bi({ text, rules, raw }: { text?: string | null; rules: Rule[]; raw?: boolean }) {
  if (text === undefined || text === null || text === "") return <span className="muted">—</span>;
  const s = String(text);
  // Observations joined with "; " (chain checks) are rendered part by part.
  const parts = s.split("; ");
  const tr = parts.map((x) => render(x, rules));
  if (tr.every((x) => x === null)) {
    return hasCJK(s) || !raw ? <>{s}</> : <span className="mono" style={{ overflowWrap: "anywhere" }} title={t("rp.raw")}>{s}</span>;
  }
  return <span title={`${t("rp.raw")}: ${s}`}>{tr.map((x, i) => x ?? parts[i]).join(" · ")}</span>;
}

const isReport = (x: any): x is ValidationReport => !!x && typeof x === "object" && !!x.levels && Array.isArray(x.checks);

function CheckTable({ checks, actionName }: { checks: ValidationCheck[]; actionName: Map<string, string> }) {
  if (checks.length === 0) return <Empty>{t("rp.noChecks")}</Empty>;
  return (
    <div style={{ overflowX: "auto" }}>
      <table className="tbl tbl-stack check-table" style={{ tableLayout: "fixed" }}>
        <colgroup><col style={{ width: 96 }} /><col /><col style={{ width: 110 }} /><col style={{ width: "22%" }} /><col style={{ width: "26%" }} /></colgroup>
        <thead><tr><th>{t("rp.col.result")}</th><th>{t("rp.col.check")}</th><th>{t("rp.col.cat")}</th><th>{t("rp.col.expected")}</th><th>{t("rp.col.observed")}</th></tr></thead>
        <tbody>
          {checks.map((c) => (
            <tr key={c.id}>
              <td className="nowrap"><StatusPill status={c.status} /></td>
              <td data-label={t("rp.col.check")}>
                <div><Bi text={c.name} rules={NAME_RULES} /></div>
                {c.action_ref && <div className="muted" style={{ fontSize: 13 }}>{t("rp.forAction", { name: actionName.get(c.action_ref) ?? c.action_ref })}</div>}
              </td>
              <td className="nowrap muted" data-label={t("rp.col.cat")}>{categoryLabel(c.category)}</td>
              <td style={{ fontSize: 13 }} data-label={t("rp.col.expected")}><Bi text={c.expected} rules={EXPECT_RULES} /></td>
              <td style={{ fontSize: 13 }} data-label={t("rp.col.observed")}>
                <Bi text={c.observed} rules={OBSERVED_RULES} raw />
                {c.evidence && <details style={{ marginTop: 4 }}><summary className="muted" style={{ cursor: "pointer" }}>{t("rp.evidence")}</summary><pre className="mono" style={{ margin: "6px 0 0", maxHeight: 200, whiteSpace: "pre-wrap" }}>{c.evidence}</pre></details>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FidelityList({ title, cls, items, actionName }: { title: string; cls: string; items?: string[]; actionName: Map<string, string> }) {
  return (
    <div className="metric">
      <div className={`k ${cls}`} style={{ fontWeight: 600 }}>{title} · {items?.length ?? 0}</div>
      {items?.length ? (
        <ul style={{ margin: "8px 0 0", paddingLeft: 18, fontSize: 14 }}>{items.map((x, i) => <li key={i}>{actionName.get(x) ?? x}</li>)}</ul>
      ) : <div className="muted" style={{ fontSize: 13, marginTop: 6 }}>{t("rp.none")}</div>}
    </div>
  );
}

function Body({ ir }: { ir: ScenarioIR }) {
  const { reload: reloadIr } = useScenario();
  // Validation probes a running environment; without one the API refuses (「尚未部署」). Unknown status never blocks the button.
  const deploy = useLoad(() => api.deployStatus(ir.id), [ir.id]);
  const deployState = typeof deploy.data?.state === "string" ? (deploy.data.state as string) : undefined;
  const notDeployed = deployState !== undefined && deployState !== "running";
  const remote = useLoad(() => api.getReport(ir.id), [ir.id]);
  const run = useAction(async () => {
    const resp = await api.runValidation(ir.id);
    if (isReport(resp)) remote.setData(resp); else await remote.reload(true);
    void reloadIr();
  });

  // Prefer the validation endpoint; fall back to the report stored in the IR (also real backend data).
  const fromRemote = isReport(remote.data) ? remote.data : null;
  const report: ValidationReport | null = fromRemote ?? (isReport(ir.validation) ? ir.validation : null);
  const noReportYet = !!remote.error && remote.error.status === 404 && remote.error.kind === "error";
  const actionName = useMemo(() => new Map(ir.actions.map((a) => [a.id, a.name])), [ir.actions]);

  const byLevel = useMemo(() => {
    const m: Record<Level, ValidationCheck[]> = { env_build: [], behavior_repro: [], full_chain: [] };
    const other: ValidationCheck[] = [];
    (report?.checks ?? []).forEach((c) => {
      const lv = LEVELS.find((l) => l.categories.includes(c.category));
      (lv ? m[lv.key] : other).push(c);
    });
    return { m, other };
  }, [report]);
  const count = (cs: ValidationCheck[], s: CheckStatus) => cs.filter((c) => c.status === s).length;
  const f = report?.fidelity;

  return (
    <div className="page">
      <PageHead title={t("rp.title")} desc={t("rp.desc")}>
        <button className={report ? "" : "primary"} disabled={run.busy || notDeployed} title={notDeployed ? t("rp.needDeploy") : undefined} onClick={() => run.run()}>{report ? t("rp.rerun") : t("rp.run")}</button>
      </PageHead>

      {notDeployed && (
        <Notice kind="warn" title={t("rp.notDeployed.title")}
          action={<Link to="/deploy"><button className="primary small">{t("rp.toDeploy")}</button></Link>}>
          <div>{t("rp.notDeployed.body", { state: deployState })}</div>
          <div>{report ? t("rp.oldReport") : t("rp.noResult")}</div>
        </Notice>
      )}

      {run.busy && <div className="card"><Busy label={t("rp.busy")} elapsed={run.elapsed} /></div>}
      <ApiNotice error={run.error} what={t("rp.runWhat")} />
      {remote.error && !noReportYet && <ApiNotice error={remote.error} what={t("rp.readWhat")} onRetry={() => remote.reload()} />}
      {remote.error && !noReportYet && report && <div className="muted" style={{ fontSize: 13, marginTop: -8 }}>{t("rp.savedReport")}</div>}

      {remote.loading && !report ? (
        <div className="card"><Busy label={t("rp.loading")} /></div>
      ) : !report ? (
        <div className="card"><Empty>{t("rp.empty")}</Empty></div>
      ) : (
        <>
          <div className="muted" style={{ fontSize: 13 }}>
            {t("rp.runAt", { time: fmtTime(report.run_at) })}
          </div>

          <div className="grid c3">
            {LEVELS.map((l, i) => {
              const cs = byLevel.m[l.key];
              return (
                <div key={l.key} className="card" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  <div className="row" style={{ flexWrap: "nowrap" }}>
                    <span className="muted mono">{i + 1}</span><h2>{l.title}</h2>
                    <span style={{ marginLeft: "auto" }}><StatusPill status={report.levels[l.key]} /></span>
                  </div>
                  <div className="muted" style={{ fontSize: 13 }}>{l.question}</div>
                  <div className="mono muted" style={{ fontSize: 13 }}>
                    {cs.length === 0 ? t("rp.noLevelChecks") : t("rp.counts", { p: count(cs, "PASS"), pa: count(cs, "PARTIAL"), f: count(cs, "FAIL"), n: count(cs, "NOT_TESTED") })}
                  </div>
                </div>
              );
            })}
          </div>
          {report.levels.env_build === "PASS" && report.levels.full_chain !== "PASS" && (
            <Notice kind="warn">{t("rp.chainWarn", { status: t(`check.${report.levels.full_chain === "NOT_TESTED" || report.levels.full_chain === "PARTIAL" ? report.levels.full_chain : "FAIL"}` as MsgKey) })}</Notice>
          )}

          <VersionBasisCard ir={ir} context="report" />
          <SubstituteCard ir={ir} context="report" />

          {LEVELS.map((l, i) => (
            <div key={l.key} className="card flush">
              <div className="card-head">
                <span className="muted mono">{i + 1}</span><h2>{l.title}</h2>
                                <div className="right"><StatusPill status={report.levels[l.key]} /></div>
              </div>
              <CheckTable checks={byLevel.m[l.key]} actionName={actionName} />
            </div>
          ))}
          {byLevel.other.length > 0 && (
            <div className="card flush">
              <div className="card-head"><h2>{t("rp.other")}</h2></div>
              <CheckTable checks={byLevel.other} actionName={actionName} />
            </div>
          )}

          <div className="card" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <h2 style={{ margin: 0 }}>{t("rp.fidelity")}</h2>
            {!f ? <span className="muted" style={{ fontSize: 14 }}>{t("rp.noFidelity")}</span> : (
              <>
                {f.summary && <div style={{ fontSize: 14, lineHeight: 1.6 }} lang={hasCJK(f.summary) ? undefined : "en"} className={hasCJK(f.summary) ? undefined : "muted"}>{f.summary}</div>}
                <div className="grid c4">
                  <FidelityList title={t("rp.f.reproduced")} cls="status-PASS" items={f.reproduced} actionName={actionName} />
                  <FidelityList title={t("rp.f.partial")} cls="status-PARTIAL" items={f.partial} actionName={actionName} />
                  <FidelityList title={t("rp.f.not")} cls="status-FAIL" items={f.not_reproduced} actionName={actionName} />
                  <FidelityList title={t("rp.f.untested")} cls="status-NOT_TESTED" items={f.not_tested} actionName={actionName} />
                </div>
                <div>
                  <h3 style={{ marginBottom: 8 }}>{t("rp.subs")}</h3>
                  {f.substitutes_used?.length ? (
                    <table className="tbl">
                      <thead><tr><th>{t("rp.col.service")}</th><th>{t("rp.col.real")}</th><th>{t("rp.col.sub")}</th><th>{t("rp.col.diff")}</th></tr></thead>
                      <tbody>
                        {f.substitutes_used.map((s, i) => (
                          <tr key={i}>
                            <td className="mono">{s.service_ref ?? "—"}</td><td>{s.real ?? "—"}</td>
                            <td><span className="tag sub">{s.substitute ?? "—"}</span></td><td className="muted">{s.difference ?? "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : <span className="muted" style={{ fontSize: 14 }}>{t("rp.noSubs")}</span>}
                </div>
              </>
            )}
          </div>
        </>
      )}

      <NextStep prev={{ to: "/deploy", label: t("stage.deploy") }} />
    </div>
  );
}

export function ReportPage() {
  const { ir } = useScenario();
  return <ScenarioGate title={t("rp.title")}>{ir && <Body key={ir.id} ir={ir} />}</ScenarioGate>;
}
