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
import { useI18n, type MsgKey, type Vars } from "../i18n";

/* ---------- shared UI translations ---------- */
const MESSAGE = {
  title: "inv.title",
  subtitle: "inv.subtitle",
  colComponent: "inv.col.component",
  colTier: "inv.col.tier",
  colChosen: "inv.col.chosen",
  colCve: "inv.col.cve",
  colBasis: "inv.col.basis",
  colAction: "inv.col.action",
  stated: "inv.stated",
  noVersion: "inv.noVersion",
  cited: "inv.cited",
  tierHave: "inv.tier.have",
  tierObtainable: "inv.tier.obtainable",
  tierUnavailable: "inv.tier.unavailable",
  tierHaveHint: "inv.tier.haveHint",
  tierObtainableHint: "inv.tier.obtainableHint",
  tierUnavailableHint: "inv.tier.unavailableHint",
  substitute: "inv.substitute",
  substituteOf: "inv.substituteOf",
  substituteHint: "inv.substituteHint",
  notDeployed: "inv.notDeployed",
  noCve: "inv.noCve",
  basisStated: "inv.basis.stated",
  basisAssumed: "inv.basis.assumed",
  basisSubstituted: "inv.basis.substituted",
  basisUserSupplied: "inv.basis.userSupplied",
  basisStatedHint: "inv.basis.statedHint",
  basisAssumedHint: "inv.basis.assumedHint",
  basisSubstitutedHint: "inv.basis.substitutedHint",
  basisUserSuppliedHint: "inv.basis.userSuppliedHint",
  overridden: "inv.overridden",
  overriddenAccept: "inv.overridden.accept",
  overriddenReplace: "inv.overridden.replace",
  overriddenVersion: "inv.overridden.version",
  autoWas: "inv.autoWas",
  needsQuestion: "inv.needsQuestion",
  pendingConfirmation: "inv.pendingConfirmation",
  hostOverrideUnavailable: "inv.hostOverrideUnavailable",
  edit: "inv.edit",
  editing: "inv.editing",
  close: "inv.close",
  why: "inv.why",
  questionVersion: "inv.question.version",
  questionVersionOptions: "inv.question.versionOptions",
  questionOther: "inv.question.other",
  optionSeparator: "inv.options.separator",
  optAccept: "inv.option.accept",
  optAcceptHint: "inv.option.acceptHint",
  optReplace: "inv.option.replace",
  optVersion: "inv.option.version",
  optClear: "inv.option.clear",
  pickComponent: "inv.pickComponent",
  pickPlaceholder: "inv.pickPlaceholder",
  versionLabel: "inv.versionLabel",
  versionPlaceholder: "inv.versionPlaceholder",
  suggestions: "inv.suggestions",
  apply: "inv.apply",
  applying: "inv.applying",
  applied: "inv.applied",
  emptyItems: "inv.emptyItems",
  loading: "inv.loading",
  what: "inv.what",
  whatOverride: "inv.whatOverride",
  sumHave: "inv.summary.have",
  sumObtainable: "inv.summary.obtainable",
  sumUnavailable: "inv.summary.unavailable",
  sumSubstitute: "inv.summary.substitute",
  sumQuestion: "inv.summary.question",
  footer: "inv.footer",
} as const satisfies Record<string, MsgKey>;

type Key = keyof typeof MESSAGE;
type S = (key: Key, vars?: Vars) => string;
function useStrings(): S {
  const { t } = useI18n();
  return (key, vars) => t(MESSAGE[key], vars);
}

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

