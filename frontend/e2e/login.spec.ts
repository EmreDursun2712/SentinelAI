import { expect, test } from "@playwright/test";

import { CREDENTIALS, login } from "./helpers";

test.describe("authentication", () => {
  test("login takes the user to the dashboard", async ({ page }) => {
    await login(page);
    await expect(page.getByRole("heading", { name: /^Dashboard$/ })).toBeVisible();
    // The signed-in username is shown in the topbar.
    await expect(page.getByText(CREDENTIALS.username, { exact: false })).toBeVisible();
  });

  test("invalid credentials show an inline error and stay on /login", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("Username").fill("nobody");
    await page.getByLabel("Password").fill("wrong-password-123!");
    await page.getByRole("button", { name: /sign in/i }).click();
    await expect(page.getByRole("alert")).toBeVisible();
    await expect(page).toHaveURL(/\/login$/);
  });

  test("sign out returns to the login screen", async ({ page }) => {
    await login(page);
    await page.getByRole("button", { name: /sign out/i }).click();
    await expect(page).toHaveURL(/\/login$/);
  });
});
