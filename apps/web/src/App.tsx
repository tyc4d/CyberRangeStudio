import { Link, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { api, type Budget } from "./lib/api";
import { isPlanApproved } from "./lib/plan";
import { stageState } from "./lib/stages";
import { TopbarProvider, TopbarSlot } from "./lib/topbar";
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
  const color = pct > 90 ? "var(--err)" : pct > 80 ? "var(--warn)" : "var(--text-dim)";
  return (
    <div className="budget" style={{ color }}>
      API 估計 ${b.est_total_usd.toFixed(2)} / ${b.hard_cap_usd}
      <div className="bar">
        <i style={{ transform: `scaleX(${pct / 100})` }} />
      </div>
    </div>
  );
}

function Topbar() {
  const { id, ir, runtime, loading } = useScenario();
  const plan = ir?.environment_plan;
  return (
    <header className="topbar">
      <Link className="studio-brand" to="/" aria-label="CyberRange Studio 首頁">
        <span className="brand-mark">CRS</span>
        <strong>CyberRange Studio</strong>
      </Link>
      <span className="header-separator" />
      <span className="document-title" title={ir?.name ?? id ?? ""}>{ir ? ir.name || ir.id : id ? (loading ? "載入中…" : id) : "尚未選擇情境"}</span>
      {ir && <span className="badge" title={`來源格式：${ir.provenance?.input_kind ?? "—"}`}>v{ir.ir_version ?? 1}</span>}
      {/* Status badges state only what the backend reports. "已核准" is topology approval, not a deployment or attack result. */}
      {plan && (isPlanApproved(plan)
        ? <span className="badge approved">拓樸已核准</span>
        : <span className="badge pending">拓樸待核准</span>)}
      {runtime.deployState === "running" && <span className="badge validated">容器執行中</span>}
      <TopbarSlot />
      <BudgetChip />
    </header>
  );
}

function StageStrip() {
  const { ir, runtime } = useScenario();
  return (
    <nav className="stages" aria-label="工作流程">
      {STAGES.map((s, i) => {
        const st = stageState(s.key, ir, runtime);
        return (
          <NavLink key={s.key} to={s.path} end={s.path === "/"} className={({ isActive }) => (isActive ? "active" : "")}>
            {i > 0 && <span className="num">{i}</span>}
            {s.label}
            {st && (st.dot || st.text) && (
              <span className="state" title={st.title}>
                {st.text}
                <span className={`dot ${st.dot}`} />
              </span>
            )}
          </NavLink>
        );
      })}
    </nav>
  );
}

/** Entering another stage starts at the top of that page, not at the previous page's scroll offset. */
function useScrollTopOnNavigate() {
  const ref = useRef<HTMLElement>(null);
  const { pathname } = useLocation();
  useLayoutEffect(() => { ref.current?.scrollTo({ top: 0 }); }, [pathname]);
  return ref;
}

export function App() {
  const mainRef = useScrollTopOnNavigate();
  return (
    <ScenarioProvider>
      <TopbarProvider>
        <div className="app-shell">
          <Topbar />
          <StageStrip />
          <main className="main" ref={mainRef}>
            <Routes>
              {STAGES.map((s) => <Route key={s.key} path={s.path} element={s.element} />)}
              <Route path="*" element={<HomePage />} />
            </Routes>
          </main>
        </div>
      </TopbarProvider>
    </ScenarioProvider>
  );
}
