import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode, type SelectHTMLAttributes, type SyntheticEvent } from "react";
import ReactFlow, {
  Background, BackgroundVariant, Controls, EdgeLabelRenderer, getBezierPath, Handle, MarkerType, MiniMap, NodeToolbar, Position, useEdgesState, useNodesState,
  type Connection, type Edge, type EdgeProps, type Node, type NodeChange, type NodeProps,
} from "reactflow";
import "reactflow/dist/style.css";
import type { Action, AttackFlowAsset, AttackFlowCondition, AttackFlowOperator, EpistemicStatus, Relation, RelationKind, ScenarioIR } from "@contracts";
import { api } from "../lib/api";
import { useAction, useLoad } from "../lib/hooks";
import { layeredLayout, loadPositions, savePositions } from "../lib/layout";
import { flowEdgeId, flowEdgesOf, lintFlow, type Finding, type FlowEdge, type FlowEdgeKind, type FlowNodeType } from "../lib/flowlint";
import { EDGE, GRID, LABEL, ROUTE, TEMPORAL } from "../lib/palette";
import type { RelationX } from "../lib/plan";
import { useScenario } from "../lib/scenario";
import {
  ApiNotice, EPISTEMIC, EPISTEMIC_ORDER, fmtTime, ScenarioGate, SourceTag,
} from "../components/ui";
import { isPlanApproved } from "../lib/plan";
import { TopbarActions } from "../lib/topbar";
import { Link } from "react-router-dom";
import {
  ArrowRight, Check, ChevronDown, ChevronUp, Copy, Crosshair, Database, DoorOpen, Flag, GitBranch, KeyRound, Layers, LayoutGrid, Network, Plus, Radar,
  Save, ScanLine, Search, Server, TerminalSquare, Trash2, X,
} from "lucide-react";

const KIND_LABEL: Record<RelationKind, string> = { temporal: "時間先後", dependency: "依賴" };
// Attack Flow edges. Colours mirror theme.css tokens (--route / --ok / --warn / --text-dim): SVG markers cannot read CSS variables.
const FLOW_COLOR: Record<FlowEdgeKind, string> = { effect: ROUTE, true: "#7ee2a8", false: "#f1c16c", asset: LABEL };
const FLOW_LABEL: Record<FlowEdgeKind, string> = { effect: "流程", true: "成立", false: "不成立", asset: "資產" };
const NODE_LABEL: Record<FlowNodeType, string> = { action: "攻擊行為", condition: "條件", operator: "運算", asset: "資產" };
/** What a new line means. temporal/dependency are the editor's own relations; flow is an Attack Flow edge. */
type ConnectKind = RelationKind | "flow";

/** Shared by every node type: start marker and the per-node commands. */
interface NodeCommon { fresh: boolean; start: boolean; issues: number; onDelete: () => void; onCheck: () => void; onToggleStart: () => void }
interface ActionNodeData extends NodeCommon {
  action: Action; index: number; host?: string; requires: number;
  hosts: { id: string; role: string }[]; onPatch: (p: Partial<Action>) => void;
  onDuplicate: () => void;
}
interface ConditionNodeData extends NodeCommon { condition: AttackFlowCondition }
interface OperatorNodeData extends NodeCommon { op: AttackFlowOperator; inputs: number; onToggleOp: () => void }
interface AssetNodeData extends NodeCommon { asset: AttackFlowAsset }
type AnyNodeData = ActionNodeData | ConditionNodeData | OperatorNodeData | AssetNodeData;

/** One dropdown for the whole app: a native <select> (keyboard + mobile native picker) with the OS arrow removed
 *  and a lucide chevron drawn in our own tokens, so every menu matches the dark studio controls in light and dark.
 *  nodeSafe adds React Flow's nodrag/nopan and stops pointer events, so opening it on a card never drags the canvas. */
