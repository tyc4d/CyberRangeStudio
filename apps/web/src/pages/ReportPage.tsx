import { useMemo } from "react";
import type { CheckStatus, ScenarioIR, ValidationCheck, ValidationReport } from "@contracts";
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
  service_up: "服務啟動", connectivity: "連線", dependency_present: "依賴存在", behavior: "行為", chain: "攻擊鏈",
};

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
                <div>{c.name}</div>
                {c.action_ref && <div className="muted" style={{ fontSize: 12 }}>對應行為：{actionName.get(c.action_ref) ?? c.action_ref}</div>}
              </td>
              <td className="nowrap muted">{CATEGORY[c.category] ?? c.category}</td>
              <td style={{ fontSize: 12 }}>{c.expected ?? <span className="muted">—</span>}</td>
              <td style={{ fontSize: 12 }}>
                {c.observed ?? <span className="muted">—</span>}
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
        <button className={report ? "" : "primary"} disabled={run.busy} onClick={() => run.run()}>{report ? "重新驗證" : "執行驗證"}</button>
      </PageHead>

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

          {LEVELS.map((l, i) => (
            <div key={l.key} className="card flush">
              <div className="card-head">
                <span className="muted mono">{i + 1}</span><h2>{l.title}</h2>
                <span className="muted mono" style={{ fontSize: 12 }}>{l.key}</span>
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
            <h2 style={{ margin: 0 }}>擬真度（fidelity）</h2>
            {!f ? <span className="muted" style={{ fontSize: 13 }}>這份報告沒有提供擬真度評估。</span> : (
              <>
                {f.summary && <div style={{ fontSize: 13, lineHeight: 1.6 }}>{f.summary}</div>}
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
