// Lets a page put its own actions (save, validate…) into the shared top bar, where the reference Studio keeps them.
import { createContext, useContext, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

const Ctx = createContext<{ slot: HTMLElement | null; setSlot: (el: HTMLElement | null) => void } | null>(null);

export function TopbarProvider({ children }: { children: ReactNode }) {
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  return <Ctx.Provider value={{ slot, setSlot }}>{children}</Ctx.Provider>;
}
/** The element in the top bar that page actions render into. */
export function TopbarSlot() {
  const ctx = useContext(Ctx);
  return <div className="topbar-actions" ref={ctx?.setSlot} />;
}
export function TopbarActions({ children }: { children: ReactNode }) {
  const ctx = useContext(Ctx);
  return ctx?.slot ? createPortal(children, ctx.slot) : null;
}
