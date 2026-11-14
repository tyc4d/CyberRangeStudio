// Whether a deployed version is a fact from the report, an assumption, or a substitute.
// The backend decides (version_basis / deployed_version); this only renders its verdict, never infers one.
import type { ScenarioIR } from "@contracts";

export type Basis = "stated" | "assumed" | "substituted";
export interface Versioned { version_basis?: string; deployed_version?: string; version?: string }

export const BASIS: Record<Basis, { label: string; cls: string; explain: string }> = {
  stated: { label: "原文版本", cls: "", explain: "部署的版本與原文（或你的補充）寫的版本相符。" },
  assumed: { label: "假設版本", cls: "sub", explain: "原文沒有寫版本；部署的是靶場元件目錄現有的版本，是假設，不是原文事實。" },
  substituted: { label: "替代版本", cls: "sub", explain: "原文寫的是另一個版本；元件目錄沒有那個版本，部署的是替代版本，行為可能與原事件不同。" },
};
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
      <div className="card-head"><h2>部署版本的依據</h2><span className="muted" style={{ fontSize: 12 }}>{notFact.length ? `${notFact.length} 項不是原文事實` : "皆與原文相符"}</span></div>
      <div style={{ overflowX: "auto" }}>
        <table className="tbl">
          <thead><tr><th>主機</th><th>軟體</th><th>原文寫的版本</th><th>實際部署的版本</th><th>依據</th></tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td>{r.hostName}</td><td>{r.software}</td>
                <td>{r.stated ?? <span className="muted">原文未寫</span>}</td>
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
            ? "驗證中的「版本」檢查通過，只代表容器跑的是上表「實際部署的版本」；標為假設或替代的項目，不能據此說環境重現了原事件的版本。"
            : "標為假設或替代的版本是靶場的選擇，不是原文的內容。教學時請向學員說明這個差異。"}
        </div>
      )}
    </div>
  );
}
