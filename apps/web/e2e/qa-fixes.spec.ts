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

/** Evidence screenshot after the page's entry animation has settled. */
async function shot(page: Page, opts: { path: string; fullPage?: boolean }) {
  await page.waitForTimeout(900);
  await page.screenshot(opts);
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
  await shot(page, { path: path.join(EVIDENCE, "01-accept-unknown-blank-note.png") });
  await send.click();
  // The form closes only after the API accepted the answer. The open count is not asserted to drop by one:
  // the backend may add a follow-up question in the same response (it does after the supplement write-back change).
  await expect(send).toHaveCount(0);
  await expect(page.locator(".notice.err")).toHaveCount(0);
  expect(failed.filter((f) => f.includes("/supplement"))).toEqual([]);
  expect(before).toBeGreaterThan(0);

  // The stored record says honestly that no note was given, and the item is marked accepted-unknown, not answered.
  const ir = await (await page.request.get(`/api/scenario/${id}`)).json();
  const resolved = ir.missing_items.filter((m: any) => m.status === "accepted_unknown");
  expect(resolved.length).toBeGreaterThan(0);
  // The page agrees with the stored state: every still-open item is counted, the accepted one is not.
  await expect(openTab).toHaveText(`待補充 ${ir.missing_items.filter((m: any) => m.status === "open").length}`);
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
  await shot(page, { path: path.join(EVIDENCE, "02-deploy-blocked-no-iac.png") });
  await page.getByRole("button", { name: "前往 IaC 預覽" }).click();
  await expect(heading(page, "IaC 預覽")).toBeVisible();
  // No up attempt was made, so nothing may be in the audit trail.
  const rec = await (await page.request.get(`/api/deploy/${id}/records`)).json();
  expect(rec.records ?? []).toEqual([]);
});

test("導覽列的缺失數與缺失頁「待補充」數一致", async ({ page }) => {
  const id = seed();
  await open(page, id, "/missing");
  await expect(heading(page, "缺失補充")).toBeVisible();
  const tab = Number((await page.getByRole("button", { name: /^待補充 \d+$/ }).innerText()).replace(/\D/g, ""));
  const nav = page.locator("nav a, .stages a, a").filter({ hasText: "缺失補充" }).first();
  expect(Number((await nav.innerText()).replace(/\D/g, "").slice(1) || NaN), "nav count (after the step number)").toBe(tab);
});

test("首頁「＋ 新建情境」在已選情境時也開啟空白匯入表單", async ({ page }) => {
  const id = seed();
  await open(page, id, "/");
  await page.getByRole("button", { name: "＋ 新建情境" }).click();
  await expect(heading(page, "情資匯入")).toBeVisible();
  await expect(page.getByRole("button", { name: "開始分析" })).toBeVisible();
  await expect(page.getByRole("button", { name: "匯入新報告" })).toHaveCount(0);
});

test("參照不一致的情境：依賴→拓樸→IaC→部署→驗證 每一站都說明狀態與下一步，且不顯示成可部署", async ({ page }) => {
  const id = seed();
  await open(page, id, "/deps");
  await expect(heading(page, "軟體依賴")).toBeVisible();
  await expect(page.getByText("尚未執行依賴分析")).toBeVisible();
  await page.getByRole("button", { name: "執行依賴分析" }).click();
  await expect(page.getByRole("button", { name: "重新分析依賴" })).toBeVisible({ timeout: 60_000 });
  const issues = page.getByTestId("ref-issues");
  await expect(issues).toContainText("沒有歸屬任何主機");
  await expect(issues).toContainText("目前的限制");
  await shot(page, { path: path.join(EVIDENCE, "03-deps-ref-issues.png"), fullPage: true });

  await page.goto("/topology");
  await page.getByRole("button", { name: "產生拓樸規劃" }).click();
  await expect(page.getByText("這份規劃沒有任何會開通的連線")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("ref-issues")).toBeVisible();
  await shot(page, { path: path.join(EVIDENCE, "04-topology-no-connections.png"), fullPage: true });
  await page.getByRole("button", { name: "核准並繼續" }).click();

  await expect(heading(page, "IaC 預覽")).toBeVisible();
  await page.getByRole("button", { name: "生成 IaC" }).click();
  const failure = page.getByTestId("iac-failure");
  await expect(failure).toBeVisible({ timeout: 60_000 });
  await expect(failure).toContainText("沒有產生任何 compose 檔");
  await expect(page.getByText("可部署", { exact: true })).toHaveCount(1); // only the table header, no "可部署" verdict
  await shot(page, { path: path.join(EVIDENCE, "05-iac-failure-readable.png"), fullPage: true });

  await page.goto("/deploy");
  await expect(page.getByText("尚未生成 IaC，不能部署")).toBeVisible();
  await expect(page.getByRole("button", { name: "啟動（up）" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "關閉（down）" })).toBeDisabled();

  await page.goto("/report");
  await expect(page.getByText("環境尚未部署，不能執行驗證")).toBeVisible();
  await expect(page.getByRole("button", { name: "執行驗證" })).toBeDisabled();
  await shot(page, { path: path.join(EVIDENCE, "06-report-not-deployed.png"), fullPage: true });
  const rec = await (await page.request.get(`/api/deploy/${id}/records`)).json();
  expect(rec.records ?? []).toEqual([]);
});

