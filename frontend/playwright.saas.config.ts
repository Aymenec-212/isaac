import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e/saas",
  globalSetup: "./e2e/saas/setup.ts",
  workers: 1,
  use: { baseURL: "http://localhost:5173", trace: "retain-on-failure" },
  reporter: [["list"]],
  webServer: [
    {
      command:
        "cd ../backend && MOSAIQUE_APPLICATION_MODE=enterprise .venv/bin/python -m uvicorn mosaique.app.main:create_app --factory --host 127.0.0.1 --port 8000",
      url: "http://localhost:8000/livez",
      timeout: 30000,
    },
    {
      command: "npm run dev -- --host 127.0.0.1",
      url: "http://localhost:5173",
      timeout: 30000,
    },
  ],
});
