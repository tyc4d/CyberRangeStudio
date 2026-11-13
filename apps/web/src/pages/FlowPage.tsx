import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactFlow, {
  Background, Controls, Handle, MarkerType, Position, useEdgesState, useNodesState,
  type Connection, type Edge, type Node, type NodeProps,
} from "reactflow";
import "reactflow/dist/style.css";
import type { Action, EpistemicStatus, Relation, RelationKind, ScenarioIR } from "@contracts";
import { api } from "../lib/api";
import { useAction, useLoad } from "../lib/hooks";
import { layeredLayout, loadPositions, savePositions } from "../lib/layout";
import { useScenario } from "../lib/scenario";
import {
  ApiNotice, EPISTEMIC, EPISTEMIC_ORDER, EpistemicBadge, fmtTime, NextStep, Notice, PageHead, ScenarioGate, SourceTag,
} from "../components/ui";

const KIND_LABEL: Record<RelationKind, string> = { temporal: "時間先後", dependency: "依賴" };
const DEP = "#4c9aff";
const TEMPORAL = "#7d8aa0";

function ActionNode({ data }: NodeProps<{ action: Action }>) {
  const a = data.action;
  return (
    <div className={`gnode ${a.epistemic_status}`}>
      <Handle type="target" position={Position.Left} />
      <div className="t">{a.name || "（未命名）"}</div>
      <div className="meta">
        {a.attack_technique && <span className="mono muted">{a.attack_technique}</span>}
        <EpistemicBadge status={a.epistemic_status} />
        {a.source === "user" && <SourceTag source="user" />}
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
const nodeTypes = { action: ActionNode };

function toEdge(r: Relation, selected: boolean): Edge {
  const dep = r.kind === "dependency";
  const color = dep ? DEP : TEMPORAL;
  return {
    id: r.id, source: r.from_action, target: r.to_action, selected,
    label: KIND_LABEL[r.kind] ?? r.kind,
    animated: false,
    style: { stroke: color, strokeWidth: selected ? 3 : dep ? 2 : 1.5, strokeDasharray: dep ? undefined : "6 5" },
    markerEnd: { type: dep ? MarkerType.ArrowClosed : MarkerType.Arrow, color, width: 18, height: 18 },
    labelStyle: { fill: color, fontSize: 10 },
    labelBgStyle: { fill: "#0b0e14" },
  };
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
  const inspectorRef = useRef<HTMLDivElement>(null);
  useEffect(() => { inspectorRef.current?.scrollTo({ top: 0 }); }, [sel?.type, sel?.id]);
  const posKey = `cr.flowpos.${ir.id}`;
  const stored = useRef(loadPositions(posKey));

  const [nodes, setNodes, onNodesChange] = useNodesState<{ action: Action }>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

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
      const auto = layeredLayout(actions.map((a) => a.id), relations.map((r) => ({ from: r.from_action, to: r.to_action })));
      return actions.map((a): Node<{ action: Action }> => ({
        id: a.id, type: "action", data: { action: a },
        position: prevPos.get(a.id) ?? stored.current[a.id] ?? auto[a.id] ?? { x: 0, y: 0 },
        selected: sel?.type === "action" && sel.id === a.id,
      }));
    });
  }, [actions, sel]); // eslint-disable-line
  useEffect(() => {
    setEdges(relations.map((r) => toEdge(r, sel?.type === "relation" && sel.id === r.id)));
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
    stored.current[id] = { x: 0, y: maxY + 120 };
    setActions((xs) => [...xs, { id, name: "新攻擊行為", epistemic_status: "inferred", source: "user", evidence_refs: [] }]);
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
    const auto = layeredLayout(actions.map((a) => a.id), relations.map((r) => ({ from: r.from_action, to: r.to_action })));
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

  const selAction = sel?.type === "action" ? actions.find((a) => a.id === sel.id) : undefined;
  const selRelation = sel?.type === "relation" ? relations.find((r) => r.id === sel.id) : undefined;
  const nameOf = useMemo(() => new Map(actions.map((a) => [a.id, a.name])), [actions]);
  const versionRows = Array.isArray(versions.data) ? versions.data : [];

  return (
    <div className="page full">
      <PageHead title="攻擊流程" desc="拖曳節點調整版面；從節點右側拉線到另一個節點左側可新增關係。點選節點或連線可在右側編輯，選取後按 Delete 可刪除。">
        {dirty && <span className="status-PARTIAL" style={{ fontSize: 12 }}>● 有未儲存的修改</span>}
        <button onClick={addAction}>＋ 新增行為</button>
        <button onClick={autoLayout}>自動排版</button>
      </PageHead>

      <div className="row">
        <div className="legend">
          <span><span className="line" />依賴：後者必須有前者才能成立</span>
          <span><span className="line temporal" />時間先後：只是發生順序，不代表依賴</span>
        </div>
        <div className="row" style={{ marginLeft: "auto", gap: 8 }}>
          <span className="muted" style={{ fontSize: 12 }}>新連線類型</span>
          <div className="seg">
            <button className={newKind === "temporal" ? "on" : ""} onClick={() => setNewKind("temporal")}>時間先後</button>
            <button className={newKind === "dependency" ? "on" : ""} onClick={() => setNewKind("dependency")}>依賴</button>
          </div>
        </div>
      </div>
      {hint && <Notice kind="warn">{hint}</Notice>}

      <div className="canvas-wrap">
        <div className="canvas">
          {actions.length === 0 && (
            <div className="empty" style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", zIndex: 1, pointerEvents: "none" }}>
              這個情境還沒有攻擊行為。按「新增行為」開始建立流程。
            </div>
          )}
          <ReactFlow
            nodes={nodes} edges={edges} nodeTypes={nodeTypes}
            onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={onConnect}
            onNodeClick={(_, n) => setSel({ type: "action", id: n.id })}
            onEdgeClick={(_, e) => setSel({ type: "relation", id: e.id })}
            onPaneClick={() => setSel(null)}
            onNodeDragStop={persistPositions}
            onNodesDelete={(ns) => removeActions(ns.map((n) => n.id))}
            onEdgesDelete={(es) => removeRelations(es.map((e) => e.id))}
            deleteKeyCode={["Delete", "Backspace"]}
            fitView fitViewOptions={{ padding: 0.2, maxZoom: 1.1 }} minZoom={0.2}
            proOptions={{ hideAttribution: true }}
          >
            <Background color="#1c2534" gap={20} />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>

        <div className="inspector" ref={inspectorRef}>
          {selAction ? (
            <div className="card">
              <div className="row"><h2>攻擊行為</h2><SourceTag source={selAction.source} /><span className="mono muted" style={{ marginLeft: "auto" }}>{selAction.id}</span></div>
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
                {ir.hosts?.length ? (
                  <select value={selAction.target_host_ref ?? ""} onChange={(e) => patchAction(selAction.id, { target_host_ref: e.target.value || undefined })}>
                    <option value="">（未指定）</option>
                    {selAction.target_host_ref && !ir.hosts.some((h) => h.id === selAction.target_host_ref) && <option value={selAction.target_host_ref}>{selAction.target_host_ref}</option>}
                    {ir.hosts.map((h) => <option key={h.id} value={h.id}>{h.role} ({h.id})</option>)}
                  </select>
                ) : (
                  <input className="mono" value={selAction.target_host_ref ?? ""} onChange={(e) => patchAction(selAction.id, { target_host_ref: e.target.value || undefined })} />
                )}
              </label>
              <EpistemicSelect value={selAction.epistemic_status} onChange={(v) => patchAction(selAction.id, { epistemic_status: v })} />
              <div className="muted" style={{ fontSize: 12 }}>證據：{selAction.evidence_refs?.length ? selAction.evidence_refs.join("、") : "無"}</div>
              <div><button className="danger small" onClick={() => removeActions([selAction.id])}>刪除行為（連同相關連線）</button></div>
            </div>
          ) : selRelation ? (
            <div className="card">
              <div className="row"><h2>關係</h2><SourceTag source={selRelation.source} /><span className="mono muted" style={{ marginLeft: "auto" }}>{selRelation.id}</span></div>
              <div style={{ fontSize: 13 }}>
                {nameOf.get(selRelation.from_action) ?? selRelation.from_action} <span className="muted">→</span> {nameOf.get(selRelation.to_action) ?? selRelation.to_action}
              </div>
              <label className="field"><span>類型</span>
                <div className="seg">
                  {(["temporal", "dependency"] as RelationKind[]).map((k) => (
                    <button key={k} className={selRelation.kind === k ? "on" : ""} onClick={() => selRelation.kind !== k && patchRelation(selRelation.id, { kind: k })}>{KIND_LABEL[k]}</button>
                  ))}
                </div>
              </label>
              <div className="muted" style={{ fontSize: 12 }}>
                {selRelation.kind === "dependency" ? "依賴：沒有前一步，後一步無法進行。" : "時間先後：只記錄發生順序。若確定後者需要前者，請改為依賴。"}
              </div>
              <label className="field"><span>理由</span>
                <textarea rows={3} value={selRelation.rationale ?? ""} onChange={(e) => patchRelation(selRelation.id, { rationale: e.target.value || undefined })} />
              </label>
              <EpistemicSelect value={selRelation.epistemic_status} onChange={(v) => patchRelation(selRelation.id, { epistemic_status: v })} />
              <div><button className="danger small" onClick={() => removeRelations([selRelation.id])}>刪除關係</button></div>
            </div>
          ) : (
            <div className="card"><div className="muted" style={{ fontSize: 13 }}>點選節點或連線以編輯。<br />目前 {actions.length} 個行為、{relations.length} 條關係。</div></div>
          )}

          <div className="card">
            <h2>儲存版本</h2>
            <div className="muted" style={{ fontSize: 12 }}>目前版本 v{ir.ir_version ?? 1}。儲存會建立新版本，你改過的項目會標示為使用者來源。</div>
            <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="版本備註（選填）" disabled={save.busy} />
            {unnamed > 0 && <div className="status-PARTIAL" style={{ fontSize: 12 }}>有 {unnamed} 個行為沒有名稱，請先命名。</div>}
            <div className="row">
              <button className="primary" disabled={!dirty || save.busy || unnamed > 0} onClick={() => save.run()}>
                {save.busy ? <><span className="spinner" /> 儲存中…</> : "儲存為新版本"}
              </button>
              <button disabled={!dirty || save.busy} onClick={discard}>捨棄修改</button>
            </div>
            {savedMsg && <div className="status-PASS" style={{ fontSize: 12 }}>{savedMsg}</div>}
            <ApiNotice error={save.error} what="儲存版本" />
            {save.error && <div className="muted" style={{ fontSize: 12 }}>修改仍保留在畫面上，尚未寫入後端。</div>}
          </div>

          <div className="card">
            <h2>版本紀錄</h2>
            {versions.error ? <ApiNotice error={versions.error} what="版本紀錄" onRetry={() => versions.reload()} />
              : versions.loading && !versions.data ? <span className="muted"><span className="spinner" /> 載入中…</span>
              : versionRows.length === 0 ? <div className="muted" style={{ fontSize: 13 }}>尚無版本紀錄。</div>
              : (
                <div style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 12 }}>
                  {versionRows.map((v) => (
                    <div key={v.ir_version} className="row" style={{ gap: 8, flexWrap: "nowrap" }}>
                      <span className="mono" style={{ color: v.ir_version === ir.ir_version ? "var(--accent)" : undefined }}>v{v.ir_version}</span>
                      <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={v.note}>{v.note || "—"}</span>
                      <span className="muted nowrap">{fmtTime(v.ts)}</span>
                    </div>
                  ))}
                </div>
              )}
          </div>
        </div>
      </div>

      <NextStep prev={{ to: "/missing", label: "缺失補充" }} next={{ to: "/deps", label: "軟體依賴" }} />
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