/** Render a backend question from its structured field and choices; never expose the backend's fixed-language text. */
function questionPrompt(question: NonNullable<InventoryResolution["question"]>, s: S): string {
  const versionField = /^version for (.+)$/i.exec(String(question.field ?? "").trim());
  if (!versionField) return s("questionOther");
  const name = versionField[1].trim();
  const suggestions = Array.isArray(question.suggestions) ? question.suggestions.filter(Boolean) : [];
  return suggestions.length
    ? s("questionVersionOptions", { name, options: suggestions.join(s("optionSeparator")) })
    : s("questionVersion", { name });
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

  if (item.ref_kind === "host") {
    return (
      <div className="inv-editor" data-testid={`inv-editor-${item.ref_id}`} style={{ display: "grid", gap: 8, padding: "10px 14px", background: "var(--bg)", borderTop: "1px solid var(--border)" }}>
        <div>{s("hostOverrideUnavailable")}</div>
        {item.override && <button className="small" disabled={busy} onClick={() => onApply({ ref_id: item.ref_id, action: "clear" })}>{s("optClear")}</button>}
      </div>
    );
  }

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

      {mode === "accept" && <div className="muted" style={{ fontSize: 14 }}>{s("optAcceptHint")}</div>}
      {mode === "replace" && (
        <label style={{ display: "grid", gap: 4, maxWidth: 420 }}>
          <span className="muted" style={{ fontSize: 14 }}>{s("pickComponent")}</span>
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
            <span className="muted" style={{ fontSize: 14 }}>{s("versionLabel")}</span>
            <input value={version} placeholder={s("versionPlaceholder")} onChange={(e) => setVersion(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") submit(); }} data-testid={`inv-version-${item.ref_id}`} />
          </label>
          {r.question?.suggestions?.length ? (
            <div style={{ fontSize: 14 }}>
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
        <div className="muted" style={{ fontSize: 14 }}>{item.version ? s("stated", { v: item.version }) : s("noVersion")}</div>
        {item.cves?.length ? <div className="muted mono" style={{ fontSize: 14 }}>{s("cited", { c: item.cves.join(", ") })}</div> : null}
        <div className="mono muted" style={{ fontSize: 14 }}>{item.ref_kind}:{item.ref_id}</div>
      </td>
      <td>
        <TierTag tier={r.tier} s={s} />
        {r.needs_question && <div style={{ marginTop: 4 }}><span className="tag major" data-testid="inv-needs-question">{s("needsQuestion")}</span></div>}
      </td>
      <td>
        <span className="mono">{chosenText(r, s)}</span>
        {item.pending_confirmation && <div style={{ marginTop: 4 }}><span className="tag major" data-testid="inv-pending-confirmation">{s("pendingConfirmation")}</span></div>}
        {r.is_substitute && (
          <div style={{ marginTop: 4 }}>
            <span className="tag sub" title={s("substituteHint")} data-testid="inv-substitute">{s("substitute")}</span>
            {r.substitute_of && <span className="muted" style={{ fontSize: 14 }}> {s("substituteOf", { name: r.substitute_of })}</span>}
          </div>
        )}
        {ov && ovLabel && (
          <div style={{ marginTop: 4, fontSize: 14 }}>
            <span className="tag user" data-testid={`inv-override-${ov.action}`}>{s("overridden")}</span>{" "}
            <span className="muted">{s(ovLabel)}{ov.action === "version" && ov.version ? ` ${ov.version}` : ""}</span>
            {item.auto_resolution && <div className="muted">{s("autoWas", { v: chosenText(item.auto_resolution, s) })}</div>}
          </div>
        )}
        {r.reason && (
          <details style={{ marginTop: 4, fontSize: 14 }}>
            <summary className="muted">{s("why")}</summary>
            <div className="muted" lang="en" style={{ overflowWrap: "anywhere" }}>{r.reason}</div>
            {r.question && <div data-testid="inv-question-prompt" style={{ marginTop: 2 }}>{questionPrompt(r.question, s)}</div>}
          </details>
        )}
      </td>
      <td>{r.reproduces_cve.length ? r.reproduces_cve.map((c) => <div key={c} className="mono">{c}</div>) : <span className="muted">{s("noCve")}</span>}</td>
      <td><BasisTag basis={r.version_basis} s={s} /></td>
      <td style={{ textAlign: "right" }}>
        <button className="small" disabled={item.ref_kind === "host" && !ov} title={item.ref_kind === "host" ? s("hostOverrideUnavailable") : undefined}
          aria-expanded={open} onClick={onToggle} data-testid={`inv-edit-${item.ref_id}`}>{open ? s("close") : s("edit")}</button>
        {item.ref_kind === "host" && !ov && <div className="muted" style={{ fontSize: 14 }}>{s("hostOverrideUnavailable")}</div>}
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
    <div className="card flush inventory-panel" data-testid="inventory-panel">
      <div className="card-head">
        <h2>{s("title")}</h2>
        {list.length > 0 && <span className="muted" style={{ fontSize: 14 }} data-testid="inv-summary">{summary}</span>}
      </div>
      <div className="muted" style={{ fontSize: 14, padding: "0 14px 10px" }}>{s("subtitle")}</div>

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
            <table className="tbl inventory-table">
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
              <div style={{ padding: "10px 14px 0", fontWeight: 600 }}>{s("editing", { name: editing.name })} <span className="mono muted" style={{ fontSize: 14 }}>{editing.ref_kind}:{editing.ref_id}</span></div>
              <OverrideEditor key={editing.ref_id} item={editing} entries={entries.data?.entries ?? []} busy={override.busy} s={s} onApply={(b) => void override.run(b)} />
            </div>
          )}
          <div className="muted" style={{ fontSize: 14, padding: "10px 14px" }}>{s("footer")}</div>
        </>
      )}
    </div>
  );
}
