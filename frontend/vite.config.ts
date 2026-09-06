import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // Playwright owns e2e/; vitest must not try to run browser specs.
  test: { include: ["src/**/*.test.ts"], exclude: ["e2e/**"] },
  server: {
    port: 5173,
    // The API is same-origin in the browser, so no CORS preflight in dev.
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        ws: true,
        rewrite: (p) => p.replace(/^\/api/, ""),
      },
    },
  },
});
