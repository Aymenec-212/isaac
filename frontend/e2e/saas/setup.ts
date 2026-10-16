import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";

export default function setup() {
  const result = execFileSync(
    "../backend/.venv/bin/python",
    ["tools/seed_saas_browser.py"],
    {
      cwd: "../backend",
      encoding: "utf8",
      env: { ...process.env, MOSAIQUE_ENVIRONMENT: "ci" },
    },
  );
  mkdirSync("e2e/.auth", { recursive: true });
  writeFileSync("e2e/.auth/saas.json", result, { mode: 0o600 });
}
