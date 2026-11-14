import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import type { ScenarioIR } from "@contracts";
import { api, type ApiError } from "../lib/api";
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

/** A failed up/down returns the whole command result (stdout, stderr, audit record, live state), with the same stderr several times over.
 *  Show the cause once, keep the rest folded, so the current status below stays in view. Other errors use the generic notice. */
function CommandFailure({ error, what }: { error: ApiError | null; what: string }) {
  const d = error?.data as any;
  const cmd = d && typeof d === "object" && !Array.isArray(d) ? d.command_result ?? (typeof d.returncode === "number" ? d : null) : null;
  if (!error || !cmd) return <ApiNotice error={error} what={what} />;
  const stderr = String(cmd.stderr ?? d.error ?? "").trim();
  const cause = recordReason({ stderr, exit_code: cmd.returncode });
  return (
    <Notice kind="err" title={`${what}失敗`}>
      <div data-testid="command-failure">
        <div>{cause ?? "指令失敗，沒有回報原因。"}{typeof cmd.returncode === "number" && <span className="muted mono">（結束代碼 {cmd.returncode}）</span>}</div>
        <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>這次嘗試已記入下方「部署紀錄」。實際的容器狀態以「目前狀態」為準，失敗不代表沒有殘留的容器。</div>
        {stderr && <details style={{ marginTop: 6 }}><summary className="muted" style={{ cursor: "pointer" }}>完整錯誤輸出</summary><pre className="mono" style={{ margin: "6px 0 0", maxHeight: 240, whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{stderr}</pre></details>}
      </div>
    </Notice>
  );
}

/** Why an attempt ended the way it did, from whatever the audit record kept. Tool output is shown as-is, never reworded. */
function recordReason(d: any): string | undefined {
  if (!d || typeof d !== "object") return undefined;
  if (typeof d.reason === "string" && d.reason) return REASON_ZH[d.reason] ?? d.reason;
  for (const k of ["error", "stderr"]) {
    const v = typeof d[k] === "string" ? d[k].trim() : "";
    if (v) { const line = v.split("\n").filter(Boolean).pop()!; return REASON_ZH[line] ?? line; }
  }
  return typeof d.exit_code === "number" && d.exit_code !== 0 ? `結束代碼 ${d.exit_code}` : undefined;
}
const REASON_ZH: Record<string, string> = {
  "topology not approved": "拓樸尚未核准",
  "approval stale; topology changed since approval": "核准後拓樸已變更，需重新核准",
  "explicit local PoC approval required": "未取得本機執行的明確同意",
  "compose file has not been generated": "尚未生成 IaC（沒有 compose 檔）",
};

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
  // Deploying needs a generated compose file. 404 with its own detail = not generated yet (same reading as the IaC page).
  const iac = useLoad(() => api.getIac(ir.id), [ir.id]);
  const iacMissing = !!iac.error && iac.error.status === 404 && iac.error.kind === "error";
  // 409 = the stored plan no longer passes the IaC checks (the API answers with the failing report).
  const iacBlocked = iac.data?.report?.deployable === false || iac.error?.status === 409;
  const upBlock = !approved ? "需先在「拓樸」頁核准拓樸" : iacMissing ? "需先在「IaC 預覽」頁生成 IaC" : iacBlocked ? "IaC 檢查報告判定目前不可部署" : undefined;

  const s = status.data;
  const stateRaw = s && typeof s === "object" ? s.state ?? s.status : typeof s === "string" ? s : undefined;
  const state = typeof stateRaw === "string" ? stateRaw : undefined;
  const containers: unknown = s && typeof s === "object" ? s.containers ?? s.services : undefined;
  const rest = s && typeof s === "object" && !Array.isArray(s)
    ? Object.fromEntries(Object.entries(s).filter(([k]) => !["state", "status", "containers", "services"].includes(k)))
    : null;
  // The status endpoint answers state=error with this text when no compose file exists. That is "nothing to deploy yet", not a fault.
  const noCompose = (v: any) => !!v && typeof v === "object" && v.error === "compose file has not been generated" && !(Array.isArray(v.containers) && v.containers.length);
  const ACTION: Record<string, string> = { up: "啟動", down: "關閉" };
  const rawRecords: any[] = Array.isArray(records.data?.records) ? records.data.records : [];
  const history = rawRecords.map((r) => ({ id: r.id, action: r.action, state: r.state, at: r.recorded_at, reason: recordReason(r.details) }));
  const liveContainers = Array.isArray(containers) ? containers.length : 0;
  // Nothing was ever generated and nothing is running: a down would only fail and add a failed record.
  const downBlock = iacMissing && liveContainers === 0 && state !== "running" ? "沒有已生成的部署設定，也沒有容器在執行，無需關閉" : undefined;

  return (
    <div className="page">
      <PageHead title="部署管理" desc="在本機隔離環境啟動或關閉這個情境。狀態每 5 秒自動更新。">
        <button className="primary" disabled={busy || !!upBlock} title={upBlock} onClick={() => { if (window.confirm("確定要在本機隔離環境啟動這個情境的容器？")) void up.run(); }}>啟動（up）</button>
        <button className="danger" disabled={busy || !!downBlock} title={downBlock} onClick={() => { if (window.confirm("確定要關閉並移除這個情境的部署？")) void down.run(); }}>關閉（down）</button>
      </PageHead>

      {!approved && (
        <Notice kind="warn" title={ir.environment_plan ? "拓樸尚未核准，不能部署" : "尚無拓樸規劃，不能部署"}
          action={<Link to="/topology"><button className="primary small">前往拓樸頁</button></Link>}>
          部署前必須先由人核准拓樸（開通哪些連線、哪些路徑必須阻擋）。核准後「啟動」按鈕才會啟用。
        </Notice>
      )}
      {approved && iacMissing && (
        <Notice kind="warn" title="尚未生成 IaC，不能部署"
          action={<Link to="/iac"><button className="primary small">前往 IaC 預覽</button></Link>}>
          拓樸已核准，但還沒有生成部署用的 Docker Compose 設定。請先到「IaC 預覽」頁按「生成 IaC」，生成後「啟動」按鈕才會啟用。
        </Notice>
      )}
      {approved && iacBlocked && (
        <Notice kind="err" title="IaC 檢查判定目前不可部署"
          action={<Link to="/iac"><button className="small">查看 IaC 報告</button></Link>}>
          已生成的設定沒有通過可部署檢查，因此「啟動」停用。請依「IaC 預覽」頁的報告修正後重新生成。
        </Notice>
      )}
      {up.busy && <div className="card"><Busy label="啟動中，正在建立網路與容器…" elapsed={up.elapsed} /></div>}
      {down.busy && <div className="card"><Busy label="關閉中，正在移除容器…" elapsed={down.elapsed} /></div>}
      <CommandFailure error={up.error} what="啟動部署" />
      <CommandFailure error={down.error} what="關閉部署" />

      <div className="card flush">
        <div className="card-head">
          <h2>目前狀態</h2>
          {state && (noCompose(s)
            ? <span className="pill status-NOT_TESTED" data-testid="deploy-state" title="後端狀態：error（compose file has not been generated）">未部署（尚未生成 IaC）</span>
            : <span className={`pill ${stateClass(state)}`} data-testid="deploy-state">{state}</span>)}
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
          {noCompose(s) && <span className="muted" style={{ fontSize: 13 }}>這個情境還沒有生成部署設定（IaC），所以沒有任何容器，也沒有可查詢的部署。</span>}
          {status.data !== null && status.data !== undefined && !noCompose(s) && (
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
          {typeof health.data?.state === "string" && (noCompose(health.data)
            ? <span className="pill status-NOT_TESTED" data-testid="health-state">未檢查（未部署）</span>
            : <span className={`pill ${stateClass(health.data.state)}`} data-testid="health-state">{health.data.state}</span>)}
          <div className="right">
            {health.loading && <span className="spinner" />}
            <button className="small" onClick={() => health.reload()} disabled={health.loading}>重新檢查</button>
          </div>
        </div>
        <div style={{ padding: 14 }}>
          {health.error ? <ApiNotice error={health.error} what="健康檢查" onRetry={() => health.reload()} />
            : health.loading && !health.data ? <Busy label="檢查中…" />
            : health.data === null || health.data === undefined ? <span className="muted">沒有健康檢查結果。</span>
            : noCompose(health.data) ? <span className="muted" style={{ fontSize: 13 }}>尚未部署，沒有可檢查的容器。這不是健康，也不是故障。</span>
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
                  <td className="muted" style={{ overflowWrap: "anywhere" }}>{r.reason ?? "—"}</td>
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
