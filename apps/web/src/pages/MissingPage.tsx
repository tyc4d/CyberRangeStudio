import { useState } from "react";
import type { MissingItem, ScenarioIR } from "@contracts";
import { api } from "../lib/api";
import { useAction } from "../lib/hooks";
import { useScenario } from "../lib/scenario";
import { ApiNotice, Empty, NextStep, PageHead, ScenarioGate, SourceTag } from "../components/ui";

const CATEGORY: Record<MissingItem["category"], string> = {
  host: "主機", software: "軟體", version: "版本", network: "網路", account: "帳號",
  dependency: "依賴", precondition: "前置條件", proprietary: "專有元件", other: "其他",
};
const STATUS: Record<MissingItem["status"], string> = {
  open: "待補充", user_supplied: "使用者已補充", llm_suggested: "LLM 建議", substitute_chosen: "已選替代方案", accepted_unknown: "接受未知",
};
const SEVERITY: Record<string, string> = { blocker: "阻擋部署", major: "重要", minor: "次要" };
const SEV_RANK: Record<string, number> = { blocker: 0, major: 1, minor: 2 };
type Resolution = "user_supplied" | "substitute_chosen" | "accepted_unknown";
const RESOLUTIONS: { v: Resolution; label: string; needText: boolean; placeholder: string }[] = [
  { v: "user_supplied", label: "我知道答案", needText: true, placeholder: "填入實際資訊，例如：Windows Server 2019、Exchange 2016 CU19" },
  { v: "substitute_chosen", label: "用替代方案", needText: true, placeholder: "說明要用什麼替代，以及與原本的差異" },
  { v: "accepted_unknown", label: "接受未知", needText: false, placeholder: "（選填）備註為何可以不補" },
];

function ItemCard({ item, scenarioId, onDone }: { item: MissingItem; scenarioId: string; onDone: (resp: unknown) => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<Resolution>("user_supplied");
  const [text, setText] = useState("");
  const res = RESOLUTIONS.find((r) => r.v === mode)!;
  const submit = useAction(async () => {
    const resp = await api.supplement(scenarioId, { text: text.trim(), targets_missing_item: item.id, status: mode });
    await onDone(resp);
    setOpen(false);
    setText("");
  });
  const isOpen = item.status === "open";

  return (
    <div className="card" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div className="row" style={{ gap: 8 }}>
        <span style={{ fontWeight: 600 }}>{item.field}</span>
        <span className="tag">{CATEGORY[item.category] ?? item.category}</span>
        {item.severity && <span className={`tag ${item.severity}`}>{SEVERITY[item.severity] ?? item.severity}</span>}
        <span style={{ marginLeft: "auto", fontSize: 12 }} className={isOpen ? "status-PARTIAL" : item.status === "llm_suggested" ? "muted" : "status-PASS"}>
          {STATUS[item.status] ?? item.status}
        </span>
      </div>
      <div className="muted" style={{ fontSize: 13 }}>{item.reason}</div>
      {item.resolution && (
        <div style={{ fontSize: 13 }}>
          <span className="muted">處理內容：</span>{item.resolution} <SourceTag source={item.resolution_source} />
          {item.status === "llm_suggested" && <span className="muted" style={{ fontSize: 12 }}>（LLM 的建議，尚未經你確認）</span>}
        </div>
      )}
      {!open ? (
        <div><button className="small" onClick={() => setOpen(true)}>{isOpen ? "補充" : "修改"}</button></div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, borderTop: "1px solid var(--border)", paddingTop: 10 }}>
          <div className="seg" style={{ alignSelf: "flex-start" }}>
            {RESOLUTIONS.map((r) => <button key={r.v} className={mode === r.v ? "on" : ""} onClick={() => setMode(r.v)} disabled={submit.busy}>{r.label}</button>)}
          </div>
          <textarea rows={2} value={text} onChange={(e) => setText(e.target.value)} placeholder={res.placeholder} disabled={submit.busy} />
          <div className="row">
            <button className="primary small" disabled={submit.busy || (res.needText && !text.trim())} onClick={() => submit.run()}>
              {submit.busy ? <><span className="spinner" /> 送出中…</> : "送出"}
            </button>
            <button className="small" onClick={() => { setOpen(false); submit.clearError(); }} disabled={submit.busy}>取消</button>
          </div>
          <ApiNotice error={submit.error} what="補充" />
        </div>
      )}
    </div>
  );
}

