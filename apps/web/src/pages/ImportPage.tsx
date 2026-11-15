import { useEffect, useRef, useState, type DragEvent } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { api, ApiError, extractIr, extractScenarioId } from "../lib/api";
import { useAction } from "../lib/hooks";
import { useScenario } from "../lib/scenario";
import { ApiNotice, Busy, Notice, PageHead } from "../components/ui";
import { PdfViewer, usePdfSource } from "../components/PdfViewer";
import { SourceTextViewer, type TextLocateResult, type TextTarget } from "./MissingPage";
import { live, t, useT } from "../i18n";
import { knownErrorKey } from "../lib/errors";

type Source = { input_kind: string; source_name: string | null; content: string; sha256: string; chars: number };

type InputKind = "text" | "markdown" | "stix2.1";
type Method = "single_pass" | "staged" | "staged_review";

const KINDS: { v: InputKind; label: string }[] = live(() => [
  { v: "text", label: t("imp.kind.text") },
  { v: "markdown", label: "Markdown" },
  { v: "stix2.1", label: "STIX 2.1 (JSON)" },
]);
/**
 * `calls` is how many model calls the backend makes for the method (each one reads the whole report),
 * so time and cost scale with it. `time` is a rough figure for a report of about ten pages, not a measurement.
 */
const METHODS: { v: Method; label: string; hint: string; calls: number; time: string }[] = live(() => [
  { v: "single_pass", label: t("imp.m.single"), hint: t("imp.m.single.hint"), calls: 1, time: t("imp.m.single.time") },
  { v: "staged", label: t("imp.m.staged"), hint: t("imp.m.staged.hint"), calls: 2, time: t("imp.m.staged.time") },
  { v: "staged_review", label: t("imp.m.review"), hint: t("imp.m.review.hint"), calls: 3, time: t("imp.m.review.time") },
]);
/** Label for text that was extracted from an uploaded PDF (the backend stores it as input_kind "text"). */
const pdfKindLabel = () => t("imp.pdfKind");
const usd = (n: number) => `US$${n < 0.1 ? n.toFixed(3) : n.toFixed(2)}`;

const kindFromName = (name: string): InputKind | null =>
  /\.(md|markdown)$/i.test(name) ? "markdown" : /\.json$/i.test(name) ? "stix2.1" : /\.(txt|text)$/i.test(name) ? "text" : null;

const kindLabel = (k: string) => KINDS.find((x) => x.v === k)?.label ?? k;

