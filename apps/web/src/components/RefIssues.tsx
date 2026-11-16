// Why a plan ends up with excluded services / no connections, and where in the UI to fix it.
// Everything here is read from the loaded IR; nothing is guessed or repaired silently.
import { Link } from "react-router-dom";
import type { ScenarioIR } from "@contracts";
import { Notice } from "./ui";
import { joinList, t } from "../i18n";

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
    unplacedServices: (ir.services ?? []).filter((s) => !placed.has(s.id) && !(s as { host_ref?: string }).host_ref).map((s) => ({ id: s.id, name: s.name })),
  };
}

const few = (xs: string[], n = 4) => (xs.length > n ? t("list.more", { list: joinList(xs.slice(0, n)), n: xs.length, more: xs.length - n }) : joinList(xs));

/** Shown on the dependency / topology / IaC pages when the IR's host references do not line up. Renders nothing when they do. */
export function RefIssuesNotice({ ir, context }: { ir: ScenarioIR; context: "deps" | "topology" | "iac" }) {
  const { danglingActions, placeholderActions, unplacedServices } = findRefIssues(ir);
  const actionFix = danglingActions.length + placeholderActions.length > 0;
  if (!actionFix && !unplacedServices.length) return null;
  const refs = [...new Set(danglingActions.map((a) => a.ref))];
  return (
    <Notice kind="warn" title={t("ref.title")}
      action={actionFix ? <Link to="/flow"><button className="small">{t("ref.toFlow")}</button></Link> : undefined}>
      <div data-testid="ref-issues">
        <ul style={{ margin: "4px 0", paddingLeft: 18 }}>
          {placeholderActions.length > 0 && (
            <li>{t("ref.placeholder", { n: placeholderActions.length, names: few(placeholderActions.map((a) => a.name || a.id)) })}</li>
          )}
          {danglingActions.length > 0 && (
            <li>{t("ref.dangling", { n: danglingActions.length, refs: few(refs), names: few(danglingActions.map((a) => a.name || a.id)) })}</li>
          )}
          {unplacedServices.length > 0 && (
            <li>{t("ref.unplaced", { n: unplacedServices.length, names: few(unplacedServices.map((s) => s.name || s.id)) })}{context === "iac" ? ` ${t("ref.unplacedIac")}` : ""}</li>
          )}
        </ul>
        {actionFix && (
          <div>{t("ref.fix")}{context !== "deps" && ` ${t("ref.fixMore")}`}</div>
        )}
        {unplacedServices.length > 0 && (
          <div style={{ marginTop: 4 }}>{t("ref.limit")}</div>
        )}
      </div>
    </Notice>
  );
}
