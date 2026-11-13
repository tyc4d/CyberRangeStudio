import { NavLink, Route, Routes } from "react-router-dom";
import { useEffect, useState } from "react";
import { api, type Budget } from "./lib/api";

// The guided workflow stages. Each maps to a page. Frontend worker fills page bodies.
export const STAGES = [
  { path: "/", label: "專案首頁", key: "home" },
  { path: "/import", label: "情資匯入", key: "import" },
  { path: "/analysis", label: "分析結果", key: "analysis" },
  { path: "/missing", label: "缺失補充", key: "missing" },
  { path: "/flow", label: "攻擊流程", key: "flow" },
  { path: "/deps", label: "軟體依賴", key: "deps" },
  { path: "/topology", label: "拓樸", key: "topology" },
  { path: "/iac", label: "IaC 預覽", key: "iac" },
  { path: "/deploy", label: "部署管理", key: "deploy" },
  { path: "/report", label: "驗證報告", key: "report" },
];

function BudgetChip() {
  const [b, setB] = useState<Budget | null>(null);
  useEffect(() => {
    const load = () => api.budget().then(setB).catch(() => {});
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, []);
  if (!b) return null;
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

function Placeholder({ label }: { label: string }) {
  return (
    <div className="card">
      <h2 style={{ marginTop: 0 }}>{label}</h2>
      <p className="muted">此頁由前端 Worker 實作，接後端真實資料。</p>
    </div>
  );
}

export function App() {
  return (
    <div style={{ display: "flex", height: "100%" }}>
      <aside style={{ width: 210, background: "var(--bg-elev)", borderRight: "1px solid var(--border)", display: "flex", flexDirection: "column" }}>
        <div style={{ padding: "18px 16px", fontWeight: 600, fontSize: 15, letterSpacing: .3 }}>
          CyberRange <span className="muted" style={{ fontWeight: 400 }}>Studio</span>
        </div>
        <nav style={{ flex: 1, overflow: "auto" }}>
          {STAGES.map((s, i) => (
            <NavLink
              key={s.key}
              to={s.path}
              end={s.path === "/"}
              style={({ isActive }) => ({
                display: "flex", gap: 10, padding: "9px 16px", color: isActive ? "var(--text)" : "var(--text-dim)",
                background: isActive ? "var(--bg-elev2)" : "transparent",
                borderLeft: isActive ? "2px solid var(--accent)" : "2px solid transparent", fontSize: 13,
              })}
            >
              <span className="muted" style={{ width: 16 }}>{i === 0 ? "" : i}</span>
              {s.label}
            </NavLink>
          ))}
        </nav>
        <BudgetChip />
      </aside>
      <main style={{ flex: 1, overflow: "auto", padding: 24 }}>
        <Routes>
          {STAGES.map((s) => (
            <Route key={s.key} path={s.path} element={<Placeholder label={s.label} />} />
          ))}
        </Routes>
      </main>
    </div>
  );
}
