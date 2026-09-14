/**
 * The typography, which until now had never been rendered by a test.
 *
 * `e2e/launch.ts` used to abort every request to fonts.googleapis.com and
 * fonts.gstatic.com in all of the specs, so the two shipped faces — Bricolage
 * Grotesque and IBM Plex Sans — were exercised by nothing: every assertion in
 * this directory ran on fallback system fonts. F1 self-hosted them and deleted
 * that block, and this is what keeps it true.
 *
 * Two things can silently undo it. Someone can put a CDN `<link>` back in
 * `index.html`, and the page still looks right on their machine. Or the
 * `woff2` files can stop being committed — an unanchored `.gitignore` glob has
 * already cost this repository a source file once — and the page falls back to
 * `system-ui` with nothing failing. Both show up here.
 *
 * Needs a running frontend; no backend state, so it does not seed or join.
 */
import { expect, test } from "@playwright/test";
import { chromiumLaunch } from "./launch";

test.use({ launchOptions: chromiumLaunch });

const CDN = /fonts\.(googleapis|gstatic)\.com/;

test("the faces are served from this origin and nothing reaches a font CDN", async ({ page }) => {
  const requested: string[] = [];
  page.on("request", (request) => requested.push(request.url()));

  await page.goto("/");
  await page.evaluate(() => document.fonts.ready);

  expect(requested.filter((url) => CDN.test(url))).toEqual([]);

  // Both `latin` files, because French lives inside that range. The
  // `latin-ext` files are meant to stay unfetched on a page with no glyph
  // outside it, which is the whole reason they are a separate request.
  const fonts = requested.filter((url) => url.endsWith(".woff2"));
  expect(fonts.some((url) => url.endsWith("/fonts/bricolage-grotesque-latin.woff2"))).toBe(true);
  expect(fonts.some((url) => url.endsWith("/fonts/ibm-plex-sans-latin.woff2"))).toBe(true);
  for (const url of fonts) expect(new URL(url).origin).toBe(new URL(page.url()).origin);
});

test("both faces actually load, rather than silently falling back to system-ui", async ({ page }) => {
  await page.goto("/");

  const loaded = await page.evaluate(async () => {
    await document.fonts.ready;
    const faces: Record<string, string[]> = {};
    document.fonts.forEach((face) => {
      (faces[face.family] ??= []).push(face.status);
    });
    return faces;
  });

  expect(loaded["Bricolage Grotesque"]).toContain("loaded");
  expect(loaded["IBM Plex Sans"]).toContain("loaded");
});

test("the two above-the-fold faces are preloaded", async ({ page }) => {
  await page.goto("/");
  const preloaded = await page
    .locator('link[rel="preload"][as="font"]')
    .evaluateAll((links) => links.map((l) => (l as HTMLLinkElement).getAttribute("href")));

  expect(preloaded).toEqual([
    "/fonts/bricolage-grotesque-latin.woff2",
    "/fonts/ibm-plex-sans-latin.woff2",
  ]);
});
