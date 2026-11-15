// Full GUI flow in a real browser, driven only by clicking the UI:
// upload CTI -> analysis -> supplement missing -> edit flow (confirm dependencies) -> dependencies -> topology
// -> IaC preview -> approve topology -> deploy -> validate -> report -> teardown.
//
// Honest by design: nothing is mocked. The deploy half is SKIPPED (not passed) when Docker is unavailable,
// and every step's outcome, browser console error and failed API call is written to e2e/artifacts/run-log.json.
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";
import { relayGets } from "./net-relay";
import zh from "../src/i18n/zh-TW";

// UI text comes from the zh-TW locale file (the app's default language), so selectors follow the locale keys
// instead of repeating the wording. Roles, labels and test ids stay the anchors.
type K = keyof typeof zh;
/** A message as the page renders it. Placeholders without a value stay as written. */
const L = (k: K, v: Record<string, string | number> = {}) => zh[k].replace(/\{(\w+)\}/g, (m, n: string) => (n in v ? String(v[n]) : m));
const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
/** Whole-text pattern for a message whose placeholders are numbers. */
const R = (k: K) => new RegExp(`^${esc(zh[k]).replace(/\\\{\w+\\\}/g, "\\d+")}$`);
/** The longest fixed part of a message whose variable values the test does not know. */
const P = (k: K) => zh[k].split(/\{\w+\}/).map((s) => s.trim()).sort((a, b) => b.length - a.length)[0];

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ARTIFACTS = path.join(HERE, "artifacts");
const SHOTS = path.join(ARTIFACTS, "screenshots");
const REPORT_FIXTURE = path.resolve(HERE, "../../../fixtures/sample-scenarios/demo-intrusion.md");

const LLM_TIMEOUT = 4 * 60_000; // real LLM analysis
const DEPLOY_TIMEOUT = 6 * 60_000; // real `docker compose up --build`

function dockerProblem(): string | null {
  try {
    execFileSync("docker", ["info", "--format", "{{.ServerVersion}}"], { stdio: "pipe", timeout: 20_000 });
    return null;
  } catch (e) {
    return e instanceof Error ? e.message.split("\n")[0] : String(e);
  }
}
const DOCKER_PROBLEM = dockerProblem();

interface StepLog { step: string; status: "passed" | "failed"; ms: number; screenshot?: string; error?: string; note?: string }
const log = {
  started_at: new Date().toISOString(),
  finished_at: "",
  base_url: "",
  docker: DOCKER_PROBLEM ? `unavailable: ${DOCKER_PROBLEM}` : "available",
  scenario_id: null as string | null,
  steps: [] as StepLog[],
  validation_levels: null as Record<string, string> | null,
  console_errors: [] as string[],
  failed_api_calls: [] as string[],
  notes: [] as string[],
};
const writeLog = () => {
  log.finished_at = new Date().toISOString();
  fs.mkdirSync(ARTIFACTS, { recursive: true });
  fs.writeFileSync(path.join(ARTIFACTS, "run-log.json"), JSON.stringify(log, null, 2));
};

// The app scrolls inside its main pane; for evidence screenshots only, let the page grow so nothing is cut off.
const SHOT_STYLE = "html, body, #root, .app-shell { height: auto !important; min-height: 100vh; overflow: visible !important; } .main:not(:has(> .workspace)) { overflow: visible !important; } .main:has(> .workspace) { height: calc(100vh - 106px); flex: none; }";

let page: Page;
let deployed = false;

/** Run one named step; always record it and take a screenshot, pass or fail. */
async function step(name: string, body: () => Promise<string | void>) {
  const t0 = Date.now();
  const file = `${String(log.steps.length + 1).padStart(2, "0")}-${name}.png`;
  await test.step(name, async () => {
    try {
      const note = await body();
      await page.screenshot({ path: path.join(SHOTS, file), fullPage: true, style: SHOT_STYLE, animations: "disabled" });
      log.steps.push({ step: name, status: "passed", ms: Date.now() - t0, screenshot: `screenshots/${file}`, ...(note ? { note } : {}) });
    } catch (e) {
      const failFile = file.replace(/\.png$/, "-FAILED.png");
      await page.screenshot({ path: path.join(SHOTS, failFile), fullPage: true, style: SHOT_STYLE }).catch(() => {});
      log.steps.push({ step: name, status: "failed", ms: Date.now() - t0, screenshot: `screenshots/${failFile}`, error: e instanceof Error ? e.message : String(e) });
      throw e;
    } finally {
      writeLog();
    }
  });
}

