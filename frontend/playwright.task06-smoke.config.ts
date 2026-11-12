import { defineConfig } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontendDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(frontendDir, "..");
const python = process.env.PYTHON ?? "python3";
const baseURL = "http://127.0.0.1:5174";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "task06-platform.smoke.spec.ts",
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  timeout: 30_000,
  use: {
    baseURL,
    browserName: "chromium",
    headless: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command: `${python} ${path.join(repoRoot, "scripts", "task06_smoke_mock_api.py")}`,
      cwd: repoRoot,
      url: "http://127.0.0.1:8003/health",
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: "npm run dev -- --config vite.platform-smoke.config.ts",
      cwd: frontendDir,
      url: baseURL,
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
