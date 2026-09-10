/**
 * Slice 6R: the review page as a person actually reads it.
 *
 * Two jobs, and the second is the risky one.
 *
 * **New behaviour** (items 1, 2, 3, 6): the transcript groups into paragraphs
 * with the speaker and timestamp said once per turn instead of once per segment;
 * interim text is marked by a word rather than only by a colour; a summary that
 * succeeded but extracted nothing says so instead of rendering empty headings.
 *
 * **Regressions** (items 4 and 5): clickable citations and search highlighting
 * both already worked, and grouping is exactly what breaks them — citation
 * scroll targets are keyed to per-segment nodes, and highlight offsets index into
 * a single segment's text, not a joined paragraph. These tests exist to fail if
 * a future "simplification" concatenates a paragraph into one string.
 *
 * Needs the app running: the backend on :8000 and the dev server on :5173.
 *
 *   MOSAIQUE_HOST_TOKEN="$(cd ../backend && uv run python -m mosaique.app.seed | awk '/^host_token:/{print $2}')" \
 *     npx playwright test e2e/review.spec.ts
 */
import { expect, test, type Page } from "@playwright/test";
import { chromiumLaunch, isolateFromCdns } from "./launch";

test.use({ launchOptions: chromiumLaunch, permissions: ["microphone"] });

test.beforeEach(async ({ context }) => isolateFromCdns(context));

/** Run one real meeting and land on its review page. */
async function meetingThroughToReview(page: Page) {
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

  await page.getByLabel("Titre de la réunion").fill("Revue de lecture");
  await page.getByRole("button", { name: "Nouvelle réunion" }).click();
  const invite = page.locator(".notice a");
  await expect(invite).toBeVisible();
  await invite.click();

  await page.getByLabel("Votre nom").fill("Amina");
  await page.getByRole("button", { name: /Rejoindre/ }).click();
  // Enough audio for several segments, which is what grouping needs to show.
  await expect(page.locator(".line-final").first()).toBeVisible({ timeout: 20_000 });
  await page.waitForTimeout(3_000);

  await page.getByRole("button", { name: "Terminer la réunion" }).click();
  await expect(page.getByRole("heading", { name: "Compte rendu" })).toBeVisible();
  await expect(page.locator(".transcript .para").first()).toBeVisible({ timeout: 20_000 });
}

test("the live view marks interim text with a word, not only a colour", async ({ page }) => {
  const hostToken = process.env.MOSAIQUE_HOST_TOKEN;
  expect(hostToken).toBeTruthy();

  await page.goto("/");
  await page.addInitScript(
    (token) => window.localStorage.setItem("mosaique.host_token", token),
    hostToken!,
  );
  await page.reload();

  await page.getByLabel("Titre de la réunion").fill("Vue en direct");
  await page.getByRole("button", { name: "Nouvelle réunion" }).click();
  await page.locator(".notice a").click();
  await page.getByLabel("Votre nom").fill("Amina");
  await page.getByRole("button", { name: /Rejoindre/ }).click();

  // The live view keeps word-by-word rendering on purpose — it is the surface
  // that makes latency and transcription activity visible. What changes is that
  // "provisional" is now legible without separating two hues.
  const interim = page.locator(".line-interim").first();
  await expect(interim).toBeVisible({ timeout: 20_000 });
  await expect(interim.locator(".tag-interim")).toHaveText("en cours");

  // And a committed line does not carry the marker.
  await expect(page.locator(".line-final").first()).toBeVisible({ timeout: 20_000 });
  await expect(page.locator(".line-final .tag-interim")).toHaveCount(0);
});

test("the review transcript reads as speaker-grouped paragraphs, not one line per segment", async ({
  page,
}) => {
  await meetingThroughToReview(page);

  const paragraphs = page.locator(".transcript .para");
  const segments = page.locator(".transcript .seg");

  const paragraphCount = await paragraphs.count();
  const segmentCount = await segments.count();

  expect(segmentCount).toBeGreaterThan(0);
  // The point of the slice: fewer blocks to read than the model produced events.
  expect(paragraphCount).toBeLessThan(segmentCount);

  // The speaker is said once per paragraph, not once per segment.
  await expect(paragraphs.first().locator(".speaker")).toHaveCount(1);
  await expect(paragraphs.first().locator(".speaker")).toHaveText("Amina");

  // And each paragraph carries when it was said (mm:ss).
  await expect(paragraphs.first().locator(".para-time")).toHaveText(/^\d{2}:\d{2}$/);
});