function Select({ children, nodeSafe, className, ...rest }: SelectHTMLAttributes<HTMLSelectElement> & { nodeSafe?: boolean }) {
  const stop = (e: SyntheticEvent) => e.stopPropagation();
  return (
    <div className={`select${nodeSafe ? " nodrag nopan" : ""}${className ? ` ${className}` : ""}`}
      onPointerDown={nodeSafe ? stop : undefined} onClick={nodeSafe ? stop : undefined}>
      <select className={nodeSafe ? "nodrag nopan" : undefined} {...rest}>{children}</select>
      <ChevronDown className="select-chevron" size={14} aria-hidden />
    </div>
  );
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
  // Keep typing and dropdown-opening inside the card: never drag/pan the canvas, never let Delete/Backspace reach the graph.
  const stop = (e: SyntheticEvent) => e.stopPropagation();
  return (
    <>
      <NodeToolbar isVisible={selected} position={Position.Top} offset={12}>
        <div className="node-toolbar nodrag nopan" onClick={(e) => e.stopPropagation()}>
          <button aria-label="複製這個行為" title="複製（不含連線）" onClick={data.onDuplicate}><Copy size={15} /></button>
          <button aria-label="刪除這個行為" title="刪除（連同相關連線）" onClick={data.onDelete}><Trash2 size={15} /></button>
          <button aria-label={data.start ? "取消起點標記" : "標記為流程起點"} aria-pressed={data.start} title={data.start ? "取消起點標記" : "標記為流程起點"} onClick={data.onToggleStart}><Flag size={15} /></button>
          <button aria-label="查看這個行為的設計檢查" title="設計檢查" onClick={data.onCheck}><ScanLine size={15} /></button>
        </div>
      </NodeToolbar>
      {/* Handles sit outside the article so its clipped corner does not cut them; only the article ever animates. */}
      <Handle type="target" position={Position.Left} />
      <article className={`gnode ${selected ? "editing" : ""} ${data.fresh ? "fresh" : ""} ${data.issues ? "has-issues" : ""} ${data.start ? "start" : ""}`}>
        <div className="node-top">
          <span className="step-icon"><Icon size={17} /></span>
          <span className="node-number">STEP {String(data.index + 1).padStart(2, "0")}</span>
          {data.start && <span className="start-flag"><Flag size={11} />起點</span>}
          {a.attack_technique && <span className="badge technique">{a.attack_technique}</span>}
        </div>
        {selected ? (
          // Edit the core fields right here. Everything carries nodrag/nopan; description, tactic and evidence stay in the dock.
          <div className="node-edit nodrag nopan" onPointerDown={stop} onClick={stop} onKeyDown={stop}>
            <input className="node-name-input nodrag nopan" aria-label="行為名稱" placeholder="為這個行為命名"
              value={a.name} onChange={(e) => data.onPatch({ name: e.target.value })} />
            <label className="node-field"><span>目標主機</span>
              {data.hosts.length ? (
                <Select nodeSafe aria-label="目標主機" value={a.target_host_ref ?? ""}
                  onChange={(e) => data.onPatch({ target_host_ref: e.target.value || undefined })}>
                  <option value="">（未指定）</option>
                  {a.target_host_ref && !data.hosts.some((h) => h.id === a.target_host_ref) && <option value={a.target_host_ref}>{a.target_host_ref}</option>}
                  {data.hosts.map((h) => <option key={h.id} value={h.id}>{h.role}（{h.id}）</option>)}
                </Select>
              ) : (
                <input className="mono nodrag nopan" aria-label="目標主機" placeholder="尚無主機，可直接輸入" value={a.target_host_ref ?? ""}
                  onChange={(e) => data.onPatch({ target_host_ref: e.target.value || undefined })} />
              )}
            </label>
            <div className="node-edit-row">
              <label className="node-field"><span>依據程度</span>
                <Select nodeSafe aria-label="依據程度" value={a.epistemic_status}
                  onChange={(e) => data.onPatch({ epistemic_status: e.target.value as EpistemicStatus })}>
                  {EPISTEMIC_ORDER.map((s) => <option key={s} value={s}>{EPISTEMIC[s].label}</option>)}
                </Select>
              </label>
              <label className="node-field"><span>ATT&amp;CK 技術</span>
                <input className="mono nodrag nopan" aria-label="ATT&CK 技術" placeholder="T1190" value={a.attack_technique ?? ""}
                  onChange={(e) => data.onPatch({ attack_technique: e.target.value || undefined })} />
              </label>
            </div>
          </div>
        ) : (
          <>
            <strong>{a.name || "（未命名）"}</strong>
            <div className="node-target"><ArrowRight size={13} /><span>{data.host ?? "未指定目標主機"}</span></div>
          </>
        )}
        <div className="node-bottom">
          <span><GitBranch size={12} />{data.requires ? `${data.requires} 項前置` : "無前置依賴"}</span>
          {/* What the report supports, or a design problem — never a run result. */}
          <span className={data.issues ? "issue-text" : ""}>{data.issues ? `${data.issues} 個問題` : EPISTEMIC[a.epistemic_status]?.label ?? a.epistemic_status}{a.source === "user" ? "・已編輯" : ""}</span>
        </div>
      </article>
      <Handle type="source" position={Position.Right} />
    </>
  );
}

/** Commands shared by the three Attack Flow node types. Assets cannot be a start, so they get no flag. */
function FlowNodeTools({ data, selected, what, canStart = true, children }: { data: NodeCommon; selected: boolean; what: string; canStart?: boolean; children?: ReactNode }) {
  return (
    <NodeToolbar isVisible={selected} position={Position.Top} offset={12}>
      <div className="node-toolbar nodrag nopan" onClick={(e) => e.stopPropagation()}>
        {children}
        <button aria-label={`刪除這個${what}`} title="刪除（連同相關連線）" onClick={data.onDelete}><Trash2 size={15} /></button>
        {canStart && <button aria-label={data.start ? "取消起點標記" : "標記為流程起點"} aria-pressed={data.start} title={data.start ? "取消起點標記" : "標記為流程起點"} onClick={data.onToggleStart}><Flag size={15} /></button>}
        <button aria-label={`查看這個${what}的設計檢查`} title="設計檢查" onClick={data.onCheck}><ScanLine size={15} /></button>
      </div>
    </NodeToolbar>
  );
}
const fnodeClass = (kind: string, d: NodeCommon) => `fnode ${kind} ${d.fresh ? "fresh" : ""} ${d.issues ? "has-issues" : ""} ${d.start ? "start" : ""}`;

/** A decision point drawn as a diamond: one way in, "成立" out to the right, "不成立" out of the bottom.
 *  It records a branch in the design — which path applies is never decided or shown here. */
function ConditionNode({ data, selected }: NodeProps<ConditionNodeData>) {
  const c = data.condition;
  return (
    <>
      <FlowNodeTools data={data} selected={selected} what="條件" />
      <Handle type="target" position={Position.Left} />
      <div className={fnodeClass("cond", data)}>
        <svg className="shape" viewBox="0 0 220 132" aria-hidden><polygon points="110,1 219,66 110,131 1,66" /></svg>
        {data.start && <span className="start-flag"><Flag size={11} />起點</span>}
        <div className="body">
          <span className="kind">條件</span>
          <span className="text" title={c.description}>{c.description?.trim() || "（未描述）"}</span>
        </div>
        <span className="branch yes">成立</span>
        <span className="branch no">不成立</span>
      </div>
      <Handle id="true" type="source" position={Position.Right} className="branch-true" />
      <Handle id="false" type="source" position={Position.Bottom} className="branch-false" />
    </>
  );
}

/** AND / OR: merges several incoming paths into one outgoing path. */
function OperatorNode({ data, selected }: NodeProps<OperatorNodeData>) {
  return (
    <>
      <FlowNodeTools data={data} selected={selected} what="運算">
        <button aria-label={`改為 ${data.op.operator === "AND" ? "OR" : "AND"}`} title={`改為 ${data.op.operator === "AND" ? "OR" : "AND"}`} onClick={data.onToggleOp} className="op-swap">{data.op.operator === "AND" ? "OR" : "AND"}</button>
      </FlowNodeTools>
      <Handle type="target" position={Position.Left} />
      <div className={fnodeClass("op", data)} title={data.op.operator === "AND" ? "AND：所有輸入路徑都要成立" : "OR：任一輸入路徑成立即可"}>
        {data.start && <span className="start-flag"><Flag size={11} />起點</span>}
        <strong>{data.op.operator}</strong>
        <small>{data.inputs} 入</small>
      </div>
      <Handle type="source" position={Position.Right} />
    </>
  );
}

