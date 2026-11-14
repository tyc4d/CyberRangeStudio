import { useMemo, useState } from "react";
import type { Action, EpistemicStatus, Evidence, Relation, ScenarioIR } from "@contracts";
import { api } from "../lib/api";
import { useLoad } from "../lib/hooks";
import { useScenario } from "../lib/scenario";
import {
  Empty, EPISTEMIC, EPISTEMIC_ORDER, EpistemicBadge, Metric, NextStep, Notice, PageHead, pct, ScenarioGate, SourceTag,
} from "../components/ui";

const attackId = (raw?: string) => raw?.match(/T\d{4}(?:\.\d{3})?/i)?.[0].toUpperCase();

const METHOD_LABEL: Record<string, string> = { single_pass: "單次分析", staged: "分階段", staged_review: "分階段＋複核" };

function EvidenceChips({ refs, active, onPick, known }: { refs?: string[]; active: string | null; onPick: (id: string) => void; known: Set<string> }) {
  if (!refs?.length) return <span className="muted" style={{ fontSize: 12 }}>無證據</span>;
  return (
    <>
      {refs.map((r) => (
        <span key={r} className={`chip ${active === r ? "on" : ""}`} title={known.has(r) ? "查看證據" : "找不到這筆證據"}
          style={known.has(r) ? undefined : { textDecoration: "line-through" }}
          onClick={(e) => { e.stopPropagation(); onPick(r); }}>{r}</span>
      ))}
    </>
  );
}

