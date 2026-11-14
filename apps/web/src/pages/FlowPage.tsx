import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactFlow, {
  Background, BackgroundVariant, Controls, EdgeLabelRenderer, getBezierPath, Handle, MarkerType, MiniMap, NodeToolbar, Position, useEdgesState, useNodesState,
  type Connection, type Edge, type EdgeProps, type Node, type NodeProps,
} from "reactflow";
import "reactflow/dist/style.css";
import type { Action, EpistemicStatus, Relation, RelationKind, ScenarioIR } from "@contracts";
import { api } from "../lib/api";
import { useAction, useLoad } from "../lib/hooks";
import { layeredLayout, loadPositions, savePositions } from "../lib/layout";
import { lintFlow, type Finding } from "../lib/flowlint";
import { EDGE, GRID, TEMPORAL } from "../lib/palette";
import type { RelationX } from "../lib/plan";
import { useScenario } from "../lib/scenario";
import {
  ApiNotice, EPISTEMIC, EPISTEMIC_ORDER, fmtTime, ScenarioGate, SourceTag,
} from "../components/ui";
import { isPlanApproved } from "../lib/plan";
import { TopbarActions } from "../lib/topbar";
import { Link } from "react-router-dom";
import {
  ArrowRight, Check, ChevronUp, Copy, Crosshair, Database, DoorOpen, GitBranch, KeyRound, Layers, LayoutGrid, Network, Plus, Radar,
  Save, ScanLine, Search, Server, TerminalSquare, Trash2, X,
} from "lucide-react";

const KIND_LABEL: Record<RelationKind, string> = { temporal: "時間先後", dependency: "依賴" };

interface ActionNodeData {
  action: Action; index: number; fresh: boolean; host?: string; requires: number; issues: number;
  onDuplicate: () => void; onDelete: () => void; onCheck: () => void;
}

// A pictogram per ATT&CK tactic; unknown tactics fall back to a neutral crosshair.
function tacticIcon(tactic?: string) {
  const t = (tactic ?? "").toLowerCase();
  if (/recon/.test(t)) return Radar;
  if (/initial/.test(t)) return DoorOpen;
  if (/discover/.test(t)) return Search;
  if (/collect|exfil/.test(t)) return Database;
  if (/credential/.test(t)) return KeyRound;
  if (/lateral/.test(t)) return Network;
  if (/execut|persist|privilege/.test(t)) return TerminalSquare;
  return Crosshair;
}

function ActionNode({ data, selected }: NodeProps<ActionNodeData>) {
  const a = data.action;
  const Icon = tacticIcon(a.attack_tactic ?? a.name);
  return (
    <>
      <NodeToolbar isVisible={selected} position={Position.Top} offset={12}>
        <div className="node-toolbar nodrag nopan" onClick={(e) => e.stopPropagation()}>
          <button aria-label="複製這個行為" title="複製（不含連線）" onClick={data.onDuplicate}><Copy size={15} /></button>
          <button aria-label="刪除這個行為" title="刪除（連同相關連線）" onClick={data.onDelete}><Trash2 size={15} /></button>
          <button aria-label="查看這個行為的設計檢查" title="設計檢查" onClick={data.onCheck}><ScanLine size={15} /></button>
        </div>
      </NodeToolbar>
      {/* Handles sit outside the article so its clipped corner does not cut them; only the article ever animates. */}
      <Handle type="target" position={Position.Left} />
      <article className={`gnode ${data.fresh ? "fresh" : ""} ${data.issues ? "has-issues" : ""}`}>
        <div className="node-top">
          <span className="step-icon"><Icon size={17} /></span>
          <span className="node-number">STEP {String(data.index + 1).padStart(2, "0")}</span>
          {a.attack_technique && <span className="badge technique">{a.attack_technique}</span>}
        </div>
        <strong>{a.name || "（未命名）"}</strong>
        <div className="node-target"><ArrowRight size={13} /><span>{data.host ?? "未指定目標主機"}</span></div>
        <div className="node-bottom">
          <span><GitBranch size={12} />{data.requires ? `${data.requires} 項前置` : "起點"}</span>
          {/* What the report supports, or a design problem — never a run result. */}
          <span className={data.issues ? "issue-text" : ""}>{data.issues ? `${data.issues} 個問題` : EPISTEMIC[a.epistemic_status]?.label ?? a.epistemic_status}{a.source === "user" ? "・已編輯" : ""}</span>
        </div>
      </article>
      <Handle type="source" position={Position.Right} />
    </>
  );
}
const nodeTypes = { action: ActionNode };