/** Something an action acts on, drawn as a cylinder. It only receives "資產" lines from actions. */
function AssetNode({ data, selected }: NodeProps<AssetNodeData>) {
  const s = data.asset;
  return (
    <>
      <FlowNodeTools data={data} selected={selected} what="資產" canStart={false} />
      <Handle type="target" position={Position.Left} />
      <div className={fnodeClass("asset", data)}>
        <svg className="shape" viewBox="0 0 180 92" aria-hidden>
          <path d="M1,15 V77 A89,14 0 0 0 179,77 V15" />
          <ellipse cx="90" cy="15" rx="89" ry="14" />
        </svg>
        <div className="body">
          <span className="kind"><Database size={11} />資產</span>
          <span className="text" title={s.description}>{s.name?.trim() || "（未命名）"}</span>
        </div>
      </div>
    </>
  );
}
const nodeTypes = { action: ActionNode, condition: ConditionNode, operator: OperatorNode, asset: AssetNode };

interface RelEdgeData { label: string; tone: "route" | "hold" | "temporal" | "flow" | "flow-true" | "flow-false" | "flow-asset"; draw: boolean }

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

/** An Attack Flow edge. Brighter and heavier than a dependency, always labelled, so the two kinds of line never read alike. */
function toFlowEdge(e: FlowEdge, selected: boolean, fresh: boolean): Edge<RelEdgeData> {
  const color = FLOW_COLOR[e.kind];
  const asset = e.kind === "asset";
  return {
    id: e.id, type: "rel", source: e.from, target: e.to, selected,
    sourceHandle: e.kind === "true" || e.kind === "false" ? e.kind : undefined,
    className: fresh ? (asset ? "fresh-fade" : "fresh") : undefined,
    data: { label: FLOW_LABEL[e.kind], tone: e.kind === "effect" ? "flow" : (`flow-${e.kind}` as RelEdgeData["tone"]), draw: fresh && !asset },
    style: { stroke: color, strokeWidth: asset ? 1.5 : 2, strokeDasharray: asset ? "2 5" : undefined },
    markerEnd: { type: MarkerType.ArrowClosed, color, width: 16, height: 16 },
  };
}

const COL_W = 310;
/** Left-to-right by dependency/order depth, with alternate columns dropped half a row: neighbours never sit on the
 *  same line, which leaves room for the relation label between them and keeps long chains legible without zooming out. */
function flowLayout(ids: string[], relations: Relation[], flowEdges: FlowEdge[]) {
  const links = [...relations.map((r) => ({ from: r.from_action, to: r.to_action })), ...flowEdges.map((e) => ({ from: e.from, to: e.to }))];
  const pos = layeredLayout(ids, links, COL_W, 208);
  for (const p of Object.values(pos)) if (Math.round(p.x / COL_W) % 2 === 1) p.y += 66;
  return pos;
}

let seq = 0;
const newId = (prefix: string, taken: Set<string>) => {
  let id: string;
  do { id = `${prefix}_u${Date.now().toString(36)}${(seq++).toString(36)}`; } while (taken.has(id));
  return id;
};

type Sel = { type: FlowNodeType | "relation" | "flow"; id: string } | null;
const without = (refs: string[] | undefined, gone: Set<string>) => (refs?.some((r) => gone.has(r)) ? refs.filter((r) => !gone.has(r)) : refs);

