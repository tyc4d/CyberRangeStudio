import { useState } from "react";
import type { ScenarioIR } from "@contracts";
import { api } from "../lib/api";
import { useAction, useLoad } from "../lib/hooks";
import { useScenario } from "../lib/scenario";
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
      <ApiNotice error={gen.error} what="IaC 生成" />

      {iac.loading && !iac.data ? (
        <div className="card"><Busy label="讀取已生成的 IaC…" /></div>
      ) : iac.error && !notGenerated && !iac.data ? (
        <ApiNotice error={iac.error} what="IaC 讀取" onRetry={() => iac.reload()} />
      ) : !iac.data || notGenerated ? (
        <div className="card"><Empty>這個情境還沒有生成 IaC。按右上角「生成 IaC」。</Empty></div>
      ) : (
        <>
          <Verdict report={report} />
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
