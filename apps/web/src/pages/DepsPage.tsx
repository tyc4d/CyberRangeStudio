import { useMemo, useState } from "react";
import { joinList, t } from "../i18n";
import type { ScenarioIR, ServiceItem } from "@contracts";
import { api } from "../lib/api";
import { useAction, useLoad } from "../lib/hooks";
import { useScenario } from "../lib/scenario";
import { BasisTag, basisOf, type Versioned } from "../components/VersionBasis";
import { RefIssuesNotice } from "../components/RefIssues";
import { ApiNotice, Busy, DataView, Empty, EpistemicBadge, Metric, NextStep, Notice, PageHead, ScenarioGate, SourceTag } from "../components/ui";

function ServiceRow({ s, hosts }: { s: ServiceItem; hosts?: string[] }) {
  return (
    <tr>
      <td>
        <div style={{ fontWeight: 600 }}>{s.name}</div>
        <div className="mono muted">{s.id}</div>
      </td>
      <td>
        <span className="mono">{s.version ?? <span className="muted">{t("dep.notStated")}</span>}</span>
        {basisOf(s as Versioned) && (
          <div style={{ marginTop: 4, fontSize: 12 }}>
            <BasisTag of={s as Versioned} />
            {(s as Versioned).deployed_version && <span className="muted"> {t("dep.deployed", { v: (s as Versioned).deployed_version })}</span>}
          </div>
        )}
      </td>
      <td>{hosts?.length ? joinList(hosts) : <span className="muted">—</span>}</td>
      <td>
        {s.catalogue_component ? <span className="mono">{s.catalogue_component}</span>
          : (s as { no_component?: boolean }).no_component
            ? <span className="status-FAIL" title={t("dep.noComp.hint")}>{t("dep.noComp")}</span>
            : <span className="muted">{t("dep.unmapped")}</span>}
        {s.is_substitute && <span className="tag sub" style={{ marginLeft: 6 }} title={t("dep.sub.hint")}>{(s as { substitute_basis?: string }).substitute_basis === "user_chosen" ? t("dep.subMine") : t("dep.sub")}</span>}
      </td>
      <td>{s.cve?.length ? s.cve.map((c) => <div key={c} className="mono">{c}</div>) : <span className="muted">—</span>}</td>
      <td><EpistemicBadge status={s.epistemic_status} /></td>
      <td><SourceTag source={s.source} /></td>
    </tr>
  );
}

