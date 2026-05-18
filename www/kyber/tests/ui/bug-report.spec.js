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

  test("review dialog makes the bundle filename downloadable", async ({ page }) => {
    await gotoHarness(page);

    await page.route("**/api/kyber/debug/bug-report", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          title: "energie prijzen failure on integrations",
          body: "## Summary\nFailed to search for correct attributes in Kyber",
          similar_issues: [],
          bundle_available: true,
        }),
      })
    );

    await page.route("**/api/kyber/debug/bundle?request_id=req-download", (route) =>
      route.fulfill({
        status: 200,
        headers: {
          "content-type": "application/zip",
          "content-disposition": "attachment; filename=kyber-debug-req-download.zip",
        },
        body: "fake-zip",
      })
    );

    await page.evaluate(async () => {
      await window.__panel._openBugReportFlow("req-download");
      const shadow = window.__panel.shadowRoot;
      shadow.querySelector("#br-happened").value = "The answer was wrong.";
      shadow.querySelector("#br-submit").click();
    });

    await expect(page.locator("#br-bundle-download-link")).toBeVisible();
    const bundleRequest = page.waitForRequest("**/api/kyber/debug/bundle?request_id=req-download");
    await page.locator("#br-bundle-download-link").click();
    await bundleRequest;

    await expect(page.locator("#br-bundle-download-link")).toContainText("kyber-debug-req-download.zip");
    await page.screenshot({ path: "screenshots/debug-bug-report-download-link.png" });
  });
});
