import { t } from "../i18n";
// Thin API client. All backend calls go through here. Never touches API keys.
// Endpoint paths other than health/budget/_routers, /scenario/list, /scenario/{id} and /ingest/analyze
// are the frontend's working assumption (see apps/web/README.md). They live only in this file.
import type {
  ScenarioIR, ValidationReport,
  ValidationPlan, PocManifest, ExecutionResult, ChainValidation, ExportManifest,
} from "@contracts";

export interface Budget {
  est_total_usd: number;
  calls: number;
  hard_cap_usd: number;
  stop_new_usd: number;
  note: string;
  by_model: { model: string; calls: number; est_cost_usd: number; input_tokens: number; output_tokens: number }[];
}

export interface AttackInfo { id: string; name: string; tactics: string[]; url: string; description?: string }
export interface ScenarioSummary { id: string; name: string; created_at: string; updated_at: string }
export interface VersionEntry { ir_version: number; note?: string; ts?: string }

/** unimplemented = route not there yet; offline = backend unreachable; error = backend answered with a failure. */
export type ApiErrorKind = "unimplemented" | "offline" | "error";

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
    public method: string,
    public path: string,
    public kind: ApiErrorKind,
    /** Structured error payload (e.g. validation errors, a failed deploy result), when the backend sent one. */
    public data?: unknown,
  ) {
    super(`${status || t("api.networkError")} ${detail}`);
  }
}

export function toApiError(e: unknown): ApiError {
  if (e instanceof ApiError) return e;
  return new ApiError(0, e instanceof Error ? e.message : String(e), "", "", "error");
}

const RETRY_DELAY_MS = 400;

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const method = init?.method ?? "GET";
  let r: Response;
  const send = () => fetch(path, { ...init, headers: { "Content-Type": "application/json", ...(init?.headers || {}) } });
  try {
    r = await send();
  } catch (e) {
    // The connection failed before any answer arrived. Browsers cancel in-flight requests when the machine's
    // network interfaces change, which a deploy or teardown on the same host causes (Docker networks come and go).
    // A read is safe to send again once; anything that changes state (POST/PUT/DELETE) is never re-sent.
    if (method !== "GET") throw new ApiError(0, e instanceof Error ? e.message : t("api.offline"), method, path, "offline");
    await new Promise((res) => setTimeout(res, RETRY_DELAY_MS));
    try {
      r = await send();
    } catch (e2) {
      throw new ApiError(0, e2 instanceof Error ? e2.message : t("api.offline"), method, path, "offline");
    }
  }
  const text = await r.text();
  let body: any = undefined;
  let isJson = false;
  if (text) {
    try { body = JSON.parse(text); isJson = true; } catch { /* non-JSON body */ }
  }
  if (!r.ok) {
    const raw = body?.detail ?? body?.message ?? (isJson ? body : text) ?? r.statusText;
    const detail = typeof raw === "string" ? raw : JSON.stringify(raw);
    let kind: ApiErrorKind = "error";
    // FastAPI answers an unknown route with exactly {"detail":"Not Found"}; a real "scenario not found" has its own text.
    if (r.status === 501 || r.status === 405 || (r.status === 404 && (!isJson || detail === "Not Found"))) kind = "unimplemented";
    // A 5xx without a JSON body comes from the dev proxy / a gateway, i.e. the API process is not reachable.
    // (The API itself uses 502/503 with a JSON detail for real failures such as a failed analysis or deploy.)
    else if (r.status >= 500 && !isJson) kind = "offline";
    throw new ApiError(r.status, detail || r.statusText, method, path, kind, typeof raw === "object" && raw !== null ? raw : undefined);
  }
  return body as T;
}

const post = <T,>(path: string, body?: unknown) =>
  req<T>(path, { method: "POST", body: JSON.stringify(body ?? {}) });

