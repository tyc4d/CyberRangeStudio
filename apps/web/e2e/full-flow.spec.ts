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

const nextStep = (label: string) => page.getByRole("button", { name: `下一步：${label}` });
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
    await page.getByRole("button", { name: "＋ 新建情境" }).click();
    await expect(heading("情資匯入")).toBeVisible();
    await page.locator('input[type="file"]').setInputFiles(REPORT_FIXTURE);
    await expect(page.getByText(/已載入 demo-intrusion\.md/)).toBeVisible();
    await expect(page.getByLabel("輸入格式")).toHaveValue("markdown");
    await page.getByLabel("情境名稱（選填）").fill(`gui-e2e ${new Date().toISOString().slice(0, 19)}`);
  });

  await step("analyze", async () => {
    await page.getByRole("button", { name: "開始分析" }).click();
    await expect(heading("分析結果")).toBeVisible({ timeout: LLM_TIMEOUT });
    log.scenario_id = await page.evaluate(() => localStorage.getItem("cr.scenario"));
    expect(log.scenario_id, "scenario id stored after analysis").toBeTruthy();
    const tab = page.getByRole("button", { name: /^攻擊行為 \d+$/ });
    const actions = Number((await tab.innerText()).replace(/\D/g, ""));
    expect(actions, "analysis produced attack actions").toBeGreaterThan(0);
    await page.getByRole("button", { name: /^關係 \d+$/ }).click();
    return `scenario ${log.scenario_id}, ${actions} actions`;
  });

  await step("supplement-missing", async () => {
    await nextStep("缺失補充").click();
    await expect(heading("缺失補充")).toBeVisible();
    const openTab = page.getByRole("button", { name: /^待補充 \d+$/ });
    const openBefore = Number((await openTab.innerText()).replace(/\D/g, ""));
    let note = `open items before: ${openBefore}`;
    if (openBefore > 0) {
      await page.getByRole("button", { name: "補充", exact: true }).first().click();
      await page.getByPlaceholder(/填入實際資訊/).fill("示範環境以開源的無害 HTTP 替身代表受害網站，版本不限。");
      await page.getByRole("button", { name: "送出", exact: true }).click();
      await expect(openTab).toHaveText(`待補充 ${openBefore - 1}`);
      note += `, after: ${openBefore - 1}`;
    }
    await page.getByPlaceholder("輸入補充說明").fill("受害環境為單一對外網站與一台只允許內網連線的資料庫。");
    await page.getByRole("button", { name: "加入補充" }).click();
    await expect(page.getByRole("heading", { name: "已加入的補充" })).toBeVisible();
    await expect(errorNotices()).toHaveCount(0);
    return note;
  });

  await step("edit-flow-confirm-dependencies", async () => {
    await nextStep("攻擊流程").click();
    await expect(page.getByRole("complementary", { name: "設計工作台" })).toBeVisible();
    await expect(page.locator(".react-flow__node").first()).toBeVisible();
    // Open one node in the inspector to prove the editor responds to clicks.
    await page.locator(".react-flow__node").first().click();
    await expect(page.getByRole("heading", { name: "攻擊行為", exact: true })).toBeVisible();
    const bar = page.getByTestId("dep-confirm-bar");
    await expect(bar, "the analysis must contain dependency relations to confirm").toBeVisible();
    const total = Number((await bar.innerText()).match(/\/\s*(\d+)/)?.[1]);
    await bar.getByRole("button", { name: "確認全部依賴關係" }).click();
    await expect(bar).toContainText(`依賴關係已確認 ${total} / ${total}`);
    await page.getByPlaceholder("版本備註（選填）").fill("e2e：確認依賴關係");
    await page.getByRole("button", { name: "儲存為新版本", exact: true }).click();
    await expect(page.getByText("已儲存為新版本。")).toBeVisible();
    // The confirmation must survive the round trip through the backend.
    await expect(bar).toContainText(`依賴關係已確認 ${total} / ${total}`);
    return `${total} dependency relations confirmed and saved`;
  });

  await step("dependencies", async () => {
    await page.getByRole("link", { name: /軟體依賴/ }).first().click();
    await expect(heading("軟體依賴")).toBeVisible();
    await page.getByRole("button", { name: /執行依賴分析|重新分析依賴/ }).click();
    await expect(page.getByRole("button", { name: "重新分析依賴" })).toBeEnabled({ timeout: 60_000 });
    await expect(errorNotices()).toHaveCount(0);
  });

  await step("topology-plan", async () => {
    await nextStep("拓樸").click();
    await expect(heading("拓樸")).toBeVisible();
    await page.getByRole("button", { name: /產生拓樸規劃|重新規劃拓樸/ }).click();
    await expect(page.getByTestId("approval-state")).toHaveText("尚未核准", { timeout: 60_000 });
    await expect(page.locator(".react-flow__node").first()).toBeVisible();
    // The approval gate lists both sides of the decision: what gets opened and what must stay shut.
    const opened = await page.getByTestId("open-paths").locator(".path").count();
    expect(opened, "planned connections are listed").toBeGreaterThan(0);
    await expect(page.getByTestId("blocked-paths")).toBeVisible();
    const blocked = await page.getByTestId("blocked-paths").locator(".path").count();
    await expect(errorNotices()).toHaveCount(0);
    return `${opened} connections to open, ${blocked} must-stay-blocked paths shown`;
  });

  await step("iac-preview", async () => {
    await nextStep("IaC 預覽").click();
    await expect(heading("IaC 預覽")).toBeVisible();
    await page.getByRole("button", { name: /^(生成 IaC|重新生成)$/ }).click();
    await expect(page.locator("pre.code")).toContainText("services:", { timeout: 60_000 });
    await expect(page.getByRole("heading", { name: "可部署報告" })).toBeVisible();
    await expect(errorNotices()).toHaveCount(0);
  });

  await step("deploy-blocked-before-approval", async () => {
    await nextStep("部署管理").click();
    await expect(heading("部署管理")).toBeVisible();
    await expect(page.getByText("拓樸尚未核准，不能部署")).toBeVisible();
    await expect(page.getByRole("button", { name: "啟動（up）" })).toBeDisabled();
  });

  await step("approve-topology", async () => {
    await page.getByRole("button", { name: "前往拓樸頁" }).click();
    await expect(heading("拓樸")).toBeVisible();
    await page.getByLabel("核准備註").fill("e2e：核准本機隔離 PoC 拓樸");
    await page.getByRole("button", { name: "核准並繼續" }).click();
    await expect(heading("IaC 預覽")).toBeVisible();
    // Back on the topology page the approval is shown as recorded by the backend.
    await page.getByRole("link", { name: /拓樸/ }).first().click();
    await expect(page.getByTestId("approval-state")).toHaveText("已核准");
    await expect(page.getByTestId("topology-approval")).toContainText("e2e：核准本機隔離 PoC 拓樸");
  });

  await step("home-progress", async () => {
    await page.getByRole("link", { name: "專案首頁" }).click();
    await expect(page.getByTestId("rangeline")).toBeVisible();
    await expect(page.getByTestId("rangeline").locator(".stop.gate-stop")).toHaveAttribute("title", "拓樸已核准");
    await page.waitForTimeout(1600); // let the hero's one-time line draw finish before the evidence screenshot
  });
});

