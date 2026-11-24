import { test, expect } from "@playwright/test";
import { gotoHarness } from "./helpers.js";

// A reply whose plan block could not be parsed used to end on a colon with
// no card at all. The panel now says so and offers the raw block.

test("unreadable plan block shows a visible notice with the raw text", async ({ page }) => {
  await gotoHarness(page);
  await page.evaluate(() => {
    window.__panel._appendAIResponse(
      "Since the editor is closed, here is the edit_automation plan:\n\n```plan\n{\"edit_automation\": true, \"summary\": oops}\n```",
      [], null,
    );
  });
  const note = page.locator(".plan-unreadable");
  await expect(note).toBeVisible();
  await note.locator("summary").click();
  await expect(note.locator("pre")).toContainText('"summary": oops');
  await page.screenshot({ path: "screenshots/plan-unreadable.png" });
});
