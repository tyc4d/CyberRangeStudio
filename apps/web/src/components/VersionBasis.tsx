// Whether a deployed version is a fact from the report, an assumption, or a substitute.
// The backend decides (version_basis / deployed_version); this only renders its verdict, never infers one.
import type { ScenarioIR } from "@contracts";
import { live, t } from "../i18n";

export type Basis = "stated" | "assumed" | "substituted";
export interface Versioned { version_basis?: string; deployed_version?: string; version?: string }

export const BASIS: Record<Basis, { label: string; cls: string; explain: string }> = live(() => ({
  stated: { label: t("vb.stated"), cls: "", explain: t("vb.stated.explain") },
  assumed: { label: t("vb.assumed"), cls: "sub", explain: t("vb.assumed.explain") },
  substituted: { label: t("vb.substituted"), cls: "sub", explain: t("vb.substituted.explain") },
}));
export const basisOf = (x: Versioned | undefined | null): Basis | null =>
  x && (x.version_basis === "stated" || x.version_basis === "assumed" || x.version_basis === "substituted") ? x.version_basis : null;

export function BasisTag({ of }: { of: Versioned | undefined | null }) {
  const b = basisOf(of);
  if (!b) return null;
  return <span className={`tag ${BASIS[b].cls}`} title={BASIS[b].explain} data-testid={`version-basis-${b}`}>{BASIS[b].label}</span>;
}

export interface VersionRow { hostId: string; hostName: string; software: string; stated?: string; deployed?: string; basis: Basis }
/** One row per service whose deployed version the backend has classified, with the host it runs on. */
export function versionRows(ir: ScenarioIR): VersionRow[] {
  const hosts = ir.hosts ?? [];
  return (ir.services ?? []).flatMap((s) => {
    const b = basisOf(s as Versioned);
    if (!b) return [];
    const ref = (s as { host_ref?: string }).host_ref;
    const h = hosts.find((x) => x.id === ref) ?? hosts.find((x) => x.service_refs?.includes(s.id));
    return [{
      hostId: h?.id ?? ref ?? "", hostName: h ? (h as { name?: string }).name || h.role || h.id : ref ?? "—",
      software: s.name, stated: s.version ?? undefined,
      deployed: (s as Versioned).deployed_version ?? (b === "stated" ? s.version ?? undefined : undefined), basis: b,
    }];
  });
}

/** Table of deployed versions vs. what the report states. Renders nothing when the backend classified no version. */
export function VersionBasisCard({ ir, context }: { ir: ScenarioIR; context: "iac" | "report" }) {
  const rows = versionRows(ir);
  if (!rows.length) return null;
  const notFact = rows.filter((r) => r.basis !== "stated");
  return (
    <div className="card flush" data-testid="version-basis-card">
      <div className="card-head"><h2>{t("vb.title")}</h2><span className="muted" style={{ fontSize: 12 }}>{notFact.length ? t("vb.notFact", { n: notFact.length }) : t("vb.allStated")}</span></div>
      <div style={{ overflowX: "auto" }}>
        <table className="tbl">
          <thead><tr><th>{t("vb.host")}</th><th>{t("vb.software")}</th><th>{t("vb.statedCol")}</th><th>{t("vb.deployedCol")}</th><th>{t("vb.basis")}</th></tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td>{r.hostName}</td><td>{r.software}</td>
                <td>{r.stated ?? <span className="muted">{t("vb.notStated")}</span>}</td>
                <td className="mono">{r.deployed ?? "—"}</td>
                <td><BasisTag of={{ version_basis: r.basis }} /><div className="muted" style={{ fontSize: 12, marginTop: 2 }}>{BASIS[r.basis].explain}</div></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {notFact.length > 0 && (
        <div className="muted" style={{ fontSize: 12, padding: "10px 14px" }}>
          {context === "report"
            ? t("vb.noteReport")
            : t("vb.noteIac")}
        </div>
      )}
    </div>
  );
}

/* ---------- substitutes: a host whose image stands in for the software the report names ---------- */
export const SUBSTITUTE_BASIS: Record<string, { label: string; explain: string }> = live(() => ({
  user_chosen: { label: t("sub.user"), explain: t("sub.user.explain") },
  catalogue_substitute: { label: t("sub.catalogue"), explain: t("sub.catalogue.explain") },
}));
interface PlanHostX { id: string; role?: string; image_hint?: string; substitute_for?: string; substitute_basis?: string; services?: { name?: string; port?: number; stated_port?: number; port_basis?: string }[] }
export interface SubstituteRow { hostId: string; hostName: string; original: string; image?: string; basis: string; ports: { name?: string; port?: number; stated: number }[] }
/** Hosts the plan deploys with a stand-in, and services whose port had to follow the stand-in. Straight from the plan. */
export function substituteRows(ir: ScenarioIR): SubstituteRow[] {
  const hosts = ((ir.environment_plan as { hosts?: PlanHostX[] } | undefined)?.hosts ?? []);
  return hosts.flatMap((h) => {
    const ports = (h.services ?? []).filter((s) => s.port_basis === "substitute_default" && typeof s.stated_port === "number").map((s) => ({ name: s.name, port: s.port, stated: s.stated_port! }));
    if (!h.substitute_for && !ports.length) return [];
    return [{ hostId: h.id, hostName: h.role || h.id, original: h.substitute_for ?? "", image: h.image_hint, basis: h.substitute_basis ?? "", ports }];
  });
}

export function SubstituteCard({ ir, context }: { ir: ScenarioIR; context: "iac" | "report" }) {
  const rows = substituteRows(ir);
  if (!rows.length) return null;
  return (
    <div className="card flush" data-testid="substitute-card">
      <div className="card-head"><h2>{t("sub.title")}</h2><span className="muted" style={{ fontSize: 12 }}>{t("sub.count", { n: rows.length })}</span></div>
      <div style={{ overflowX: "auto" }}>
        <table className="tbl">
          <thead><tr><th>{t("vb.host")}</th><th>{t("sub.original")}</th><th>{t("sub.deployed")}</th><th>{t("sub.who")}</th><th>{t("sub.port")}</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.hostId}>
                <td>{r.hostName}</td>
                <td>{r.original || <span className="muted">—</span>}</td>
                <td><span className="tag sub">{t("sub.tag")}</span> <span className="mono">{r.image ?? "—"}</span></td>
                <td>{SUBSTITUTE_BASIS[r.basis]?.label ?? (r.basis || "—")}<div className="muted" style={{ fontSize: 12 }}>{SUBSTITUTE_BASIS[r.basis]?.explain}</div></td>
                <td>{r.ports.length ? r.ports.map((p, i) => <div key={i} className="mono">{t("sub.portUse", { port: p.port, stated: p.stated })}</div>) : <span className="muted">{t("sub.portSame")}</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="muted" style={{ fontSize: 12, padding: "10px 14px" }}>
        {context === "report"
          ? t("sub.noteReport")
          : t("sub.noteIac")}
      </div>
    </div>
  );
}
