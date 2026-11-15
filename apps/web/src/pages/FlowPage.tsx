import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode, type SelectHTMLAttributes, type SyntheticEvent } from "react";
import { joinList, live, t, useI18n } from "../i18n";
import { knownErrorKey } from "../lib/errors";
import ReactFlow, {
  Background, BackgroundVariant, Controls, EdgeLabelRenderer, getBezierPath, Handle, MarkerType, MiniMap, NodeToolbar, Position, useEdgesState, useNodesState,
  type Connection, type Edge, type EdgeProps, type Node, type NodeChange, type NodeProps, type ReactFlowInstance,
} from "reactflow";
import "reactflow/dist/style.css";
import type { Action, AttackFlowAsset, AttackFlowCondition, AttackFlowOperator, EpistemicStatus, Evidence, Relation, RelationKind, ScenarioIR } from "@contracts";
import { api } from "../lib/api";
import { useAction, useLoad } from "../lib/hooks";
import { layeredLayout, loadPositions, savePositions } from "../lib/layout";
import { countsInChain, findLoops, flowEdgeId, flowEdgesOf, lintFlow, relationBacked, type Finding, type FlowEdge, type FlowEdgeKind, type FlowNodeType } from "../lib/flowlint";
import { BARRIER, EDGE, GRID, LABEL, ROUTE, TEMPORAL } from "../lib/palette";
import type { RelationX } from "../lib/plan";
import { useScenario } from "../lib/scenario";
import {
  ApiNotice, CITATION, CitationBadge, claimLabel, EPISTEMIC, EPISTEMIC_ORDER, fmtTime, QuoteSnippet, ScenarioGate, SourceTag, summarizeCitations,
  type CitationSummary,
} from "../components/ui";
import { isPlanApproved } from "../lib/plan";
import { TopbarActions } from "../lib/topbar";
import { Link } from "react-router-dom";
import {
  ArrowRight, Check, ChevronDown, ChevronUp, Copy, Crosshair, Database, DoorOpen, Flag, GitBranch, KeyRound, Layers, LayoutGrid, Network, Plus, Radar,
  Save, ScanLine, Search, Server, TerminalSquare, Trash2, X,
} from "lucide-react";

const KIND_LABEL: Record<RelationKind, string> = live(() => ({ temporal: t("fl.k.temporal"), dependency: t("fl.k.dependency") }));
// Attack Flow edges. Colours mirror theme.css tokens (--route / --ok / --warn / --text-dim): SVG markers cannot read CSS variables.
const FLOW_COLOR: Record<FlowEdgeKind, string> = { effect: ROUTE, true: "#7ee2a8", false: "#f1c16c", asset: LABEL };
const FLOW_LABEL: Record<FlowEdgeKind, string> = live(() => ({ effect: t("fl.f.effect"), true: t("fl.f.true"), false: t("fl.f.false"), asset: t("fl.f.asset") }));
/** A relation the model asserted without a quote found in the source. A warning hue of its own — not the grey of
 *  "order only", not the amber of a "不成立" branch, not the red of a loop — so it is told apart by colour, not dash spacing. */
const UNCITED = "#ff9a3d";
const NODE_LABEL: Record<FlowNodeType, string> = live(() => ({ action: t("fl.n.action"), condition: t("fl.n.condition"), operator: t("fl.n.operator"), asset: t("fl.n.asset") }));
/** What a new line means. temporal/dependency are the editor's own relations; flow is an Attack Flow edge. */
type ConnectKind = RelationKind | "flow";

/** Shared by every node type: start marker and the per-node commands. */
/** looped: the node sits on a cycle of lines, so no step in that cycle can come first. */
interface NodeCommon { fresh: boolean; start: boolean; looped: boolean; issues: number; onDelete: () => void; onCheck: () => void; onToggleStart: () => void }
interface ActionNodeData extends NodeCommon {
  action: Action; index: number; host?: string; requires: number; cite: CitationSummary;
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
          <button aria-label={t("fl.dupStep")} title={t("fl.dupTitle")} onClick={data.onDuplicate}><Copy size={15} /></button>
          <button aria-label={t("fl.delStep")} title={t("fl.delTitle")} onClick={data.onDelete}><Trash2 size={15} /></button>
          <button aria-label={data.start ? t("fl.unstart") : t("fl.start")} aria-pressed={data.start} title={data.start ? t("fl.unstart") : t("fl.start")} onClick={data.onToggleStart}><Flag size={15} /></button>
          <button aria-label={t("fl.checkStep")} title={t("fl.check")} onClick={data.onCheck}><ScanLine size={15} /></button>
        </div>
      </NodeToolbar>
      {/* Handles sit outside the article so its clipped corner does not cut them; only the article ever animates. */}
      <Handle type="target" position={Position.Left} />
      <article className={`gnode ${selected ? "editing" : ""} ${data.fresh ? "fresh" : ""} ${data.issues ? "has-issues" : ""} ${data.start ? "start" : ""}`}>
        <div className="node-top">
          <span className="step-icon"><Icon size={17} /></span>
          <span className="node-number">STEP {String(data.index + 1).padStart(2, "0")}</span>
          {data.start && <span className="start-flag"><Flag size={11} />{t("fl.startFlag")}</span>}
          {data.looped && <span className="badge insufficient" title={t("fl.loop.hint")}>{t("fl.loop")}</span>}
          {a.attack_technique && <span className="badge technique">{a.attack_technique}</span>}
        </div>
        {selected ? (
          // Edit the core fields right here. Everything carries nodrag/nopan; description, tactic and evidence stay in the dock.
          <div className="node-edit nodrag nopan" onPointerDown={stop} onClick={stop} onKeyDown={stop}>
            <input className="node-name-input nodrag nopan" aria-label={t("fl.stepName")} placeholder={t("fl.stepNamePh")}
              value={a.name} onChange={(e) => data.onPatch({ name: e.target.value })} />
            <label className="node-field"><span>{t("fl.targetHost")}</span>
              {data.hosts.length ? (
                <Select nodeSafe aria-label={t("fl.targetHost")} value={a.target_host_ref ?? ""}
                  onChange={(e) => data.onPatch({ target_host_ref: e.target.value || undefined })}>
                  <option value="">{t("fl.unset")}</option>
                  {a.target_host_ref && !data.hosts.some((h) => h.id === a.target_host_ref) && <option value={a.target_host_ref}>{a.target_host_ref}</option>}
                  {data.hosts.map((h) => <option key={h.id} value={h.id}>{h.role}（{h.id}）</option>)}
                </Select>
              ) : (
                <input className="mono nodrag nopan" aria-label={t("fl.targetHost")} placeholder={t("fl.hostPh")} value={a.target_host_ref ?? ""}
                  onChange={(e) => data.onPatch({ target_host_ref: e.target.value || undefined })} />
              )}
            </label>
            <div className="node-edit-row">
              <label className="node-field"><span>{t("fl.basis")}</span>
                <Select nodeSafe aria-label={t("fl.basis")} value={a.epistemic_status}
                  onChange={(e) => data.onPatch({ epistemic_status: e.target.value as EpistemicStatus })}>
                  {EPISTEMIC_ORDER.map((s) => <option key={s} value={s}>{EPISTEMIC[s].label}</option>)}
                </Select>
              </label>
              <label className="node-field"><span>{t("fl.technique")}</span>
                <input className="mono nodrag nopan" aria-label={t("fl.technique")} placeholder="T1190" value={a.attack_technique ?? ""}
                  onChange={(e) => data.onPatch({ attack_technique: e.target.value || undefined })} />
              </label>
            </div>
          </div>
        ) : (
          <>
            <strong>{a.name || t("fl.unnamed")}</strong>
            <div className="node-target"><ArrowRight size={13} /><span>{data.host ?? t("fl.noTarget")}</span></div>
          </>
        )}
        {/* Quote quality is its own line, separate from the claim status below: a step can be "原文" and still have a quote that did not match. */}
        {(data.cite.state === "some" || data.cite.state === "none") && (
          <div className="node-target" title={CITATION[data.cite.state].hint} style={{ color: data.cite.state === "none" ? "var(--err)" : "var(--warn)", paddingTop: 0 }}>
            <span aria-hidden>{data.cite.state === "none" ? "✗" : "～"}</span>
            <span>{CITATION[data.cite.state].label}（{data.cite.bad}/{data.cite.total}）</span>
          </div>
        )}
        <div className="node-bottom">
          <span><GitBranch size={12} />{data.requires ? t("fl.requires", { n: data.requires }) : t("fl.noRequires")}</span>
          {/* What the report supports, or a design problem — never a run result. */}
          <span className={data.issues ? "issue-text" : ""}>{data.issues ? t("fl.issues", { n: data.issues }) : claimLabel(a.epistemic_status, a.source)}{a.source === "user" ? t("fl.edited") : ""}</span>
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
        <button aria-label={t("fl.delWhat", { what })} title={t("fl.delTitle")} onClick={data.onDelete}><Trash2 size={15} /></button>
        {canStart && <button aria-label={data.start ? t("fl.unstart") : t("fl.start")} aria-pressed={data.start} title={data.start ? t("fl.unstart") : t("fl.start")} onClick={data.onToggleStart}><Flag size={15} /></button>}
        <button aria-label={t("fl.checkWhat", { what })} title={t("fl.check")} onClick={data.onCheck}><ScanLine size={15} /></button>
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
      <FlowNodeTools data={data} selected={selected} what={t("fl.n.condition")} />
      <Handle type="target" position={Position.Left} />
      <div className={fnodeClass("cond", data)}>
        <svg className="shape" viewBox="0 0 220 132" aria-hidden><polygon points="110,1 219,66 110,131 1,66" /></svg>
        {data.start && <span className="start-flag"><Flag size={11} />{t("fl.startFlag")}</span>}
        <div className="body">
          <span className="kind">{t("fl.n.condition")}{data.looped && <span style={{ color: "var(--err)" }}> · {t("fl.loop")}</span>}</span>
          <span className="text" title={c.description}>{c.description?.trim() || t("fl.noDesc")}</span>
        </div>
        <span className="branch yes">{t("fl.f.true")}</span>
        <span className="branch no">{t("fl.f.false")}</span>
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
      <FlowNodeTools data={data} selected={selected} what={t("fl.n.operator")}>
        <button aria-label={t("fl.toOp", { op: data.op.operator === "AND" ? "OR" : "AND" })} title={t("fl.toOp", { op: data.op.operator === "AND" ? "OR" : "AND" })} onClick={data.onToggleOp} className="op-swap">{data.op.operator === "AND" ? "OR" : "AND"}</button>
      </FlowNodeTools>
      <Handle type="target" position={Position.Left} />
      <div className={fnodeClass("op", data)} title={data.op.operator === "AND" ? t("fl.and.hint") : t("fl.or.hint")}>
        {data.start && <span className="start-flag"><Flag size={11} />{t("fl.startFlag")}</span>}
        <strong>{data.op.operator}</strong>
        <small>{t("fl.inputs", { n: data.inputs })}{data.looped && <span style={{ color: "var(--err)" }}> · {t("fl.loop")}</span>}</small>
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
      <FlowNodeTools data={data} selected={selected} what={t("fl.n.asset")} canStart={false} />
      <Handle type="target" position={Position.Left} />
      <div className={fnodeClass("asset", data)}>
        <svg className="shape" viewBox="0 0 180 92" aria-hidden>
          <path d="M1,15 V77 A89,14 0 0 0 179,77 V15" />
          <ellipse cx="90" cy="15" rx="89" ry="14" />
        </svg>
        <div className="body">
          <span className="kind"><Database size={11} />{t("fl.n.asset")}</span>
          <span className="text" title={s.description}>{s.name?.trim() || t("fl.unnamed")}</span>
        </div>
      </div>
    </>
  );
}
const nodeTypes = { action: ActionNode, condition: ConditionNode, operator: OperatorNode, asset: AssetNode };

