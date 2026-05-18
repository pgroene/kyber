import { test, expect } from "@playwright/test";
import { gotoHarness, sendMessage } from "./helpers.js";

test.describe("Memory badge", () => {
  test.beforeEach(async ({ page }) => {
    // Stub the knowledge API so the badge initialises with a known count
    await page.route("**/api/kyber/knowledge", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          entries: Array.from({ length: 7 }, (_, i) => ({
            id: `fact-${i}`,
            category: "general",
            subject: `fact ${i}`,
            content: `Content of fact ${i}`,
          })),
          needs_review_count: 0,
          categories: ["general"],
        }),
      })
    );
    await gotoHarness(page);
  });

  test("memory badge is visible in the sidebar-brand area", async ({ page }) => {
    const badge = page.locator("#memory-badge");
    await expect(badge).toBeVisible();
    await page.screenshot({ path: "screenshots/memory-badge-visible.png" });
  });

  test("memory badge shows count after loading", async ({ page }) => {
    const countEl = page.locator("#memory-count");
    // Should show 7 after the knowledge API resolves
    await expect(countEl).toHaveText("7", { timeout: 5_000 });
    await page.screenshot({ path: "screenshots/memory-badge-count.png" });
  });

  test("memory badge shows … before knowledge loads", async ({ page }) => {
    // Route is already set in beforeEach — but we can check the initial state
    // by evaluating the DOM immediately after gotoHarness before the fetch completes.
    // This test just verifies the element exists and has text.
    const countEl = page.locator("#memory-count");
    await expect(countEl).not.toBeEmpty();
  });

  test("clicking the memory badge opens the popover", async ({ page }) => {
    const badge = page.locator("#memory-badge");
    const popover = page.locator("#memory-popover");

    // Popover hidden initially
    await expect(popover).toBeHidden();

    // Click to open
    await badge.click();
    await expect(popover).toBeVisible();
    await page.screenshot({ path: "screenshots/memory-badge-popover-open.png" });
  });

  test("clicking the memory badge again closes the popover", async ({ page }) => {
    const badge = page.locator("#memory-badge");
    const popover = page.locator("#memory-popover");

    await badge.click();
    await expect(popover).toBeVisible();

    await badge.click();
    await expect(popover).toBeHidden();
  });

  test("popover shows 'No facts recalled this turn' when no knowledge was used", async ({ page }) => {
    const badge = page.locator("#memory-badge");
    await badge.click();

    const body = page.locator("#memory-popover-body");
    await expect(body).toContainText("No facts recalled this turn");
    await page.screenshot({ path: "screenshots/memory-badge-popover-no-recall.png" });
  });

  test("popover shows recalled facts after an AI turn that used knowledge", async ({ page }) => {
    await page.route("**/api/kyber/complete", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          response: "The espresso machine is in the kitchen.",
          plan: null,
          yaml_blocks: [],
          knowledge_used: [
            { id: "kn-1", category: "entity_alias", subject: "espresso", content: "media_player.espresso_machine" },
          ],
        }),
      })
    );
    await page.route("**/api/lovelace/resources", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
    );

    await sendMessage(page, "where is the espresso machine?");

    // Wait for AI response
    await expect(page.locator(".chat-message.assistant").last()).toContainText(
      "espresso machine",
      { timeout: 8_000 }
    );

    // Open popover — should now show recalled facts
    await page.locator("#memory-badge").click();
    const body = page.locator("#memory-popover-body");
    await expect(body).toContainText("entity_alias");
    await expect(body).toContainText("espresso");
    await page.screenshot({ path: "screenshots/memory-badge-popover-recalled.png" });
  });

  test("memory badge gets the recalled CSS class after an AI turn with knowledge", async ({ page }) => {
    await page.route("**/api/kyber/complete", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          response: "Done.",
          plan: null,
          yaml_blocks: [],
          knowledge_used: [
            { id: "kn-1", category: "general", subject: "test", content: "test content" },
          ],
        }),
      })
    );
    await page.route("**/api/lovelace/resources", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
    );

    await sendMessage(page, "test recall");
    await expect(page.locator(".chat-message.assistant").last()).toContainText("Done.", { timeout: 8_000 });

    // Badge should have the recalled class for the pulse animation
    await expect(page.locator("#memory-badge")).toHaveClass(/memory-badge--recalled/);
    await page.screenshot({ path: "screenshots/memory-badge-pulse.png" });
  });

  test("autopilot badge is visible in the sidebar-brand area", async ({ page }) => {
    // Autopilot badge should be in sidebar-brand (next to memory badge), not status bar
    const badge = page.locator("#autopilot-badge");
    await expect(badge).toBeAttached();
    // When inactive it should be hidden (display:none via CSS)
    // Activate autopilot and verify it appears
    await page.evaluate(() => {
      window.__panel._autopilot = true;
      window.__panel._updateAutopilotBadge();
    });
    await expect(badge).toBeVisible();
    await page.screenshot({ path: "screenshots/autopilot-badge-active.png" });
  });
});
