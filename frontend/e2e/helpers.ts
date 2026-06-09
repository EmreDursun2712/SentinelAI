import { expect, type Page } from "@playwright/test";

export const CREDENTIALS = {
  username: process.env.PLAYWRIGHT_USER ?? "admin",
  password: process.env.PLAYWRIGHT_PASSWORD ?? "Sentinel-Demo-2026!",
};

/** Sign in through the login form and wait until the app shell is visible. */
export async function login(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Username").fill(CREDENTIALS.username);
  await page.getByLabel("Password").fill(CREDENTIALS.password);
  await page.getByRole("button", { name: /sign in/i }).click();
  // Sidebar nav appears once authenticated.
  await expect(page.getByRole("navigation", { name: /primary/i })).toBeVisible({
    timeout: 15_000,
  });
}
