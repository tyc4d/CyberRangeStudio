import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import type { ScenarioIR } from "@contracts";
import { api, type ApiError } from "../lib/api";
import { useAction, useLoad } from "../lib/hooks";
import { isPlanApproved } from "../lib/plan";
import { useScenario } from "../lib/scenario";
import { ApiNotice, Busy, DataView, Empty, fmtTime, NextStep, Notice, PageHead, ScenarioGate } from "../components/ui";
import { PlacementPanel } from "./PlacementPanel";
import { getLocale, live, t, type MsgKey } from "../i18n";
import type { EnvHost, EnvNetwork } from "@contracts";

const POLL_MS = 5000;

function stateClass(s: string): string {
  const v = s.toLowerCase();
  if (/(fail|error|unhealthy|dead)/.test(v)) return "status-FAIL";
  if (/(running|^up$|healthy|deployed|ready)/.test(v)) return "status-PASS";
  if (/(down|stopped|exited|not_deployed|none|absent)/.test(v)) return "status-NOT_TESTED";
  return "status-PARTIAL";
}

/** The forwarder the platform adds to every deployment that publishes a port. It is not one of the scenario's hosts. */
const GATEWAY = "cr-gateway";

function ContainerTable({ containers, roleOf }: { containers: any[]; roleOf: (svc: string) => string | undefined }) {
  const lab = containers.filter((c) => c?.service !== GATEWAY);
  const gw = containers.filter((c) => c?.service === GATEWAY);
  return (
    <div data-testid="container-table">
      <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>{t("dp.hostsCount", { n: lab.length })}{gw.length > 0 && <> · {t("dp.platformCount", { n: gw.length })}</>}</div>
      <table className="tbl">
        <thead><tr><th>{t("dp.col.kind")}</th><th>{t("dp.col.name")}</th><th>{t("dp.col.state")}</th><th>{t("dp.col.health")}</th></tr></thead>
        <tbody>
          {[...lab, ...gw].map((c, i) => {
            const isGw = c?.service === GATEWAY;
            return (
              <tr key={c?.id ?? i} data-kind={isGw ? "platform" : "lab"}>
                <td>{isGw
                  ? <span className="tag" title={t("dp.platform.hint")}>{t("dp.platform")}</span>
                  : <span className="tag">{t("dp.scenarioHost")}</span>}</td>
                <td>{isGw ? t("dp.gateway") : roleOf(String(c?.service)) ?? String(c?.service ?? "—")}</td>
                <td><span className={stateClass(String(c?.state ?? ""))}>{String(c?.state ?? "—")}</span>{c?.status && <div className="muted" style={{ fontSize: 11 }}>{String(c.status)}</div>}</td>
                <td className="muted">{c?.health ? String(c.health) : t("dp.noHealth")}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
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
    <Notice kind="err" title={t("dp.failed", { what })}>
      <div data-testid="command-failure">
        <div>{cause ?? t("dp.noCause")}{typeof cmd.returncode === "number" && <span className="muted mono">{t("dp.exitCode", { n: cmd.returncode })}</span>}</div>
        <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>{t("dp.failNote")}</div>
        {stderr && <details style={{ marginTop: 6 }}><summary className="muted" style={{ cursor: "pointer" }}>{t("dp.fullOutput")}</summary><pre className="mono" style={{ margin: "6px 0 0", maxHeight: 240, whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{stderr}</pre></details>}
      </div>
    </Notice>
  );
}

/** Why an attempt ended the way it did, from whatever the audit record kept. Tool output is shown as-is, never reworded. */
function recordReason(d: any): string | undefined {
  if (!d || typeof d !== "object") return undefined;
  if (typeof d.reason === "string" && d.reason) return REASON[d.reason] ?? d.reason;
  for (const k of ["error", "stderr"]) {
    const v = typeof d[k] === "string" ? d[k].trim() : "";
    if (v) { const line = v.split("\n").filter(Boolean).pop()!; return REASON[line] ?? line; }
  }
  return typeof d.exit_code === "number" && d.exit_code !== 0 ? t("dp.exit", { n: d.exit_code }) : undefined;
}
/** The command output kept with an attempt, verbatim, for the expandable row detail. */
function recordOutput(d: any): string | undefined {
  if (!d || typeof d !== "object") return undefined;
  const parts = [["stderr", d.stderr], ["stdout", d.stdout]].filter(([, v]) => typeof v === "string" && v.trim()).map(([k, v]) => `[${k}]\n${String(v).trim()}`);
  return parts.length ? parts.join("\n\n") : undefined;
}
const REASON: Record<string, string> = live(() => ({
  "topology not approved": t("dp.r.notApproved"),
  "approval stale; topology changed since approval": t("dp.r.stale"),
  "explicit local PoC approval required": t("dp.r.noConsent"),
  "explicit deployment test approval required": t("dp.r.noConsent"),
  "compose file has not been generated": t("dp.r.noFiles"),
}));

// Known runtime preflight refusals (apps/api/app/deploy/backends/proxmox.py), in plain words for the user.
// Anything else gets a generic line. The raw text stays in the collapsed technical details.
const PVE_REASON: [RegExp, MsgKey][] = [
  [/runtime VM quota is exhausted/, "dp.cap.quota"],
  [/memory budget is exhausted/, "dp.cap.memory"],
  [/insufficient node memory/, "dp.cap.nodeMemory"],
  [/insufficient local-lvm space/, "dp.cap.storage"],
  [/worker template 900000 failed/, "dp.cap.template"],
  [/not the approved 9\.2\.x/, "dp.cap.version"],
  [/outside the approved product VMID range/, "dp.cap.unknownVm"],
  [/active \S+ deployment/, "dp.cap.otherBackend"],
];

// Global capacity refusals: they only gate creating a NEW worker VM. Its own running worker occupies the quota.
const PVE_CAPACITY = /runtime VM quota is exhausted|memory budget is exhausted|insufficient node memory|insufficient local-lvm space/;

/** Reason the loaded Proxmox preflight refuses "up", or undefined when "up" is allowed. */
function pveBlockReason(pf: any): { label: string; raw?: string } | undefined {
  const parts = [pf, pf?.capacity, pf?.isolation].filter((x) => x && typeof x === "object");
  const refused = parts.some((x) => x.ok === false || x.state === "unavailable");
  if (!refused) return undefined;
  const raw = parts.map((x) => x.error ?? x.reason).find((v) => typeof v === "string" && v.trim()) as string | undefined;
  // This scenario already owns a running PVE deployment (current_state comes from its own worker VM). The backend's
  // "up" then returns that deployment without a capacity check, so a global capacity refusal must not block it.
  // Conflicts and other failures (template, version, VMID range, unknown) still block.
  const ownedRunning = pf?.current_state === "running";
  if (ownedRunning && raw && PVE_CAPACITY.test(raw)) {
    return pf?.would_change_running_environment === true
      ? { label: t("dp.cap.changed") }
      : undefined;
  }
  const hit = raw ? PVE_REASON.find(([re]) => re.test(raw)) : undefined;
  return { label: hit ? t(hit[1]) : t("dp.cap.noReason"), raw };
}

function Body({ ir }: { ir: ScenarioIR }) {
  const { reload: reloadIr } = useScenario();
  const status = useLoad(() => api.deployStatus(ir.id), [ir.id]);
  const preflight = useLoad(() => api.deployPreflight(ir.id), [ir.id]);
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

  const after = async () => { await Promise.all([status.reload(true), preflight.reload(true), health.reload(true), records.reload(true)]); void reloadIr(); };
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

  const s = status.data;
  const pf = preflight.data && typeof preflight.data === "object" ? preflight.data : null;
  const backend = s && typeof s === "object" ? s.backend : pf?.backend;
  const isProxmox = backend === "proxmox" || pf?.backend === "proxmox";
  // Proxmox only: a preflight that loaded (no request error) and explicitly reports not-ready. A failed or pending request
  // is NOT a confirmed refusal and must not be shown as one; the backend still re-checks capacity on "up".
  const pveUnavailable = isProxmox && !!pf && !preflight.error ? pveBlockReason(pf) : undefined;
  const upBlock = !approved ? t("dp.block.approve") : iacMissing ? t("dp.block.files") : iacBlocked ? t("dp.block.check")
    : pveUnavailable ? t("dp.block.runtime", { reason: pveUnavailable.label }) : undefined;
  const stateRaw = s && typeof s === "object" ? s.state ?? s.status : typeof s === "string" ? s : undefined;
  const state = typeof stateRaw === "string" ? stateRaw : undefined;
  const containers: unknown = s && typeof s === "object" ? s.containers ?? s.services : undefined;
  const placementActual = s && typeof s === "object" ? s.placement : undefined;
  const placementTarget = preflight.data?.isolation?.placement_target ?? preflight.data?.capacity?.placement_target;
  const rest = s && typeof s === "object" && !Array.isArray(s)
    ? Object.fromEntries(Object.entries(s).filter(([k]) => !["state", "status", "containers", "services", "backend", "placement"].includes(k)))
    : null;
  // The status endpoint answers state=error with this text when no compose file exists. That is "nothing to deploy yet", not a fault.
  const noCompose = (v: any) => !!v && typeof v === "object" && v.error === "compose file has not been generated" && !(Array.isArray(v.containers) && v.containers.length);
  const ACTION: Record<string, string> = { up: t("dp.act.up"), down: t("dp.act.down") };
  const rawRecords: any[] = Array.isArray(records.data?.records) ? records.data.records : [];
  const history = rawRecords.map((r) => ({ id: r.id, action: r.action, state: r.state, at: r.recorded_at, reason: recordReason(r.details), output: recordOutput(r.details) }));
  // Host name for a compose service id, from the approved plan. The gateway is not in the plan: it is platform plumbing.
  const planHosts: EnvHost[] = (ir.environment_plan as any)?.hosts ?? [];
  const planNetworks: EnvNetwork[] = (ir.environment_plan as any)?.networks ?? [];
  const roleOf = (svc: string): string | undefined => planHosts.find((h) => h.id === svc)?.role;
  // Ports of the running deployment: the newest successful "up" in the audit trail (the up response carries the same list).
  const lastUp = rawRecords.find((r) => r.action === "up");
  const published: any[] | null = lastUp && lastUp.state === "running" && Array.isArray(lastUp.details?.published_ports) ? lastUp.details.published_ports : null;
  const boundPorts: string[] = (Array.isArray(containers) ? containers : []).flatMap((c: any) =>
    (Array.isArray(c?.ports) ? c.ports : []).map((p: any) => `${p.host_ip ?? ""}:${p.host_port}`));
  const liveContainers = Array.isArray(containers) ? containers.length : 0;
  // Nothing was ever generated and nothing is running: a down would only fail and add a failed record.
  const downBlock = iacMissing && liveContainers === 0 && state !== "running" ? t("dp.block.down") : undefined;

  return (
    <div className="page">
      <PageHead title={t("dp.title")} desc={t("dp.desc")}>
        <button className="primary" disabled={busy || !!upBlock} title={upBlock} onClick={() => { if (window.confirm(t("dp.confirmUp"))) void up.run(); }}>{t("dp.act.up")}</button>
        <button className="danger" disabled={busy || !!downBlock} title={downBlock} onClick={() => { if (window.confirm(t("dp.confirmDown"))) void down.run(); }}>{t("dp.act.down")}</button>
      </PageHead>

      {!approved && (
        <Notice kind="warn" title={ir.environment_plan ? t("dp.n.notApproved") : t("dp.n.noPlan")}
          action={<Link to="/topology"><button className="primary small">{t("dp.n.toTopology")}</button></Link>}>
          {t("dp.n.approveBody")}
        </Notice>
      )}
      {approved && iacMissing && (
        <Notice kind="warn" title={t("dp.n.noFiles")}
          action={<Link to="/iac"><button className="primary small">{t("dp.n.toFiles")}</button></Link>}>
          {t("dp.n.noFilesBody")}
        </Notice>
      )}
      {approved && iacBlocked && (
        <Notice kind="err" title={t("dp.n.check")}
          action={<Link to="/iac"><button className="small">{t("dp.n.viewReport")}</button></Link>}>
          {t("dp.n.checkBody")}
        </Notice>
      )}
      {isProxmox && pveUnavailable && (
        <Notice kind="err" title={t("dp.n.runtime")} >
          <span data-testid="pve-preflight-block">{pveUnavailable.label}</span>
          <div className="muted" style={{ marginTop: 6 }}>{t("dp.n.runtimeNote")}</div>
          {pveUnavailable.raw && (
            <details className="tech-details"><summary>{t("notice.techDetails")}</summary><div className="mono muted" style={{ overflowWrap: "anywhere" }}>{pveUnavailable.raw}</div></details>
          )}
          <div style={{ marginTop: 8 }}><button className="small" onClick={() => preflight.reload()} disabled={preflight.loading}>{t("dp.n.recheck")}</button></div>
        </Notice>
      )}
      {isProxmox && !pf && preflight.loading && <Notice kind="info">{t("dp.n.checking")}</Notice>}
      {isProxmox && preflight.error && (
        <><ApiNotice error={preflight.error} what={t("dp.n.preflightWhat")} onRetry={() => preflight.reload()} /><div className="muted" style={{ fontSize: 12, marginTop: -8 }}>{t("dp.n.preflightNote")}</div></>
      )}
      {up.busy && <div className="card"><Busy label={t("dp.busyUp")} elapsed={up.elapsed} /></div>}
      {down.busy && <div className="card"><Busy label={t("dp.busyDown")} elapsed={down.elapsed} /></div>}
      <CommandFailure error={up.error} what={t("dp.upWhat")} />
      <CommandFailure error={down.error} what={t("dp.downWhat")} />
      {status.error && <ApiNotice error={status.error} what={t("dp.statusWhat")} onRetry={() => status.reload()} />}

      <PlacementPanel
        hosts={planHosts}
        networks={planNetworks}
        containers={Array.isArray(containers) ? containers : []}
        target={placementTarget}
        actual={placementActual}
        backend={backend}
        state={state}
        statusLoading={status.loading}
        statusError={!!status.error}
      />

      <details className="deploy-more">
        <summary>{t("dp.more")}</summary>
        <div className="deploy-more__content">
      <div className="card flush">
        <div className="card-head">
          <h2>{t("dp.now")}</h2>
          {state && (noCompose(s)
            ? <span className="pill status-NOT_TESTED" data-testid="deploy-state" >{t("dp.notDeployed")}</span>
            : <span className={`pill ${stateClass(state)}`} data-testid="deploy-state">{state}</span>)}
          <div className="right">
            {status.data && lastAt && <span className="muted" style={{ fontSize: 12 }}>{t("dp.updatedAt", { time: lastAt.toLocaleTimeString(getLocale(), { hour12: false }) })}</span>}
            <label className="row muted" style={{ gap: 5, fontSize: 12 }}>
              <input type="checkbox" style={{ width: "auto" }} checked={auto} onChange={(e) => setAuto(e.target.checked)} /> {t("dp.auto")}
            </label>
            <button className="small" onClick={() => status.reload()} disabled={status.loading}>{t("dp.refresh")}</button>
          </div>
        </div>
        <div style={{ padding: 14, display: "flex", flexDirection: "column", gap: 14 }}>
          {status.error && status.data && <div className="muted" style={{ fontSize: 12 }}>{t("dp.stale")}</div>}
          {status.loading && !status.data && !status.error && <Busy label={t("dp.loading")} />}
          {noCompose(s) && <span className="muted" style={{ fontSize: 13 }}>{t("dp.noFilesState")}</span>}
          {status.data !== null && status.data !== undefined && !noCompose(s) && (
            <>
              {containers !== undefined && (
                <div>
                  <h3 style={{ marginBottom: 8 }}>{t("dp.parts")}</h3>
                  {Array.isArray(containers) && containers.length === 0 ? <span className="muted" style={{ fontSize: 13 }}>{t("dp.nothingRunning")}</span>
                    : Array.isArray(containers) ? <ContainerTable containers={containers} roleOf={roleOf} />
                    : <DataView data={containers} />}
                </div>
              )}
              {state === "running" && (
                <div data-testid="published-ports">
                  <h3 style={{ marginBottom: 8 }}>{t("dp.ports")}</h3>
                  {published === null ? (
                    <span className="muted" style={{ fontSize: 13 }}>
                      {t("dp.ports.unknown")}{" "}
                      {boundPorts.length > 0
                        ? <>{t("dp.ports.bound", { list: "" })}<span className="mono">{boundPorts.join(", ")}</span></>
                        : t("dp.ports.noneBound")}
                    </span>
                  )
                    : published.length === 0 ? <span className="muted" style={{ fontSize: 13 }}>{t("dp.ports.none")}</span> : (
                    <>
                      <table className="tbl">
                        <thead><tr><th>{t("dp.ports.from")}</th><th>{t("dp.ports.to")}</th></tr></thead>
                        <tbody>
                          {published.map((p, i) => (
                            <tr key={i}>
                              <td className="mono">{p.host_ip ?? "127.0.0.1"}:{p.host_port ?? "?"}</td>
                              <td>{t("dp.ports.target", { host: roleOf(String(p.host_id)) ?? p.host_id, port: p.container_port })}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>
                        {t("dp.ports.note")} {published.some((p) => p.host_ip && p.host_ip !== "127.0.0.1") ? t("dp.ports.lan") : t("dp.ports.local")}
                      </div>
                    </>
                  )}
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
          <h2>{t("dp.health")}</h2>
          {typeof health.data?.state === "string" && (noCompose(health.data)
            ? <span className="pill status-NOT_TESTED" data-testid="health-state">{t("dp.health.notChecked")}</span>
            : <span className={`pill ${stateClass(health.data.state)}`} data-testid="health-state">{health.data.state}</span>)}
          <div className="right">
            {health.loading && <span className="spinner" />}
            <button className="small" onClick={() => health.reload()} disabled={health.loading}>{t("dp.n.recheck")}</button>
          </div>
        </div>
        <div style={{ padding: 14 }}>
          {health.error ? <ApiNotice error={health.error} what={t("dp.health.what")} onRetry={() => health.reload()} />
            : health.loading && !health.data ? <Busy label={t("dp.health.busy")} />
            : health.data === null || health.data === undefined ? <span className="muted">{t("dp.health.none")}</span>
            : noCompose(health.data) ? <span className="muted" style={{ fontSize: 13 }}>{t("dp.health.notDeployed")}</span>
            : <DataView data={health.data} />}
          {health.data && !noCompose(health.data) && !health.error && (
            <div className="muted" style={{ fontSize: 12, marginTop: 10 }}>
              {t("dp.health.note")}
            </div>
          )}
        </div>
      </div>

      <div className="card flush">
        <div className="card-head"><h2>{t("dp.records")}</h2><span className="muted" style={{ fontSize: 12 }}>{history.length}</span></div>
        {records.error && records.error.kind !== "unimplemented" ? <div style={{ padding: 14 }}><ApiNotice error={records.error} what={t("dp.recordsWhat")} onRetry={() => records.reload()} /></div>
          : history.length === 0 ? <Empty>{t("dp.noRecords")}</Empty> : (
          <table className="tbl" data-testid="deploy-records">
            <thead><tr><th>{t("dp.col.time")}</th><th>{t("dp.col.action")}</th><th>{t("dp.col.result")}</th><th>{t("dp.col.note")}</th></tr></thead>
            <tbody>
              {history.map((r) => (
                <tr key={r.id}>
                  <td className="nowrap muted">{fmtTime(r.at)}</td>
                  <td>{ACTION[r.action] ?? r.action}</td>
                  <td><span className={stateClass(String(r.state))}>{String(r.state)}</span></td>
                  <td className="muted" style={{ overflowWrap: "anywhere" }}>
                    {r.reason ?? "—"}
                    {r.output && (
                      <details style={{ marginTop: 4 }}>
                        <summary style={{ cursor: "pointer", fontSize: 12 }}>{t("dp.output")}</summary>
                        <pre className="mono" style={{ margin: "6px 0 0", maxHeight: 240, whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{r.output}</pre>
                      </details>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
        </div>
      </details>

      <NextStep prev={{ to: "/iac", label: t("stage.iac") }} next={{ to: "/report", label: t("stage.report") }} />
    </div>
  );
}

export function DeployPage() {
  const { ir } = useScenario();
  return <ScenarioGate title={t("dp.title")}>{ir && <Body key={ir.id} ir={ir} />}</ScenarioGate>;
}
