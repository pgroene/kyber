import { test, expect } from "@playwright/test";
import { gotoHarness } from "./helpers.js";

test.describe("Debug bug report dialog", () => {
  test("opens with upload logs unchecked by default", async ({ page }) => {
    await gotoHarness(page);

    await page.evaluate(async () => {
      await window.__panel._openBugReportFlow("req-123");
    });

    await expect(page.locator("#br-submit")).toBeVisible();
    await expect(page.locator("#br-include-bundle")).not.toBeChecked();
    await expect(page.locator(".bug-report-bundle-name")).toContainText("kyber-debug-req-123.zip");

    await page.screenshot({ path: "screenshots/debug-bug-report-dialog.png" });
  });
});
