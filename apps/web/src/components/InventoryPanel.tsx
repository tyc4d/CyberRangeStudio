// Inventory status of each extracted component: tier, the component the backend chose (or its stand-in), the CVEs
// that component really reproduces, and a per-row override (accept the stand-in, pick another component, or supply a
// version). The backend decides every verdict (app.planner.inventory.resolve); this panel only renders and forwards.
//
// Self-contained on purpose: it carries its own zh-TW / en strings (parity checked by tsc) and follows the same
// `cr.locale` setting as the app-wide i18n, so it does not depend on which frontend line it is merged into.
import { useMemo, useState } from "react";
import type { ScenarioIR } from "@contracts";
import {
  api, extractIr,
  type InventoryEntry, type InventoryItem, type InventoryOverrideRequest, type InventoryResolution, type InventoryTier, type InventoryVersionBasis,
} from "../lib/api";
import { useAction, useLoad } from "../lib/hooks";
import { useScenario } from "../lib/scenario";
import { ApiNotice, Empty, Notice } from "./ui";

/* ---------- strings ---------- */
const zh = {
  title: "元件盤點",
  subtitle: "每個擷取到的元件能不能部署、實際用哪個元件、能重現哪些 CVE。結果由後端決定；你可以逐項覆寫。",
  count: "{n} 項",
  colComponent: "原文元件",
  colTier: "狀態",
  colChosen: "實際部署",
  colCve: "重現的 CVE",
  colBasis: "版本依據",
  colAction: "調整",
  stated: "原文版本 {v}",
  noVersion: "原文未寫版本",
  cited: "原文提到 {c}",
  tierHave: "已可部署",
  tierObtainable: "可取得",
  tierUnavailable: "無法提供",
  tierHaveHint: "平台現在就能部署這個元件。",
  tierObtainableHint: "平台還沒有這個元件，但可以在預算內取得（下載映像或評估版）。",
  tierUnavailableHint: "沒有可用的映像，也無法模擬。這個元件不會被重現。",
  substitute: "替代品",
  substituteOf: "代替 {name}",
  substituteHint: "部署的不是原文的產品，是能重現相同漏洞或技術的替代品。不能說原產品被重現。",
  notDeployed: "不部署",
  noCve: "—",
  basisStated: "原文版本",
  basisAssumed: "假設版本",
  basisSubstituted: "替代版本",
  basisUserSupplied: "你提供的版本",
  basisStatedHint: "部署的版本與原文寫的相符。",
  basisAssumedHint: "原文沒有寫版本，使用平台現有的版本。這是假設，不是原文事實。",
  basisSubstitutedHint: "部署的版本或產品與原文不同。行為可能與原事件不同。",
  basisUserSuppliedHint: "版本由你提供，不是原文寫的。",
  overridden: "已覆寫",
  overriddenAccept: "你已確認這個替代品",
  overriddenReplace: "你改用的元件",
  overriddenVersion: "你提供的版本",
  autoWas: "自動建議原本是：{v}",
  needsQuestion: "需要選版本",
  edit: "調整",
  editing: "調整：{name}",
  close: "收起",
  why: "判斷理由（後端原文）",
  optAccept: "接受替代品",
  optAcceptHint: "確認用這個替代品教學。它仍會標成替代品。",
  optReplace: "改用其他元件",
  optVersion: "指定版本",
  optClear: "恢復自動判斷",
  pickComponent: "選擇元件",
  pickPlaceholder: "— 選擇 —",
  versionLabel: "版本",
  versionPlaceholder: "例如 2019",
  suggestions: "可選：",
  apply: "套用",
  applying: "套用中…",
  applied: "已更新。依賴分析與缺失項目會依新的選擇重新判斷；請重新執行依賴分析確認。",
  emptyItems: "沒有可盤點的元件。先執行依賴分析。",
  loading: "載入中…",
  what: "元件盤點",
  whatOverride: "覆寫元件選擇",
  reloadHint: "重新整理",
  sumHave: "已可部署 {n}",
  sumObtainable: "可取得 {n}",
  sumUnavailable: "無法提供 {n}",
  sumSubstitute: "替代品 {n}",
  sumQuestion: "待選版本 {n}",
  footer: "標為替代品的元件只重現上表列出的 CVE，不代表原產品被重現。無法提供的元件不會問版本，因為不論版本都無法部署。",
} as const;

