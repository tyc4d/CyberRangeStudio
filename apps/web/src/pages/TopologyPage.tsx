import { useMemo, useState } from "react";
import ReactFlow, { Background, Controls, Handle, MarkerType, Position, type Edge, type Node, type NodeProps } from "reactflow";
import "reactflow/dist/style.css";
import type { EnvHost, EnvironmentPlan, EnvNetwork, ScenarioIR } from "@contracts";
import { api } from "../lib/api";
import { useAction } from "../lib/hooks";
import { layeredLayout } from "../lib/layout";
import { useScenario } from "../lib/scenario";
import { ApiNotice, Busy, Empty, NextStep, Notice, PageHead, ScenarioGate } from "../components/ui";

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

function buildGraph(plan: EnvironmentPlan): { nodes: Node[]; edges: Edge[] } {
  const nets = plan.networks ?? [];
  const hosts = plan.hosts ?? [];
  // Hosts flow left to right along their connections; each network sits above the middle of its member hosts.
  const hostPos = layeredLayout(hosts.map((h) => h.id), (plan.connections ?? []).map((c) => ({ from: c.from_host, to: c.to_host })), 290, 150);
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
      type: "straight", style: { stroke: "#3a4760", strokeWidth: 1 },
    });
  }));
  const hostIds = new Set(hosts.map((h) => h.id));
  (plan.connections ?? []).forEach((c, i) => {
    if (!hostIds.has(c.from_host) || !hostIds.has(c.to_host)) return;
    edges.push({
      id: `c:${i}`, source: `host:${c.from_host}`, sourceHandle: "r", target: `host:${c.to_host}`, targetHandle: "l",
      label: c.port ? `${c.protocol ?? "tcp"}/${c.port}` : undefined,
      style: { stroke: "#4c9aff", strokeWidth: 1.75 },
      markerEnd: { type: MarkerType.ArrowClosed, color: "#4c9aff", width: 16, height: 16 },
      labelStyle: { fill: "#9aa7b8", fontSize: 10 }, labelBgStyle: { fill: "#0b0e14" },
    });
  });
  return { nodes, edges };
}

function Body({ ir }: { ir: ScenarioIR }) {
  const { absorb } = useScenario();
  const plan = ir.environment_plan;
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
        <button className={plan ? "" : "primary"} disabled={run.busy} onClick={() => run.run()}>{plan ? "重新規劃拓樸" : "產生拓樸規劃"}</button>
      </PageHead>

      {run.busy && <div className="card"><Busy label="規劃拓樸中…" elapsed={run.elapsed} /></div>}
      <ApiNotice error={run.error} what="拓樸規劃" />
      {ranOk && !run.busy && (plan
        ? <Notice kind="info">拓樸規劃完成，結果已更新。</Notice>
        : <Notice kind="warn" title="規劃完成，但沒有結果">後端沒有回傳環境規劃。請確認「軟體依賴」已有主機與服務。</Notice>)}

      {!plan || !graph ? (
        <div className="card"><Empty>這個情境還沒有環境規劃。{!(ir.hosts?.length) && "建議先完成「軟體依賴」，再"}按右上角「產生拓樸規劃」。</Empty></div>
      ) : (
        <>
          <div className="legend">
            <span><span className="line" />主機間連線（箭頭為連線方向）</span>
            <span><span className="line" style={{ borderTop: "1px solid #3a4760" }} />主機所屬網路</span>
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
                <Background color="#1c2534" gap={20} />
                <Controls showInteractive={false} />
              </ReactFlow>
            )}
          </div>
          {danglingConn > 0 && <div className="status-PARTIAL" style={{ fontSize: 12 }}>有 {danglingConn} 條連線指向規劃中不存在的主機，圖上未畫出，詳見下表。</div>}

          <div className="grid c2" style={{ alignItems: "start" }}>
            <div className="card flush" style={{ overflowX: "auto" }}>
              <div className="card-head"><h2>連線</h2><span className="muted" style={{ fontSize: 12 }}>{plan.connections?.length ?? 0}</span></div>
              {plan.connections?.length ? (
                <table className="tbl">
                  <thead><tr><th>從</th><th>到</th><th>埠</th><th>用途</th></tr></thead>
                  <tbody>
                    {plan.connections.map((c, i) => (
                      <tr key={i}><td>{name(c.from_host)}</td><td>{name(c.to_host)}</td>
                        <td className="mono">{c.port ? `${c.protocol ?? "tcp"}/${c.port}` : "—"}</td><td className="muted">{c.reason ?? "—"}</td></tr>
                    ))}
                  </tbody>
                </table>
              ) : <Empty>沒有定義主機間連線。</Empty>}
            </div>
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