function Editor({ ir }: { ir: ScenarioIR }) {
  const { absorb } = useScenario();
  const [actions, setActions] = useState<Action[]>(ir.actions);
  const [relations, setRelations] = useState<Relation[]>(ir.relations);
  // Attack Flow part of the design: decision points, AND/OR joins, assets, and which nodes the flow starts from.
  const [conditions, setConditions] = useState<AttackFlowCondition[]>(ir.conditions ?? []);
  const [operators, setOperators] = useState<AttackFlowOperator[]>(ir.operators ?? []);
  const [assets, setAssets] = useState<AttackFlowAsset[]>(ir.assets ?? []);
  const [startRefs, setStartRefs] = useState<string[]>(ir.flow?.start_refs ?? []);
  const adoptIr = () => {
    setActions(ir.actions); setRelations(ir.relations);
    setConditions(ir.conditions ?? []); setOperators(ir.operators ?? []); setAssets(ir.assets ?? []); setStartRefs(ir.flow?.start_refs ?? []);
  };
  const [dirty, setDirty] = useState(false);
  const [sel, setSel] = useState<Sel>(null);
  const [newKind, setNewKind] = useState<ConnectKind>("temporal");
  const [note, setNote] = useState("");
  const [hint, setHint] = useState<string | null>(null);
  const [savedMsg, setSavedMsg] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);
  const inspectorRef = useRef<HTMLDivElement>(null);
  useEffect(() => { inspectorRef.current?.scrollTo({ top: 0 }); }, [sel?.type, sel?.id]);
  const posKey = `cr.flowpos.${ir.id}`;
  const stored = useRef(loadPositions(posKey));

  const [nodes, setNodes, onNodesChange] = useNodesState<AnyNodeData>([]);
  // Objects created in this editing session: only these get an entrance, so loading a scenario never animates.
  const fresh = useRef(new Set<string>());
  const [consoleOpen, setConsoleOpen] = useState(false);
  const hostRole = useMemo(() => new Map((ir.hosts ?? []).map((h) => [h.id, h.role])), [ir.hosts]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const extras = useMemo(() => ({ conditions, operators, assets, startRefs }), [conditions, operators, assets, startRefs]);
  const flowEdges = useMemo(() => flowEdgesOf(actions, extras), [actions, extras]);
  const findings = useMemo(() => lintFlow(actions, relations, extras), [actions, relations, extras]);
  const typeOf = useMemo(() => {
    const m = new Map<string, FlowNodeType>();
    actions.forEach((a) => m.set(a.id, "action")); conditions.forEach((c) => m.set(c.id, "condition"));
    operators.forEach((o) => m.set(o.id, "operator")); assets.forEach((x) => m.set(x.id, "asset"));
    return m;
  }, [actions, conditions, operators, assets]);

  // Adopt a new IR from the server (after save / reload) only when there are no local edits to lose.
  const irStamp = `${ir.id}:${ir.ir_version}:${ir.updated_at}`;
  const lastStamp = useRef(irStamp);
  useEffect(() => {
    if (lastStamp.current === irStamp) return;
    lastStamp.current = irStamp;
    if (!dirty) adoptIr();
  }, [irStamp]); // eslint-disable-line

  useEffect(() => {
    setNodes((prev) => {
      const prevPos = new Map(prev.map((n) => [n.id, n.position]));
      const auto = flowLayout([...typeOf.keys()], relations, flowEdges);
      const common = (type: FlowNodeType, id: string): NodeCommon => ({
        fresh: fresh.current.has(id), start: startRefs.includes(id),
        issues: findings.filter((f) => f.level === "error" && f.target?.type === type && f.target.id === id).length,
        onDelete: () => removeNodes([id]), onCheck: () => setConsoleOpen(true), onToggleStart: () => toggleStart(id),
      });
      const node = (type: FlowNodeType, id: string, data: AnyNodeData): Node<AnyNodeData> => ({
        id, type, data,
        position: prevPos.get(id) ?? stored.current[id] ?? auto[id] ?? { x: 0, y: 0 },
        selected: sel?.type === type && sel.id === id,
      });
      const built = [
        ...actions.map((a, index) => node("action", a.id, {
          ...common("action", a.id), action: a, index,
          host: a.target_host_ref ? hostRole.get(a.target_host_ref) ?? a.target_host_ref : undefined,
          requires: relations.filter((r) => r.kind === "dependency" && r.to_action === a.id).length,
          hosts: ir.hosts ?? [], onPatch: (p: Partial<Action>) => patchAction(a.id, p),
          onDuplicate: () => duplicateAction(a.id),
        })),
        ...conditions.map((c) => node("condition", c.id, { ...common("condition", c.id), condition: c })),
        ...operators.map((o) => node("operator", o.id, {
          ...common("operator", o.id), op: o, inputs: flowEdges.filter((e) => e.to === o.id).length,
          onToggleOp: () => patchOperator(o.id, { operator: o.operator === "AND" ? "OR" : "AND" }),
        })),
        ...assets.map((x) => node("asset", x.id, { ...common("asset", x.id), asset: x })),
      ];
      // Loaded nodes keep their order (actions first); anything created in this session follows, in creation order.
      const order = [...fresh.current];
      return [
        ...built.filter((n) => !fresh.current.has(n.id)),
        ...built.filter((n) => fresh.current.has(n.id)).sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id)),
      ];
    });
  }, [actions, relations, conditions, operators, assets, startRefs, flowEdges, typeOf, sel, hostRole, findings]); // eslint-disable-line
  useEffect(() => {
    setEdges([
      ...relations.map((r) => toEdge(r, sel?.type === "relation" && sel.id === r.id, fresh.current.has(r.id))),
      // A ref to a node that no longer exists cannot be drawn; the design check reports it instead.
      ...flowEdges.filter((e) => typeOf.has(e.from) && typeOf.has(e.to))
        .map((e) => toFlowEdge(e, sel?.type === "flow" && sel.id === e.id, fresh.current.has(e.id))),
    ]);
  }, [relations, flowEdges, typeOf, sel]); // eslint-disable-line

  const touch = () => { setDirty(true); setSavedMsg(null); };
  const patchAction = (id: string, p: Partial<Action>) => {
    setActions((xs) => xs.map((a) => (a.id === id ? { ...a, ...p, source: "user" } : a)));
    touch();
  };
  const patchRelation = (id: string, p: Partial<Relation>) => {
    setRelations((xs) => xs.map((r) => (r.id === id ? { ...r, ...p, source: "user" } : r)));
    touch();
  };
  const patchCondition = (id: string, p: Partial<AttackFlowCondition>) => {
    setConditions((xs) => xs.map((c) => (c.id === id ? { ...c, ...p, source: "user" } : c)));
    touch();
  };
  const patchOperator = (id: string, p: Partial<AttackFlowOperator>) => {
    setOperators((xs) => xs.map((o) => (o.id === id ? { ...o, ...p, source: "user" } : o)));
    touch();
  };
  const patchAsset = (id: string, p: Partial<AttackFlowAsset>) => {
    setAssets((xs) => xs.map((x) => (x.id === id ? { ...x, ...p, source: "user" } : x)));
    touch();
  };
  const toggleStart = (id: string) => {
    setStartRefs((xs) => (xs.includes(id) ? xs.filter((x) => x !== id) : [...xs, id]));
    touch();
  };
  /** Delete nodes of any type, together with every relation, flow ref and start marker that pointed at them. */
  const removeNodes = (ids: string[]) => {
    const gone = new Set(ids);
    setActions((xs) => xs.filter((a) => !gone.has(a.id)).map((a) => {
      const effect_refs = without(a.effect_refs, gone), asset_refs = without(a.asset_refs, gone);
      return effect_refs === a.effect_refs && asset_refs === a.asset_refs ? a : { ...a, effect_refs, asset_refs };
    }));
    setConditions((xs) => xs.filter((c) => !gone.has(c.id)).map((c) => {
      const on_true_refs = without(c.on_true_refs, gone), on_false_refs = without(c.on_false_refs, gone);
      return on_true_refs === c.on_true_refs && on_false_refs === c.on_false_refs ? c : { ...c, on_true_refs, on_false_refs };
    }));
    setOperators((xs) => xs.filter((o) => !gone.has(o.id)).map((o) => {
      const effect_refs = without(o.effect_refs, gone);
      return effect_refs === o.effect_refs ? o : { ...o, effect_refs };
    }));
    setAssets((xs) => xs.filter((x) => !gone.has(x.id)));
    setStartRefs((xs) => (xs.some((x) => gone.has(x)) ? xs.filter((x) => !gone.has(x)) : xs));
    setRelations((xs) => xs.filter((r) => !gone.has(r.from_action) && !gone.has(r.to_action)));
    setSel((s) => (s && s.type !== "relation" && s.type !== "flow" && gone.has(s.id) ? null : s));
    touch();
  };
  /** Flow edges live in the source node's ref list; which list depends on the node type and the edge kind. */
  const editRefs = (from: string, kind: FlowEdgeKind, fn: (refs: string[]) => string[]) => {
    const t = typeOf.get(from);
    if (t === "action") {
      const key = kind === "asset" ? "asset_refs" : "effect_refs";
      setActions((xs) => xs.map((a) => (a.id === from ? { ...a, [key]: fn(a[key] ?? []), source: "user" } : a)));
    } else if (t === "condition") {
      const key = kind === "false" ? "on_false_refs" : "on_true_refs";
      setConditions((xs) => xs.map((c) => (c.id === from ? { ...c, [key]: fn(c[key] ?? []), source: "user" } : c)));
    } else if (t === "operator") {
      setOperators((xs) => xs.map((o) => (o.id === from ? { ...o, effect_refs: fn(o.effect_refs ?? []), source: "user" } : o)));
    }
    touch();
  };
  const removeFlowEdges = (ids: string[]) => {
    const gone = new Set(ids);
    for (const e of flowEdges) if (gone.has(e.id)) editRefs(e.from, e.kind, (refs) => refs.filter((r) => r !== e.to));
    setSel((s) => (s && s.type === "flow" && gone.has(s.id) ? null : s));
  };
  /** Move a condition's line to its other branch. */
  const flipBranch = (e: FlowEdge) => {
    if (e.kind !== "true" && e.kind !== "false") return;
    const other: FlowEdgeKind = e.kind === "true" ? "false" : "true";
    editRefs(e.from, e.kind, (refs) => refs.filter((r) => r !== e.to));
    editRefs(e.from, other, (refs) => (refs.includes(e.to) ? refs : [...refs, e.to]));
    setSel({ type: "flow", id: flowEdgeId(e.from, other, e.to) });
  };
  const removeRelations = (ids: string[]) => {
    const gone = new Set(ids);
    setRelations((xs) => xs.filter((r) => !gone.has(r.id)));
    setSel((s) => (s && s.type === "relation" && gone.has(s.id) ? null : s));
    touch();
  };
  /** Park a new node under everything else and mark it as created in this session. */
  const stage = (id: string, gap: number) => {
    const maxY = nodes.reduce((m, n) => Math.max(m, n.position.y), -120);
    stored.current[id] = { x: 0, y: maxY + gap };
    fresh.current.add(id);
  };
  // New Attack Flow nodes start as the author's own, unverified design choices — same as a new action.
  const addCondition = () => {
    const id = newId("cond", new Set(typeOf.keys()));
    stage(id, 210);
    setConditions((xs) => [...xs, { id, description: "", on_true_refs: [], on_false_refs: [], epistemic_status: "inferred", source: "user", evidence_refs: [] }]);
    setSel({ type: "condition", id });
    touch();
  };
  const addOperator = () => {
    const id = newId("op", new Set(typeOf.keys()));
    stage(id, 210);
    setOperators((xs) => [...xs, { id, operator: "AND", effect_refs: [], epistemic_status: "inferred", source: "user", evidence_refs: [] }]);
    setSel({ type: "operator", id });
    touch();
  };
  const addAsset = () => {
    const id = newId("asset", new Set(typeOf.keys()));
    stage(id, 210);
    setAssets((xs) => [...xs, { id, name: "新資產", epistemic_status: "inferred", source: "user", evidence_refs: [] }]);
    setSel({ type: "asset", id });
    touch();
  };
  const addAction = () => {
    const id = newId("act", new Set(typeOf.keys()));
    stage(id, 150);
    setActions((xs) => [...xs, { id, name: "新攻擊行為", epistemic_status: "inferred", source: "user", evidence_refs: [] }]);
    setSel({ type: "action", id });
    touch();
  };
  // A copy keeps the step's own fields but none of its relations or flow lines: those are decided per step, not inherited.
  const duplicateAction = (srcId: string) => {
    const src = actions.find((a) => a.id === srcId);
    if (!src) return;
    const id = newId("act", new Set(typeOf.keys()));
    const at = nodes.find((n) => n.id === srcId)?.position ?? { x: 0, y: 0 };
    stored.current[id] = { x: at.x + 40, y: at.y + 150 };
    fresh.current.add(id);
    setActions((xs) => [...xs, { ...src, id, name: `${src.name}（複製）`, source: "user", effect_refs: undefined, asset_refs: undefined }]);
    setSel({ type: "action", id });
    touch();
  };
  const onConnect = useCallback((c: Connection) => {
    if (!c.source || !c.target) return;
    const from = typeOf.get(c.source), to = typeOf.get(c.target);
    if (!from || !to) return;
    if (c.source === c.target) { setHint(from === "action" ? "行為不能連到自己。" : "節點不能連到自己。"); return; }
    // temporal / dependency exist only between two actions. Any line touching a condition, operator or asset is a flow edge.
    if (newKind !== "flow" && from === "action" && to === "action") {
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
      return;
    }
    if (to === "asset" && from !== "action") { setHint("只有攻擊行為可以連到資產節點。"); return; }
    const kind: FlowEdgeKind = to === "asset" ? "asset" : from === "condition" ? (c.sourceHandle === "false" ? "false" : "true") : "effect";
    const id = flowEdgeId(c.source, kind, c.target);
    if (flowEdges.some((e) => e.id === id)) { setHint("這兩個節點之間已經有相同的流程連線。"); return; }
    if (from === "condition" && flowEdges.some((e) => e.from === c.source && e.to === c.target)) {
      setHint("這個節點已經接在此條件的另一個分支上；同一個節點不能同時是成立與不成立的去向。");
      return;
    }
    setHint(null);
    fresh.current.add(id);
    editRefs(c.source, kind, (refs) => (refs.includes(c.target!) ? refs : [...refs, c.target!]));
    setSel({ type: "flow", id });
  }, [relations, newKind, typeOf, flowEdges]); // eslint-disable-line

  // React Flow selects a node on pointer-down, which swaps an action card into its inline fields before the click
  // lands; those fields keep clicks to themselves, so onNodeClick alone can miss. Follow the selection change too.
  const handleNodesChange = (changes: NodeChange[]) => {
    onNodesChange(changes);
    for (const c of changes) {
      if (c.type === "select" && c.selected) { setSel({ type: typeOf.get(c.id) ?? "action", id: c.id }); break; }
    }
  };
  const persistPositions = () => {
    const pos = Object.fromEntries(nodes.map((n) => [n.id, n.position]));
    stored.current = pos;
    savePositions(posKey, pos);
  };
  const autoLayout = () => {
    const auto = flowLayout([...typeOf.keys()], relations, flowEdges);
    stored.current = auto;
    savePositions(posKey, auto);
    setNodes((ns) => ns.map((n) => ({ ...n, position: auto[n.id] ?? n.position })));
  };

  const versions = useLoad(() => api.listVersions(ir.id), [ir.id]);
  const unnamed = actions.filter((a) => !a.name.trim()).length;
  const save = useAction(async () => {
    const next: ScenarioIR = { ...ir, actions, relations };
    // Attack Flow fields are written only when the scenario already had them or the author added some.
    if (ir.conditions || conditions.length) next.conditions = conditions;
    if (ir.operators || operators.length) next.operators = operators;
    if (ir.assets || assets.length) next.assets = assets;
    if (ir.flow || startRefs.length) next.flow = { ...ir.flow, start_refs: startRefs };
    const resp = await api.saveScenario(ir.id, next, note.trim() || "流程編輯");
    setDirty(false);
    setNote("");
    await absorb(resp);
    setSavedMsg("已儲存為新版本。");
    void versions.reload(true);
  });
  const discard = () => { adoptIr(); setDirty(false); setSel(null); setHint(null); };

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
  const selCondition = sel?.type === "condition" ? conditions.find((c) => c.id === sel.id) : undefined;
  const selOperator = sel?.type === "operator" ? operators.find((o) => o.id === sel.id) : undefined;
  const selAsset = sel?.type === "asset" ? assets.find((x) => x.id === sel.id) : undefined;
  const selFlow = sel?.type === "flow" ? flowEdges.find((e) => e.id === sel.id) : undefined;
  const nameOf = useMemo(() => new Map<string, string>([
    ...actions.map((a): [string, string] => [a.id, a.name]),
    ...conditions.map((c): [string, string] => [c.id, `條件：${c.description?.trim() || "（未描述）"}`]),
    ...operators.map((o): [string, string] => [o.id, `${o.operator} 運算`]),
    ...assets.map((x): [string, string] => [x.id, `資產：${x.name?.trim() || "（未命名）"}`]),
  ]), [actions, conditions, operators, assets]);
  const flowNodes = conditions.length + operators.length + assets.length;
  /** "標記為流程起點" for the inspector; the same switch as the flag on the node toolbar. */
  const startToggle = (id: string) => (
    <label className="row" style={{ gap: 8, fontSize: 12 }}>
      <input type="checkbox" checked={startRefs.includes(id)} onChange={() => toggleStart(id)} />
      這是流程的起點之一
    </label>
  );
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
        <h3>主機</h3>
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
        <h3>流程節點</h3>
        {flowNodes === 0 && <p className="note">條件、AND/OR 運算與資產節點用來畫出分支。可從畫布上方的工具列新增。</p>}
        {conditions.map((c) => (
          <button key={c.id} className={`library-item ${sel?.type === "condition" && sel.id === c.id ? "on" : ""}`} onClick={() => setSel({ type: "condition", id: c.id })}>
            <span className="ico"><GitBranch size={14} /></span>
            <span className="name">{c.description?.trim() || "（未描述的條件）"}</span>
          </button>
        ))}
        {operators.map((o) => (
          <button key={o.id} className={`library-item ${sel?.type === "operator" && sel.id === o.id ? "on" : ""}`} onClick={() => setSel({ type: "operator", id: o.id })}>
            <span className="ico mono">{o.operator === "AND" ? "&" : "|"}</span>
            <span className="name">{o.operator} 運算</span>
          </button>
        ))}
        {assets.map((x) => (
          <button key={x.id} className={`library-item ${sel?.type === "asset" && sel.id === x.id ? "on" : ""}`} onClick={() => setSel({ type: "asset", id: x.id })}>
            <span className="ico"><Database size={14} /></span>
            <span className="name">{x.name?.trim() || "（未命名的資產）"}</span>
          </button>
        ))}
      </aside>

      <div className="canvas-col">
        <div className="canvas">
          <div className="canvas-tools" role="toolbar" aria-label="畫布工具">
            <span className="canvas-label">攻擊鏈</span>
            <span className="badge">{actions.length} 步驟</span>
            <button onClick={addAction}>＋ 新增行為</button>
            <button onClick={addCondition} title="新增條件節點：依條件成立與否分成兩條路徑"><Plus size={14} />條件</button>
            <button onClick={addOperator} title="新增 AND / OR 運算節點：把多條路徑合併成一條"><Plus size={14} />AND/OR</button>
            <button onClick={addAsset} title="新增資產節點：攻擊行為作用的對象"><Plus size={14} />資產</button>
            <button onClick={autoLayout}><LayoutGrid size={15} />自動排版</button>
            <span className="sep" />
            <span className="canvas-label muted" style={{ fontWeight: 500 }}>新連線</span>
            <button aria-pressed={newKind === "temporal"} onClick={() => setNewKind("temporal")}>時間先後</button>
            <button aria-pressed={newKind === "dependency"} onClick={() => setNewKind("dependency")}>依賴</button>
            <button aria-pressed={newKind === "flow"} title="Attack Flow 流程連線：這一步之後接到哪個節點。接到條件、運算或資產節點的線一律是流程連線。" onClick={() => setNewKind("flow")}>流程</button>
          </div>
          {typeOf.size === 0 && (
            <div className="canvas-empty">
              <h2>尚無攻擊步驟</h2>
              <span>這個情境還沒有攻擊行為。新增第一個行為，或回到情資匯入重新分析報告。</span>
              <button className="primary" onClick={addAction}><Plus size={16} />新增第一個行為</button>
            </div>
          )}
          <ReactFlow
            nodes={nodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes}
            onNodesChange={handleNodesChange} onEdgesChange={onEdgesChange} onConnect={onConnect}
            onConnectStart={() => setConnecting(true)} onConnectEnd={() => setConnecting(false)}
            className={connecting ? "connecting" : ""} connectionRadius={48}
            onNodeClick={(_, n) => setSel({ type: typeOf.get(n.id) ?? "action", id: n.id })}
            onEdgeClick={(_, e) => setSel({ type: e.id.startsWith("flow|") ? "flow" : "relation", id: e.id })}
            onPaneClick={() => setSel(null)}
            onNodeDragStop={persistPositions}
            onNodesDelete={(ns) => removeNodes(ns.map((n) => n.id))}
            onEdgesDelete={(es) => {
              const flow = es.filter((e) => e.id.startsWith("flow|")).map((e) => e.id);
              const rel = es.filter((e) => !e.id.startsWith("flow|")).map((e) => e.id);
              if (rel.length) removeRelations(rel);
              if (flow.length) removeFlowEdges(flow);
            }}
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
            <p className="dock-hint">名稱、目標主機、依據程度與 ATT&amp;CK 技術現在可直接在畫布的卡片上編輯；這裡保留較少用到的欄位。</p>
            <label className="field"><span>說明</span>
              <textarea rows={4} value={selAction.description ?? ""} onChange={(e) => patchAction(selAction.id, { description: e.target.value || undefined })} />
            </label>
            <label className="field"><span>ATT&amp;CK 戰術</span>
              <input value={selAction.attack_tactic ?? ""} placeholder="initial-access" onChange={(e) => patchAction(selAction.id, { attack_tactic: e.target.value || undefined })} />
            </label>
            {startToggle(selAction.id)}
            <div className="muted" style={{ fontSize: 12 }}>證據：{selAction.evidence_refs?.length ? selAction.evidence_refs.join("、") : "無"}</div>
            <div><button className="danger quiet" onClick={() => removeNodes([selAction.id])}><Trash2 size={15} />刪除行為（連同相關連線）</button></div>
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
        ) : selCondition ? (
          <div className="swap" key={`c:${selCondition.id}`}>
            <div className="overview-title">
              <h2>條件</h2><SourceTag source={selCondition.source} />
              <button className="quiet icon close" aria-label="關閉屬性" onClick={() => setSel(null)}><X size={16} /></button>
            </div>
            <div className="mono muted">{selCondition.id}</div>
            <p className="dock-hint">條件把流程分成兩條路徑：從右側拉線是「成立」，從下方拉線是「不成立」。這只是設計上的分支，不代表哪一條實際發生。</p>
            <label className="field"><span>條件描述</span>
              <textarea rows={3} placeholder="例如：取得網域管理員憑證" value={selCondition.description ?? ""} onChange={(e) => patchCondition(selCondition.id, { description: e.target.value })} />
            </label>
            <RefList title="成立時接到" kind="true" refs={selCondition.on_true_refs} from={selCondition.id} nameOf={nameOf} onRemove={removeFlowEdges} />
            <RefList title="不成立時接到" kind="false" refs={selCondition.on_false_refs} from={selCondition.id} nameOf={nameOf} onRemove={removeFlowEdges} />
            <EpistemicSelect value={selCondition.epistemic_status} onChange={(v) => patchCondition(selCondition.id, { epistemic_status: v })} />
            {startToggle(selCondition.id)}
            <div className="muted" style={{ fontSize: 12 }}>證據：{selCondition.evidence_refs?.length ? selCondition.evidence_refs.join("、") : "無"}</div>
            <div><button className="danger quiet" onClick={() => removeNodes([selCondition.id])}><Trash2 size={15} />刪除條件（連同相關連線）</button></div>
          </div>
        ) : selOperator ? (
          <div className="swap" key={`o:${selOperator.id}`}>
            <div className="overview-title">
              <h2>運算</h2><SourceTag source={selOperator.source} />
              <button className="quiet icon close" aria-label="關閉屬性" onClick={() => setSel(null)}><X size={16} /></button>
            </div>
            <div className="mono muted">{selOperator.id}</div>
            <div className="field"><span style={{ display: "block", marginBottom: 5, fontSize: 12 }} className="muted">運算方式</span>
              <div className="seg">
                {(["AND", "OR"] as const).map((k) => (
                  <button key={k} className={selOperator.operator === k ? "on" : ""} aria-pressed={selOperator.operator === k} onClick={() => selOperator.operator !== k && patchOperator(selOperator.id, { operator: k })}>{k}</button>
                ))}
              </div>
            </div>
            <div className="muted" style={{ fontSize: 12 }}>
              {selOperator.operator === "AND" ? "AND：所有接進來的路徑都要成立，才往下走。" : "OR：接進來的路徑任一條成立，就往下走。"}
              目前有 {flowEdges.filter((e) => e.to === selOperator.id).length} 條輸入。
            </div>
            <RefList title="輸出接到" kind="effect" refs={selOperator.effect_refs} from={selOperator.id} nameOf={nameOf} onRemove={removeFlowEdges} />
            <EpistemicSelect value={selOperator.epistemic_status} onChange={(v) => patchOperator(selOperator.id, { epistemic_status: v })} />
            {startToggle(selOperator.id)}
            <div><button className="danger quiet" onClick={() => removeNodes([selOperator.id])}><Trash2 size={15} />刪除運算（連同相關連線）</button></div>
          </div>
        ) : selAsset ? (
          <div className="swap" key={`s:${selAsset.id}`}>
            <div className="overview-title">
              <h2>資產</h2><SourceTag source={selAsset.source} />
              <button className="quiet icon close" aria-label="關閉屬性" onClick={() => setSel(null)}><X size={16} /></button>
            </div>
            <div className="mono muted">{selAsset.id}</div>
            <p className="dock-hint">資產是攻擊行為作用的對象。在「流程」連線模式下，從攻擊行為拉線到這個節點即可標示。</p>
            <label className="field"><span>名稱</span>
              <input value={selAsset.name ?? ""} placeholder="例如：網域控制站" onChange={(e) => patchAsset(selAsset.id, { name: e.target.value })} />
            </label>
            <label className="field"><span>說明</span>
              <textarea rows={3} value={selAsset.description ?? ""} onChange={(e) => patchAsset(selAsset.id, { description: e.target.value || undefined })} />
            </label>
            <EpistemicSelect value={selAsset.epistemic_status} onChange={(v) => patchAsset(selAsset.id, { epistemic_status: v })} />
            <div className="muted" style={{ fontSize: 12 }}>
              被這些行為指到：{flowEdges.filter((e) => e.to === selAsset.id).map((e) => nameOf.get(e.from) ?? e.from).join("、") || "無"}
            </div>
            <div><button className="danger quiet" onClick={() => removeNodes([selAsset.id])}><Trash2 size={15} />刪除資產（連同相關連線）</button></div>
          </div>
        ) : selFlow ? (
          <div className="swap" key={`f:${selFlow.id}`}>
            <div className="overview-title">
              <h2>流程連線</h2>
              <button className="quiet icon close" aria-label="關閉屬性" onClick={() => setSel(null)}><X size={16} /></button>
            </div>
            <div style={{ fontSize: 13, fontWeight: 600 }}>
              {nameOf.get(selFlow.from) ?? selFlow.from} <span className="muted">→</span> {nameOf.get(selFlow.to) ?? selFlow.to}
            </div>
            <div><span className={`edge-chip ${selFlow.kind === "effect" ? "flow" : `flow-${selFlow.kind}`}`}>{FLOW_LABEL[selFlow.kind]}</span></div>
            <div className="muted" style={{ fontSize: 12 }}>
              {selFlow.kind === "effect" ? `Attack Flow 流程連線：「${NODE_LABEL[typeOf.get(selFlow.from) ?? "action"]}」之後接到下一個節點。它不是依賴關係，不會在拓樸規劃中開通連線。`
                : selFlow.kind === "asset" ? "這個攻擊行為作用在這個資產上。"
                : selFlow.kind === "true" ? "條件成立時走這條路徑。" : "條件不成立時走這條路徑。"}
            </div>
            {(selFlow.kind === "true" || selFlow.kind === "false") && (
              <div><button onClick={() => flipBranch(selFlow)}><GitBranch size={15} />改接到「{selFlow.kind === "true" ? "不成立" : "成立"}」分支</button></div>
            )}
            <div><button className="danger quiet" onClick={() => removeFlowEdges([selFlow.id])}><Trash2 size={15} />刪除流程連線</button></div>
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
            {(flowNodes > 0 || flowEdges.length > 0 || startRefs.length > 0) && (
              <div className="overview-flow" data-testid="attack-flow-summary">
                <span><Flag size={12} />{startRefs.length} 起點</span>
                <span>{conditions.length} 條件</span>
                <span>{operators.length} 運算</span>
                <span>{assets.length} 資產</span>
                <span>{flowEdges.length} 流程連線</span>
              </div>
            )}
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
              <p>流程連線、條件與 AND/OR 運算依 MITRE Attack Flow 的畫法記錄「設計上有哪些分支」。條件的「成立／不成立」是兩條可能的路徑，不是任何一次執行的判定結果。</p>
              <div className="legend">
                <span><i className="line" />依賴</span>
                <span><i className="line temporal" />時間先後</span>
                <span><i className="line flow" />流程</span>
                <span><i className="line flow-true" />成立</span>
                <span><i className="line flow-false" />不成立</span>
                <span><i className="line flow-asset" />資產</span>
              </div>
            </details>
            <Link to="/missing" className="muted" style={{ fontSize: 12 }}>← 缺失補充</Link>
          </div>
        )}
      </aside>
    </div>
  );
}

