// Phone layout, touch-target and instructor-access checks, read-only. Runs against an EXISTING scenario
// (CR_E2E_SCENARIO) and never writes: every non-GET request is aborted and the test fails if the page tried to send one.
// The instructor-access cases answer three deploy GETs (status / preflight / health) with fixed data, so each display
// rule is reproducible without deploying.
//   CR_E2E_SCENARIO=<scenario id> npx playwright test e2e/mobile-rwd.spec.ts --reporter=list
// Without CR_E2E_SCENARIO the tests are skipped (not passed).
import { expect, test, type Page } from "@playwright/test";
import zh from "../src/i18n/zh-TW";

type K = keyof typeof zh;
/** UI text as the zh-TW locale renders it. */
const L = (k: K, v: Record<string, string | number> = {}) => zh[k].replace(/\{(\w+)\}/g, (m, n: string) => (n in v ? String(v[n]) : m));

const SCENARIO = process.env.CR_E2E_SCENARIO ?? "";
const PHONES = [360, 390, 430];

async function openReadOnly(page: Page, route: string): Promise<string[]> {
  const writes: string[] = [];
  await page.route("**/api/**", (r) => {
    // fallback, not continue: a GET answer fixed by an earlier route (instructor-access cases) must still apply.
    if (r.request().method() === "GET") return r.fallback();
    writes.push(`${r.request().method()} ${new URL(r.request().url()).pathname}`);
    return r.abort();
  });
  await page.addInitScript((sid) => { localStorage.setItem("cr.scenario", sid); localStorage.setItem("cr.locale", "zh-TW"); }, SCENARIO);
  await page.goto(route);
  return writes;
}

/** Visible text elements under `root` whose computed size is below `px`. Flow canvas content is excluded (it is zoomed). */
const smallText = (page: Page, px: number) => page.evaluate((min) => {
  const out: string[] = [];
  for (const el of document.querySelectorAll<HTMLElement>("main *, header *, nav *")) {
    if (el.closest(".react-flow, details:not([open]) > :not(summary), [aria-hidden='true']")) continue;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    if (![...el.childNodes].some((n) => n.nodeType === 3 && n.textContent!.trim())) continue;
    const size = parseFloat(getComputedStyle(el).fontSize);
    if (size < min) out.push(`${el.tagName.toLowerCase()}.${[...el.classList].join(".")} ${size}px "${el.textContent!.trim().slice(0, 20)}"`);
  }
  return out;
}, px);