/** Plan hosts the backend deploys with a stand-in for the software the report names. */
async function substituteHosts(): Promise<any[]> {
  const ir = await (await page.request.get(`/api/scenario/${log.scenario_id}`)).json();
  return (ir.environment_plan?.hosts ?? []).filter((h: any) => h.substitute_for);
}

const nextStep = (stage: K) => page.getByRole("button", { name: L("next.step", { label: L(stage) }) });
/** A stage link in the workflow navigation. */
const stageLink = (stage: K) => page.getByRole("navigation", { name: L("shell.workflow") }).getByRole("link", { name: L(stage) });
/** The deploy page keeps state, records and health in a folded section. Open it before reading visible text there. */
const openDeployDetails = async () => { const d = page.locator("details.deploy-more", { has: page.getByTestId("deploy-records") }); if (!(await d.evaluate((el) => (el as HTMLDetailsElement).open))) await d.locator("summary").first().click(); };
const heading = (title: string) => page.getByRole("heading", { level: 1, name: title, exact: true });
const errorNotices = () => page.locator(".notice.err");

test.describe.configure({ mode: "serial" });

test.beforeAll(async ({ browser, baseURL }) => {
  fs.rmSync(SHOTS, { recursive: true, force: true });
  fs.mkdirSync(SHOTS, { recursive: true });
  log.base_url = baseURL ?? "";
  if (!/^https?:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/.test(baseURL ?? "")) throw new Error(`e2e only targets localhost, got ${baseURL}`);
  const context = await browser.newContext();
  await relayGets(context, baseURL); // see net-relay.ts: deploy/teardown changes host networks mid-run
  page = await context.newPage();
  page.on("console", (m) => { if (m.type() === "error") log.console_errors.push(m.text()); });
  page.on("pageerror", (e) => log.console_errors.push(`pageerror: ${e.message}`));
  page.on("response", (r) => {
    if (r.url().includes("/api/") && r.status() >= 400) log.failed_api_calls.push(`${r.status()} ${r.request().method()} ${new URL(r.url()).pathname}`);
  });
  // The deploy buttons ask for confirmation with window.confirm; the test user says yes.
  page.on("dialog", (d) => void d.accept());
});

test.afterAll(async ({ request }) => {
  // Safety net only: if the flow died after deploying, do not leave containers behind. Recorded so it is not mistaken for a UI teardown.
  if (deployed && log.scenario_id) {
    const r = await request.post(`/api/deploy/${log.scenario_id}/down`, { data: {} }).catch(() => null);
    log.notes.push(`safety-net teardown via API (the UI teardown did not complete): HTTP ${r?.status() ?? "no response"}`);
  }
  writeLog();
  await page?.context().close();
});

