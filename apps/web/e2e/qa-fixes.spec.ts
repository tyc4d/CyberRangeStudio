// Regression tests for QA round 1 findings, in a real browser against the real API.
// No LLM: the scenario is seeded from a stored analysis result (see seed-scenario.py); nothing is mocked.
import { execFileSync } from "node:child_process";
import crypto from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "../../..");
const EVIDENCE = path.join(ROOT, "reports/overnight/evidence/frontend-eng");
const PYTHON = path.join(process.env.CR_VENV ?? path.join(ROOT, ".venv"), "bin", "python");

function seed(): string {
  const id = `scn_e2e${crypto.randomBytes(4).toString("hex")}`;
  execFileSync(PYTHON, [path.join(HERE, "seed-scenario.py"), id], { stdio: "pipe", timeout: 30_000 });
  return id;
}

async function open(page: Page, id: string, route: string) {
  await page.addInitScript((sid) => localStorage.setItem("cr.scenario", sid), id);
  await page.goto(route);
}
const heading = (page: Page, title: string) => page.getByRole("heading", { level: 1, name: title, exact: true });

test("缺失補充：「接受未知」備註留白也能送出，且不會出現 422", async ({ page }) => {
  const id = seed();
  const failed: string[] = [];
  page.on("response", (r) => { if (r.url().includes("/api/") && r.status() >= 400) failed.push(`${r.status()} ${new URL(r.url()).pathname}`); });
  await open(page, id, "/missing");
  await expect(heading(page, "缺失補充")).toBeVisible();
  const openTab = page.getByRole("button", { name: /^待補充 \d+$/ });
  const before = Number((await openTab.innerText()).replace(/\D/g, ""));
  expect(before).toBeGreaterThan(0);

  await page.getByRole("button", { name: "補充", exact: true }).first().click();
  const send = page.getByRole("button", { name: "送出", exact: true });
  // Default mode needs text: the button is disabled and the form says why.
  await expect(send).toBeDisabled();
  await expect(page.getByTestId("resolution-hint")).toContainText("必填");

  await page.getByRole("button", { name: "接受未知", exact: true }).click();
  await expect(page.getByTestId("resolution-hint")).toContainText("備註選填");
  await expect(send).toBeEnabled();
  await page.screenshot({ path: path.join(EVIDENCE, "01-accept-unknown-blank-note.png") });
  await send.click();
  await expect(openTab).toHaveText(`待補充 ${before - 1}`);
  await expect(page.locator(".notice.err")).toHaveCount(0);
  expect(failed.filter((f) => f.includes("/supplement"))).toEqual([]);

  // The stored record says honestly that no note was given, and the item is marked accepted-unknown, not answered.
  const ir = await (await page.request.get(`/api/scenario/${id}`)).json();
  const resolved = ir.missing_items.filter((m: any) => m.status === "accepted_unknown");
  expect(resolved.length).toBeGreaterThan(0);
  for (const m of resolved) expect(m.resolution).toBe("接受未知（使用者未填寫備註）");
});

// Contract probe only: it pins the backend rule the UI adapts to. The plain-language 422 notice itself has no e2e
// coverage, because the UI no longer has a path that sends an empty text.
test("後端契約：補充的 text 留白會回 422（前端因此代填備註）", async ({ page }) => {
  const id = seed();
  await open(page, id, "/missing");
  await expect(heading(page, "缺失補充")).toBeVisible();
  // Whitespace-only free text passes no client check on purpose here: send it straight to the real API.
  const status = await page.evaluate(async (sid) => (await fetch(`/api/ingest/${sid}/supplement`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: "" }) })).status, id);
  expect(status).toBe(422); // documents the backend contract the UI adapts to
});

test("部署管理：拓樸已核准但尚未生成 IaC 時，「啟動」停用並說明下一步", async ({ page }) => {
  const id = seed();
  await open(page, id, "/topology");
  await expect(heading(page, "拓樸")).toBeVisible();
  await page.getByRole("button", { name: /產生拓樸規劃|重新規劃拓樸/ }).first().click();
  const approve = page.getByRole("button", { name: /核准/ }).first();
  await expect(approve).toBeEnabled({ timeout: 60_000 });
  await approve.click();

  await page.goto("/deploy");
  await expect(heading(page, "部署管理")).toBeVisible();
  await expect(page.getByText("尚未生成 IaC，不能部署")).toBeVisible();
  const up = page.getByRole("button", { name: "啟動（up）" });
  await expect(up).toBeDisabled();
  await expect(up).toHaveAttribute("title", /IaC/);
  await page.screenshot({ path: path.join(EVIDENCE, "02-deploy-blocked-no-iac.png") });
  await page.getByRole("button", { name: "前往 IaC 預覽" }).click();
  await expect(heading(page, "IaC 預覽")).toBeVisible();
  // No up attempt was made, so nothing may be in the audit trail.
  const rec = await (await page.request.get(`/api/deploy/${id}/records`)).json();
  expect(rec.records ?? []).toEqual([]);
});
