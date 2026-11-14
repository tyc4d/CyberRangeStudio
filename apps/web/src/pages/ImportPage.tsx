import { useRef, useState, type DragEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError, extractIr, extractScenarioId } from "../lib/api";
import { useAction } from "../lib/hooks";
import { useScenario } from "../lib/scenario";
import { ApiNotice, Busy, Notice, PageHead } from "../components/ui";

type InputKind = "text" | "markdown" | "stix2.1";
type Method = "single_pass" | "staged" | "staged_review";

const KINDS: { v: InputKind; label: string }[] = [
  { v: "text", label: "純文字" },
  { v: "markdown", label: "Markdown" },
  { v: "stix2.1", label: "STIX 2.1 (JSON)" },
];
const METHODS: { v: Method; label: string; hint: string }[] = [
  { v: "single_pass", label: "單次分析", hint: "一次呼叫完成，最快、最省預算，適合短報告。" },
  { v: "staged", label: "分階段分析", hint: "拆成多個步驟逐步抽取，較慢但較完整。" },
  { v: "staged_review", label: "分階段＋複核", hint: "分階段後再做一輪複核，最慢、花費最高。" },
];

const kindFromName = (name: string): InputKind | null =>
  /\.(md|markdown)$/i.test(name) ? "markdown" : /\.json$/i.test(name) ? "stix2.1" : /\.(txt|text)$/i.test(name) ? "text" : null;

export function ImportPage() {
  const nav = useNavigate();
  const { select } = useScenario();
  const [name, setName] = useState("");
  const [kind, setKind] = useState<InputKind>("text");
  const [method, setMethod] = useState<Method>("single_pass");
  const [content, setContent] = useState("");
  const [fileNote, setFileNote] = useState<string | null>(null);
  const [fileErr, setFileErr] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const analyze = useAction(async () => {
    const resp = await api.analyze({ input_kind: kind, content, method, name: name.trim() || undefined });
    const sid = extractScenarioId(resp);
    if (!sid) throw new ApiError(0, "後端有回應，但找不到情境 ID，無法開啟結果。", "POST", "/api/ingest/analyze", "error");
    select(sid, extractIr(resp));
    nav("/analysis");
  });

  const loadFile = async (f: File) => {
    setFileErr(null);
    if (f.size > 5 * 1024 * 1024) { setFileErr(`檔案 ${f.name} 超過 5 MB，請改貼上需要的段落。`); return; }
    try {
      const text = await f.text();
      setContent(text);
      const k = kindFromName(f.name);
      if (k) setKind(k);
      if (!name.trim()) setName(f.name.replace(/\.[^.]+$/, ""));
      setFileNote(`已載入 ${f.name}（${text.length.toLocaleString()} 字元）`);
    } catch {
      setFileErr(`無法讀取 ${f.name}`);
    }
  };
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDrag(false);
    const f = e.dataTransfer.files?.[0];
    if (f) void loadFile(f);
  };

  let stixProblem: string | null = null;
  if (kind === "stix2.1" && content.trim()) {
    try {
      const j = JSON.parse(content);
      if (j?.type !== "bundle" && !Array.isArray(j?.objects)) stixProblem = "這份 JSON 看起來不是 STIX bundle（缺少 type: bundle / objects）。仍可送出，由後端判斷。";
    } catch {
      stixProblem = "內容不是有效的 JSON，STIX 2.1 需要 JSON 格式。";
    }
  }
  const canSubmit = content.trim().length > 0 && !analyze.busy && !(kind === "stix2.1" && stixProblem?.startsWith("內容不是"));
  const methodHint = METHODS.find((m) => m.v === method)?.hint;

  return (
    <div className="page" style={{ maxWidth: 900 }}>
      <PageHead title="情資匯入" desc="上傳或貼上一份威脅情資報告。分析會從原文抽取攻擊行為、關係與證據，並標示哪些是原文支持、哪些是推測。" />

      <div className="card" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div className="grid c3">
          <label className="field"><span>情境名稱（選填）</span>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="例如：某勒索軟體入侵報告" disabled={analyze.busy} />
          </label>
          <label className="field"><span>輸入格式</span>
            <select value={kind} onChange={(e) => setKind(e.target.value as InputKind)} disabled={analyze.busy}>
              {KINDS.map((k) => <option key={k.v} value={k.v}>{k.label}</option>)}
            </select>
          </label>
          <label className="field"><span>分析方式</span>
            <select value={method} onChange={(e) => setMethod(e.target.value as Method)} disabled={analyze.busy}>
              {METHODS.map((m) => <option key={m.v} value={m.v}>{m.label}</option>)}
            </select>
          </label>
        </div>
        {methodHint && <div className="muted" style={{ fontSize: 12, marginTop: -6 }}>{methodHint}</div>}

        <div
          onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
          onDragLeave={() => setDrag(false)}
          onDrop={onDrop}
          style={{ border: `1px dashed ${drag ? "var(--accent)" : "var(--control)"}`, background: drag ? "var(--accent-dim)" : undefined, transition: "border-color var(--quick), background-color var(--quick)", padding: "10px 12px" }}
          className="row"
        >
          <button onClick={() => fileRef.current?.click()} disabled={analyze.busy}>選擇檔案</button>
          <span className="muted" style={{ fontSize: 13 }}>{fileNote ?? "或把 .txt / .md / .json 檔拖到這裡"}</span>
          <input ref={fileRef} type="file" accept=".txt,.text,.md,.markdown,.json" hidden
            onChange={(e) => { const f = e.target.files?.[0]; if (f) void loadFile(f); e.target.value = ""; }} />
        </div>
        {fileErr && <Notice kind="err">{fileErr}</Notice>}

        <label className="field"><span>報告內容 {content && <span className="mono">· {content.length.toLocaleString()} 字元</span>}</span>
          <textarea
            className={kind === "stix2.1" ? "mono" : ""}
            rows={16} value={content} disabled={analyze.busy}
            onChange={(e) => { setContent(e.target.value); setFileNote(null); }}
            placeholder={kind === "stix2.1" ? "貼上 STIX 2.1 bundle JSON" : "貼上情資報告全文"}
          />
        </label>
        {stixProblem && <Notice kind="warn">{stixProblem}</Notice>}

        {analyze.busy ? (
          <Busy label="分析中，後端正在處理報告…請勿關閉頁面" elapsed={analyze.elapsed} />
        ) : (
          <div className="row">
            <button className="primary" disabled={!canSubmit} onClick={() => analyze.run()}>開始分析</button>
            {!content.trim() && <span className="muted" style={{ fontSize: 12 }}>請先貼上或上傳報告內容</span>}
          </div>
        )}
        <ApiNotice error={analyze.error} what="情資分析" onRetry={canSubmit ? () => analyze.run() : undefined} />
        {analyze.error && analyze.error.kind !== "unimplemented" && (
          <div className="muted" style={{ fontSize: 12 }}>你輸入的內容仍保留在上方，可直接重試。</div>
        )}
      </div>
    </div>
  );
}
