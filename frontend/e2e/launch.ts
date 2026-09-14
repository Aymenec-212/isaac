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
