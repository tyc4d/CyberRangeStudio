import { NavLink, Route, Routes } from "react-router-dom";
import { useEffect, useState, type ReactNode } from "react";
import { api, type Budget } from "./lib/api";
import { stageState } from "./lib/stages";
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
  const color = pct > 90 ? "#ff7a66" : pct > 80 ? "#f0b03f" : "var(--rail-dim)";
  return (
    <div style={{ padding: "8px 14px", borderTop: "1px solid #2f4450", fontSize: 12, color }}>
      API 估計花費 ${b.est_total_usd.toFixed(2)} / ${b.hard_cap_usd}
      <div style={{ height: 4, background: "#2f4450", borderRadius: 2, marginTop: 4 }}>
        <div style={{ width: `${pct}%`, height: "100%", background: color, borderRadius: 2 }} />
      </div>
    </div>
  );
}

function Sidebar() {
  const { id, ir, runtime, loading } = useScenario();
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
          const st = stageState(s.key, ir, runtime);
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
