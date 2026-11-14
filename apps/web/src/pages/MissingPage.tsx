import { useCallback, useState } from "react";
import type { MissingItem, ScenarioIR } from "@contracts";
import { api } from "../lib/api";
import { useAction } from "../lib/hooks";
import { useScenario } from "../lib/scenario";
import { ApiNotice, Empty, NextStep, PageHead, ScenarioGate, SourceTag } from "../components/ui";
import { PdfViewer, usePdfSource, type PdfAnchor, type PdfLocateResult } from "../components/PdfViewer";

/* ---------- PDF anchors ---------- */

type Reffed = { id?: string; name?: string; role?: string; evidence_refs?: string[] };
interface AnchorGroup { label: string; queries: string[] }

/**
 * Candidate strings to look for in the PDF for one missing item, strongest first:
 *  (a) evidence quotes of the steps / hosts / services the item's `affects` names,
 *  (b) the `affects` strings themselves,
 *  (c) the field name as keywords,
 *  (d) evidence quotes of the hosts / services the item's category is about — where the
 *      report talks about that entity, which need not contain the missing answer.
 * A missing item is by definition something the report does not state, so every anchor is
 * "the nearest related passage", and the UI says which kind was used.
 */
function anchorGroups(item: MissingItem, ir: ScenarioIR): AnchorGroup[] {
  const quoteOf = new Map((ir.evidence ?? []).map((e) => [e.id, e.quote]));
  const quotes = (ents: Reffed[]) =>
    ents.flatMap((e) => e.evidence_refs ?? []).map((r) => quoteOf.get(r)).filter((q): q is string => !!q && !!q.trim());
  const actions = ir.actions as Reffed[], hosts = (ir.hosts ?? []) as Reffed[], services = (ir.services ?? []) as Reffed[];
  const affects = (item.affects ?? []).filter((a) => a && a.trim());
  const named = [...actions, ...hosts, ...services].filter((e) => affects.some((a) => a === e.id || a === e.name || a === e.role));

  const field = item.field?.trim() ?? "";
  const keyword = field.replace(/^(target|attacker|victim)\s+/i, "");
  const about =
    item.category === "host" || item.category === "network" ? hosts
    : item.category === "software" ? services
    : item.category === "version" ? (/service|software/i.test(field) ? services : hosts)
    : [];

  return [
    { label: "相關步驟的證據原文", queries: quotes(named) },
    { label: "相關步驟名稱", queries: affects },
    { label: "欄位關鍵字", queries: [field, keyword].filter(Boolean) },
    { label: `報告提到相關${about === services ? "服務" : "主機"}的段落（未必含答案）`, queries: quotes(about) },
  ].filter((g) => g.queries.length > 0);
}

type Located =
  | { itemId: string; state: "searching" }
  | { itemId: string; state: "found"; page: number; label: string; partial: boolean }
  | { itemId: string; state: "notfound" };

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

