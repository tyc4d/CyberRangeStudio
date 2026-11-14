import { useMemo, useState } from "react";
import type { Action, EpistemicStatus, Evidence, Relation, ScenarioIR } from "@contracts";
import { api } from "../lib/api";
import { useLoad } from "../lib/hooks";
import { useScenario } from "../lib/scenario";
import {
  CitationBadge, Empty, EPISTEMIC, EPISTEMIC_ORDER, EpistemicBadge, isImported, Metric, NextStep, Notice, PageHead, QUOTE_LEVEL, quoteLevel,
  QuoteSnippet, ScenarioGate, SourceTag, summarizeCitations,
} from "../components/ui";

const attackId = (raw?: string) => raw?.match(/T\d{4}(?:\.\d{3})?/i)?.[0].toUpperCase();

const METHOD_LABEL: Record<string, string> = { single_pass: "單次分析", staged: "分階段", staged_review: "分階段＋複核" };

// ---- B4: can each step be rebuilt in this deployment? Honest degradation — a stand-in is never called a reproduction. ----
type Repro = NonNullable<Action["reproducibility"]>;
/** Worst first: the scenario as a whole is only as reproducible as its weakest step. */
const REPRO_ORDER: Repro[] = ["not_reproducible", "needs_vm", "substitute_only", "reproducible"];
const REPRO: Record<Repro, { label: string; cls: string; hint: string }> = {
  reproducible: { label: "可重現", cls: "badge supported", hint: "目錄有對應元件，本環境可以建置並檢查這一步。這不代表攻擊已經執行或驗證通過。" },
  substitute_only: { label: "只能替身", cls: "tag sub", hint: "只能用不同的實作當替身，檢查有限的連線或服務概念；這不是原步驟的重現。" },
  needs_vm: { label: "需 Windows VM", cls: "badge inferred", hint: "這一步需要 Windows VM；本部署環境尚未具備，目前無法重現。" },
  not_reproducible: { label: "無法重現", cls: "badge insufficient", hint: "目錄沒有對應元件，無法重現。" },
};
/** The backend may not send the field yet (or may send something unknown) — anything unrecognised counts as "not judged". */
function reproOf(a: Action): Repro | null {
  const v: unknown = (a as { reproducibility?: unknown }).reproducibility;
  return typeof v === "string" && Object.prototype.hasOwnProperty.call(REPRO, v) ? (v as Repro) : null;
}
function reproReason(a: Action): string | null {
  const v: unknown = (a as { reproducibility_reason?: unknown }).reproducibility_reason;
  return typeof v === "string" && v.trim() ? v.trim() : null;
}

function ReproBadge({ action }: { action: Action }) {
  const r = reproOf(action);
  if (!r) return <span className="badge absent" style={{ cursor: "help" }} title="後端尚未回報這一步能不能重現；未判定不等於可重現。">尚未判定</span>;
  const reason = reproReason(action);
  return <span className={REPRO[r].cls} style={{ cursor: "help" }} title={reason ? `${REPRO[r].hint}\n理由：${reason}` : REPRO[r].hint}>{REPRO[r].label}</span>;
}

/** Scenario-level verdict. Hidden entirely until the backend reports reproducibility for at least one step. */
function ReproBanner({ actions }: { actions: Action[] }) {
  const c: Record<Repro, number> = { reproducible: 0, substitute_only: 0, needs_vm: 0, not_reproducible: 0 };
  let unknown = 0;
  for (const a of actions) { const r = reproOf(a); if (r) c[r] += 1; else unknown += 1; }
  const total = actions.length;
  if (total === 0 || unknown === total) return null;
  const lowest = REPRO_ORDER.find((r) => c[r] > 0)!;
  const allOk = c.reproducible === total;
  const parts = [
    c.substitute_only > 0 && `${c.substitute_only} 步只能用替身（替身不算重現）`,
    c.needs_vm > 0 && `${c.needs_vm} 步需要 Windows VM（本部署環境尚未具備，目前無法重現）`,
    c.not_reproducible > 0 && `${c.not_reproducible} 步無法重現（目錄沒有對應元件）`,
    unknown > 0 && `${unknown} 步尚未判定（不計入可重現）`,
  ].filter(Boolean);
  return (
    <Notice kind={allOk ? "info" : "warn"} title={`本情境 ${c.reproducible}/${total} 步可重現`}>
      <div data-testid="repro-banner">
        {parts.length > 0 && <div>其餘：{parts.join("；")}。</div>}
        <div>
          整體判定取最弱的一步：<b>{allOk ? REPRO.reproducible.label : unknown > 0 && lowest === "reproducible" ? "尚未判定完" : REPRO[lowest].label}</b>
          {!allOk && "，所以整個情境目前不能算可重現"}。
          「可重現」只表示本環境能建置並檢查該步驟，不代表攻擊已經執行或驗證通過。各步驟理由請把游標移到下表的徽章上。
        </div>
      </div>
    </Notice>
  );
}

