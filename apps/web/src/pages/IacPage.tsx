import { useState } from "react";
import type { ScenarioIR } from "@contracts";
import { api, type ApiError } from "../lib/api";
import { useAction, useLoad } from "../lib/hooks";
import { useScenario } from "../lib/scenario";
import { VersionBasisCard } from "../components/VersionBasis";
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
    ? <Notice kind="info" title="可部署">後端檢查認為這份設定可以部署。細節見下方報告。</Notice>
    : <Notice kind="err" title="目前不可部署">後端檢查發現阻擋部署的問題，請依下方報告修正後重新生成。</Notice>;
}

/** The generator's refusal payload ({errors, report}); null for any other failure. */
function planFailure(e: ApiError | null): { errors: string[]; report: any } | null {
  const d = e?.data as any;
  if (!e || (e.status !== 422 && e.status !== 409) || !d || !Array.isArray(d.errors)) return null;
  return { errors: d.errors.map(String), report: d.report };
}
const ERR_RULES: [RegExp, (m: RegExpMatchArray) => string][] = [
  [/^host (.+) cannot be resolved to a safe local image$/, (m) => `主機 ${m[1]} 找不到可用的安全本機映像（它的服務沒有對應到元件目錄中的元件）。`],
  [/^host (.+) could not be resolved to a supported component$/, (m) => `主機 ${m[1]} 無法對應到支援的元件。`],
  [/^host (.+) runtime=vm is not supported by the configured deployment backend: (.*)$/, (m) => `主機 ${m[1]} 需要虛擬機，但這台伺服器的虛擬機後端尚未安裝或設定。`],
  [/^connection (.+) -> (.+):(\d+) does not match a declared target service$/, (m) => `連線 ${m[1]} → ${m[2]}:${m[3]} 對不上目標主機宣告的任何服務。`],
  [/^at least one host is required$/, () => "規劃中至少要有一台主機。"],
];
const errZh = (t: string): string | null => { for (const [re, f] of ERR_RULES) { const m = t.match(re); if (m) return f(m); } return null; };

function IacFailure({ detail }: { detail: { errors: string[]; report: any } }) {
  const comps: any[] = Array.isArray(detail.report?.components) ? detail.report.components : [];
  return (
    <Notice kind="err" title="IaC 沒有生成：這份規劃目前不可部署">
      <div data-testid="iac-failure">
        <div>沒有產生任何 compose 檔，也沒有啟動任何東西。阻擋原因（{detail.errors.length}）：</div>
        <ul style={{ margin: "4px 0", paddingLeft: 18 }}>
          {detail.errors.map((e, i) => { const z = errZh(e); return <li key={i}>{z ?? e}{z && <div className="muted" lang="en" style={{ fontSize: 11, overflowWrap: "anywhere" }}>{e}</div>}</li>; })}
        </ul>
        {comps.length > 0 && (
          <div style={{ overflowX: "auto", margin: "8px 0" }}>
            <table className="tbl">
              <thead><tr><th>主機</th><th>對應元件</th><th>映像</th><th>可部署</th></tr></thead>
              <tbody>
                {comps.map((c, i) => (
                  <tr key={i}>
                    <td className="mono">{String(c.host_id ?? "—")}</td>
                    <td>{c.component ? String(c.component) : <span className="muted">未對應</span>}</td>
                    <td className="mono">{c.image ? `${c.image}${c.version ? `:${c.version}` : ""}` : <span className="muted">無</span>}</td>
                    <td className={c.deployable ? "status-PASS" : "status-FAIL"}>{c.deployable ? "是" : "否"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div>下一步：回「軟體依賴」查看哪些主機的服務沒有「對應元件」。要讓一台主機可部署，它的服務必須對應到元件目錄中的元件，且該服務的「所在主機」是這台主機；條件滿足後重新規劃拓樸、重新核准，再回來生成。在此之前這個情境維持不可部署。</div>
        {detail.report && <details style={{ marginTop: 6 }}><summary className="muted" style={{ cursor: "pointer" }}>後端原始檢查報告</summary><div style={{ marginTop: 6 }}><DataView data={detail.report} /></div></details>}
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
      <PageHead title="IaC 預覽" desc="由環境規劃生成的 Docker Compose 設定，以及它是否可以部署的檢查報告。這一步只產生檔案，不會啟動任何容器。">
        <button className={files.length ? "" : "primary"} disabled={gen.busy} onClick={() => gen.run()}>{files.length ? "重新生成" : "生成 IaC"}</button>
      </PageHead>

      {!ir.environment_plan && <Notice kind="warn" title="尚無環境規劃">IaC 由拓樸規劃生成，建議先完成「拓樸」步驟。</Notice>}
      {gen.busy && <div className="card"><Busy label="生成 IaC 中…" elapsed={gen.elapsed} /></div>}
      {planFailure(gen.error) ? <IacFailure detail={planFailure(gen.error)!} /> : <ApiNotice error={gen.error} what="IaC 生成" />}
      {ir.environment_plan && <RefIssuesNotice ir={ir} context="iac" />}

      {iac.loading && !iac.data ? (
        <div className="card"><Busy label="讀取已生成的 IaC…" /></div>
      ) : iac.error && !notGenerated && !iac.data ? (
        <ApiNotice error={iac.error} what="IaC 讀取" onRetry={() => iac.reload()} />
      ) : !iac.data || notGenerated ? (
        <div className="card"><Empty>這個情境還沒有生成 IaC。按右上角「生成 IaC」。</Empty></div>
      ) : (
        <>
          <Verdict report={report} />
          <VersionBasisCard ir={ir} context="iac" />
          <div className="card flush">
            <div className="card-head">
              {files.length > 1 ? (
                <div className="seg">{files.map((f, i) => <button key={f.name} className={`mono ${file === f ? "on" : ""}`} onClick={() => setActive(i)}>{f.name}</button>)}</div>
              ) : <h2 className="mono">{file?.name ?? "docker-compose.yml"}</h2>}
              {file && <div className="right">
                <span className="muted" style={{ fontSize: 12 }}>{file.content.split("\n").length} 行</span>
                <button className="small" onClick={copy}>{copied ? "已複製" : "複製"}</button>
              </div>}
            </div>
            {file ? (
              <pre className="code" style={{ border: "none", borderRadius: 0 }}>
                {file.content.replace(/\n$/, "").split("\n").map((l, i) => <span key={i} className="ln">{l || " "}</span>)}
              </pre>
            ) : <Empty>後端有回應，但其中沒有 compose 內容。</Empty>}
          </div>

          <div className="card">
            <h2>可部署報告</h2>
            {report === undefined || report === null ? <span className="muted" style={{ fontSize: 13 }}>後端沒有提供可部署報告。</span> : <DataView data={report} />}
          </div>
        </>
      )}

      <NextStep prev={{ to: "/topology", label: "拓樸" }} next={{ to: "/deploy", label: "部署管理" }} />
    </div>
  );
}

export function IacPage() {
  const { ir } = useScenario();
  return <ScenarioGate title="IaC 預覽">{ir && <Body key={ir.id} ir={ir} />}</ScenarioGate>;
}