interface RelEdgeData { label: string; tone: "route" | "hold" | "temporal" | "barrier" | "flow" | "flow-true" | "flow-false" | "flow-asset"; draw: boolean; color?: string }

/** A relation line. A new dependency is drawn once (pathLength=1 + dashoffset) and is static from then on;
 *  nothing here ever loops, so a line can never read as traffic or as an attack in progress. */
function RelEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, style, markerEnd, data }: EdgeProps<RelEdgeData>) {
  const [d, lx, ly] = getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition });
  return (
    <>
      <path id={id} d={d} fill="none" className="react-flow__edge-path" style={style} markerEnd={markerEnd} pathLength={data?.draw ? 1 : undefined} />
      {/* Invisible touch stroke. Phones: 56 units, so it stays at least 44 px at the 0.8 zoom floor. */}
      <path d={d} fill="none" strokeOpacity={0} strokeWidth={isPhone() ? 56 : 22} className="react-flow__edge-interaction" />
      {data?.label && (
        <EdgeLabelRenderer>
          <div className={`edge-label ${data.tone}`} style={{ transform: `translate(-50%, -50%) translate(${lx}px, ${ly}px)`, color: data.color }}>{data.label}</div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}
const edgeTypes = { rel: RelEdge };

/** counted: the relation is part of the chain (see countsInChain). An uncounted one — asserted without a quote that
 *  matches the source — is drawn as a dotted line in the UNCITED warning colour and labelled "無引文". Dashes alone mean
 *  "order only" (temporal). looped: it lies on a cycle, drawn in the barrier colour. */
function toEdge(r: Relation, selected: boolean, fresh: boolean, counted: boolean, looped: boolean): Edge<RelEdgeData> {
  const dep = r.kind === "dependency";
  const confirmed = dep && (r as RelationX).confirmed === true;
  const color = looped ? BARRIER : !counted ? UNCITED : dep ? EDGE : TEMPORAL;
  // Temporal lines normally carry no label: the dashed stroke already says "order only" (see legend).
  const label = [dep ? t("fl.k.dependency") : null, looped ? t("fl.loop") : null, !counted ? t("fl.uncited") : dep && !confirmed ? t("fl.unconfirmed") : null].filter(Boolean).join(" · ");
  return {
    id: r.id, type: "rel", source: r.from_action, target: r.to_action, selected,
    // Dashed temporal lines cannot use the dash-offset draw, so a new one simply fades in.
    className: fresh ? (dep && counted ? "fresh" : "fresh-fade") : undefined,
    data: {
      label, tone: looped ? "barrier" : dep && confirmed ? "route" : dep || !counted ? "hold" : "temporal", draw: fresh && dep && counted,
      color: !counted && !looped ? UNCITED : undefined,
    },
    style: {
      stroke: color, strokeWidth: !counted ? 2 : 1.5, strokeLinecap: !counted ? "round" : undefined,
      strokeDasharray: !counted ? "1 7" : dep ? undefined : "5 5",
      opacity: counted && dep && !confirmed ? 0.55 : 1,
    },
    markerEnd: { type: dep ? MarkerType.ArrowClosed : MarkerType.Arrow, color, width: 18, height: 18 },
  };
}

/** An Attack Flow edge. Brighter and heavier than a dependency, always labelled, so the two kinds of line never read alike. */
function toFlowEdge(e: FlowEdge, selected: boolean, fresh: boolean, looped: boolean): Edge<RelEdgeData> {
  const color = looped ? BARRIER : FLOW_COLOR[e.kind];
  const asset = e.kind === "asset";
  return {
    id: e.id, type: "rel", source: e.from, target: e.to, selected,
    sourceHandle: e.kind === "true" || e.kind === "false" ? e.kind : undefined,
    className: fresh ? (asset ? "fresh-fade" : "fresh") : undefined,
    data: { label: looped ? `${FLOW_LABEL[e.kind]} · ${t("fl.loop")}` : FLOW_LABEL[e.kind], tone: looped ? "barrier" : e.kind === "effect" ? "flow" : (`flow-${e.kind}` as RelEdgeData["tone"]), draw: fresh && !asset },
    style: { stroke: color, strokeWidth: asset ? 1.5 : 2, strokeDasharray: asset ? "2 5" : undefined },
    markerEnd: { type: MarkerType.ArrowClosed, color, width: 16, height: 16 },
  };
}

/** Never fit below this: smaller and the cards are unreadable dots. A graph that does not fit is panned/scrolled instead. */
const MIN_FIT = 0.5;
const FIT = { padding: 0.1, maxZoom: 1, minZoom: MIN_FIT };
const SIDE = 32;
/** Phones: a higher floor, so card text stays readable. The rest of the graph is reached by dragging. */
const isPhone = () => typeof window !== "undefined" && window.matchMedia("(max-width: 760px)").matches;
const minFit = () => (isPhone() ? 0.8 : MIN_FIT);
const side = () => (isPhone() ? 12 : SIDE);
/** fitView options with the zoom floor for this screen (React Flow's own fit is used before nodes are measured). */
const fitOpts = () => ({ ...FIT, minZoom: minFit() });
/** The part of the canvas nothing floats over: below the toolbar (which wraps, so it is measured), above the
 *  legend / status line and the minimap. */
function freeArea(pane: HTMLElement) {
  const box = pane.getBoundingClientRect();
  let top = 84, bottom = 64;
  pane.querySelectorAll<HTMLElement>("[data-fit-inset]").forEach((el) => {
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) return;
    if (el.dataset.fitInset === "top") top = Math.max(top, r.bottom - box.top + 14);
    else bottom = Math.max(bottom, box.bottom - r.top + 14);
  });
  const sd = side();
  return { top, bottom, left: sd, right: sd, w: pane.clientWidth - sd * 2, h: pane.clientHeight - top - bottom };
}
/** Fit every node into the free part of the canvas, but never below MIN_FIT. What does not fit at that zoom starts
 *  at the top-left (the first step) and the rest is reached by scrolling or dragging the canvas. */
function fitAll(inst: ReactFlowInstance, pane: HTMLElement | null) {
  const ns = inst.getNodes().filter((n) => n.width && n.height);
  if (!pane || ns.length === 0) { inst.fitView(fitOpts()); return; }
  const minX = Math.min(...ns.map((n) => n.position.x)), minY = Math.min(...ns.map((n) => n.position.y));
  const w = Math.max(...ns.map((n) => n.position.x + n.width!)) - minX, h = Math.max(...ns.map((n) => n.position.y + n.height!)) - minY;
  const free = freeArea(pane);
  if (free.w <= 0 || free.h <= 0 || w <= 0 || h <= 0) { inst.fitView(fitOpts()); return; }
  const zoom = Math.max(minFit(), Math.min(1, free.w / w, free.h / h));
  inst.setViewport({
    x: free.left + Math.max(0, (free.w - w * zoom) / 2) - minX * zoom,
    y: free.top + Math.max(0, (free.h - h * zoom) / 2) - minY * zoom,
    zoom,
  });
}
const COL_W = 310;
const CARD_W = 276;
const GAP_Y = 44;      // between two cards stacked in one column
const BAND_GAP = 96;   // between two folded rows of columns
const STAGGER = 56;
const MAX_STACK = 6;   // more than this in one layer (e.g. many unlinked nodes) spills into the next column
/** Height to assume for a node React Flow has not measured yet. Deliberately generous: a long name wraps to 3–4 lines. */
const EST_H: Record<FlowNodeType, number> = { action: 250, condition: 150, operator: 60, asset: 96 };
/** How many columns fit across the canvas at MIN_FIT, so folding the chain never forces a zoom below it. */
function wrapFor(pane: HTMLElement | null) {
  if (!pane || pane.clientWidth <= 0) return 5;
  const cols = Math.floor(((pane.clientWidth - SIDE * 2) / MIN_FIT - CARD_W) / COL_W) + 1;
  return Math.max(3, Math.min(8, Number.isFinite(cols) ? cols : 5));
}
/** Left-to-right by dependency/order depth, with alternate columns dropped a little: neighbours never sit on the
 *  same line, which leaves room for the relation label between them.
 *  Cards in one column are stacked by their real height (heightOf), so a tall card never covers the one below it.
 *  A long chain is folded into bands of `wrap` columns; each band is only as tall as its own tallest column, so one
 *  wide fan-out no longer pushes every band apart. */
function flowLayout(ids: string[], relations: Relation[], flowEdges: FlowEdge[], heightOf: (id: string) => number, wrap = 5) {
  const all = [...relations.map((r) => ({ from: r.from_action, to: r.to_action })), ...flowEdges.map((e) => ({ from: e.from, to: e.to }))];
  // Drop the lines that close a cycle before layering; otherwise every node of the cycle is parked in one far column
  // and the chain cannot be read left to right.
  const next = new Map<string, number[]>();
  all.forEach((l, i) => next.set(l.from, [...(next.get(l.from) ?? []), i]));
  const state = new Map<string, 1 | 2>();
  const back = new Set<number>();
  const visit = (n: string) => {
    state.set(n, 1);
    for (const i of next.get(n) ?? []) {
      const m = all[i].to;
      if (state.get(m) === 1) back.add(i);
      else if (!state.has(m)) visit(m);
    }
    state.set(n, 2);
  };
  ids.forEach((n) => { if (!state.has(n)) visit(n); });
  // Unit spacing: x is the layer (depth), list order inside a layer is the order of `ids`.
  const layer = layeredLayout(ids, all.filter((_, i) => !back.has(i)), 1, 1);
  const byDepth = new Map<number, string[]>();
  for (const id of ids) {
    const d = Math.round(layer[id]?.x ?? 0);
    byDepth.set(d, [...(byDepth.get(d) ?? []), id]);
  }
  const cols: string[][] = [];
  for (const d of [...byDepth.keys()].sort((a, b) => a - b)) {
    const list = byDepth.get(d)!;
    for (let i = 0; i < list.length; i += MAX_STACK) cols.push(list.slice(i, i + MAX_STACK));
  }
  const per = Math.max(1, Math.floor(wrap));
  const pos: Record<string, { x: number; y: number }> = {};
  let top = 0;
  for (let b = 0; b * per < cols.length; b++) {
    let bandH = 0;
    cols.slice(b * per, (b + 1) * per).forEach((col, c) => {
      let y = c % 2 === 1 ? STAGGER : 0;
      for (const id of col) {
        pos[id] = { x: c * COL_W, y: top + y };
        const h = heightOf(id);
        y += (Number.isFinite(h) && h > 0 ? h : EST_H.action) + GAP_Y;
      }
      bandH = Math.max(bandH, y - GAP_Y);
    });
    top += bandH + BAND_GAP;
  }
  return pos;
}

/** Always on the canvas: what each kind of line means. Colours are the ones the edges are drawn with. */
const LEGEND: { label: string; hint: string; line: string }[] = [
  { label: t("fl.k.dependency"), hint: t("fl.lg.dep"), line: `2px solid ${EDGE}` },
  { label: t("fl.k.temporal"), hint: t("fl.lg.temporal"), line: `2px dashed ${TEMPORAL}` },
  { label: t("fl.uncited"), hint: t("fl.lg.uncited"), line: `2px dotted ${UNCITED}` },
  { label: t("fl.loop"), hint: t("fl.lg.loop"), line: `2px solid ${BARRIER}` },
  { label: t("fl.f.effect"), hint: t("fl.lg.flow"), line: `2px solid ${FLOW_COLOR.effect}` },
  { label: t("fl.f.true"), hint: t("fl.lg.true"), line: `2px solid ${FLOW_COLOR.true}` },
  { label: t("fl.f.false"), hint: t("fl.lg.false"), line: `2px solid ${FLOW_COLOR.false}` },
  { label: t("fl.f.asset"), hint: t("fl.lg.asset"), line: `2px dotted ${FLOW_COLOR.asset}` },
];
function CanvasLegend() {
  return (
    <div className="legend" data-testid="flow-legend" data-fit-inset="bottom" role="group" aria-label={t("fl.legend")}
      style={{
        position: "absolute", zIndex: 5, left: 68, bottom: 60, maxWidth: "calc(100% - 68px - 176px)", gap: "4px 14px", padding: "6px 10px",
        background: "var(--bg-elev)", border: "1px solid var(--border)", borderRadius: "var(--radius)",
      }}>
      <strong style={{ fontWeight: 700 }}>{t("fl.legend")}</strong>
      {LEGEND.map((l) => (
        <span key={l.label} title={l.hint} style={{ whiteSpace: "nowrap" }}>
          <i className="line" style={{ borderTop: l.line }} />{l.label}
        </span>
      ))}
    </div>
  );
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
  // v2: positions saved before the layout fix were produced by the broken auto-layout (overlaps, huge row gaps).
  const posKey = `cr.flowpos.v2.${ir.id}`;
  const stored = useRef(loadPositions(posKey));
  // Nothing saved for this scenario: the whole graph is auto-placed, and re-placed once the real card heights are known.
  const autoPlaced = useRef(Object.keys(stored.current ?? {}).length === 0);

  const [nodes, setNodes, onNodesChange] = useNodesState<AnyNodeData>([]);
  // Objects created in this editing session: only these get an entrance, so loading a scenario never animates.
  const fresh = useRef(new Set<string>());
  const [consoleOpen, setConsoleOpen] = useState(false);
  const consoleSeen = useRef(false);
  const { locale } = useI18n();
  const hostRole = useMemo(() => new Map((ir.hosts ?? []).map((h) => [h.id, h.role])), [ir.hosts]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const evById = useMemo(() => new Map((ir.evidence ?? []).map((e): [string, Evidence] => [e.id, e])), [ir.evidence]);
  const extras = useMemo(() => ({ conditions, operators, assets, startRefs, evidence: ir.evidence ?? [] }), [conditions, operators, assets, startRefs, ir.evidence]);
  const flowEdges = useMemo(() => flowEdgesOf(actions, extras), [actions, extras]);
  // Findings and names carry translated text, so they are rebuilt when the language changes.
  const findings = useMemo(() => lintFlow(actions, relations, extras), [actions, relations, extras, locale]); // eslint-disable-line react-hooks/exhaustive-deps
  const typeOf = useMemo(() => {
    const m = new Map<string, FlowNodeType>();
    actions.forEach((a) => m.set(a.id, "action")); conditions.forEach((c) => m.set(c.id, "condition"));
    operators.forEach((o) => m.set(o.id, "operator")); assets.forEach((x) => m.set(x.id, "asset"));
    return m;
  }, [actions, conditions, operators, assets]);

  // Lines that lie on a cycle, and the nodes they pass through — marked on the canvas, reported by the design check.
  const loops = useMemo(() => {
    const drawable = flowEdges.filter((e) => typeOf.has(e.from) && typeOf.has(e.to));
    const found = findLoops([...typeOf.keys()], relations, drawable);
    return { nodes: new Set(found.flatMap((l) => l.nodes)), edges: new Set(found.flatMap((l) => [...l.relationIds, ...l.flowEdgeIds])) };
  }, [typeOf, relations, flowEdges]);
  const inChain = (r: Relation) => countsInChain(r, evById);
  /** Auto-layout with the heights React Flow measured; a node not measured yet gets a generous estimate. */
  const layoutWith = (ns: Node<AnyNodeData>[]) => {
    const h = new Map(ns.map((n) => [n.id, n.height]));
    return flowLayout([...typeOf.keys()], relations, flowEdges, (id) => h.get(id) || EST_H[typeOf.get(id) ?? "action"], wrapFor(paneRef.current));
  };

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
      const auto = layoutWith(prev);
      const common = (type: FlowNodeType, id: string): NodeCommon => ({
        fresh: fresh.current.has(id), start: startRefs.includes(id), looped: loops.nodes.has(id),
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
          requires: relations.filter((r) => r.kind === "dependency" && r.to_action === a.id && inChain(r)).length,
          cite: summarizeCitations(a.evidence_refs, evById),
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
  }, [actions, relations, conditions, operators, assets, startRefs, flowEdges, typeOf, sel, hostRole, findings, loops, evById]); // eslint-disable-line
  useEffect(() => {
    setEdges([
      // An imported Attack Flow repeats each flow edge as a relation between the same two nodes; the flow edge is the one drawn.
      ...relations.filter((r) => !flowEdges.some((e) => e.from === r.from_action && e.to === r.to_action))
        .map((r) => toEdge(r, sel?.type === "relation" && sel.id === r.id, fresh.current.has(r.id), inChain(r), loops.edges.has(r.id))),
      // A ref to a node that no longer exists cannot be drawn; the design check reports it instead.
      ...flowEdges.filter((e) => typeOf.has(e.from) && typeOf.has(e.to))
        .map((e) => toFlowEdge(e, sel?.type === "flow" && sel.id === e.id, fresh.current.has(e.id), loops.edges.has(e.id))),
    ]);
  }, [relations, flowEdges, typeOf, sel, loops, evById, locale]); // eslint-disable-line

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
    const maxY = nodes.reduce((m, n) => Math.max(m, n.position.y + (n.height ?? EST_H[typeOf.get(n.id) ?? "action"])), -gap);
    stored.current[id] = { x: 0, y: maxY + gap };
    fresh.current.add(id);
  };
  // New Attack Flow nodes start as the author's own, unverified design choices — same as a new action.
  const addCondition = () => {
    const id = newId("cond", new Set(typeOf.keys()));
    stage(id, GAP_Y);
    setConditions((xs) => [...xs, { id, description: "", on_true_refs: [], on_false_refs: [], epistemic_status: "inferred", source: "user", evidence_refs: [] }]);
    setSel({ type: "condition", id });
    touch();
  };
  const addOperator = () => {
    const id = newId("op", new Set(typeOf.keys()));
    stage(id, GAP_Y);
    setOperators((xs) => [...xs, { id, operator: "AND", effect_refs: [], epistemic_status: "inferred", source: "user", evidence_refs: [] }]);
    setSel({ type: "operator", id });
    touch();
  };
  const addAsset = () => {
    const id = newId("asset", new Set(typeOf.keys()));
    stage(id, GAP_Y);
    setAssets((xs) => [...xs, { id, name: t("fl.newAsset"), epistemic_status: "inferred", source: "user", evidence_refs: [] }]);
    setSel({ type: "asset", id });
    touch();
  };
  const addAction = () => {
    const id = newId("act", new Set(typeOf.keys()));
    stage(id, GAP_Y);
    setActions((xs) => [...xs, { id, name: t("fl.newStep"), epistemic_status: "inferred", source: "user", evidence_refs: [] }]);
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
    setActions((xs) => [...xs, { ...src, id, name: t("fl.copySuffix", { name: src.name }), source: "user", effect_refs: undefined, asset_refs: undefined }]);
    setSel({ type: "action", id });
    touch();
  };
  const onConnect = useCallback((c: Connection) => {
    if (!c.source || !c.target) return;
    const from = typeOf.get(c.source), to = typeOf.get(c.target);
    if (!from || !to) return;
    if (c.source === c.target) { setHint(from === "action" ? t("fl.h.selfStep") : t("fl.h.self")); return; }
    // temporal / dependency exist only between two actions. Any line touching a condition, operator or asset is a flow edge.
    if (newKind !== "flow" && from === "action" && to === "action") {
      if (relations.some((r) => r.from_action === c.source && r.to_action === c.target && r.kind === newKind)) {
        setHint(t("fl.h.dupRel", { kind: KIND_LABEL[newKind] }));
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
    if (to === "asset" && from !== "action") { setHint(t("fl.h.assetOnly")); return; }
    const kind: FlowEdgeKind = to === "asset" ? "asset" : from === "condition" ? (c.sourceHandle === "false" ? "false" : "true") : "effect";
    const id = flowEdgeId(c.source, kind, c.target);
    if (flowEdges.some((e) => e.id === id)) { setHint(t("fl.h.dupFlow")); return; }
    if (from === "condition" && flowEdges.some((e) => e.from === c.source && e.to === c.target)) {
      setHint(t("fl.h.bothBranches"));
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
  // Fit the whole graph once, after React Flow has measured the cards: fitting earlier uses guessed sizes and can leave
  // a long chain half outside the window. Later edits never move the viewport on their own.
  const rf = useRef<ReactFlowInstance | null>(null);
  const paneRef = useRef<HTMLDivElement>(null);
  const fitted = useRef(false);
  const measured = nodes.length > 0 && nodes.every((n) => n.width && n.height);
  useEffect(() => {
    if (!measured || fitted.current || !rf.current) return;
    fitted.current = true;
    const inst = rf.current;
    // The first placement used estimated heights. Now that the cards are measured, place them again so none overlap.
    if (autoPlaced.current) {
      const auto = layoutWith(nodes);
      setNodes((ns) => ns.map((n) => ({ ...n, position: auto[n.id] ?? n.position })));
    }
    requestAnimationFrame(() => fitAll(inst, paneRef.current));
  }, [measured]);
  const persistPositions = () => {
    const pos = Object.fromEntries(nodes.map((n) => [n.id, n.position]));
    stored.current = pos;
    savePositions(posKey, pos);
  };
  const autoLayout = () => {
    const auto = layoutWith(nodes);
    stored.current = auto;
    savePositions(posKey, auto);
    setNodes((ns) => ns.map((n) => ({ ...n, position: auto[n.id] ?? n.position })));
    requestAnimationFrame(() => { if (rf.current) fitAll(rf.current, paneRef.current); });
  };

  // On a short window, opening or closing the design-check console changes the canvas height enough that the
  // legend / zoom controls would sit on top of the nodes. Refit once the console has finished resizing.
  useEffect(() => {
    if (!consoleSeen.current) { consoleSeen.current = true; return; }
    if (window.innerHeight > 800) return;
    const t = setTimeout(() => { if (rf.current) fitAll(rf.current, paneRef.current); }, 320);
    return () => clearTimeout(t);
  }, [consoleOpen]);

  const versions = useLoad(() => api.listVersions(ir.id), [ir.id]);
  const unnamed = actions.filter((a) => !a.name.trim()).length;
  const save = useAction(async () => {
    const next: ScenarioIR = { ...ir, actions, relations };
    // Attack Flow fields are written only when the scenario already had them or the author added some.
    if (ir.conditions || conditions.length) next.conditions = conditions;
    if (ir.operators || operators.length) next.operators = operators;
    if (ir.assets || assets.length) next.assets = assets;
    if (ir.flow || startRefs.length) next.flow = { ...ir.flow, start_refs: startRefs };
    const resp = await api.saveScenario(ir.id, next, note.trim() || t("fl.defaultNote"));
    setDirty(false);
    setNote("");
    await absorb(resp);
    setSavedMsg(t("fl.saved"));
    void versions.reload(true);
  });
  const discard = () => { adoptIr(); setDirty(false); setSel(null); setHint(null); };

  const deps = relations.filter((r) => r.kind === "dependency");
  const unconfirmed = deps.filter((r) => (r as RelationX).confirmed !== true);
  // Confirming is the analyst's judgement on the link, not a rewrite of it, so the relation keeps its original source.
  const setConfirmed = (which: (r: Relation) => boolean, confirmed: boolean) => {
    setRelations((xs) => xs.map((r) => (which(r) ? ({ ...r, confirmed } as Relation) : r)));
    touch();
  };
  const confirmAllDeps = () => setConfirmed((r) => r.kind === "dependency", true);
  // Order-only relations the model asserted without a quote that matches the source: drawn dotted, left out of the chain.
  const temporal = relations.filter((r) => r.kind !== "dependency");
  const uncountedTemporal = temporal.filter((r) => !inChain(r));

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
    ...conditions.map((c): [string, string] => [c.id, t("fl.nameCond", { text: c.description?.trim() || t("fl.noDesc") })]),
    ...operators.map((o): [string, string] => [o.id, t("fl.nameOp", { op: o.operator })]),
    ...assets.map((x): [string, string] => [x.id, t("fl.nameAsset", { name: x.name?.trim() || t("fl.unnamed") })]),
  ]), [actions, conditions, operators, assets, locale]); // eslint-disable-line react-hooks/exhaustive-deps
  const flowNodes = conditions.length + operators.length + assets.length;
  /** "標記為流程起點" for the inspector; the same switch as the flag on the node toolbar. */
  const startToggle = (id: string) => (
    <label className="row" style={{ gap: 8, fontSize: 13 }}>
      <input type="checkbox" checked={startRefs.includes(id)} onChange={() => toggleStart(id)} />
      {t("fl.isStart")}
    </label>
  );
  const versionRows = Array.isArray(versions.data) ? versions.data : [];

  const approved = isPlanApproved(ir.environment_plan);
  // "通過" means nothing is left to deal with: no problems AND nothing pending.
  const designOk = errors === 0 && warns === 0;
  const hosts = ir.hosts ?? [];
  const svcOf = (hid: string) => (ir.services ?? []).filter((x: any) => x.host_ref === hid);

  return (
    <div className="workspace">
      <TopbarActions>
        {dirty && <span className="save-state">{t("fl.unsaved")}</span>}
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder={t("fl.notePh")} aria-label={t("fl.note")} disabled={save.busy} />
        <button className="primary" disabled={!dirty || save.busy || unnamed > 0} title={unnamed > 0 ? t("fl.needNames") : undefined} onClick={() => save.run()}>
          {save.busy ? <span className="spinner" /> : <Save size={15} />}<span className="btn-label">{save.busy ? t("fl.saving") : t("fl.save")}</span>
        </button>
        <button disabled={!dirty || save.busy} onClick={discard}>{t("fl.discard")}</button>
        <button onClick={() => setConsoleOpen((o) => !o)} aria-pressed={consoleOpen}><ScanLine size={15} /><span className="btn-label">{t("fl.check")}</span></button>
      </TopbarActions>

      <aside className="library" aria-label={t("fl.parts")}>
        <h2>{t("fl.parts")}</h2>
        <h3>{t("fl.hosts")}</h3>
        {hosts.length === 0 ? (
          <p className="note">{t("fl.noHosts")}</p>
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
        <h3>{t("fl.steps")}</h3>
        {actions.map((a, i) => (
          <button key={a.id} className={`library-item ${sel?.type === "action" && sel.id === a.id ? "on" : ""}`} onClick={() => setSel({ type: "action", id: a.id })}>
            <span className="ico">{i + 1}</span>
            <span className="name">{a.name || t("fl.unnamed")}</span>
          </button>
        ))}
        <button className="library-item" onClick={addAction} aria-label={t("fl.addStepAria")}>
          <span className="ico"><Plus size={14} /></span><span className="name muted">{t("fl.addStep")}</span>
        </button>
        <h3>{t("fl.flowNodes")}</h3>
        {flowNodes === 0 && <p className="note">{t("fl.flowNodesNote")}</p>}
        {conditions.map((c) => (
          <button key={c.id} className={`library-item ${sel?.type === "condition" && sel.id === c.id ? "on" : ""}`} onClick={() => setSel({ type: "condition", id: c.id })}>
            <span className="ico"><GitBranch size={14} /></span>
            <span className="name">{c.description?.trim() || t("fl.condUnnamed")}</span>
          </button>
        ))}
        {operators.map((o) => (
          <button key={o.id} className={`library-item ${sel?.type === "operator" && sel.id === o.id ? "on" : ""}`} onClick={() => setSel({ type: "operator", id: o.id })}>
            <span className="ico mono">{o.operator === "AND" ? "&" : "|"}</span>
            <span className="name">{t("fl.nameOp", { op: o.operator })}</span>
          </button>
        ))}
        {assets.map((x) => (
          <button key={x.id} className={`library-item ${sel?.type === "asset" && sel.id === x.id ? "on" : ""}`} onClick={() => setSel({ type: "asset", id: x.id })}>
            <span className="ico"><Database size={14} /></span>
            <span className="name">{x.name?.trim() || t("fl.assetUnnamed")}</span>
          </button>
        ))}
      </aside>

      <div className="canvas-col">
        <div className="canvas" ref={paneRef}>
          <div className="canvas-tools" role="toolbar" aria-label={t("fl.tools")} data-fit-inset="top">
            <span className="canvas-label">{t("fl.chain")}</span>
            <span className="badge">{t("fl.stepCount", { n: actions.length })}</span>
            <button onClick={addAction}>＋ {t("fl.addStep")}</button>
            <button onClick={addCondition} title={t("fl.addCond.hint")}><Plus size={14} />{t("fl.n.condition")}</button>
            <button onClick={addOperator} title={t("fl.addOp.hint")}><Plus size={14} />AND/OR</button>
            <button onClick={addAsset} title={t("fl.addAsset.hint")}><Plus size={14} />{t("fl.n.asset")}</button>
            <button onClick={autoLayout}><LayoutGrid size={15} />{t("fl.autoLayout")}</button>
            <span className="sep" />
            <span className="canvas-label muted" style={{ fontWeight: 500 }}>{t("fl.newLine")}</span>
            <button aria-pressed={newKind === "temporal"} onClick={() => setNewKind("temporal")}>{t("fl.k.temporal")}</button>
            <button aria-pressed={newKind === "dependency"} onClick={() => setNewKind("dependency")}>{t("fl.k.dependency")}</button>
            <button aria-pressed={newKind === "flow"} title={t("fl.flow.hint")} onClick={() => setNewKind("flow")}>{t("fl.f.effect")}</button>
          </div>
          {typeOf.size === 0 && (
            <div className="canvas-empty">
              <h2>{t("fl.empty.title")}</h2>
              <span>{t("fl.empty.body")}</span>
              <button className="primary" onClick={addAction}><Plus size={16} />{t("fl.empty.add")}</button>
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
            onInit={(inst) => { rf.current = inst; }}
            defaultViewport={{ x: SIDE, y: 96, zoom: MIN_FIT }} minZoom={0.2}
            panOnScroll zoomOnPinch
            proOptions={{ hideAttribution: true }}
          >
            <Background variant={BackgroundVariant.Lines} color={GRID} gap={32} lineWidth={1} />
            <Controls showInteractive={false} position="bottom-left" fitViewOptions={fitOpts()}
              onFitView={() => { if (rf.current) fitAll(rf.current, paneRef.current); }} />
            <MiniMap pannable position="bottom-right" nodeColor={EDGE} nodeStrokeWidth={0} maskColor="#070b11c7" style={{ width: 140, height: 90 }} ariaLabel={t("fl.minimap")} />
          </ReactFlow>
          <CanvasLegend />
          <div className="canvas-status" data-fit-inset="bottom">
            <span className="local-indicator" />
            <span>{t("fl.designOnly")}</span>
            {deps.length > 0 && (
              <span data-testid="dep-confirm-bar" style={{ display: "inline-flex", alignItems: "center", gap: 9, marginLeft: 8 }}>
                <span className={unconfirmed.length ? "status-PARTIAL" : "status-PASS"}>{t("fl.depsConfirmed", { ok: deps.length - unconfirmed.length, total: deps.length })}</span>
                {unconfirmed.length > 0 && <button className="small" title={t("fl.confirmAll.hint")} onClick={confirmAllDeps}>{t("fl.confirmAll")}</button>}
              </span>
            )}
          </div>
          {(hint || savedMsg || save.error) && (
            <div className="feedback" role="status">
              {save.error ? <span className="status-FAIL">{t("fl.saveFail")}{(() => { const k = knownErrorKey(save.error); return k ? ` ${t(k)}` : ""; })()}</span>
                : hint ? <span className="status-PARTIAL">{hint}</span>
                : <span>{savedMsg}</span>}
              <button className="quiet icon" aria-label={t("fl.closeMsg")} onClick={() => { setHint(null); setSavedMsg(null); save.clearError(); }}><X size={15} /></button>
            </div>
          )}
        </div>

        <section className={`console ${consoleOpen ? "open" : ""}`} data-testid="validation-console" aria-label={t("fl.check")}>
          <button className="console-toggle" aria-expanded={consoleOpen} onClick={() => setConsoleOpen((o) => !o)}>
            <ScanLine size={16} />
            <strong>{t("fl.check")}</strong>
            {findings.length === 0 ? <span className="badge approved">{t("fl.noIssues")}</span> : (
              <>
                {errors > 0 && <span className="badge insufficient">{t("fl.issues", { n: errors })}</span>}
                {warns > 0 && <span className="badge pending">{t("fl.warnCount", { n: warns })}</span>}
                {findings.length - errors - warns > 0 && <span className="badge">{t("fl.infoCount", { n: findings.length - errors - warns })}</span>}
              </>
            )}
            <span className="muted">{t("fl.checkNote")}</span>
            <ChevronUp size={16} className="chev" aria-hidden />
          </button>
          <div className="console-body">
            <div {...(consoleOpen ? {} : { inert: "" })}>
              <ul className="console-list">
                {findings.length === 0 && <li className="console-empty"><Check size={16} />{t("fl.checkClean")}</li>}
                {findings.map((f) => (
                  <li key={f.id}>
                    <button className={`finding ${f.level}`} onClick={() => openFinding(f)}>
                      <span className="badge">{f.level === "error" ? t("fl.lv.error") : f.level === "warn" ? t("fl.lv.warn") : t("fl.lv.info")}</span>
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

      <aside className="context-dock" ref={inspectorRef} aria-label={sel ? t("fl.props") : t("fl.workbench")}>
        {selAction ? (
          <div className="swap" key={`a:${selAction.id}`}>
            <div className="overview-title">
              <h2>{t("fl.n.action")}</h2><SourceTag source={selAction.source} />
              <button className="quiet icon close" aria-label={t("fl.closeProps")} onClick={() => setSel(null)}><X size={16} /></button>
            </div>
            <div className="mono muted">{selAction.id}</div>
            <p className="dock-hint">{t("fl.dockHint")}</p>
            <label className="field"><span>{t("fl.desc")}</span>
              <textarea rows={4} value={selAction.description ?? ""} onChange={(e) => patchAction(selAction.id, { description: e.target.value || undefined })} />
            </label>
            <label className="field"><span>{t("fl.tactic")}</span>
              <input value={selAction.attack_tactic ?? ""} placeholder="initial-access" onChange={(e) => patchAction(selAction.id, { attack_tactic: e.target.value || undefined })} />
            </label>
            {startToggle(selAction.id)}
            <QuoteList refs={selAction.evidence_refs} byId={evById} source={selAction.source} />
            <div><button className="danger quiet" onClick={() => removeNodes([selAction.id])}><Trash2 size={15} />{t("fl.delStepFull")}</button></div>
          </div>
        ) : selRelation ? (
          <div className="swap" key={`r:${selRelation.id}`}>
            <div className="overview-title">
              <h2>{t("fl.relation")}</h2><SourceTag source={selRelation.source} />
              <button className="quiet icon close" aria-label={t("fl.closeProps")} onClick={() => setSel(null)}><X size={16} /></button>
            </div>
            <div className="mono muted">{selRelation.id}</div>
            <div style={{ fontSize: 14, fontWeight: 600 }}>
              {nameOf.get(selRelation.from_action) ?? selRelation.from_action} <span className="muted">→</span> {nameOf.get(selRelation.to_action) ?? selRelation.to_action}
            </div>
            <div className="field"><span style={{ display: "block", marginBottom: 5, fontSize: 13 }} className="muted">{t("fl.type")}</span>
              <div className="seg">
                {(["temporal", "dependency"] as RelationKind[]).map((k) => (
                  <button key={k} className={selRelation.kind === k ? "on" : ""} aria-pressed={selRelation.kind === k} onClick={() => selRelation.kind !== k && patchRelation(selRelation.id, { kind: k })}>{KIND_LABEL[k]}</button>
                ))}
              </div>
            </div>
            <div className="muted" style={{ fontSize: 13 }}>
              {selRelation.kind === "dependency" ? t("fl.dep.explain") : t("fl.temporal.explain")}
            </div>
            <label className="field"><span>{t("fl.reason")}</span>
              <textarea rows={3} value={selRelation.rationale ?? ""} onChange={(e) => patchRelation(selRelation.id, { rationale: e.target.value || undefined })} />
            </label>
            <EpistemicSelect value={selRelation.epistemic_status} onChange={(v) => patchRelation(selRelation.id, { epistemic_status: v })} />
            <QuoteList refs={selRelation.evidence_refs} byId={evById} source={selRelation.source} />
            {!inChain(selRelation) && (
              <p className="dock-hint">{t("fl.uncited.explain")}</p>
            )}
            {selRelation.kind === "dependency" ? (
              <label className="row" style={{ gap: 8, fontSize: 13 }}>
                <input type="checkbox" checked={(selRelation as RelationX).confirmed === true}
                  onChange={(e) => setConfirmed((r) => r.id === selRelation.id, e.target.checked)} />
                {t("fl.confirmDep")}
              </label>
            ) : (selRelation.source !== "user" && selRelation.source !== "stix" && !relationBacked(selRelation, evById)) && (
              <label className="row" style={{ gap: 8, fontSize: 13 }}>
                <input type="checkbox" checked={(selRelation as RelationX).confirmed === true}
                  onChange={(e) => setConfirmed((r) => r.id === selRelation.id, e.target.checked)} />
                {t("fl.confirmTemporal")}
              </label>
            )}
            <div><button className="danger quiet" onClick={() => removeRelations([selRelation.id])}><Trash2 size={15} />{t("fl.delRelation")}</button></div>
          </div>
        ) : selCondition ? (
          <div className="swap" key={`c:${selCondition.id}`}>
            <div className="overview-title">
              <h2>{t("fl.n.condition")}</h2><SourceTag source={selCondition.source} />
              <button className="quiet icon close" aria-label={t("fl.closeProps")} onClick={() => setSel(null)}><X size={16} /></button>
            </div>
            <div className="mono muted">{selCondition.id}</div>
            <p className="dock-hint">{t("fl.cond.explain")}</p>
            <label className="field"><span>{t("fl.condDesc")}</span>
              <textarea rows={3} placeholder={t("fl.condPh")} value={selCondition.description ?? ""} onChange={(e) => patchCondition(selCondition.id, { description: e.target.value })} />
            </label>
            <RefList title={t("fl.trueTo")} kind="true" refs={selCondition.on_true_refs} from={selCondition.id} nameOf={nameOf} onRemove={removeFlowEdges} />
            <RefList title={t("fl.falseTo")} kind="false" refs={selCondition.on_false_refs} from={selCondition.id} nameOf={nameOf} onRemove={removeFlowEdges} />
            <EpistemicSelect value={selCondition.epistemic_status} onChange={(v) => patchCondition(selCondition.id, { epistemic_status: v })} />
            {startToggle(selCondition.id)}
            <QuoteList refs={selCondition.evidence_refs} byId={evById} source={selCondition.source} />
            <div><button className="danger quiet" onClick={() => removeNodes([selCondition.id])}><Trash2 size={15} />{t("fl.delCond")}</button></div>
          </div>
        ) : selOperator ? (
          <div className="swap" key={`o:${selOperator.id}`}>
            <div className="overview-title">
              <h2>{t("fl.n.operator")}</h2><SourceTag source={selOperator.source} />
              <button className="quiet icon close" aria-label={t("fl.closeProps")} onClick={() => setSel(null)}><X size={16} /></button>
            </div>
            <div className="mono muted">{selOperator.id}</div>
            <div className="field"><span style={{ display: "block", marginBottom: 5, fontSize: 13 }} className="muted">{t("fl.opMode")}</span>
              <div className="seg">
                {(["AND", "OR"] as const).map((k) => (
                  <button key={k} className={selOperator.operator === k ? "on" : ""} aria-pressed={selOperator.operator === k} onClick={() => selOperator.operator !== k && patchOperator(selOperator.id, { operator: k })}>{k}</button>
                ))}
              </div>
            </div>
            <div className="muted" style={{ fontSize: 13 }}>
              {selOperator.operator === "AND" ? t("fl.and.explain") : t("fl.or.explain")}{" "}
              {t("fl.opInputs", { n: flowEdges.filter((e) => e.to === selOperator.id).length })}
            </div>
            <RefList title={t("fl.outTo")} kind="effect" refs={selOperator.effect_refs} from={selOperator.id} nameOf={nameOf} onRemove={removeFlowEdges} />
            <EpistemicSelect value={selOperator.epistemic_status} onChange={(v) => patchOperator(selOperator.id, { epistemic_status: v })} />
            {startToggle(selOperator.id)}
            <div><button className="danger quiet" onClick={() => removeNodes([selOperator.id])}><Trash2 size={15} />{t("fl.delOp")}</button></div>
          </div>
        ) : selAsset ? (
          <div className="swap" key={`s:${selAsset.id}`}>
            <div className="overview-title">
              <h2>{t("fl.n.asset")}</h2><SourceTag source={selAsset.source} />
              <button className="quiet icon close" aria-label={t("fl.closeProps")} onClick={() => setSel(null)}><X size={16} /></button>
            </div>
            <div className="mono muted">{selAsset.id}</div>
            <p className="dock-hint">{t("fl.asset.explain")}</p>
            <label className="field"><span>{t("fl.name")}</span>
              <input value={selAsset.name ?? ""} placeholder={t("fl.assetPh")} onChange={(e) => patchAsset(selAsset.id, { name: e.target.value })} />
            </label>
            <label className="field"><span>{t("fl.desc")}</span>
              <textarea rows={3} value={selAsset.description ?? ""} onChange={(e) => patchAsset(selAsset.id, { description: e.target.value || undefined })} />
            </label>
            <EpistemicSelect value={selAsset.epistemic_status} onChange={(v) => patchAsset(selAsset.id, { epistemic_status: v })} />
            <div className="muted" style={{ fontSize: 13 }}>
              {t("fl.assetFrom", { list: joinList(flowEdges.filter((e) => e.to === selAsset.id).map((e) => nameOf.get(e.from) ?? e.from)) || t("fl.none") })}
            </div>
            <div><button className="danger quiet" onClick={() => removeNodes([selAsset.id])}><Trash2 size={15} />{t("fl.delAsset")}</button></div>
          </div>
        ) : selFlow ? (
          <div className="swap" key={`f:${selFlow.id}`}>
            <div className="overview-title">
              <h2>{t("fl.flowLine")}</h2>
              <button className="quiet icon close" aria-label={t("fl.closeProps")} onClick={() => setSel(null)}><X size={16} /></button>
            </div>
            <div style={{ fontSize: 14, fontWeight: 600 }}>
              {nameOf.get(selFlow.from) ?? selFlow.from} <span className="muted">→</span> {nameOf.get(selFlow.to) ?? selFlow.to}
            </div>
            <div><span className={`edge-chip ${selFlow.kind === "effect" ? "flow" : `flow-${selFlow.kind}`}`}>{FLOW_LABEL[selFlow.kind]}</span></div>
            <div className="muted" style={{ fontSize: 13 }}>
              {selFlow.kind === "effect" ? t("fl.effect.explain", { from: NODE_LABEL[typeOf.get(selFlow.from) ?? "action"] })
                : selFlow.kind === "asset" ? t("fl.asset.edge")
                : selFlow.kind === "true" ? t("fl.true.edge") : t("fl.false.edge")}
            </div>
            {(selFlow.kind === "true" || selFlow.kind === "false") && (
              <div><button onClick={() => flipBranch(selFlow)}><GitBranch size={15} />{t("fl.flip", { branch: selFlow.kind === "true" ? t("fl.f.false") : t("fl.f.true") })}</button></div>
            )}
            <div><button className="danger quiet" onClick={() => removeFlowEdges([selFlow.id])}><Trash2 size={15} />{t("fl.delFlow")}</button></div>
          </div>
        ) : (
          <div className="swap" key="overview">
            <div className="overview-title"><Layers size={20} /><h2>{t("fl.workbench")}</h2></div>
            <p className="overview-name">{ir.name || ir.id}</p>
            <div className="overview-chain">
              <GitBranch size={16} />
              <span>{t("fl.stepCount", { n: actions.length })}</span>
              <span>{t("fl.sum.deps", { n: deps.length })}{deps.length > 0 && t("fl.sum.depsOk", { n: deps.length - unconfirmed.length })}</span>
              <span>{t("fl.sum.temporal", { n: temporal.length - uncountedTemporal.length })}</span>
            </div>
            {uncountedTemporal.length > 0 && (
              <div className="muted" style={{ fontSize: 13 }} data-testid="uncounted-relations">
                {t("fl.sum.uncited", { n: uncountedTemporal.length })}
              </div>
            )}
            {(flowNodes > 0 || flowEdges.length > 0 || startRefs.length > 0) && (
              <div className="overview-flow" data-testid="attack-flow-summary">
                <span><Flag size={12} />{t("fl.sum.starts", { n: startRefs.length })}</span>
                <span>{t("fl.sum.conds", { n: conditions.length })}</span>
                <span>{t("fl.sum.ops", { n: operators.length })}</span>
                <span>{t("fl.sum.assets", { n: assets.length })}</span>
                <span>{t("fl.sum.flows", { n: flowEdges.length })}</span>
              </div>
            )}
            <div className="topology-summary">
              <h3>{t("fl.trainAssets")}</h3>
              {hosts.length === 0 ? <div><span className="muted">{t("fl.noDeps")}</span></div> : hosts.map((h) => (
                <div key={h.id}>
                  <span>{h.role}</span>
                  <span>{svcOf(h.id).map((x: any) => x.port).filter(Boolean).join(" / ") || "—"}</span>
                  <Check size={13} />
                </div>
              ))}
            </div>
            <ol className="design-route" aria-label={t("fl.route")}>
              <li className={designOk && !dirty ? "complete" : "current"}>
                <span>{designOk && !dirty ? <Check size={12} /> : "1"}</span>{t("fl.r.design")}
                {dirty && <small>{t("fl.unsaved")}</small>}
              </li>
              <li className={designOk ? "complete" : ""}>
                <span>{designOk ? <Check size={12} /> : "2"}</span>{t("fl.r.check")}
                <small>{errors > 0 ? t("fl.issues", { n: errors }) : unconfirmed.length > 0 ? t("fl.r.depsOpen", { n: unconfirmed.length }) : warns > 0 ? t("fl.warnCount", { n: warns }) : t("fl.r.pass")}</small>
              </li>
              <li className={approved ? "complete" : designOk && !dirty ? "current" : ""}>
                <span>{approved ? <Check size={12} /> : "3"}</span>{t("fl.r.approve")}
                <small>{approved ? t("fl.r.approved") : t("fl.r.onTopology")}</small>
              </li>
            </ol>
            {errors > 0 ? (
              <button className="primary next-action" onClick={() => setConsoleOpen(true)}><ScanLine size={16} />{t("fl.n.showIssues")}<ArrowRight size={15} /></button>
            ) : unconfirmed.length > 0 ? (
              <button className="primary next-action" onClick={confirmAllDeps}><Check size={16} />{t("fl.n.confirmDeps")}<ArrowRight size={15} /></button>
            ) : dirty ? (
              <button className="primary next-action" disabled={save.busy || unnamed > 0} onClick={() => save.run()}>{save.busy ? <span className="spinner" /> : <Save size={16} />}{t("fl.n.save")}<ArrowRight size={15} /></button>
            ) : (
              <Link className="next-action-link" to="/deps"><button className="primary next-action"><ArrowRight size={16} />{t("fl.n.next")}<ArrowRight size={15} /></button></Link>
            )}
            <details className="capability-note">
              <summary>{t("fl.versions", { v: ir.ir_version ?? 1 })}</summary>
              {versions.error ? <ApiNotice error={versions.error} what={t("fl.versionsWhat")} onRetry={() => versions.reload()} />
                : versions.loading && !versions.data ? <p><span className="spinner" /> {t("fl.loading")}</p>
                : versionRows.length === 0 ? <p>{t("fl.noVersions")}</p>
                : versionRows.map((v) => (
                  <div key={v.ir_version} className="version-row">
                    <span className="mono" style={{ color: v.ir_version === ir.ir_version ? "var(--accent)" : undefined }}>v{v.ir_version}</span>
                    <span className="note" title={v.note}>{v.note || "—"}</span>
                    <span className="nowrap">{fmtTime(v.ts)}</span>
                  </div>
                ))}
            </details>
            <details className="capability-note">
              <summary>{t("fl.about")}</summary>
              <p>{t("fl.about1")}</p>
              <p>{t("fl.about2")}</p>
              <p>{t("fl.about3")}</p>
            </details>
            <Link to="/missing" className="muted" style={{ fontSize: 13 }}>← {t("stage.missing")}</Link>
          </div>
        )}
      </aside>
    </div>
  );
}

/** The quotes behind one item: overall verdict, then each quote as its match mark plus opening words (not a bare id). */
function QuoteList({ refs, byId, source }: { refs?: string[]; byId: Map<string, Evidence>; source?: Action["source"] }) {
  const ids = Array.isArray(refs) ? refs : [];
  return (
    <div className="ref-list">
      <span className="row" style={{ gap: 8 }}><span className="muted" style={{ fontSize: 13 }}>{t("fl.quote")}</span><CitationBadge summary={summarizeCitations(ids, byId)} source={source} /></span>
      {ids.map((id) => <div key={id} className="ref-row"><span className="name"><QuoteSnippet evidence={byId.get(id)} id={id} max={60} /></span></div>)}
    </div>
  );
}

/** The outgoing flow lines of one node, listed in the inspector with a remove button each. */
function RefList({ title, kind, refs, from, nameOf, onRemove }: { title: string; kind: FlowEdgeKind; refs?: string[]; from: string; nameOf: Map<string, string>; onRemove: (ids: string[]) => void }) {
  return (
    <div className="ref-list">
      <span className={`edge-chip ${kind === "effect" ? "flow" : `flow-${kind}`}`}>{title}</span>
      {(refs ?? []).length === 0 ? <span className="muted">{t("fl.notLinked")}</span> : (refs ?? []).map((id) => (
        <div key={id} className="ref-row">
          <span className="name">{nameOf.get(id) ?? t("fl.gone", { id })}</span>
          <button className="quiet icon" aria-label={t("fl.removeFlow")} onClick={() => onRemove([flowEdgeId(from, kind, id)])}><X size={14} /></button>
        </div>
      ))}
    </div>
  );
}

function EpistemicSelect({ value, onChange }: { value: EpistemicStatus; onChange: (v: EpistemicStatus) => void }) {
  return (
    <label className="field"><span>{t("fl.basis")}</span>
      <Select value={value} aria-label={t("fl.basis")} onChange={(e) => onChange(e.target.value as EpistemicStatus)}>
        {EPISTEMIC_ORDER.map((s) => <option key={s} value={s}>{EPISTEMIC[s].label}（{s}）</option>)}
      </Select>
    </label>
  );
}

export function FlowPage() {
  const { ir } = useScenario();
  // key by scenario so switching scenarios resets the local draft
  return <ScenarioGate title={t("fl.title")}>{ir && <Editor key={ir.id} ir={ir} />}</ScenarioGate>;
}
