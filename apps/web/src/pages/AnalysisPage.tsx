import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { joinList, live, t } from "../i18n";
import { createPortal } from "react-dom";
import type { Action, EpistemicStatus, Evidence, Relation, ScenarioIR } from "@contracts";
import { api } from "../lib/api";
import { useLoad } from "../lib/hooks";
import { useScenario } from "../lib/scenario";
import {
  CitationBadge, Empty, EPISTEMIC, EPISTEMIC_ORDER, EpistemicBadge, IMPORTED, isImported, Metric, NextStep, Notice, PageHead, QUOTE_LEVEL, quoteLevel,
  locatorText, QuoteSnippet, ScenarioGate, SourceTag, summarizeCitations,
} from "../components/ui";
import { PdfViewer, usePdfSource, type PdfAnchor, type PdfLocateResult } from "../components/PdfViewer";

const attackId = (raw?: string) => raw?.match(/T\d{4}(?:\.\d{3})?/i)?.[0].toUpperCase();

const METHOD_LABEL: Record<string, string> = live(() => ({ single_pass: t("an.m.single"), staged: t("an.m.staged"), staged_review: t("an.m.review") }));

// ---- B4: can each step be rebuilt in this deployment? Honest degradation — a stand-in is never called a reproduction. ----
type Repro = NonNullable<Action["reproducibility"]>;
/** Worst first: the scenario as a whole is only as reproducible as its weakest step. */
const REPRO_ORDER: Repro[] = ["not_reproducible", "needs_vm", "substitute_only", "reproducible"];
const REPRO: Record<Repro, { label: string; cls: string; hint: string }> = live(() => ({
  reproducible: { label: t("an.r.ok"), cls: "badge supported", hint: t("an.r.ok.hint") },
  substitute_only: { label: t("an.r.sub"), cls: "tag sub", hint: t("an.r.sub.hint") },
  needs_vm: { label: t("an.r.vm"), cls: "badge inferred", hint: t("an.r.vm.hint") },
  not_reproducible: { label: t("an.r.no"), cls: "badge insufficient", hint: t("an.r.no.hint") },
}));
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
  if (!r) return <span className="badge absent" style={{ cursor: "help" }} title={t("an.r.unknown.hint")}>{t("an.r.unknown")}</span>;
  const reason = reproReason(action);
  return <span className={REPRO[r].cls} style={{ cursor: "help" }} title={reason ? `${REPRO[r].hint}\n${t("an.r.reason", { reason })}` : REPRO[r].hint}>{REPRO[r].label}</span>;
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
    c.substitute_only > 0 && t("an.r.partSub", { n: c.substitute_only }),
    c.needs_vm > 0 && t("an.r.partVm", { n: c.needs_vm }),
    c.not_reproducible > 0 && t("an.r.partNo", { n: c.not_reproducible }),
    unknown > 0 && t("an.r.partUnknown", { n: unknown }),
  ].filter((x): x is string => !!x);
  return (
    <Notice kind={allOk ? "info" : "warn"} title={t("an.r.title", { ok: c.reproducible, total })}>
      <div data-testid="repro-banner">
        {parts.length > 0 && <div>{t("an.r.others", { parts: joinList(parts) })}</div>}
        <div>
          {t("an.r.overall")} <b>{allOk ? REPRO.reproducible.label : unknown > 0 && lowest === "reproducible" ? t("an.r.notDone") : REPRO[lowest].label}</b>
          {!allOk && ` ${t("an.r.notWhole")}`}
        </div>
        <div className="muted" style={{ fontSize: 13 }}>{t("an.r.meaning")}
        </div>
      </div>
    </Notice>
  );
}

/** The quotes behind one row: each shown as its match mark plus its opening words, so nobody has to decode "evidence-1". */
function EvidenceChips({ refs, active, onPick, byId, basis }: { refs?: string[]; active: string | null; onPick: (id: string) => void; byId: Map<string, Evidence>; basis?: boolean }) {
  if (!refs?.length) return null;
  return (
    <>
      {refs.map((r) => (
        <span key={r} className={`chip ${active === r ? "on" : ""}`} style={{ display: "block", fontFamily: "inherit", padding: "2px 6px", margin: "0 0 4px", lineHeight: 1.5 }}
          onClick={(e) => { e.stopPropagation(); onPick(r); }}><QuoteSnippet evidence={byId.get(r)} id={r} basis={basis} /></span>
      ))}
    </>
  );
}

