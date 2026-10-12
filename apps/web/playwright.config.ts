import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests/voice",
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
