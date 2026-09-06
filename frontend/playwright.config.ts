import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  use: { baseURL: process.env.MOSAIQUE_BASE_URL ?? "http://localhost:5173" },
  reporter: [["list"]],
});
