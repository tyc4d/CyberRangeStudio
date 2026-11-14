import type { ScenarioIR } from "@contracts";
import { openCardCount } from "../pages/MissingPage";
import { isPlanApproved } from "./plan";
import type { Runtime } from "./scenario";

export type StageState = { dot: "" | "done" | "warn" | "err"; text?: string; title: string };

/** Progress markers derived only from what the loaded IR actually contains. */
export function stageState(key: string, ir: ScenarioIR | null, runtime: Runtime = {}): StageState | null {
  if (!ir) return null;
  const todo: StageState = { dot: "", title: "尚無資料" };
  switch (key) {
    case "import": return { dot: "done", title: "已匯入" };
    case "analysis": return ir.actions.length ? { dot: "done", text: String(ir.actions.length), title: `${ir.actions.length} 個攻擊行為` } : todo;
    case "missing": {
      const items = ir.missing_items ?? [];
      const open = openCardCount(ir);
      if (!items.length) return todo;
      return open ? { dot: "warn", text: String(open), title: `${open} 項待補充` } : { dot: "done", title: "缺失皆已處理" };
    }
    case "flow": return (ir.ir_version ?? 1) > 1 ? { dot: "done", text: `v${ir.ir_version}`, title: `目前版本 v${ir.ir_version}` } : todo;
    case "deps": return ir.hosts?.length || ir.services?.length ? { dot: "done", title: "已有主機／服務" } : todo;
    case "topology":
      if (!ir.environment_plan) return todo;
      return isPlanApproved(ir.environment_plan) ? { dot: "done", title: "拓樸已核准" } : { dot: "warn", text: "待核准", title: "已有環境規劃，尚未人工核准" };
    case "deploy":
      if (runtime.deployState === "running") return { dot: "done", text: "執行中", title: "容器執行中" };
      return ir.deployments?.length ? { dot: "done", title: "有部署紀錄" } : { dot: "", title: "目前沒有容器在執行" };
    case "report": {
      const lv = runtime.levels ?? ir.validation?.levels;
      if (!lv) return todo;
      const all = [lv.env_build, lv.behavior_repro, lv.full_chain];
      if (all.includes("FAIL")) return { dot: "err", title: "有驗證層失敗" };
      return all.every((s) => s === "PASS") ? { dot: "done", title: "三層皆通過" } : { dot: "warn", title: "部分通過或未測" };
    }
    default: return null;
  }
}
