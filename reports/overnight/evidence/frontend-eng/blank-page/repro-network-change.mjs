// Reproduce: load the app repeatedly while a throwaway Docker network is created and removed (as deploy/teardown does).
// usage: node netchg.mjs <loads> <churn:0|1> [chromium args...]
import { chromium } from "/home/tyc4d/cr-project/apps/web/node_modules/playwright/index.mjs";
import { spawn, execFile } from "node:child_process";
const [loads, churn, relay, ...args] = process.argv.slice(2);
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const vite = spawn(process.execPath, ["node_modules/.bin/vite", "--host", "127.0.0.1", "--port", "5182", "--strictPort"],
  { env: { ...process.env, CR_VITE_CACHE_DIR: ".vite-cache", CR_API_URL: "http://127.0.0.1:8131" }, stdio: "ignore" });
await wait(4000);
let stop = false, cycles = 0;
const sh = (c, a) => new Promise((r) => execFile(c, a, () => r()));
const churner = (async () => { while (!stop && churn === "1") { await sh("docker", ["network", "create", "cr-fe-netprobe"]); await wait(150); await sh("docker", ["network", "rm", "cr-fe-netprobe"]); cycles++; await wait(150); } })();
const browser = await chromium.launch({ args });
let blank = 0, changed = 0;
for (let i = 0; i < Number(loads); i++) {
  const page = await browser.newPage(); let hit = false;
  if (relay === "1") await page.context().route((u) => u.origin === "http://127.0.0.1:5182", async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    try { await route.fulfill({ response: await route.fetch() }); } catch { await route.abort().catch(() => {}); }
  });
  page.on("requestfailed", (r) => { if ((r.failure()?.errorText ?? "").includes("ERR_NETWORK_CHANGED")) hit = true; });
  await page.goto("http://127.0.0.1:5182/").catch(() => { hit = true; });
  await page.locator(".app-shell").waitFor({ timeout: 3000 }).catch(() => { blank++; });
  if (hit) changed++;
  await page.close();
}
stop = true; await churner; await sh("docker", ["network", "rm", "cr-fe-netprobe"]);
console.log(JSON.stringify({ relay, churn, loads: Number(loads), networkCycles: cycles, loadsWithNetworkChanged: changed, blankPages: blank }));
await browser.close(); vite.kill(); process.exit(0);