/** The outgoing flow lines of one node, listed in the inspector with a remove button each. */
function RefList({ title, kind, refs, from, nameOf, onRemove }: { title: string; kind: FlowEdgeKind; refs?: string[]; from: string; nameOf: Map<string, string>; onRemove: (ids: string[]) => void }) {
  return (
    <div className="ref-list">
      <span className={`edge-chip ${kind === "effect" ? "flow" : `flow-${kind}`}`}>{title}</span>
      {(refs ?? []).length === 0 ? <span className="muted">尚未連線</span> : (refs ?? []).map((id) => (
        <div key={id} className="ref-row">
          <span className="name">{nameOf.get(id) ?? `${id}（已不存在）`}</span>
          <button className="quiet icon" aria-label="移除這條流程連線" onClick={() => onRemove([flowEdgeId(from, kind, id)])}><X size={14} /></button>
        </div>
      ))}
    </div>
  );
}

function EpistemicSelect({ value, onChange }: { value: EpistemicStatus; onChange: (v: EpistemicStatus) => void }) {
  return (
    <label className="field"><span>依據程度</span>
      <Select value={value} aria-label="依據程度" onChange={(e) => onChange(e.target.value as EpistemicStatus)}>
        {EPISTEMIC_ORDER.map((s) => <option key={s} value={s}>{EPISTEMIC[s].label}（{s}）</option>)}
      </Select>
    </label>
  );
}

export function FlowPage() {
  const { ir } = useScenario();
  // key by scenario so switching scenarios resets the local draft
  return <ScenarioGate title="攻擊流程">{ir && <Editor key={ir.id} ir={ir} />}</ScenarioGate>;
}
