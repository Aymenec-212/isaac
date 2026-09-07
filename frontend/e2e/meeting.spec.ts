/**
 * Slice 1 exit gate, browser half: create -> join -> speak -> live transcript
 * -> end -> review page populated.
 *
 * Uses Chromium's fake microphone rather than a real device, so the run is
 * deterministic and headless. The backend must be running with the fake
 * recognizer and fake LLM provider (the default configuration).
 *
 * Needs the app running: the backend on :8000 and the dev server on :5173.
 *
 *   npx playwright install chromium   # or set MOSAIQUE_CHROMIUM_PATH
 *   MOSAIQUE_HOST_TOKEN="$(cd ../backend && uv run python -m mosaique.app.seed | tail -1)" \
 *     npx playwright test
 */
import { expect, test } from "@playwright/test";
import { chromiumLaunch, isolateFromCdns } from "./launch";

test.use({ launchOptions: chromiumLaunch, permissions: ["microphone"] });

test.beforeEach(async ({ context }) => isolateFromCdns(context));

test("a host can run a meeting end to end and read the review page", async ({ page }) => {
  const hostToken = process.env.MOSAIQUE_HOST_TOKEN;
  expect(hostToken, "set MOSAIQUE_HOST_TOKEN from `uv run python -m mosaique.app.seed`").toBeTruthy();

  await page.goto("/");
  await page.addInitScript(
    (token) => window.localStorage.setItem("mosaique.host_token", token),
    hostToken!,
  );
  await page.reload();

  // Create the meeting.
  await page.getByLabel("Titre de la réunion").fill("Point hebdomadaire");
  await page.getByRole("button", { name: "Nouvelle réunion" }).click();
  await expect(page.getByRole("button", { name: /Point hebdomadaire/ }).first()).toBeVisible();

  // Follow the invite link into the consent screen.
  const invite = page.locator(".notice a");
  await expect(invite).toBeVisible();
  await invite.click();
  await expect(page.getByText("Cette réunion est enregistrée et transcrite.")).toBeVisible();

  // Join grants the microphone and starts streaming.
  await page.getByLabel("Votre nom").fill("Amina");
  await page.getByRole("button", { name: /Rejoindre/ }).click();

  // Live transcript: interim text first, then a committed final segment.
  await expect(page.locator(".line-interim").first()).toBeVisible({ timeout: 20_000 });
  await expect(page.locator(".line-final").first()).toBeVisible({ timeout: 20_000 });
  await expect(page.locator(".line-final").first()).toContainText("Bonjour");

  // End the meeting and land on the review page.
  await page.getByRole("button", { name: "Terminer la réunion" }).click();
  await expect(page.getByRole("heading", { name: "Compte rendu" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Résumé" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("heading", { name: "Décisions" })).toBeVisible();
  await expect(page.locator(".transcript .line-final").first()).toBeVisible();

  // The transcript survives a reload: it is durable, not screen state.
  await page.reload();
  await expect(page.locator(".transcript .line-final").first()).toBeVisible();
});