function ItemCard({ item, scenarioId, onDone, onLocate, located }: {
  item: MissingItem; scenarioId: string; onDone: (resp: unknown) => Promise<void>;
  /** Present only when the scenario has a PDF: locate this item's nearest passage in it. */
  onLocate?: () => void;
  located?: Located | null;
}) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<Resolution>("user_supplied");
  const [text, setText] = useState("");
  const res = RESOLUTIONS.find((r) => r.v === mode)!;
  const isOpen = item.status === "open";

  const send = async (statusV: Resolution, textV: string) => {
    const resp = await api.supplement(scenarioId, { text: textV.trim(), targets_missing_item: item.id, status: statusV });
    await onDone(resp);
    setOpen(false);
    setText("");
  };
  const submit = useAction(() => send(mode, text));
  // One click: accept a benign substitute (never recorded as a report fact).
  const accept = useAction((value: string) => send("substitute_chosen", value));

  const prefill = (example: string) => { setMode("user_supplied"); setOpen(true); setText(example); };
  const suggestions = item.suggestions?.length ? item.suggestions : item.suggestion ? [item.suggestion] : [];

  return (
    <div
      className={`card${onLocate ? " locatable" : ""}${located ? " located" : ""}`}
      style={{ display: "flex", flexDirection: "column", gap: 8 }}
      // Clicking the card (not its controls) locates the item in the PDF.
      onClick={onLocate ? (e) => { if (!(e.target as HTMLElement).closest("button, textarea, input, select, a")) onLocate(); } : undefined}
    >
      <div className="row" style={{ gap: 8 }}>
        {/* Lead with a plain-language question so the user need not read the whole report. */}
        <span style={{ fontWeight: 600 }}>{item.question || item.field}</span>
        <span className="tag">{CATEGORY[item.category] ?? item.category}</span>
        {item.severity && <span className={`tag ${item.severity}`}>{SEVERITY[item.severity] ?? item.severity}</span>}
        <span style={{ marginLeft: "auto", fontSize: 12 }} className={isOpen ? "status-PARTIAL" : item.status === "llm_suggested" ? "muted" : "status-PASS"}>
          {STATUS[item.status] ?? item.status}
        </span>
      </div>

      {item.affects?.length ? (
        <div className="muted" style={{ fontSize: 12 }}>相關步驟：{item.affects.join("、")}</div>
      ) : null}
      {/* Keep the original field name + rationale available, but secondary. */}
      <div className="muted" style={{ fontSize: 12 }}>
        <span className="mono">{item.field}</span>{item.reason ? `　·　${item.reason}` : ""}
      </div>

      {item.resolution && (
        <div style={{ fontSize: 13 }}>
          <span className="muted">處理內容：</span>{item.resolution} <SourceTag source={item.resolution_source} />
          {item.status === "llm_suggested" && <span className="muted" style={{ fontSize: 12 }}>（LLM 的建議，尚未經你確認）</span>}
        </div>
      )}

      {/* Benign substitutes the user can accept in one click. Each is clearly a substitute, not a report fact. */}
      {suggestions.length > 0 && isOpen && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 13, padding: "8px 10px", border: "1px solid var(--border)", borderRadius: "var(--radius)", background: "var(--bg-elev2, transparent)" }}>
          <span className="muted" style={{ fontSize: 12 }}>建議替身（點一下直接採用，會記為「已選替代方案」）：</span>
          <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
            {suggestions.map((s) => (
              <button key={s} className="small" disabled={accept.busy} onClick={() => accept.run(s)} title="以此替身補上，並標記為『已選替代方案』">{s}</button>
            ))}
          </div>
        </div>
      )}
      <ApiNotice error={accept.error} what="採用建議" />

      {located && (
        <div className="pdf-hint" role="status">
          {located.state === "searching" ? "在 PDF 中搜尋…"
            : located.state === "found"
              ? <>已跳到 PDF 第 {located.page} 頁並標示。依據：{located.label}{located.partial ? "（僅部分文字相符）" : ""}。</>
              : "在 PDF 中找不到對應段落，未跳轉；可在右側自行翻閱。"}
        </div>
      )}

      {!open ? (
        <div className="row" style={{ gap: 6 }}>
          <button className="small" onClick={() => setOpen(true)}>{isOpen ? "補充" : "修改"}</button>
          {onLocate && <button className="small" onClick={onLocate} title="在右側 PDF 中搜尋、標示並跳到最相關的段落">在 PDF 中定位</button>}
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, borderTop: "1px solid var(--border)", paddingTop: 10 }}>
          <div className="seg" style={{ alignSelf: "flex-start" }}>
            {RESOLUTIONS.map((r) => <button key={r.v} className={mode === r.v ? "on" : ""} onClick={() => setMode(r.v)} disabled={submit.busy}>{r.label}</button>)}
          </div>
          {/* Example answers make an abstract field concrete; click to fill. Examples only, not report claims. */}
          {mode === "user_supplied" && item.examples?.length ? (
            <div className="row" style={{ gap: 6, flexWrap: "wrap", fontSize: 12 }}>
              <span className="muted">範例：</span>
              {item.examples.map((ex) => (
                <button key={ex} className="small" onClick={() => prefill(ex)} disabled={submit.busy}>{ex}</button>
              ))}
            </div>
          ) : null}
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

  // PDF original beside the list; clicking an item searches, highlights and jumps to its anchor.
  const pdf = usePdfSource(ir.id);
  const hasPdf = pdf.state === "ready" && !!pdf.data;
  const [anchor, setAnchor] = useState<(PdfAnchor & { itemId: string; labels: string[] }) | null>(null);
  const [located, setLocated] = useState<Located | null>(null);
  const locateItem = (item: MissingItem) => {
    const groups = anchorGroups(item, ir);
    setAnchor((prev) => ({ itemId: item.id, groups: groups.map((g) => g.queries), labels: groups.map((g) => g.label), seq: (prev?.seq ?? 0) + 1 }));
    setLocated({ itemId: item.id, state: "searching" });
  };
  const onLocated = useCallback((r: PdfLocateResult) => {
    setAnchor((a) => {
      if (a && a.seq === r.seq) {
        setLocated(r.found
          ? { itemId: a.itemId, state: "found", page: r.page, label: a.labels[r.group] ?? "", partial: r.partial }
          : { itemId: a.itemId, state: "notfound" });
      }
      return a;
    });
  }, []);

  const addFree = useAction(async () => {
    const resp = await api.supplement(ir.id, { text: free.trim() });
    await absorb(resp);
    setFree("");
  });

  const pdfPane = hasPdf ? (
    <div className="pdf-pane">
      <span className="pdf-hint">點左側任一缺失項目，會在 PDF 中標示並跳到最相關的段落（缺失項目是報告沒寫的資訊，標示的是相關上下文，不是答案）。</span>
      <PdfViewer data={pdf.data!} filename="PDF 原檔" anchor={anchor} onLocated={onLocated} />
    </div>
  ) : null;

  return (
    <div className="page" style={{ maxWidth: hasPdf ? 1640 : 980 }}>
      <PageHead title="缺失補充" desc="報告沒寫清楚、但重建環境需要的資訊。每一項都附上白話問題、相關步驟與範例；你可以直接填答案、點範例帶入、採用建議替身，或明確接受未知。補充內容一律標示為使用者來源，不會與原文證據混淆。" />
      {pdf.state === "none" && <div className="pdf-hint">此情境無 PDF 原檔</div>}
      {pdf.state === "error" && <div className="pdf-hint">無法確認此情境是否有 PDF 原檔（後端未回應）。</div>}

      <div className={hasPdf ? "pdf-split" : undefined} style={hasPdf ? undefined : { display: "contents" }}>
      <div className={hasPdf ? "pdf-col" : undefined} style={hasPdf ? undefined : { display: "contents" }}>

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
        shown.map((m) => (
          <ItemCard key={m.id} item={m} scenarioId={ir.id} onDone={absorb}
            onLocate={hasPdf ? () => locateItem(m) : undefined}
            located={located?.itemId === m.id ? located : null} />
        ))
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

      </div>
      {pdfPane}
      </div>

      <NextStep prev={{ to: "/analysis", label: "分析結果" }} next={{ to: "/flow", label: "攻擊流程" }} />
    </div>
  );
}

export function MissingPage() {
  const { ir } = useScenario();
  return <ScenarioGate title="缺失補充">{ir && <Body ir={ir} />}</ScenarioGate>;
}
