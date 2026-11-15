// Phones: show multi-column tables as one card per row, without losing table semantics.
// - The header row stays in the accessibility tree. CSS only hides it visually (never display:none).
// - display:block on table parts makes some browsers drop the native table roles, so explicit ARIA table roles are set.
// - Each cell gets a real label element with its column name, shown on phones. It is aria-hidden, because the column
//   header association already gives screen readers the name, and it would otherwise be read twice.
// Desktop tables look the same: the label elements are hidden there by CSS.
const MQ = "(max-width: 760px)";
const LABEL = "cell-label";

function setRole(el: Element, role: string) {
  if (el.getAttribute("role") !== role) el.setAttribute("role", role);
}

function label(table: HTMLTableElement) {
  const headRow = table.querySelector(":scope > thead > tr");
  const heads = headRow ? [...headRow.children].map((th) => th.textContent?.trim() ?? "") : [];
  if (heads.length < 2) return;
  table.classList.add("tbl-stack");
  setRole(table, "table");
  table.querySelectorAll(":scope > thead, :scope > tbody").forEach((g) => setRole(g, "rowgroup"));
  if (headRow) {
    setRole(headRow, "row");
    [...headRow.children].forEach((th) => setRole(th, "columnheader"));
  }
  for (const row of table.querySelectorAll(":scope > tbody > tr")) {
    setRole(row, "row");
    [...row.children].forEach((td, i) => {
      setRole(td, td.tagName === "TH" ? "rowheader" : "cell");
      const h = heads[i] ?? "";
      const first = td.firstElementChild;
      const existing = first?.classList.contains(LABEL) ? first : null;
      if (!h) { existing?.remove(); return; }
      if (existing) { if (existing.textContent !== h) existing.textContent = h; return; }
      const span = document.createElement("span");
      span.className = LABEL;
      span.setAttribute("aria-hidden", "true");
      span.textContent = h;
      td.insertBefore(span, td.firstChild);
    });
  }
}

/** Starts labelling tables inside `root`. Returns a stop function. */
export function stackTables(root: HTMLElement): () => void {
  const mq = window.matchMedia(MQ);
  let frame = 0;
  const run = () => {
    frame = 0;
    if (mq.matches) root.querySelectorAll<HTMLTableElement>("table.tbl").forEach(label);
  };
  const schedule = () => { if (!frame) frame = requestAnimationFrame(run); };
  // Only DOM changes outside the flow canvas matter: the canvas changes often and has no tables.
  // A text change reports the Text node as its target, so its parent element is checked.
  const obs = new MutationObserver((records) => {
    if (records.some((r) => !elementOf(r.target)?.closest(".react-flow"))) schedule();
  });
  obs.observe(root, { childList: true, subtree: true, characterData: true });
  mq.addEventListener("change", schedule);
  schedule();
  return () => { obs.disconnect(); mq.removeEventListener("change", schedule); if (frame) cancelAnimationFrame(frame); };
}

/** The element a mutation happened in: the node itself, or a Text node's parent. */
export function elementOf(node: Node): Element | null {
  return node.nodeType === Node.ELEMENT_NODE ? (node as Element) : node.parentElement;
}
