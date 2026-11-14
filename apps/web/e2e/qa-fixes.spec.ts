// Regression tests for QA round 1 findings, in a real browser against the real API.
// No LLM: the scenario is seeded from a stored analysis result (see seed-scenario.py); nothing is mocked.
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";
import { relayGets } from "./net-relay";
import { seedScenario } from "./seed";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "../../..");
const EVIDENCE = path.join(ROOT, "reports/overnight/evidence/frontend-eng");

// Diagnostics for every test: what the browser itself reported. Attached to the report when a test fails, so an
// intermittent failure (e.g. a page that never mounts) can be explained from evidence instead of a rerun.
const diag = new WeakMap<Page, string[]>();
test.beforeEach(async ({ page, context, baseURL }) => {
  await relayGets(context, baseURL);
  const lines: string[] = [];
  diag.set(page, lines);
  const at = () => new Date().toISOString().slice(11, 23);
  page.on("console", (m) => { if (m.type() === "error" || m.type() === "warning") lines.push(`${at()} console.${m.type()} ${m.text().slice(0, 300)}`); });
  page.on("pageerror", (e) => lines.push(`${at()} pageerror ${e.message.slice(0, 300)}`));
  page.on("requestfailed", (r) => lines.push(`${at()} requestfailed ${r.failure()?.errorText ?? ""} ${r.url().slice(0, 200)}`));
  page.on("response", (r) => { if (r.status() >= 400 && !r.url().includes("/api/")) lines.push(`${at()} http ${r.status()} ${r.url().slice(0, 200)}`); });
  page.on("framenavigated", (f) => { if (f === page.mainFrame()) lines.push(`${at()} navigated ${f.url()}`); });
});
test.afterEach(async ({ page }, info) => {
  if (info.status === info.expectedStatus) return;
  const lines = diag.get(page) ?? [];
  const mounted = await page.locator(".app-shell").count().catch(() => -1);
  const body = await page.evaluate(() => document.body?.innerHTML.length ?? -1).catch(() => -1);
  await info.attach("browser-diagnostics", { body: [`app-shell mounted: ${mounted}`, `body html length: ${body}`, ...lines].join("\n"), contentType: "text/plain" });
});

const seed = seedScenario;

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

test("補件會說明答案寫到哪裡，送出後顯示已寫入的欄位；目錄沒有的軟體明確標示", async ({ page }) => {
  const id = seed();
  await open(page, id, "/deps");
  await page.getByRole("button", { name: "執行依賴分析" }).click();
  await expect(page.getByRole("button", { name: "重新分析依賴" })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("no-component")).toContainText("Progress MOVEit Transfer");
  await expect(page.getByText("目錄無此元件")).toBeVisible();
  await shot(page, { path: path.join(EVIDENCE, "10-deps-no-component.png"), fullPage: true });

  await page.goto("/missing");
  await expect(heading(page, "缺失補充")).toBeVisible();
  const card = page.locator(".card", { hasText: "實際使用哪個作業系統" }).first();
  await card.getByRole("button", { name: "補充", exact: true }).click();
  await expect(card.getByTestId("write-target")).toContainText("的作業系統");
  await card.getByPlaceholder(/填入實際資訊/).fill("Windows Server 2019");
  await shot(page, { path: path.join(EVIDENCE, "11-missing-write-target.png") });
  await card.getByRole("button", { name: "送出", exact: true }).click();
  await expect(page.locator(".notice.err")).toHaveCount(0);
  await page.getByRole("button", { name: /^全部 \d+$/ }).click();
  await expect(page.getByTestId("applied-to").first()).toContainText("的作業系統");
  await shot(page, { path: path.join(EVIDENCE, "12-missing-applied-to.png") });
  // The page's claim matches what the backend stored.
  const ir = await (await page.request.get(`/api/scenario/${id}`)).json();
  const item = ir.missing_items.find((m: any) => m.applied_to?.field === "os");
  expect(item, "an item records applied_to os").toBeTruthy();
  expect(ir.hosts.find((h: any) => h.id === item.applied_to.id).os).toBe("Windows Server 2019");
});