/** An inferred claim's quotes are the basis for the inference, not direct evidence — no pass/fail verdict applies. */
const isInferred = (x: { epistemic_status?: unknown }) => x.epistemic_status === "inferred";
/** The analysis sometimes names a host "unknown" (as id or role) when it could not tell which machine a step ran on. */
const isPlaceholder = (s: unknown) => typeof s !== "string" || /^(unknown|unspecified|n\/a|none|null|未知|不明)?$/i.test(s.trim()); // i18n-ignore: matches data values

/** Result of looking one quote up in the PDF original. */
type PdfFind = { state: "searching" } | { state: "found"; page: number; partial: boolean } | { state: "notfound" };

/** The PDF original in a side drawer, with one quote located and highlighted — so "對照原文" can be done on this page. */
function PdfDrawer({ data, evidence, anchor, find, onLocated, onClose }: {
  data: ArrayBuffer; evidence: Evidence; anchor: PdfAnchor; find?: PdfFind;
  onLocated: (r: PdfLocateResult) => void; onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const quote = (evidence.quote ?? "").replace(/\s+/g, " ").trim();
  // Portalled to <body>: the page container is animated (transformed), which would otherwise capture `position: fixed`
  // and let the drawer scroll away under the top bar.
  return createPortal(
    <div role="dialog" aria-label={t("an.pdf.dialog")} data-testid="analysis-pdf-drawer"
      style={{
        position: "fixed", top: 0, right: 0, bottom: 0, width: "min(760px, 94vw)", zIndex: 1000, display: "flex", flexDirection: "column", gap: 8,
        padding: 12, background: "var(--bg-elev)", borderLeft: "1px solid var(--border)", boxShadow: "var(--elevation)",
      }}>
      <div className="row" style={{ gap: 8 }}>
        <b>{t("an.pdf.title")}</b>
        <button className="small" style={{ marginLeft: "auto" }} onClick={onClose}>{t("an.close")}</button>
      </div>
      <blockquote className="quote" style={{ margin: 0, maxHeight: 84, overflow: "auto" }}>{quote}</blockquote>
      <div className="pdf-hint" role="status" data-testid="analysis-pdf-located">
        {!find || find.state === "searching" ? t("an.pdf.searching")
          : find.state === "found" ? t(find.partial ? "an.pdf.foundPartial" : "an.pdf.found", { page: find.page })
          : t("an.pdf.notFound")}
      </div>
      {/* One grid row that takes the remaining height, so the viewer scrolls inside the drawer. */}
      <div style={{ flex: 1, minHeight: 0, display: "grid", gridTemplateRows: "minmax(0, 1fr)" }}>
        <PdfViewer data={data} filename={t("pdf.original")} anchor={anchor} onLocated={onLocated} />
      </div>
    </div>,
    document.body,
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
    // Only the tab on screen: the number on a filter button is the number of rows that button will show.
    for (const x of tab === "actions" ? ir.actions : ir.relations) c[x.epistemic_status] = (c[x.epistemic_status] ?? 0) + 1;
    return c;
  }, [ir, tab]);
  // Per-level breakdown of how well each evidence quote matches the source (graded, not a single rate).
  const evMatch = useMemo(() => {
    const c = { exact: 0, strong: 0, partial: 0, none: 0 };
    for (const e of evidence) { const lvl = quoteLevel(e); if (lvl) c[lvl] += 1; }
    return c;
  }, [evidence]);
  const evTotal = evMatch.exact + evMatch.strong + evMatch.partial + evMatch.none;
  // The one set of headline numbers: every step falls in exactly one bucket, so the tiles always add up to the step count.
  const steps = useMemo(() => {
    // `fragment` = no quote fully holds, but at least one matched as a fragment (so it is not "not found").
    // `inferred` steps are kept out: their quotes are the basis for an inference, not evidence to grade.
    const c = { all: 0, some: 0, fragment: 0, none: 0, empty: 0, ungraded: 0, inferred: 0 };
    for (const a of ir.actions) {
      if (isInferred(a)) { c.inferred += 1; continue; }
      const s = summarizeCitations(a.evidence_refs, evById);
      c[s.state === "some" && s.ok === 0 ? "fragment" : s.state] += 1;
    }
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
  const qx = q as { excluded_non_attacker_actions?: { id?: string; name?: string; actor?: string }[]; dropped_placeholder_hosts?: number } | undefined;
  const excluded = Array.isArray(qx?.excluded_non_attacker_actions) ? qx!.excluded_non_attacker_actions! : [];
  const dropped = typeof qx?.dropped_placeholder_hosts === "number" ? qx.dropped_placeholder_hosts : 0;
  // Only show the reproducibility column once the backend reports it for at least one step.
  const hasRepro = useMemo(() => ir.actions.some((a) => reproOf(a) !== null), [ir.actions]);
  const cite = (x: Action | Relation) => summarizeCitations(x.evidence_refs, evById);

  // Which machine a step targets, in words: the host's role instead of its internal id ("h1"), and never a bare "unknown".
  const hostById = useMemo(() => new Map((Array.isArray(ir.hosts) ? ir.hosts : []).map((h) => [h.id, h])), [ir.hosts]);
  const stepNo = useMemo(() => new Map(ir.actions.map((a, i) => [a.id, i + 1])), [ir.actions]);
  const target = (a: Action): { text: string; hint: string } | null => {
    const ref = a.target_host_ref;
    if (ref === undefined || ref === null || ref === "") return null;
    const host = hostById.get(ref);
    const role = typeof host?.role === "string" ? host.role.trim() : "";
    if (isPlaceholder(ref) || (host && isPlaceholder(role)))
      return { text: t("an.unknownHost", { n: stepNo.get(a.id) ?? "?" }), hint: t("an.unknownHost.hint") };
    return { text: role || String(ref), hint: t("an.hostId", { ref }) };
  };

  // "在 PDF 中查看": the same viewer and locating as the 缺失補充 page, opened in a drawer for one quote.
  const pdf = usePdfSource(ir.id);
  const seqRef = useRef(0);
  const pendingPdf = useRef<{ id: string; seq: number } | null>(null);
  const [pdfView, setPdfView] = useState<{ id: string; anchor: PdfAnchor } | null>(null);
  const [pdfFound, setPdfFound] = useState<Record<string, PdfFind>>({});
  const viewInPdf = (e: Evidence) => {
    const seq = ++seqRef.current;
    // One group = one passage: the source wording the backend matched (if any), then the quote itself.
    const texts = [e.matched_text, e.quote].filter((t): t is string => typeof t === "string" && t.trim().length > 0);
    pendingPdf.current = { id: e.id, seq };
    setActiveEv(e.id);
    setPdfFound((m) => ({ ...m, [e.id]: { state: "searching" } }));
    setPdfView({ id: e.id, anchor: { groups: [texts], seq } });
  };
  const onPdfLocated = useCallback((r: PdfLocateResult) => {
    const p = pendingPdf.current;
    if (!p || p.seq !== r.seq) return;
    setPdfFound((m) => ({ ...m, [p.id]: r.found ? { state: "found", page: r.page, partial: r.partial } : { state: "notfound" } }));
  }, []);
  const closePdf = useCallback(() => setPdfView(null), []);
  const pdfEvidence = pdfView ? evById.get(pdfView.id) : undefined;

  const pickEv = (id: string) => {
    setActiveEv(id);
    setFocusRefs(null);
    requestAnimationFrame(() => document.getElementById(`ev-${id}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" }));
  };
  const shownEvidence: Evidence[] = focusRefs ? evidence.filter((e) => focusRefs.includes(e.id)) : evidence;

  return (
    <div className="page">
      <PageHead title={t("an.title")} />

      {q?.provisional && (
        <Notice kind="warn" title={t("an.prov.title")}>
          <div>{t("an.prov.body")}</div>
          <div>{t("an.prov.next")}</div>
        </Notice>
      )}

      {noQuotes && (
        <Notice title={imported ? t("an.noQuotes.imported") : t("an.noQuotes")}>
          {imported
            ? t("an.noQuotes.importedBody")
            : t("an.noQuotes.body")}
        </Notice>
      )}
      <div className="grid c4">
        <Metric k={t("an.k.all")} v={tile(steps.all)} placeholder={t("an.na")} hint={t("an.k.all.hint")} />
        <Metric k={t("an.k.some")} v={tile(steps.some)} placeholder={t("an.na")} hint={t("an.k.some.hint")} />
        <Metric k={t("an.k.frag")} v={tile(steps.fragment)} placeholder={t("an.na")} hint={t("an.k.frag.hint")} />
        <Metric k={t("an.k.none")} v={tile(steps.none)} placeholder={t("an.na")} hint={t("an.k.none.hint")} />
      </div>
      <div className="muted" style={{ fontSize: 13, marginTop: -6 }}>
        {[
          t("an.steps", { n: ir.actions.length }),
          !noQuotes && steps.inferred > 0 && t("an.steps.inferred", { n: steps.inferred }),
          !noQuotes && steps.empty > 0 && t("an.steps.empty", { n: steps.empty }),
          !noQuotes && steps.ungraded > 0 && t("an.steps.ungraded", { n: steps.ungraded }),
          noQuotes && ir.actions.length > 0 && t("an.steps.noQuotes"),
        ].filter(Boolean).join(" · ")}
      </div>

      {evTotal > 0 && (
        <div className="row" style={{ gap: 10, marginTop: -6, flexWrap: "wrap", alignItems: "center" }}>
          <span className="muted" style={{ fontSize: 13 }}>{t("an.quotes", { n: evTotal })}</span>
          {(["exact", "strong", "partial", "none"] as const).map((l) => (
            <span key={l} className={QUOTE_LEVEL[l].cls} style={{ fontSize: 13 }} title={QUOTE_LEVEL[l].desc}>{QUOTE_LEVEL[l].mark} {QUOTE_LEVEL[l].word} {evMatch[l]}</span>
          ))}
        </div>
      )}
      {excluded.length > 0 && (
        <details className="card" data-testid="excluded-actions">
          <summary style={{ cursor: "pointer", fontSize: 14 }}>{t("an.excluded", { n: excluded.length })}</summary>
          <ul style={{ margin: "8px 0 0", paddingLeft: 18, fontSize: 14 }}>
            {excluded.map((x, i) => <li key={i}>{x.name || x.id || t("an.unnamed")}{x.actor && <span className="muted"> · {t("an.actor", { actor: x.actor })}</span>}</li>)}
          </ul>
          <div className="muted" style={{ fontSize: 13, marginTop: 6 }}>{t("an.excluded.note")}</div>
        </details>
      )}
      {dropped > 0 && <div className="muted" style={{ fontSize: 13 }}>{t("an.dropped", { n: dropped })}</div>}
      {q?.method && <div className="muted" style={{ fontSize: 13, marginTop: -6 }}>{t("an.method", { m: METHOD_LABEL[q.method] ?? q.method })}</div>}

      <ReproBanner actions={ir.actions} />

      <div className="row">
        <div className="seg" role="tablist">
          <button className={tab === "actions" ? "on" : ""} onClick={() => setTab("actions")}>{t("an.tab.actions", { n: ir.actions.length })}</button>
          <button className={tab === "relations" ? "on" : ""} onClick={() => setTab("relations")}>{t("an.tab.relations", { n: ir.relations.length })}</button>
        </div>
        <div className="seg" style={{ marginLeft: "auto" }}>
          <button className={filter === "all" ? "on" : ""} onClick={() => setFilter("all")}>{t("an.all")}</button>
          {EPISTEMIC_ORDER.map((s) => (
            <button key={s} className={filter === s ? "on" : ""} onClick={() => setFilter(s)} title={EPISTEMIC[s].hint}>
              {imported && s === "supported" ? IMPORTED.label : EPISTEMIC[s].label} {counts[s] ?? 0}
            </button>
          ))}
        </div>
      </div>

      <div className="grid analysis-split">
        <div className="card flush" style={{ overflowX: "auto" }}>
          {tab === "actions" ? (
            actions.length === 0 ? <Empty>{ir.actions.length ? t("an.noMatchActions") : t("an.noActions")}</Empty> : (
              <table className={`tbl analysis-tbl ${hasRepro ? "w760" : "w640"}`}>
                <colgroup><col /><col style={{ width: 170 }} /><col style={{ width: 118 }} />{hasRepro && <col style={{ width: 120 }} />}<col style={{ width: 230 }} /></colgroup>
                <thead><tr><th>{t("an.col.action")}</th><th>ATT&CK</th><th>{t("an.col.claim")}</th>{hasRepro && <th title={t("an.col.repro.hint")}>{t("an.col.repro")}</th>}<th title={t("an.col.cite.hint")}>{t("an.col.cite")}</th></tr></thead>
                <tbody>
                  {actions.map((a) => (
                    <tr key={a.id} className="clickable" onClick={() => { setFocusRefs(a.evidence_refs ?? []); setActiveEv(null); }}>
                      <td>
                        <div style={{ fontWeight: 600 }}>{a.name}</div>
                        {a.description && <div className="muted" style={{ fontSize: 13, marginTop: 2 }}>{a.description}</div>}
                        {(() => { const tg = target(a); return tg && <div className="muted" style={{ fontSize: 13, marginTop: 2 }} title={tg.hint}>{t("an.target", { text: tg.text })}</div>; })()}
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
                              {info && <div style={{ fontSize: 13 }}>{info.name}</div>}
                              {tactics && <div className="muted" style={{ fontSize: 13 }}>{tactics}</div>}
                              {info && <div className="muted" style={{ fontSize: 12 }}>{t("an.official")}</div>}
                            </>
                          );
                        })()}
                      </td>
                      <td className="nowrap">
                        <EpistemicBadge status={a.epistemic_status} source={a.source} /><div style={{ marginTop: 4 }}><SourceTag source={a.source} /></div>
                        {(a as { source_certainty?: string }).source_certainty === "hedged" && (
                          <div style={{ marginTop: 4 }}><span className="tag sub" title={t("an.hedged.hint")}>{t("an.hedged")}</span></div>
                        )}
                      </td>
                      {hasRepro && <td className="nowrap"><ReproBadge action={a} /></td>}
                      <td>
                        <div style={{ marginBottom: 5 }}><CitationBadge summary={cite(a)} source={a.source} basis={isInferred(a)} /></div>
                        <EvidenceChips refs={a.evidence_refs} active={activeEv} onPick={pickEv} byId={evById} basis={isInferred(a)} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )
          ) : relations.length === 0 ? <Empty>{ir.relations.length ? t("an.noMatchRel") : t("an.noRel")}</Empty> : (
            <table className="tbl analysis-tbl w700">
              <colgroup><col /><col style={{ width: 84 }} /><col /><col /><col style={{ width: 118 }} /><col style={{ width: 210 }} /></colgroup>
              <thead><tr><th>{t("an.col.from")}</th><th>{t("an.col.kind")}</th><th>{t("an.col.to")}</th><th>{t("an.col.why")}</th><th>{t("an.col.claim")}</th><th>{t("an.col.cite")}</th></tr></thead>
              <tbody>
                {relations.map((r) => (
                  <tr key={r.id} className="clickable" onClick={() => { setFocusRefs(r.evidence_refs ?? []); setActiveEv(null); }}>
                    <td>{actionName.get(r.from_action) ?? <span className="mono muted">{r.from_action}</span>}</td>
                    <td><span className={`tag ${r.kind === "dependency" ? "dep" : "temporal"}`}>{r.kind === "dependency" ? t("an.dep") : t("an.temporal")}</span></td>
                    <td>{actionName.get(r.to_action) ?? <span className="mono muted">{r.to_action}</span>}</td>
                    <td className="muted" style={{ fontSize: 13 }}>
                      {r.rationale ?? "—"}
                      {(r as { epistemic_reason?: string }).epistemic_reason && <div title={t("an.relReason.hint")}>{t("an.relReason", { reason: (r as { epistemic_reason?: string }).epistemic_reason })}</div>}
                    </td>
                    <td className="nowrap"><EpistemicBadge status={r.epistemic_status} source={r.source} /><div style={{ marginTop: 4 }}><SourceTag source={r.source} /></div></td>
                    <td>
                      <div style={{ marginBottom: 5 }}><CitationBadge summary={cite(r)} source={r.source} basis={isInferred(r)} /></div>
                      <EvidenceChips refs={r.evidence_refs} active={activeEv} onPick={pickEv} byId={evById} basis={isInferred(r)} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="card flush" style={{ position: "sticky", top: 0 }}>
          <div className="card-head">
            <h2>{t("an.ev.title")}</h2>
            <span className="muted" style={{ fontSize: 13 }}>{shownEvidence.length} / {evidence.length}</span>
            {focusRefs && <div className="right"><button className="small" onClick={() => setFocusRefs(null)}>{t("an.ev.showAll")}</button></div>}
          </div>
          {evidence.length > 0 && (pdf.state === "none" || pdf.state === "error") && (
            <div className="muted" style={{ fontSize: 13, padding: "8px 12px 0" }}>
              {pdf.state === "none" ? t("an.ev.noPdf") : t("an.ev.pdfFail")}
            </div>
          )}
          <div style={{ maxHeight: "62vh", overflow: "auto", padding: 12, display: "flex", flexDirection: "column", gap: 12 }}>
            {evidence.length === 0 ? <Empty>{imported ? t("an.ev.noneImported") : t("an.ev.none")}</Empty>
              : shownEvidence.length === 0 ? <Empty>{t("an.ev.noneSel")}</Empty>
              : shownEvidence.map((e) => (
                <div key={e.id} id={`ev-${e.id}`}>
                  <div className="row" style={{ gap: 8, marginBottom: 4 }}>
                    {(() => {
                      // Graded source support first — the id is only a handle, so it comes last and small.
                      const level = quoteLevel(e);
                      if (!level) return <span className="muted" style={{ fontSize: 13 }} title={t("an.ev.ungraded")}>· {t("quote.unchecked")}</span>;
                      const M = QUOTE_LEVEL[level];
                      const tip = e.matched_text ? `${M.desc}\n${t("an.ev.fragment", { text: e.matched_text })}` : M.desc;
                      return <span className={M.cls} style={{ fontSize: 13, fontWeight: 700 }} title={tip}>{M.mark} {M.word}</span>;
                    })()}
                    {(() => {
                      // Where the quote sits, in words. Once it has been located in the PDF, the real page number is known too.
                      const where = locatorText(e.locator);
                      const f = pdfFound[e.id];
                      return (
                        <>
                          {where && <span className="muted" style={{ fontSize: 13 }} title={t("an.ev.where")}>{where}</span>}
                          {f?.state === "found" && <span className="muted" style={{ fontSize: 13 }}>{t("an.ev.pdfPage", { page: f.page })}</span>}
                        </>
                      );
                    })()}
                    <span className="muted mono" style={{ marginLeft: "auto", fontSize: 12 }}>{e.id}</span>
                  </div>
                  <blockquote className="quote" style={activeEv === e.id ? { borderLeftColor: "var(--accent)" } : undefined}>{e.quote}</blockquote>
                  {pdf.state === "ready" ? (
                    <button className="link" style={{ fontSize: 13, marginTop: 4 }} data-testid="view-in-pdf" onClick={() => viewInPdf(e)}>{t("an.ev.viewPdf")}</button>
                  ) : pdf.state === "loading" ? (
                    <span className="muted" style={{ fontSize: 13 }}>{t("an.ev.pdfLoading")}</span>
                  ) : null}
                </div>
              ))}
          </div>
        </div>
      </div>

      {pdfView && pdfEvidence && pdf.data && (
        <PdfDrawer data={pdf.data} evidence={pdfEvidence} anchor={pdfView.anchor} find={pdfFound[pdfView.id]} onLocated={onPdfLocated} onClose={closePdf} />
      )}

      <NextStep prev={{ to: "/import", label: t("stage.import") }} next={{ to: "/missing", label: t("stage.missing") }} />
    </div>
  );
}

export function AnalysisPage() {
  const { ir } = useScenario();
  return <ScenarioGate title={t("an.title")}>{ir && <Body ir={ir} />}</ScenarioGate>;
}
