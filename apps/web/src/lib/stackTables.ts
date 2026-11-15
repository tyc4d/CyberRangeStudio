// Phones: show multi-column tables as one card per row. Each cell gets its column name as a label (data-label),
// read from the table head, so the CSS in theme.css can stack the cells. Desktop tables are not changed.
const MQ = "(max-width: 760px)";

function label(table: HTMLTableElement) {
  const heads = [...table.querySelectorAll(":scope > thead > tr > th")].map((th) => th.textContent?.trim() ?? "");
  if (heads.length < 2) return;
  table.classList.add("tbl-stack");
  for (const row of table.querySelectorAll(":scope > tbody > tr")) {
    [...row.children].forEach((td, i) => {
      const h = heads[i];
      if (h && td.getAttribute("data-label") !== h) td.setAttribute("data-label", h);
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
  // Only DOM changes that can add or rename a table matter. The flow canvas changes often and has no tables.
  const obs = new MutationObserver((records) => {
    if (records.some((r) => !(r.target as Element).closest?.(".react-flow"))) schedule();
  });
  obs.observe(root, { childList: true, subtree: true, characterData: true });
  mq.addEventListener("change", schedule);
  schedule();
  return () => { obs.disconnect(); mq.removeEventListener("change", schedule); if (frame) cancelAnimationFrame(frame); };
}