test.describe("phone layout (read-only)", () => {
  test.skip(!SCENARIO, "CR_E2E_SCENARIO is not set: needs an existing scenario id");

  for (const width of PHONES) {
    test(`analysis page at ${width}px`, async ({ browser }) => {
      const context = await browser.newContext({ viewport: { width, height: 844 }, isMobile: true, hasTouch: true, locale: "zh-TW" });
      const page = await context.newPage();
      const writes = await openReadOnly(page, "/analysis");
      await expect(page.locator(".analysis-split")).toBeVisible();

      // No sideways page scroll.
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
      // One column: the evidence column sits below the findings.
      const cols = await page.locator(".analysis-split").evaluate((el) => getComputedStyle(el).gridTemplateColumns.split(" ").length);
      expect(cols, "analysis grid has one column on a phone").toBe(1);
      // Stacked tables ignore the desktop minimum width.
      for (const t of await page.locator("table.analysis-tbl").all()) {
        expect(await t.evaluate((el) => getComputedStyle(el).minWidth)).toBe("0px");
        expect((await t.boundingBox())!.width).toBeLessThanOrEqual(width);
      }

      // Table semantics survive the card layout.
      const table = page.locator("table.analysis-tbl").first();
      await expect(table).toHaveAttribute("role", "table");
      const thead = table.locator(":scope > thead");
      expect(await thead.evaluate((el) => getComputedStyle(el).display), "header row is not display:none").not.toBe("none");
      const headers = table.getByRole("columnheader");
      expect(await headers.count()).toBeGreaterThan(1);
      const firstRow = table.locator(":scope > tbody > tr").first();
      await expect(firstRow).toHaveAttribute("role", "row");
      await expect(firstRow.locator(":scope > td").first()).toHaveAttribute("role", "cell");
      // Each cell shows its column name as a real element (not ::before), matching the header text.
      const label = firstRow.locator(":scope > td > .cell-label").first();
      await expect(label).toBeVisible();
      await expect(label).toHaveText((await headers.first().innerText()).trim());

      // Type floor: labels and secondary text at least 14 px, running text at least 16 px.
      expect(await smallText(page, 14), "visible text under 14px").toEqual([]);
      for (const sel of ["body", "table.analysis-tbl td", ".notice .body"]) {
        const el = page.locator(sel).first();
        if (await el.count()) expect(parseFloat(await el.evaluate((e) => getComputedStyle(e).fontSize)), `${sel} font size`).toBeGreaterThanOrEqual(16);
      }

      expect(writes, "no write requests").toEqual([]);
      await context.close();
    });
  }

  for (const width of PHONES) {
    test(`PoC page at ${width}px keeps readable text and no sideways scroll`, async ({ browser }) => {
      test.skip(!SCENARIO, "CR_E2E_SCENARIO is not set: needs an existing scenario id");
      const context = await browser.newContext({ viewport: { width, height: 844 }, isMobile: true, hasTouch: true, locale: "zh-TW" });
      const page = await context.newPage();
      const writes = await openReadOnly(page, "/poc");
      await expect(page.locator("main")).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
      expect(await smallText(page, 14), "visible PoC text under 14px").toEqual([]);
      expect(writes, "no write requests").toEqual([]);
      await context.close();
    });
  }

  test("deploy page technical-details summary is a 44px touch target at 390px", async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, locale: "zh-TW" });
    const page = await context.newPage();
    const writes = await openReadOnly(page, "/deploy");
    const summary = page.locator("[data-testid='placement-tech'] > summary");
    if (await summary.count()) expect((await summary.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    else test.info().annotations.push({ type: "note", description: "this scenario's runtime shows no technical details section" });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    expect(writes, "no write requests").toEqual([]);
    await context.close();
  });

  test("deploy hosts panel: no isolation/security chip and no implementation terms in its header (zh-TW, en)", async ({ browser }) => {
    for (const locale of ["zh-TW", "en"]) {
      const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
      const page = await context.newPage();
      const writes = await openReadOnly(page, "/deploy");
      await page.evaluate((loc) => localStorage.setItem("cr.locale", loc), locale);
      await page.reload();
      const panel = page.locator(".placement-panel");
      await expect(panel).toBeVisible();
      // The status endpoint has no complete isolation evidence, so the panel must not show any pass/fail chip for it.
      await expect(page.getByTestId("isolation-state")).toHaveCount(0);
      const header = await panel.locator(".placement-panel__header").innerText();
      expect(header, "no implementation terms").not.toMatch(/隔離|網卡|PVE|Proxmox|worker|VM|Compose|isolation|NIC|approved topology|核准的拓樸/i);
      expect(writes, "no write requests").toEqual([]);
      await context.close();
    }
  });

  test("deploy hosts panel: multi-network note appears only when a host is drawn in several networks", async ({ page }) => {
    const ir = await (await page.request.get(`/api/scenario/${SCENARIO}`)).json();
    const multi = (ir.environment_plan?.hosts ?? []).some((h: any) => new Set(h.networks ?? []).size > 1);
    const writes = await openReadOnly(page, "/deploy");
    await expect(page.locator(".placement-panel")).toBeVisible();
    // Real data first: the note follows the plan.
    await expect(page.getByTestId("multi-network-note")).toHaveCount(multi ? 1 : 0);
    expect(writes).toEqual([]);
  });

  test("deploy hosts panel: multi-network note text (fixed plan answer, rendering only)", async ({ page }) => {
    const ir = await (await page.request.get(`/api/scenario/${SCENARIO}`)).json();
    const plan = ir.environment_plan;
    test.skip(!plan?.hosts?.length || (plan.networks?.length ?? 0) < 2, "the scenario plan needs one host and two networks");
    // Rendering only: the GET answer for this scenario puts the first host on the first two networks.
    const fixed = { ...ir, environment_plan: { ...plan, hosts: plan.hosts.map((h: any, i: number) => (i === 0 ? { ...h, networks: [plan.networks[0].id, plan.networks[1].id] } : h)) } };
    await page.route(`**/api/scenario/${SCENARIO}`, (r) => (r.request().method() === "GET" ? r.fulfill({ json: fixed }) : r.fallback()));
    const writes = await openReadOnly(page, "/deploy");
    await expect(page.getByTestId("multi-network-note")).toHaveText(L("pl.multiNet"));
    // The same host is drawn in both network zones.
    await expect(page.locator(".placement-host", { hasText: plan.hosts[0].role || plan.hosts[0].id })).toHaveCount(2);
    expect(writes).toEqual([]);
  });

  test("desktop analysis layout is unchanged at 1440px", async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: "zh-TW" });
    const page = await context.newPage();
    const writes = await openReadOnly(page, "/analysis");
    await expect(page.locator(".analysis-split")).toBeVisible();
    const cols = await page.locator(".analysis-split").evaluate((el) => getComputedStyle(el).gridTemplateColumns.split(" ").length);
    expect(cols, "two columns on desktop").toBe(2);
    const t = page.locator("table.analysis-tbl").first();
    expect(["640px", "760px"]).toContain(await t.evaluate((el) => getComputedStyle(el).minWidth));
    expect(await t.evaluate((el) => el.classList.contains("tbl-stack")), "desktop tables are not stacked").toBe(false);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(1440);
    expect(await smallText(page, 12), "desktop text under 12px").toEqual([]);
    expect(writes, "no write requests").toEqual([]);
    await context.close();
  });
});