test("情資上傳到拓樸核准（上傳、分析、補充、流程、依賴、拓樸、IaC、核准）", async () => {
  await step("upload-report", async () => {
    await page.goto("/");
    await page.getByRole("button", { name: `＋ ${L("home.new")}` }).click();
    await expect(heading(L("imp.title"))).toBeVisible();
    await page.locator('input[type="file"]').setInputFiles(REPORT_FIXTURE);
    await expect(page.getByText(L("imp.loaded", { name: "demo-intrusion.md" }).split("{")[0])).toBeVisible();
    await expect(page.getByLabel(L("imp.kind"))).toHaveValue("markdown");
    await page.getByLabel(L("imp.name")).fill(`gui-e2e ${new Date().toISOString().slice(0, 19)}`);
  });

  await step("analyze", async () => {
    await page.getByRole("button", { name: L("imp.start") }).click();
    await expect(heading(L("an.title"))).toBeVisible({ timeout: LLM_TIMEOUT });
    log.scenario_id = await page.evaluate(() => localStorage.getItem("cr.scenario"));
    expect(log.scenario_id, "scenario id stored after analysis").toBeTruthy();
    const tab = page.getByRole("button", { name: R("an.tab.actions") });
    const actions = Number((await tab.innerText()).replace(/\D/g, ""));
    expect(actions, "analysis produced attack actions").toBeGreaterThan(0);
    await page.getByRole("button", { name: R("an.tab.relations") }).click();
    return `scenario ${log.scenario_id}, ${actions} actions`;
  });

  await step("supplement-missing", async () => {
    await nextStep("stage.missing").click();
    await expect(heading(L("ms.title"))).toBeVisible();
    const openTab = page.getByRole("button", { name: R("ms.tab.open") });
    const openBefore = Number((await openTab.innerText()).replace(/\D/g, ""));
    let note = `open items before: ${openBefore}`;
    if (openBefore > 0) {
      await page.getByRole("button", { name: L("ms.answer"), exact: true }).first().click();
      await page.getByPlaceholder(L("ms.res.user.ph")).fill("示範環境以開源的無害 HTTP 替身代表受害網站，版本不限。");
      await page.getByRole("button", { name: L("ms.send"), exact: true }).click();
      await expect(openTab).toHaveText(L("ms.tab.open", { n: openBefore - 1 }));
      note += `, after: ${openBefore - 1}`;
    }
    await page.getByPlaceholder(L("ms.free.ph")).fill("受害環境為單一對外網站與一台只允許內網連線的資料庫。");
    await page.getByRole("button", { name: L("ms.free.add") }).click();
    await expect(page.getByRole("heading", { name: L("ms.added") })).toBeVisible();
    await expect(errorNotices()).toHaveCount(0);
    return note;
  });

  await step("edit-flow-confirm-dependencies", async () => {
    await nextStep("stage.flow").click();
    await expect(page.getByRole("complementary", { name: L("fl.workbench") })).toBeVisible();
    await expect(page.locator(".react-flow__node").first()).toBeVisible();
    // Open one node in the inspector to prove the editor responds to clicks.
    await page.locator(".react-flow__node").first().click();
    await expect(page.getByRole("heading", { name: L("fl.n.action"), exact: true })).toBeVisible();
    const bar = page.getByTestId("dep-confirm-bar");
    await expect(bar, "the analysis must contain dependency relations to confirm").toBeVisible();
    const total = Number((await bar.innerText()).match(/\/\s*(\d+)/)?.[1]);
    await bar.getByRole("button", { name: L("fl.confirmAll") }).click();
    await expect(bar).toContainText(L("fl.depsConfirmed", { ok: total, total }));
    await page.getByPlaceholder(L("fl.notePh")).fill("e2e：確認依賴關係");
    await page.getByRole("button", { name: L("fl.save"), exact: true }).click();
    await expect(page.getByText(L("fl.saved"))).toBeVisible();
    // The confirmation must survive the round trip through the backend.
    await expect(bar).toContainText(L("fl.depsConfirmed", { ok: total, total }));
    return `${total} dependency relations confirmed and saved`;
  });

  await step("dependencies", async () => {
    await stageLink("stage.deps").click();
    await expect(heading(L("dep.title"))).toBeVisible();
    await page.getByRole("button", { name: new RegExp(`^(${esc(L("dep.run"))}|${esc(L("dep.rerun"))})$`) }).click();
    await expect(page.getByRole("button", { name: L("dep.rerun"), exact: true })).toBeEnabled({ timeout: 60_000 });
    await expect(errorNotices()).toHaveCount(0);
  });

  await step("topology-plan", async () => {
    await nextStep("stage.topology").click();
    await expect(heading(L("tp.title"))).toBeVisible();
    await page.getByRole("button", { name: new RegExp(`^(${esc(L("tp.plan"))}|${esc(L("tp.replan"))})$`) }).click();
    await expect(page.getByTestId("approval-state")).toHaveText(L("tp.notApproved"), { timeout: 60_000 });
    await expect(page.locator(".react-flow__node").first()).toBeVisible();
    // The approval gate lists both sides of the decision: what gets opened and what must stay shut.
    const opened = await page.getByTestId("open-paths").locator(".path").count();
    expect(opened, "planned connections are listed").toBeGreaterThan(0);
    await expect(page.getByTestId("blocked-paths")).toBeVisible();
    const blocked = await page.getByTestId("blocked-paths").locator(".path").count();
    await expect(errorNotices()).toHaveCount(0);
    // Whatever the backend marked as a stand-in is labelled as one on the canvas (count taken from the stored plan).
    const subs = await substituteHosts();
    await expect(page.getByTestId("host-substitute")).toHaveCount(subs.length);
    return `${opened} connections to open, ${blocked} must-stay-blocked paths shown, ${subs.length} substitute hosts labelled`;
  });

  await step("iac-preview", async () => {
    await nextStep("stage.iac").click();
    await expect(heading(L("iac.title"))).toBeVisible();
    await page.getByRole("button", { name: new RegExp(`^(${esc(L("iac.gen"))}|${esc(L("iac.regen"))})$`) }).click();
    await expect(page.locator("pre.code")).toContainText("services:", { timeout: 60_000 });
    // The check report is now a folded section; its summary line proves the report is shown.
    await expect(page.locator("details > summary", { hasText: L("iac.report") })).toBeVisible();
    await expect(errorNotices()).toHaveCount(0);
    const subs = await substituteHosts();
    await expect(page.getByTestId("substitute-card")).toHaveCount(subs.length ? 1 : 0);
    for (const h of subs) await expect(page.getByTestId("substitute-card")).toContainText(String(h.substitute_for));
  });

  await step("deploy-blocked-before-approval", async () => {
    await nextStep("stage.deploy").click();
    await expect(heading(L("dp.title"))).toBeVisible();
    await expect(page.getByText(L("dp.n.notApproved"))).toBeVisible();
    await expect(page.getByRole("button", { name: L("dp.act.up"), exact: true })).toBeDisabled();
  });

  await step("approve-topology", async () => {
    await page.getByRole("button", { name: L("dp.n.toTopology") }).click();
    await expect(heading(L("tp.title"))).toBeVisible();
    await page.getByLabel(L("tp.note"), { exact: true }).fill("e2e：核准本機隔離 PoC 拓樸");
    await page.getByRole("button", { name: L("tp.approve") }).click();
    await expect(heading(L("iac.title"))).toBeVisible();
    // Back on the topology page the approval is shown as recorded by the backend.
    await stageLink("stage.topology").click();
    await expect(page.getByTestId("approval-state")).toHaveText(L("tp.approved"));
    await expect(page.getByTestId("topology-approval")).toContainText("e2e：核准本機隔離 PoC 拓樸");
  });

  await step("home-progress", async () => {
    await stageLink("stage.home").click();
    await expect(page.getByTestId("rangeline")).toBeVisible();
    await expect(page.getByTestId("rangeline").locator(".stop.gate-stop")).toHaveAttribute("title", L("stageState.approved"));
    await page.waitForTimeout(1600); // let the hero's one-time line draw finish before the evidence screenshot
  });
});

