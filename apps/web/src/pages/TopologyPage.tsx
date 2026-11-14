import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import ReactFlow, { Background, Controls, Handle, MarkerType, Position, type Edge, type Node, type NodeProps } from "reactflow";
import "reactflow/dist/style.css";
import type { EnvHost, EnvironmentPlan, EnvNetwork, ScenarioIR } from "@contracts";
import { api } from "../lib/api";
import { useAction } from "../lib/hooks";
import { BARRIER, CANVAS, GRID, LABEL, MEMBER, ROUTE } from "../lib/palette";
import type { PlanX } from "../lib/plan";
import { layeredLayout } from "../lib/layout";
import { useScenario } from "../lib/scenario";
import { ApiNotice, Busy, Empty, fmtTime, NextStep, Notice, PageHead, ScenarioGate } from "../components/ui";

function NetworkNode({ data }: NodeProps<{ net: EnvNetwork }>) {
  const n = data.net;
  return (
    <div className={`gnode net ${n.internal ? "internal" : ""}`}>
      <div className="t" style={{ marginBottom: 2 }}>{n.id}</div>
      <div className="muted">{n.segment ?? "未指定網段"} · {n.internal ? "隔離" : "可對外"}</div>
      <Handle type="source" position={Position.Bottom} id="b" style={{ opacity: 0 }} isConnectable={false} />
    </div>
  );
}
function HostNode({ data }: NodeProps<{ host: EnvHost }>) {
  const h = data.host;
  return (
    <div className="gnode">
      <Handle type="target" position={Position.Top} id="t" style={{ opacity: 0 }} isConnectable={false} />
      <Handle type="target" position={Position.Left} id="l" isConnectable={false} />
      <div className="t">{h.role}</div>
      <div className="mono muted" style={{ marginBottom: 4 }}>{h.id}</div>
      {h.image_hint && <div className="mono muted" style={{ marginBottom: 4, overflowWrap: "anywhere" }}>{h.image_hint}</div>}
      <div className="meta">
        {h.services?.map((s, i) => <span key={i} className="tag" title={s.protocol ?? "tcp"}>{s.name}:{s.port}</span>)}
      </div>
      <Handle type="source" position={Position.Right} id="r" isConnectable={false} />
    </div>
  );
}
const nodeTypes = { network: NetworkNode, host: HostNode };

