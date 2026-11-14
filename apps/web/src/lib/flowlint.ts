// Design checks for the attack-flow graph. Computed in the browser from what is on the canvas right now.
// These say whether the DESIGN is coherent; they say nothing about deployment, validation or any attack outcome.
import type { Action, AttackFlowAsset, AttackFlowCondition, AttackFlowOperator, Evidence, Relation } from "@contracts";
import { summarizeCitations } from "../components/ui";
import type { RelationX } from "./plan";

export type FindingLevel = "error" | "warn" | "info";
export type FlowNodeType = "action" | "condition" | "operator" | "asset";
export interface Finding { id: string; level: FindingLevel; text: string; target?: { type: FlowNodeType | "relation"; id: string } }

/** The Attack Flow part of the graph, next to the actions and relations the editor always had. */
export interface FlowExtras {
  conditions?: AttackFlowCondition[];
  operators?: AttackFlowOperator[];
  assets?: AttackFlowAsset[];
  startRefs?: string[];
  /** The scenario's quotes, used to tell relations a quote backs from ones the model merely asserted. */
  evidence?: Evidence[];
}

/** A relation is backed when at least one of its quotes is found in the source (exact / strong match). */
export function relationBacked(r: Relation, evById: Map<string, Evidence>): boolean {
  return summarizeCitations(r.evidence_refs, evById).ok > 0;
}
/** Whether a relation counts as part of the attack chain. Relations a model asserted without a matching quote are
 *  shown but left out by default; the analyst's own lines, lines from an imported file, and confirmed lines count. */
export function countsInChain(r: Relation, evById: Map<string, Evidence>): boolean {
  return r.source === "user" || r.source === "stix" || (r as RelationX).confirmed === true || relationBacked(r, evById);
}

export interface Loop { nodes: string[]; relationIds: string[]; flowEdgeIds: string[] }
/** Directed cycles over every line on the canvas (relations of both kinds and flow edges), as strongly connected
 *  components with more than one node. A cycle such as a6 → a8 → a9 → a6 has no possible first step. */
export function findLoops(nodeIds: string[], relations: Relation[], flowEdges: FlowEdge[]): Loop[] {
  const ids = new Set(nodeIds);
  const adj = new Map<string, string[]>(nodeIds.map((n) => [n, []]));
  const link = (a: string, b: string) => { if (a !== b && ids.has(a) && ids.has(b)) adj.get(a)!.push(b); };
  relations.forEach((r) => link(r.from_action, r.to_action));
  flowEdges.forEach((e) => { if (e.kind !== "asset") link(e.from, e.to); });
  // Tarjan, iterative so a long chain cannot overflow the stack.
  const index = new Map<string, number>(), low = new Map<string, number>(), comp = new Map<string, number>();
  const stack: string[] = [], onStack = new Set<string>();
  let counter = 0, compN = 0;
  for (const root of nodeIds) {
    if (index.has(root)) continue;
    const work: [string, number][] = [[root, 0]];
    while (work.length) {
      const frame = work[work.length - 1];
      const [n, i] = frame;
      if (i === 0) { index.set(n, counter); low.set(n, counter); counter++; stack.push(n); onStack.add(n); }
      const next = adj.get(n)!;
      if (i < next.length) {
        frame[1] = i + 1;
        const m = next[i];
        if (!index.has(m)) work.push([m, 0]);
        else if (onStack.has(m)) low.set(n, Math.min(low.get(n)!, index.get(m)!));
      } else {
        if (low.get(n) === index.get(n)) {
          let m: string;
          do { m = stack.pop()!; onStack.delete(m); comp.set(m, compN); } while (m !== n);
          compN++;
        }
        work.pop();
        const parent = work[work.length - 1]?.[0];
        if (parent) low.set(parent, Math.min(low.get(parent)!, low.get(n)!));
      }
    }
  }
  const members = new Map<number, string[]>();
  nodeIds.forEach((n) => members.set(comp.get(n)!, [...(members.get(comp.get(n)!) ?? []), n]));
  const loops: Loop[] = [];
  for (const [c, nodes] of members) {
    if (nodes.length < 2) continue;
    const inside = (a: string, b: string) => comp.get(a) === c && comp.get(b) === c;
    loops.push({
      nodes,
      relationIds: relations.filter((r) => inside(r.from_action, r.to_action)).map((r) => r.id),
      flowEdgeIds: flowEdges.filter((e) => e.kind !== "asset" && inside(e.from, e.to)).map((e) => e.id),
    });
  }
  return loops;
}