/** Backends may return the IR bare or wrapped; accept the common shapes, never invent content. */
export function extractIr(resp: any): ScenarioIR | null {
  for (const c of [resp, resp?.scenario, resp?.ir, resp?.scenario_ir, resp?.result]) {
    if (c && typeof c === "object" && Array.isArray(c.actions) && Array.isArray(c.relations)) return c as ScenarioIR;
  }
  return null;
}
export function extractScenarioId(resp: any): string | null {
  const ir = extractIr(resp);
  const id = ir?.id ?? resp?.scenario_id ?? resp?.id;
  return typeof id === "string" ? id : null;
}

const enc = encodeURIComponent;

export const api = {
  health: () => req<{ status: string }>("/api/health"),
  budget: () => req<Budget>("/api/budget"),
  routers: () => req<Record<string, string>>("/api/_routers"),

  // scenarios (module 3 store)
  listScenarios: () => req<ScenarioSummary[]>("/api/scenario/list"),
  getScenario: (id: string) => req<any>(`/api/scenario/${enc(id)}`),
  saveScenario: (id: string, ir: ScenarioIR, note: string) =>
    req<any>(`/api/scenario/${enc(id)}`, { method: "PUT", body: JSON.stringify({ ir, note }) }),
  listVersions: (id: string) => req<VersionEntry[]>(`/api/scenario/${enc(id)}/versions`),
  /** Official MITRE ATT&CK info for the technique ids this scenario uses (reference enrichment). */
  getAttack: (id: string) =>
    req<{ meta: { source?: string; downloaded?: string; count?: number }; techniques: Record<string, AttackInfo> }>(
      `/api/scenario/${enc(id)}/attack`,
    ),
  /** Original imported report, kept verbatim for review. 404 (unimplemented) when none was stored. */
  getSource: (id: string) =>
    req<{ input_kind: string; source_name: string | null; content: string; sha256: string; chars: number }>(
      `/api/scenario/${enc(id)}/source`,
    ),
  /** Original uploaded file (PDF) bytes for the viewer. Resolves null when the scenario has none (404). */
  getSourceFile: async (id: string): Promise<{ data: ArrayBuffer; contentType: string } | null> => {
    const path = `/api/scenario/${enc(id)}/source/file`;
    let r: Response;
    try {
      r = await fetch(path);
    } catch (e) {
      throw new ApiError(0, e instanceof Error ? e.message : t("api.offline"), "GET", path, "offline");
    }
    if (r.status === 404) return null;
    if (!r.ok) throw new ApiError(r.status, r.statusText, "GET", path, r.status >= 500 ? "offline" : "error");
    return { data: await r.arrayBuffer(), contentType: r.headers.get("content-type") ?? "" };
  },

  // module 1-2 ingest / supplement
  analyze: (body: { input_kind: string; content: string; method?: string; name?: string; upload_token?: string }) =>
    post<any>("/api/ingest/analyze", body),
  /** Upload a file (PDF/text/STIX) and get its readable text back for review. Does not analyze or store. */
  extract: async (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    let r: Response;
    try {
      // No Content-Type header: the browser sets the multipart boundary itself.
      r = await fetch("/api/ingest/extract", { method: "POST", body: fd });
    } catch (e) {
      throw new ApiError(0, e instanceof Error ? e.message : t("api.offline"), "POST", "/api/ingest/extract", "offline");
    }
    const text = await r.text();
    let body: any; try { body = text ? JSON.parse(text) : undefined; } catch { /* non-JSON */ }
    if (!r.ok) {
      const detail = typeof body?.detail === "string" ? body.detail : text || r.statusText;
      throw new ApiError(r.status, detail, "POST", "/api/ingest/extract", r.status === 501 ? "unimplemented" : "error");
    }
    return body as { input_kind: string; content: string; source_name: string; filename: string; chars: number; sha256: string; upload_token?: string };
  },
  supplement: (id: string, body: { text: string; targets_missing_item?: string; status?: string }) =>
    // `missing_item_id` duplicates `targets_missing_item` for backends that named the field that way.
    post<any>(`/api/ingest/${enc(id)}/supplement`, { ...body, ...(body.targets_missing_item ? { missing_item_id: body.targets_missing_item } : {}) }),

  // module 4-5 planning
  analyzeDependencies: (id: string) => post<any>(`/api/planning/${enc(id)}/dependencies`),
  catalogue: () => req<any>("/api/planning/catalogue"),
  planTopology: (id: string) => post<any>(`/api/planning/${enc(id)}/topology`),
  /** Human approval gate: deploy/up answers 409 until the current topology is approved. Returns the updated environment_plan. */
  approveTopology: (id: string, note?: string) =>
    post<any>(`/api/planning/${enc(id)}/topology/approve`, { approved: true, approved_by: "user", ...(note ? { note } : {}) }),

  // module 6 IaC
  getIac: (id: string) => req<any>(`/api/iac/${enc(id)}`),
  generateIac: (id: string) => post<any>(`/api/iac/${enc(id)}/generate`),

  // module 7 deploy
  /** `test_approved` is the backend's explicit-approval gate; callers must only invoke this after the user confirms. */
  deployUp: (id: string) => post<any>(`/api/deploy/${enc(id)}/up`, { test_approved: true }),
  deployDown: (id: string) => post<any>(`/api/deploy/${enc(id)}/down`),
  deployStatus: (id: string) => req<any>(`/api/deploy/${enc(id)}/status`),
  deployPreflight: (id: string) => req<any>(`/api/deploy/${enc(id)}/preflight`),
  deployHealth: (id: string) => req<any>(`/api/deploy/${enc(id)}/health`),
  /** Audit trail of up/down attempts (including refused ones), newest first. */
  deployRecords: (id: string) => req<any>(`/api/deploy/${enc(id)}/records`),

  // module 8 validation
  getReport: (id: string) => req<ValidationReport | any>(`/api/validate/${enc(id)}/report`),
  runValidation: (id: string) => post<ValidationReport | any>(`/api/validate/${enc(id)}/run`),

  // module 9 — PoC discovery, exploit validation & environment export (CONTRACT.md §HTTP API, prefix /api/poc).
  // All six frozen routes. The /report response shape is not yet a @contracts type (m9-chain owns it), so it is
  // typed loosely; the GUI derives its five separate fidelity metrics defensively. See requests/m9-gui.md.
  poc: {
    plan: (id: string) => post<ValidationPlan>(`/api/poc/${enc(id)}/plan`),
    discover: (id: string) => post<PocManifest>(`/api/poc/${enc(id)}/discover`),
    /** Real, ownership-gated payload execution. `signal` lets the GUI stop waiting (client-side abort). */
    execute: (id: string, actionIds?: string[], signal?: AbortSignal) =>
      req<ExecutionResult[]>(`/api/poc/${enc(id)}/execute`, {
        method: "POST",
        body: JSON.stringify(actionIds && actionIds.length ? { action_ids: actionIds } : {}),
        signal,
      }),
    chain: (id: string) => post<ChainValidation>(`/api/poc/${enc(id)}/chain`),
    report: (id: string) => req<any>(`/api/poc/${enc(id)}/report`),
    /** `format` is additive (CONTRACT has no field yet; a backend may ignore it). */
    export: (id: string, format?: string) =>
      post<{ bundle_path: string; manifest: ExportManifest }>(`/api/poc/${enc(id)}/export`, format ? { format } : {}),
    /** Fetch the built ZIP bytes. No frozen route yet (see requests/m9-gui.md); resolves null on 404/501. */
    exportDownload: async (id: string): Promise<{ data: ArrayBuffer; contentType: string } | null> => {
      const path = `/api/poc/${enc(id)}/export/download`;
      let r: Response;
      try {
        r = await fetch(path);
      } catch (e) {
        throw new ApiError(0, e instanceof Error ? e.message : t("api.offline"), "GET", path, "offline");
      }
      if (r.status === 404 || r.status === 501) return null;
      if (!r.ok) throw new ApiError(r.status, r.statusText, "GET", path, r.status >= 500 ? "offline" : "error");
      return { data: await r.arrayBuffer(), contentType: r.headers.get("content-type") ?? "" };
    },
  },
};