test("a citation still scrolls to its segment with grouping in place", async ({ page }) => {
  // Regression for FR-11. The scroll target is a segment *inside* a paragraph;
  // a paragraph rendered as one joined string would have nothing to scroll to.
  await meetingThroughToReview(page);

  // The invariant that makes the rest of this meaningful, and the one a
  // concatenating "simplification" breaks first: grouping changes how the
  // transcript looks, never what is addressable. One element per segment.
  // Asserted here rather than assumed, because an earlier draft of this file
  // passed against a joined paragraph and proved nothing.
  const segmentCount = await page.locator(".transcript .seg").count();
  const paragraphCount = await page.locator(".transcript .para").count();
  expect(segmentCount).toBeGreaterThan(paragraphCount);

  await expect(page.getByRole("heading", { name: "Résumé" })).toBeVisible({ timeout: 30_000 });

  // The *last* citation, not the first. The fake provider cites the first and
  // last segments; the first segment is also its paragraph's first, so clicking
  // it resolves even when segments have been collapsed. The last one is the
  // case that actually needs per-segment addressability.
  const citation = page.locator(".evidence-link").last();
  await expect(citation).toBeVisible();
  await citation.click();

  const cited = page.locator(".transcript .seg-cited");
  await expect(cited).toHaveCount(1);
  await expect(cited).toHaveAttribute("data-segment-id", /^[A-Z0-9]{26}$/i);
  await expect(cited).toBeInViewport();
});

test("search still highlights the matching phrase inside a grouped paragraph", async ({ page }) => {
  // Regression for FR-10. Highlight spans are offsets into one segment's text;
  // if a paragraph were joined into a single string they would land in the
  // wrong place, or on the wrong word, and only a browser would show it.
  await meetingThroughToReview(page);

  // Deliberately a word from a segment that is *not* its paragraph's first.
  // Offsets into the first segment happen to line up even against a joined
  // paragraph, because both start at index 0 — so searching the first segment
  // proves nothing. A later segment's offsets are shifted by everything before
  // it, which is precisely the breakage this guards.
  const laterSeg = page.locator(".transcript .para").first().locator(".seg").nth(1);
  await expect(laterSeg).toBeVisible();
  const laterId = await laterSeg.getAttribute("data-segment-id");
  const laterText = ((await laterSeg.innerText()) ?? "").trim();
  const word = laterText.split(/\s+/).find((w) => w.replace(/\W/g, "").length >= 4);
  expect(word, "the second segment should contain a searchable word").toBeTruthy();
  const query = word!.replace(/\W/g, "");

  await page.getByLabel("Rechercher dans le transcript").fill(query);

  const marks = page.locator(".transcript mark");
  await expect(marks.first()).toBeVisible({ timeout: 10_000 });
  // The highlight covers exactly the matched word, not a neighbour and not the
  // whole paragraph — which is what a wrong offset would produce.
  await expect(marks.first()).toHaveText(new RegExp(query, "i"));

  // And it sits inside the segment that actually matched, still addressable by
  // its own id after grouping.
  await expect(
    page.locator(`.transcript .seg[data-segment-id="${laterId}"] mark`).first(),
  ).toBeVisible();
});

test("a summary that extracted nothing says so instead of showing empty headings", async ({
  page,
}) => {
  // Item 6. Succeeded-but-thin was previously indistinguishable from a page
  // that had simply not finished loading: a summary with no headings under it.
  await page.route("**/meetings/*/outputs", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "succeeded",
        summary: "Réunion courte, sans décision formelle.",
        key_points: [],
        decisions: [],
        action_items: [],
        open_questions: [],
      }),
    }),
  );

  await meetingThroughToReview(page);

  await expect(page.getByText("Compte rendu partiel.")).toBeVisible();
  await expect(page.getByText("ni décision ni action")).toBeVisible();
  // The transcript is untouched by a thin summary.
  await expect(page.locator(".transcript .para").first()).toBeVisible();
});

test("a failed summary says the transcript is still the record", async ({ page }) => {
  await page.route("**/meetings/*/outputs", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "failed",
        summary: null,
        key_points: [],
        decisions: [],
        action_items: [],
        open_questions: [],
        error_code: "POSTPROCESSING_FAILED",
      }),
    }),
  );

  await meetingThroughToReview(page);

  await expect(page.getByText("Le compte rendu n'a pas pu être généré.")).toBeVisible();
  await expect(page.getByText("c'est la seule partie qui fait foi")).toBeVisible();
  await expect(page.getByText("POSTPROCESSING_FAILED")).toBeVisible();
  await expect(page.locator(".transcript .para").first()).toBeVisible();
});
