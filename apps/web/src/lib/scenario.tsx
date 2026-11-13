// Current-scenario state shared by all workflow pages.
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import type { ScenarioIR } from "@contracts";
import { api, ApiError, extractIr, toApiError } from "./api";

const KEY = "cr.scenario";
const readStored = () => { try { return localStorage.getItem(KEY); } catch { return null; } };
const writeStored = (id: string | null) => {
  try { id ? localStorage.setItem(KEY, id) : localStorage.removeItem(KEY); } catch { /* storage unavailable */ }
};

interface ScenarioState {
  id: string | null;
  ir: ScenarioIR | null;
  loading: boolean;
  error: ApiError | null;
  /** Select a scenario; pass the IR if the caller already has it to skip a fetch. */
  select: (id: string | null, ir?: ScenarioIR | null) => void;
  reload: () => Promise<void>;
  /** Accept an API response that may carry an updated IR; otherwise refetch. */
  absorb: (resp: unknown) => Promise<void>;
}

const Ctx = createContext<ScenarioState | null>(null);

export function ScenarioProvider({ children }: { children: ReactNode }) {
  const [id, setId] = useState<string | null>(readStored);
  const [ir, setIr] = useState<ScenarioIR | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const seq = useRef(0);

  const load = useCallback(async (sid: string) => {
    const n = ++seq.current;
    setLoading(true);
    setError(null);
    try {
      const resp = await api.getScenario(sid);
      if (n !== seq.current) return;
      const got = extractIr(resp);
      if (got) setIr(got);
      else { setIr(null); setError(new ApiError(0, "後端回傳的內容不是 Scenario IR", "GET", `/api/scenario/${sid}`, "error")); }
    } catch (e) {
      if (n !== seq.current) return;
      setIr(null);
      setError(toApiError(e));
    } finally {
      if (n === seq.current) setLoading(false);
    }
  }, []);

  useEffect(() => { if (id && !ir) void load(id); /* initial load only */ }, []); // eslint-disable-line

  const select = useCallback((next: string | null, given?: ScenarioIR | null) => {
    seq.current++;
    writeStored(next);
    setId(next);
    setError(null);
    setLoading(false);
    if (!next) { setIr(null); return; }
    if (given) setIr(given);
    else { setIr(null); void load(next); }
  }, [load]);

  const reload = useCallback(async () => { if (id) await load(id); }, [id, load]);

  const absorb = useCallback(async (resp: unknown) => {
    const got = extractIr(resp);
    if (got && (!id || got.id === id)) { seq.current++; setIr(got); setError(null); setLoading(false); }
    else if (id) await load(id);
  }, [id, load]);

  return <Ctx.Provider value={{ id, ir, loading, error, select, reload, absorb }}>{children}</Ctx.Provider>;
}

export function useScenario(): ScenarioState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useScenario outside ScenarioProvider");
  return v;
}
