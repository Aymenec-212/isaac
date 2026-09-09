/**
 * Slice 6A item 2: what a person actually sees when a dependency is down.
 *
 * **Why this file exists.** `status.test.ts` has covered the banner's logic
 * since rev 15 and never once rendered it. On 2026-09-09 Aymen ran the app on
 * his M1 with the ASR runtime unavailable and found the gap by hand: the banner
 * correctly said **Service indisponible**, named `asr_runtime: unknown` in the
 * detail — and **Nouvelle réunion** was still clickable. The app told you
 * transcription was unavailable and then let you start a meeting that could not
 * transcribe. Unit tests could not see it because the two halves lived in
 * different components and only the sentence had a consumer.
 *
 * **What this stubs, and what it does not.** `/readyz` is intercepted in the
 * browser and answered with a canned payload. Everything else is the real app
 * against the real backend: the token gate, `GET /meetings`, the create call.
 * That split is deliberate and it bounds the claim — this spec asserts **the UI
 * contract given a readiness payload**, not that the backend correctly detects
 * a downed dependency. The detection half is already covered server-side by
 * `test_health_probes.py` (11) and `test_health_endpoints.py` (10), and forcing
 * a real MLX runtime to fail needs Apple silicon, which no sandbox has.
 *
 * Needs the app running: the backend on :8000 and the dev server on :5173.
 *
 *   MOSAIQUE_HOST_TOKEN="$(cd ../backend && uv run python -m mosaique.app.seed | awk '/^host_token:/{print $2}')" \
 *     npx playwright test e2e/degraded.spec.ts
 */
import { expect, test, type Page } from "@playwright/test";
import { chromiumLaunch, isolateFromCdns } from "./launch";

test.use({ launchOptions: chromiumLaunch });

test.beforeEach(async ({ context }) => isolateFromCdns(context));

const dep = (name: string, state: string, gates: boolean) => ({
  name,
  state,
  detail: `${name} is ${state}`,
  gates_readiness: gates,
});

const HEALTHY = [dep("database", "ok", true), dep("asr_runtime", "ok", true)];

/**
 * Answer `/readyz` with a fixed set of dependencies.
 *
 * 503 when something gating is unhappy, mirroring the real route — the client
 * reads the body either way, and serving 200 for a not-ready payload would be
 * testing a server this project does not have.
 */
async function stubReadiness(page: Page, dependencies: ReturnType<typeof dep>[]) {
  const notReady = dependencies.some((d) => d.gates_readiness && d.state !== "ok");
  await page.route("**/readyz", (route) =>
    route.fulfill({
      status: notReady ? 503 : 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: notReady ? "not_ready" : "ready",
        version: "0.1.0",
        summary: notReady ? "not ready" : "ready",
        dependencies,
      }),
    }),
  );
}

/** Land on the meeting list as an authenticated host. */
async function openList(page: Page) {
  const hostToken = process.env.MOSAIQUE_HOST_TOKEN;
  expect(
    hostToken,
    "set MOSAIQUE_HOST_TOKEN from `uv run python -m mosaique.app.seed`",
  ).toBeTruthy();

  await page.goto("/");
  await page.addInitScript(
    (token) => window.localStorage.setItem("mosaique.host_token", token),
    hostToken!,
  );
  await page.reload();
  await expect(page.getByLabel("Titre de la réunion")).toBeVisible();
}

test("the transcription engine being down blocks creating a meeting, not just warns", async ({
  page,
}) => {
  // The regression. Before this was wired, every assertion here passed except
  // the last two.
  await stubReadiness(page, [dep("database", "ok", true), dep("asr_runtime", "unknown", true)]);
  await openList(page);

  const banner = page.locator(".health-banner");
  await expect(banner).toBeVisible();
  await expect(banner).toContainText("Service indisponible");
  await expect(banner).toContainText("transcription");
  // A blocking banner is an alert, not a status: it interrupts a screen reader
  // rather than waiting to be read.
  await expect(banner).toHaveAttribute("role", "alert");

  // The detail names the dependency to go and restart.
  await page.getByRole("button", { name: "Détail technique" }).click();
  await expect(page.locator(".health-detail")).toContainText("asr_runtime");

  // The two assertions the manual run failed: typing a title does not make the
  // button live, and the page says why rather than leaving it mysteriously dead.
  await page.getByLabel("Titre de la réunion").fill("Réunion impossible");
  await expect(page.getByRole("button", { name: "Nouvelle réunion" })).toBeDisabled();
  await expect(page.locator("#creation-blocked")).toContainText("transcription");
});

