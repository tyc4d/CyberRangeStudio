import { useState } from "react";
import { t } from "../i18n";
import type { ScenarioIR } from "@contracts";
import { api, type ApiError } from "../lib/api";
import { useAction, useLoad } from "../lib/hooks";
import { useScenario } from "../lib/scenario";
import { SubstituteCard, VersionBasisCard } from "../components/VersionBasis";
import { RefIssuesNotice } from "../components/RefIssues";
import { ApiNotice, Busy, DataView, Empty, NextStep, Notice, PageHead, ScenarioGate } from "../components/ui";

interface IacFile { name: string; content: string }

/** Pull compose text out of the response without assuming more than the contract ({compose, report}) plus its documented aliases. */
function pickFiles(resp: any): IacFile[] {
  if (!resp || typeof resp !== "object") return [];
  const out: IacFile[] = [];
  for (const k of ["compose", "compose_yaml", "docker_compose"]) {
    if (typeof resp[k] === "string" && resp[k].trim()) { out.push({ name: "docker-compose.yml", content: resp[k] }); break; }
  }
  const files = resp.files;
  if (Array.isArray(files)) {
    files.forEach((f: any) => {
      const name = f?.path ?? f?.name;
      if (typeof name === "string" && typeof f?.content === "string") out.push({ name, content: f.content });
    });
  } else if (files && typeof files === "object") {
    Object.entries(files).forEach(([name, content]) => { if (typeof content === "string") out.push({ name, content }); });
  }
  return out.filter((f, i) => out.findIndex((g) => g.name === f.name) === i);
}

function Verdict({ report }: { report: any }) {
  const d = report?.deployable;
  if (typeof d !== "boolean") return null;
  return d
    ? <Notice kind="info" title={t("iac.ok")}>{t("iac.ok.body")}</Notice>
    : <Notice kind="err" title={t("iac.bad")}>{t("iac.bad.body")}</Notice>;
}

/** The generator's refusal payload ({errors, report}); null for any other failure. */
function planFailure(e: ApiError | null): { errors: string[]; report: any } | null {
  const d = e?.data as any;
  if (!e || (e.status !== 422 && e.status !== 409) || !d || !Array.isArray(d.errors)) return null;
  return { errors: d.errors.map(String), report: d.report };
}
const ERR_RULES: [RegExp, (m: RegExpMatchArray) => string][] = [
  [/^host (.+) cannot be resolved to a safe local image$/, (m) => t("iac.e.image", { host: m[1] })],
  [/^host (.+) could not be resolved to a supported component$/, (m) => t("iac.e.component", { host: m[1] })],
  [/^host (.+) runtime=vm is not supported by the configured deployment backend: (.*)$/, (m) => t("iac.e.vm", { host: m[1] })],
  [/^connection (.+) -> (.+):(\d+) does not match a declared target service$/, (m) => t("iac.e.conn", { from: m[1], to: m[2], port: m[3] })],
  [/^at least one host is required$/, () => t("iac.e.noHost")],
];
const errText = (s: string): string | null => { for (const [re, f] of ERR_RULES) { const m = s.match(re); if (m) return f(m); } return null; };

