import { defineConfig } from "@playwright/test";

const apiTarget = process.env.EKIP_API_PROXY_TARGET ?? "http://127.0.0.1:8001";
let targetUrl: URL;

try {
  targetUrl = new URL(apiTarget);
} catch {
  throw new Error(`Invalid EKIP_API_PROXY_TARGET: ${apiTarget}`);
}

if (targetUrl.port === "8000") {
  throw new Error("Playwright refuses production API port 8000. Set EKIP_API_PROXY_TARGET to http://127.0.0.1:8001.");
}

if (
  targetUrl.protocol !== "http:" ||
  targetUrl.port !== "8001" ||
  !["127.0.0.1", "localhost", "[::1]"].includes(targetUrl.hostname) ||
  targetUrl.pathname !== "/" ||
  targetUrl.search !== "" ||
  targetUrl.hash !== ""
) {
  throw new Error("Playwright requires EKIP_API_PROXY_TARGET to be a loopback URL on port 8001.");
}

const frontendUrl = "http://127.0.0.1:4173";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: frontendUrl,
    browserName: "chromium",
    headless: true,
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm run dev -- --host 127.0.0.1 --port 4173 --strictPort",
    url: frontendUrl,
    reuseExistingServer: false,
    timeout: 120_000,
    env: {
      EKIP_API_PROXY_TARGET: apiTarget,
    },
  },
});
