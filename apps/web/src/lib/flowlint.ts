// Design checks for the attack-flow graph. Computed in the browser from what is on the canvas right now.
// These say whether the DESIGN is coherent; they say nothing about deployment, validation or any attack outcome.
import type { Action, Relation } from "@contracts";
import type { RelationX } from "./plan";

export type FindingLevel = "error" | "warn" | "info";
export interface Finding { id: string; level: FindingLevel; text: string; target?: { type: "action" | "relation"; id: string } }

export function lintFlow(actions: Action[], relations: Relation[]): Finding[] {
  const out: Finding[] = [];
  const byId = new Map(actions.map((a) => [a.id, a]));
  const label = (id: string) => byId.get(id)?.name?.trim() || id;

  for (const a of actions) {
    if (!a.name.trim()) out.push({ id: `unnamed:${a.id}`, level: "error", text: "這個行為沒有名稱，無法儲存。", target: { type: "action", id: a.id } });
  }
  const seen = new Set<string>();
  for (const r of relations) {
    if (!byId.has(r.from_action) || !byId.has(r.to_action)) {
      out.push({ id: `dangling:${r.id}`, level: "error", text: "這條關係連到一個已不存在的行為。", target: { type: "relation", id: r.id } });
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

  for (const r of deps) {
    if ((r as RelationX).confirmed !== true) {
      out.push({ id: `unconfirmed:${r.id}`, level: "warn", text: `依賴「${label(r.from_action)} → ${label(r.to_action)}」尚未確認，拓樸規劃不會為它開通連線。`, target: { type: "relation", id: r.id } });
    }
  }
  if (actions.length > 1) {
    const linked = new Set(relations.flatMap((r) => [r.from_action, r.to_action]));
    for (const a of actions) {
      if (!linked.has(a.id)) out.push({ id: `isolated:${a.id}`, level: "warn", text: `「${label(a.id)}」沒有和任何行為相連。`, target: { type: "action", id: a.id } });
    }
  }
  for (const a of actions) {
    if (a.epistemic_status === "inferred" || a.epistemic_status === "insufficient") {
      out.push({ id: `weak:${a.id}`, level: "info", text: `「${label(a.id)}」是${a.epistemic_status === "inferred" ? "推測" : "證據不足"}的項目，原文沒有明講。`, target: { type: "action", id: a.id } });
    }
  }
  const rank = { error: 0, warn: 1, info: 2 };
  return out.sort((a, b) => rank[a.level] - rank[b.level]);
}