test("拓樸：推定的入口主機有「待確認」標記與中文備註", async ({ page }) => {
  const id = seed();
  // Same edit the flow editor makes (target host of every action), sent to the real API to keep the test short.
  const ir = await (await page.request.get(`/api/scenario/${id}`)).json();
  for (const a of ir.actions) a.target_host_ref = ir.hosts[0].id;
  expect((await page.request.put(`/api/scenario/${id}`, { data: { ir, note: "e2e: set target hosts" } })).ok()).toBe(true);
  await open(page, id, "/deps");
  await page.getByRole("button", { name: /執行依賴分析|重新分析依賴/ }).click();
  await expect(page.getByText("依賴分析完成")).toBeVisible({ timeout: 60_000 });
  await page.goto("/topology");
  await page.getByRole("button", { name: "產生拓樸規劃" }).click();
  await expect(page.getByText("推定入口・待確認")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(/被放在對外網路，當作推定的入侵入口/)).toBeVisible();
  await shot(page, { path: path.join(EVIDENCE, "13-topology-inferred-entry.png"), fullPage: true });
});

test("讀取類 API 連線被中斷一次時自動重試，不顯示「無法連線到後端」；寫入類不重送", async ({ page }) => {
  const id = seed();
  // Fault injection only: the first read of the scenario list and of the deploy status is cut at the connection
  // level, like a request cancelled by a network change. Later attempts reach the real API untouched.
  const cut = { list: 0, status: 0, down: 0 };
  await page.route("**/api/scenario/list", (route) => (cut.list++ === 0 ? route.abort("connectionfailed") : route.fallback()));
  await page.route(`**/api/deploy/${id}/status`, (route) => (cut.status++ === 0 ? route.abort("connectionfailed") : route.fallback()));
  await open(page, id, "/");
  await expect(page.getByText(/e2e seeded \(no LLM\)/).first()).toBeVisible();
  expect(cut.list, "the list was requested again after the cut").toBeGreaterThanOrEqual(2);
  await expect(page.locator(".notice.warn", { hasText: "無法連線到後端" })).toHaveCount(0);

  await page.goto("/deploy");
  await expect(page.getByTestId("deploy-state")).toBeVisible();
  await expect(page.locator(".notice.warn", { hasText: "無法連線到後端" })).toHaveCount(0);

  // A write that fails at the connection level is reported, and sent exactly once.
  await page.route(`**/api/ingest/${id}/supplement`, (route) => { cut.down++; return route.abort("connectionfailed"); });
  await page.goto("/missing");
  await page.getByRole("button", { name: "補充", exact: true }).first().click();
  await page.getByRole("button", { name: "接受未知", exact: true }).click();
  await page.getByRole("button", { name: "送出", exact: true }).click();
  await expect(page.locator(".notice.warn", { hasText: "無法連線到後端" })).toBeVisible();
  await page.waitForTimeout(1200);
  expect(cut.down, "a POST is never re-sent automatically").toBe(1);
});

