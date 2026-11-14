import { defineConfig } from "@playwright/test";

// Local-only browser e2e. Both servers are loopback; nothing here talks to an external target.
const API_PORT = Number(process.env.CR_E2E_API_PORT ?? 8077);
// A dedicated port: 5173/5174 are often taken by other dev servers on this host, which may serve different code.
const WEB_PORT = Number(process.env.CR_E2E_WEB_PORT ?? 5184);
const API_URL = `http://127.0.0.1:${API_PORT}`;
const WEB_URL = `http://127.0.0.1:${WEB_PORT}`;

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./e2e/artifacts/test-results",
  timeout: 10 * 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [
    ["list"],
    ["json", { outputFile: "e2e/artifacts/results.json" }],
    ["html", { outputFolder: "e2e/artifacts/html-report", open: "never" }],
  ],
  use: {
    baseURL: WEB_URL,
    browserName: "chromium",
    viewport: { width: 1440, height: 900 },
    locale: "zh-TW",
    trace: "retain-on-failure",
    video: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command: "bash e2e/start-api.sh",
      url: `${API_URL}/api/health`,
      reuseExistingServer: true,
      timeout: 60_000,
      stdout: "ignore",
      stderr: "pipe",
    },
    {
      command: `npx vite --host 127.0.0.1 --port ${WEB_PORT} --strictPort`,
      url: WEB_URL,
      env: { CR_API_URL: API_URL },
      reuseExistingServer: true,
      timeout: 60_000,
    },
  ],
});
