// UI localization. zh-TW is the default and the source of every key; en must define the same keys (checked by tsc).
// Only static UI text goes through here. Intelligence text, evidence quotes and API data are shown as received.
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import zhTW from "./zh-TW";
import en from "./en";

export type Locale = "zh-TW" | "en";
export const LOCALES: Locale[] = ["zh-TW", "en"];
export type MsgKey = keyof typeof zhTW;
/** English needs singular and plural forms. A plural message picks `one` when the count `n` is 1. */
export type Plural = { one: string; other: string };
export type Messages = Record<MsgKey, string | Plural>;
export type Vars = Record<string, string | number | undefined | null>;

const TABLES: Record<Locale, Messages> = { "zh-TW": zhTW, en };
const KEY = "cr.locale";
const readStored = (): Locale => {
  try { const v = localStorage.getItem(KEY); return v === "en" || v === "zh-TW" ? v : "zh-TW"; } catch { return "zh-TW"; }
};

let current: Locale = readStored();
export const getLocale = () => current;

/** Translate with the current locale. `{name}` placeholders take values from `vars`. */
export function t(key: MsgKey, vars?: Vars): string {
  const raw = TABLES[current][key] ?? zhTW[key] ?? key;
  const s = typeof raw === "string" ? raw : vars?.n === 1 ? raw.one : raw.other;
  return vars ? s.replace(/\{(\w+)\}/g, (m, k) => (vars[k] === undefined || vars[k] === null ? m : String(vars[k]))) : s;
}
/** Join a short list with the locale's list separator. */
export const joinList = (xs: string[]) => xs.join(current === "en" ? ", " : "、");

/** An object whose contents are rebuilt from `make` on every read, so module-level label tables follow the locale. */
export function live<T extends object>(make: () => T): T {
  return new Proxy({} as T, {
    get: (_o, p) => (make() as any)[p],
    has: (_o, p) => p in make(),
    ownKeys: () => Reflect.ownKeys(make()),
    getOwnPropertyDescriptor: (_o, p) => {
      const d = Object.getOwnPropertyDescriptor(make(), p);
      return d ? { ...d, configurable: true } : undefined;
    },
  });
}

const Ctx = createContext<{ locale: Locale; setLocale: (l: Locale) => void; t: typeof t }>({ locale: current, setLocale: () => {}, t });

export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, setState] = useState<Locale>(current);
  const setLocale = useCallback((l: Locale) => {
    current = l;
    try { localStorage.setItem(KEY, l); } catch { /* storage unavailable */ }
    setState(l);
  }, []);
  useEffect(() => { document.documentElement.lang = locale; }, [locale]);
  // A new function per locale, so memoized values that depend on `t` recompute when the locale changes.
  const value = useMemo(() => ({ locale, setLocale, t: ((k: MsgKey, v?: Vars) => t(k, v)) as typeof t }), [locale, setLocale]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const useI18n = () => useContext(Ctx);
export const useT = () => useContext(Ctx).t;
