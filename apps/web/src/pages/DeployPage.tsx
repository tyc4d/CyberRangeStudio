import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import type { ScenarioIR } from "@contracts";
import { api } from "../lib/api";
import { useAction, useLoad } from "../lib/hooks";
import { isPlanApproved } from "../lib/plan";
import { useScenario } from "../lib/scenario";
import { ApiNotice, Busy, DataView, Empty, fmtTime, NextStep, Notice, PageHead, ScenarioGate } from "../components/ui";

const POLL_MS = 5000;

function stateClass(s: string): string {
  const v = s.toLowerCase();
  if (/(fail|error|unhealthy|dead)/.test(v)) return "status-FAIL";
  if (/(running|^up$|healthy|deployed|ready)/.test(v)) return "status-PASS";
  if (/(down|stopped|exited|not_deployed|none|absent)/.test(v)) return "status-NOT_TESTED";
  return "status-PARTIAL";
}

function Body({ ir }: { ir: ScenarioIR }) {
  const { reload: reloadIr } = useScenario();
  const status = useLoad(() => api.deployStatus(ir.id), [ir.id]);
  const health = useLoad(() => api.deployHealth(ir.id), [ir.id]);
  const records = useLoad(() => api.deployRecords(ir.id), [ir.id]);
  const [auto, setAuto] = useState(true);
  const [lastAt, setLastAt] = useState<Date | null>(null);

  // Live status: poll while the tab is visible. Stop when the endpoint is not there, to avoid hammering a 404.
  const pollable = auto && status.error?.kind !== "unimplemented";
  useEffect(() => {
    if (!pollable) return;
    // Health is polled too: right after "up" the containers are still "starting", and it must not stay that way on screen.
    const t = setInterval(() => { if (!document.hidden) { void status.reload(true); void health.reload(true); } }, POLL_MS);
    return () => clearInterval(t);
  }, [pollable, status.reload, health.reload]);
  useEffect(() => { if (status.data && !status.loading) setLastAt(new Date()); }, [status.data, status.loading]);

  const after = async () => { await Promise.all([status.reload(true), health.reload(true), records.reload(true)]); void reloadIr(); };
  // Refresh even when the action fails: a refused or failed attempt is still written to the audit trail.
  const up = useAction(async () => { try { await api.deployUp(ir.id); } finally { await after(); } });
  const down = useAction(async () => { try { await api.deployDown(ir.id); } finally { await after(); } });
  const busy = up.busy || down.busy;
  const approved = isPlanApproved(ir.environment_plan);

  const s = status.data;
  const stateRaw = s && typeof s === "object" ? s.state ?? s.status : typeof s === "string" ? s : undefined;
  const state = typeof stateRaw === "string" ? stateRaw : undefined;
  const containers: unknown = s && typeof s === "object" ? s.containers ?? s.services : undefined;
  const rest = s && typeof s === "object" && !Array.isArray(s)
    ? Object.fromEntries(Object.entries(s).filter(([k]) => !["state", "status", "containers", "services"].includes(k)))
    : null;
  const ACTION: Record<string, string> = { up: "啟動", down: "關閉" };
  const rawRecords: any[] = Array.isArray(records.data?.records) ? records.data.records : [];
  const history = rawRecords.map((r) => ({ id: r.id, action: r.action, state: r.state, at: r.recorded_at, reason: r.details?.reason }));

  return (
    <div className="page">
      <PageHead title="部署管理" desc="在本機隔離環境啟動或關閉這個情境。狀態每 5 秒自動更新。">
        <button className="primary" disabled={busy || !approved} title={approved ? undefined : "需先在「拓樸」頁核准拓樸"} onClick={() => { if (window.confirm("確定要在本機隔離環境啟動這個情境的容器？")) void up.run(); }}>啟動（up）</button>
        <button className="danger" disabled={busy} onClick={() => { if (window.confirm("確定要關閉並移除這個情境的部署？")) void down.run(); }}>關閉（down）</button>
      </PageHead>

      {!approved && (
        <Notice kind="warn" title={ir.environment_plan ? "拓樸尚未核准，不能部署" : "尚無拓樸規劃，不能部署"}
          action={<Link to="/topology"><button className="primary small">前往拓樸頁</button></Link>}>
          部署前必須先由人核准拓樸（開通哪些連線、哪些路徑必須阻擋）。核准後「啟動」按鈕才會啟用。
        </Notice>
      )}
      {up.busy && <div className="card"><Busy label="啟動中，正在建立網路與容器…" elapsed={up.elapsed} /></div>}
      {down.busy && <div className="card"><Busy label="關閉中，正在移除容器…" elapsed={down.elapsed} /></div>}
      <ApiNotice error={up.error} what="啟動部署" />
      <ApiNotice error={down.error} what="關閉部署" />

      <div className="card flush">
        <div className="card-head">
          <h2>目前狀態</h2>
          {state && <span className={`pill ${stateClass(state)}`} data-testid="deploy-state">{state}</span>}
          <div className="right">
            {status.data && lastAt && <span className="muted" style={{ fontSize: 12 }}>更新於 {lastAt.toLocaleTimeString("zh-TW", { hour12: false })}</span>}
            <label className="row muted" style={{ gap: 5, fontSize: 12 }}>
              <input type="checkbox" style={{ width: "auto" }} checked={auto} onChange={(e) => setAuto(e.target.checked)} /> 自動更新
            </label>
            <button className="small" onClick={() => status.reload()} disabled={status.loading}>立即更新</button>
          </div>
        </div>
        <div style={{ padding: 14, display: "flex", flexDirection: "column", gap: 14 }}>
          {status.error && <ApiNotice error={status.error} what="部署狀態" onRetry={() => status.reload()} />}
          {status.error && status.data && <div className="muted" style={{ fontSize: 12 }}>以下是最後一次成功取得的狀態，可能已過期。</div>}
          {status.loading && !status.data && !status.error && <Busy label="讀取部署狀態…" />}
          {status.data !== null && status.data !== undefined && (
            <>
              {containers !== undefined && (
                <div>
                  <h3 style={{ marginBottom: 8 }}>容器</h3>
                  {Array.isArray(containers) && containers.length === 0 ? <span className="muted" style={{ fontSize: 13 }}>目前沒有容器在執行。</span> : <DataView data={containers} />}
                </div>
              )}
              {rest && Object.keys(rest).length > 0 && <DataView data={rest} />}
              {!state && containers === undefined && !rest && <DataView data={s} />}
            </>
          )}
        </div>
      </div>

      <div className="card flush">
        <div className="card-head">
          <h2>健康檢查</h2>
          {typeof health.data?.state === "string" && <span className={`pill ${stateClass(health.data.state)}`} data-testid="health-state">{health.data.state}</span>}
          <div className="right">
            {health.loading && <span className="spinner" />}
            <button className="small" onClick={() => health.reload()} disabled={health.loading}>重新檢查</button>
          </div>
        </div>
        <div style={{ padding: 14 }}>
          {health.error ? <ApiNotice error={health.error} what="健康檢查" onRetry={() => health.reload()} />
            : health.loading && !health.data ? <Busy label="檢查中…" />
            : health.data === null || health.data === undefined ? <span className="muted">沒有健康檢查結果。</span>
            : <DataView data={health.data} />}
        </div>
      </div>

      <div className="card flush">
        <div className="card-head"><h2>部署紀錄</h2><span className="muted" style={{ fontSize: 12 }}>{history.length}</span></div>
        {records.error && records.error.kind !== "unimplemented" ? <div style={{ padding: 14 }}><ApiNotice error={records.error} what="部署紀錄" onRetry={() => records.reload()} /></div>
          : history.length === 0 ? <Empty>這個情境還沒有部署紀錄。啟動或關閉後，每一次嘗試（包含被拒絕的）都會記在這裡。</Empty> : (
          <table className="tbl" data-testid="deploy-records">
            <thead><tr><th>時間</th><th>動作</th><th>結果</th><th>說明</th></tr></thead>
            <tbody>
              {history.map((r) => (
                <tr key={r.id}>
                  <td className="nowrap muted">{fmtTime(r.at)}</td>
                  <td>{ACTION[r.action] ?? r.action}</td>
                  <td><span className={stateClass(String(r.state))}>{String(r.state)}</span></td>
                  <td className="muted">{r.reason ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <Notice kind="info">部署只在本機隔離網路中進行，容器名稱以 <span className="mono">cr-demo-</span> 開頭。</Notice>
      <NextStep prev={{ to: "/iac", label: "IaC 預覽" }} next={{ to: "/report", label: "驗證報告" }} />
    </div>
  );
}

export function DeployPage() {
  const { ir } = useScenario();
  return <ScenarioGate title="部署管理">{ir && <Body key={ir.id} ir={ir} />}</ScenarioGate>;
}