function buildGraph(plan: PlanX): { nodes: Node[]; edges: Edge[] } {
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
      style: { stroke: ROUTE, strokeWidth: 2 },
      markerEnd: { type: MarkerType.ArrowClosed, color: ROUTE, width: 16, height: 16 },
      labelStyle: { fill: LABEL, fontSize: 10 }, labelBgStyle: { fill: CANVAS },
    });
  });
  // Paths that must stay shut are drawn too, so the picture shows what is refused as well as what is opened.
  (plan.verify_blocked ?? []).forEach((b, i) => {
    if (!hostIds.has(b.from_host) || !hostIds.has(b.to_host)) return;
    edges.push({
      id: `b:${i}`, source: `host:${b.from_host}`, sourceHandle: "r", target: `host:${b.to_host}`, targetHandle: "l",
      label: `✕ 阻擋${b.port ? ` ${b.protocol ?? "tcp"}/${b.port}` : ""}`,
      style: { stroke: BARRIER, strokeWidth: 1.5, strokeDasharray: "3 5" },
      labelStyle: { fill: BARRIER, fontSize: 10, fontWeight: 600 }, labelBgStyle: { fill: CANVAS },
    });
  });
  return { nodes, edges };
}

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
    await reload(); // the endpoint returns the plan, not the IR
    nav("/iac");
  });
  const [ranOk, setRanOk] = useState(false);
  const run = useAction(async () => { setRanOk(false); await absorb(await api.planTopology(ir.id)); setRanOk(true); });
  const graph = useMemo(() => (plan ? buildGraph(plan) : null), [plan]);
  const [stamp, setStamp] = useState(0);
  const hostRole = useMemo(() => new Map((plan?.hosts ?? []).map((h) => [h.id, h.role])), [plan]);
  const name = (id?: string) => (id ? hostRole.get(id) ?? id : "任意");
  const danglingConn = plan ? (plan.connections ?? []).filter((c) => !hostRole.has(c.from_host) || !hostRole.has(c.to_host)).length : 0;

  return (
    <div className="page">
      <PageHead title="拓樸" desc="依攻擊流程與軟體依賴規劃出的環境：有哪些網路、主機放在哪、彼此需要哪些連線。這份規劃是下一步產生 IaC 的輸入。">
        <button className={plan ? "" : "primary"} disabled={run.busy || approve.busy} onClick={() => run.run()}>{plan ? "重新規劃拓樸" : "產生拓樸規劃"}</button>
      </PageHead>

      {run.busy && <div className="card"><Busy label="規劃拓樸中…" elapsed={run.elapsed} /></div>}
      <ApiNotice error={run.error} what="拓樸規劃" />
      {ranOk && !run.busy && (plan
        ? <Notice kind="info">拓樸規劃完成，結果已更新。重新規劃後需要重新核准。</Notice>
        : <Notice kind="warn" title="規劃完成，但沒有結果">後端沒有回傳環境規劃。請確認「軟體依賴」已有主機與服務。</Notice>)}

      {!plan || !graph ? (
        <div className="card"><Empty>這個情境還沒有環境規劃。{!(ir.hosts?.length) && "建議先完成「軟體依賴」，再"}按右上角「產生拓樸規劃」。</Empty></div>
      ) : (
        <>
          <div className="legend">
            <span><span className="line" />主機間連線（箭頭為連線方向）</span>
            <span><span className="line" style={{ borderTop: `2px dashed ${BARRIER}` }} />必須保持阻擋的路徑</span>
            <span><span className="line" style={{ borderTop: `1px solid ${MEMBER}` }} />主機所屬網路</span>
            <span>實線外框網路＝隔離（internal），虛線＝可對外</span>
            <button className="small" style={{ marginLeft: "auto" }} onClick={() => setStamp((s) => s + 1)}>重設版面</button>
          </div>
          <div className="canvas" style={{ height: 520, flex: "none" }}>
            {plan.hosts.length === 0 && plan.networks.length === 0 ? <Empty>環境規劃裡沒有主機或網路。</Empty> : (
              <ReactFlow
                key={`${stamp}:${ir.updated_at ?? ""}:${ir.ir_version ?? ""}`}
                defaultNodes={graph.nodes} defaultEdges={graph.edges} nodeTypes={nodeTypes}
                nodesConnectable={false} deleteKeyCode={null} elementsSelectable
                fitView fitViewOptions={{ padding: 0.2, maxZoom: 1.1 }} minZoom={0.2}
                proOptions={{ hideAttribution: true }}
              >
                <Background color={GRID} gap={20} />
                <Controls showInteractive={false} />
              </ReactFlow>
            )}
          </div>
          {danglingConn > 0 && <div className="status-PARTIAL" style={{ fontSize: 12 }}>有 {danglingConn} 條連線指向規劃中不存在的主機，圖上未畫出，詳見下表。</div>}

          <section className={`gate ${approved ? "approved" : "pending"}`} data-testid="topology-approval" aria-label="拓樸人工核准">
            <div className="gate-head">
              <h2>部署前，由你確認這份拓樸</h2>
              <span className={`pill ${approved ? "status-PASS" : "status-PARTIAL"}`} data-testid="approval-state">{approved ? "已核准" : "尚未核准"}</span>
            </div>
            <div className="gate-cols">
              <div className="gate-col open" data-testid="open-paths">
                <h3>會開通的連線（{plan.connections?.length ?? 0}）</h3>
                {plan.connections?.length ? plan.connections.map((c, i) => (
                  <div className="path" key={i}>
                    <span>{name(c.from_host)}</span>
                    <span className="wire">{c.port ? `${c.protocol ?? "tcp"}/${c.port}` : "任意埠"}</span>
                    <span className="to">{name(c.to_host)}</span>
                    {c.reason && <span className="why">{c.reason}</span>}
                  </div>
                )) : <div className="muted" style={{ fontSize: 13 }}>沒有要開通的主機間連線。</div>}
              </div>
              <div className="gate-col shut" data-testid="blocked-paths">
                <h3>必須保持阻擋的路徑（{blocked.length}）</h3>
                {blocked.length ? blocked.map((b, i) => (
                  <div className="path shut" key={i}>
                    <span>{name(b.from_host)}</span>
                    <span className="wire">{b.port ? `${b.protocol ?? "tcp"}/${b.port}` : "任意埠"}</span>
                    <span className="to">{name(b.to_host)}</span>
                    {b.reason && <span className="why">{b.reason}</span>}
                  </div>
                )) : <div className="muted" style={{ fontSize: 13 }}>規劃沒有列出必須阻擋的路徑。</div>}
                <div className="muted" style={{ fontSize: 12, marginTop: 10 }}>部署後，驗證會逐條探測這些路徑；只要有一條連得上，驗證就判定失敗。</div>
              </div>
            </div>
            <div className="gate-foot">
              {approved ? (
                <>
                  <div style={{ fontSize: 13 }}>
                    由 <span className="mono">{approval?.approved_by ?? "—"}</span> 於 {fmtTime(approval?.approved_at)} 核准
                    {approval?.note ? <>，備註：{approval.note}</> : null}。核准只對目前這組連線有效；重新規劃拓樸後需要重新核准。
                  </div>
                  <div className="row">
                    <Link to="/iac"><button className="small">前往 IaC 預覽</button></Link>
                    <Link to="/deploy"><button className="small">前往部署管理</button></Link>
                  </div>
                </>
              ) : (
                <>
                  <div style={{ fontSize: 13 }}>核准前，部署會被拒絕。請確認左欄的連線都是這個情境需要的，右欄的路徑確實不該連通。</div>
                  <div className="row" style={{ flexWrap: "nowrap" }}>
                    <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="核准備註（選填）" disabled={approve.busy} aria-label="核准備註" style={{ maxWidth: 420 }} />
                    <button className="primary" style={{ flex: "none" }} disabled={approve.busy || run.busy} onClick={() => approve.run()}>
                      {approve.busy ? <><span className="spinner" /> 核准中…</> : "核准並繼續"}
                    </button>
                  </div>
                </>
              )}
              <ApiNotice error={approve.error} what="拓樸核准" />
            </div>
          </section>

          <div className="card flush" style={{ overflowX: "auto" }}>
              <div className="card-head"><h2>存取規則</h2><span className="muted" style={{ fontSize: 12 }}>{plan.access_rules?.length ?? 0}</span></div>
              {plan.access_rules?.length ? (
                <table className="tbl">
                  <thead><tr><th>動作</th><th>從</th><th>到</th><th>埠</th></tr></thead>
                  <tbody>
                    {plan.access_rules.map((r, i) => (
                      <tr key={i}>
                        <td className={r.action === "deny" ? "status-FAIL" : "status-PASS"}>{r.action === "deny" ? "拒絕" : r.action === "allow" ? "允許" : "—"}</td>
                        <td>{name(r.from)}</td><td>{name(r.to)}</td><td className="mono">{r.port ?? "任意"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : <Empty>沒有定義存取規則。</Empty>}
            </div>

          {plan.notes?.length ? (
            <div className="card"><h2>規劃備註</h2><ul style={{ margin: 0, paddingLeft: 18, fontSize: 13 }}>{plan.notes.map((n, i) => <li key={i}>{n}</li>)}</ul></div>
          ) : null}
        </>
      )}

      <NextStep prev={{ to: "/deps", label: "軟體依賴" }} next={{ to: "/iac", label: "IaC 預覽" }} />
    </div>
  );
}

export function TopologyPage() {
  const { ir } = useScenario();
  return <ScenarioGate title="拓樸">{ir && <Body ir={ir} />}</ScenarioGate>;
}
