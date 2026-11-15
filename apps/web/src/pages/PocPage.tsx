// Module 9 — PoC discovery, exploit validation & environment export console.
// Five panels (owner prompt §8): PoC Discovery · Validation Execution · Attack Chain Validation ·
// Fidelity Report (five SEPARATE metrics) · Environment Export. Reads real backend data only; derives nothing
// it cannot show evidence for. The GUI never fakes a verdict — BLOCKED / not_executable are shown as themselves.
// Owns only this file plus one additive method group in lib/api.ts and one STAGES entry in App.tsx.
// Interface gaps against the frozen CONTRACT (live-poll/cancel, export download, report shape) are tracked in
// reports/overnight/m9/requests/m9-gui.md; this page degrades honestly where a route is missing.
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type {
  ChainValidation, ExecutionResult, ExportManifest, PocCandidate, PocCheckStatus,
  PocEvidenceKind, ScenarioIR, ValidationItem, ValidationPlan,
} from "@contracts";
import { t, type MsgKey } from "../i18n";
import { api } from "../lib/api";
import { useAction } from "../lib/hooks";
import { useScenario } from "../lib/scenario";
import { ApiNotice, Busy, Empty, fmtTime, NextStep, Notice, PageHead, ScenarioGate } from "../components/ui";

/* ---------- small shared bits ---------- */

const STATUS_COLOR: Record<PocCheckStatus, string> = {
  PASS: "var(--accent)", FAIL: "var(--err)", PARTIAL: "var(--partial)",
  BLOCKED: "var(--sub)", NOT_TESTED: "var(--text-dim)",
};
const statusLabel = (s: PocCheckStatus) =>
  s === "BLOCKED" ? t("poc.st.BLOCKED") : t(`check.${s}` as MsgKey);

/** Status pill that also understands BLOCKED (not a module-8 CheckStatus, so it needs its own colour). */
function PocPill({ status }: { status?: PocCheckStatus | string }) {
  const s = (status ?? "NOT_TESTED") as PocCheckStatus;
  return <span className="pill" style={{ color: STATUS_COLOR[s] ?? "var(--text-dim)" }}>{statusLabel(s)}</span>;
}

function Bool({ v }: { v?: boolean }) {
  if (v === undefined) return <span className="muted">—</span>;
  return <span className={v ? "status-PASS" : "status-FAIL"}>{v ? "✓" : "✗"}</span>;
}

function Section({ n, title, desc, children }: { n: string; title: string; desc: string; children: ReactNode }) {
  return (
    <div className="card flush">
      <div className="card-head"><span className="muted mono">{n}</span><h2>{title}</h2></div>
      <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 12 }}>
        <p className="desc" style={{ margin: 0, maxWidth: "72ch" }}>{desc}</p>
        {children}
      </div>
    </div>
  );
}

const STRATEGY: Record<ValidationItem["strategy"], MsgKey> = {
  poc_exec: "poc.strat.poc_exec", config_check: "poc.strat.config_check",
  log_check: "poc.strat.log_check", not_executable: "poc.strat.not_executable",
};
const EVIDENCE_KIND: Record<PocEvidenceKind, MsgKey> = {
  exploit_effect: "poc.ev.exploit_effect", callback: "poc.ev.callback", file_written: "poc.ev.file_written",
  shell_output: "poc.ev.shell_output", state_change: "poc.ev.state_change", log: "poc.ev.log",
  request: "poc.ev.request", response: "poc.ev.response",
};
const CARRIED: Record<ChainValidation["transfers"][number]["carried"], MsgKey> = {
  cred: "poc.carried.cred", session: "poc.carried.session", network: "poc.carried.network",
  token: "poc.carried.token", artifact: "poc.carried.artifact",
};
const STAGE_KEYS: { key: keyof ExecutionResult["stages"]; label: MsgKey }[] = [
  { key: "started", label: "poc.stage.started" },
  { key: "delivered", label: "poc.stage.delivered" },
  { key: "responded", label: "poc.stage.responded" },
  { key: "vuln_behavior", label: "poc.stage.vuln_behavior" },
  { key: "state_change", label: "poc.stage.state_change" },
  { key: "action_complete", label: "poc.stage.action_complete" },
];

