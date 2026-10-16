import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

export default defineConfig({
  ...base,
  globalSetup: "./e2e/prototype-setup.ts",
  workers: 1,
  webServer: [
    {
      command:
        "cd ../backend && MOSAIQUE_APPLICATION_MODE=prototype .venv/bin/python -m uvicorn mosaique.app.main:create_app --factory --host 127.0.0.1 --port 8000",
      url: "http://localhost:8000/livez",
      timeout: 30000,
    },
    {
      command:
        "VITE_APPLICATION_MODE=prototype npm run dev -- --host 127.0.0.1",
      url: "http://localhost:5173",
      timeout: 30000,
    },
  ],
});