function Body({ ir }: { ir: ScenarioIR }) {
  const { absorb } = useScenario();
  const hosts = ir.hosts ?? [];
  const services = ir.services ?? [];
  const [ranOk, setRanOk] = useState(false);
  const run = useAction(async () => { setRanOk(false); await absorb(await api.analyzeDependencies(ir.id)); setRanOk(true); });
  const catalogue = useLoad(() => api.catalogue(), []);
  const catItems: unknown[] | null = Array.isArray(catalogue.data) ? catalogue.data
    : Array.isArray(catalogue.data?.components) ? catalogue.data.components : null;

  const svcById = useMemo(() => new Map(services.map((s) => [s.id, s])), [services]);
  const hostsOf = useMemo(() => {
    const m = new Map<string, string[]>();
    hosts.forEach((h) => h.service_refs?.forEach((r) => m.set(r, [...(m.get(r) ?? []), h.role || h.id])));
    return m;
  }, [hosts]);
  const hostOfRef = (s: ServiceItem) => {
    const ref = (s as { host_ref?: string }).host_ref;
    const h = ref ? hosts.find((x) => x.id === ref) : undefined;
    return ref ? [h?.role || ref] : undefined;
  };
  const noComponent = services.filter((s) => (s as { no_component?: boolean }).no_component);
  const substitutes = services.filter((s) => s.is_substitute);
  const has = hosts.length > 0 || services.length > 0;
  // The dependency analysis stamps a fidelity verdict on the IR; without it, what is listed below came straight from the report analysis.
  const analysed = (ir as { fidelity?: unknown }).fidelity !== undefined;

  return (
    <div className="page">
      <PageHead title={t("dep.title")} desc={t("dep.desc")}>
        <button className={analysed ? "" : "primary"} disabled={run.busy} onClick={() => run.run()}>{analysed ? t("dep.rerun") : t("dep.run")}</button>
      </PageHead>

      {run.busy && <div className="card"><Busy label={t("dep.busy")} elapsed={run.elapsed} /></div>}
      <ApiNotice error={run.error} what={t("dep.what")} />
      {ranOk && !run.busy && (has
        ? <Notice kind="info">{t("dep.done")}</Notice>
        : <Notice kind="warn" title={t("dep.empty.title")}>{t("dep.empty.body")}</Notice>)}

      {has && !analysed && !run.busy && (
        <Notice kind="warn" title={t("dep.notRun.title")}>
          {t("dep.notRun.body")}
        </Notice>
      )}
      {analysed && <RefIssuesNotice ir={ir} context="deps" />}
      {analysed && noComponent.length > 0 && (
        <Notice kind="warn" title={t("dep.noComp.title", { n: noComponent.length })}>
          <div data-testid="no-component">
            <div>{t("dep.noComp.body1", { list: joinList(noComponent.map((s) => s.name || s.id)) })}</div>
            <div>{t("dep.noComp.body2")}</div>
            <div className="muted" style={{ fontSize: 12 }}>{t("dep.noComp.body3")}</div>
          </div>
        </Notice>
      )}

      {!has ? (
        <div className="card"><Empty>{t("dep.noData")}</Empty></div>
      ) : (
        <>
          <div className="grid c4">
            <Metric k={t("dep.m.hosts")} v={hosts.length} />
            <Metric k={t("dep.m.services")} v={services.length} />
            <Metric k={t("dep.m.subs")} v={substitutes.length} hint={t("dep.m.subs.hint")} />
            <Metric k={t("dep.m.unmapped")} v={services.filter((s) => !s.catalogue_component).length} />
          </div>

          <div className="card flush" style={{ overflowX: "auto" }}>
            <div className="card-head"><h2>{t("dep.hosts")}</h2></div>
            {hosts.length === 0 ? <Empty>{t("dep.noHosts")}</Empty> : (
              <table className="tbl">
                <thead><tr><th>{t("dep.col.role")}</th><th>{t("dep.col.os")}</th><th>{t("dep.col.services")}</th><th>{t("dep.col.basis")}</th><th>{t("dep.col.source")}</th></tr></thead>
                <tbody>
                  {hosts.map((h) => (
                    <tr key={h.id}>
                      <td><div style={{ fontWeight: 600 }}>{h.role}</div><div className="mono muted">{h.id}</div></td>
                      <td>{h.os ? `${h.os}${h.os_version ? ` ${h.os_version}` : ""}` : <span className="muted">{t("dep.unknown")}</span>}</td>
                      <td>
                        {h.service_refs?.length ? h.service_refs.map((r) => {
                          const s = svcById.get(r);
                          return <span key={r} className={`tag ${s?.is_substitute ? "sub" : ""}`} style={{ marginRight: 4 }} title={s ? undefined : t("dep.svcMissing")}>{s ? `${s.name}${s.version ? ` ${s.version}` : ""}` : r}</span>;
                        }) : <span className="muted">—</span>}
                      </td>
                      <td><EpistemicBadge status={h.epistemic_status} /></td>
                      <td><SourceTag source={h.source} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className="card flush" style={{ overflowX: "auto" }}>
            <div className="card-head"><h2>{t("dep.services")}</h2></div>
            {services.length === 0 ? <Empty>{t("dep.noServices")}</Empty> : (
              <table className="tbl">
                <thead><tr><th>{t("dep.col.name")}</th><th>{t("dep.col.version")}</th><th>{t("dep.col.host")}</th><th>{t("dep.col.component")}</th><th>CVE</th><th>{t("dep.col.basis")}</th><th>{t("dep.col.source")}</th></tr></thead>
                <tbody>{services.map((s) => <ServiceRow key={s.id} s={s} hosts={hostsOf.get(s.id) ?? hostOfRef(s)} />)}</tbody>
              </table>
            )}
          </div>
        </>
      )}

      {/* Reference data. Folded, because most users never need the full catalog. */}
      <details className="card flush deploy-more">
        <summary>{t("dep.catalog")}{catItems && <span className="muted" style={{ fontSize: 12 }}>{catItems.length}</span>}</summary>
        <div style={{ padding: catItems?.length ? 0 : 14 }}>
          {catalogue.error ? <ApiNotice error={catalogue.error} what={t("dep.catalogWhat")} onRetry={() => catalogue.reload()} />
            : catalogue.loading ? <span className="muted"><span className="spinner" /> {t("dep.loading")}</span>
            : catItems ? (catItems.length ? <DataView data={catItems} /> : <span className="muted">{t("dep.catalogEmpty")}</span>)
            : <DataView data={catalogue.data} />}
        </div>
      </details>

      <NextStep prev={{ to: "/flow", label: t("stage.flow") }} next={{ to: "/topology", label: t("stage.topology") }} />
    </div>
  );
}

export function DepsPage() {
  const { ir } = useScenario();
  return <ScenarioGate title={t("dep.title")}>{ir && <Body ir={ir} />}</ScenarioGate>;
}
