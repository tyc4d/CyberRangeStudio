import { useEffect, useMemo, useState } from "react";
import type { EnvHost, ScenarioIR, ValidationReport } from "@contracts";
import { t } from "../i18n";

/* An animated replay of the attack across the planned topology, driven entirely by the
 * validation report: each host takes the state its targeting actions earned (reproduced /
 * partial / failed / not-tested). It reuses the product's status tokens and the navy
 * topology look, so it reads as part of the app rather than a bolt-on. */

type State = "reproduced" | "partial" | "failed" | "not_tested";
const STATE_VAR: Record<State, string> = {
  reproduced: "var(--ok)", partial: "var(--warn)", failed: "var(--err)", not_tested: "var(--muted)",
};
const STATE_LABEL: Record<State, string> = {
  reproduced: "rp.ar.reproduced", partial: "rp.ar.partial", failed: "rp.ar.failed", not_tested: "rp.ar.nottested",
};

interface PNode { id: string; role: string; col: 0 | 1 | 2; x: number; y: number; state: State; attacker: boolean; vuln: boolean; }

function isAttacker(h: EnvHost): boolean {
  return /attacker/i.test(h.role) || /attacker/i.test(h.image_hint || "");
}
function deployed(h: EnvHost): boolean {
  return h.component_mode === "real" || h.component_mode === "substitute" || h.component_mode === "vm";
}

function buildModel(ir: ScenarioIR, report: ValidationReport) {
  const plan = (ir as { environment_plan?: { hosts?: EnvHost[] } }).environment_plan;
  const hosts = plan?.hosts ?? [];
  if (hosts.length === 0) return null;
  const actions = ir.actions ?? [];
  const f = report.fidelity;
  if (!f) return null;
  const bucket = (id: string): State | null =>
    f.reproduced?.includes(id) ? "reproduced"
    : f.partial?.includes(id) ? "partial"
    : f.not_reproduced?.includes(id) ? "failed"
    : f.not_tested?.includes(id) ? "not_tested" : null;
  // Strongest evidence a host's own actions earned; a host with no action and no deployment is "not_tested".
  const RANK: State[] = ["reproduced", "partial", "failed", "not_tested"];
  const hostState = (hid: string): State => {
    const mine = actions.filter((a) => (a as { target_host_ref?: string }).target_host_ref === hid)
      .map((a) => bucket(a.id)).filter(Boolean) as State[];
    for (const s of RANK) if (mine.includes(s)) return s;
    return deployed(hosts.find((h) => h.id === hid) as EnvHost) ? "partial" : "not_tested";
  };

  const attackers = hosts.filter(isAttacker);
  const targets = hosts.filter((h) => !isAttacker(h) && deployed(h));
  const dormant = hosts.filter((h) => !isAttacker(h) && !deployed(h));
  if (targets.length === 0) return null;

  const W = 960, colX = [150, 486, 812];
  const place = (list: EnvHost[], col: 0 | 1 | 2, attacker: boolean): PNode[] => {
    const n = Math.max(list.length, 1);
    const gap = 300 / (n + 1);
    return list.slice(0, 5).map((h, i) => ({
      id: h.id, role: h.role, col, x: colX[col], y: 70 + gap * (i + 1) + (n === 1 ? 70 : 0),
      state: attacker ? "reproduced" : hostState(h.id), attacker,
      vuln: !attacker && deployed(h) && /vuln|cve/i.test(h.image_hint || ""),
    }));
  };
  const nodes = [...place(attackers.length ? attackers : [{ id: "attacker", role: "attacker", networks: [] }], 0, true),
    ...place(targets, 1, false), ...place(dormant, 2, false)];
  const primary = nodes.find((n) => n.col === 1 && n.vuln) ?? nodes.find((n) => n.col === 1)!;
  const atk = nodes.find((n) => n.attacker)!;
  const edges = [
    { from: atk, to: primary, dashed: false },
    ...nodes.filter((n) => n.col === 2).map((n) => ({ from: primary, to: n, dashed: true })),
  ];
  return { nodes, edges, atk, primary, W };
}

const PHASES = ["rp.ar.p.recon", "rp.ar.p.exploit", "rp.ar.p.result", "rp.ar.p.pivot", "rp.ar.p.untested"];

