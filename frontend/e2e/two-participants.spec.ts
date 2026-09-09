/**
 * Slice 2 exit gate, browser half: two participants, one merged transcript,
 * identical in both browsers.
 *
 * The backend half of this gate is `backend/tests/integration/test_replay.py`,
 * which proves the same properties over real WebSockets without a browser.
 * This file adds the part only a browser can show: that both people see the
 * same thing on screen, each line attributed to whoever said it.
 *
 * Needs the app running: the backend on :8000 and the dev server on :5173.
 *
 *   npx playwright install chromium   # or set MOSAIQUE_CHROMIUM_PATH
 *   MOSAIQUE_HOST_TOKEN="$(cd ../backend && uv run python -m mosaique.app.seed | awk '/^host_token:/{print $2}')" \
 *     npx playwright test e2e/two-participants.spec.ts
 */
import { expect, test, type Page } from "@playwright/test";
import { chromiumLaunch, isolateFromCdns } from "./launch";

test.use({ launchOptions: chromiumLaunch, permissions: ["microphone"] });

/** The set of (speaker, text) pairs a page is currently showing. */
async function transcriptOn(page: Page): Promise<string[]> {
  return page.locator(".transcript .line-final").evaluateAll((lines) =>
    lines.map((line) => {
      const speaker = line.querySelector(".speaker")?.textContent?.trim() ?? "";
      const text = (line.textContent ?? "").replace(speaker, "").trim();
      return `${speaker}|${text}`;
    }),
  );
}

async function join(page: Page, inviteUrl: string, name: string): Promise<void> {
  await page.goto(inviteUrl);
  await expect(page.getByText("Cette réunion est enregistrée et transcrite.")).toBeVisible();
  await page.getByLabel("Votre nom").fill(name);
  await page.getByRole("button", { name: /Rejoindre/ }).click();
}

test("two participants see one merged, correctly attributed transcript", async ({ browser }) => {
  const hostToken = process.env.MOSAIQUE_HOST_TOKEN;
  expect(hostToken, "set MOSAIQUE_HOST_TOKEN from `uv run python -m mosaique.app.seed`").toBeTruthy();

  const contexts = await Promise.all([
    browser.newContext({ permissions: ["microphone"] }),
    browser.newContext({ permissions: ["microphone"] }),
  ]);
  await Promise.all(contexts.map(isolateFromCdns));
  const [amina, bruno] = await Promise.all(contexts.map((c) => c.newPage()));

  // Amina hosts, and takes the invite link from the meeting she just created.
  await amina.goto("/");
  await amina.addInitScript(
    (token) => window.localStorage.setItem("mosaique.host_token", token),
    hostToken!,
  );
  await amina.reload();
  await amina.getByLabel("Titre de la réunion").fill("Réunion à deux");
  await amina.getByRole("button", { name: "Nouvelle réunion" }).click();

  const invite = amina.locator(".notice a");
  await expect(invite).toBeVisible();
  const inviteUrl = (await invite.getAttribute("href"))!;

  await join(amina, inviteUrl, "Amina");
  await join(bruno, inviteUrl, "Bruno");

  // The panel is the roster, and it is the same roster on both screens.
  for (const page of [amina, bruno]) {
    await expect(page.locator(".roster-entry")).toHaveCount(2, { timeout: 20_000 });
    await expect(page.locator(".roster")).toContainText("Amina");
    await expect(page.locator(".roster")).toContainText("Bruno");
  }

  // Speaking lights up while a participant's words are being transcribed.
  await expect(amina.locator('.roster-entry[data-speaking="true"]').first()).toBeVisible({
    timeout: 30_000,
  });

  // Both streams reach both browsers, and the two screens converge on the
  // same lines. They are compared together rather than one after the other:
  // a final lands on the two sockets microseconds apart, so a snapshot of one
  // taken before the other is a race, not a disagreement.
  await expect
    .poll(
      async () => {
        const [onAmina, onBruno] = [await transcriptOn(amina), await transcriptOn(bruno)];
        const speakers = new Set(onAmina.map((line) => line.split("|")[0]));
        if (!speakers.has("Amina") || !speakers.has("Bruno")) {
          return `heard from ${[...speakers].join(", ") || "nobody"}`;
        }
        return JSON.stringify(onAmina) === JSON.stringify(onBruno)
          ? "identical"
          : `amina has ${onAmina.length} lines, bruno has ${onBruno.length}`;
      },
      { timeout: 45_000, intervals: [400] },
    )
    .toBe("identical");

  // Ending is the host's; the persisted transcript keeps both speakers.
  await amina.getByRole("button", { name: "Terminer la réunion" }).click();
  await expect(amina.getByRole("heading", { name: "Compte rendu" })).toBeVisible();
  await expect(amina.locator(".transcript .line-final").first()).toBeVisible({ timeout: 30_000 });

  const reviewed = await transcriptOn(amina);
  expect(reviewed.some((line) => line.startsWith("Amina|"))).toBe(true);
  expect(reviewed.some((line) => line.startsWith("Bruno|"))).toBe(true);
});