test("部署、驗證、報告、清理（需要 Docker）", async () => {
  test.skip(!!DOCKER_PROBLEM, `Docker 不可用，部署段未執行：${DOCKER_PROBLEM}`);
  test.skip(!log.steps.some((s) => s.step === "approve-topology" && s.status === "passed"), "前半段未完成，沒有已核准的拓樸可部署");

  await step("deploy-up", async () => {
    await page.getByRole("link", { name: /部署管理/ }).first().click();
    await expect(heading("部署管理")).toBeVisible();
    const up = page.getByRole("button", { name: "啟動（up）" });
    await expect(up).toBeEnabled();
    deployed = true;
    await up.click();
    await expect(page.getByText("啟動中，正在建立網路與容器…")).toBeVisible();
    await expect(page.getByText("啟動中，正在建立網路與容器…")).toBeHidden({ timeout: DEPLOY_TIMEOUT });
    await expect(errorNotices(), "deploy must not report an error").toHaveCount(0);
    await expect(page.getByTestId("deploy-state")).toHaveText("running");
    // Health is polled by the page; wait until every container reports healthy.
    await expect(page.getByTestId("health-state")).toHaveText("healthy", { timeout: 120_000 });
    await expect(page.getByTestId("deploy-records").locator("tbody tr").first()).toContainText("啟動");
    const names = execFileSync("docker", ["ps", "--filter", `name=cr-demo-${log.scenario_id}`, "--format", "{{.Names}}"]).toString().trim().split("\n").filter(Boolean);
    expect(names.length, "containers really exist in Docker").toBeGreaterThan(0);
    return `containers: ${names.join(", ")}`;
  });

  await step("validate", async () => {
    await nextStep("驗證報告").click();
    await expect(heading("驗證報告")).toBeVisible();
    await page.getByRole("button", { name: /^(執行驗證|重新驗證)$/ }).click();
    await expect(page.getByRole("button", { name: "重新驗證" })).toBeEnabled({ timeout: 180_000 });
    await expect(errorNotices()).toHaveCount(0);
  });

  await step("report", async () => {
    const resp = await page.request.get(`/api/validate/${log.scenario_id}/report`);
    const report = await resp.json();
    log.validation_levels = report.levels;
    // What the page shows must be what the backend reported, level by level.
    const label: Record<string, string> = { PASS: "通過", FAIL: "失敗", PARTIAL: "部分", NOT_TESTED: "未測" };
    const pills = page.locator(".pill");
    for (const lv of ["env_build", "behavior_repro", "full_chain"]) {
      await expect(pills.filter({ hasText: label[report.levels[lv]] }).first()).toBeVisible();
    }
    await expect(page.getByRole("heading", { name: "擬真度", exact: true })).toBeVisible();
    // The sidebar's stage marker reflects the verdict too (it used to stay blank after a successful run).
    await expect(page.locator(".stages a", { hasText: "驗證報告" }).locator(".state")).toHaveAttribute("title", /通過|未測|失敗/);
    expect(report.levels.env_build, "environment build level").toBe("PASS");
    expect(Object.values(report.levels), "no validation level may be FAIL").not.toContain("FAIL");
    // Guard against a false PASS: this flow deploys the environment and runs only benign checks. No attack step is
    // reproduced, so the full chain cannot honestly be PASS. If it ever reports PASS, the verdict logic is wrong.
    expect(["PARTIAL", "NOT_TESTED"], `full_chain must not be PASS when no attack step is reproduced (got ${report.levels.full_chain})`).toContain(report.levels.full_chain);
    return `levels: ${JSON.stringify(report.levels)}`;
  });

  await step("teardown", async () => {
    await page.getByRole("link", { name: /部署管理/ }).first().click();
    await expect(heading("部署管理")).toBeVisible();
    await page.getByRole("button", { name: "關閉（down）" }).click();
    await expect(page.getByText("關閉中，正在移除容器…")).toBeHidden({ timeout: 180_000 });
    await expect(errorNotices()).toHaveCount(0);
    await expect(page.getByText("目前沒有容器在執行。")).toBeVisible();
    await expect(page.getByTestId("deploy-records").locator("tbody tr").first()).toContainText("關閉");
    const left = execFileSync("docker", ["ps", "-a", "--filter", `name=cr-demo-${log.scenario_id}`, "--format", "{{.Names}}"]).toString().trim();
    expect(left, "no containers left behind").toBe("");
    deployed = false;
  });
});