type Key = keyof typeof zh;
const en: Record<Key, string> = {
  title: "Component inventory",
  subtitle: "For each extracted component: can the platform deploy it, which component runs, and which CVEs that component reproduces. The backend decides. You can override each row.",
  count: "{n} items",
  colComponent: "Component in source",
  colTier: "Status",
  colChosen: "Deployed as",
  colCve: "Reproduced CVEs",
  colBasis: "Version basis",
  colAction: "Change",
  stated: "Source version {v}",
  noVersion: "No version in source",
  cited: "Source cites {c}",
  tierHave: "Deployable",
  tierObtainable: "Obtainable",
  tierUnavailable: "Unavailable",
  tierHaveHint: "The platform can deploy this component now.",
  tierObtainableHint: "The platform does not have this component yet. It can get it within budget (image pull or evaluation release).",
  tierUnavailableHint: "No image exists and it cannot be simulated. This component is not reproduced.",
  substitute: "Substitute",
  substituteOf: "Stands in for {name}",
  substituteHint: "This is not the product in the source. It reproduces the same vulnerability or technique. Do not say that the original product was reproduced.",
  notDeployed: "Not deployed",
  noCve: "—",
  basisStated: "Source version",
  basisAssumed: "Assumed version",
  basisSubstituted: "Substituted",
  basisUserSupplied: "Your version",
  basisStatedHint: "The deployed version matches the source.",
  basisAssumedHint: "The source gives no version. The platform uses the version it has. This is an assumption, not a fact from the source.",
  basisSubstitutedHint: "The deployed version or product is different from the source. Behavior can be different from the original incident.",
  basisUserSuppliedHint: "You gave this version. The source does not state it.",
  overridden: "Overridden",
  overriddenAccept: "You confirmed this substitute",
  overriddenReplace: "Component you chose",
  overriddenVersion: "Version you gave",
  autoWas: "Automatic proposal was: {v}",
  needsQuestion: "Choose a version",
  edit: "Change",
  editing: "Change: {name}",
  close: "Close",
  why: "Reason (backend text)",
  optAccept: "Accept substitute",
  optAcceptHint: "Confirm this substitute for teaching. It stays marked as a substitute.",
  optReplace: "Use another component",
  optVersion: "Set version",
  optClear: "Back to automatic",
  pickComponent: "Component",
  pickPlaceholder: "— Select —",
  versionLabel: "Version",
  versionPlaceholder: "For example 2019",
  suggestions: "Options:",
  apply: "Apply",
  applying: "Applying…",
  applied: "Updated. Dependency analysis and gaps use the new choice. Run the dependency analysis again to confirm.",
  emptyItems: "No components to show. Run the dependency analysis first.",
  loading: "Loading…",
  what: "Component inventory",
  whatOverride: "Component override",
  reloadHint: "Reload",
  sumHave: "Deployable {n}",
  sumObtainable: "Obtainable {n}",
  sumUnavailable: "Unavailable {n}",
  sumSubstitute: "Substitutes {n}",
  sumQuestion: "Version needed {n}",
  footer: "A substitute reproduces only the CVEs listed above. It does not mean that the original product was reproduced. Unavailable components get no version question, because no version of them can be deployed.",
};

const TABLES = { "zh-TW": zh as Record<Key, string>, en };
/** Same storage key as the app-wide i18n (`cr.locale`); zh-TW when unset or unreadable. */
function locale(): keyof typeof TABLES {
  try { return localStorage.getItem("cr.locale") === "en" ? "en" : "zh-TW"; } catch { return "zh-TW"; }
}
function useStrings() {
  const table = TABLES[locale()];
  return (k: Key, vars?: Record<string, string | number>) =>
    vars ? table[k].replace(/\{(\w+)\}/g, (m, v) => (vars[v] === undefined ? m : String(vars[v]))) : table[k];
}
type S = ReturnType<typeof useStrings>;

/* ---------- small renderers ---------- */
const TIER: Record<InventoryTier, { label: Key; hint: Key; cls: string }> = {
  have: { label: "tierHave", hint: "tierHaveHint", cls: "user" },
  obtainable: { label: "tierObtainable", hint: "tierObtainableHint", cls: "major" },
  unavailable: { label: "tierUnavailable", hint: "tierUnavailableHint", cls: "blocker" },
};
const BASIS: Record<InventoryVersionBasis, { label: Key; hint: Key; cls: string }> = {
  stated: { label: "basisStated", hint: "basisStatedHint", cls: "" },
  assumed: { label: "basisAssumed", hint: "basisAssumedHint", cls: "sub" },
  substituted: { label: "basisSubstituted", hint: "basisSubstitutedHint", cls: "sub" },
  user_supplied: { label: "basisUserSupplied", hint: "basisUserSuppliedHint", cls: "user" },
};