function Body({ ir }: { ir: ScenarioIR }) {
  const [filter, setFilter] = useState<EpistemicStatus | "all">("all");
  const [tab, setTab] = useState<"actions" | "relations">("actions");
  const [activeEv, setActiveEv] = useState<string | null>(null);
  const [focusRefs, setFocusRefs] = useState<string[] | null>(null);

  const evidence = ir.evidence ?? [];
  const evIds = useMemo(() => new Set(evidence.map((e) => e.id)), [evidence]);
  const actionName = useMemo(() => new Map(ir.actions.map((a) => [a.id, a.name])), [ir.actions]);
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const x of [...ir.actions, ...ir.relations]) c[x.epistemic_status] = (c[x.epistemic_status] ?? 0) + 1;
    return c;
  }, [ir]);

  // Official MITRE ATT&CK info for the technique ids used here (reference enrichment, not report facts).
  const attack = useLoad(() => api.getAttack(ir.id), [ir.id]);
  const attackMap = attack.data?.techniques ?? {};

  const match = (x: Action | Relation) => filter === "all" || x.epistemic_status === filter;
  const actions = ir.actions.filter(match);
  const relations = ir.relations.filter(match);
  const q = ir.quality;

  const pickEv = (id: string) => {
    setActiveEv(id);
    setFocusRefs(null);
    requestAnimationFrame(() => document.getElementById(`ev-${id}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" }));
  };
  const shownEvidence: Evidence[] = focusRefs ? evidence.filter((e) => focusRefs.includes(e.id)) : evidence;

  return (
    <div className="page">
      <PageHead title="分析結果" desc="每個項目都標示它在原文中的依據程度。「推測」與「原文未提」的項目不代表錯誤，但部署前值得再確認。" />

      {q?.provisional && <Notice kind="warn" title="暫定結果">後端標示這份分析為暫定（provisional），品質指標尚未完整。</Notice>}

      <div className="grid c4">
        <Metric k="引文核對率" v={pct(q?.quote_verified_rate)} hint="證據引文能在原文中逐字找到的比例" />
        <Metric k="無依據主張" v={q?.unsupported_claim_count} hint="沒有任何證據支持的主張數" />
        <Metric k="推測項目" v={q?.inferred_count} />
        <Metric k="原文未提項目" v={q?.absent_count} />
      </div>
      <div className="muted" style={{ fontSize: 12, marginTop: -6 }}>
        {q ? <>分析方式：{q.method ? METHOD_LABEL[q.method] ?? q.method : "未提供"}。引文核對率只代表引文確實出自原文，不代表推論內容正確。</> : "後端沒有提供品質指標。"}
      </div>

      <div className="row">
        <div className="seg" role="tablist">
          <button className={tab === "actions" ? "on" : ""} onClick={() => setTab("actions")}>攻擊行為 {ir.actions.length}</button>
          <button className={tab === "relations" ? "on" : ""} onClick={() => setTab("relations")}>關係 {ir.relations.length}</button>
        </div>
        <div className="seg" style={{ marginLeft: "auto" }}>
          <button className={filter === "all" ? "on" : ""} onClick={() => setFilter("all")}>全部</button>
          {EPISTEMIC_ORDER.map((s) => (
            <button key={s} className={filter === s ? "on" : ""} onClick={() => setFilter(s)} title={EPISTEMIC[s].hint}>
              {EPISTEMIC[s].label} {counts[s] ?? 0}
            </button>
          ))}
        </div>
      </div>

      <div className="grid" style={{ gridTemplateColumns: "minmax(0, 1.7fr) minmax(280px, 1fr)", alignItems: "start" }}>
        <div className="card flush" style={{ overflowX: "auto" }}>
          {tab === "actions" ? (
            actions.length === 0 ? <Empty>{ir.actions.length ? "沒有符合篩選條件的攻擊行為。" : "這份分析沒有抽取到攻擊行為。"}</Empty> : (
              <table className="tbl">
                <thead><tr><th>攻擊行為</th><th>ATT&CK</th><th>依據</th><th>來源</th><th>證據</th></tr></thead>
                <tbody>
                  {actions.map((a) => (
                    <tr key={a.id} className="clickable" onClick={() => { setFocusRefs(a.evidence_refs ?? []); setActiveEv(null); }}>
                      <td>
                        <div style={{ fontWeight: 600 }}>{a.name}</div>
                        {a.description && <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>{a.description}</div>}
                        {a.target_host_ref && <div className="mono muted" style={{ marginTop: 2 }}>目標：{a.target_host_ref}</div>}
                      </td>
                      <td className="nowrap">
                        {(() => {
                          if (!a.attack_technique) return <span className="muted">—</span>;
                          const info = attackMap[attackId(a.attack_technique) ?? ""];
                          const tactics = info?.tactics?.length ? info.tactics.join(" / ") : a.attack_tactic;
                          return (
                            <>
                              {info ? (
                                <a className="mono" href={info.url} target="_blank" rel="noreferrer"
                                  title={info.description} onClick={(e) => e.stopPropagation()}>{info.id}</a>
                              ) : <span className="mono">{a.attack_technique}</span>}
                              {info && <div style={{ fontSize: 12 }}>{info.name}</div>}
                              {tactics && <div className="muted" style={{ fontSize: 12 }}>{tactics}</div>}
                              {info && <div className="muted" style={{ fontSize: 11 }}>官方 ATT&amp;CK</div>}
                            </>
                          );
                        })()}
                      </td>
                      <td><EpistemicBadge status={a.epistemic_status} /></td>
                      <td><SourceTag source={a.source} /></td>
                      <td><EvidenceChips refs={a.evidence_refs} active={activeEv} onPick={pickEv} known={evIds} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )
          ) : relations.length === 0 ? <Empty>{ir.relations.length ? "沒有符合篩選條件的關係。" : "這份分析沒有抽取到行為之間的關係。"}</Empty> : (
            <table className="tbl">
              <thead><tr><th>從</th><th>類型</th><th>到</th><th>理由</th><th>依據</th><th>來源</th><th>證據</th></tr></thead>
              <tbody>
                {relations.map((r) => (
                  <tr key={r.id} className="clickable" onClick={() => { setFocusRefs(r.evidence_refs ?? []); setActiveEv(null); }}>
                    <td>{actionName.get(r.from_action) ?? <span className="mono muted">{r.from_action}</span>}</td>
                    <td><span className={`tag ${r.kind === "dependency" ? "dep" : "temporal"}`}>{r.kind === "dependency" ? "依賴" : "時間先後"}</span></td>
                    <td>{actionName.get(r.to_action) ?? <span className="mono muted">{r.to_action}</span>}</td>
                    <td className="muted" style={{ fontSize: 12 }}>{r.rationale ?? "—"}</td>
                    <td><EpistemicBadge status={r.epistemic_status} /></td>
                    <td><SourceTag source={r.source} /></td>
                    <td><EvidenceChips refs={r.evidence_refs} active={activeEv} onPick={pickEv} known={evIds} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="card flush" style={{ position: "sticky", top: 0 }}>
          <div className="card-head">
            <h2>原文證據</h2>
            <span className="muted" style={{ fontSize: 12 }}>{shownEvidence.length} / {evidence.length}</span>
            {focusRefs && <div className="right"><button className="small" onClick={() => setFocusRefs(null)}>顯示全部</button></div>}
          </div>
          <div style={{ maxHeight: "62vh", overflow: "auto", padding: 12, display: "flex", flexDirection: "column", gap: 12 }}>
            {evidence.length === 0 ? <Empty>這份分析沒有附原文證據。</Empty>
              : shownEvidence.length === 0 ? <Empty>所選項目沒有對應的證據。</Empty>
              : shownEvidence.map((e) => (
                <div key={e.id} id={`ev-${e.id}`}>
                  <div className="row" style={{ gap: 8, marginBottom: 4 }}>
                    <span className={`chip ${activeEv === e.id ? "on" : ""}`} style={{ cursor: "default" }}>{e.id}</span>
                    {e.locator?.ref && <span className="muted mono">{e.locator.kind ?? "位置"} {e.locator.ref}</span>}
                    {(() => {
                      // Graded source support: exact/strong verify; partial = keyword/fragment; none = not found.
                      const level = e.quote_match ?? (e.quote_verified === true ? "exact" : e.quote_verified === false ? "none" : undefined);
                      if (!level) return null;
                      const tip = e.matched_text ? `原文對應片段：${e.matched_text}` : undefined;
                      if (level === "exact") return <span className="status-PASS" style={{ fontSize: 12 }} title={tip}>✓ 原文逐字核對</span>;
                      if (level === "strong") return <span className="status-PASS" style={{ fontSize: 12 }} title={tip}>✓ 原文高度相符</span>;
                      if (level === "partial") return <span className="status-PARTIAL" style={{ fontSize: 12 }} title={tip}>～ 關鍵字／片段相符</span>;
                      return <span className="status-FAIL" style={{ fontSize: 12 }} title={tip}>✗ 原文找不到此引文</span>;
                    })()}
                  </div>
                  <blockquote className="quote" style={activeEv === e.id ? { borderLeftColor: "var(--accent)" } : undefined}>{e.quote}</blockquote>
                </div>
              ))}
          </div>
        </div>
      </div>

      <NextStep prev={{ to: "/import", label: "情資匯入" }} next={{ to: "/missing", label: "缺失補充" }} />
    </div>
  );
}

export function AnalysisPage() {
  const { ir } = useScenario();
  return <ScenarioGate title="分析結果">{ir && <Body ir={ir} />}</ScenarioGate>;
}