/** The quotes behind one row: each shown as its match mark plus its opening words, so nobody has to decode "evidence-1". */
function EvidenceChips({ refs, active, onPick, byId }: { refs?: string[]; active: string | null; onPick: (id: string) => void; byId: Map<string, Evidence> }) {
  if (!refs?.length) return null;
  return (
    <>
      {refs.map((r) => (
        <span key={r} className={`chip ${active === r ? "on" : ""}`} style={{ display: "block", fontFamily: "inherit", padding: "2px 6px", margin: "0 0 4px", lineHeight: 1.5 }}
          onClick={(e) => { e.stopPropagation(); onPick(r); }}><QuoteSnippet evidence={byId.get(r)} id={r} /></span>
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
  const evById = useMemo(() => new Map(evidence.map((e) => [e.id, e])), [evidence]);
  const actionName = useMemo(() => new Map(ir.actions.map((a) => [a.id, a.name])), [ir.actions]);
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const x of [...ir.actions, ...ir.relations]) c[x.epistemic_status] = (c[x.epistemic_status] ?? 0) + 1;
    return c;
  }, [ir]);
  // Per-level breakdown of how well each evidence quote matches the source (graded, not a single rate).
  const evMatch = useMemo(() => {
    const c = { exact: 0, strong: 0, partial: 0, none: 0 };
    for (const e of evidence) { const lvl = quoteLevel(e); if (lvl) c[lvl] += 1; }
    return c;
  }, [evidence]);
  const evTotal = evMatch.exact + evMatch.strong + evMatch.partial + evMatch.none;
  // The one set of headline numbers: every step falls in exactly one bucket, so the tiles always add up to the step count.
  const steps = useMemo(() => {
    const c = { all: 0, some: 0, none: 0, empty: 0, ungraded: 0 };
    for (const a of ir.actions) c[summarizeCitations(a.evidence_refs, evById).state] += 1;
    return c;
  }, [ir.actions, evById]);
  // An imported STIX / Attack Flow file carries no report text to check quotes against.
  const imported = ir.provenance?.input_kind === "stix2.1" || (ir.actions.length > 0 && ir.actions.every((a) => isImported(a.source)));
  const noQuotes = evidence.length === 0;
  const tile = (n: number) => (noQuotes ? undefined : n);

  // Official MITRE ATT&CK info for the technique ids used here (reference enrichment, not report facts).
  const attack = useLoad(() => api.getAttack(ir.id), [ir.id]);
  const attackMap = attack.data?.techniques ?? {};

  const match = (x: Action | Relation) => filter === "all" || x.epistemic_status === filter;
  const actions = ir.actions.filter(match);
  const relations = ir.relations.filter(match);
  const q = ir.quality;
  // Only show the reproducibility column once the backend reports it for at least one step.
  const hasRepro = useMemo(() => ir.actions.some((a) => reproOf(a) !== null), [ir.actions]);
  const cite = (x: Action | Relation) => summarizeCitations(x.evidence_refs, evById);

  const pickEv = (id: string) => {
    setActiveEv(id);
    setFocusRefs(null);
    requestAnimationFrame(() => document.getElementById(`ev-${id}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" }));
  };
  const shownEvidence: Evidence[] = focusRefs ? evidence.filter((e) => focusRefs.includes(e.id)) : evidence;

  return (
    <div className="page">
      <PageHead title="分析結果" />

      {q?.provisional && <Notice kind="warn" title="暫定結果">後端標示這份分析為暫定（provisional），品質指標尚未完整。</Notice>}

      {noQuotes && (
        <Notice title={imported ? "這個情境來自匯入檔，沒有原文引文可核對" : "這份分析沒有附原文引文"}>
          {imported
            ? "內容直接取自匯入的 STIX／Attack Flow 檔。下面的步驟標示為「來自匯入檔」，代表它們寫在匯入檔裡，不代表已經和任何報告原文核對過。"
            : "沒有引文就無法核對步驟是否有原文依據，下面的指標因此留空。"}
        </Notice>
      )}
      <div className="grid c3" style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))" }}>
        <Metric k="全部引文成立的步驟" v={tile(steps.all)} placeholder="不適用" hint="這個步驟附的每一句引文，都能在原文找到（逐字或高度相符）" />
        <Metric k="部分引文成立的步驟" v={tile(steps.some)} placeholder="不適用" hint="有的引文對得上原文，有的對不上或只對上片段" />
        <Metric k="引文都沒對上的步驟" v={tile(steps.none)} placeholder="不適用" hint="附了引文，但沒有一句能在原文找到；需要人工對照原文" />
      </div>
      <div className="muted" style={{ fontSize: 12, marginTop: -6 }}>
        共 {ir.actions.length} 個步驟
        {!noQuotes && steps.empty > 0 && `，另有 ${steps.empty} 個沒有附引文`}
        {!noQuotes && steps.ungraded > 0 && `，另有 ${steps.ungraded} 個的引文後端沒有回報核對結果`}
        {noQuotes && ir.actions.length > 0 && "，都沒有附引文"}
        。以上只算步驟；每一句引文的核對結果見下一行與右側。
      </div>

      {evTotal > 0 && (
        <div className="row" style={{ gap: 10, marginTop: -6, flexWrap: "wrap", alignItems: "center" }}>
          <span className="muted" style={{ fontSize: 12 }}>{evTotal} 句引文</span>
          {(["exact", "strong", "partial", "none"] as const).map((l) => (
            <span key={l} className={QUOTE_LEVEL[l].cls} style={{ fontSize: 12 }} title={QUOTE_LEVEL[l].desc}>{QUOTE_LEVEL[l].mark} {QUOTE_LEVEL[l].word} {evMatch[l]}</span>
          ))}
        </div>
      )}
      {q?.method && <div className="muted" style={{ fontSize: 12, marginTop: -6 }}>分析方式：{METHOD_LABEL[q.method] ?? q.method}</div>}

      <ReproBanner actions={ir.actions} />

      <div className="row">
        <div className="seg" role="tablist">
          <button className={tab === "actions" ? "on" : ""} onClick={() => setTab("actions")}>攻擊行為 {ir.actions.length}</button>
          <button className={tab === "relations" ? "on" : ""} onClick={() => setTab("relations")}>關係 {ir.relations.length}</button>
        </div>
        <div className="seg" style={{ marginLeft: "auto" }}>
          <button className={filter === "all" ? "on" : ""} onClick={() => setFilter("all")}>全部</button>
          {EPISTEMIC_ORDER.map((s) => (
            <button key={s} className={filter === s ? "on" : ""} onClick={() => setFilter(s)} title={EPISTEMIC[s].hint}>
              {imported && s === "supported" ? "來自匯入檔" : EPISTEMIC[s].label} {counts[s] ?? 0}
            </button>
          ))}
        </div>
      </div>

      <div className="grid" style={{ gridTemplateColumns: "minmax(0, 1.7fr) minmax(280px, 1fr)", alignItems: "start" }}>
        <div className="card flush" style={{ overflowX: "auto" }}>
          {tab === "actions" ? (
            actions.length === 0 ? <Empty>{ir.actions.length ? "沒有符合篩選條件的攻擊行為。" : "這份分析沒有抽取到攻擊行為。"}</Empty> : (
              <table className="tbl" style={{ tableLayout: "fixed", width: "100%", minWidth: hasRepro ? 760 : 640 }}>
                <colgroup><col /><col style={{ width: 170 }} /><col style={{ width: 118 }} />{hasRepro && <col style={{ width: 120 }} />}<col style={{ width: 230 }} /></colgroup>
                <thead><tr><th>攻擊行為</th><th>ATT&CK</th><th>主張狀態</th>{hasRepro && <th title="本部署環境能不能建置並檢查這一步；不代表攻擊已執行">可否重現</th>}<th>引文核對</th></tr></thead>
                <tbody>
                  {actions.map((a) => (
                    <tr key={a.id} className="clickable" onClick={() => { setFocusRefs(a.evidence_refs ?? []); setActiveEv(null); }}>
                      <td>
                        <div style={{ fontWeight: 600 }}>{a.name}</div>
                        {a.description && <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>{a.description}</div>}
                        {a.target_host_ref && <div className="mono muted" style={{ marginTop: 2 }}>目標：{a.target_host_ref}</div>}
                      </td>
                      <td style={{ overflowWrap: "anywhere" }}>
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
                      <td className="nowrap"><EpistemicBadge status={a.epistemic_status} source={a.source} /><div style={{ marginTop: 4 }}><SourceTag source={a.source} /></div></td>
                      {hasRepro && <td className="nowrap"><ReproBadge action={a} /></td>}
                      <td>
                        <div style={{ marginBottom: 5 }}><CitationBadge summary={cite(a)} source={a.source} /></div>
                        <EvidenceChips refs={a.evidence_refs} active={activeEv} onPick={pickEv} byId={evById} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )
          ) : relations.length === 0 ? <Empty>{ir.relations.length ? "沒有符合篩選條件的關係。" : "這份分析沒有抽取到行為之間的關係。"}</Empty> : (
            <table className="tbl" style={{ tableLayout: "fixed", width: "100%", minWidth: 700 }}>
              <colgroup><col /><col style={{ width: 84 }} /><col /><col /><col style={{ width: 118 }} /><col style={{ width: 210 }} /></colgroup>
              <thead><tr><th>從</th><th>類型</th><th>到</th><th>理由</th><th>主張狀態</th><th>引文核對</th></tr></thead>
              <tbody>
                {relations.map((r) => (
                  <tr key={r.id} className="clickable" onClick={() => { setFocusRefs(r.evidence_refs ?? []); setActiveEv(null); }}>
                    <td>{actionName.get(r.from_action) ?? <span className="mono muted">{r.from_action}</span>}</td>
                    <td><span className={`tag ${r.kind === "dependency" ? "dep" : "temporal"}`}>{r.kind === "dependency" ? "依賴" : "時間先後"}</span></td>
                    <td>{actionName.get(r.to_action) ?? <span className="mono muted">{r.to_action}</span>}</td>
                    <td className="muted" style={{ fontSize: 12 }}>{r.rationale ?? "—"}</td>
                    <td className="nowrap"><EpistemicBadge status={r.epistemic_status} source={r.source} /><div style={{ marginTop: 4 }}><SourceTag source={r.source} /></div></td>
                    <td>
                      <div style={{ marginBottom: 5 }}><CitationBadge summary={cite(r)} source={r.source} /></div>
                      <EvidenceChips refs={r.evidence_refs} active={activeEv} onPick={pickEv} byId={evById} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="card flush" style={{ position: "sticky", top: 0 }}>
          <div className="card-head">
            <h2>原文引文</h2>
            <span className="muted" style={{ fontSize: 12 }}>{shownEvidence.length} / {evidence.length}</span>
            {focusRefs && <div className="right"><button className="small" onClick={() => setFocusRefs(null)}>顯示全部</button></div>}
          </div>
          <div style={{ maxHeight: "62vh", overflow: "auto", padding: 12, display: "flex", flexDirection: "column", gap: 12 }}>
            {evidence.length === 0 ? <Empty>{imported ? "匯入檔沒有附原文引文。" : "這份分析沒有附原文引文。"}</Empty>
              : shownEvidence.length === 0 ? <Empty>所選項目沒有附引文。</Empty>
              : shownEvidence.map((e) => (
                <div key={e.id} id={`ev-${e.id}`}>
                  <div className="row" style={{ gap: 8, marginBottom: 4 }}>
                    {(() => {
                      // Graded source support first — the id is only a handle, so it comes last and small.
                      const level = quoteLevel(e);
                      if (!level) return <span className="muted" style={{ fontSize: 12 }} title="後端沒有回報這句引文的核對結果">· 未核對</span>;
                      const M = QUOTE_LEVEL[level];
                      const tip = e.matched_text ? `${M.desc}\n原文片段：${e.matched_text}` : M.desc;
                      return <span className={M.cls} style={{ fontSize: 12, fontWeight: 700 }} title={tip}>{M.mark} {M.word}</span>;
                    })()}
                    {e.locator?.ref && <span className="muted mono">{e.locator.kind ?? "位置"} {e.locator.ref}</span>}
                    <span className="muted mono" style={{ marginLeft: "auto", fontSize: 11 }}>{e.id}</span>
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
