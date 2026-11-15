import type { ScenarioIR } from "@contracts";
import { openCardCount } from "../pages/MissingPage";
import { isPlanApproved } from "./plan";
import type { Runtime } from "./scenario";
import { t } from "../i18n";

export type StageState = { dot: "" | "done" | "warn" | "err"; text?: string; title: string };

/** Progress markers derived only from what the loaded IR actually contains. */
export function stageState(key: string, ir: ScenarioIR | null, runtime: Runtime = {}): StageState | null {
  if (!ir) return null;
  const todo: StageState = { dot: "", title: t("stageState.empty") };
  switch (key) {
    case "import": return { dot: "done", title: t("stageState.imported") };
    case "analysis": return ir.actions.length ? { dot: "done", text: String(ir.actions.length), title: t("stageState.actions", { n: ir.actions.length }) } : todo;
    case "missing": {
      const items = ir.missing_items ?? [];
      const open = openCardCount(ir);
      if (!items.length) return todo;
      return open ? { dot: "warn", text: String(open), title: t("stageState.open", { n: open }) } : { dot: "done", title: t("stageState.allDone") };
    }
    case "flow": return (ir.ir_version ?? 1) > 1 ? { dot: "done", text: `v${ir.ir_version}`, title: t("stageState.version", { v: ir.ir_version }) } : todo;
    case "deps": return ir.hosts?.length || ir.services?.length ? { dot: "done", title: t("stageState.hasHosts") } : todo;
    case "topology":
      if (!ir.environment_plan) return todo;
      return isPlanApproved(ir.environment_plan) ? { dot: "done", title: t("stageState.approved") } : { dot: "warn", text: t("stageState.pendingShort"), title: t("stageState.pending") };
    case "deploy":
      if (runtime.deployState === "running") return { dot: "done", text: t("stageState.runningShort"), title: t("stageState.running") };
      return ir.deployments?.length ? { dot: "done", title: t("stageState.hasDeploys") } : { dot: "", title: t("stageState.notRunning") };
    case "report": {
      const lv = runtime.levels ?? ir.validation?.levels;
      if (!lv) return todo;
      const all = [lv.env_build, lv.behavior_repro, lv.full_chain];
      if (all.includes("FAIL")) return { dot: "err", title: t("stageState.fail") };
      return all.every((s) => s === "PASS") ? { dot: "done", title: t("stageState.allPass") } : { dot: "warn", title: t("stageState.partial") };
    }
    default: return null;
  }
}