test("版本依據與平台閘道：替代版本在依賴／拓樸／IaC／報告都標示；部署頁把 cr-gateway 標成平台元件並列出實際對外埠", async ({ page }) => {
  test.setTimeout(6 * 60_000);
  let docker = true;
  try { execFileSync("docker", ["info", "--format", "{{.ServerVersion}}"], { stdio: "pipe", timeout: 20_000 }); } catch { docker = false; }
  const id = seed();
  // Test data, written through the real API (the same edits the flow editor and a supplement make): the report's
  // software becomes a named product the catalogue has in a different release, bound to the host.
  const ir0 = await (await page.request.get(`/api/scenario/${id}`)).json();
  for (const a of ir0.actions) a.target_host_ref = ir0.hosts[0].id;
  Object.assign(ir0.services[0], { name: "NGINX", version: "1.18.0", host_ref: ir0.hosts[0].id, port: 80, protocol: "tcp" });
  expect((await page.request.put(`/api/scenario/${id}`, { data: { ir: ir0, note: "e2e: named product with a stated version" } })).ok()).toBe(true);
  page.on("dialog", (d) => void d.accept());

  await open(page, id, "/deps");
  await page.getByRole("button", { name: /執行依賴分析|重新分析依賴/ }).click();
  await expect(page.getByText("依賴分析完成")).toBeVisible({ timeout: 60_000 });
  const ir = await (await page.request.get(`/api/scenario/${id}`)).json();
  const svc = ir.services.find((s: any) => s.version_basis);
  expect(svc.version_basis, "backend classifies the deployed release").toBe("substituted");
  const row = page.locator("tr", { has: page.getByTestId("version-basis-substituted") }).first();
  await expect(row).toContainText("NGINX");
  await expect(row.getByTestId("version-basis-substituted")).toBeVisible();
  await expect(row).toContainText(svc.deployed_version);
  await expect(row).toContainText("1.18.0");
  await shot(page, { path: path.join(EVIDENCE, "15-deps-version-basis.png"), fullPage: true });

  await page.goto("/topology");
  await page.getByRole("button", { name: "產生拓樸規劃" }).click();
  await expect(page.locator(".gnode.host").getByTestId("version-basis-substituted")).toBeVisible({ timeout: 60_000 });
  await shot(page, { path: path.join(EVIDENCE, "16-topology-version-basis.png"), fullPage: true });
  await page.getByRole("button", { name: "核准並繼續" }).click();

  await expect(heading(page, "IaC 預覽")).toBeVisible();
  await page.getByRole("button", { name: "生成 IaC" }).click();
  const card = page.getByTestId("version-basis-card");
  await expect(card).toBeVisible({ timeout: 60_000 });
  await expect(card).toContainText("1 項不是原文事實");
  await expect(card).toContainText("1.18.0");
  await expect(card).toContainText(svc.deployed_version);
  await shot(page, { path: path.join(EVIDENCE, "17-iac-version-basis.png"), fullPage: true });

  test.skip(!docker, "Docker 不可用：部署頁與報告頁的部分未執行（不是通過）");
  try {
    await page.goto("/deploy");
    await page.getByRole("button", { name: "啟動（up）" }).click();
    await expect(page.getByTestId("deploy-state")).toHaveText("running", { timeout: 4 * 60_000 });
    const table = page.getByTestId("container-table");
    await expect(table.locator('tr[data-kind="platform"]')).toHaveCount(1);
    await expect(table.locator('tr[data-kind="platform"]')).toContainText("平台元件");
    await expect(table.locator('tr[data-kind="platform"]')).toContainText("cr-gateway");
    await expect(table.locator('tr[data-kind="lab"]')).toHaveCount(2);
    // The port shown is the one Docker really bound, and it answers.
    const status = await (await page.request.get(`/api/deploy/${id}/status`)).json();
    const bound = status.containers.flatMap((c: any) => c.ports ?? []).map((p: any) => Number(p.host_port));
    expect(bound.length).toBe(1);
    const ports = page.getByTestId("published-ports");
    await expect(ports).toContainText(`127.0.0.1:${bound[0]}`);
    await expect(ports).toContainText("只有這台主機本身連得到");
    const http = await page.request.get(`http://127.0.0.1:${bound[0]}/`);
    expect(http.status(), "the published port reaches the lab web server through the gateway").toBe(200);
    await shot(page, { path: path.join(EVIDENCE, "18-deploy-gateway-and-ports.png"), fullPage: true });

    await page.goto("/report");
    await page.getByRole("button", { name: /執行驗證|重新驗證/ }).click();
    const rcard = page.getByTestId("version-basis-card");
    await expect(rcard).toBeVisible({ timeout: 3 * 60_000 });
    await expect(rcard).toContainText("不能據此說環境重現了原事件的版本");
    await shot(page, { path: path.join(EVIDENCE, "19-report-version-basis.png"), fullPage: true });
  } finally {
    // Always remove what this test deployed.
    await page.request.post(`/api/deploy/${id}/down`, { data: {} }).catch(() => null);
  }
  const left = execFileSync("docker", ["ps", "-a", "--filter", `label=com.docker.compose.project=cr-demo-${id}`, "--format", "{{.Names}}"], { encoding: "utf8" }).trim();
  expect(left, "no containers left behind").toBe("");
});