test("the database being down blocks creating a meeting", async ({ page }) => {
  await stubReadiness(page, [
    dep("database", "unavailable", true),
    dep("asr_runtime", "ok", true),
  ]);
  await openList(page);

  await expect(page.locator(".health-banner")).toContainText("Service indisponible");
  await page.getByLabel("Titre de la réunion").fill("Réunion impossible");
  await expect(page.getByRole("button", { name: "Nouvelle réunion" })).toBeDisabled();
  await expect(page.locator("#creation-blocked")).toBeVisible();
});

test("only the summary provider being down warns but still allows a meeting", async ({ page }) => {
  // The other half of the manual run, and the half that already behaved. The
  // meeting, the transcript and persistence all work without the LLM, so
  // refusing here would deny a meeting that would have succeeded. This test
  // exists to stop the fix above from over-reaching into that case.
  await stubReadiness(page, [...HEALTHY, dep("llm_provider", "unavailable", false)]);
  await openList(page);

  const banner = page.locator(".health-banner");
  await expect(banner).toBeVisible();
  await expect(banner).toContainText("Service dégradé");
  await expect(banner).toContainText("compte rendu");
  await expect(banner).toHaveAttribute("role", "status");

  await page.getByLabel("Titre de la réunion").fill("Réunion sans compte rendu");
  await expect(page.getByRole("button", { name: "Nouvelle réunion" })).toBeEnabled();
  await expect(page.locator("#creation-blocked")).toHaveCount(0);
});

test("a server that does not answer readiness blocks creating a meeting", async ({ page }) => {
  await page.route("**/readyz", (route) => route.abort());
  await openList(page);

  const banner = page.locator(".health-banner");
  await expect(banner).toContainText("Service indisponible");
  await expect(banner).toContainText("injoignable");

  await page.getByLabel("Titre de la réunion").fill("Réunion impossible");
  await expect(page.getByRole("button", { name: "Nouvelle réunion" })).toBeDisabled();
});

test("a healthy server shows no banner and lets a meeting be created", async ({ page }) => {
  // The control. Without it, a fix that disabled the button unconditionally
  // would pass every test above.
  await stubReadiness(page, [...HEALTHY, dep("llm_provider", "ok", false)]);
  await openList(page);

  await expect(page.locator(".health-banner")).toHaveCount(0);
  await expect(page.locator("#creation-blocked")).toHaveCount(0);

  await page.getByLabel("Titre de la réunion").fill("Réunion possible");
  await expect(page.getByRole("button", { name: "Nouvelle réunion" })).toBeEnabled();
  await page.getByRole("button", { name: "Nouvelle réunion" }).click();
  await expect(page.locator(".notice a")).toBeVisible();
});

test("recovery re-enables creation without a reload", async ({ page }) => {
  // The banner polls every 5 s while unhappy, and the button reads the same
  // poll. Someone who restarts their model should not have to reload the page —
  // and if the two ever stopped sharing a source, this is where it would show.
  let healthy = false;
  await page.route("**/readyz", (route) => {
    const dependencies = healthy
      ? [...HEALTHY, dep("llm_provider", "ok", false)]
      : [dep("database", "ok", true), dep("asr_runtime", "unknown", true)];
    route.fulfill({
      status: healthy ? 200 : 503,
      contentType: "application/json",
      body: JSON.stringify({
        status: healthy ? "ready" : "not_ready",
        version: "0.1.0",
        summary: "",
        dependencies,
      }),
    });
  });

  await openList(page);
  await page.getByLabel("Titre de la réunion").fill("Réunion différée");
  await expect(page.getByRole("button", { name: "Nouvelle réunion" })).toBeDisabled();

  healthy = true;
  // pollIntervalMs is 5 s while unhappy; allow two cycles before giving up.
  await expect(page.locator(".health-banner")).toHaveCount(0, { timeout: 15_000 });
  await expect(page.getByRole("button", { name: "Nouvelle réunion" })).toBeEnabled();
});
