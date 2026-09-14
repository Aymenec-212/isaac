/**
 * F2's one non-negotiable: glass never touches a surface someone reads.
 *
 * The material is for chrome — the rail, the banner, the status bar, the
 * roster, notices, the join card — because there it earns its place by
 * revealing the ground behind it. Over long-form French it does the opposite:
 * running text on a blurred, *varying* backdrop is exactly where
 * glassmorphism fails, and that text is the product. The enhancement plan
 * calls for this spec by name so the rule cannot erode into "mostly".
 *
 * The positive control in the second test matters as much as the first. An
 * assertion that reading surfaces are opaque passes trivially on a page where
 * the glass was never applied at all — so this also proves the chrome really
 * is glazed in the same run.
 *
 * Needs a running backend; the reading-surface test walks a real meeting
 * through to its review page, because that is where .para and .seg exist.
 */
import { expect, test, type Page } from "@playwright/test";
import { chromiumLaunch } from "./launch";

test.use({ launchOptions: chromiumLaunch, permissions: ["microphone"] });

/** The computed background and backdrop of one element. */
async function paint(page: Page, selector: string) {
  return page.locator(selector).first().evaluate((el) => {
    const cs = getComputedStyle(el);
    return { background: cs.backgroundColor, backdrop: cs.backdropFilter };
  });
}

/** `rgb(…)` or `rgba(…, 1)` — anything the compositor need not see through. */
function isOpaque(color: string): boolean {
  const alpha = color.match(/^rgba\([^,]+,[^,]+,[^,]+,\s*([\d.]+)\s*\)$/);
  return alpha ? Number(alpha[1]) === 1 : /^rgb\(/.test(color);
}

/** Transparent, i.e. it contributes nothing and reveals its opaque parent. */
const isClear = (color: string) => /^rgba\(0,\s*0,\s*0,\s*0\)$/.test(color);

async function signIn(page: Page) {
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
}

test("no reading surface is glass", async ({ page }) => {
  await signIn(page);

  // The ledger is a reading surface too — rows are compared, not glanced at.
  const ledger = await paint(page, ".ledger");
  expect(isOpaque(ledger.background), `.ledger background ${ledger.background}`).toBe(true);
  expect(ledger.backdrop).toBe("none");

  // Walk one meeting to its review page, which is where .para and .seg live.
  await page.getByLabel("Titre de la réunion").fill("Surface de lecture");
  await page.getByRole("button", { name: "Nouvelle réunion" }).click();
  const invite = page.locator(".notice a");
  await expect(invite).toBeVisible();
  await invite.click();
  await page.getByLabel("Votre nom").fill("Amina");
  await page.getByRole("button", { name: /Rejoindre/ }).click();
  await expect(page.locator(".line-final").first()).toBeVisible({ timeout: 20_000 });

  // The live transcript first: it is a reading surface while it is still moving.
  const live = await paint(page, ".transcript");
  expect(isOpaque(live.background), `live .transcript background ${live.background}`).toBe(true);
  expect(live.backdrop).toBe("none");

  await page.waitForTimeout(3_000);
  await page.getByRole("button", { name: "Terminer la réunion" }).click();
  await expect(page.locator(".transcript .para").first()).toBeVisible({ timeout: 20_000 });

  for (const selector of [".transcript", ".outputs"]) {
    const surface = await paint(page, selector);
    expect(isOpaque(surface.background), `${selector} background ${surface.background}`).toBe(true);
    expect(surface.backdrop, `${selector} backdrop`).toBe("none");
  }

  // These carry no background of their own, which is the point: they reveal
  // the opaque card they sit in. What they must never do is introduce glass.
  for (const selector of [".transcript .para", ".transcript .seg"]) {
    const inner = await paint(page, selector);
    expect(isClear(inner.background), `${selector} background ${inner.background}`).toBe(true);
    expect(inner.backdrop, `${selector} backdrop`).toBe("none");
  }
});

test("chrome really is glazed, so the test above is not passing on nothing", async ({ page }) => {
  await signIn(page);

  for (const selector of [".rail", ".health-banner"]) {
    const chrome = await paint(page, selector);
    expect(chrome.backdrop, `${selector} backdrop`).toContain("blur");
    expect(isOpaque(chrome.background), `${selector} background ${chrome.background}`).toBe(false);
  }
});

test("a reader who asks for less transparency gets none of it", async ({ page, context }) => {
  await signIn(page);

  // Playwright's emulateMedia does not carry prefers-reduced-transparency yet,
  // so this goes through CDP. Chromium-only, which is what these specs run.
  const cdp = await context.newCDPSession(page);
  await cdp.send("Emulation.setEmulatedMedia", {
    features: [{ name: "prefers-reduced-transparency", value: "reduce" }],
  });
  await page.reload();
  await expect(page.locator(".rail")).toBeVisible();

  for (const selector of [".rail", ".health-banner"]) {
    const chrome = await paint(page, selector);
    expect(chrome.backdrop, `${selector} backdrop`).toBe("none");
    expect(isOpaque(chrome.background), `${selector} background ${chrome.background}`).toBe(true);
  }
});
