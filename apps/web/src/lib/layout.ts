// Left-to-right layered layout for the action graph. Deterministic, cycle-tolerant, no extra dependency.
export interface XY { x: number; y: number }

export function layeredLayout(ids: string[], edges: { from: string; to: string }[], colW = 270, rowH = 120): Record<string, XY> {
  const idSet = new Set(ids);
  const out = new Map<string, string[]>();
  const indeg = new Map<string, number>();
  ids.forEach((i) => { out.set(i, []); indeg.set(i, 0); });
  for (const e of edges) {
    if (!idSet.has(e.from) || !idSet.has(e.to) || e.from === e.to) continue;
    out.get(e.from)!.push(e.to);
    indeg.set(e.to, indeg.get(e.to)! + 1);
  }
  const depth = new Map<string, number>();
  const queue = ids.filter((i) => indeg.get(i) === 0);
  queue.forEach((i) => depth.set(i, 0));
  for (let q = 0; q < queue.length; q++) {
    const n = queue[q];
    for (const m of out.get(n)!) {
      depth.set(m, Math.max(depth.get(m) ?? 0, depth.get(n)! + 1));
      indeg.set(m, indeg.get(m)! - 1);
      if (indeg.get(m) === 0) queue.push(m);
    }
  }
  // Nodes stuck in cycles never reach indegree 0; park them after the deepest resolved layer.
  const maxDepth = Math.max(-1, ...depth.values());
  ids.forEach((i) => { if (!queue.includes(i)) depth.set(i, Math.max(depth.get(i) ?? 0, maxDepth + 1)); });

  const rows = new Map<number, number>();
  const pos: Record<string, XY> = {};
  for (const i of ids) {
    const d = depth.get(i) ?? 0;
    const r = rows.get(d) ?? 0;
    rows.set(d, r + 1);
    pos[i] = { x: d * colW, y: r * rowH };
  }
  return pos;
}

export function loadPositions(key: string): Record<string, XY> {
  try { return JSON.parse(localStorage.getItem(key) ?? "{}") ?? {}; } catch { return {}; }
}
export function savePositions(key: string, pos: Record<string, XY>) {
  try { localStorage.setItem(key, JSON.stringify(pos)); } catch { /* per-viewer convenience only */ }
}
