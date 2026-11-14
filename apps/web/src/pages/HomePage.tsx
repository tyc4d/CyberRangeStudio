import { useLayoutEffect, useRef } from "react";
import gsap from "gsap";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useLoad } from "../lib/hooks";
import { useScenario } from "../lib/scenario";
import { stageState } from "../lib/stages";
import { ApiNotice, Busy, Empty, fmtTime, PageHead } from "../components/ui";

const MODULES: { key: string; label: string }[] = [
  { key: "ingest", label: "情資分析／缺失補齊" },
  { key: "scenario", label: "情境與流程編輯" },
  { key: "planning", label: "依賴與拓樸" },
  { key: "iac", label: "IaC 生成" },
  { key: "deploy", label: "部署" },
  { key: "validate", label: "驗證" },
];

function BackendStatus() {
  const routers = useLoad(() => api.routers(), []);
  if (routers.loading && !routers.data) return null;
  if (routers.error) return <ApiNotice error={routers.error} what="後端狀態" onRetry={() => routers.reload()} />;
  const r = routers.data ?? {};
  return (
    <div className="card">
      <h2>後端模組</h2>
      <div className="row" style={{ gap: 18 }}>
        {MODULES.map((m) => {
          const s = r[m.key];
          const ok = s === "ok";
          return (
            <span key={m.key} title={s ?? "後端未回報此模組"} style={{ fontSize: 13 }}>
              <span className={`dot ${ok ? "done" : s ? "err" : ""}`} style={{ marginRight: 6 }} />
              {m.label}
              {!ok && <span className="muted">（{s ? "載入失敗" : "未回報"}）</span>}
            </span>
          );
        })}
      </div>
      <p className="muted" style={{ fontSize: 12, margin: "10px 0 0" }}>
        綠點只代表模組已載入；個別功能是否完成，以各頁面實際回應為準。
      </p>
    </div>
  );
}

// The nine stops a report passes on its way to a running range. Order is the real order of the workflow.
const STOPS: { key: string; to: string; label: string }[] = [
  { key: "import", to: "/import", label: "情資匯入" }, { key: "analysis", to: "/analysis", label: "分析結果" },
  { key: "missing", to: "/missing", label: "缺失補充" }, { key: "flow", to: "/flow", label: "攻擊流程" },
  { key: "deps", to: "/deps", label: "軟體依賴" }, { key: "topology", to: "/topology", label: "拓樸核准" },
  { key: "iac", to: "/iac", label: "IaC 預覽" }, { key: "deploy", to: "/deploy", label: "部署" },
  { key: "report", to: "/report", label: "驗證報告" },
];

function RangeLine() {
  const { ir, runtime } = useScenario();
  const root = useRef<HTMLElement>(null);
  const states = STOPS.map((s) => stageState(s.key, ir, runtime));
  // How far this scenario has really got: the last stop the backend data marks as done.
  const reached = states.reduce((last, st, i) => (st?.dot === "done" ? i : last), -1);
  const share = reached < 0 ? 0 : reached / (STOPS.length - 1);

  // The page's one orchestrated moment: the line runs out to where the scenario actually stands, and the stops
  // it passed light in order. It plays once per load and only reports state the backend already returned.
  useLayoutEffect(() => {
    const mm = gsap.matchMedia();
    mm.add("(prefers-reduced-motion: no-preference)", () => {
      const q = gsap.utils.selector(root);
      const tl = gsap.timeline({ defaults: { ease: "power3.out" } });
      tl.from(q(".rail-line"), { scaleX: 0, duration: 0.5 })
        .from(q(".rail-done"), { scaleX: 0, duration: 0.7 }, "-=0.2")
        .from(q(".stop .node"), { scale: 0, duration: 0.28, stagger: 0.06, transformOrigin: "50% 50%" }, 0.15)
        .from(q(".stop .txt"), { opacity: 0, y: 6, duration: 0.3, stagger: 0.06 }, 0.2);
    });
    return () => mm.revert();
  }, [ir?.id, reached]);

  return (
    <section className="rangeline" data-testid="rangeline" ref={root}>
      <h2>{ir ? ir.name || ir.id : "把一份情資報告，變成一座可以驗證的靶場"}</h2>
      <p>{ir
        ? "這個情境目前走到哪一站。拓樸那一站是人工閘門：沒有人核准，後面的部署不會放行。"
        : "報告進來後依序經過九站。拓樸那一站是人工閘門：沒有人核准，後面的部署不會放行。"}</p>
      <div className="track">
        <span className="rail-line" aria-hidden />
        <span className="rail-done" aria-hidden style={{ width: `${share * 100 * (8 / 9)}%` }} />
        {STOPS.map((s, i) => {
          const st = states[i];
          return (
            <Link key={s.key} to={s.to} className={`stop ${st?.dot ?? ""} ${s.key === "topology" ? "gate-stop" : ""}`} title={st?.title}>
              <span className="node" aria-hidden>{i + 1}</span>
              <span className="txt">
                {s.label}
                <span className="s">{ir ? st?.title ?? "隨時可看" : " "}</span>
              </span>
            </Link>
          );
        })}
      </div>
    </section>
  );
}

export function HomePage() {
  const nav = useNavigate();
  const { id: currentId, select } = useScenario();
  const list = useLoad(() => api.listScenarios(), []);
  const rows = Array.isArray(list.data) ? list.data : [];

  const open = (id: string) => { select(id); nav("/analysis"); };

  return (
    <div className="page">
      <PageHead title="專案首頁" desc="從一份威脅情資報告出發，依序完成分析、補充、流程編輯、環境規劃、部署與驗證。每個階段完成後仍可回頭修改。">
        <Link to="/import" state={{ fresh: true }}><button className="primary">＋ 新建情境</button></Link>
      </PageHead>

      <RangeLine />

      <div className="card flush">
        <div className="card-head">
          <h2>情境清單</h2>
          <div className="right">
            {list.loading && <span className="spinner" />}
            <button className="small" onClick={() => list.reload()} disabled={list.loading}>重新整理</button>
          </div>
        </div>
        {list.error ? (
          <div style={{ padding: 14 }}><ApiNotice error={list.error} what="情境清單" onRetry={() => list.reload()} /></div>
        ) : list.loading && !list.data ? (
          <div style={{ padding: 16 }}><Busy label="載入情境清單…" /></div>
        ) : rows.length === 0 ? (
          <Empty>還沒有任何情境。<Link to="/import">匯入第一份情資報告</Link>即可開始。</Empty>
        ) : (
          <table className="tbl">
            <thead><tr><th>名稱</th><th>ID</th><th>建立時間</th><th>最後更新</th><th /></tr></thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.id} className={`clickable ${s.id === currentId ? "sel" : ""}`} onClick={() => open(s.id)}>
                  <td>{s.name || <span className="muted">（未命名）</span>}{s.id === currentId && <span className="tag user" style={{ marginLeft: 8 }}>目前</span>}</td>
                  <td className="mono muted">{s.id}</td>
                  <td className="nowrap muted">{fmtTime(s.created_at)}</td>
                  <td className="nowrap muted">{fmtTime(s.updated_at)}</td>
                  <td style={{ textAlign: "right" }}><button className="small" onClick={(e) => { e.stopPropagation(); open(s.id); }}>開啟</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <BackendStatus />
    </div>
  );
}
