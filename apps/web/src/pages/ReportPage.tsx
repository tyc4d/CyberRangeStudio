import { useMemo } from "react";
import { Link } from "react-router-dom";
import type { CheckStatus, ScenarioIR, ValidationCheck, ValidationReport } from "@contracts";
import { SubstituteCard, VersionBasisCard } from "../components/VersionBasis";
import { api } from "../lib/api";
import { useAction, useLoad } from "../lib/hooks";
import { useScenario } from "../lib/scenario";
import { ApiNotice, Busy, Empty, fmtTime, NextStep, Notice, PageHead, ScenarioGate, StatusPill } from "../components/ui";

type Level = "env_build" | "behavior_repro" | "full_chain";
const LEVELS: { key: Level; title: string; question: string; categories: ValidationCheck["category"][] }[] = [
  { key: "env_build", title: "環境建置", question: "環境有照規劃建起來嗎？（服務啟動、連線、依賴存在）", categories: ["service_up", "connectivity", "dependency_present"] },
  { key: "behavior_repro", title: "行為重現", question: "個別攻擊行為對應的條件，能在環境中觀察到嗎？", categories: ["behavior"] },
  { key: "full_chain", title: "完整攻擊鏈", question: "整條流程能從頭到尾串起來嗎？", categories: ["chain"] },
];
const CATEGORY: Record<string, string> = {
  service_up: "服務啟動", version: "版本", connectivity: "連線", dependency_present: "依賴存在", behavior: "行為", chain: "攻擊鏈",
};

/* ---------- Chinese rendering of the validator's English strings ----------
 * The validator writes check names / expectations / observations in English. Known sentence
 * shapes are rendered in Chinese with the original kept underneath; raw tool output and
 * anything unrecognised is shown as-is, never guessed at. */
const hasCJK = (t: string) => /[\u3400-\u9fff]/.test(t);
type Rule = [RegExp, (m: RegExpMatchArray) => string];
const NAME_RULES: Rule[] = [
  [/^(.+) is running$/, (m) => `${m[1]} 正在執行`],
  [/^(.+) has the Python runtime$/, (m) => `${m[1]} 具備 Python 執行環境`],
  [/^(.+) runs the pinned (.+) version$/, (m) => `${m[1]} 執行的是釘選版本 ${m[2]}`],
  [/^(.+) reaches (.+)$/, (m) => `${m[1]} 可連到 ${m[2]}`],
  [/^(.+) returns a benign service response$/, (m) => `${m[1]} 回應無害的服務請求`],
  [/^(.+) completes the declared path to (.+)$/, (m) => `${m[1]} 走完到 ${m[2]} 的宣告路徑`],
  [/^unmapped behavior$/, () => "沒有對應探測的行為"],
];
const EXPECT_RULES: Rule[] = [
  [/^container state is running$/, () => "容器狀態為執行中"],
  [/^Python standard library imports successfully$/, () => "Python 標準函式庫可成功匯入"],
  [/^one TCP connection to declared service (.+)$/, (m) => `能對宣告的服務 ${m[1]} 建立一次 TCP 連線`],
  [/^pg_isready reports accepting connections$/, () => "pg_isready 回報可接受連線"],
  [/^HTTP GET (\S+) returns status 200 from the pinned web server$/, (m) => `對釘選的網頁伺服器 HTTP GET ${m[1]} 回傳 200`],
  [/^HTTP GET (\S+) returns (\S+)$/, (m) => `HTTP GET ${m[1]} 回傳 ${m[2]}`],
  [/^HTTP service returns its expected benign response$/, () => "HTTP 服務回傳預期的無害回應"],
  [/^a mapped benign behavior$/, () => "有對應的無害行為探測"],
  [/^declared TCP path and its benign service behavior pass$/, () => "宣告的 TCP 路徑與其無害服務行為都通過"],
];
const OBSERVED_RULES: Rule[] = [
  [/^state=(\S+), health=(.+)$/, (m) => `容器狀態 ${m[1]}，健康檢查 ${m[2] === "no health status" ? "未設定" : m[2]}`],
  [/^container not present in docker compose ps output$/, () => "docker compose ps 的輸出中沒有這個容器"],
  [/^only declared TCP service ports are probed$/, () => "只探測有宣告的 TCP 服務埠，這條路徑未探測"],
  [/^source or target container is not running; this path was not probed$/, () => "來源或目標容器未執行，這條路徑未探測"],
  [/^PostgreSQL container is not running$/, () => "PostgreSQL 容器未執行"],
  [/^HTTP behavior was not probed because its path was unavailable$/, () => "路徑不通，未探測 HTTP 行為"],
  [/^no benign behavior probe exists for the target service$/, () => "目標服務沒有可用的無害行為探測"],
  [/^(.*) \(target name did not resolve; inconclusive\)$/, (m) => `${m[1]}（目標名稱無法解析，結果不確定）`],
];
/** Chinese rendering of a validator sentence, or null when it is not a known shape. */
function zh(text: string, rules: Rule[]): string | null {
  const t = text.trim();
  if (!t || hasCJK(t)) return null;
  for (const [re, f] of rules) { const m = t.match(re); if (m) return f(m); }
  return null;
}
/** Chinese first, the original English underneath; unknown text is shown unchanged. */
function Bi({ text, rules, raw }: { text?: string | null; rules: Rule[]; raw?: boolean }) {
  if (text === undefined || text === null || text === "") return <span className="muted">—</span>;
  const s = String(text);
  // Observations joined with "; " (chain checks) are translated part by part.
  const parts = s.split("; ");
  const tr = parts.map((x) => zh(x, rules));
  if (tr.every((x) => x === null)) {
    return hasCJK(s) || !raw ? <>{s}</> : <span className="mono" style={{ overflowWrap: "anywhere" }} title="驗證工具的原始輸出">{s}</span>;
  }
  return (
    <>
      <div>{tr.map((x, i) => x ?? parts[i]).join("；")}</div>
      <div className="muted" lang="en" style={{ fontSize: 11, overflowWrap: "anywhere" }} title="驗證工具的原始輸出">{s}</div>
    </>
  );
}

