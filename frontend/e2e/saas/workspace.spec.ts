import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";

test("persisted account, two workspaces, invitation, private meeting, revoke and logout", async ({
  browser,
}, testInfo) => {
  const fixture = JSON.parse(readFileSync("e2e/.auth/saas.json", "utf8"));
  const owner = await browser.newContext();
  const member = await browser.newContext();
  try {
    for (const [context, account] of [
      [owner, fixture.owner],
      [member, fixture.member],
    ] as const) {
      await context.addCookies([
        {
          name: "mosaique_session",
          value: account.token,
          url: "http://localhost:5173",
          httpOnly: true,
          sameSite: "Lax",
        },
      ]);
    }
    const page = await owner.newPage();
    await page.goto("/");
    await page
      .getByLabel("Nom de l’espace", { exact: true })
      .fill("Équipe Alpha");
    await page
      .getByRole("button", { name: "Créer l’espace", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "Équipe Alpha", exact: true }),
    ).toBeVisible();
    const create = page
      .getByRole("heading", { name: "Créer un espace" })
      .locator("..");
    await create.getByLabel("Nom de l’espace").fill("Équipe Beta");
    await create.getByRole("button", { name: "Créer l’espace" }).click();
    await expect(
      page.getByRole("heading", { name: "Équipe Beta", exact: true }),
    ).toBeVisible();
    await page
      .getByLabel("Changer d’espace")
      .selectOption({ label: "Équipe Alpha" });
    await page.getByLabel("Titre de la réunion").fill("Décisions de lancement");
    await page.getByRole("button", { name: "Préparer une réunion" }).click();
    await expect(
      page.getByText("Décisions de lancement", { exact: true }),
    ).toBeVisible();
    await page.getByLabel("Nom affiché").fill("Camille");
    await page.getByRole("button", { name: "Enregistrer le profil" }).click();
    await page.reload();
    await expect(page.getByLabel("Nom affiché")).toHaveValue("Camille");
    await page
      .getByLabel("Adresse e-mail", { exact: true })
      .fill(fixture.member.email);
    await page.getByRole("button", { name: "Créer une invitation" }).click();
    const link = await page.getByLabel("Lien d’invitation").inputValue();
    const teammate = await member.newPage();
    await teammate.goto(link);
    await teammate.getByRole("button", { name: "Rejoindre l’espace" }).click();
    await expect(
      teammate.getByRole("heading", { name: "Équipe Alpha", exact: true }),
    ).toBeVisible();
    await expect(
      teammate.getByText("Décisions de lancement", { exact: true }),
    ).toHaveCount(0);
    await page.reload();
    await page.getByText("Gérer l’accès", { exact: true }).click();
    await page.getByRole("button", { name: "Autoriser", exact: true }).click();
    await teammate.reload();
    await expect(
      teammate.getByText("Décisions de lancement", { exact: true }),
    ).toBeVisible();
    const row = page
      .locator("li")
      .filter({ has: page.getByText(fixture.member.email, { exact: true }) })
      .first();
    await row.getByRole("button", { name: "Retirer", exact: true }).click();
    await teammate.reload();
    await expect(
      teammate.getByRole("heading", { name: "Bienvenue dans Mosaïque" }),
    ).toBeVisible();
    await expect(
      teammate.getByText("Décisions de lancement", { exact: true }),
    ).toHaveCount(0);
    await page.screenshot({
      path: testInfo.outputPath("workspace.png"),
      fullPage: true,
    });
    await page.getByRole("button", { name: "Se déconnecter" }).click();
    await page.reload();
    await expect(
      page.getByRole("heading", {
        name: "La mémoire de vos réunions commence ici.",
      }),
    ).toBeVisible();
  } finally {
    await owner.close();
    await member.close();
  }
});