function IacFailure({ detail }: { detail: { errors: string[]; report: any } }) {
  const comps: any[] = Array.isArray(detail.report?.components) ? detail.report.components : [];
  return (
    <Notice kind="err" title={t("iac.fail.title")}>
      <div data-testid="iac-failure">
        <div>{t("iac.fail.body", { n: detail.errors.length })}</div>
        <ul style={{ margin: "4px 0", paddingLeft: 18 }}>
          {detail.errors.map((e, i) => <li key={i}>{errText(e) ?? t("notice.generic")}</li>)}
        </ul>
        {comps.length > 0 && (
          <div style={{ overflowX: "auto", margin: "8px 0" }}>
            <table className="tbl">
              <thead><tr><th>{t("iac.col.host")}</th><th>{t("iac.col.component")}</th><th>{t("iac.col.image")}</th><th>{t("iac.col.ok")}</th></tr></thead>
              <tbody>
                {comps.map((c, i) => (
                  <tr key={i}>
                    <td className="mono">{String(c.host_id ?? "—")}</td>
                    <td>{c.component ? String(c.component) : <span className="muted">{t("iac.unmapped")}</span>}</td>
                    <td className="mono">{c.image ? `${c.image}${c.version ? `:${c.version}` : ""}` : <span className="muted">{t("iac.none")}</span>}</td>
                    <td className={c.deployable ? "status-PASS" : "status-FAIL"}>{c.deployable ? t("data.yes") : t("data.no")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div>{t("iac.fail.next")}</div>
        <details className="tech-details"><summary>{t("notice.techDetails")}</summary>
          <ul style={{ margin: "4px 0", paddingLeft: 18 }} lang="en">{detail.errors.map((e, i) => <li key={i} className="mono">{e}</li>)}</ul>
          {detail.report && <DataView data={detail.report} />}
        </details>
      </div>
    </Notice>
  );
}

function Body({ ir }: { ir: ScenarioIR }) {
  const iac = useLoad(() => api.getIac(ir.id), [ir.id]);
  const gen = useAction(async () => {
    const resp = await api.generateIac(ir.id);
    if (resp && typeof resp === "object" && (pickFiles(resp).length || resp.report)) iac.setData(resp);
    else await iac.reload(true);
  });
  const [active, setActive] = useState(0);
  const [copied, setCopied] = useState(false);

  const files = pickFiles(iac.data);
  const file = files[Math.min(active, files.length - 1)];
  const report = iac.data?.report;
  // A missing IaC for this scenario (404 with its own detail) is "not generated yet", not a failure.
  const notGenerated = !!iac.error && iac.error.status === 404 && iac.error.kind === "error";

  const copy = async () => {
    if (!file) return;
    try { await navigator.clipboard.writeText(file.content); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* clipboard blocked */ }
  };

  return (
    <div className="page">
      <PageHead title={t("iac.title")} desc={t("iac.desc")}>
        <button className={files.length ? "" : "primary"} disabled={gen.busy} onClick={() => gen.run()}>{files.length ? t("iac.regen") : t("iac.gen")}</button>
      </PageHead>

      {!ir.environment_plan && <Notice kind="warn" title={t("iac.noPlan.title")}>{t("iac.noPlan.body")}</Notice>}
      {gen.busy && <div className="card"><Busy label={t("iac.busy")} elapsed={gen.elapsed} /></div>}
      {planFailure(gen.error) ? <IacFailure detail={planFailure(gen.error)!} /> : <ApiNotice error={gen.error} what={t("iac.genWhat")} />}
      {ir.environment_plan && <RefIssuesNotice ir={ir} context="iac" />}

      {iac.loading && !iac.data ? (
        <div className="card"><Busy label={t("iac.loading")} /></div>
      ) : iac.error && !notGenerated && !iac.data ? (
        <ApiNotice error={iac.error} what={t("iac.readWhat")} onRetry={() => iac.reload()} />
      ) : !iac.data || notGenerated ? (
        <div className="card"><Empty>{t("iac.empty")}</Empty></div>
      ) : (
        <>
          <Verdict report={report} />
          <VersionBasisCard ir={ir} context="iac" />
          <SubstituteCard ir={ir} context="iac" />
          <div className="card flush">
            <div className="card-head">
              {files.length > 1 ? (
                <div className="seg">{files.map((f, i) => <button key={f.name} className={`mono ${file === f ? "on" : ""}`} onClick={() => setActive(i)}>{f.name}</button>)}</div>
              ) : <h2 className="mono">{file?.name ?? "docker-compose.yml"}</h2>}
              {file && <div className="right">
                <span className="muted" style={{ fontSize: 12 }}>{t("iac.lines", { n: file.content.split("\n").length })}</span>
                <button className="small" onClick={copy}>{copied ? t("iac.copied") : t("iac.copy")}</button>
              </div>}
            </div>
            {file ? (
              <pre className="code" style={{ border: "none", borderRadius: 0 }}>
                {file.content.replace(/\n$/, "").split("\n").map((l, i) => <span key={i} className="ln">{l || " "}</span>)}
              </pre>
            ) : <Empty>{t("iac.noContent")}</Empty>}
          </div>

          <details className="card deploy-more">
            <summary>{t("iac.report")}</summary>
            {report === undefined || report === null ? <span className="muted" style={{ fontSize: 13 }}>{t("iac.noReport")}</span> : <DataView data={report} />}
          </details>
        </>
      )}

      <NextStep prev={{ to: "/topology", label: t("stage.topology") }} next={{ to: "/deploy", label: t("stage.deploy") }} />
    </div>
  );
}

export function IacPage() {
  const { ir } = useScenario();
  return <ScenarioGate title={t("iac.title")}>{ir && <Body key={ir.id} ir={ir} />}</ScenarioGate>;
}
