/**
 * Slice 6R item 7 in a browser: fixing a word, and what happens to the summary.
 *
 * The backend suite proves the storage contract — `text` and `words` keep what
 * the ASR produced, the correction lands beside them, `transcript_version`
 * moves. What only a browser can show is the loop a person actually walks:
 * click a segment, change it, see the transcript update, see the summary
 * declare itself out of date, press one button, see it catch up.
 *
 * **Regeneration is a button, never automatic** (Aymen's call). Five
 * corrections should cost one LLM call, so the third test here asserts the
 * absence of something: editing does *not* quietly re-summarize.
 *
 * Needs the app running: the backend on :8000 and the dev server on :5173.
 *
 *   MOSAIQUE_HOST_TOKEN="$(cd ../backend && uv run python -m mosaique.app.seed | awk '/^host_token:/{print $2}')" \
 *     npx playwright test e2e/corrections.spec.ts
 */
import { expect, test, type Page } from "@playwright/test";
import { chromiumLaunch, isolateFromCdns } from "./launch";

test.use({ launchOptions: chromiumLaunch, permissions: ["microphone"] });

test.beforeEach(async ({ context }) => isolateFromCdns(context));

/** Run one real meeting through to a review page with a summary on it. */
async function meetingWithSummary(page: Page) {
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

  await page.getByLabel("Titre de la réunion").fill("Réunion à corriger");
  await page.getByRole("button", { name: "Nouvelle réunion" }).click();
  await page.locator(".notice a").click();
  await page.getByLabel("Votre nom").fill("Amina");
  await page.getByRole("button", { name: /Rejoindre/ }).click();

  await expect(page.locator(".line-final").first()).toBeVisible({ timeout: 20_000 });
  await page.waitForTimeout(3_000);

  await page.getByRole("button", { name: "Terminer la réunion" }).click();
  await expect(page.getByRole("heading", { name: "Compte rendu" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Résumé" })).toBeVisible({ timeout: 30_000 });
  await expect(page.locator(".transcript .seg").first()).toBeVisible();
}

test("correcting a segment shows the new text and keeps the original available", async ({
  page,
}) => {
  await meetingWithSummary(page);

  const segment = page.locator(".transcript .seg").first();
  const before = ((await segment.innerText()) ?? "").replace("✎", "").trim();
  expect(before.length).toBeGreaterThan(0);

  await segment.getByRole("button", { name: /Corriger/ }).click();

  const editor = page.locator(".seg-editor");
  await expect(editor).toBeVisible();
  // The box opens pre-filled: correcting a word should not mean retyping a
  // sentence.
  await expect(editor.getByLabel("Texte du segment")).toHaveValue(before);

  await editor.getByLabel("Texte du segment").fill("Le budget du trimestre est validé.");
  await editor.getByRole("button", { name: "Enregistrer" }).click();

  await expect(editor).toBeHidden();
  const corrected = page.locator('.transcript .seg[data-segment-id]').first();
  await expect(corrected).toContainText("Le budget du trimestre est validé.");
  // Marked as edited, and the model's own words reachable rather than erased —
  // the visible half of Q9's "additive only".
  await expect(corrected).toHaveClass(/seg-corrected/);
  await expect(corrected).toHaveAttribute("title", new RegExp("Texte d'origine"));
});

test("the summary declares itself out of date and one button brings it back", async ({ page }) => {
  await meetingWithSummary(page);

  // Before any edit the provenance line is ordinary, not a warning.
  const provenance = page.locator(".outputs-provenance");
  await expect(provenance).toContainText("transcript v1");
  await expect(provenance).not.toHaveClass(/outputs-stale/);
  await expect(page.getByRole("button", { name: /Régénérer/ })).toHaveCount(0);

  const segment = page.locator(".transcript .seg").first();
  await segment.getByRole("button", { name: /Corriger/ }).click();
  await page.getByLabel("Texte du segment").fill("Une correction qui change le sens.");
  await page.getByRole("button", { name: "Enregistrer" }).click();

  // Now it says so, in product terms rather than as a version number alone.
  await expect(provenance).toHaveClass(/outputs-stale/);
  await expect(provenance).toContainText("à revoir");
  await expect(provenance).toContainText("transcript v1");

  await page.getByRole("button", { name: /Régénérer/ }).click();

  // Caught up: derived from v2, and the warning is gone.
  await expect(provenance).toContainText("transcript v2", { timeout: 30_000 });
  await expect(provenance).not.toHaveClass(/outputs-stale/);
  await expect(page.getByRole("heading", { name: "Résumé" })).toBeVisible();
});

test("correcting several segments does not re-summarize on its own", async ({ page }) => {
  // The decision, asserted as an absence. If editing triggered regeneration,
  // the provenance line would climb to v2, v3, v4 by itself and each step
  // would be a paid call.
  await meetingWithSummary(page);

  const segments = page.locator(".transcript .seg");
  const count = Math.min(3, await segments.count());
  expect(count).toBeGreaterThan(1);

  for (let i = 0; i < count; i++) {
    await segments.nth(i).getByRole("button", { name: /Corriger/ }).click();
    await page.getByLabel("Texte du segment").fill(`Correction numéro ${i + 1}.`);
    await page.getByRole("button", { name: "Enregistrer" }).click();
    await expect(page.locator(".seg-editor")).toBeHidden();
  }

  // Still derived from v1 — nothing re-ran — and still asking to be reviewed.
  const provenance = page.locator(".outputs-provenance");
  await expect(provenance).toContainText("transcript v1");
  await expect(provenance).toHaveClass(/outputs-stale/);
});

test("a correction survives a reload, because it is stored and not screen state", async ({
  page,
}) => {
  await meetingWithSummary(page);

  const segment = page.locator(".transcript .seg").first();
  const id = await segment.getAttribute("data-segment-id");
  await segment.getByRole("button", { name: /Corriger/ }).click();
  await page.getByLabel("Texte du segment").fill("Corrigé et durable.");
  await page.getByRole("button", { name: "Enregistrer" }).click();
  await expect(page.locator(".seg-editor")).toBeHidden();

  await page.reload();

  const after = page.locator(`.transcript .seg[data-segment-id="${id}"]`);
  await expect(after).toContainText("Corrigé et durable.");
  await expect(after).toHaveClass(/seg-corrected/);
});

test("cancelling an edit changes nothing", async ({ page }) => {
  // The control. Without it a "save on every keystroke" implementation would
  // pass every test above.
  await meetingWithSummary(page);

  const segment = page.locator(".transcript .seg").first();
  const before = ((await segment.innerText()) ?? "").replace("✎", "").trim();

  await segment.getByRole("button", { name: /Corriger/ }).click();
  await page.getByLabel("Texte du segment").fill("Ceci ne doit pas être enregistré.");
  await page.getByRole("button", { name: "Annuler" }).click();

  await expect(page.locator(".seg-editor")).toBeHidden();
  await expect(page.locator(".transcript .seg").first()).toContainText(before);
  await expect(page.locator(".outputs-provenance")).not.toHaveClass(/outputs-stale/);
});