/** effect: action/operator → next node · true/false: a condition's two branches · asset: an action → the asset it touches. */
export type FlowEdgeKind = "effect" | "true" | "false" | "asset";
export interface FlowEdge { id: string; from: string; to: string; kind: FlowEdgeKind }
export const flowEdgeId = (from: string, kind: FlowEdgeKind, to: string) => `flow|${from}|${kind}|${to}`;

/** Attack Flow edges are not stored as objects: they are the *_refs lists on each node. This reads them out as edges. */
export function flowEdgesOf(actions: Action[], x: FlowExtras = {}): FlowEdge[] {
  const out: FlowEdge[] = [];
  const seen = new Set<string>();
  const push = (from: string, kind: FlowEdgeKind, refs?: string[]) => {
    for (const to of refs ?? []) {
      const id = flowEdgeId(from, kind, to);
      if (!seen.has(id)) { seen.add(id); out.push({ id, from, to, kind }); }
    }
  };
  for (const a of actions) { push(a.id, "effect", a.effect_refs); push(a.id, "asset", a.asset_refs); }
  for (const c of x.conditions ?? []) { push(c.id, "true", c.on_true_refs); push(c.id, "false", c.on_false_refs); }
  for (const o of x.operators ?? []) push(o.id, "effect", o.effect_refs);
  return out;
}

// inferred = the report does not say it, it was filled in. insufficient = quotes were given but did not match the
// source — that is a "go and read the original" case, not "the report is silent".
const weakText = (name: string, status: string) => (status === "inferred"
  ? `「${name}」是推論補全的項目，原文沒有明講。`
  : `「${name}」附的引文沒有對上原文，需要人工對照原文確認。`);
const short = (s: string, n = 18) => (s.length > n ? `${s.slice(0, n)}…` : s);

