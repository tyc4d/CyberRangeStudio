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
import { LocaleProvider, useI18n, type MsgKey } from "./i18n";
import { stackTables } from "./lib/stackTables";

// The guided workflow stages. Each maps to a page.
export const STAGES: { path: string; label: MsgKey; key: string; element: ReactNode }[] = [
  { path: "/", label: "stage.home", key: "home", element: <HomePage /> },
  { path: "/import", label: "stage.import", key: "import", element: <ImportPage /> },
  { path: "/analysis", label: "stage.analysis", key: "analysis", element: <AnalysisPage /> },
  { path: "/missing", label: "stage.missing", key: "missing", element: <MissingPage /> },
  { path: "/flow", label: "stage.flow", key: "flow", element: <FlowPage /> },
  { path: "/deps", label: "stage.deps", key: "deps", element: <DepsPage /> },
  { path: "/topology", label: "stage.topology", key: "topology", element: <TopologyPage /> },
  { path: "/iac", label: "stage.iac", key: "iac", element: <IacPage /> },
  { path: "/deploy", label: "stage.deploy", key: "deploy", element: <DeployPage /> },
  { path: "/report", label: "stage.report", key: "report", element: <ReportPage /> },
];

function BudgetChip() {
  const { t } = useI18n();
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
      {t("shell.budget", { used: b.est_total_usd.toFixed(2), cap: b.hard_cap_usd })}
      <div className="bar">
        <i style={{ transform: `scaleX(${pct / 100})` }} />
      </div>
    </div>
  );
}

/** Visible language switch. zh-TW is the default; the choice is remembered in this browser. */
function LanguageSwitch() {
  const { locale, setLocale, t } = useI18n();
  const next = locale === "en" ? "zh-TW" : "en";
  return (
    <button className="small lang-switch" onClick={() => setLocale(next)} aria-label={t("shell.switchToLabel")} title={t("shell.language")} lang={next}>
      {t("shell.switchTo")}
    </button>
  );
}

function Topbar() {
  const { t } = useI18n();
  const { id, ir, runtime, loading } = useScenario();
  const plan = ir?.environment_plan;
  return (
    <header className="topbar">
      <Link className="studio-brand" to="/" aria-label={t("shell.home")}>
        <span className="brand-mark">CRS</span>
        <strong>CyberRange Studio</strong>
      </Link>
      <span className="header-separator" />
      <span className="document-title" title={ir?.name ?? id ?? ""}>{ir ? ir.name || ir.id : id ? (loading ? t("shell.loading") : id) : t("shell.noScenario")}</span>
      {ir && <span className="badge" title={t("shell.sourceFormat", { kind: ir.provenance?.input_kind ?? "—" })}>v{ir.ir_version ?? 1}</span>}
      {/* Status badges state only what the backend reports. "已核准" is topology approval, not a deployment or attack result. */}
      {plan && (isPlanApproved(plan)
        ? <span className="badge approved">{t("shell.planApproved")}</span>
        : <span className="badge pending">{t("shell.planPending")}</span>)}
      {runtime.deployState === "running" && <span className="badge validated">{t("shell.rangeRunning")}</span>}
      <TopbarSlot />
      <BudgetChip />
      <LanguageSwitch />
    </header>
  );
}

function StageStrip() {
  const { t } = useI18n();
  const { ir, runtime } = useScenario();
  return (
    <nav className="stages" aria-label={t("shell.workflow")}>
      {STAGES.map((s, i) => {
        const st = stageState(s.key, ir, runtime);
        return (
          <NavLink key={s.key} to={s.path} end={s.path === "/"} className={({ isActive }) => (isActive ? "active" : "")}>
            {i > 0 && <span className="num">{i}</span>}
            <span className="stage-label">{t(s.label)}</span>
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
  return <LocaleProvider><Shell /></LocaleProvider>;
}

function Shell() {
  // Subscribing here re-renders the whole tree when the language changes, without remounting pages (no lost edits).
  useI18n();
  const mainRef = useScrollTopOnNavigate();
  useEffect(() => (mainRef.current ? stackTables(mainRef.current) : undefined), [mainRef]);
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
