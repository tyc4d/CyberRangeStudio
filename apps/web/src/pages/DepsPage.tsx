import { useMemo, useState } from "react";
import type { ScenarioIR, ServiceItem } from "@contracts";
import { api } from "../lib/api";
import { useAction, useLoad } from "../lib/hooks";
import { useScenario } from "../lib/scenario";
import { BasisTag, basisOf, type Versioned } from "../components/VersionBasis";
import { RefIssuesNotice } from "../components/RefIssues";
import { InventoryPanel } from "../components/InventoryPanel";
import { ApiNotice, Busy, DataView, Empty, EpistemicBadge, Metric, NextStep, Notice, PageHead, ScenarioGate, SourceTag } from "../components/ui";

function ServiceRow({ s, hosts }: { s: ServiceItem; hosts?: string[] }) {
  return (
    <tr>
      <td>
        <div style={{ fontWeight: 600 }}>{s.name}</div>
        <div className="mono muted">{s.id}</div>
      </td>
      <td>
        <span className="mono">{s.version ?? <span className="muted">原文未寫</span>}</span>
        {basisOf(s as Versioned) && (
          <div style={{ marginTop: 4, fontSize: 12 }}>
            <BasisTag of={s as Versioned} />
            {(s as Versioned).deployed_version && <span className="muted">　部署 <span className="mono">{(s as Versioned).deployed_version}</span></span>}
          </div>
        )}
      </td>
      <td>{hosts?.length ? hosts.join("、") : <span className="muted">—</span>}</td>
      <td>
        {s.catalogue_component ? <span className="mono">{s.catalogue_component}</span>
          : (s as { no_component?: boolean }).no_component
            ? <span className="status-FAIL" title="元件目錄裡沒有這個軟體，也不會自動用別的軟體頂替。要部署需在「缺失補充」明確選擇替代方案。">目錄無此元件</span>
            : <span className="muted">未對應</span>}
        {s.is_substitute && <span className="tag sub" style={{ marginLeft: 6 }} title="環境中使用的不是報告裡的原始軟體">{(s as { substitute_basis?: string }).substitute_basis === "user_chosen" ? "替代品・你選的" : "替代品"}</span>}
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
      <PageHead title="軟體依賴" desc="重建這條攻擊流程需要的主機與軟體，以及它們對應到哪個可部署的元件。標為「替代品」的項目與報告中的原始軟體不同，會影響重現的擬真度。">
        <button className={analysed ? "" : "primary"} disabled={run.busy} onClick={() => run.run()}>{analysed ? "重新分析依賴" : "執行依賴分析"}</button>
      </PageHead>

      {run.busy && <div className="card"><Busy label="分析軟體依賴中…" elapsed={run.elapsed} /></div>}
      <ApiNotice error={run.error} what="依賴分析" />
      {ranOk && !run.busy && (has
        ? <Notice kind="info">依賴分析完成，結果已更新。</Notice>
        : <Notice kind="warn" title="分析完成，但沒有結果">後端沒有從目前的攻擊流程與補充資訊推導出任何主機或服務。可以回到「缺失補充」補上軟體與版本資訊後再試。</Notice>)}

      {has && !analysed && !run.busy && (
        <Notice kind="warn" title="尚未執行依賴分析">
          下方只是情資分析階段擷取到的主機與服務，還沒有對應到可部署的元件，也可能缺少項目。請按右上角「執行依賴分析」；補充缺失或修改攻擊流程之後也要重新分析一次。
        </Notice>
      )}
      {analysed && <RefIssuesNotice ir={ir} context="deps" />}
      {analysed && noComponent.length > 0 && (
        <Notice kind="warn" title={`${noComponent.length} 個軟體在元件目錄中沒有可部署的對應`}>
          <div data-testid="no-component">
            {noComponent.map((s) => s.name || s.id).join("、")}。系統不會自動拿別的軟體頂替，所以目前這個情境無法生成可部署的 IaC。
            若接受用替代軟體教學，可到「缺失補充」對相關項目選「用替代方案」並寫明用什麼替代，再回來重新分析。
            重新分析後請在下方確認：替代軟體有出現在該主機的「服務」欄，且「對應元件」有值。只出現在服務清單、「所在主機」是「—」的替代軟體不會被部署。
          </div>
        </Notice>
      )}

      {!has ? (
        <div className="card"><Empty>這個情境還沒有主機與服務資料。按右上角「執行依賴分析」由後端產生。</Empty></div>
      ) : (
        <>
          <div className="grid c4">
            <Metric k="主機" v={hosts.length} />
            <Metric k="服務／軟體" v={services.length} />
            <Metric k="使用替代品" v={substitutes.length} hint="is_substitute 為真的服務數" />
            <Metric k="尚未對應元件" v={services.filter((s) => !s.catalogue_component).length} />
          </div>

          <div className="card flush" style={{ overflowX: "auto" }}>
            <div className="card-head"><h2>主機</h2></div>
            {hosts.length === 0 ? <Empty>沒有主機資料。</Empty> : (
              <table className="tbl">
                <thead><tr><th>角色</th><th>作業系統</th><th>服務</th><th>依據</th><th>來源</th></tr></thead>
                <tbody>
                  {hosts.map((h) => (
                    <tr key={h.id}>
                      <td><div style={{ fontWeight: 600 }}>{h.role}</div><div className="mono muted">{h.id}</div></td>
                      <td>{h.os ? `${h.os}${h.os_version ? ` ${h.os_version}` : ""}` : <span className="muted">未知</span>}</td>
                      <td>
                        {h.service_refs?.length ? h.service_refs.map((r) => {
                          const s = svcById.get(r);
                          return <span key={r} className={`tag ${s?.is_substitute ? "sub" : ""}`} style={{ marginRight: 4 }} title={s ? undefined : "找不到這個服務"}>{s ? `${s.name}${s.version ? ` ${s.version}` : ""}` : r}</span>;
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
            <div className="card-head"><h2>服務／軟體</h2></div>
            {services.length === 0 ? <Empty>沒有服務資料。</Empty> : (
              <table className="tbl">
                <thead><tr><th>名稱</th><th>版本</th><th>所在主機</th><th>對應元件</th><th>CVE</th><th>依據</th><th>來源</th></tr></thead>
                <tbody>{services.map((s) => <ServiceRow key={s.id} s={s} hosts={hostsOf.get(s.id) ?? hostOfRef(s)} />)}</tbody>
              </table>
            )}
          </div>
        </>
      )}

      {has && <InventoryPanel ir={ir} />}

      <div className="card flush">
        <div className="card-head"><h2>可用元件 catalogue</h2>{catItems && <span className="muted" style={{ fontSize: 12 }}>{catItems.length}</span>}</div>
        <div style={{ padding: catItems?.length ? 0 : 14 }}>
          {catalogue.error ? <ApiNotice error={catalogue.error} what="元件 catalogue" onRetry={() => catalogue.reload()} />
            : catalogue.loading ? <span className="muted"><span className="spinner" /> 載入中…</span>
            : catItems ? (catItems.length ? <DataView data={catItems} /> : <span className="muted">catalogue 是空的。</span>)
            : <DataView data={catalogue.data} />}
        </div>
      </div>

      <NextStep prev={{ to: "/flow", label: "攻擊流程" }} next={{ to: "/topology", label: "拓樸" }} />
    </div>
  );
}

export function DepsPage() {
  const { ir } = useScenario();
  return <ScenarioGate title="軟體依賴">{ir && <Body ir={ir} />}</ScenarioGate>;
}