function TierTag({ tier, s }: { tier: InventoryTier; s: S }) {
  const t = TIER[tier];
  if (!t) return <span className="tag">{tier}</span>;
  return <span className={`tag ${t.cls}`} title={s(t.hint)} data-testid={`inv-tier-${tier}`}>{s(t.label)}</span>;
}
function BasisTag({ basis, s }: { basis: InventoryVersionBasis; s: S }) {
  const b = BASIS[basis];
  if (!b) return <span className="tag">{basis}</span>;
  return <span className={`tag ${b.cls}`} title={s(b.hint)} data-testid={`inv-basis-${basis}`}>{s(b.label)}</span>;
}
const chosenText = (r: InventoryResolution | null | undefined, s: S) => (r?.component_id ?? s("notDeployed"));

/* ---------- override editor ---------- */
/** Same display label as the backend's inventory `_label` (name without a trailing "(...)", plus the version if absent). */
function entryLabel(e: InventoryEntry): string {
  const name = String(e.name ?? e.id).replace(/\s*\([^)]*\)\s*$/, "").trim();
  return e.version && !name.includes(String(e.version)) ? `${name} ${e.version}` : name;
}
/** A question suggestion is a display label; the version resolve() accepts is the matching entry's pinned version.
 *  Falls back to the label itself when no entry matches (the backend then decides). */
function suggestionVersion(label: string, entries: InventoryEntry[]): string {
  const e = entries.find((x) => entryLabel(x) === label);
  return e?.version ? String(e.version) : label;
}

type Mode = "accept" | "replace" | "version";
// The global input style is full-width; a radio stays its natural size.
const RADIO = { width: "auto", minHeight: 0, margin: 0, accentColor: "var(--accent)" } as const;

