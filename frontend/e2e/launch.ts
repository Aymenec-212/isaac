import type { BrowserContext } from "@playwright/test";

/**
 * Chromium launch options shared by the browser specs.
 *
 * The fake device flags let a headless run stream audio without a microphone,
 * which is what makes these deterministic. `MOSAIQUE_CHROMIUM_PATH` is an
 * escape hatch for environments where `playwright install` cannot reach the
 * network but a Chromium is already on disk; unset, Playwright uses its own.
 */
export const chromiumLaunch = {
  args: [
    "--use-fake-ui-for-media-stream",
    "--use-fake-device-for-media-stream",
    "--autoplay-policy=no-user-gesture-required",
  ],
  ...(process.env.MOSAIQUE_CHROMIUM_PATH
    ? { executablePath: process.env.MOSAIQUE_CHROMIUM_PATH }
    : {}),
};

/**
 * Cut the page off from the webfont CDN.
 *
 * `index.html` loads Google Fonts through a render-blocking `<link>`, so where
 * that host is slow or unreachable the first paint waits on it and every
 * assertion below races a third-party CDN. The typeface is cosmetic and
 * nothing here asserts on it, so the honest thing is for these tests not to
 * depend on the network at all.
 */
export async function isolateFromCdns(context: BrowserContext): Promise<void> {
  await context.route(/fonts\.(googleapis|gstatic)\.com/, (route) => route.abort());
}
