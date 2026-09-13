/** R4: reload identity and guest review with real HTTP/WS/storage and fake ASR/LLM. */
import { expect, test } from "@playwright/test";
import { chromiumLaunch, isolateFromCdns } from "./launch";

test.use({ launchOptions: chromiumLaunch, permissions: ["microphone"] });

test("reload retains two identities and the guest reviews transcript, outputs and audio", async ({ browser, request }) => {
  const hostToken = process.env.MOSAIQUE_HOST_TOKEN!;
  expect(hostToken).toBeTruthy();
  const created = await request.post("/api/meetings", {
    headers: { Authorization: `Bearer ${hostToken}` }, data: { title: "Identités R4" },
  });
  expect(created.ok()).toBeTruthy();
  const { meeting, invite_url: invite } = await created.json();
  const host = await browser.newContext({ baseURL: process.env.MOSAIQUE_BASE_URL ?? "http://localhost:5173", permissions: ["microphone"] });
  const guest = await browser.newContext({ baseURL: process.env.MOSAIQUE_BASE_URL ?? "http://localhost:5173", permissions: ["microphone"] });
  await Promise.all([host, guest].map(isolateFromCdns));
  await host.addInitScript((token) => localStorage.setItem("mosaique.host_token", token), hostToken);
  const a = await host.newPage(), b = await guest.newPage();
  try {
    for (const [page, name] of [[a, "Amina"], [b, "Bruno"]] as const) {
      await page.goto(invite);
      await page.getByLabel("Votre nom").fill(name);
      await page.getByRole("button", { name: /Rejoindre/ }).click();
      await expect(page).toHaveURL(new RegExp(`/meeting/${meeting.id}$`));
    }
    await expect(a.getByRole("button", { name: "Terminer la réunion" })).toBeVisible();
    await expect(b.getByRole("button", { name: "Terminer la réunion" })).toHaveCount(0);
    await expect(b.locator(".line-final").first()).toBeVisible({ timeout: 20_000 });
    const before = await b.evaluate((id) => JSON.parse(sessionStorage.getItem(`mosaique.meeting.${id}`)!).joined, meeting.id);
    await b.reload();
    await expect(b.locator(".roster-entry")).toHaveCount(2);
    await expect(b.locator(".line-final").first()).toBeVisible({ timeout: 20_000 });
    const after = await b.evaluate((id) => JSON.parse(sessionStorage.getItem(`mosaique.meeting.${id}`)!).joined, meeting.id);
    expect(after.participant.id).toBe(before.participant.id);
    const detail = await request.get(`/api/meetings/${meeting.id}`, { headers: { Authorization: `Bearer ${hostToken}` } });
    expect((await detail.json()).participants).toHaveLength(2);
    await a.getByRole("button", { name: "Terminer la réunion" }).click();
    for (const page of [a, b]) {
      await expect(page.getByRole("heading", { name: "Compte rendu" })).toBeVisible();
      await expect(page.getByRole("heading", { name: "Résumé" })).toBeVisible({ timeout: 30_000 });
    }
    await b.reload();
    await expect(b.getByRole("heading", { name: "Compte rendu" })).toBeVisible();
    await expect(b.locator(".transcript .seg").first()).toBeVisible();
    await expect(b.getByRole("button", { name: /Corriger/ })).toHaveCount(0);
    await expect(b.getByRole("button", { name: /Régénérer/ })).toHaveCount(0);
    const audio = b.waitForResponse((response) => response.url().includes(`/meetings/${meeting.id}/audio/`));
    await b.locator(".evidence-link:not([disabled])").first().click();
    expect((await audio).ok()).toBeTruthy();
    expect(await b.evaluate(() => localStorage.getItem("mosaique.host_token"))).toBeNull();
  } finally { await host.close(); await guest.close(); }
});
