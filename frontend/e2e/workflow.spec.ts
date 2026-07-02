import { expect, test } from "@playwright/test";

import { login } from "./helpers";

test.describe("ingestion → detection → alerts", () => {
  test("replay the sample, run detection, and see alerts", async ({ page }) => {
    await login(page);
    // Navigate via the sidebar (scoped), since the dashboard also links to these
    // pages and the topbar echoes the page title — both would otherwise make the
    // link/heading locators ambiguous under Playwright strict mode.
    const nav = page.getByRole("navigation", { name: /primary/i });

    // Step 1 — replay the bundled sample CSV.
    await nav.getByRole("link", { name: /ingestion/i }).click();
    await expect(page.getByRole("heading", { name: /ingestion/i }).first()).toBeVisible();
    await page.getByRole("button", { name: /replay bundled sample/i }).click();

    // A success toast confirms ingestion, and step 2 unlocks. Filter to the
    // matching toast — an earlier "Signed in." toast may still be on screen, so
    // an unfiltered role=status locator would resolve to multiple elements.
    await expect(
      page.getByRole("status").filter({ hasText: /ingested|replayed/i }),
    ).toBeVisible({ timeout: 20_000 });

    // Step 2 — run detection.
    await page.getByRole("button", { name: /run detection now/i }).click();
    await expect(page.getByText(/alerts created/i)).toBeVisible({ timeout: 20_000 });

    // Step 3 — open the alerts console and confirm rows are present.
    await nav.getByRole("link", { name: /alerts/i }).click();
    await expect(page.getByRole("heading", { name: /alerts/i }).first()).toBeVisible();
    await expect(page.getByRole("table")).toBeVisible({ timeout: 15_000 });
  });
});
