import { expect, test } from "@playwright/test";

import { login } from "./helpers";

test.describe("response center", () => {
  test("approve a simulated pending action", async ({ page }) => {
    await login(page);
    await page.getByRole("link", { name: /response center/i }).click();
    // Topbar title + page header both match; first() avoids strict mode.
    await expect(page.getByRole("heading", { name: /response center/i }).first()).toBeVisible();

    const firstApprove = page.getByRole("button", { name: /^Approve$/ }).first();
    if (!(await firstApprove.isVisible().catch(() => false))) {
      test.skip(true, "No simulated pending actions in the queue to approve.");
      return;
    }

    await firstApprove.click();
    // A simulated approve has no modal — it succeeds and surfaces a success toast.
    await expect(page.getByRole("status").or(page.getByRole("alert"))).toContainText(
      /approved/i,
      { timeout: 15_000 },
    );
  });

  test("LAB approval requires typed confirmation + reason in a modal", async ({ page }) => {
    await login(page);
    await page.getByRole("link", { name: /response center/i }).click();

    const labApprove = page.getByRole("button", { name: /approve \(lab\)/i }).first();
    if (!(await labApprove.isVisible().catch(() => false))) {
      test.skip(true, "No real-LAB action present (LAB mode is off by default).");
      return;
    }

    await labApprove.click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    // The confirm button is blocked until the user types CONFIRM + a reason.
    const confirmBtn = dialog.getByRole("button", { name: /approve lab action/i });
    await expect(confirmBtn).toBeDisabled();

    await dialog.getByLabel(/type/i).fill("CONFIRM");
    await dialog.getByLabel(/reason/i).fill("approved for the scheduled lab exercise");
    await expect(confirmBtn).toBeEnabled();

    // Escape cancels without taking the action.
    await page.keyboard.press("Escape");
    await expect(dialog).not.toBeVisible();
  });
});
