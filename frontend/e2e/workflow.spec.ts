import { expect, test } from "@playwright/test";

import { login } from "./helpers";

test.describe("ingestion → detection → alerts", () => {
  test("replay the sample, run detection, and see alerts", async ({ page }) => {
    await login(page);

    // Step 1 — replay the bundled sample CSV. (The topbar title and the page
    // header both match /ingestion/i, so take the first to avoid strict mode.)
    await page.getByRole("link", { name: /ingestion/i }).click();
    await expect(page.getByRole("heading", { name: /ingestion/i }).first()).toBeVisible();
    await page.getByRole("button", { name: /replay bundled sample/i }).click();

    // A success toast confirms ingestion, and step 2 unlocks.
    await expect(page.getByRole("status").or(page.getByRole("alert"))).toContainText(
      /ingested|replayed/i,
      { timeout: 20_000 },
    );

    // Step 2 — run detection.
    await page.getByRole("button", { name: /run detection now/i }).click();
    await expect(page.getByText(/alerts created/i)).toBeVisible({ timeout: 20_000 });

    // Step 3 — open the alerts console and confirm rows are present.
    await page.getByRole("link", { name: /alerts/i }).first().click();
    await expect(page.getByRole("heading", { name: /alerts/i }).first()).toBeVisible();
    await expect(page.getByRole("table")).toBeVisible({ timeout: 15_000 });
  });
});