export function lintFlow(actions: Action[], relations: Relation[], x: FlowExtras = {}): Finding[] {
  const out: Finding[] = [];
  const conditions = x.conditions ?? [];
  const operators = x.operators ?? [];
  const assets = x.assets ?? [];
  const byId = new Map(actions.map((a) => [a.id, a]));
  const typeOf = new Map<string, FlowNodeType>();
  actions.forEach((a) => typeOf.set(a.id, "action"));
  conditions.forEach((c) => typeOf.set(c.id, "condition"));
  operators.forEach((o) => typeOf.set(o.id, "operator"));
  assets.forEach((s) => typeOf.set(s.id, "asset"));
  const names = new Map<string, string>();
  conditions.forEach((c) => names.set(c.id, c.description?.trim() ? `條件：${short(c.description.trim())}` : "未描述的條件"));
  operators.forEach((o) => names.set(o.id, `${o.operator} 運算`));
  assets.forEach((s) => names.set(s.id, s.name?.trim() ? `資產：${s.name.trim()}` : "未命名的資產"));
  const label = (id: string) => byId.get(id)?.name?.trim() || names.get(id) || id;
  const target = (id: string) => ({ type: typeOf.get(id) ?? "action", id });

  for (const a of actions) {
    if (!a.name.trim()) out.push({ id: `unnamed:${a.id}`, level: "error", text: "這個行為沒有名稱，無法儲存。", target: { type: "action", id: a.id } });
  }
  const seen = new Set<string>();
  for (const r of relations) {
    // An imported Attack Flow may relate an action to a condition or operator, so any node on the canvas is a valid end.
    if (!typeOf.has(r.from_action) || !typeOf.has(r.to_action)) {
      out.push({ id: `dangling:${r.id}`, level: "error", text: "這條關係連到一個已不存在的節點。", target: { type: "relation", id: r.id } });
      continue;
    }
    const key = `${r.from_action}>${r.to_action}>${r.kind}`;
    if (seen.has(key)) out.push({ id: `dup:${r.id}`, level: "error", text: `「${label(r.from_action)} → ${label(r.to_action)}」有重複的同類型關係。`, target: { type: "relation", id: r.id } });
    seen.add(key);
  }

  // A dependency cycle means no step could ever come first.
  const deps = relations.filter((r) => r.kind === "dependency" && byId.has(r.from_action) && byId.has(r.to_action));
  const out_ = new Map<string, Relation[]>();
  deps.forEach((r) => out_.set(r.from_action, [...(out_.get(r.from_action) ?? []), r]));
  const state = new Map<string, 1 | 2>();
  const inCycle = new Set<string>();
  const visit = (n: string, trail: Relation[]) => {
    state.set(n, 1);
    for (const r of out_.get(n) ?? []) {
      if (state.get(r.to_action) === 1) {
        const from = trail.findIndex((t) => t.from_action === r.to_action);
        [...trail.slice(from < 0 ? 0 : from), r].forEach((t) => inCycle.add(t.id));
      } else if (!state.has(r.to_action)) visit(r.to_action, [...trail, r]);
    }
    state.set(n, 2);
  };
  actions.forEach((a) => { if (!state.has(a.id)) visit(a.id, []); });
  for (const r of deps) {
    if (inCycle.has(r.id)) out.push({ id: `cycle:${r.id}`, level: "error", text: `「${label(r.from_action)} → ${label(r.to_action)}」在依賴循環裡：互相依賴的步驟沒有一個能先發生。`, target: { type: "relation", id: r.id } });
  }

  // ---- Attack Flow edges (the *_refs lists) ----
  const all = flowEdgesOf(actions, x);
  const live: FlowEdge[] = [];
  for (const e of all) {
    const to = typeOf.get(e.to);
    if (!to) {
      out.push({ id: `flowdangling:${e.id}`, level: "error", text: `「${label(e.from)}」的流程連線指向一個已不存在的節點（${e.to}）。`, target: target(e.from) });
    } else if (e.kind === "asset" ? to !== "asset" : to === "asset") {
      out.push({
        id: `flowkind:${e.id}`, level: "error", target: target(e.from),
        text: e.kind === "asset" ? `「${label(e.from)}」的資產連線指向的不是資產節點。` : `「${label(e.from)}」的流程連線指向資產節點；資產只能由攻擊行為以「資產」連線指到。`,
      });
    } else if (e.from === e.to) {
      out.push({ id: `flowself:${e.id}`, level: "error", text: `「${label(e.from)}」的流程連線連到自己。`, target: target(e.from) });
    } else live.push(e);
  }
  const flowIn = new Map<string, number>();
  const flowOut = new Map<string, number>();
  for (const e of live) {
    flowIn.set(e.to, (flowIn.get(e.to) ?? 0) + 1);
    flowOut.set(e.from, (flowOut.get(e.from) ?? 0) + 1);
  }
  const starts = new Set(x.startRefs ?? []);
  for (const id of starts) {
    if (!typeOf.has(id)) out.push({ id: `startdangling:${id}`, level: "error", text: `流程起點指向一個已不存在的節點（${id}）。` });
    else if (typeOf.get(id) === "asset") out.push({ id: `startasset:${id}`, level: "error", text: `「${label(id)}」是資產節點，不能當流程起點。`, target: target(id) });
  }

  // Loops through any kind of line. Pure dependency cycles are already reported above as errors, edge by edge.
  for (const loop of findLoops([...typeOf.keys()], relations, live)) {
    if (loop.relationIds.length > 0 && loop.flowEdgeIds.length === 0 && loop.relationIds.every((id) => inCycle.has(id))) continue;
    const names = loop.nodes.slice(0, 4).map((n) => `「${short(label(n), 14)}」`).join("、");
    out.push({
      id: `loop:${loop.nodes.join(",")}`, level: "warn",
      text: `${names}${loop.nodes.length > 4 ? ` 等 ${loop.nodes.length} 個節點` : ""}的連線繞成一圈：沒有哪一步能排在最前面。請檢查其中是否有方向畫反或不該有的連線。`,
      target: loop.relationIds[0] ? { type: "relation", id: loop.relationIds[0] } : target(loop.nodes[0]),
    });
  }

  const evById = new Map((x.evidence ?? []).map((e) => [e.id, e]));
  for (const r of relations) {
    if (!typeOf.has(r.from_action) || !typeOf.has(r.to_action)) continue;
    const name = `「${label(r.from_action)} → ${label(r.to_action)}」`;
    if (r.kind === "dependency" && (r as RelationX).confirmed !== true) {
      out.push({
        id: `unconfirmed:${r.id}`, level: "warn", target: { type: "relation", id: r.id },
        text: `依賴${name}尚未確認，拓樸規劃不會為它開通連線。${countsInChain(r, evById) ? "" : "它也沒有對得上原文的引文。"}`,
      });
    } else if (!countsInChain(r, evById)) {
      out.push({ id: `unbacked:${r.id}`, level: "warn", text: `${name}的先後關係沒有對得上原文的引文，目前以虛線顯示、不計入攻擊鏈。對照原文後可在屬性面板確認或刪除。`, target: { type: "relation", id: r.id } });
    }
  }
  for (const c of conditions) {
    const t = { type: "condition" as const, id: c.id };
    if (!c.description?.trim()) out.push({ id: `conddesc:${c.id}`, level: "warn", text: "這個條件沒有描述，看不出它在判斷什麼。", target: t });
    if (!(c.on_true_refs ?? []).length) out.push({ id: `condtrue:${c.id}`, level: "warn", text: `「${label(c.id)}」缺少「成立」分支：條件成立後沒有接到任何節點。`, target: t });
    const both = (c.on_true_refs ?? []).filter((id) => (c.on_false_refs ?? []).includes(id));
    if (both.length) out.push({ id: `condboth:${c.id}`, level: "warn", text: `「${label(c.id)}」的成立與不成立分支指向同一個節點（${label(both[0])}），這個條件沒有造成分歧。`, target: t });
  }
  for (const o of operators) {
    const t = { type: "operator" as const, id: o.id };
    const n = flowIn.get(o.id) ?? 0;
    if (n < 2) out.push({ id: `opin:${o.id}`, level: "warn", text: `${o.operator} 運算只有 ${n} 條輸入；要合併兩條以上的路徑才有意義。`, target: t });
    if (!(flowOut.get(o.id) ?? 0)) out.push({ id: `opout:${o.id}`, level: "warn", text: `${o.operator} 運算沒有輸出，合併後沒有接到任何節點。`, target: t });
  }

  // Orphans: a node no line of any kind touches. A lone start node in a one-node graph is not an orphan.
  const linked = new Set(relations.flatMap((r) => [r.from_action, r.to_action]));
  live.forEach((e) => { linked.add(e.from); linked.add(e.to); });
  if (typeOf.size > 1) {
    for (const a of actions) {
      if (!linked.has(a.id)) out.push({ id: `isolated:${a.id}`, level: "warn", text: `「${label(a.id)}」沒有和任何行為相連。`, target: { type: "action", id: a.id } });
    }
  }
  for (const n of [...conditions, ...operators, ...assets]) {
    if (!linked.has(n.id)) out.push({ id: `orphan:${n.id}`, level: "warn", text: `「${label(n.id)}」是孤兒節點：沒有任何連線接到它。`, target: target(n.id) });
  }
  if (live.some((e) => e.kind !== "asset") && starts.size === 0) {
    out.push({ id: "nostart", level: "info", text: "這張流程圖有流程連線，但還沒有標記任何起點。" });
  }

  for (const a of actions) {
    if (a.epistemic_status === "inferred" || a.epistemic_status === "insufficient") {
      out.push({ id: `weak:${a.id}`, level: "info", text: weakText(label(a.id), a.epistemic_status), target: { type: "action", id: a.id } });
    }
  }
  for (const n of [...conditions, ...operators, ...assets]) {
    if (n.epistemic_status === "inferred" || n.epistemic_status === "insufficient") {
      out.push({ id: `weak:${n.id}`, level: "info", text: weakText(label(n.id), n.epistemic_status), target: target(n.id) });
    }
  }
  const rank = { error: 0, warn: 1, info: 2 };
  return out.sort((a, b) => rank[a.level] - rank[b.level]);
}