interface RelEdgeData { label: string; tone: "route" | "hold" | "temporal"; draw: boolean }

/** A relation line. A new dependency is drawn once (pathLength=1 + dashoffset) and is static from then on;
 *  nothing here ever loops, so a line can never read as traffic or as an attack in progress. */
function RelEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, style, markerEnd, data }: EdgeProps<RelEdgeData>) {
  const [d, lx, ly] = getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition });
  return (
    <>
      <path id={id} d={d} fill="none" className="react-flow__edge-path" style={style} markerEnd={markerEnd} pathLength={data?.draw ? 1 : undefined} />
      <path d={d} fill="none" strokeOpacity={0} strokeWidth={22} className="react-flow__edge-interaction" />
      {data?.label && (
        <EdgeLabelRenderer>
          <div className={`edge-label ${data.tone}`} style={{ transform: `translate(-50%, -50%) translate(${lx}px, ${ly}px)` }}>{data.label}</div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}
const edgeTypes = { rel: RelEdge };

function toEdge(r: Relation, selected: boolean, fresh: boolean): Edge<RelEdgeData> {
  const dep = r.kind === "dependency";
  const confirmed = dep && (r as RelationX).confirmed === true;
  const color = dep ? EDGE : TEMPORAL;
  return {
    id: r.id, type: "rel", source: r.from_action, target: r.to_action, selected,
    // Dashed temporal lines cannot use the dash-offset draw, so a new one simply fades in.
    className: fresh ? (dep ? "fresh" : "fresh-fade") : undefined,
    data: {
      // Temporal lines carry no label: the dashed stroke already says "order only" (see legend).
      label: dep ? (confirmed ? "依賴" : "依賴 · 未確認") : "",
      tone: dep ? (confirmed ? "route" : "hold") : "temporal",
      draw: fresh && dep,
    },
    style: { stroke: color, strokeWidth: 1.5, strokeDasharray: dep ? undefined : "5 5", opacity: dep && !confirmed ? 0.55 : 1 },
    markerEnd: { type: dep ? MarkerType.ArrowClosed : MarkerType.Arrow, color, width: 18, height: 18 },
  };
}

const COL_W = 310;
/** Left-to-right by dependency/order depth, with alternate columns dropped half a row: neighbours never sit on the
 *  same line, which leaves room for the relation label between them and keeps long chains legible without zooming out. */
function flowLayout(actions: Action[], relations: Relation[]) {
  const pos = layeredLayout(actions.map((a) => a.id), relations.map((r) => ({ from: r.from_action, to: r.to_action })), COL_W, 208);
  for (const p of Object.values(pos)) if (Math.round(p.x / COL_W) % 2 === 1) p.y += 66;
  return pos;
}

let seq = 0;
const newId = (prefix: string, taken: Set<string>) => {
  let id: string;
  do { id = `${prefix}_u${Date.now().toString(36)}${(seq++).toString(36)}`; } while (taken.has(id));
  return id;
};

type Sel = { type: "action" | "relation"; id: string } | null;

function Editor({ ir }: { ir: ScenarioIR }) {
  const { absorb } = useScenario();
  const [actions, setActions] = useState<Action[]>(ir.actions);
  const [relations, setRelations] = useState<Relation[]>(ir.relations);
  const [dirty, setDirty] = useState(false);
  const [sel, setSel] = useState<Sel>(null);
  const [newKind, setNewKind] = useState<RelationKind>("temporal");
  const [note, setNote] = useState("");
  const [hint, setHint] = useState<string | null>(null);
  const [savedMsg, setSavedMsg] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);
  const inspectorRef = useRef<HTMLDivElement>(null);
  useEffect(() => { inspectorRef.current?.scrollTo({ top: 0 }); }, [sel?.type, sel?.id]);
  const posKey = `cr.flowpos.${ir.id}`;
  const stored = useRef(loadPositions(posKey));

  const [nodes, setNodes, onNodesChange] = useNodesState<ActionNodeData>([]);
  // Objects created in this editing session: only these get an entrance, so loading a scenario never animates.
  const fresh = useRef(new Set<string>());
  const [consoleOpen, setConsoleOpen] = useState(false);
  const hostRole = useMemo(() => new Map((ir.hosts ?? []).map((h) => [h.id, h.role])), [ir.hosts]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const findings = useMemo(() => lintFlow(actions, relations), [actions, relations]);

  // Adopt a new IR from the server (after save / reload) only when there are no local edits to lose.
  const irStamp = `${ir.id}:${ir.ir_version}:${ir.updated_at}`;
  const lastStamp = useRef(irStamp);
  useEffect(() => {
    if (lastStamp.current === irStamp) return;
    lastStamp.current = irStamp;
    if (!dirty) { setActions(ir.actions); setRelations(ir.relations); }
  }, [irStamp]); // eslint-disable-line

  useEffect(() => {
    setNodes((prev) => {
      const prevPos = new Map(prev.map((n) => [n.id, n.position]));
      const auto = flowLayout(actions, relations);
      return actions.map((a, index): Node<ActionNodeData> => ({
        id: a.id, type: "action",
        data: {
          action: a, index, fresh: fresh.current.has(a.id),
          host: a.target_host_ref ? hostRole.get(a.target_host_ref) ?? a.target_host_ref : undefined,
          requires: relations.filter((r) => r.kind === "dependency" && r.to_action === a.id).length,
          issues: findings.filter((f) => f.level === "error" && f.target?.type === "action" && f.target.id === a.id).length,
          onDuplicate: () => duplicateAction(a.id), onDelete: () => removeActions([a.id]), onCheck: () => setConsoleOpen(true),
        },
        position: prevPos.get(a.id) ?? stored.current[a.id] ?? auto[a.id] ?? { x: 0, y: 0 },
        selected: sel?.type === "action" && sel.id === a.id,
      }));
    });
  }, [actions, relations, sel, hostRole, findings]); // eslint-disable-line
  useEffect(() => {
    setEdges(relations.map((r) => toEdge(r, sel?.type === "relation" && sel.id === r.id, fresh.current.has(r.id))));
  }, [relations, sel]); // eslint-disable-line

  const touch = () => { setDirty(true); setSavedMsg(null); };
  const patchAction = (id: string, p: Partial<Action>) => {
    setActions((xs) => xs.map((a) => (a.id === id ? { ...a, ...p, source: "user" } : a)));
    touch();
  };
  const patchRelation = (id: string, p: Partial<Relation>) => {
    setRelations((xs) => xs.map((r) => (r.id === id ? { ...r, ...p, source: "user" } : r)));
    touch();
  };
  const removeActions = (ids: string[]) => {
    const gone = new Set(ids);
    setActions((xs) => xs.filter((a) => !gone.has(a.id)));
    setRelations((xs) => xs.filter((r) => !gone.has(r.from_action) && !gone.has(r.to_action)));
    setSel((s) => (s && s.type === "action" && gone.has(s.id) ? null : s));
    touch();
  };
  const removeRelations = (ids: string[]) => {
    const gone = new Set(ids);
    setRelations((xs) => xs.filter((r) => !gone.has(r.id)));
    setSel((s) => (s && s.type === "relation" && gone.has(s.id) ? null : s));
    touch();
  };
  const addAction = () => {
    const id = newId("act", new Set(actions.map((a) => a.id)));
    const maxY = nodes.reduce((m, n) => Math.max(m, n.position.y), -120);
    stored.current[id] = { x: 0, y: maxY + 150 };
    fresh.current.add(id);
    setActions((xs) => [...xs, { id, name: "新攻擊行為", epistemic_status: "inferred", source: "user", evidence_refs: [] }]);
    setSel({ type: "action", id });
    touch();
  };
  // A copy keeps the step's own fields but none of its relations: dependencies are decided per step, not inherited.
  const duplicateAction = (srcId: string) => {
    const src = actions.find((a) => a.id === srcId);
    if (!src) return;
    const id = newId("act", new Set(actions.map((a) => a.id)));
    const at = nodes.find((n) => n.id === srcId)?.position ?? { x: 0, y: 0 };
    stored.current[id] = { x: at.x + 40, y: at.y + 150 };
    fresh.current.add(id);
    setActions((xs) => [...xs, { ...src, id, name: `${src.name}（複製）`, source: "user" }]);
    setSel({ type: "action", id });
    touch();
  };
  const onConnect = useCallback((c: Connection) => {
    if (!c.source || !c.target) return;
    if (c.source === c.target) { setHint("行為不能連到自己。"); return; }
    if (relations.some((r) => r.from_action === c.source && r.to_action === c.target && r.kind === newKind)) {
      setHint(`這兩個行為之間已經有「${KIND_LABEL[newKind]}」關係。`);
      return;
    }
    setHint(null);
    const id = newId("rel", new Set(relations.map((r) => r.id)));
    fresh.current.add(id);
    setRelations((xs) => [...xs, { id, from_action: c.source!, to_action: c.target!, kind: newKind, epistemic_status: "inferred", source: "user", evidence_refs: [] }]);
    setSel({ type: "relation", id });
    touch();
  }, [relations, newKind]);

  const persistPositions = () => {
    const pos = Object.fromEntries(nodes.map((n) => [n.id, n.position]));
    stored.current = pos;
    savePositions(posKey, pos);
  };
  const autoLayout = () => {
    const auto = flowLayout(actions, relations);
    stored.current = auto;
    savePositions(posKey, auto);
    setNodes((ns) => ns.map((n) => ({ ...n, position: auto[n.id] ?? n.position })));
  };

  const versions = useLoad(() => api.listVersions(ir.id), [ir.id]);
  const unnamed = actions.filter((a) => !a.name.trim()).length;
  const save = useAction(async () => {
    const next: ScenarioIR = { ...ir, actions, relations };
    const resp = await api.saveScenario(ir.id, next, note.trim() || "流程編輯");
    setDirty(false);
    setNote("");
    await absorb(resp);
    setSavedMsg("已儲存為新版本。");
    void versions.reload(true);
  });
  const discard = () => { setActions(ir.actions); setRelations(ir.relations); setDirty(false); setSel(null); setHint(null); };

  const deps = relations.filter((r) => r.kind === "dependency");
  const unconfirmed = deps.filter((r) => (r as RelationX).confirmed !== true);
  // Confirming is the analyst's judgement on the link, not a rewrite of it, so the relation keeps its original source.
  const setConfirmed = (which: (r: Relation) => boolean, confirmed: boolean) => {
    setRelations((xs) => xs.map((r) => (r.kind === "dependency" && which(r) ? ({ ...r, confirmed } as Relation) : r)));
    touch();
  };
  const confirmAllDeps = () => setConfirmed(() => true, true);

  const errors = findings.filter((f) => f.level === "error").length;
  const warns = findings.filter((f) => f.level === "warn").length;
  // Selecting from the console points the inspector at the object; the viewport is left where the author put it.
  const openFinding = (f: Finding) => { if (f.target) setSel(f.target); };

  const selAction = sel?.type === "action" ? actions.find((a) => a.id === sel.id) : undefined;
  const selRelation = sel?.type === "relation" ? relations.find((r) => r.id === sel.id) : undefined;
  const nameOf = useMemo(() => new Map(actions.map((a) => [a.id, a.name])), [actions]);
  const versionRows = Array.isArray(versions.data) ? versions.data : [];

  const approved = isPlanApproved(ir.environment_plan);
  const designOk = errors === 0 && unconfirmed.length === 0;
  const hosts = ir.hosts ?? [];
  const svcOf = (hid: string) => (ir.services ?? []).filter((x: any) => x.host_ref === hid);

  return (
    <div className="workspace">
      <TopbarActions>
        {dirty && <span className="save-state">有未儲存的修改</span>}
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="版本備註（選填）" aria-label="版本備註" disabled={save.busy} />
        <button className="primary" disabled={!dirty || save.busy || unnamed > 0} title={unnamed > 0 ? "有行為沒有名稱，請先命名" : undefined} onClick={() => save.run()}>
          {save.busy ? <span className="spinner" /> : <Save size={15} />}{save.busy ? "儲存中…" : "儲存為新版本"}
        </button>
        <button disabled={!dirty || save.busy} onClick={discard}>捨棄修改</button>
        <button onClick={() => setConsoleOpen((o) => !o)} aria-pressed={consoleOpen}><ScanLine size={15} />設計檢查</button>
      </TopbarActions>

      <aside className="library" aria-label="元件">
        <h2>元件</h2>
        <h3>資產</h3>
        {hosts.length === 0 ? (
          <p className="note">還沒有主機。完成「軟體依賴」後，這裡會列出由攻擊行為推得的主機與服務。</p>
        ) : hosts.map((h) => {
          const svcs = svcOf(h.id);
          return (
            <div className="library-item" key={h.id} title={h.id}>
              <span className="ico"><Server size={14} /></span>
              <span className="name">{h.role}</span>
              <span className="port">{svcs.map((x: any) => x.port).filter(Boolean).join(" / ") || "—"}</span>
            </div>
          );
        })}
        <h3>步驟</h3>
        {actions.map((a, i) => (
          <button key={a.id} className={`library-item ${sel?.type === "action" && sel.id === a.id ? "on" : ""}`} onClick={() => setSel({ type: "action", id: a.id })}>
            <span className="ico">{i + 1}</span>
            <span className="name">{a.name || "（未命名）"}</span>
          </button>
        ))}
        <button className="library-item" onClick={addAction} aria-label="新增一個空白行為">
          <span className="ico"><Plus size={14} /></span><span className="name muted">新增行為</span>
        </button>
      </aside>

      <div className="canvas-col">
        <div className="canvas">
          <div className="canvas-tools" role="toolbar" aria-label="畫布工具">
            <span className="canvas-label">攻擊鏈</span>
            <span className="badge">{actions.length} 步驟</span>
            <button onClick={addAction}>＋ 新增行為</button>
            <button onClick={autoLayout}><LayoutGrid size={15} />自動排版</button>
            <span className="sep" />
            <span className="canvas-label muted" style={{ fontWeight: 500 }}>新連線</span>
            <button aria-pressed={newKind === "temporal"} onClick={() => setNewKind("temporal")}>時間先後</button>
            <button aria-pressed={newKind === "dependency"} onClick={() => setNewKind("dependency")}>依賴</button>
          </div>
          {actions.length === 0 && (
            <div className="canvas-empty">
              <h2>尚無攻擊步驟</h2>
              <span>這個情境還沒有攻擊行為。新增第一個行為，或回到情資匯入重新分析報告。</span>
              <button className="primary" onClick={addAction}><Plus size={16} />新增第一個行為</button>
            </div>
          )}
          <ReactFlow
            nodes={nodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes}
            onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={onConnect}
            onConnectStart={() => setConnecting(true)} onConnectEnd={() => setConnecting(false)}
            className={connecting ? "connecting" : ""} connectionRadius={48}
            onNodeClick={(_, n) => setSel({ type: "action", id: n.id })}
            onEdgeClick={(_, e) => setSel({ type: "relation", id: e.id })}
            onPaneClick={() => setSel(null)}
            onNodeDragStop={persistPositions}
            onNodesDelete={(ns) => removeActions(ns.map((n) => n.id))}
            onEdgesDelete={(es) => removeRelations(es.map((e) => e.id))}
            deleteKeyCode={["Delete", "Backspace"]}
            fitView fitViewOptions={{ padding: 0.04, maxZoom: 1, minZoom: 0.72 }} minZoom={0.2}
            proOptions={{ hideAttribution: true }}
          >
            <Background variant={BackgroundVariant.Lines} color={GRID} gap={32} lineWidth={1} />
            <Controls showInteractive={false} position="bottom-left" />
            <MiniMap pannable position="bottom-right" nodeColor={EDGE} nodeStrokeWidth={0} maskColor="#070b11c7" style={{ width: 140, height: 90 }} ariaLabel="畫布縮圖" />
          </ReactFlow>
          <div className="canvas-status">
            <span className="local-indicator" />
            <span>設計圖，不是執行紀錄</span>
            {deps.length > 0 && (
              <span data-testid="dep-confirm-bar" style={{ display: "inline-flex", alignItems: "center", gap: 9, marginLeft: 8 }}>
                <span className={unconfirmed.length ? "status-PARTIAL" : "status-PASS"}>依賴關係已確認 {deps.length - unconfirmed.length} / {deps.length}</span>
                {unconfirmed.length > 0 && <button className="small" title="只有經你確認的依賴關係，才會在拓樸規劃中開通主機間連線" onClick={confirmAllDeps}>確認全部依賴關係</button>}
              </span>
            )}
          </div>
          {(hint || savedMsg || save.error) && (
            <div className="feedback" role="status">
              {save.error ? <span className="status-FAIL">儲存失敗：{save.error.detail}。修改仍保留在畫面上，尚未寫入後端。</span>
                : hint ? <span className="status-PARTIAL">{hint}</span>
                : <span>{savedMsg}</span>}
              <button className="quiet icon" aria-label="關閉訊息" onClick={() => { setHint(null); setSavedMsg(null); save.clearError(); }}><X size={15} /></button>
            </div>
          )}
        </div>

        <section className={`console ${consoleOpen ? "open" : ""}`} data-testid="validation-console" aria-label="設計檢查">
          <button className="console-toggle" aria-expanded={consoleOpen} onClick={() => setConsoleOpen((o) => !o)}>
            <ScanLine size={16} />
            <strong>設計檢查</strong>
            {findings.length === 0 ? <span className="badge approved">沒有發現問題</span> : (
              <>
                {errors > 0 && <span className="badge insufficient">{errors} 個問題</span>}
                {warns > 0 && <span className="badge pending">{warns} 個待處理</span>}
                {findings.length - errors - warns > 0 && <span className="badge">{findings.length - errors - warns} 個提醒</span>}
              </>
            )}
            <span className="muted">隨畫布即時計算，只檢查這張設計圖；不代表部署或驗證結果</span>
            <ChevronUp size={16} className="chev" aria-hidden />
          </button>
          <div className="console-body">
            <div {...(consoleOpen ? {} : { inert: "" })}>
              <ul className="console-list">
                {findings.length === 0 && <li className="console-empty"><Check size={16} />流程圖本身沒有可指出的問題。</li>}
                {findings.map((f) => (
                  <li key={f.id}>
                    <button className={`finding ${f.level}`} onClick={() => openFinding(f)}>
                      <span className="badge">{f.level === "error" ? "問題" : f.level === "warn" ? "待處理" : "提醒"}</span>
                      <span className="text">{f.text}</span>
                      <small>{f.target?.id}</small>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </section>
      </div>

      <aside className="context-dock" ref={inspectorRef} aria-label={sel ? "屬性" : "設計工作台"}>
        {selAction ? (
          <div className="swap" key={`a:${selAction.id}`}>
            <div className="overview-title">
              <h2>攻擊行為</h2><SourceTag source={selAction.source} />
              <button className="quiet icon close" aria-label="關閉屬性" onClick={() => setSel(null)}><X size={16} /></button>
            </div>
            <div className="mono muted">{selAction.id}</div>
            <label className="field"><span>名稱</span>
              <input value={selAction.name} onChange={(e) => patchAction(selAction.id, { name: e.target.value })} />
            </label>
            <label className="field"><span>說明</span>
              <textarea rows={3} value={selAction.description ?? ""} onChange={(e) => patchAction(selAction.id, { description: e.target.value || undefined })} />
            </label>
            <div className="grid c2">
              <label className="field"><span>ATT&CK 技術</span>
                <input className="mono" value={selAction.attack_technique ?? ""} placeholder="T1190" onChange={(e) => patchAction(selAction.id, { attack_technique: e.target.value || undefined })} />
              </label>
              <label className="field"><span>戰術</span>
                <input value={selAction.attack_tactic ?? ""} placeholder="initial-access" onChange={(e) => patchAction(selAction.id, { attack_tactic: e.target.value || undefined })} />
              </label>
            </div>
            <label className="field"><span>目標主機</span>
              {hosts.length ? (
                <select value={selAction.target_host_ref ?? ""} onChange={(e) => patchAction(selAction.id, { target_host_ref: e.target.value || undefined })}>
                  <option value="">（未指定）</option>
                  {selAction.target_host_ref && !hosts.some((h) => h.id === selAction.target_host_ref) && <option value={selAction.target_host_ref}>{selAction.target_host_ref}</option>}
                  {hosts.map((h) => <option key={h.id} value={h.id}>{h.role} ({h.id})</option>)}
                </select>
              ) : (
                <input className="mono" value={selAction.target_host_ref ?? ""} onChange={(e) => patchAction(selAction.id, { target_host_ref: e.target.value || undefined })} />
              )}
            </label>
            <EpistemicSelect value={selAction.epistemic_status} onChange={(v) => patchAction(selAction.id, { epistemic_status: v })} />
            <div className="muted" style={{ fontSize: 12 }}>證據：{selAction.evidence_refs?.length ? selAction.evidence_refs.join("、") : "無"}</div>
            <div><button className="danger quiet" onClick={() => removeActions([selAction.id])}><Trash2 size={15} />刪除行為（連同相關連線）</button></div>
          </div>
        ) : selRelation ? (
          <div className="swap" key={`r:${selRelation.id}`}>
            <div className="overview-title">
              <h2>關係</h2><SourceTag source={selRelation.source} />
              <button className="quiet icon close" aria-label="關閉屬性" onClick={() => setSel(null)}><X size={16} /></button>
            </div>
            <div className="mono muted">{selRelation.id}</div>
            <div style={{ fontSize: 13, fontWeight: 600 }}>
              {nameOf.get(selRelation.from_action) ?? selRelation.from_action} <span className="muted">→</span> {nameOf.get(selRelation.to_action) ?? selRelation.to_action}
            </div>
            <div className="field"><span style={{ display: "block", marginBottom: 5, fontSize: 12 }} className="muted">類型</span>
              <div className="seg">
                {(["temporal", "dependency"] as RelationKind[]).map((k) => (
                  <button key={k} className={selRelation.kind === k ? "on" : ""} aria-pressed={selRelation.kind === k} onClick={() => selRelation.kind !== k && patchRelation(selRelation.id, { kind: k })}>{KIND_LABEL[k]}</button>
                ))}
              </div>
            </div>
            <div className="muted" style={{ fontSize: 12 }}>
              {selRelation.kind === "dependency" ? "依賴：沒有前一步，後一步無法進行。" : "時間先後：只記錄發生順序。若確定後者需要前者，請改為依賴。"}
            </div>
            <label className="field"><span>理由</span>
              <textarea rows={3} value={selRelation.rationale ?? ""} onChange={(e) => patchRelation(selRelation.id, { rationale: e.target.value || undefined })} />
            </label>
            <EpistemicSelect value={selRelation.epistemic_status} onChange={(v) => patchRelation(selRelation.id, { epistemic_status: v })} />
            {selRelation.kind === "dependency" && (
              <label className="row" style={{ gap: 8, fontSize: 12 }}>
                <input type="checkbox" checked={(selRelation as RelationX).confirmed === true}
                  onChange={(e) => setConfirmed((r) => r.id === selRelation.id, e.target.checked)} />
                我確認這個依賴關係成立
              </label>
            )}
            <div><button className="danger quiet" onClick={() => removeRelations([selRelation.id])}><Trash2 size={15} />刪除關係</button></div>
          </div>
        ) : (
          <div className="swap" key="overview">
            <div className="overview-title"><Layers size={20} /><h2>設計工作台</h2></div>
            <p className="overview-name">{ir.name || ir.id}</p>
            <div className="overview-chain">
              <GitBranch size={16} />
              <span>{actions.length} 步驟</span>
              <span>{deps.length} 依賴{deps.length > 0 && `（已確認 ${deps.length - unconfirmed.length}）`}</span>
              <span>{relations.length - deps.length} 時序</span>
            </div>
            <div className="topology-summary">
              <h3>訓練資產</h3>
              {hosts.length === 0 ? <div><span className="muted">尚未分析軟體依賴</span></div> : hosts.map((h) => (
                <div key={h.id}>
                  <span>{h.role}</span>
                  <span>{svcOf(h.id).map((x: any) => x.port).filter(Boolean).join(" / ") || "—"}</span>
                  <Check size={13} />
                </div>
              ))}
            </div>
            <ol className="design-route" aria-label="設計流程">
              <li className={designOk && !dirty ? "complete" : "current"}>
                <span>{designOk && !dirty ? <Check size={12} /> : "1"}</span>編排設計
                {dirty && <small>有未儲存的修改</small>}
              </li>
              <li className={designOk ? "complete" : ""}>
                <span>{designOk ? <Check size={12} /> : "2"}</span>設計檢查
                <small>{errors > 0 ? `${errors} 個問題` : unconfirmed.length > 0 ? `${unconfirmed.length} 條依賴未確認` : "通過"}</small>
              </li>
              <li className={approved ? "complete" : designOk && !dirty ? "current" : ""}>
                <span>{approved ? <Check size={12} /> : "3"}</span>人工核准
                <small>{approved ? "拓樸已核准" : "在拓樸頁進行"}</small>
              </li>
            </ol>
            {errors > 0 ? (
              <button className="primary next-action" onClick={() => setConsoleOpen(true)}><ScanLine size={16} />查看設計檢查的問題<ArrowRight size={15} /></button>
            ) : unconfirmed.length > 0 ? (
              <button className="primary next-action" onClick={confirmAllDeps}><Check size={16} />確認所有依賴<ArrowRight size={15} /></button>
            ) : dirty ? (
              <button className="primary next-action" disabled={save.busy || unnamed > 0} onClick={() => save.run()}>{save.busy ? <span className="spinner" /> : <Save size={16} />}儲存這份設計<ArrowRight size={15} /></button>
            ) : (
              <Link className="next-action-link" to="/deps"><button className="primary next-action"><ArrowRight size={16} />下一步：軟體依賴<ArrowRight size={15} /></button></Link>
            )}
            <details className="capability-note">
              <summary>版本紀錄　v{ir.ir_version ?? 1}</summary>
              {versions.error ? <ApiNotice error={versions.error} what="版本紀錄" onRetry={() => versions.reload()} />
                : versions.loading && !versions.data ? <p><span className="spinner" /> 載入中…</p>
                : versionRows.length === 0 ? <p>尚無版本紀錄。</p>
                : versionRows.map((v) => (
                  <div key={v.ir_version} className="version-row">
                    <span className="mono" style={{ color: v.ir_version === ir.ir_version ? "var(--accent)" : undefined }}>v{v.ir_version}</span>
                    <span className="note" title={v.note}>{v.note || "—"}</span>
                    <span className="nowrap">{fmtTime(v.ts)}</span>
                  </div>
                ))}
            </details>
            <details className="capability-note">
              <summary>這張圖代表什麼</summary>
              <p>這是攻擊流程的設計：連線只表示「後一步需要前一步」或發生順序。這裡不執行任何攻擊；部署與驗證在後面的步驟，並且只顯示後端回報的真實狀態。</p>
            </details>
            <Link to="/missing" className="muted" style={{ fontSize: 12 }}>← 缺失補充</Link>
          </div>
        )}
      </aside>
    </div>
  );
}

function EpistemicSelect({ value, onChange }: { value: EpistemicStatus; onChange: (v: EpistemicStatus) => void }) {
  return (
    <label className="field"><span>依據程度</span>
      <select value={value} onChange={(e) => onChange(e.target.value as EpistemicStatus)}>
        {EPISTEMIC_ORDER.map((s) => <option key={s} value={s}>{EPISTEMIC[s].label}（{s}）</option>)}
      </select>
    </label>
  );
}

export function FlowPage() {
  const { ir } = useScenario();
  // key by scenario so switching scenarios resets the local draft
  return <ScenarioGate title="攻擊流程">{ir && <Editor key={ir.id} ir={ir} />}</ScenarioGate>;
}
