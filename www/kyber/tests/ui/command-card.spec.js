import { test, expect } from "@playwright/test";
import { gotoHarness, injectCommandCard } from "./helpers.js";

test.describe("Command card — confirm button", () => {
  test.beforeEach(async ({ page }) => {
    await gotoHarness(page);
  });

  test("confirm button is visible", async ({ page }) => {
    await injectCommandCard(page, { title: "Delete automation", detail: "my_automation" });

    const btn = page.locator(".btn-cmd-execute");
    await expect(btn).toBeVisible();
    await expect(btn).toContainText("▶ Execute");

    await page.screenshot({ path: "screenshots/command-confirm-before.png" });
  });

  test("confirm button fires the onConfirm action and shows ✓ Done", async ({ page }) => {
    let confirmCalled = false;

    await page.route("**/api/kyber/test-confirm", (route) => {
      confirmCalled = true;
      route.fulfill({ status: 200, body: "{}" });
    });

    await injectCommandCard(page, { title: "Test action", detail: "some entity" });
    await page.locator(".btn-cmd-execute").click();

    // Button text should change to Done (or similar) after confirm
    await expect(page.locator(".btn-cmd-execute")).toContainText(/done|✓/i, { timeout: 5_000 });

    await page.screenshot({ path: "screenshots/command-confirm-done.png" });

    expect(confirmCalled).toBe(true);
  });

  test("cancel button removes the card", async ({ page }) => {
    await injectCommandCard(page, { title: "Dangerous action", detail: "target" });

    const card = page.locator(".command-card");
    await expect(card).toBeVisible();

    await page.locator(".btn-cmd-cancel").click();

    await expect(card).not.toBeVisible({ timeout: 3_000 });
    await page.screenshot({ path: "screenshots/command-cancel.png" });
  });

  test("danger styling applied for destructive actions", async ({ page }) => {
    await injectCommandCard(page, { title: "Delete area", detail: "bedroom", danger: true });

    const btn = page.locator(".btn-cmd-execute");
    await expect(btn).toBeVisible();

    // Danger button should have the danger class
    await expect(btn).toHaveClass(/danger/);

    await page.screenshot({ path: "screenshots/command-danger.png" });
  });
});
