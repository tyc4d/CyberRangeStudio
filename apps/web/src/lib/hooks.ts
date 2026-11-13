import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, toApiError } from "./api";

/** Load data on mount / when deps change. Keeps the last good data while reloading. */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[], enabled = true) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(enabled);
  const seq = useRef(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  const reload = useCallback(async (silent = false) => {
    const n = ++seq.current;
    if (!silent) setLoading(true);
    try {
      const d = await fnRef.current();
      if (n !== seq.current) return;
      setData(d);
      setError(null);
    } catch (e) {
      if (n !== seq.current) return;
      setError(toApiError(e));
    } finally {
      if (n === seq.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!enabled) { seq.current++; setLoading(false); return; }
    setData(null);
    void reload();
  }, [...deps, enabled]); // eslint-disable-line

  /** Replace the data with a fresher result obtained elsewhere (e.g. a POST response); supersedes any earlier load error. */
  const put = useCallback((d: T) => { seq.current++; setData(d); setError(null); setLoading(false); }, []);

  return { data, error, loading, reload, setData: put };
}

/** Run a user-triggered action with busy / error state and an elapsed-seconds counter for honest progress feedback. */
export function useAction<A extends unknown[], T>(fn: (...args: A) => Promise<T>) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    if (!busy) return;
    setElapsed(0);
    const t0 = Date.now();
    const t = setInterval(() => setElapsed(Math.floor((Date.now() - t0) / 1000)), 500);
    return () => clearInterval(t);
  }, [busy]);

  const run = useCallback(async (...args: A): Promise<T | undefined> => {
    setBusy(true);
    setError(null);
    try {
      return await fnRef.current(...args);
    } catch (e) {
      setError(toApiError(e));
      return undefined;
    } finally {
      setBusy(false);
    }
  }, []);

  return { run, busy, error, elapsed, clearError: () => setError(null) };
}