export function ImportPage() {
  const t = useT();
  const nav = useNavigate();
  const { id, ir, select } = useScenario();

  // When a scenario is already imported, show its original report for review
  // instead of a blank form. "匯入新報告" switches back to the form.
  // The home page's "＋ 新建情境" asks for a blank form explicitly (router state), even while a scenario is selected.
  const fresh = (useLocation().state as { fresh?: boolean } | null)?.fresh === true;
  const [forceNew, setForceNew] = useState(fresh);
  const [source, setSource] = useState<Source | null>(null);
  const [sourceState, setSourceState] = useState<"idle" | "loading" | "missing" | "error">("idle");
  useEffect(() => {
    setForceNew(fresh);
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
  }, [id, fresh]);

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
  /** True while the content shown came from an uploaded PDF, so the format is not mislabelled as plain text. */
  const [fromPdf, setFromPdf] = useState(false);
  // Average cost per model call so far, to turn "N calls" into a rough amount. Optional: absent when there is no usage yet.
  const [perCall, setPerCall] = useState<number | null>(null);
  useEffect(() => {
    let live = true;
    api.budget().then((b) => {
      const calls = Number(b?.calls), total = Number(b?.est_total_usd);
      if (live && Number.isFinite(calls) && Number.isFinite(total) && calls > 0 && total > 0) setPerCall(total / calls);
    }).catch(() => { /* the estimate is optional */ });
    return () => { live = false; };
  }, []);

  const analyze = useAction(async () => {
    const resp = await api.analyze({ input_kind: kind, content, method, name: name.trim() || undefined, upload_token: uploadToken ?? undefined });
    const sid = extractScenarioId(resp);
    if (!sid) throw new ApiError(0, "no scenario id in analyze response", "POST", "/api/ingest/analyze", "error");
    select(sid, extractIr(resp));
    nav("/analysis");
  });

  const loadFile = async (f: File) => {
    setFileErr(null);
    setUploadToken(null);
    setFromPdf(false);
    if (f.size > 25 * 1024 * 1024) { setFileErr(t("imp.tooBig", { name: f.name })); return; }
    const isPdf = /\.pdf$/i.test(f.name) || f.type === "application/pdf";
    const isBinaryish = isPdf || /\.(xml)$/i.test(f.name);
    try {
      if (isBinaryish) {
        // PDF (and XML) go to the backend: pdftotext extracts the text, which we show for review.
        setExtracting(true);
        const r = await api.extract(f);
        setContent(r.content);
        setUploadToken(r.upload_token ?? null);
        setKind(KINDS.some((k) => k.v === r.input_kind) ? (r.input_kind as InputKind) : "text");
        setFromPdf(isPdf);
        if (!name.trim()) setName(r.source_name);
        setFileNote(`${t("imp.extracted", { name: f.name, n: r.chars.toLocaleString() })}${isPdf ? ` ${t("imp.extractedPdf")}` : ""}`);
      } else {
        const text = await f.text();
        setContent(text);
        const k = kindFromName(f.name);
        if (k) setKind(k);
        if (!name.trim()) setName(f.name.replace(/\.[^.]+$/, ""));
        setFileNote(t("imp.loaded", { name: f.name, n: text.length.toLocaleString() }));
      }
    } catch (e) {
      { const k = e instanceof ApiError ? knownErrorKey(e) : null; setFileErr(k ? `${t("imp.parseFail", { name: f.name })} ${t(k)}` : t("imp.parseFail", { name: f.name })); }
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
  let stixInvalid = false;
  if (kind === "stix2.1" && content.trim()) {
    try {
      const j = JSON.parse(content);
      if (j?.type !== "bundle" && !Array.isArray(j?.objects)) stixProblem = t("imp.notBundle");
    } catch {
      stixProblem = t("imp.notJson");
      stixInvalid = true;
    }
  }
  const canSubmit = content.trim().length > 0 && !analyze.busy && !(kind === "stix2.1" && stixInvalid);

  if (reviewing) {
    const title = source?.source_name || ir?.name || id || t("imp.current");
    const hasPdf = pdf.state === "ready" && !!pdf.data;
    return (
      <div className="page" style={{ maxWidth: hasPdf || (source && (ir?.evidence?.length ?? 0) > 0) ? 1560 : 900 }}>
        <PageHead title={t("imp.title")} desc={t("imp.reviewDesc")} />
        <div className="card" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              <strong>{title}</strong>
              <span className="muted mono" style={{ fontSize: 12 }}>
                {id}
                {source && <> · {hasPdf && source.input_kind === "text" ? pdfKindLabel() : kindLabel(source.input_kind)} · {t("imp.chars", { n: Number(source.chars ?? 0).toLocaleString() })}</>}
              </span>
            </div>
            <div className="row" style={{ gap: 8 }}>
              <button onClick={() => nav("/analysis")}>{t("imp.toAnalysis")}</button>
              <button className="primary" onClick={() => setForceNew(true)}>{t("imp.importNew")}</button>
            </div>
          </div>

          {sourceState === "loading" && <Busy label={t("imp.sourceLoading")} />}
          {sourceState === "missing" && (
            <Notice kind="warn">{t("imp.noSource")}</Notice>
          )}
          {sourceState === "error" && (
            <Notice kind="err">{t("imp.sourceError")}</Notice>
          )}
          {(() => {
            if (!source) return null;
            const label = <span className="pdf-hint">{t("imp.readonly")}</span>;
            if (hasPdf) {
              // Extracted text (what was analyzed) next to the PDF original (what was uploaded).
              return (
                <div className="pdf-split">
                  <div className="pdf-col">
                    <label className="field">
                      {label}
                      <textarea rows={30} value={source.content} readOnly style={{ background: "var(--surface-2, transparent)" }} />
                    </label>
                    <span className="pdf-hint">{t("imp.pdfSide")}</span>
                  </div>
                  <div className="pdf-pane"><PdfViewer data={pdf.data!} filename={t("pdf.original")} /></div>
                </div>
              );
            }
            // No PDF: the imported text is the original. Passages the analysis cited can be located in it.
            const evidence = (ir?.id === id ? ir?.evidence ?? [] : []).filter((e) => typeof e?.quote === "string" && e.quote.trim());
            const viewer = (
              <SourceTextViewer text={source.content} title={source.source_name || t("imp.sourceTitle")} mono={source.input_kind === "stix2.1"}
                target={textTarget} onLocated={onTextLocated} />
            );
            const noPdfNote = pdf.state === "loading" ? null : (
              <span className="pdf-hint">
                {pdf.state === "error" ? t("imp.pdfUnknown") : t("imp.textOnly")}
              </span>
            );
            if (evidence.length === 0) {
              return (
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {noPdfNote}{label}
                  <div style={{ height: "60dvh", minHeight: 320, display: "flex", flexDirection: "column" }}>{viewer}</div>
                  <span className="pdf-hint">{t("imp.noEvidence")}</span>
                </div>
              );
            }
            return (
              <div className="pdf-split">
                <div className="pdf-col" style={{ gap: 8 }}>
                  {noPdfNote}
                  <span className="pdf-hint">{t("imp.evidenceList", { n: evidence.length })}</span>
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
                              {hit.found ? (hit.line ? t("imp.hitLine", { line: hit.line }) : t("imp.hit")) : t("imp.miss")}
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
      <PageHead title={t("imp.title")} desc={t("imp.desc")} />

      {id && (
        <Notice kind="info">
          {t("imp.newWarn1", { name: ir?.name || id })} <strong>{t("imp.newWarnStrong")}</strong>{t("imp.newWarn2")}
          <button className="link" style={{ marginLeft: 8 }} onClick={() => setForceNew(false)}>{t("imp.backToReview")}</button>
        </Notice>
      )}

      <div className="card" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div className="grid c3">
          <label className="field"><span>{t("imp.name")}</span>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder={t("imp.namePh")} disabled={analyze.busy} />
          </label>
          <label className="field"><span>{t("imp.kind")}</span>
            <select value={kind} onChange={(e) => setKind(e.target.value as InputKind)} disabled={analyze.busy}
              title={fromPdf ? t("imp.fromPdf") : undefined}>
              {KINDS.map((k) => <option key={k.v} value={k.v}>{fromPdf && k.v === "text" ? pdfKindLabel() : k.label}</option>)}
            </select>
          </label>
          <label className="field"><span>{t("imp.method")}</span>
            <select value={method} onChange={(e) => setMethod(e.target.value as Method)} disabled={analyze.busy}>
              {METHODS.map((m) => <option key={m.v} value={m.v}>{m.label}</option>)}
            </select>
          </label>
        </div>
        <div className="muted" style={{ fontSize: 12, marginTop: -6, display: "flex", flexDirection: "column", gap: 2 }} data-testid="method-estimates">
          {/* Only the chosen method is described, so the form stays short. */}
          {METHODS.filter((m) => m.v === method).map((m) => (
            <div key={m.v} style={{ color: "var(--text)" }}>
              {m.hint} {[m.time, t("imp.calls", { n: m.calls }), perCall !== null ? t("imp.cost", { usd: usd(perCall * m.calls) }) : m.calls > 1 ? t("imp.costX", { n: m.calls }) : ""].filter(Boolean).join(" · ")}
            </div>
          ))}
          <div>{t("imp.estimate")}{perCall !== null ? ` ${t("imp.estimateUsd")}` : ""}</div>
        </div>

        <div
          onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
          onDragLeave={() => setDrag(false)}
          onDrop={onDrop}
          style={{ border: `1px dashed ${drag ? "var(--accent)" : "var(--control)"}`, background: drag ? "var(--accent-dim)" : undefined, transition: "border-color var(--quick), background-color var(--quick)", padding: "10px 12px" }}
          className="row"
        >
          <button onClick={() => fileRef.current?.click()} disabled={analyze.busy || extracting}>{t("imp.chooseFile")}</button>
          <span className="muted" style={{ fontSize: 13 }}>
            {extracting ? <><span className="spinner" /> {t("imp.extracting")}</> : fileNote ?? t("imp.dropHint")}
          </span>
          <input ref={fileRef} type="file" accept=".pdf,.txt,.text,.md,.markdown,.json,.xml" hidden
            onChange={(e) => { const f = e.target.files?.[0]; if (f) void loadFile(f); e.target.value = ""; }} />
        </div>
        {fileErr && <Notice kind="err">{fileErr}</Notice>}

        <label className="field"><span>{t("imp.content")} {content && <span className="mono">· {t("imp.chars", { n: content.length.toLocaleString() })}</span>}</span>
          <textarea
            className={kind === "stix2.1" ? "mono" : ""}
            rows={12} value={content} disabled={analyze.busy}
            onChange={(e) => { setContent(e.target.value); setFileNote(null); if (!e.target.value.trim()) { setFromPdf(false); setUploadToken(null); } }}
            placeholder={kind === "stix2.1" ? t("imp.phStix") : t("imp.phText")}
          />
        </label>
        {stixProblem && <Notice kind="warn">{stixProblem}</Notice>}

        {analyze.busy ? (
          <Busy label={t("imp.busy")} elapsed={analyze.elapsed} />
        ) : (
          <div className="row">
            <button className="primary" disabled={!canSubmit} onClick={() => analyze.run()}>{t("imp.start")}</button>
            {!content.trim() && <span className="muted" style={{ fontSize: 12 }}>{t("imp.needContent")}</span>}
          </div>
        )}
        <ApiNotice error={analyze.error} what={t("imp.what")} onRetry={canSubmit ? () => analyze.run() : undefined} />
        {analyze.error && analyze.error.kind !== "unimplemented" && (
          <div className="muted" style={{ fontSize: 12 }}>{t("imp.kept")}</div>
        )}
      </div>
    </div>
  );
}
