import { defineConfig } from "@playwright/test";
import { readdirSync, readFileSync, existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const appRoot = dirname(fileURLToPath(import.meta.url));
const featuresRoot = resolve(appRoot, "../../packages/features");
const featureProjects = readdirSync(featuresRoot).flatMap((name) => {
  const root = resolve(featuresRoot, name);
  const manifest = JSON.parse(
    readFileSync(resolve(root, "package.json"), "utf8"),
  );
  const tests = manifest.clinic?.webTests;
  return tests && existsSync(resolve(root, tests))
    ? [{ name, testDir: resolve(root, tests) }]
    : [];
});
export default defineConfig({
  projects: [
    { name: "platform", testDir: resolve(appRoot, "tests") },
    ...featureProjects,
  ],
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:3100",
    channel: process.env.CI ? undefined : "chrome",
    headless: true,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command:
        "../../.venv/bin/uvicorn tests.browser_server:app --app-dir ../api --host 127.0.0.1 --port 8001 --no-access-log",
      url: "http://127.0.0.1:8001/api/v1/health/live",
      reuseExistingServer: false,
      timeout: 60000,
    },
    {
      command: "pnpm dev --hostname 127.0.0.1 --port 3100",
      url: "http://127.0.0.1:3100",
      env: { BACKEND_INTERNAL_URL: "http://127.0.0.1:8001" },
      reuseExistingServer: false,
      timeout: 60000,
    },
  ],
  reporter: [["list"]],
});