/* ---------- touch targets: every control a finger operates is at least 44 px on a phone ---------- */

/** Interactive elements under 44 px tall or wide. Links inside running text are exempt (WCAG 2.5.8 inline exception). */
const smallTargets = (page: Page) => page.evaluate(() => {
  const sel = "button, a[href], input:not([type=hidden]), select, textarea, summary, [role=button], .chip, .react-flow__controls-button";
  const out: string[] = [];
  for (const el of document.querySelectorAll<HTMLElement>(sel)) {
    if (el.closest("details:not([open]) > :not(summary)")) continue;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height || getComputedStyle(el).visibility === "hidden") continue;
    if (el.matches("a[href]") && !el.querySelector("button") && el.closest("p, li, .notice .body, .empty, td")) continue;
    if (el.matches(".react-flow__edge")) {
      // A line is touched through its invisible interaction stroke: compare its on-screen width.
      const hit = el.querySelector(".react-flow__edge-interaction");
      const zoom = (() => { const m = /scale\(([\d.]+)\)/.exec(el.closest(".react-flow__viewport")?.getAttribute("style") ?? ""); return m ? parseFloat(m[1]) : 1; })();
      const w = hit ? parseFloat(hit.getAttribute("stroke-width") ?? "0") * zoom : 0;
      if (w < 44) out.push(`edge touch stroke ${Math.round(w)}px`);
      continue;
    }
    // A checkbox is operated through its label row.
    const target = el.matches("input[type=checkbox]") ? el.closest("label") ?? el : el;
    const b = target.getBoundingClientRect();
    if (b.height < 44 || (b.width < 44 && !target.matches("a, summary, label"))) out.push(`${el.tagName.toLowerCase()}.${[...el.classList].join(".")} ${b.width.toFixed(6)}x${b.height.toFixed(6)} "${(el.textContent || el.getAttribute("aria-label") || "").trim().slice(0, 16)}"`);
  }
  return out;
});

test.describe("phone touch targets (read-only)", () => {
  test.skip(!SCENARIO, "CR_E2E_SCENARIO is not set: needs an existing scenario id");
  for (const route of ["/analysis", "/missing", "/flow", "/deploy", "/import"]) {
    test(`controls are at least 44px on ${route} at 390px`, async ({ browser }) => {
      const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, locale: "zh-TW" });
      const page = await context.newPage();
      const writes = await openReadOnly(page, route);
      await page.waitForLoadState("networkidle");
      if (route === "/flow") {
        // Selecting a node shows its toolbar. Selection is screen state only; nothing is saved.
        await page.locator(".react-flow__node").first().click();
        await expect(page.locator(".node-toolbar").first()).toBeVisible();
      }
      expect(await smallTargets(page), "controls under 44px").toEqual([]);
      expect(writes, "no write requests").toEqual([]);
      await context.close();
    });
  }
});