function Body({ ir }: { ir: ScenarioIR }) {
  const { absorb } = useScenario();
  const [show, setShow] = useState<"open" | "all">("open");
  const [free, setFree] = useState("");
  const items = [...(ir.missing_items ?? [])].sort((a, b) => (SEV_RANK[a.severity ?? "minor"] ?? 3) - (SEV_RANK[b.severity ?? "minor"] ?? 3));
  const openItems = items.filter((m) => m.status === "open");
  const blockers = openItems.filter((m) => m.severity === "blocker").length;
  const shown = show === "open" ? openItems : items;
  const supplements = ir.supplements ?? [];
  const fieldOf = new Map(items.map((m) => [m.id, m.field]));

  const addFree = useAction(async () => {
    const resp = await api.supplement(ir.id, { text: free.trim() });
    await absorb(resp);
    setFree("");
  });

  return (
    <div className="page" style={{ maxWidth: 980 }}>
      <PageHead title="缺失補充" desc="報告沒寫清楚、但重建環境需要的資訊。你可以補上答案、選擇替代方案，或明確接受未知。補充內容會標示為使用者來源，不會與原文證據混淆。" />

      <div className="row">
        <div className="seg">
          <button className={show === "open" ? "on" : ""} onClick={() => setShow("open")}>待補充 {openItems.length}</button>
          <button className={show === "all" ? "on" : ""} onClick={() => setShow("all")}>全部 {items.length}</button>
        </div>
        {blockers > 0 && <span className="status-FAIL" style={{ fontSize: 13 }}>{blockers} 項會阻擋部署</span>}
      </div>

      {items.length === 0 ? (
        <div className="card"><Empty>分析沒有列出缺失項目。若你知道報告以外的背景資訊，仍可在下方自由補充。</Empty></div>
      ) : shown.length === 0 ? (
        <div className="card"><Empty>所有缺失項目都已處理。</Empty></div>
      ) : (
        shown.map((m) => <ItemCard key={m.id} item={m} scenarioId={ir.id} onDone={absorb} />)
      )}

      <div className="card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <h2 style={{ margin: 0 }}>自由補充</h2>
        <div className="muted" style={{ fontSize: 13 }}>不針對特定缺失項目的背景資訊，例如受害環境的已知配置。</div>
        <textarea rows={3} value={free} onChange={(e) => setFree(e.target.value)} placeholder="輸入補充說明" disabled={addFree.busy} />
        <div><button className="primary small" disabled={!free.trim() || addFree.busy} onClick={() => addFree.run()}>
          {addFree.busy ? <><span className="spinner" /> 送出中…</> : "加入補充"}
        </button></div>
        <ApiNotice error={addFree.error} what="補充" />
      </div>

      {supplements.length > 0 && (
        <div className="card flush">
          <div className="card-head"><h2>已加入的補充</h2><span className="muted" style={{ fontSize: 12 }}>{supplements.length}</span></div>
          <table className="tbl">
            <thead><tr><th>內容</th><th>對應缺失項目</th><th>來源</th></tr></thead>
            <tbody>
              {supplements.map((s) => (
                <tr key={s.id}>
                  <td style={{ whiteSpace: "pre-wrap" }}>{s.text}</td>
                  <td className="muted">{s.targets_missing_item ? fieldOf.get(s.targets_missing_item) ?? <span className="mono">{s.targets_missing_item}</span> : "—"}</td>
                  <td><SourceTag source={s.source} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <NextStep prev={{ to: "/analysis", label: "分析結果" }} next={{ to: "/flow", label: "攻擊流程" }} />
    </div>
  );
}

export function MissingPage() {
  const { ir } = useScenario();
  return <ScenarioGate title="缺失補充">{ir && <Body ir={ir} />}</ScenarioGate>;
}