export function AttackReplay({ ir, report }: { ir: ScenarioIR; report: ValidationReport }) {
  const model = useMemo(() => buildModel(ir, report), [ir, report]);
  const [phase, setPhase] = useState(0);
  const [run, setRun] = useState(0);

  useEffect(() => {
    if (!model) return;
    const prefersReduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (prefersReduce) { setPhase(4); return; }
    const steps = [300, 1300, 600, 1600, 1400, 2200];
    const timers: number[] = [];
    let acc = 0;
    [0, 1, 2, 3, 4].forEach((p, i) => { acc += steps[i]; timers.push(window.setTimeout(() => setPhase(p), acc)); });
    acc += steps[5];
    timers.push(window.setTimeout(() => setRun((r) => r + 1), acc)); // loop
    return () => timers.forEach(clearTimeout);
  }, [model, run]);

  if (!model) return null;
  const { nodes, edges, primary, W } = model;
  const primaryBadge = report.checks?.find((c) => c.category === "behavior" && c.status === "PASS");

  return (
    <div className="card ar">
      <div className="card-head"><h2>{t("rp.ar.title")}</h2>
        <div className="right"><button className="link" onClick={() => { setPhase(0); setRun((r) => r + 1); }}>↻ {t("rp.ar.replay")}</button></div>
      </div>
      <div className="ar-stage">
        <svg viewBox={`0 0 ${W} 420`} className="ar-svg" role="img" aria-label={t("rp.ar.title")}>
          {/* zones */}
          <rect className="ar-zone" x="20" y="24" width="300" height="372" rx="12" />
          <rect className="ar-zone sc" x="340" y="24" width={W - 360} height="372" rx="12" />
          <text className="ar-zlabel" x="40" y="48">{t("tp.external")}</text>
          <text className="ar-zlabel" x="360" y="48">{t("tp.isolated")}</text>
          <line className="ar-boundary" x1="330" y1="34" x2="330" y2="386" />
          {/* edges */}
          {edges.map((e, i) => {
            const active = (e.dashed && phase >= 3) || (!e.dashed && phase >= 1);
            return <line key={i} className={`ar-edge ${e.dashed ? "dash" : ""} ${active ? "on" : ""}`}
              x1={e.from.x} y1={e.from.y} x2={e.to.x} y2={e.to.y} />;
          })}
          {/* packets */}
          {phase >= 1 && phase < 3 && <circle className="ar-packet run" r="6"
            cx={model.atk.x} cy={model.atk.y} style={{ ["--dx" as string]: `${primary.x - model.atk.x}px`, ["--dy" as string]: `${primary.y - model.atk.y}px` }} />}
          {phase >= 3 && edges.filter((e) => e.dashed).map((e, i) => (
            <circle key={i} className="ar-packet idle run" r="5" cx={e.from.x} cy={e.from.y}
              style={{ ["--dx" as string]: `${e.to.x - e.from.x}px`, ["--dy" as string]: `${e.to.y - e.from.y}px` }} />
          ))}
          {/* nodes */}
          {nodes.map((n) => {
            const revealed = n.attacker || (n === primary ? phase >= 2 : n.col === 2 ? phase >= 4 : phase >= 2);
            const colour = n.attacker ? "var(--accent)" : revealed ? STATE_VAR[n.state] : "var(--border)";
            const w = 168, h = 46;
            return (
              <g key={n.id} className={`ar-node ${revealed ? "rev" : ""}`} transform={`translate(${n.x - w / 2},${n.y - h / 2})`} style={{ ["--c" as string]: colour }}>
                {n.attacker && phase >= 0 && <rect className="ar-glow" x="-4" y="-4" width={w + 8} height={h + 8} rx="11" />}
                {n === primary && revealed && n.state !== "not_tested" && n.state !== "failed" && <rect className="ar-ripple" x="0" y="0" width={w} height={h} rx="9" style={{ transformOrigin: `${w / 2}px ${h / 2}px` }} />}
                <rect className="ar-box" width={w} height={h} rx="9" />
                <circle className="ar-dot" cx="16" cy={h / 2} r="4" />
                <text className="ar-role" x="30" y={h / 2 - 2}>{n.role.length > 24 ? n.role.slice(0, 23) + "…" : n.role}</text>
                <text className="ar-sub" x="30" y={h / 2 + 13}>{n.attacker ? t("rp.ar.attacker") : revealed ? t(STATE_LABEL[n.state] as Parameters<typeof t>[0]) : t("rp.ar.waiting")}</text>
              </g>
            );
          })}
          {/* evidence badge on the primary target */}
          {phase >= 2 && primaryBadge && (
            <g className="ar-badge" transform={`translate(${primary.x},${primary.y + 34})`}>
              <rect x="-96" y="-13" width="192" height="24" rx="12" />
              <text x="0" y="3" textAnchor="middle">✓ {t("rp.ar.verified")}</text>
            </g>
          )}
        </svg>
        <div className="ar-cap"><span className="ar-cap-dot" />{t(PHASES[phase] as Parameters<typeof t>[0])}</div>
      </div>
      <div className="ar-legend">
        {(["reproduced", "partial", "failed", "not_tested"] as State[]).map((s) => (
          <span key={s} className="ar-leg"><i style={{ background: STATE_VAR[s] }} />{t(STATE_LABEL[s] as Parameters<typeof t>[0])}</span>
        ))}
      </div>
    </div>
  );
}
