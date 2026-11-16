import { useLayoutEffect, useRef } from "react";
import gsap from "gsap";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useLoad } from "../lib/hooks";
import { useScenario } from "../lib/scenario";
import { stageState } from "../lib/stages";
import { ApiNotice, Busy, Empty, fmtTime, PageHead } from "../components/ui";
import { t, useT, type MsgKey } from "../i18n";

const MODULES: { key: string; label: MsgKey }[] = [
  { key: "ingest", label: "home.mod.ingest" },
  { key: "scenario", label: "home.mod.scenario" },
  { key: "planning", label: "home.mod.planning" },
  { key: "iac", label: "home.mod.iac" },
  { key: "deploy", label: "home.mod.deploy" },
  { key: "validate", label: "home.mod.validate" },
];

function BackendStatus() {
  const routers = useLoad(() => api.routers(), []);
  if (routers.loading && !routers.data) return null;
  if (routers.error) return <ApiNotice error={routers.error} what={t("home.backendWhat")} onRetry={() => routers.reload()} />;
  const r = routers.data ?? {};
  return (
    <div className="card">
      <h2>{t("home.backend")}</h2>
      <div className="row" style={{ gap: 18 }}>
        {MODULES.map((m) => {
          const s = r[m.key];
          const ok = s === "ok";
          return (
            <span key={m.key} title={s ?? t("home.modNoReport")} style={{ fontSize: 13 }}>
              <span className={`dot ${ok ? "done" : s ? "err" : ""}`} style={{ marginRight: 6 }} />
              {t(m.label)}
              {!ok && <span className="muted"> ({s ? t("home.modFailed") : t("home.modUnknown")})</span>}
            </span>
          );
        })}
      </div>
      <p className="muted" style={{ fontSize: 12, margin: "10px 0 0" }}>
        {t("home.modNote")}
      </p>
    </div>
  );
}

// The nine stops a report passes on its way to a running range. Order is the real order of the workflow.
const STOPS: { key: string; to: string; label: MsgKey }[] = [
  { key: "import", to: "/import", label: "stage.import" }, { key: "analysis", to: "/analysis", label: "stage.analysis" },
  { key: "missing", to: "/missing", label: "stage.missing" }, { key: "flow", to: "/flow", label: "stage.flow" },
  { key: "deps", to: "/deps", label: "stage.deps" }, { key: "topology", to: "/topology", label: "home.stop.topology" },
  { key: "iac", to: "/iac", label: "stage.iac" }, { key: "deploy", to: "/deploy", label: "stage.deploy" },
  { key: "report", to: "/report", label: "stage.report" },
];

function RangeLine() {
  const t = useT();
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
      <h2>{ir ? ir.name || ir.id : t("home.heroEmpty")}</h2>
      <p>{ir ? t("home.heroIr") : t("home.heroNone")}</p>
      <div className="track">
        <span className="rail-line" aria-hidden />
        <span className="rail-done" aria-hidden style={{ width: `${share * 100 * (8 / 9)}%` }} />
        {STOPS.map((s, i) => {
          const st = states[i];
          return (
            <Link key={s.key} to={s.to} className={`stop ${st?.dot ?? ""} ${s.key === "topology" ? "gate-stop" : ""}`} title={st?.title}>
              <span className="node" aria-hidden>{i + 1}</span>
              <span className="txt">
                {t(s.label)}
                <span className="s">{ir ? st?.title ?? t("home.stopAny") : " "}</span>
              </span>
            </Link>
          );
        })}
      </div>
    </section>
  );
}

export function HomePage() {
  const t = useT();
  const nav = useNavigate();
  const { id: currentId, select } = useScenario();
  const list = useLoad(() => api.listScenarios(), []);
  const rows = Array.isArray(list.data) ? list.data : [];

  const open = (id: string) => { select(id); nav("/analysis"); };

  return (
    <div className="page">
      <PageHead title={t("home.title")} desc={t("home.desc")}>
        <Link to="/import" state={{ fresh: true }}><button className="primary">＋ {t("home.new")}</button></Link>
      </PageHead>

      <RangeLine />

      <div className="card flush">
        <div className="card-head">
          <h2>{t("home.list")}</h2>
          <div className="right">
            {list.loading && <span className="spinner" />}
            <button className="small" onClick={() => list.reload()} disabled={list.loading}>{t("home.refresh")}</button>
          </div>
        </div>
        {list.error ? (
          <div style={{ padding: 14 }}><ApiNotice error={list.error} what={t("home.listWhat")} onRetry={() => list.reload()} /></div>
        ) : list.loading && !list.data ? (
          <div style={{ padding: 16 }}><Busy label={t("home.listLoading")} /></div>
        ) : rows.length === 0 ? (
          <Empty>{t("home.empty1")} <Link to="/import">{t("home.empty2")}</Link></Empty>
        ) : (
          <table className="tbl tbl-stack">
            <thead><tr><th>{t("home.colName")}</th><th className="hide-sm">{t("home.colId")}</th><th className="hide-sm">{t("home.colCreated")}</th><th>{t("home.colUpdated")}</th><th /></tr></thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.id} className={`clickable ${s.id === currentId ? "sel" : ""}`} onClick={() => open(s.id)}>
                  <td>{s.name || <span className="muted">{t("home.unnamed")}</span>}{s.id === currentId && <span className="tag user" style={{ marginLeft: 8 }}>{t("home.current")}</span>}</td>
                  <td className="mono muted hide-sm">{s.id}</td>
                  <td className="nowrap muted hide-sm">{fmtTime(s.created_at)}</td>
                  <td className="nowrap muted">{fmtTime(s.updated_at)}</td>
                  <td style={{ textAlign: "right" }}><button className="small" onClick={(e) => { e.stopPropagation(); open(s.id); }}>{t("home.open")}</button></td>
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
