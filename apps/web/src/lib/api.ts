// Thin API client. All backend calls go through here. Never touches API keys.
export interface Budget {
  est_total_usd: number;
  calls: number;
  hard_cap_usd: number;
  stop_new_usd: number;
  note: string;
  by_model: { model: string; calls: number; est_cost_usd: number; input_tokens: number; output_tokens: number }[];
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail ?? detail; } catch { /* ignore */ }
    throw new Error(`${r.status} ${detail}`);
  }
  return r.json() as Promise<T>;
}

export const api = {
  health: () => req<{ status: string }>("/api/health"),
  budget: () => req<Budget>("/api/budget"),
  routers: () => req<Record<string, string>>("/api/_routers"),

  // scenarios (module 3 store)
  listScenarios: () => req<{ id: string; name: string; created_at: string; updated_at: string }[]>("/api/scenario/list").catch(() => []),
  getScenario: (id: string) => req<any>(`/api/scenario/${id}`),

  // module 1-2 ingest/analyze
  analyze: (body: { input_kind: string; content?: string; method?: string; name?: string }) =>
    req<any>("/api/ingest/analyze", { method: "POST", body: JSON.stringify(body) }),

  get: <T = any>(path: string) => req<T>(path),
  post: <T = any>(path: string, body: unknown) => req<T>(path, { method: "POST", body: JSON.stringify(body) }),
};
