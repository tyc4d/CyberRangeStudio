import { NavLink, Route, Routes } from "react-router-dom";
import { useEffect, useState, type ReactNode } from "react";
import type { ScenarioIR } from "@contracts";
import { api, type Budget } from "./lib/api";
import { ScenarioProvider, useScenario } from "./lib/scenario";
import { HomePage } from "./pages/HomePage";
import { ImportPage } from "./pages/ImportPage";
import { AnalysisPage } from "./pages/AnalysisPage";
import { MissingPage } from "./pages/MissingPage";
import { FlowPage } from "./pages/FlowPage";
import { DepsPage } from "./pages/DepsPage";
import { TopologyPage } from "./pages/TopologyPage";
import { IacPage } from "./pages/IacPage";
import { DeployPage } from "./pages/DeployPage";
import { ReportPage } from "./pages/ReportPage";

// The guided workflow stages. Each maps to a page.
export const STAGES: { path: string; label: string; key: string; element: ReactNode }[] = [
  { path: "/", label: "專案首頁", key: "home", element: <HomePage /> },
  { path: "/import", label: "情資匯入", key: "import", element: <ImportPage /> },
  { path: "/analysis", label: "分析結果", key: "analysis", element: <AnalysisPage /> },
  { path: "/missing", label: "缺失補充", key: "missing", element: <MissingPage /> },
  { path: "/flow", label: "攻擊流程", key: "flow", element: <FlowPage /> },
  { path: "/deps", label: "軟體依賴", key: "deps", element: <DepsPage /> },
  { path: "/topology", label: "拓樸", key: "topology", element: <TopologyPage /> },
  { path: "/iac", label: "IaC 預覽", key: "iac", element: <IacPage /> },
  { path: "/deploy", label: "部署管理", key: "deploy", element: <DeployPage /> },
  { path: "/report", label: "驗證報告", key: "report", element: <ReportPage /> },
];

type StageState = { dot: "" | "done" | "warn" | "err"; text?: string; title: string };

/** Progress markers derived only from what the loaded IR actually contains. */
function stageState(key: string, ir: ScenarioIR | null): StageState | null {
  if (!ir) return null;
  const todo: StageState = { dot: "", title: "尚無資料" };
  switch (key) {
    case "import": return { dot: "done", title: "已匯入" };
    case "analysis": return ir.actions.length ? { dot: "done", text: String(ir.actions.length), title: `${ir.actions.length} 個攻擊行為` } : todo;
    case "missing": {
      const items = ir.missing_items ?? [];
      const open = items.filter((m) => m.status === "open").length;
      if (!items.length) return todo;
      return open ? { dot: "warn", text: String(open), title: `${open} 項待補充` } : { dot: "done", title: "缺失皆已處理" };
    }
    case "flow": return (ir.ir_version ?? 1) > 1 ? { dot: "done", text: `v${ir.ir_version}`, title: `目前版本 v${ir.ir_version}` } : todo;
    case "deps": return ir.hosts?.length || ir.services?.length ? { dot: "done", title: "已有主機／服務" } : todo;
    case "topology": return ir.environment_plan ? { dot: "done", title: "已有環境規劃" } : todo;
    case "deploy": return ir.deployments?.length ? { dot: "done", title: "有部署紀錄" } : todo;
    case "report": {
      const lv = ir.validation?.levels;
      if (!lv) return todo;
      const all = [lv.env_build, lv.behavior_repro, lv.full_chain];
      if (all.includes("FAIL")) return { dot: "err", title: "有驗證層失敗" };
      return all.every((s) => s === "PASS") ? { dot: "done", title: "三層皆通過" } : { dot: "warn", title: "部分通過或未測" };
    }
    default: return null;
  }
}

function BudgetChip() {
  const [b, setB] = useState<Budget | null>(null);
  useEffect(() => {
    const load = () => api.budget().then(setB).catch(() => {});
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, []);
  if (!b || !b.hard_cap_usd) return null;
  const pct = Math.min(100, (b.est_total_usd / b.hard_cap_usd) * 100);
  const color = pct > 90 ? "var(--err)" : pct > 80 ? "var(--warn)" : "var(--text-dim)";
  return (
    <div style={{ padding: "8px 14px", borderTop: "1px solid var(--border)", fontSize: 12, color }}>
      API 估計花費 ${b.est_total_usd.toFixed(2)} / ${b.hard_cap_usd}
      <div style={{ height: 4, background: "var(--bg)", borderRadius: 2, marginTop: 4 }}>
        <div style={{ width: `${pct}%`, height: "100%", background: color, borderRadius: 2 }} />
      </div>
    </div>
  );
}

function Sidebar() {
  const { id, ir, loading } = useScenario();
  return (
    <aside className="side">
      <div className="brand">CyberRange <span className="muted" style={{ fontWeight: 400 }}>Studio</span></div>
      <div className="current">
        <div className="muted">目前情境</div>
        <div className="name" title={ir?.name ?? id ?? ""}>{ir ? ir.name || ir.id : id ? (loading ? "載入中…" : id) : "未選擇"}</div>
        {ir && <div className="muted mono">v{ir.ir_version ?? 1} · {ir.provenance?.input_kind ?? "—"}</div>}
      </div>
      <nav>
        {STAGES.map((s, i) => {
          const st = stageState(s.key, ir);
          return (
            <NavLink key={s.key} to={s.path} end={s.path === "/"} className={({ isActive }) => (isActive ? "active" : "")}>
              <span className="num">{i === 0 ? "" : i}</span>
              {s.label}
              {st && (
                <span className="state muted" title={st.title}>
                  {st.text && <span style={{ marginRight: 5 }}>{st.text}</span>}
                  <span className={`dot ${st.dot}`} />
                </span>
              )}
            </NavLink>
          );
        })}
      </nav>
      <BudgetChip />
    </aside>
  );
}

export function App() {
  return (
    <ScenarioProvider>
      <div className="shell">
        <Sidebar />
        <main className="main">
          <Routes>
            {STAGES.map((s) => <Route key={s.key} path={s.path} element={s.element} />)}
            <Route path="*" element={<HomePage />} />
          </Routes>
        </main>
      </div>
    </ScenarioProvider>
  );
}