/* ---------- instructor access: what is labelled reachable, and what is not ----------
 * Uses the real scenario and plan. Only the deploy status / preflight / health GET answers are fixed per case,
 * so each display rule is reproducible without deploying anything. Writes are still blocked. */
test.describe("instructor access block (read-only, fixed status answers)", () => {
  test.skip(!SCENARIO, "CR_E2E_SCENARIO is not set: needs an existing scenario id");

  async function openDeployWith(page: Page, status: Record<string, unknown>) {
    const ir = await (await page.request.get(`/api/scenario/${SCENARIO}`)).json();
    const host = ir.environment_plan?.hosts?.find((h: any) => h.services?.length) ?? ir.environment_plan?.hosts?.[0];
    await page.route(`**/api/deploy/${SCENARIO}/status`, (r) => r.fulfill({ json: status }));
    await page.route(`**/api/deploy/${SCENARIO}/preflight`, (r) => r.fulfill({ json: { backend: status.backend, ok: true } }));
    await page.route(`**/api/deploy/${SCENARIO}/health`, (r) => r.fulfill({ json: { state: status.state } }));
    const writes = await openReadOnly(page, "/deploy");
    await expect(page.getByTestId("instructor-access")).toBeVisible();
    return { writes, host };
  }
  const published = (host: any, ip: string, extra: Record<string, unknown> = {}) =>
    [{ host_id: host?.id, container_port: host?.services?.[0]?.port ?? 80, host_ip: ip, host_port: 20000, ...extra }];

  test("Proxmox: no instructor entry, no address, internal facts marked range-only", async ({ page }) => {
    const { writes } = await openDeployWith(page, { backend: "proxmox", state: "running", containers: [], published_ports: [] });
    const block = page.getByTestId("instructor-access");
    await expect(block.getByTestId("instructor-no-entry")).toContainText(L("ia.pve.title"));
    // The card ends with one next step for the instructor.
    await expect(block.getByTestId("instructor-next-step")).toHaveText(L("ia.pve.next"));
    await expect(block.getByTestId("instructor-endpoint")).toHaveCount(0);
    await expect(block.getByRole("button", { name: /^複製|^Copy/ })).toHaveCount(0);
    await expect(block.getByText(L("ia.st.reachable"), { exact: true })).toHaveCount(0);
    await expect(block.getByTestId("internal-badge")).toHaveText(L("ia.internal.badge"));
    expect(writes).toEqual([]);
  });

  test("local loopback: platform host only, access not verified, copy allowed", async ({ page }) => {
    const ir = await (await page.request.get(`/api/scenario/${SCENARIO}`)).json();
    const host = ir.environment_plan?.hosts?.find((h: any) => h.services?.length);
    const { writes } = await openDeployWith(page, { backend: "local-docker", state: "running", containers: [], published_ports: published(host, "127.0.0.1") });
    const row = page.getByTestId("instructor-endpoint");
    await expect(row).toHaveCount(1);
    await expect(row).toContainText("127.0.0.1:20000");
    await expect(row.locator("[data-scope]")).toHaveText(L("ia.scope.local"));
    await expect(row.locator("[data-status]")).toHaveText(L("ia.st.unverified"));
    await expect(row.getByRole("button", { name: L("ia.copy", { address: "127.0.0.1:20000" }) })).toBeVisible();
    await expect(page.getByTestId("instructor-access").getByText(L("ia.st.reachable"), { exact: true })).toHaveCount(0);
    expect(writes).toEqual([]);
  });

  test("LAN interface address: no reach claim without evidence", async ({ page }) => {
    const ir = await (await page.request.get(`/api/scenario/${SCENARIO}`)).json();
    const host = ir.environment_plan?.hosts?.find((h: any) => h.services?.length);
    await openDeployWith(page, { backend: "local-docker", state: "running", containers: [], published_ports: published(host, "192.168.20.5") });
    const row = page.getByTestId("instructor-endpoint");
    await expect(row.locator("[data-scope]")).toHaveText(L("ia.scope.lan"));
    await expect(row.locator("[data-status]")).toHaveText(L("ia.st.unverified"));
  });

  test("wildcard bind 0.0.0.0: shown as a bind address, never as a destination to copy", async ({ page }) => {
    const ir = await (await page.request.get(`/api/scenario/${SCENARIO}`)).json();
    const host = ir.environment_plan?.hosts?.find((h: any) => h.services?.length);
    await openDeployWith(page, { backend: "local-docker", state: "running", containers: [], published_ports: published(host, "0.0.0.0", { reachable: true }) });
    const row = page.getByTestId("instructor-endpoint");
    await expect(row.locator("[data-scope]")).toHaveText(L("ia.scope.any"));
    await expect(row.getByRole("button")).toHaveCount(0);
    await expect(row.locator("[data-status]")).toHaveText(L("ia.st.unverified"));
  });

  test("explicit reachability evidence from the backend is the only way to show 'reachable'", async ({ page }) => {
    const ir = await (await page.request.get(`/api/scenario/${SCENARIO}`)).json();
    const host = ir.environment_plan?.hosts?.find((h: any) => h.services?.length);
    await openDeployWith(page, { backend: "local-docker", state: "running", containers: [], published_ports: published(host, "192.168.20.5", { reachable: true }) });
    await expect(page.getByTestId("instructor-endpoint").locator("[data-status]")).toHaveText(L("ia.st.reachable"));
  });

  test("not running: published entries are not shown", async ({ page }) => {
    const ir = await (await page.request.get(`/api/scenario/${SCENARIO}`)).json();
    const host = ir.environment_plan?.hosts?.find((h: any) => h.services?.length);
    await openDeployWith(page, { backend: "local-docker", state: "stopped", containers: [], published_ports: published(host, "127.0.0.1") });
    await expect(page.getByTestId("instructor-endpoint")).toHaveCount(0);
    await expect(page.getByTestId("instructor-access")).toContainText(L("ia.notRunning"));
  });

  test("internal section lists plan hosts and allowed connections, marked range-only, and fits 360px", async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 360, height: 800 }, isMobile: true, hasTouch: true, locale: "zh-TW" });
    const page = await context.newPage();
    const ir = await (await page.request.get(`/api/scenario/${SCENARIO}`)).json();
    await page.route(`**/api/deploy/${SCENARIO}/status`, (r) => r.fulfill({ json: { backend: "proxmox", state: "not_created", containers: [], published_ports: [] } }));
    const writes = await openReadOnly(page, "/deploy");
    const internal = page.getByTestId("instructor-internal");
    await internal.locator("summary").click();
    await expect(internal.getByTestId("internal-badge")).toHaveText(L("ia.internal.badge"));
    await expect(internal.locator("tbody tr")).toHaveCount(ir.environment_plan?.hosts?.length ?? 0);
    await expect(internal).toContainText(L("ia.allowed", { n: ir.environment_plan?.connections?.length ?? 0 }));
    // Plan facts are named as a plan, not as connections that are active.
    await expect(internal.getByTestId("planned-note")).toHaveText(L("ia.plannedNote"));
    // Hosts are named by their short code; a long role is cut to two lines but stays readable in the title.
    const hosts = ir.environment_plan?.hosts ?? [];
    for (const [i, h] of hosts.entries()) {
      const row = internal.getByTestId("internal-host").nth(i);
      await expect(row.locator(".mono").first()).toHaveText(h.id);
      if (h.role) {
        const role = row.locator(".clamp-2");
        await expect(role).toHaveAttribute("title", h.role);
        const lines = await role.evaluate((el) => Math.round(el.getBoundingClientRect().height / parseFloat(getComputedStyle(el).lineHeight)));
        expect(lines, "role text is at most two lines").toBeLessThanOrEqual(2);
      }
    }
    const conns = ir.environment_plan?.connections ?? [];
    for (const [i, c] of conns.entries()) await expect(internal.getByTestId("planned-connection").nth(i)).toContainText(`${c.from_host} → ${c.to_host}`);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(360);
    expect(writes).toEqual([]);
    await context.close();
  });
});