function OverrideEditor({ item, entries, busy, onApply, s }: {
  item: InventoryItem; entries: InventoryEntry[]; busy: boolean; onApply: (b: InventoryOverrideRequest) => void; s: S;
}) {
  const r = item.resolution;
  const canAccept = r.is_substitute && item.override?.action !== "accept";
  const [mode, setMode] = useState<Mode>(r.needs_question ? "version" : canAccept ? "accept" : "replace");
  const [component, setComponent] = useState("");
  const [version, setVersion] = useState(item.override?.version ?? "");
  // Only components the platform can actually stand up are offered; "unavailable" ones would deploy nothing.
  const options = useMemo(() => entries.filter((e) => e.tier !== "unavailable"), [entries]);
  const name = `inv-mode-${item.ref_id}`;
  const ready = mode === "accept" || (mode === "replace" && component !== "") || (mode === "version" && version.trim() !== "");
  const submit = () => {
    if (!ready || busy) return;
    if (mode === "accept") onApply({ ref_id: item.ref_id, action: "accept" });
    else if (mode === "replace") onApply({ ref_id: item.ref_id, action: "replace", component_id: component });
    else onApply({ ref_id: item.ref_id, action: "version", version: version.trim() });
  };

  return (
    <div className="inv-editor" data-testid={`inv-editor-${item.ref_id}`} style={{ display: "grid", gap: 8, padding: "10px 14px", background: "var(--bg)", borderTop: "1px solid var(--border)" }}>
      <div role="radiogroup" className="row" style={{ gap: 14 }}>
        {canAccept && (
          <label className="row" style={{ gap: 6 }} title={s("optAcceptHint")}>
            <input type="radio" style={RADIO} name={name} checked={mode === "accept"} onChange={() => setMode("accept")} /> {s("optAccept")}
          </label>
        )}
        <label className="row" style={{ gap: 6 }}>
          <input type="radio" style={RADIO} name={name} checked={mode === "replace"} onChange={() => setMode("replace")} /> {s("optReplace")}
        </label>
        <label className="row" style={{ gap: 6 }}>
          <input type="radio" style={RADIO} name={name} checked={mode === "version"} onChange={() => setMode("version")} /> {s("optVersion")}
        </label>
      </div>

      {mode === "accept" && <div className="muted" style={{ fontSize: 12 }}>{s("optAcceptHint")}</div>}
      {mode === "replace" && (
        <label style={{ display: "grid", gap: 4, maxWidth: 420 }}>
          <span className="muted" style={{ fontSize: 12 }}>{s("pickComponent")}</span>
          <select value={component} onChange={(e) => setComponent(e.target.value)} data-testid={`inv-pick-${item.ref_id}`}>
            <option value="">{s("pickPlaceholder")}</option>
            {options.map((e) => (
              <option key={e.id} value={e.id}>
                {e.id}{e.version ? ` · ${e.version}` : ""}{e.reproduces_cve.length ? ` · ${e.reproduces_cve.join(", ")}` : ""} · {s(TIER[e.tier]?.label ?? "tierHave")}
              </option>
            ))}
          </select>
        </label>
      )}
      {mode === "version" && (
        <div style={{ display: "grid", gap: 4, maxWidth: 420 }}>
          <label style={{ display: "grid", gap: 4 }}>
            <span className="muted" style={{ fontSize: 12 }}>{s("versionLabel")}</span>
            <input value={version} placeholder={s("versionPlaceholder")} onChange={(e) => setVersion(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") submit(); }} data-testid={`inv-version-${item.ref_id}`} />
          </label>
          {r.question?.suggestions?.length ? (
            <div style={{ fontSize: 12 }}>
              <span className="muted">{s("suggestions")} </span>
              {r.question.suggestions.map((label) => {
                const v = suggestionVersion(label, entries);
                return <button key={label} type="button" className={`chip ${version === v ? "on" : ""}`} onClick={() => setVersion(v)}>{label}</button>;
              })}
            </div>
          ) : null}
        </div>
      )}

      <div className="row" style={{ gap: 8 }}>
        <button className="primary small" disabled={!ready || busy} onClick={submit} data-testid={`inv-apply-${item.ref_id}`}>{busy ? s("applying") : s("apply")}</button>
        {item.override && (
          <button className="small" disabled={busy} onClick={() => onApply({ ref_id: item.ref_id, action: "clear" })} data-testid={`inv-clear-${item.ref_id}`}>{s("optClear")}</button>
        )}
      </div>
    </div>
  );
}

/* ---------- one row (+ its editor) ---------- */
function Row({ item, open, onToggle, s }: { item: InventoryItem; open: boolean; onToggle: () => void; s: S }) {
  const r = item.resolution;
  const ov = item.override;
  const ovLabel: Key | null = ov ? (ov.action === "accept" ? "overriddenAccept" : ov.action === "replace" ? "overriddenReplace" : "overriddenVersion") : null;
  return (
    <tr data-testid={`inv-row-${item.ref_id}`}>
      <td>
        <div style={{ fontWeight: 600 }}>{item.name}</div>
        <div className="muted" style={{ fontSize: 12 }}>{item.version ? s("stated", { v: item.version }) : s("noVersion")}</div>
        {item.cves?.length ? <div className="muted mono" style={{ fontSize: 12 }}>{s("cited", { c: item.cves.join(", ") })}</div> : null}
        <div className="mono muted" style={{ fontSize: 11 }}>{item.ref_kind}:{item.ref_id}</div>
      </td>
      <td>
        <TierTag tier={r.tier} s={s} />
        {r.needs_question && <div style={{ marginTop: 4 }}><span className="tag major" data-testid="inv-needs-question">{s("needsQuestion")}</span></div>}
      </td>
      <td>
        <span className="mono">{chosenText(r, s)}</span>
        {r.is_substitute && (
          <div style={{ marginTop: 4 }}>
            <span className="tag sub" title={s("substituteHint")} data-testid="inv-substitute">{s("substitute")}</span>
            {r.substitute_of && <span className="muted" style={{ fontSize: 12 }}> {s("substituteOf", { name: r.substitute_of })}</span>}
          </div>
        )}
        {ov && ovLabel && (
          <div style={{ marginTop: 4, fontSize: 12 }}>
            <span className="tag user" data-testid={`inv-override-${ov.action}`}>{s("overridden")}</span>{" "}
            <span className="muted">{s(ovLabel)}{ov.action === "version" && ov.version ? ` ${ov.version}` : ""}</span>
            {item.auto_resolution && <div className="muted">{s("autoWas", { v: chosenText(item.auto_resolution, s) })}</div>}
          </div>
        )}
        {r.reason && (
          <details style={{ marginTop: 4, fontSize: 12 }}>
            <summary className="muted">{s("why")}</summary>
            <div className="muted" lang="en" style={{ overflowWrap: "anywhere" }}>{r.reason}</div>
            {r.question?.text && <div style={{ marginTop: 2 }}>{r.question.text}</div>}
          </details>
        )}
      </td>
      <td>{r.reproduces_cve.length ? r.reproduces_cve.map((c) => <div key={c} className="mono">{c}</div>) : <span className="muted">{s("noCve")}</span>}</td>
      <td><BasisTag basis={r.version_basis} s={s} /></td>
      <td style={{ textAlign: "right" }}>
        <button className="small" aria-expanded={open} onClick={onToggle} data-testid={`inv-edit-${item.ref_id}`}>{open ? s("close") : s("edit")}</button>
      </td>
    </tr>
  );
}

/* ---------- panel ---------- */
export function InventoryPanel({ ir }: { ir: ScenarioIR }) {
  const s = useStrings();
  const { absorb } = useScenario();
  // Refetch whenever the scenario changes (a new dependency analysis or an override rewrites the IR).
  const items = useLoad(() => api.scenarioInventory(ir.id), [ir.id, ir]);
  const entries = useLoad(() => api.inventory(), []);
  const [openId, setOpenId] = useState<string | null>(null);
  const [appliedOk, setAppliedOk] = useState(false);
  const override = useAction(async (body: InventoryOverrideRequest) => {
    setAppliedOk(false);
    const resp = await api.overrideInventory(ir.id, body);
    if (Array.isArray(resp?.items)) items.setData({ items: resp.items });
    if (resp?.scenario && extractIr(resp.scenario)) await absorb(resp.scenario);
    setOpenId(null);
    setAppliedOk(true);
  });

  const list = items.data?.items ?? [];
  const editing = list.find((i) => i.ref_id === openId) ?? null;
  const n = (pred: (i: InventoryItem) => boolean) => list.filter(pred).length;
  const summary = list.length ? [
    s("sumHave", { n: n((i) => i.resolution.tier === "have") }),
    s("sumObtainable", { n: n((i) => i.resolution.tier === "obtainable") }),
    s("sumUnavailable", { n: n((i) => i.resolution.tier === "unavailable") }),
    s("sumSubstitute", { n: n((i) => i.resolution.is_substitute) }),
    s("sumQuestion", { n: n((i) => i.resolution.needs_question) }),
  ].join(" · ") : "";

  return (
    <div className="card flush" data-testid="inventory-panel">
      <div className="card-head">
        <h2>{s("title")}</h2>
        {list.length > 0 && <span className="muted" style={{ fontSize: 12 }} data-testid="inv-summary">{summary}</span>}
      </div>
      <div className="muted" style={{ fontSize: 12, padding: "0 14px 10px" }}>{s("subtitle")}</div>

      {items.error ? (
        <div style={{ padding: "0 14px 14px" }}><ApiNotice error={items.error} what={s("what")} onRetry={() => items.reload()} /></div>
      ) : items.loading && !items.data ? (
        <div className="muted" style={{ padding: "0 14px 14px" }}><span className="spinner" /> {s("loading")}</div>
      ) : list.length === 0 ? (
        <Empty>{s("emptyItems")}</Empty>
      ) : (
        <>
          {(override.error || appliedOk) && (
            <div style={{ padding: "0 14px 10px" }}>
              <ApiNotice error={override.error} what={s("whatOverride")} />
              {appliedOk && !override.error && <Notice kind="info">{s("applied")}</Notice>}
            </div>
          )}
          {entries.error && <div style={{ padding: "0 14px 10px" }}><ApiNotice error={entries.error} what={s("what")} onRetry={() => entries.reload()} /></div>}
          <div style={{ overflowX: "auto" }}>
            <table className="tbl">
              <thead>
                <tr><th>{s("colComponent")}</th><th>{s("colTier")}</th><th>{s("colChosen")}</th><th>{s("colCve")}</th><th>{s("colBasis")}</th><th>{s("colAction")}</th></tr>
              </thead>
              <tbody>
                {list.map((item) => {
                  const open = openId === item.ref_id;
                  return <Row key={item.ref_id} item={item} open={open} s={s} onToggle={() => setOpenId(open ? null : item.ref_id)} />;
                })}
              </tbody>
            </table>
          </div>
          {editing && (
            // Below the table, not as an extra row: phones show each table row as a labelled card.
            <div>
              <div style={{ padding: "10px 14px 0", fontWeight: 600 }}>{s("editing", { name: editing.name })} <span className="mono muted" style={{ fontSize: 11 }}>{editing.ref_kind}:{editing.ref_id}</span></div>
              <OverrideEditor key={editing.ref_id} item={editing} entries={entries.data?.entries ?? []} busy={override.busy} s={s} onApply={(b) => void override.run(b)} />
            </div>
          )}
          <div className="muted" style={{ fontSize: 12, padding: "10px 14px" }}>{s("footer")}</div>
        </>
      )}
    </div>
  );
}