/* ---------- 1. PoC discovery ---------- */

function PlanTable({ plan, actionName }: { plan: ValidationPlan; actionName: Map<string, string> }) {
  return (
    <div style={{ overflowX: "auto" }}>
      <table className="tbl tbl-stack">
        <thead><tr>
          <th>{t("poc.col.action")}</th><th>{t("poc.col.strategy")}</th><th>{t("poc.col.cve")}</th>
          <th>{t("poc.col.target")}</th><th>{t("poc.col.evidence")}</th>
        </tr></thead>
        <tbody>
          {plan.items.map((it) => (
            <tr key={it.action_id}>
              <td data-label={t("poc.col.action")}>{actionName.get(it.action_id) ?? it.action_id}</td>
              <td data-label={t("poc.col.strategy")}>
                <span className={it.strategy === "not_executable" ? "status-FAIL" : undefined}>{t(STRATEGY[it.strategy])}</span>
                {it.strategy === "not_executable" && it.not_executable_reason && (
                  <div className="muted" style={{ fontSize: 12 }} title={t("poc.notExec.reason")}>{it.not_executable_reason}</div>
                )}
              </td>
              <td className="mono" data-label={t("poc.col.cve")}>{it.cve ?? "—"}</td>
              <td className="mono" data-label={t("poc.col.target")}>{it.target_host_ref ?? it.service_ref ?? "—"}</td>
              <td style={{ fontSize: 12 }} data-label={t("poc.col.evidence")}>{it.expected_evidence || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const TRUST: Record<PocCandidate["trust"], MsgKey> = {
  high: "poc.trust.high", medium: "poc.trust.medium", low: "poc.trust.low", unknown: "poc.trust.unknown",
};
function CandidateTable({ items, actionName }: { items: PocCandidate[]; actionName: Map<string, string> }) {
  return (
    <div style={{ overflowX: "auto" }}>
      <table className="tbl tbl-stack">
        <thead><tr>
          <th>{t("poc.col.score")}</th><th>{t("poc.col.action")}</th><th>{t("poc.col.cve")}</th>
          <th>{t("poc.col.source")}</th><th>{t("poc.col.product")}</th><th>{t("poc.col.version")}</th>
          <th>{t("poc.col.exec")}</th><th>{t("poc.col.trust")}</th>
        </tr></thead>
        <tbody>
          {items.map((c, i) => (
            <tr key={`${c.action_id}-${i}`}>
              <td className="mono" data-label={t("poc.col.score")}>{Math.round((c.compatibility_score ?? 0) * 100)}%</td>
              <td data-label={t("poc.col.action")}>{actionName.get(c.action_id) ?? c.action_id}</td>
              <td className="mono" data-label={t("poc.col.cve")}>{c.cve ?? "—"}</td>
              <td data-label={t("poc.col.source")}>
                {c.source_url
                  ? <a href={c.source_url} target="_blank" rel="noreferrer noopener">{c.source}</a>
                  : c.source}
                {c.ref?.commit_sha && <div className="mono muted" style={{ fontSize: 11 }}>{c.ref.commit_sha.slice(0, 10)}</div>}
              </td>
              <td data-label={t("poc.col.product")}>{c.product || "—"}</td>
              <td className="mono" data-label={t("poc.col.version")} style={{ fontSize: 11 }}>{c.version_range || "—"}</td>
              <td className="mono" data-label={t("poc.col.exec")}>{c.exec_method}</td>
              <td data-label={t("poc.col.trust")}>{t(TRUST[c.trust] ?? "poc.trust.unknown")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ---------- 2. Validation execution ---------- */

function ResultCard({ r, name }: { r: ExecutionResult; name: string }) {
  return (
    <div className="card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div className="row" style={{ flexWrap: "nowrap" }}>
        <strong style={{ minWidth: 0, overflowWrap: "anywhere" }}>{name}</strong>
        <span style={{ marginLeft: "auto" }}><PocPill status={r.status} /></span>
      </div>

      {/* Stage timeline: the honest "status" view — which of the six stages the real payload actually reached. */}
      <div className="row" style={{ gap: 6, fontSize: 11 }} aria-label={t("poc.exec.stages")}>
        {STAGE_KEYS.map(({ key, label }) => {
          const on = r.stages?.[key];
          return (
            <span key={key} className="row" style={{ gap: 4, flexWrap: "nowrap", color: on ? "var(--accent)" : "var(--text-dim)" }}>
              <span aria-hidden>{on ? "●" : "○"}</span>{t(label)}
            </span>
          );
        })}
      </div>

      <div className="row" style={{ fontSize: 12, gap: 16 }}>
        <span style={{ color: r.target_ownership_verified ? "var(--text-dim)" : "var(--err)" }}>
          <Bool v={r.target_ownership_verified} /> {r.target_ownership_verified ? t("poc.exec.ownership") : t("poc.exec.ownershipNo")}
        </span>
        {typeof r.confidence === "number" && <span className="muted">{t("poc.exec.confidence")}: {Math.round(r.confidence * 100)}%</span>}
        {typeof r.exit_code === "number" && <span className="muted mono">{t("poc.exec.exit")}: {r.exit_code}</span>}
      </div>

      {r.failure_reason && <div className="status-FAIL" style={{ fontSize: 13 }}>{t("poc.exec.failReason")}: {r.failure_reason}</div>}

      <div className="mono muted" style={{ fontSize: 11, overflowWrap: "anywhere" }}>
        {r.poc?.source_url && <div>{t("poc.exec.pocSource")}: {r.poc.source_url}{r.poc.ref?.commit_sha ? ` @ ${r.poc.ref.commit_sha.slice(0, 10)}` : ""}</div>}
        {r.payload_sha256 && <div>{t("poc.exec.payload")}: {r.payload_sha256.slice(0, 16)}…</div>}
        {r.logs_path && <div>{t("poc.exec.logs")}: {r.logs_path}</div>}
      </div>

      <details>
        <summary className="muted" style={{ cursor: "pointer", fontSize: 12 }}>{t("poc.exec.evidence")} · {r.evidence?.length ?? 0}</summary>
        {r.evidence?.length ? (
          <table className="tbl" style={{ marginTop: 8 }}>
            <tbody>
              {r.evidence.map((e, i) => (
                <tr key={i}>
                  <td><span className="tag">{t(EVIDENCE_KIND[e.kind] ?? "poc.ev.log")}</span>{e.redacted && <span className="tag sub" style={{ marginLeft: 4 }}>{t("poc.ev.redacted")}</span>}</td>
                  <td className="mono" style={{ fontSize: 11, overflowWrap: "anywhere" }}>{e.note || e.path}{e.sha256 ? <div className="muted">{e.sha256.slice(0, 16)}…</div> : null}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>{t("poc.exec.noEvidence")}</div>}
      </details>
    </div>
  );
}

/* ---------- 3. Attack chain validation (flow view) ---------- */

function ChainFlow({ ir, chain, statusByAction, evidenceByAction, actionName }: {
  ir: ScenarioIR; chain: ChainValidation | null;
  statusByAction: Map<string, PocCheckStatus>; evidenceByAction: Map<string, number>; actionName: Map<string, string>;
}) {
  // Order the nodes by declared execution start when present, else keep the scenario's action order.
  const ordered = useMemo(() => {
    const idx = new Map(ir.actions.map((a, i) => [a.id, i]));
    return [...ir.actions].sort((a, b) => {
      const sa = a.execution_start, sb = b.execution_start;
      if (sa && sb && sa !== sb) return sa < sb ? -1 : 1;
      return (idx.get(a.id) ?? 0) - (idx.get(b.id) ?? 0);
    });
  }, [ir.actions]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
      <h3 style={{ margin: "0 0 8px" }}>{t("poc.chain.perAction")}</h3>
      {ordered.map((a, i) => {
        const st = statusByAction.get(a.id);
        const ev = evidenceByAction.get(a.id) ?? 0;
        return (
          <div key={a.id}>
            {i > 0 && <div aria-hidden style={{ width: 2, height: 16, background: "var(--border)", marginLeft: 20 }} />}
            <div className="card" style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 14px" }}>
              <span className="mono" style={{ width: 24, textAlign: "center", color: "var(--text-dim)" }}>{i + 1}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 600, overflowWrap: "anywhere" }}>{a.name}</div>
                <div className="muted" style={{ fontSize: 12 }}>
                  {a.technique_id || a.attack_technique || "—"}
                  {a.target_host_ref ? ` · ${a.target_host_ref}` : ""}
                  {ev > 0 ? ` · ${t("poc.exec.evidence")} ${ev}` : ""}
                </div>
              </div>
              <PocPill status={st} />
            </div>
          </div>
        );
      })}

      {chain && (
        <div style={{ marginTop: 16 }}>
          <h3 style={{ marginBottom: 8 }}>{t("poc.chain.transfers")}</h3>
          {chain.transfers?.length ? (
            <div style={{ overflowX: "auto" }}>
              <table className="tbl tbl-stack">
                <thead><tr>
                  <th>{t("poc.chain.from")}</th><th>{t("poc.chain.to")}</th>
                  <th>{t("poc.chain.carried")}</th><th>{t("poc.chain.verified")}</th>
                </tr></thead>
                <tbody>
                  {chain.transfers.map((tr, i) => (
                    <tr key={i}>
                      <td data-label={t("poc.chain.from")}>{actionName.get(tr.from_action) ?? tr.from_action}</td>
                      <td data-label={t("poc.chain.to")}>{actionName.get(tr.to_action) ?? tr.to_action}</td>
                      <td data-label={t("poc.chain.carried")}><span className="tag">{t(CARRIED[tr.carried] ?? "poc.carried.artifact")}</span></td>
                      <td data-label={t("poc.chain.verified")}>
                        <span className={tr.verified ? "status-PASS" : "status-FAIL"}>
                          <Bool v={tr.verified} /> {tr.verified ? t("poc.chain.verified") : t("poc.chain.unverified")}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <div className="muted" style={{ fontSize: 13 }}>{t("poc.chain.noTransfers")}</div>}
        </div>
      )}
    </div>
  );
}

/* ---------- 4. Fidelity report (five separate metrics) ---------- */

function FidelityMetric({ label, hint, n, total, caption }: { label: string; hint: string; n?: number; total?: number; caption?: string }) {
  const has = typeof n === "number" && typeof total === "number";
  return (
    <div className="metric" title={hint}>
      <div className="k">{label}</div>
      <div className={`v ${has ? "" : "na"}`}>{has ? t("poc.fid.of", { n, total }) : "—"}</div>
      {caption && <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>{caption}</div>}
    </div>
  );
}

/* ---------- 5. Environment export ---------- */

function ExportManifestView({ manifest, bundlePath }: { manifest: ExportManifest; bundlePath?: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <h3 style={{ margin: 0 }}>{t("poc.export.manifest")}</h3>
      <div className="row" style={{ gap: 16, fontSize: 13 }}>
        <span className={manifest.rebuildable ? "status-PASS" : "status-FAIL"}>
          <Bool v={manifest.rebuildable} /> {manifest.rebuildable ? t("poc.export.rebuildable") : t("poc.export.notRebuildable")}
        </span>
        <span className="status-PASS"><Bool v={manifest.contains_secrets === false} /> {t("poc.export.secrets")}</span>
        {manifest.scenario_version !== undefined && <span className="muted">{t("poc.export.version")}: {String(manifest.scenario_version)}</span>}
        {manifest.created_at && <span className="muted">{t("poc.export.createdAt")}: {fmtTime(manifest.created_at)}</span>}
      </div>

      {bundlePath && <div className="mono muted" style={{ fontSize: 11, overflowWrap: "anywhere" }}>{t("poc.export.bundlePath")}: {bundlePath}</div>}

      {manifest.missing_for_rebuild?.length ? (
        <Notice kind="warn" title={t("poc.export.missing")}>
          <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>{manifest.missing_for_rebuild.map((m, i) => <li key={i} className="mono" style={{ fontSize: 12 }}>{m}</li>)}</ul>
        </Notice>
      ) : null}

      {manifest.files?.length ? (
        <div style={{ overflowX: "auto" }}>
          <h3 style={{ margin: "4px 0 8px" }}>{t("poc.export.files")}</h3>
          <table className="tbl tbl-stack">
            <thead><tr><th>{t("poc.col.path")}</th><th>{t("poc.col.sha")}</th><th>{t("poc.col.by")}</th></tr></thead>
            <tbody>
              {manifest.files.map((f, i) => (
                <tr key={i}>
                  <td className="mono" style={{ fontSize: 11, overflowWrap: "anywhere" }} data-label={t("poc.col.path")}>{f.path}</td>
                  <td className="mono muted" style={{ fontSize: 11 }} data-label={t("poc.col.sha")}>{f.sha256 ? `${f.sha256.slice(0, 16)}…` : "—"}</td>
                  <td className="muted" data-label={t("poc.col.by")}>{f.generated_by || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}

/* ---------- page body ---------- */

function Body({ ir }: { ir: ScenarioIR }) {
  const actionName = useMemo(() => new Map(ir.actions.map((a) => [a.id, a.name])), [ir.actions]);

  const [plan, setPlan] = useState<ValidationPlan | null>(null);
  const [candidates, setCandidates] = useState<PocCandidate[] | null>(null);
  const [results, setResults] = useState<ExecutionResult[] | null>(null);
  const [chain, setChain] = useState<ChainValidation | null>(null);
  const [report, setReport] = useState<any | null>(null);
  const [bundle, setBundle] = useState<{ bundle_path: string; manifest: ExportManifest } | null>(null);

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [stopped, setStopped] = useState(false);
  const [format, setFormat] = useState("full");
  const [dlUnavail, setDlUnavail] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const planAct = useAction(async () => { const d = await api.poc.plan(ir.id); setPlan(d); return d; });
  const discoverAct = useAction(async () => { const d = await api.poc.discover(ir.id); setCandidates(d.items ?? []); return d; });
  const reportAct = useAction(async () => { const d = await api.poc.report(ir.id); setReport(d); return d; });
  const chainAct = useAction(async () => {
    const d = await api.poc.chain(ir.id); setChain(d); void reportAct.run(); return d;
  });
  const execAct = useAction(async () => {
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setStopped(false);
    const d = await api.poc.execute(ir.id, Array.from(selected), ctrl.signal);
    setResults(d);
    void reportAct.run();
    return d;
  });
  const exportAct = useAction(async () => { const d = await api.poc.export(ir.id, format); setBundle(d); setDlUnavail(false); return d; });
  const downloadAct = useAction(async () => {
    const res = await api.poc.exportDownload(ir.id);
    if (!res) { setDlUnavail(true); return; }
    const blob = new Blob([res.data], { type: res.contentType || "application/zip" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `${ir.id}-range-bundle.zip`;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
  });

  // Default selection: every runnable (poc_exec) action, once a plan is loaded.
  const runnable = useMemo(() => (plan?.items ?? []).filter((it) => it.strategy === "poc_exec"), [plan]);
  useEffect(() => { setSelected(new Set(runnable.map((it) => it.action_id))); }, [runnable]);
  const toggle = (id: string) => setSelected((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const stop = () => { abortRef.current?.abort(); setStopped(true); };

  // Per-action status and evidence counts, from the chain roll-up first, then the raw execution results.
  const statusByAction = useMemo(() => {
    const m = new Map<string, PocCheckStatus>();
    chain?.per_action?.forEach((p) => m.set(p.action_id, p.status));
    results?.forEach((r) => { if (!m.has(r.action_id)) m.set(r.action_id, r.status); });
    return m;
  }, [chain, results]);
  const evidenceByAction = useMemo(() => {
    const m = new Map<string, number>();
    results?.forEach((r) => m.set(r.action_id, r.evidence?.length ?? 0));
    return m;
  }, [results]);

  // Five SEPARATE fidelity metrics — never merged into one success rate (owner §8 / §11). Derived from the real
  // data the GUI holds; a structured /report payload (report.fidelity) is preferred for scenario fidelity when present.
  const fid = useMemo(() => {
    const items = plan?.items ?? [];
    const planTotal = items.length;
    const deployReady = items.filter((it) => it.strategy !== "not_executable").length;

    const res = results ?? [];
    const vulnPassed = res.filter((r) => r.status === "PASS").length;

    const chainActions = chain?.per_action ?? [];
    const chainPassed = chainActions.filter((p) => p.status === "PASS").length;

    const f = report?.fidelity;
    const scenarioRepro = Array.isArray(f?.reproduced) ? f.reproduced.length : vulnPassed;
    const scenarioTotal = f
      ? (f.reproduced?.length ?? 0) + (f.partial?.length ?? 0) + (f.not_reproduced?.length ?? 0) + (f.not_tested?.length ?? 0)
      : planTotal;

    const notExec = items.filter((it) => it.strategy === "not_executable").length;
    const blocked = res.filter((r) => r.status === "BLOCKED").length;
    const notTested = res.filter((r) => r.status === "NOT_TESTED").length;
    const unverified = notExec + blocked + notTested;

    return {
      any: planTotal > 0 || res.length > 0 || chainActions.length > 0,
      deploy: planTotal ? { n: deployReady, total: planTotal } : undefined,
      vuln: res.length ? { n: vulnPassed, total: res.length } : undefined,
      chain: chainActions.length ? { n: chainPassed, total: chainActions.length } : undefined,
      scenario: scenarioTotal ? { n: scenarioRepro, total: scenarioTotal } : undefined,
      unverified: (planTotal || res.length) ? { n: unverified, total: planTotal || res.length } : undefined,
    };
  }, [plan, results, chain, report]);

  return (
    <div className="page">
      <PageHead title={t("poc.title")} desc={t("poc.desc")} />

      {/* 1. PoC discovery */}
      <Section n="1" title={t("poc.s.discovery")} desc={t("poc.s.discovery.desc")}>
        <div className="row">
          <button className={plan ? "" : "primary"} disabled={planAct.busy} onClick={() => planAct.run()}>
            {plan ? t("poc.plan.rebuild") : t("poc.plan.build")}
          </button>
          <button disabled={discoverAct.busy || !plan} onClick={() => discoverAct.run()}>
            {candidates ? t("poc.discover.rerun") : t("poc.discover.run")}
          </button>
          {plan && <span className="muted" style={{ fontSize: 12 }}>{t("poc.plan.at", { time: fmtTime(plan.generated_at) })}</span>}
        </div>
        {planAct.busy && <div className="card"><Busy label={t("poc.what.plan")} elapsed={planAct.elapsed} /></div>}
        <ApiNotice error={planAct.error} what={t("poc.what.plan")} onRetry={() => planAct.run()} />
        <ApiNotice error={discoverAct.error} what={t("poc.what.discover")} onRetry={() => discoverAct.run()} />
        {plan ? <PlanTable plan={plan} actionName={actionName} /> : !planAct.busy && <Empty>{t("poc.plan.none")}</Empty>}
        {candidates && (
          candidates.length
            ? <><div className="muted" style={{ fontSize: 12 }}>{t("poc.discover.count", { n: candidates.length })}</div><CandidateTable items={candidates} actionName={actionName} /></>
            : <Empty>{t("poc.discover.none")}</Empty>
        )}
      </Section>

      {/* 2. Validation execution */}
      <Section n="2" title={t("poc.s.exec")} desc={t("poc.s.exec.desc")}>
        {!plan ? <Empty>{t("poc.plan.none")}</Empty> : (
          <>
            <div className="card" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <strong>{t("poc.exec.review")}</strong>
                <button className="small" onClick={() => setSelected(new Set(runnable.map((it) => it.action_id)))}>{t("poc.exec.selectAll")}</button>
              </div>
              <div className="muted" style={{ fontSize: 12 }}>{t("poc.exec.onlyExec")}</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                {runnable.map((it) => (
                  <label key={it.action_id} className="row" style={{ gap: 8, fontSize: 13 }}>
                    <input type="checkbox" checked={selected.has(it.action_id)} onChange={() => toggle(it.action_id)} />
                    <span>{actionName.get(it.action_id) ?? it.action_id}</span>
                    {it.cve && <span className="mono muted" style={{ fontSize: 11 }}>{it.cve}</span>}
                  </label>
                ))}
                {runnable.length === 0 && <span className="muted" style={{ fontSize: 13 }}>{t("poc.strat.not_executable")}</span>}
              </div>
            </div>
            <div className="row">
              <button className="primary" disabled={execAct.busy || selected.size === 0}
                onClick={() => { if (window.confirm(t("poc.exec.confirm"))) void execAct.run(); }}>
                {results ? t("poc.exec.rerun") : t("poc.exec.run")}
              </button>
              {execAct.busy && <button className="danger" onClick={stop}>{t("poc.exec.stop")}</button>}
              <span className="muted" style={{ fontSize: 12 }}>{t("poc.exec.selected", { n: selected.size })}</span>
            </div>
          </>
        )}
        {execAct.busy && <div className="card"><Busy label={t("poc.exec.busy")} elapsed={execAct.elapsed} /></div>}
        {stopped && <Notice kind="warn">{t("poc.exec.stopped")}</Notice>}
        {!stopped && <ApiNotice error={execAct.error} what={t("poc.what.execute")} />}
        {results && (
          results.length ? (
            <>
              <div className="muted" style={{ fontSize: 12 }}>{t("poc.exec.liveNote")}</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {results.map((r) => <ResultCard key={r.action_id} r={r} name={actionName.get(r.action_id) ?? r.action_id} />)}
              </div>
            </>
          ) : <Empty>{t("poc.exec.none")}</Empty>
        )}
      </Section>

      {/* 3. Attack chain validation */}
      <Section n="3" title={t("poc.s.chain")} desc={t("poc.s.chain.desc")}>
        <div className="row">
          <button className={chain ? "" : "primary"} disabled={chainAct.busy} onClick={() => chainAct.run()}>
            {chain ? t("poc.chain.rerun") : t("poc.chain.run")}
          </button>
          {chain && (
            <>
              <span className="row" style={{ gap: 6, fontSize: 13 }}><Bool v={chain.objective_reached} /> {t("poc.chain.objective")}</span>
              <span className="row" style={{ gap: 6, fontSize: 13 }}><Bool v={chain.order_ok} /> {t("poc.chain.order")}</span>
              <span className="row" style={{ marginLeft: "auto", gap: 6 }}><span className="muted" style={{ fontSize: 13 }}>{t("poc.chain.passes")}</span><PocPill status={chain.passes ? "PASS" : "FAIL"} /></span>
            </>
          )}
        </div>
        {chainAct.busy && <div className="card"><Busy label={t("poc.what.chain")} elapsed={chainAct.elapsed} /></div>}
        <ApiNotice error={chainAct.error} what={t("poc.what.chain")} onRetry={() => chainAct.run()} />
        {chain || results ? (
          <ChainFlow ir={ir} chain={chain} statusByAction={statusByAction} evidenceByAction={evidenceByAction} actionName={actionName} />
        ) : <Empty>{t("poc.chain.none")}</Empty>}
      </Section>

      {/* 4. Fidelity report — five separate metrics */}
      <Section n="4" title={t("poc.s.fidelity")} desc={t("poc.s.fidelity.desc")}>
        <ApiNotice error={reportAct.error} what={t("poc.what.report")} onRetry={() => reportAct.run()} />
        {!fid.any ? <Empty>{t("poc.fid.none")}</Empty> : (
          <>
            <div style={{ display: "grid", gap: 12, gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))" }}>
              <FidelityMetric label={t("poc.fid.deploy")} hint={t("poc.fid.deploy.hint")} n={fid.deploy?.n} total={fid.deploy?.total} caption={t("poc.fid.reproduced")} />
              <FidelityMetric label={t("poc.fid.vuln")} hint={t("poc.fid.vuln.hint")} n={fid.vuln?.n} total={fid.vuln?.total} caption={t("poc.fid.passed")} />
              <FidelityMetric label={t("poc.fid.chain")} hint={t("poc.fid.chain.hint")} n={fid.chain?.n} total={fid.chain?.total} caption={t("poc.fid.passed")} />
              <FidelityMetric label={t("poc.fid.scenario")} hint={t("poc.fid.scenario.hint")} n={fid.scenario?.n} total={fid.scenario?.total} caption={t("poc.fid.reproduced")} />
              <FidelityMetric label={t("poc.fid.unverified")} hint={t("poc.fid.unverified.hint")} n={fid.unverified?.n} total={fid.unverified?.total} caption={t("poc.fid.pending")} />
            </div>
            {report?.fidelity?.summary && <div style={{ fontSize: 13, lineHeight: 1.6 }} className="muted">{report.fidelity.summary}</div>}
            <Notice kind="info">{t("poc.fid.note")}</Notice>
          </>
        )}
      </Section>

      {/* 5. Environment export */}
      <Section n="5" title={t("poc.s.export")} desc={t("poc.s.export.desc")}>
        <div className="row">
          <label className="row" style={{ gap: 8, fontSize: 13 }}>
            <span>{t("poc.export.format")}</span>
            <span className="select">
              <select value={format} onChange={(e) => setFormat(e.target.value)}>
                <option value="full">{t("poc.fmt.full")}</option>
                <option value="iac">{t("poc.fmt.iac")}</option>
                <option value="evidence">{t("poc.fmt.evidence")}</option>
              </select>
            </span>
          </label>
          <button className={bundle ? "" : "primary"} disabled={exportAct.busy} onClick={() => exportAct.run()}>
            {bundle ? t("poc.export.rerun") : t("poc.export.run")}
          </button>
          {bundle && <button disabled={downloadAct.busy} onClick={() => downloadAct.run()}>{t("poc.export.download")}</button>}
        </div>
        <div className="muted" style={{ fontSize: 12 }}>{t("poc.export.formatHint")}</div>
        {exportAct.busy && <div className="card"><Busy label={t("poc.what.export")} elapsed={exportAct.elapsed} /></div>}
        <ApiNotice error={exportAct.error} what={t("poc.what.export")} onRetry={() => exportAct.run()} />
        <ApiNotice error={downloadAct.error} what={t("poc.what.download")} />
        {dlUnavail && <Notice kind="info">{t("poc.export.downloadUnavail")}</Notice>}
        {bundle ? <ExportManifestView manifest={bundle.manifest} bundlePath={bundle.bundle_path} /> : !exportAct.busy && <Empty>{t("poc.export.none")}</Empty>}
      </Section>

      <NextStep prev={{ to: "/report", label: t("stage.report") }} />
    </div>
  );
}

export function PocPage() {
  const { ir } = useScenario();
  return <ScenarioGate title={t("poc.title")}>{ir && <Body key={ir.id} ir={ir} />}</ScenarioGate>;
}
