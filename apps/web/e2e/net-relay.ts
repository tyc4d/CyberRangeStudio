// Why this exists: Chromium cancels every in-flight request with net::ERR_NETWORK_CHANGED whenever the host's
// network interfaces change, and creating or removing a Docker network is such a change. Deploy/teardown in
// full-flow.spec.ts does exactly that, and other projects on the same host do it at any time. When it lands on a
// page load, the dev server's module requests are aborted, the app never boots and the page stays blank
// (reproduced: 7 of 60 loads blank while a throwaway Docker network was created/removed; 0 of 60 with this relay).
//
// The relay fetches GET requests to the app under test from the Playwright (Node) side and hands the real response
// to the page. Nothing is mocked or altered. Mutating requests (POST/PUT/DELETE) are left on the browser's own
// network stack so that a deploy or a save is still exercised exactly as a user's browser would send it.
import type { BrowserContext } from "@playwright/test";

export async function relayGets(context: BrowserContext, baseURL: string | undefined) {
  if (!baseURL) return;
  const origin = new URL(baseURL).origin;
  await context.route((url) => url.origin === origin, async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    let response;
    try {
      response = await route.fetch();
    } catch {
      // The page or test ended while the request was in flight.
      return route.abort().catch(() => {});
    }
    await route.fulfill({ response }).catch(() => {});
  });
}
