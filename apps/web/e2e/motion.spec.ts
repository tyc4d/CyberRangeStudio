// Motion contract for the flow editor, checked in a real browser against a real scenario:
//  - a dependency line is drawn ONCE when it is created and is static afterwards (no looping "traffic" on any line);
//  - loading an existing scenario animates no lines at all;
//  - with prefers-reduced-motion the draw and the entrances are gone, while loading indicators still exist.
// Runs after full-flow.spec.ts (alphabetical order) and reuses the newest scenario; it never saves, so it changes nothing.
import { expect, test, type Page } from "@playwright/test";
import { relayGets } from "./net-relay";

test.beforeEach(async ({ context, baseURL }) => { await relayGets(context, baseURL); });

async function openFlow(page: Page): Promise<boolean> {
  const list = await (await page.request.get("/api/scenario/list")).json();
  if (!Array.isArray(list) || list.length === 0) return false;
  const newest = [...list].sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)))[0];
  await page.addInitScript((id) => localStorage.setItem("cr.scenario", id), newest.id);
  await page.goto("/flow");
  await expect(page.locator(".react-flow__node").first()).toBeVisible();
  return true;
}

/** Infinite animations currently running on graph lines or nodes. Spinners / progress bars are not graph elements. */
const loopingGraphAnimations = (page: Page) => page.evaluate(() =>
  document.getAnimations().filter((a) => {
    const t = (a.effect as KeyframeEffect | null)?.target as Element | null;
    return !!t?.closest(".react-flow") && a.effect?.getComputedTiming().iterations === Infinity;
  }).length);

/** Add a new action from the toolbar and pull a dependency line from an existing node onto it. */
async function connectNewDependency(page: Page) {
  await page.getByRole("toolbar", { name: "畫布工具" }).getByRole("button", { name: "依賴", exact: true }).click();
  await page.getByRole("button", { name: "＋ 新增行為" }).click();
  const before = await page.locator(".react-flow__edge").count();
  const source = page.locator(".react-flow__node").first().locator(".react-flow__handle.source");
  const target = page.locator(".react-flow__node").last().locator(".react-flow__handle.target");
  const s = (await source.boundingBox())!;
  const t = (await target.boundingBox())!;
  await page.mouse.move(s.x + s.width / 2, s.y + s.height / 2);
  await page.mouse.down();
  await page.mouse.move((s.x + t.x) / 2, (s.y + t.y) / 2, { steps: 6 });
  await page.mouse.move(t.x + t.width / 2, t.y + t.height / 2, { steps: 6 });
  await page.mouse.up();
  await expect(page.locator(".react-flow__edge")).toHaveCount(before + 1);
}

test("依賴連線只在建立時畫一次，之後靜止；既有連線載入時不動", async ({ page }) => {
  test.skip(!(await openFlow(page)), "後端沒有任何情境可用（先跑 full-flow）");

  // Existing lines: nothing marked fresh, nothing looping.
  await expect(page.locator(".react-flow__edge.fresh, .react-flow__edge.fresh-fade")).toHaveCount(0);
  expect(await loopingGraphAnimations(page)).toBe(0);

  await connectNewDependency(page);
  const line = page.locator(".react-flow__edge.fresh .react-flow__edge-path").first();
  await expect(line).toHaveAttribute("pathLength", "1");
  const iterations = await line.evaluate((el) => el.getAnimations().map((a) => a.effect?.getComputedTiming().iterations));
  expect(iterations, "the draw runs exactly once").toEqual([1]);
  // After it finishes the line is fully drawn and nothing on the canvas is still moving.
  await expect.poll(() => line.evaluate((el) => getComputedStyle(el).strokeDashoffset)).toBe("0px");
  await expect.poll(() => line.evaluate((el) => el.getAnimations().filter((a) => a.playState === "running").length)).toBe(0);
  expect(await loopingGraphAnimations(page)).toBe(0);

  // The new, unconfirmed dependency is reported by the design check and labelled as unconfirmed, not as done.
  await expect(page.getByTestId("validation-console")).toContainText("待處理");
  await expect(page.locator(".edge-label.hold").last()).toHaveText("依賴 · 未確認");
  await expect(page.getByText("有未儲存的修改").first()).toBeVisible();
});

test.describe("prefers-reduced-motion", () => {
  test.use({ reducedMotion: "reduce" });

  test("關閉位移與描繪動畫，但狀態仍可辨識", async ({ page }) => {
    test.skip(!(await openFlow(page)), "後端沒有任何情境可用（先跑 full-flow）");
    // Page entrance is a short fade, not a slide.
    // The workspace entrance is opacity-only by design; the context dock is the part that would otherwise slide.
    expect(await page.locator(".context-dock .swap").evaluate((el) => getComputedStyle(el).animationName)).toBe("fade-only");

    await connectNewDependency(page);
    const line = page.locator(".react-flow__edge.fresh .react-flow__edge-path").first();
    expect(await line.evaluate((el) => el.getAnimations().length), "no draw-on animation").toBe(0);
    expect(await line.evaluate((el) => getComputedStyle(el).strokeDashoffset)).toBe("0px");
    // The new node appears without travelling.
    expect(await page.locator(".gnode.fresh").evaluate((el) => getComputedStyle(el).animationName)).toBe("fade-only");

    // Home hero: the GSAP line draw is not registered at all under reduced motion.
    await page.getByRole("link", { name: "專案首頁" }).click();
    await expect(page.getByTestId("rangeline")).toBeVisible();
    const hero = await page.getByTestId("rangeline").locator(".rail-done").evaluate((el) => getComputedStyle(el).transform);
    expect(["none", "matrix(1, 0, 0, 1, 0, 0)"]).toContain(hero);
  });
});
