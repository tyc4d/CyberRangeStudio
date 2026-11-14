import { useEffect, useRef, useState, type DragEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError, extractIr, extractScenarioId } from "../lib/api";
import { useAction } from "../lib/hooks";
import { useScenario } from "../lib/scenario";
import { ApiNotice, Busy, Notice, PageHead } from "../components/ui";
import { PdfViewer, usePdfSource } from "../components/PdfViewer";
import { SourceTextViewer, type TextLocateResult, type TextTarget } from "./MissingPage";

type Source = { input_kind: string; source_name: string | null; content: string; sha256: string; chars: number };

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

const kindLabel = (k: string) => KINDS.find((x) => x.v === k)?.label ?? k;

export function ImportPage() {
  const nav = useNavigate();
  const { id, ir, select } = useScenario();

  // When a scenario is already imported, show its original report for review
  // instead of a blank form. "匯入新報告" switches back to the form.
  const [forceNew, setForceNew] = useState(false);
  const [source, setSource] = useState<Source | null>(null);
  const [sourceState, setSourceState] = useState<"idle" | "loading" | "missing" | "error">("idle");
  useEffect(() => {
    setForceNew(false);
    if (!id) { setSource(null); setSourceState("idle"); return; }
    let live = true;
    setSource(null);
    setSourceState("loading");
    api.getSource(id)
      .then((s) => { if (live) { setSource(s); setSourceState("idle"); } })
      .catch((e: unknown) => {
        if (!live) return;
        setSourceState(e instanceof ApiError && e.kind === "unimplemented" ? "missing" : "error");
      });
    return () => { live = false; };
  }, [id]);

  const reviewing = !!id && !forceNew;
  // Original PDF of the imported scenario, when one was uploaded (source/file answers 200).
  const pdf = usePdfSource(id);
  // Text-only scenarios: locate a passage the analysis cited inside the imported text.
  const [textTarget, setTextTarget] = useState<(TextTarget & { evidenceId: string }) | null>(null);
  const [textHit, setTextHit] = useState<{ evidenceId: string; found: boolean; line?: number } | null>(null);
  const targetRef = useRef(textTarget);
  targetRef.current = textTarget;
  useEffect(() => { setTextTarget(null); setTextHit(null); }, [id]);
  const onTextLocated = (r: TextLocateResult) => {
    const t = targetRef.current;
    if (t && t.seq === r.seq) setTextHit({ evidenceId: t.evidenceId, found: r.found, line: r.line });
  };

  const [name, setName] = useState("");
  const [kind, setKind] = useState<InputKind>("text");
  const [method, setMethod] = useState<Method>("single_pass");
  const [content, setContent] = useState("");
  const [fileNote, setFileNote] = useState<string | null>(null);
  const [fileErr, setFileErr] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  // Token for the uploaded PDF original; sent with analyze so the new scenario keeps the PDF.
  const [uploadToken, setUploadToken] = useState<string | null>(null);

  const analyze = useAction(async () => {
    const resp = await api.analyze({ input_kind: kind, content, method, name: name.trim() || undefined, upload_token: uploadToken ?? undefined });
    const sid = extractScenarioId(resp);
    if (!sid) throw new ApiError(0, "後端有回應，但找不到情境 ID，無法開啟結果。", "POST", "/api/ingest/analyze", "error");
    select(sid, extractIr(resp));
    nav("/analysis");
  });

  const loadFile = async (f: File) => {
    setFileErr(null);
    setUploadToken(null);
    if (f.size > 25 * 1024 * 1024) { setFileErr(`檔案 ${f.name} 超過 25 MB，請改貼上需要的段落。`); return; }
    const isPdf = /\.pdf$/i.test(f.name) || f.type === "application/pdf";
    const isBinaryish = isPdf || /\.(xml)$/i.test(f.name);
    try {
      if (isBinaryish) {
        // PDF (and XML) go to the backend: pdftotext extracts the text, which we show for review.
        setExtracting(true);
        const r = await api.extract(f);
        setContent(r.content);
        setUploadToken(r.upload_token ?? null);
        setKind(r.input_kind as InputKind);
        if (!name.trim()) setName(r.source_name);
        setFileNote(`已從 ${f.name} 擷取文字（${r.chars.toLocaleString()} 字元）${isPdf ? "，請確認內容後再分析" : ""}`);
      } else {
        const text = await f.text();
        setContent(text);
        const k = kindFromName(f.name);
        if (k) setKind(k);
        if (!name.trim()) setName(f.name.replace(/\.[^.]+$/, ""));
        setFileNote(`已載入 ${f.name}（${text.length.toLocaleString()} 字元）`);
      }
    } catch (e) {
      setFileErr(e instanceof ApiError ? `無法解析 ${f.name}：${e.detail}` : `無法讀取 ${f.name}`);
    } finally {
      setExtracting(false);
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

  if (reviewing) {
    const title = source?.source_name || ir?.name || id || "目前情境";
    const hasPdf = pdf.state === "ready" && !!pdf.data;
    return (
      <div className="page" style={{ maxWidth: hasPdf || (source && (ir?.evidence?.length ?? 0) > 0) ? 1560 : 900 }}>
        <PageHead title="情資匯入" desc="此情境已匯入報告。以下為原始匯入內容，供檢視；要分析另一份報告請點「匯入新報告」。" />
        <div className="card" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              <strong>{title}</strong>
              <span className="muted mono" style={{ fontSize: 12 }}>
                {id}
                {source && <> · {kindLabel(source.input_kind)} · {source.chars.toLocaleString()} 字元</>}
              </span>
            </div>
            <div className="row" style={{ gap: 8 }}>
              <button onClick={() => nav("/analysis")}>查看分析結果</button>
              <button className="primary" onClick={() => setForceNew(true)}>匯入新報告</button>
            </div>
          </div>

          {sourceState === "loading" && <Busy label="載入已匯入內容…" />}
          {sourceState === "missing" && (
            <Notice kind="warn">這個情境沒有保存原始報告（可能是較早匯入或由範例建立）。分析結果仍可在「分析結果」查看。</Notice>
          )}
          {sourceState === "error" && (
            <Notice kind="err">無法載入已匯入內容。後端可能未啟動或該情境不存在。</Notice>
          )}
          {(() => {
            if (!source) return null;
            const label = <span className="pdf-hint">已匯入報告內容（唯讀）<span className="mono"> · sha256 {String(source.sha256 ?? "").slice(0, 12)}…</span></span>;
            if (hasPdf) {
              // Extracted text (what was analyzed) next to the PDF original (what was uploaded).
              return (
                <div className="pdf-split">
                  <div className="pdf-col">
                    <label className="field">
                      {label}
                      <textarea rows={30} value={source.content} readOnly style={{ background: "var(--surface-2, transparent)" }} />
                    </label>
                    <span className="pdf-hint">左側是送去分析的擷取文字，右側是上傳的 PDF 原檔，可對照版面與圖表。</span>
                  </div>
                  <div className="pdf-pane"><PdfViewer data={pdf.data!} filename="PDF 原檔" /></div>
                </div>
              );
            }
            // No PDF: the imported text is the original. Passages the analysis cited can be located in it.
            const evidence = (ir?.id === id ? ir?.evidence ?? [] : []).filter((e) => typeof e?.quote === "string" && e.quote.trim());
            const viewer = (
              <SourceTextViewer text={source.content} title={source.source_name || "匯入的原文"} mono={source.input_kind === "stix2.1"}
                target={textTarget} onLocated={onTextLocated} />
            );
            const noPdfNote = pdf.state === "loading" ? null : (
              <span className="pdf-hint">
                {pdf.state === "error" ? "無法確認此情境是否有 PDF 原檔（後端未回應）；以下是匯入的文字原文。" : "此情境以文字匯入，沒有 PDF 原檔；以下就是送去分析的原文。"}
              </span>
            );
            if (evidence.length === 0) {
              return (
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {noPdfNote}{label}
                  <div style={{ height: "60dvh", minHeight: 320, display: "flex", flexDirection: "column" }}>{viewer}</div>
                  <span className="pdf-hint">分析沒有為這份內容留下原文引文，所以沒有可定位的段落。</span>
                </div>
              );
            }
            return (
              <div className="pdf-split">
                <div className="pdf-col" style={{ gap: 8 }}>
                  {noPdfNote}
                  <span className="pdf-hint">分析引用的原文段落（{evidence.length}）。點一段會在右側原文中標示；只做整段比對，找不到就如實顯示。</span>
                  <div style={{ display: "flex", flexDirection: "column", gap: 6, maxHeight: "62dvh", overflow: "auto" }}>
                    {evidence.map((e) => {
                      const on = textTarget?.evidenceId === e.id;
                      const hit = textHit?.evidenceId === e.id ? textHit : null;
                      return (
                        <button key={e.id} data-testid="import-evidence" aria-pressed={on}
                          onClick={() => {
                            const matched = (e as unknown as { matched_text?: unknown }).matched_text;
                            setTextTarget((prev) => ({ evidenceId: e.id, quote: e.quote, alts: typeof matched === "string" && matched.trim() ? [matched] : undefined, seq: (prev?.seq ?? 0) + 1 }));
                          }}
                          style={{ display: "block", width: "100%", flex: "none", textAlign: "left", whiteSpace: "normal", height: "auto", minHeight: 0, padding: "8px 10px", fontSize: 13, lineHeight: 1.5, borderColor: on ? "var(--accent)" : undefined }}>
                          「{e.quote.length > 220 ? `${e.quote.slice(0, 220)}…` : e.quote}」
                          {hit && (
                            <span className="muted" role="status" style={{ display: "block", fontSize: 12, marginTop: 4 }}>
                              {hit.found ? `已在原文${hit.line ? `第 ${hit.line} 行` : ""}標示。` : "在匯入的原文中找不到完全相符的文字，未標示。"}
                            </span>
                          )}
                        </button>
                      );
                    })}
                  </div>
                </div>
                <div className="pdf-pane">{label}{viewer}</div>
              </div>
            );
          })()}
        </div>
      </div>
    );
  }

  return (
    <div className="page" style={{ maxWidth: 900 }}>
      <PageHead title="情資匯入" desc="上傳或貼上一份威脅情資報告。分析會從原文抽取攻擊行為、關係與證據，並標示哪些是原文支持、哪些是推測。" />

      {id && (
        <Notice kind="info">
          目前已選定情境「{ir?.name || id}」。送出後會<strong>建立新情境</strong>，不會覆蓋現有的。
          <button className="link" style={{ marginLeft: 8 }} onClick={() => setForceNew(false)}>返回檢視已匯入內容</button>
        </Notice>
      )}

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
          <button onClick={() => fileRef.current?.click()} disabled={analyze.busy || extracting}>選擇檔案</button>
          <span className="muted" style={{ fontSize: 13 }}>
            {extracting ? <><span className="spinner" /> 解析檔案中…</> : fileNote ?? "或把 .pdf / .txt / .md / .json / .xml 檔拖到這裡"}
          </span>
          <input ref={fileRef} type="file" accept=".pdf,.txt,.text,.md,.markdown,.json,.xml" hidden
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
