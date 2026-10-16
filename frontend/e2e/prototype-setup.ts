import { execFileSync } from "node:child_process";

export default function setup() {
  const output = execFileSync(
    "../backend/.venv/bin/python",
    ["-m", "mosaique.app.seed"],
    {
      cwd: "../backend",
      encoding: "utf8",
      env: { ...process.env, MOSAIQUE_ENVIRONMENT: "ci" },
    },
  );
  const token = output.match(/^host_token:\s*(.+)$/m)?.[1];
  if (!token) throw new Error("Prototype fixture did not issue a test token");
  process.env.MOSAIQUE_HOST_TOKEN = token;
}
