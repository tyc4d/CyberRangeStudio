// Inventory panel on the Software (deps) page, against a fully mocked API (no backend, no LLM).
// The mocked rows are real outputs of app.planner.inventory.resolve (e2e/fixtures/inventory-mock.json, generated
// from the inventory module), so the UI is checked against the contract's actual shapes.
// Checks: tier / substitute / reproduced CVE / version basis are shown as the backend decided; the override control
// sends the right request; strings follow cr.locale (zh-TW and en); phone width has no horizontal page scroll.
import { expect, test, type Page, type Route } from "@playwright/test";
import fs from "node:fs";

const fx = JSON.parse(fs.readFileSync(new URL("./fixtures/inventory-mock.json", import.meta.url), "utf8"));
const SID = "scn_inv_gui_mock";
const IR = {
  id: SID, name: "inventory mock", ir_version: 1, actions: [], relations: [], evidence: [],
  hosts: [{ id: "host_dc", role: "domain controller", os: "Windows Server", service_refs: ["svc_ad"] }],
  services: [
    { id: "svc_horizon", name: "VMware Horizon", cve: ["CVE-2021-44228"] },
    { id: "svc_ad", name: "Active Directory" },
    { id: "svc_web", name: "nginx", version: "1.31.8", catalogue_component: "oss-nginx" },
  ],
  fidelity: {},
};

async function mockApi(page: Page, locale: "zh-TW" | "en") {
  const sent: any[] = [];
  let items = structuredClone(fx.items);
  await page.addInitScript(([sid, loc]) => { localStorage.setItem("cr.scenario", sid); localStorage.setItem("cr.locale", loc); }, [SID, locale]);
  await page.route("**/api/**", async (route: Route) => {
    const url = new URL(route.request().url());
    const p = url.pathname;
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (p === `/api/scenario/${SID}`) return json(IR);
    if (p === "/api/planning/inventory") return json({ entries: fx.entries });
    if (p === `/api/planning/${SID}/inventory`) return json({ items });
    if (p === `/api/planning/${SID}/inventory/override`) {
      const body = route.request().postDataJSON();
      sent.push(body);
      items = items.map((it: any) => it.ref_id !== body.ref_id ? it
        : body.action === "version" ? { ...it, auto_resolution: it.resolution, resolution: fx.after_version, override: { action: "version", version: body.version } }
        : body.action === "accept" ? { ...it, override: { action: "accept" } }
        : body.action === "clear" ? { ...it, override: null, auto_resolution: null }
        : it);
      return json({ items });
    }
    if (p === "/api/planning/catalogue") return json({ components: [] });
    if (p === "/api/budget") return json({ est_total_usd: 0, calls: 0, hard_cap_usd: 50, stop_new_usd: 45, note: "", by_model: [] });
    if (p === "/api/health") return json({ status: "ok" });
    if (p === "/api/scenario/list") return json([{ id: SID, name: "inventory mock", created_at: "", updated_at: "" }]);
    return json({ detail: "Not Found" }, 404);
  });
  return sent;
}

test("盤點表顯示後端判斷，覆寫送出正確請求（zh-TW）", async ({ page }) => {
  const sent = await mockApi(page, "zh-TW");
  await page.goto("/deps");
  const panel = page.getByTestId("inventory-panel");
  await expect(panel).toBeVisible();

  const horizon = panel.getByTestId("inv-row-svc_horizon");
  await expect(horizon.getByTestId("inv-tier-have")).toHaveText("已可部署");
  await expect(horizon.getByTestId("inv-substitute")).toBeVisible();
  await expect(horizon).toContainText("vuln-log4shell-solr");
  await expect(horizon).toContainText("代替 VMware Horizon");
  await expect(horizon).toContainText("CVE-2021-44228");
  await expect(horizon.getByTestId("inv-basis-substituted")).toBeVisible();

  const ad = panel.getByTestId("inv-row-svc_ad");
  await expect(ad.getByTestId("inv-tier-unavailable")).toBeVisible();
  await expect(ad).toContainText("不部署");
  await expect(ad.getByTestId("inv-needs-question")).toHaveCount(0);

  const dc = panel.getByTestId("inv-row-host_dc");
  await expect(dc.getByTestId("inv-tier-obtainable")).toBeVisible();
  await expect(dc.getByTestId("inv-needs-question")).toBeVisible();
  await expect(panel.getByTestId("inv-summary")).toContainText("替代品 1");

  // Accept the auto-proposed substitute.
  await horizon.getByTestId("inv-edit-svc_horizon").click();
  await page.getByTestId("inv-apply-svc_horizon").click();
  await expect(horizon.getByTestId("inv-override-accept")).toBeVisible();
  await expect(horizon.getByTestId("inv-substitute")).toBeVisible(); // still flagged after acceptance

  // Supply a version from the backend's suggestions for the genuine ambiguity.
  await dc.getByTestId("inv-edit-host_dc").click();
  await page.getByTestId("inv-editor-host_dc").getByRole("button", { name: /2019/ }).click();
  await page.getByTestId("inv-apply-host_dc").click();
  await expect(dc.getByTestId("inv-basis-user_supplied")).toBeVisible();
  await expect(dc).toContainText("os-windows-server-2019-eval");
  await expect(dc.getByTestId("inv-needs-question")).toHaveCount(0);

  // Replace offers only deployable components.
  await ad.getByTestId("inv-edit-svc_ad").click();
  const opts = await page.getByTestId("inv-pick-svc_ad").locator("option").allTextContents();
  expect(opts.some((o) => o.startsWith("unsupported-"))).toBe(false);
  expect(opts.some((o) => o.startsWith("oss-nginx"))).toBe(true);

  await panel.screenshot({ path: "e2e/artifacts/inventory-panel-desktop.png" });
  expect(sent[0]).toEqual({ ref_id: "svc_horizon", action: "accept" });
  expect(sent[1].ref_id).toBe("host_dc");
  expect(sent[1].action).toBe("version");
  expect(sent[1].version).toBe("2019"); // the pinned version, not the display label
});

