import type { Server } from "node:http";
import type { Socket } from "node:net";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

// 對外開放範圍：本機 + 區網 192.168.0.0/16。其他來源（Tailscale、Docker 橋接等）直接斷線。
const allowed = (addr = "") => {
  const ip = addr.replace(/^::ffff:/, "");
  return ip === "::1" || ip.startsWith("127.") || ip.startsWith("192.168.");
};

const guard = (http: Server | null) =>
  http?.on("connection", (socket: Socket) => {
    if (!allowed(socket.remoteAddress)) socket.destroy();
  });

const lanOnly = (): Plugin => ({
  name: "cr-lan-only",
  configureServer: (server) => void guard(server.httpServer as Server | null),
  configurePreviewServer: (server) => void guard(server.httpServer as Server | null),
});

export default defineConfig({
  plugins: [react(), lanOnly()],
  // Dependency pre-bundle cache. Default is node_modules/.vite; set CR_VITE_CACHE_DIR when node_modules is shared
  // (symlinked) between checkouts, otherwise two dev servers overwrite each other's bundles and pages load blank.
  ...(process.env.CR_VITE_CACHE_DIR ? { cacheDir: process.env.CR_VITE_CACHE_DIR } : {}),
  server: {
    host: "0.0.0.0",
    port: 5173,
    ...(process.env.CR_VITE_NO_HMR ? { hmr: false } : {}),
    proxy: { "/api": { target: process.env.CR_API_URL ?? "http://0.0.0.0:8077", changeOrigin: true } },
  },
  preview: { host: "0.0.0.0" },
});
