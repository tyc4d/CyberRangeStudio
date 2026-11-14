// Why a plan ends up with excluded services / no connections, and where in the UI to fix it.
// Everything here is read from the loaded IR; nothing is guessed or repaired silently.
import { Link } from "react-router-dom";
import type { ScenarioIR } from "@contracts";
import { Notice } from "./ui";

export interface RefIssues {
  /** Actions whose target host id is not one of the scenario's hosts. */
  danglingActions: { id: string; name: string; ref: string }[];
  /** Actions aimed at a placeholder host literally called "unknown". */
  placeholderActions: { id: string; name: string }[];
  /** Services no host lists, so the planner cannot place them. */
  unplacedServices: { id: string; name: string }[];
}

const isPlaceholder = (v?: string) => /^unknown$/i.test((v ?? "").trim());

export function findRefIssues(ir: ScenarioIR): RefIssues {
  const hosts = ir.hosts ?? [];
  const hostIds = new Set(hosts.map((h) => h.id));
  const placed = new Set(hosts.flatMap((h) => h.service_refs ?? []));
  const named = (a: ScenarioIR["actions"][number]) => ({ id: a.id, name: a.name });
  return {
    danglingActions: hosts.length
      ? ir.actions.filter((a) => a.target_host_ref && !isPlaceholder(a.target_host_ref) && !hostIds.has(a.target_host_ref)).map((a) => ({ ...named(a), ref: a.target_host_ref! }))
      : [],
    placeholderActions: ir.actions.filter((a) => isPlaceholder(a.target_host_ref)).map(named),
    unplacedServices: (ir.services ?? []).filter((s) => !placed.has(s.id)).map((s) => ({ id: s.id, name: s.name })),
  };
}

const few = (xs: string[], n = 4) => (xs.length > n ? `${xs.slice(0, n).join("、")} 等 ${xs.length} 項` : xs.join("、"));

/** Shown on the dependency / topology / IaC pages when the IR's host references do not line up. Renders nothing when they do. */
export function RefIssuesNotice({ ir, context }: { ir: ScenarioIR; context: "deps" | "topology" | "iac" }) {
  const { danglingActions, placeholderActions, unplacedServices } = findRefIssues(ir);
  const actionFix = danglingActions.length + placeholderActions.length > 0;
  if (!actionFix && !unplacedServices.length) return null;
  const refs = [...new Set(danglingActions.map((a) => a.ref))];
  return (
    <Notice kind="warn" title="主機參照不一致：服務會被排除，連線無法開通"
      action={actionFix ? <Link to="/flow"><button className="small">前往攻擊流程</button></Link> : undefined}>
      <div data-testid="ref-issues">
        <ul style={{ margin: "4px 0", paddingLeft: 18 }}>
          {placeholderActions.length > 0 && (
            <li>{placeholderActions.length} 個攻擊行為的「目標主機」是未指明的主機（<span className="mono">unknown</span>）：{few(placeholderActions.map((a) => a.name || a.id))}。分析沒有把它們對到主機清單中的任何一台。</li>
          )}
          {danglingActions.length > 0 && (
            <li>{danglingActions.length} 個攻擊行為的「目標主機」指向主機清單裡沒有的名稱（<span className="mono">{few(refs)}</span>）：{few(danglingActions.map((a) => a.name || a.id))}。</li>
          )}
          {unplacedServices.length > 0 && (
            <li>{unplacedServices.length} 個服務沒有歸屬任何主機：{few(unplacedServices.map((s) => s.name || s.id))}。規劃時這些服務不會放進任何主機，也不會為它們開通連線{context === "iac" ? "，IaC 因此可能無法生成" : ""}。</li>
          )}
        </ul>
        {actionFix && (
          <div>可以補正的部分：到「攻擊流程」點開上述行為，把「目標主機」改選為主機清單中正確的主機並儲存新版本，再回「軟體依賴」重新分析{context !== "deps" && "、到「拓樸」重新規劃並重新核准"}。</div>
        )}
        {unplacedServices.length > 0 && (
          <div style={{ marginTop: 4 }}>目前的限制：畫面上還沒有「指定服務屬於哪台主機」的操作，重新分析也不一定會補上歸屬。服務仍未歸屬時，這個情境無法部署出可用的連線；系統不會自行猜測歸屬，也不會把它顯示成可部署。</div>
        )}
      </div>
    </Notice>
  );
}