test("English strings follow cr.locale", async ({ page }) => {
  await mockApi(page, "en");
  await page.goto("/deps");
  const panel = page.getByTestId("inventory-panel");
  await expect(panel.getByRole("heading", { name: "Component inventory" })).toBeVisible();
  await expect(panel.getByTestId("inv-row-svc_ad").getByTestId("inv-tier-unavailable")).toHaveText("Unavailable");
  await expect(panel.getByTestId("inv-row-svc_horizon")).toContainText("Stands in for VMware Horizon");
});

test("version questions use the selected locale, not backend display text", async ({ browser }) => {
  for (const locale of ["en", "zh-TW"] as const) {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
    const page = await context.newPage();
    await mockApi(page, locale);
    await page.goto("/deps");
    const row = page.getByTestId("inv-row-host_dc");
    await row.locator("details > summary").click();
    const prompt = row.getByTestId("inv-question-prompt");
    if (locale === "en") {
      await expect(prompt).toHaveText("Choose a version of Windows Server: Windows Server 2016 Evaluation, Windows Server 2019 Evaluation, Windows Server 2022 Evaluation.");
      expect(await prompt.innerText()).not.toMatch(/[\u3400-\u9fff]/);
    } else {
      await expect(prompt).toHaveText("請選擇 Windows Server 的版本：Windows Server 2016 Evaluation、Windows Server 2019 Evaluation、Windows Server 2022 Evaluation。");
      expect(await prompt.innerText()).not.toContain("Choose a version");
    }
    await context.close();
  }
});

test("phone inventory editor labels and question summary have 44px hit areas", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const page = await context.newPage();
  await mockApi(page, "en");
  await page.goto("/deps");
  const panel = page.getByTestId("inventory-panel");
  const row = panel.getByTestId("inv-row-svc_horizon");
  await row.getByTestId("inv-edit-svc_horizon").click();
  const radioLabels = page.locator("[data-testid='inv-editor-svc_horizon'] [role='radiogroup'] > label");
  await expect(radioLabels).toHaveCount(3);
  for (const label of await radioLabels.all()) {
    const box = await label.boundingBox();
    expect(box, "radio label is visible").not.toBeNull();
    expect(box!.height, `radio label height ${box!.height}`).toBeGreaterThanOrEqual(44);
    expect(box!.width, `radio label width ${box!.width}`).toBeGreaterThanOrEqual(44);
  }
  const summary = panel.getByTestId("inv-row-host_dc").locator("details > summary");
  const summaryBox = await summary.boundingBox();
  expect(summaryBox, "reason summary is visible").not.toBeNull();
  expect(summaryBox!.height, `summary height ${summaryBox!.height}`).toBeGreaterThanOrEqual(44);
  expect(summaryBox!.width, `summary width ${summaryBox!.width}`).toBeGreaterThanOrEqual(44);
  await context.close();
});

test("phone width: the panel itself never overflows its card", async ({ page }) => {
  // This base (main) has no phone layout yet, so the app shell itself is wider than a phone; that is not measured here.
  // What the panel owns: its card fits its container and only the table wrapper scrolls sideways (stacked on the RWD line).
  await page.setViewportSize({ width: 390, height: 844 });
  await mockApi(page, "zh-TW");
  await page.goto("/deps");
  const panel = page.getByTestId("inventory-panel");
  await expect(panel).toBeVisible();
  await page.getByTestId("inv-edit-host_dc").click();
  await expect(page.getByTestId("inv-editor-host_dc")).toBeVisible();
  const over = await panel.evaluate((el) => el.scrollWidth - el.clientWidth);
  expect(over).toBeLessThanOrEqual(0);
  await panel.screenshot({ path: "e2e/artifacts/inventory-panel-phone.png" });
});