test("部署、驗證、報告、清理（需要 Docker）", async () => {
  test.skip(!!DOCKER_PROBLEM, `Docker 不可用，部署段未執行：${DOCKER_PROBLEM}`);
  test.skip(!log.steps.some((s) => s.step === "approve-topology" && s.status === "passed"), "前半段未完成，沒有已核准的拓樸可部署");

  await step("deploy-up", async () => {
    await stageLink("stage.deploy").click();
    await expect(heading(L("dp.title"))).toBeVisible();
    const up = page.getByRole("button", { name: L("dp.act.up"), exact: true });
    await expect(up).toBeEnabled();
    deployed = true;
    await up.click();
    await expect(page.getByText(L("dp.busyUp"))).toBeVisible();
    await expect(page.getByText(L("dp.busyUp"))).toBeHidden({ timeout: DEPLOY_TIMEOUT });
    await openDeployDetails();
    await expect(errorNotices(), "deploy must not report an error").toHaveCount(0);
    await expect(page.getByTestId("deploy-state")).toHaveText("running");
    // Health is polled by the page; wait until every container reports healthy.
    await expect(page.getByTestId("health-state")).toHaveText("healthy", { timeout: 120_000 });
    await expect(page.getByTestId("deploy-records").locator("tbody tr").first()).toContainText(L("dp.act.up"));
    // The forwarder is shown as a platform component, never as a scenario host; ports shown are the ones Docker bound.
    const live = await (await page.request.get(`/api/deploy/${log.scenario_id}/status`)).json();
    const gateways = live.containers.filter((c: any) => c.service === "cr-gateway").length;
    await expect(page.getByTestId("container-table").locator('tr[data-kind="platform"]')).toHaveCount(gateways);
    await expect(page.getByTestId("container-table").locator('tr[data-kind="lab"]')).toHaveCount(live.containers.length - gateways);
    for (const p of live.containers.flatMap((c: any) => c.ports ?? [])) await expect(page.getByTestId("published-ports")).toContainText(`:${p.host_port}`);
    const names = execFileSync("docker", ["ps", "--filter", `name=cr-demo-${log.scenario_id}`, "--format", "{{.Names}}"]).toString().trim().split("\n").filter(Boolean);
    expect(names.length, "containers really exist in Docker").toBeGreaterThan(0);
    return `containers: ${names.join(", ")}`;
  });

  await step("validate", async () => {
    await nextStep("stage.report").click();
    await expect(heading(L("rp.title"))).toBeVisible();
    await page.getByRole("button", { name: new RegExp(`^(${esc(L("rp.run"))}|${esc(L("rp.rerun"))})$`) }).click();
    await expect(page.getByRole("button", { name: L("rp.rerun"), exact: true })).toBeEnabled({ timeout: 180_000 });
    await expect(errorNotices()).toHaveCount(0);
  });

  await step("report", async () => {
    const resp = await page.request.get(`/api/validate/${log.scenario_id}/report`);
    const report = await resp.json();
    log.validation_levels = report.levels;
    const subs = await substituteHosts();
    await expect(page.getByTestId("substitute-card")).toHaveCount(subs.length ? 1 : 0);
    // What the page shows must be what the backend reported, level by level.
    const label: Record<string, string> = { PASS: L("check.PASS"), FAIL: L("check.FAIL"), PARTIAL: L("check.PARTIAL"), NOT_TESTED: L("check.NOT_TESTED") };
    const pills = page.locator(".pill");
    for (const lv of ["env_build", "behavior_repro", "full_chain"]) {
      await expect(pills.filter({ hasText: label[report.levels[lv]] }).first()).toBeVisible();
    }
    await expect(page.getByRole("heading", { name: L("rp.fidelity"), exact: true })).toBeVisible();
    // The sidebar's stage marker reflects the verdict too (it used to stay blank after a successful run).
    await expect(stageLink("stage.report").locator(".state")).toHaveAttribute("title", new RegExp([L("stageState.allPass"), L("stageState.partial"), L("stageState.fail")].map(esc).join("|")));
    expect(report.levels.env_build, "environment build level").toBe("PASS");
    expect(Object.values(report.levels), "no validation level may be FAIL").not.toContain("FAIL");
    // Guard against a false PASS: this flow deploys the environment and runs only benign checks. No attack step is
    // reproduced, so the full chain cannot honestly be PASS. If it ever reports PASS, the verdict logic is wrong.
    expect(["PARTIAL", "NOT_TESTED"], `full_chain must not be PASS when no attack step is reproduced (got ${report.levels.full_chain})`).toContain(report.levels.full_chain);
    return `levels: ${JSON.stringify(report.levels)}`;
  });

  await step("teardown", async () => {
    await stageLink("stage.deploy").click();
    await expect(heading(L("dp.title"))).toBeVisible();
    await page.getByRole("button", { name: L("dp.act.down"), exact: true }).click();
    await expect(page.getByText(L("dp.busyDown"))).toBeHidden({ timeout: 180_000 });
    await expect(errorNotices()).toHaveCount(0);
    await openDeployDetails();
    await expect(page.getByText(L("dp.nothingRunning"))).toBeVisible();
    await expect(page.getByTestId("deploy-records").locator("tbody tr").first()).toContainText(L("dp.act.down"));
    const left = execFileSync("docker", ["ps", "-a", "--filter", `name=cr-demo-${log.scenario_id}`, "--format", "{{.Names}}"]).toString().trim();
    expect(left, "no containers left behind").toBe("");
    deployed = false;
  });
});