test("部署紀錄：失敗的嘗試顯示原因，不是「—」", async ({ page }) => {
  const id = seed();
  // A real refused/failed attempt, made against the real API (the UI now disables this button in this state).
  const r = await page.request.post(`/api/deploy/${id}/down`, { data: {} });
  expect(r.status(), "down without a compose file fails").toBeGreaterThanOrEqual(400);
  await open(page, id, "/deploy");
  const row = page.getByTestId("deploy-records").locator("tbody tr").first();
  await expect(row).toContainText("關閉");
  await expect(row).toContainText("failed");
  await expect(row.locator("td").last()).not.toHaveText("—");
  await shot(page, { path: path.join(EVIDENCE, "07-deploy-record-reason.png"), fullPage: true });
});

test("攻擊流程：1280×720 展開設計檢查（截圖供人工檢視重疊）", async ({ page }) => {
  const id = seed();
  await page.setViewportSize({ width: 1280, height: 720 });
  await open(page, id, "/flow");
  await expect(page.locator(".react-flow")).toBeVisible();
  await page.getByText("隨畫布即時計算").click();
  await shot(page, { path: path.join(EVIDENCE, "08-flow-1280x720.png") });
});

test("換頁後從新頁面頂端開始，不沿用前一頁的捲動位置", async ({ page }) => {
  const id = seed();
  await open(page, id, "/analysis");
  await expect(heading(page, "分析結果")).toBeVisible();
  const main = page.locator("main.main");
  await main.evaluate((el) => el.scrollTo({ top: el.scrollHeight }));
  await page.getByRole("button", { name: "下一步：缺失補充" }).click();
  await expect(heading(page, "缺失補充")).toBeVisible();
  expect(await main.evaluate((el) => el.scrollTop)).toBe(0);
  await expect(heading(page, "缺失補充")).toBeInViewport();
});

test("缺失補充：嚴重度沿用後端的 major；沒有原文依據的佔位主機不標成「原文已知」", async ({ page }) => {
  const id = seed();
  const ir = await (await page.request.get(`/api/scenario/${id}`)).json();
  // Preconditions read from the seeded data, so the test fails loudly if the fixture changes.
  expect(ir.missing_items.every((m: any) => m.severity === "major")).toBe(true);
  expect(ir.missing_items[0].known[0].epistemic_status).toBe("insufficient");
  await open(page, id, "/missing");
  await expect(heading(page, "缺失補充")).toBeVisible();
  const cards = page.getByTestId("known-vs-decide");
  await expect(cards.first()).toContainText("系統推定（原文未證實）");
  await expect(page.getByText("原文已知：")).toHaveCount(0);
  await expect(page.getByText("次要", { exact: true })).toHaveCount(0);
  await expect(page.getByText("重要", { exact: true }).first()).toBeVisible();
  await shot(page, { path: path.join(EVIDENCE, "09-missing-severity-and-source-labels.png") });
});
