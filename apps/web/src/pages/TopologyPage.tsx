import { BasisTag, SUBSTITUTE_BASIS, type Versioned } from "../components/VersionBasis";
import { t, useI18n } from "../i18n";
import { RefIssuesNotice } from "../components/RefIssues";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import ReactFlow, { Background, BackgroundVariant, Controls, EdgeLabelRenderer, getBezierPath, Handle, MarkerType, Position, type Edge, type EdgeProps, type Node, type NodeProps } from "reactflow";
import "reactflow/dist/style.css";
import type { EnvHost, EnvironmentPlan, EnvNetwork, ScenarioIR } from "@contracts";
import { api } from "../lib/api";
import { useAction } from "../lib/hooks";
import { BARRIER, CANVAS, EDGE, GRID, MEMBER } from "../lib/palette";
import type { PlanX } from "../lib/plan";
import { layeredLayout } from "../lib/layout";
import { useScenario } from "../lib/scenario";
import { ApiNotice, Busy, Empty, fmtTime, NextStep, Notice, PageHead, ScenarioGate } from "../components/ui";

function NetworkNode({ data }: NodeProps<{ net: EnvNetwork }>) {
  const n = data.net;
  return (
    <div className={`gnode net ${n.internal ? "internal" : ""}`}>
      <div className="t" style={{ marginBottom: 2 }}>{n.id}</div>
      <div className="muted">{n.segment ?? t("tp.noSeg")} · {n.internal ? t("tp.isolated") : t("tp.external")}</div>
      <Handle type="source" position={Position.Bottom} id="b" style={{ opacity: 0 }} isConnectable={false} />
    </div>
  );
}
/** Plan-host fields the backend writes that the shared TS type may not list yet. */
type HostX = EnvHost & { exposure_basis?: string; deployable?: boolean; substitute_for?: string; substitute_basis?: string };

function HostNode({ data }: NodeProps<{ host: EnvHost }>) {
  const h = data.host;
  return (
    <div style={{ position: "relative" }}>
      <Handle type="target" position={Position.Top} id="t" style={{ opacity: 0 }} isConnectable={false} />
      <Handle type="target" position={Position.Left} id="l" isConnectable={false} />
      <article className="gnode host">
      <div className="t">{h.role}</div>
      <div className="mono muted" style={{ marginBottom: 4 }}>{h.id}</div>
      {h.image_hint && <div className="mono muted" style={{ marginBottom: 4, overflowWrap: "anywhere" }}>{h.image_hint}</div>}
      <div className="meta">
        {h.services?.map((s, i) => {
          const sx = s as { stated_port?: number; port_basis?: string };
          const moved = sx.port_basis === "substitute_default" && typeof sx.stated_port === "number";
          return <span key={i} className={`tag ${moved ? "sub" : ""}`} title={moved ? t("tp.portMoved", { stated: sx.stated_port, port: s.port }) : s.protocol ?? "tcp"}>{s.name}:{s.port}{moved && t("tp.portWas", { stated: sx.stated_port })}</span>;
        })}
        {(h as HostX).substitute_for && (
          <span className="tag sub" data-testid="host-substitute" title={t("tp.subTitle", { explain: SUBSTITUTE_BASIS[(h as HostX).substitute_basis ?? ""]?.explain ?? "", orig: (h as HostX).substitute_for })}>
            {t("tp.sub", { orig: (h as HostX).substitute_for })}
          </span>
        )}
        {(h as Versioned).version_basis && <><BasisTag of={h as Versioned} />{(h as Versioned).deployed_version && <span className="mono muted" style={{ fontSize: 11 }}>{(h as Versioned).deployed_version}</span>}</>}
        {(h as HostX).exposure_basis === "inferred_entry_point" && <span className="tag sub" title={t("tp.entry.hint")}>{t("tp.entry")}</span>}
        {(h as HostX).deployable === false && <span className="tag" style={{ color: "var(--err, #ff6b6b)" }} title={t("tp.notDeployable.hint")}>{t("tp.notDeployable")}</span>}
      </div>
      </article>
      <Handle type="source" position={Position.Right} id="r" isConnectable={false} />
    </div>
  );
}
const nodeTypes = { network: NetworkNode, host: HostNode };

function PlannedEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, style, markerEnd, label, data }: EdgeProps<{ draw: boolean }>) {
  const [d, lx, ly] = getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition });
  return (
    <>
      <path id={id} d={d} fill="none" className="react-flow__edge-path" style={style} markerEnd={markerEnd} pathLength={data?.draw ? 1 : undefined} />
      {label && (
        <EdgeLabelRenderer>
          <div className="edge-label" style={{ transform: `translate(-50%, -50%) translate(${lx}px, ${ly}px)` }}>{label}</div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}
const edgeTypes = { planned: PlannedEdge };

function buildGraph(plan: PlanX, drawOnce: boolean): { nodes: Node[]; edges: Edge[] } {
  const nets = plan.networks ?? [];
  const hosts = plan.hosts ?? [];
  // Hosts flow left to right along their paths (opened and blocked alike, so refused paths do not loop backwards); each network sits above the middle of its member hosts.
  const hostPos = layeredLayout(hosts.map((h) => h.id), [...(plan.connections ?? []), ...(plan.verify_blocked ?? [])].map((c) => ({ from: c.from_host, to: c.to_host })), 360, 150);
  const nodes: Node[] = hosts.map((h) => ({ id: `host:${h.id}`, type: "host", data: { host: h }, position: { x: hostPos[h.id].x, y: hostPos[h.id].y + 170 } }));
  const placed = nets
    .map((n) => {
      const xs = hosts.filter((h) => h.networks?.includes(n.id)).map((h) => hostPos[h.id].x);
      return { n, x: xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length + 10 : 0 };
    })
    .sort((a, b) => a.x - b.x);
  placed.forEach((p, i) => { if (i > 0) p.x = Math.max(p.x, placed[i - 1].x + 220); });
  placed.forEach((p) => nodes.push({ id: `net:${p.n.id}`, type: "network", data: { net: p.n }, position: { x: p.x, y: 0 } }));

  const edges: Edge[] = [];
  const netIds = new Set(nets.map((n) => n.id));
  hosts.forEach((h) => h.networks?.forEach((nid) => {
    if (!netIds.has(nid)) return;
    edges.push({
      id: `m:${nid}:${h.id}`, source: `net:${nid}`, sourceHandle: "b", target: `host:${h.id}`, targetHandle: "t",
      type: "straight", style: { stroke: MEMBER, strokeWidth: 1 },
    });
  }));
  const hostIds = new Set(hosts.map((h) => h.id));
  (plan.connections ?? []).forEach((c, i) => {
    if (!hostIds.has(c.from_host) || !hostIds.has(c.to_host)) return;
    edges.push({
      id: `c:${i}`, source: `host:${c.from_host}`, sourceHandle: "r", target: `host:${c.to_host}`, targetHandle: "l",
      label: c.port ? `${c.protocol ?? "tcp"}/${c.port}` : undefined,
      // Drawn once, right after the plan is produced, then static. It shows a planned rule, never traffic.
      type: "planned", data: { draw: drawOnce }, className: drawOnce ? "fresh" : undefined,
      style: { stroke: EDGE, strokeWidth: 1.5 },
      markerEnd: { type: MarkerType.ArrowClosed, color: EDGE, width: 16, height: 16 },
      });
  });
  // Paths that must stay shut are drawn too, so the picture shows what is refused as well as what is opened.
  (plan.verify_blocked ?? []).forEach((b, i) => {
    if (!hostIds.has(b.from_host) || !hostIds.has(b.to_host)) return;
    edges.push({
      id: `b:${i}`, source: `host:${b.from_host}`, sourceHandle: "r", target: `host:${b.to_host}`, targetHandle: "l",
      label: `${t("tp.blocked")}${b.port ? ` ${b.protocol ?? "tcp"}/${b.port}` : ""}`,
      style: { stroke: BARRIER, strokeWidth: 1.5, strokeDasharray: "3 5" },
      labelStyle: { fill: BARRIER, fontSize: 10, fontWeight: 600 }, labelBgStyle: { fill: CANVAS },
    });
  });
  return { nodes, edges };
}

/** Chinese rendering of the planner's known note shapes; the original stays underneath. Unknown notes are shown unchanged. */
const NOTE_RULES: [RegExp, (m: RegExpMatchArray) => string][] = [
  [/^An attacker host was added as a lab scaffold because the IR did not define one\.$/, () => t("tp.n.attacker")],
  [/^No port is known for service (.+) \((.+)\); it remains unreachable by default\.$/, (m) => t("tp.n.noPort", { svc: m[1], host: m[2] })],
  [/^Host (.+) has services from multiple catalogue components; .*$/, (m) => t("tp.n.multi", { host: m[1] })],
  [/^Services without a resolved host association were left out of host service lists: (.+)\.$/, (m) => t("tp.n.unplaced", { list: m[1] })],
  [/^Connection (.+) to (.+) has no known destination port and was not allowed\.$/, (m) => t("tp.n.connNoPort", { from: m[1], to: m[2] })],
  [/^Actions for host (.+) do not identify one of its multiple services; no inbound service port was opened\.$/, (m) => t("tp.n.multiSvc", { host: m[1] })],
  [/^Confirmed dependency (.+) has no uniquely identified destination service port; default deny remains in effect\.$/, (m) => t("tp.n.depNoPort", { dep: m[1] })],
];
NOTE_RULES.push(
  [/^Host (.+) was placed on the external network as the inferred entry point \(basis: (.+)\); the source does not state its network placement\. Confirm or correct it\.$/, (m) => t("tp.n.entry", { host: m[1], basis: m[2] })],
  [/^No target host is stated or inferable as reachable from outside; .*$/, () => t("tp.n.noEntry")],
  [/^Host (.+) needs (.+), which the catalogue cannot deploy \((.+)\)\. It is not replaced by a stand-in\.$/, (m) => t("tp.n.cannotDeploy", { host: m[1], sw: m[2], why: m[3] })],
  [/^Host (.+) needs (.+) as a VM, which is not deployable yet \((.+)\)\.$/, (m) => t("tp.n.vm", { host: m[1], sw: m[2], why: m[3] })],
  [/^Action (.+) is stated to run from (.+) against (.+), but no destination service port is identified; the path stays denied\.$/, (m) => t("tp.n.actionNoPort", { action: m[1], from: m[2], to: m[3] })],
);
const noteText = (n: string): string | null => { for (const [re, f] of NOTE_RULES) { const m = n.match(re); if (m) return f(m); } return null; };

function Body({ ir }: { ir: ScenarioIR }) {
  const { absorb, reload } = useScenario();
  const nav = useNavigate();
  const plan = ir.environment_plan as PlanX | undefined;
  const approval = plan?.approval;
  const approved = approval?.approved === true;
  const blocked = plan?.verify_blocked ?? [];
  const [note, setNote] = useState("");
  const approve = useAction(async () => {
    await api.approveTopology(ir.id, note.trim() || undefined);
    sessionStorage.setItem("cr.justApproved", ir.id);
    await reload(); // the endpoint returns the plan, not the IR
    nav("/iac");
  });
  // The approval answer is acknowledged once, the first time the approved gate is shown after the click.
  const [justApproved] = useState(() => {
    const hit = approved && sessionStorage.getItem("cr.justApproved") === ir.id;
    if (hit) sessionStorage.removeItem("cr.justApproved");
    return hit;
  });
  const [ranOk, setRanOk] = useState(false);
  const run = useAction(async () => { setRanOk(false); await absorb(await api.planTopology(ir.id)); setRanOk(true); });
  const { locale } = useI18n();
  // Edge labels are translated, so the graph is rebuilt when the language changes.
  const graph = useMemo(() => (plan ? buildGraph(plan, ranOk) : null), [plan, ranOk, locale]); // eslint-disable-line react-hooks/exhaustive-deps
  const [stamp, setStamp] = useState(0);
  const hostRole = useMemo(() => new Map((plan?.hosts ?? []).map((h) => [h.id, h.role])), [plan]);
  const name = (id?: string) => (id ? hostRole.get(id) ?? id : t("tp.any"));
  const danglingConn = plan ? (plan.connections ?? []).filter((c) => !hostRole.has(c.from_host) || !hostRole.has(c.to_host)).length : 0;

  return (
    <div className="page">
      <PageHead title={t("tp.title")} desc={t("tp.desc")}>
        <button className={plan ? "" : "primary"} disabled={run.busy || approve.busy} onClick={() => run.run()}>{plan ? t("tp.replan") : t("tp.plan")}</button>
      </PageHead>

      {run.busy && <div className="card"><Busy label={t("tp.busy")} elapsed={run.elapsed} /></div>}
      <ApiNotice error={run.error} what={t("tp.what")} />
      {ranOk && !run.busy && (plan
        ? <Notice kind="info">{t("tp.done")}</Notice>
        : <Notice kind="warn" title={t("tp.empty.title")}>{t("tp.empty.body")}</Notice>)}

      {plan && <RefIssuesNotice ir={ir} context="topology" />}
      {plan && !(plan.connections?.length) && (
        <Notice kind="warn" title={t("tp.noConn.title")}>
          <div>{t("tp.noConn.body")}</div>
          <div>{t("tp.noConn.approve")}</div>
        </Notice>
      )}

      {!plan || !graph ? (
        <div className="card"><Empty>{t("tp.noPlan")}{!(ir.hosts?.length) && ` ${t("tp.noPlanDeps")}`}</Empty></div>
      ) : (
        <>
          <div className="legend">
            <span><span className="line" />{t("tp.lg.conn")}</span>
            <span><span className="line" style={{ borderTop: `2px dashed ${BARRIER}` }} />{t("tp.lg.blocked")}</span>
            <span><span className="line" style={{ borderTop: `1px solid ${MEMBER}` }} />{t("tp.lg.member")}</span>
            <span>{t("tp.lg.border")}</span>
            <button className="small" style={{ marginLeft: "auto" }} onClick={() => setStamp((s) => s + 1)}>{t("tp.resetLayout")}</button>
          </div>
          <div className="canvas card-canvas" style={{ flex: "none" }}>
            {plan.hosts.length === 0 && plan.networks.length === 0 ? <Empty>{t("tp.emptyPlan")}</Empty> : (
              <ReactFlow
                key={`${stamp}:${ir.updated_at ?? ""}:${ir.ir_version ?? ""}`}
                defaultNodes={graph.nodes} defaultEdges={graph.edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes}
                nodesConnectable={false} deleteKeyCode={null} elementsSelectable
                fitView fitViewOptions={{ padding: 0.2, maxZoom: 1.1 }} minZoom={0.2}
                proOptions={{ hideAttribution: true }}
              >
                <Background variant={BackgroundVariant.Lines} color={GRID} gap={32} lineWidth={1} />
                <Controls showInteractive={false} />
              </ReactFlow>
            )}
          </div>
          {danglingConn > 0 && <div className="status-PARTIAL" style={{ fontSize: 12 }}>{t("tp.dangling", { n: danglingConn })}</div>}

          <section className={`gate ${approved ? "approved" : "pending"} ${justApproved ? "just-approved" : ""}`} data-testid="topology-approval" aria-label={t("tp.gate.aria")}>
            <div className="gate-head">
              <h2>{t("tp.gate.title")}</h2>
              <span className={`badge ${approved ? "approved" : "pending"}`} data-testid="approval-state">{approved ? t("tp.approved") : t("tp.notApproved")}</span>
            </div>
            <div className="gate-cols">
              <div className="gate-col open" data-testid="open-paths">
                <h3>{t("tp.open", { n: plan.connections?.length ?? 0 })}</h3>
                {plan.connections?.length ? plan.connections.map((c, i) => (
                  <div className="path" key={i}>
                    <span>{name(c.from_host)}</span>
                    <span className="wire">{c.port ? `${c.protocol ?? "tcp"}/${c.port}` : t("tp.anyPort")}</span>
                    <span className="to">{name(c.to_host)}</span>
                    {c.reason && <span className="why">{c.reason}</span>}
                  </div>
                )) : <div className="muted" style={{ fontSize: 13 }}>{t("tp.noOpen")}</div>}
              </div>
              <div className="gate-col shut" data-testid="blocked-paths">
                <h3>{t("tp.shut", { n: blocked.length })}</h3>
                {blocked.length ? blocked.map((b, i) => (
                  <div className="path shut" key={i}>
                    <span>{name(b.from_host)}</span>
                    <span className="wire">{b.port ? `${b.protocol ?? "tcp"}/${b.port}` : t("tp.anyPort")}</span>
                    <span className="to">{name(b.to_host)}</span>
                    {b.reason && <span className="why">{b.reason}</span>}
                  </div>
                )) : <div className="muted" style={{ fontSize: 13 }}>{t("tp.noShut")}</div>}
                <div className="muted" style={{ fontSize: 12, marginTop: 10 }}>{t("tp.shutNote")}</div>
              </div>
            </div>
            <div className="gate-foot">
              {approved ? (
                <>
                  <div style={{ fontSize: 13 }}>
                    {t("tp.approvedBy", { who: approval?.approved_by ?? "—", when: fmtTime(approval?.approved_at) })}
                    {approval?.note ? <> {t("tp.approvedNote", { note: approval.note })}</> : null} {t("tp.approvedScope")}
                  </div>
                  <div className="row">
                    <Link to="/iac"><button className="small">{t("tp.toIac")}</button></Link>
                    <Link to="/deploy"><button className="small">{t("tp.toDeploy")}</button></Link>
                  </div>
                </>
              ) : (
                <>
                  <div style={{ fontSize: 13 }}>{t("tp.beforeApprove")}</div>
                  <div className="row approve-row">
                    <input value={note} onChange={(e) => setNote(e.target.value)} placeholder={t("tp.notePh")} disabled={approve.busy} aria-label={t("tp.note")} style={{ maxWidth: 420 }} />
                    <button className="primary" style={{ flex: "none" }} disabled={approve.busy || run.busy} onClick={() => approve.run()}>
                      {approve.busy ? <><span className="spinner" /> {t("tp.approving")}</> : t("tp.approve")}
                    </button>
                  </div>
                </>
              )}
              <ApiNotice error={approve.error} what={t("tp.approveWhat")} />
            </div>
          </section>

          <details className="card flush deploy-more" style={{ overflowX: "auto" }}>
              <summary>{t("tp.rules")} <span className="muted" style={{ fontSize: 12 }}>{plan.access_rules?.length ?? 0}</span></summary>
              {plan.access_rules?.length ? (
                <table className="tbl">
                  <thead><tr><th>{t("tp.col.action")}</th><th>{t("tp.col.from")}</th><th>{t("tp.col.to")}</th><th>{t("tp.col.port")}</th></tr></thead>
                  <tbody>
                    {plan.access_rules.map((r, i) => (
                      <tr key={i}>
                        <td className={r.action === "deny" ? "status-FAIL" : "status-PASS"}>{r.action === "deny" ? t("tp.deny") : r.action === "allow" ? t("tp.allow") : "—"}</td>
                        <td>{name(r.from)}</td><td>{name(r.to)}</td><td className="mono">{r.port ?? t("tp.any")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : <Empty>{t("tp.noRules")}</Empty>}
            </details>

          {plan.notes?.length ? (
            <details className="card deploy-more" open={!(plan.connections?.length)}>
              <summary>{t("tp.notes")} <span className="muted" style={{ fontSize: 12 }}>{plan.notes.length}</span></summary>
              {/* Known planner notes are shown in the UI language. An unknown note is kept as the planner wrote it, because it may explain a closed path. */}
              <ul style={{ margin: 0, paddingLeft: 18, fontSize: 14 }}>{plan.notes.map((n, i) => <li key={i} lang={noteText(n) ? undefined : "en"}>{noteText(n) ?? n}</li>)}</ul>
            </details>
          ) : null}
        </>
      )}

      <NextStep prev={{ to: "/deps", label: t("stage.deps") }} next={{ to: "/iac", label: t("stage.iac") }} />
    </div>
  );
}

export function TopologyPage() {
  const { ir } = useScenario();
  return <ScenarioGate title={t("tp.title")}>{ir && <Body ir={ir} />}</ScenarioGate>;
}