const isReport = (x: any): x is ValidationReport => !!x && typeof x === "object" && !!x.levels && Array.isArray(x.checks);

function CheckTable({ checks, actionName }: { checks: ValidationCheck[]; actionName: Map<string, string> }) {
  if (checks.length === 0) return <Empty>這一層沒有任何檢查項目。</Empty>;
  return (
    <div style={{ overflowX: "auto" }}>
      <table className="tbl" style={{ tableLayout: "fixed", minWidth: 760 }}>
        <colgroup><col style={{ width: 96 }} /><col /><col style={{ width: 110 }} /><col style={{ width: "22%" }} /><col style={{ width: "26%" }} /></colgroup>
        <thead><tr><th>結果</th><th>檢查項目</th><th>類別</th><th>預期</th><th>實際觀察</th></tr></thead>
        <tbody>
          {checks.map((c) => (
            <tr key={c.id}>
              <td className="nowrap"><StatusPill status={c.status} /></td>
              <td>
                <div><Bi text={c.name} rules={NAME_RULES} /></div>
                {c.action_ref && <div className="muted" style={{ fontSize: 12 }}>對應行為：{actionName.get(c.action_ref) ?? c.action_ref}</div>}
              </td>
              <td className="nowrap muted">{CATEGORY[c.category] ?? c.category}</td>
              <td style={{ fontSize: 12 }}><Bi text={c.expected} rules={EXPECT_RULES} /></td>
              <td style={{ fontSize: 12 }}>
                <Bi text={c.observed} rules={OBSERVED_RULES} raw />
                {c.evidence && <details style={{ marginTop: 4 }}><summary className="muted" style={{ cursor: "pointer" }}>佐證輸出</summary><pre className="mono" style={{ margin: "6px 0 0", maxHeight: 200, whiteSpace: "pre-wrap" }}>{c.evidence}</pre></details>}
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
        <ul style={{ margin: "8px 0 0", paddingLeft: 18, fontSize: 13 }}>{items.map((x, i) => <li key={i}>{actionName.get(x) ?? x}</li>)}</ul>
      ) : <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>無</div>}
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
      <PageHead title="驗證報告" desc="驗證分三層，各自獨立判定：環境建好不代表行為能重現，個別行為重現也不代表整條攻擊鏈成立。所有檢查都是無害的觀察，不執行真正的漏洞利用。">
        <button className={report ? "" : "primary"} disabled={run.busy || notDeployed} title={notDeployed ? "需先在「部署管理」啟動環境" : undefined} onClick={() => run.run()}>{report ? "重新驗證" : "執行驗證"}</button>
      </PageHead>

      {notDeployed && (
        <Notice kind="warn" title="環境尚未部署，不能執行驗證"
          action={<Link to="/deploy"><button className="primary small">前往部署管理</button></Link>}>
          驗證是對執行中的環境逐項檢查。目前部署狀態為 <span className="mono">{deployState}</span>，請先啟動環境。
          {report ? "下方是先前留下的報告，不代表目前的環境狀態。" : "在此之前沒有任何驗證結果，各層一律視為未測。"}
        </Notice>
      )}

      {run.busy && <div className="card"><Busy label="驗證中，正在對部署的環境逐項檢查…" elapsed={run.elapsed} /></div>}
      <ApiNotice error={run.error} what="執行驗證" />
      {remote.error && !noReportYet && <ApiNotice error={remote.error} what="讀取驗證報告" onRetry={() => remote.reload()} />}
      {remote.error && !noReportYet && report && <div className="muted" style={{ fontSize: 12, marginTop: -8 }}>以下顯示的是情境中已儲存的上一份報告。</div>}

      {remote.loading && !report ? (
        <div className="card"><Busy label="讀取驗證報告…" /></div>
      ) : !report ? (
        <div className="card"><Empty>這個情境還沒有驗證報告。先在「部署管理」啟動環境，再按右上角「執行驗證」。</Empty></div>
      ) : (
        <>
          <div className="muted" style={{ fontSize: 12 }}>
            執行時間：{fmtTime(report.run_at)}{report.deployment_id && <> · 部署 <span className="mono">{report.deployment_id}</span></>}
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
                  <div className="muted" style={{ fontSize: 12 }}>{l.question}</div>
                  <div className="mono muted" style={{ fontSize: 12 }}>
                    {cs.length === 0 ? "沒有檢查項目" : `通過 ${count(cs, "PASS")} · 部分 ${count(cs, "PARTIAL")} · 失敗 ${count(cs, "FAIL")} · 未測 ${count(cs, "NOT_TESTED")}`}
                  </div>
                </div>
              );
            })}
          </div>
          {report.levels.env_build === "PASS" && report.levels.full_chain !== "PASS" && (
            <Notice kind="warn">環境建置通過，但完整攻擊鏈為「{report.levels.full_chain === "NOT_TESTED" ? "未測" : report.levels.full_chain === "PARTIAL" ? "部分" : "失敗"}」。這個環境目前不能視為已重現整個攻擊情境。</Notice>
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
              <div className="card-head"><h2>未歸類的檢查</h2></div>
              <CheckTable checks={byLevel.other} actionName={actionName} />
            </div>
          )}

          <div className="card" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <h2 style={{ margin: 0 }}>擬真度</h2>
            {!f ? <span className="muted" style={{ fontSize: 13 }}>這份報告沒有提供擬真度評估。</span> : (
              <>
                {f.summary && <div style={{ fontSize: 13, lineHeight: 1.6 }} lang={hasCJK(f.summary) ? undefined : "en"} className={hasCJK(f.summary) ? undefined : "muted"}>{!hasCJK(f.summary) && <span>後端摘要（英文原文）：</span>}{f.summary}</div>}
                <div className="grid c4">
                  <FidelityList title="已重現" cls="status-PASS" items={f.reproduced} actionName={actionName} />
                  <FidelityList title="部分重現" cls="status-PARTIAL" items={f.partial} actionName={actionName} />
                  <FidelityList title="未重現" cls="status-FAIL" items={f.not_reproduced} actionName={actionName} />
                  <FidelityList title="未測試" cls="status-NOT_TESTED" items={f.not_tested} actionName={actionName} />
                </div>
                <div>
                  <h3 style={{ marginBottom: 8 }}>使用的替代品</h3>
                  {f.substitutes_used?.length ? (
                    <table className="tbl">
                      <thead><tr><th>服務</th><th>報告中的原始軟體</th><th>環境中的替代品</th><th>差異</th></tr></thead>
                      <tbody>
                        {f.substitutes_used.map((s, i) => (
                          <tr key={i}>
                            <td className="mono">{s.service_ref ?? "—"}</td><td>{s.real ?? "—"}</td>
                            <td><span className="tag sub">{s.substitute ?? "—"}</span></td><td className="muted">{s.difference ?? "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : <span className="muted" style={{ fontSize: 13 }}>沒有使用替代品。</span>}
                </div>
              </>
            )}
          </div>
        </>
      )}

      <NextStep prev={{ to: "/deploy", label: "部署管理" }} />
    </div>
  );
}

export function ReportPage() {
  const { ir } = useScenario();
  return <ScenarioGate title="驗證報告">{ir && <Body key={ir.id} ir={ir} />}</ScenarioGate>;
}
