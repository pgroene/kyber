/**
 * UX tests — chat compaction banner + Undo button restore
 *
 * Covers:
 *   - Compaction banner appears in chat after size trigger fires
 *   - Compaction banner appears after count trigger fires
 *   - Undo button renders in [CHANGE] message bubble after plan execution
 *   - Undo button is restored on page reload from persisted history
 *   - Restored Undo button is greyed-out when history entry is already undone
 *   - Clicking the restored Undo button calls the undo endpoint
 */

import { test, expect } from "@playwright/test";
import { gotoHarness, injectPlanCard } from "./helpers.js";

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

/** Seed _chatHistory with n short messages so compaction may fire. */
async function seedMessages(page, count) {
  await page.evaluate((n) => {
    for (let i = 0; i < n; i++) {
      window.__panel._chatHistory.push({
        role: i % 2 === 0 ? "user" : "assistant",
        content: `message number ${i} to fill history`,
      });
    }
  }, count);
}

/** Seed _chatHistory with large messages to exceed the size trigger (12000 chars). */
async function seedLargeMessages(page, count = 4) {
  await page.evaluate((n) => {
    const chunk = "x".repeat(3200); // 4 × 3200 = 12800 > 12000 trigger
    for (let i = 0; i < n; i++) {
      window.__panel._chatHistory.push({
        role: i % 2 === 0 ? "user" : "assistant",
        content: chunk,
      });
    }
  }, count);
}

/** Route the /api/kyber/summarize endpoint with a canned summary. */
function routeSummarize(page, summary = "Earlier: lights were adjusted.") {
  return page.route("**/api/kyber/summarize", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ summary }),
    })
  );
}

/** Route /api/kyber/history GET to return a persisted history entry with meta. */
function routeHistoryWithMeta(page, entryId) {
  return page.route("**/api/kyber/history", async (route) => {
    if (route.request().method() !== "GET") { await route.fallback(); return; }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        history: [
          { role: "user", content: "Turn on the kitchen light" },
          {
            role: "assistant",
            content: "[CHANGE] The following changes were successfully applied:\n- turn_on on light.kitchen",
            meta: { history_entry_id: entryId },
          },
        ],
        compacted_summary: "",
      }),
    });
  });
}

// ---------------------------------------------------------------------------
// Compaction banner
// ---------------------------------------------------------------------------

test.describe("Chat compaction — UX banner", () => {
  test("compaction banner appears after size trigger fires", async ({ page }) => {
    await page.route("**/api/kyber/history", async (route) => {
      if (route.request().method() !== "GET") { await route.fallback(); return; }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ history: [], compacted_summary: "" }),
      });
    });
    await routeSummarize(page);
    await gotoHarness(page);

    // Seed history large enough to exceed size trigger
    await seedLargeMessages(page, 4);

    // Trigger _maybeCompact by sending one more message (adds new user msg)
    await page.route("**/api/kyber/complete", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ response: "Done.", plan: null, yaml_blocks: [] }),
      })
    );
    await page.route("**/api/lovelace/resources", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
    );

    const input = page.locator("#prompt-input");
    await input.fill("another question");
    await page.locator("#btn-ask").click();

    await expect(page.locator(".chat-message.system-compact")).toBeVisible({ timeout: 8_000 });
    await expect(page.locator(".chat-message.system-compact")).toContainText("summarized");

    await page.screenshot({ path: "screenshots/chat-compaction-banner-size.png" });
  });

  test("compaction banner appears after count trigger fires", async ({ page }) => {
    await page.route("**/api/kyber/history", async (route) => {
      if (route.request().method() !== "GET") { await route.fallback(); return; }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ history: [], compacted_summary: "" }),
      });
    });
    await routeSummarize(page);
    await gotoHarness(page);

    // Seed 21 messages to exceed the count trigger of 20
    await seedMessages(page, 21);

    await page.route("**/api/kyber/complete", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ response: "OK.", plan: null, yaml_blocks: [] }),
      })
    );
    await page.route("**/api/lovelace/resources", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
    );

    const input = page.locator("#prompt-input");
    await input.fill("trigger compaction");
    await page.locator("#btn-ask").click();

    await expect(page.locator(".chat-message.system-compact")).toBeVisible({ timeout: 8_000 });

    await page.screenshot({ path: "screenshots/chat-compaction-banner-count.png" });
  });

  test("compaction banner includes the AI-generated summary", async ({ page }) => {
    await page.route("**/api/kyber/history", async (route) => {
      if (route.request().method() !== "GET") { await route.fallback(); return; }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ history: [], compacted_summary: "" }),
      });
    });
    await routeSummarize(page, "Earlier you asked about kitchen lights.");
    await gotoHarness(page);
    await seedLargeMessages(page, 4);

    await page.route("**/api/kyber/complete", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ response: "Done.", plan: null, yaml_blocks: [] }),
      })
    );
    await page.route("**/api/lovelace/resources", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
    );

    await page.locator("#prompt-input").fill("another");
    await page.locator("#btn-ask").click();

    const banner = page.locator(".chat-message.system-compact");
    await expect(banner).toBeVisible({ timeout: 8_000 });
    await expect(banner).toContainText("summarized");
    // Summary is stored in _compactedSummary but not embedded in the banner text itself
    const summary = await page.evaluate(() => window.__panel._compactedSummary);
    expect(summary).toContain("Earlier you asked about kitchen lights.");

    await page.screenshot({ path: "screenshots/chat-compaction-summary.png" });
  });
});

// ---------------------------------------------------------------------------
// Undo button in [CHANGE] messages
// ---------------------------------------------------------------------------

test.describe("Undo button — after plan execution", () => {
  test("Undo button appears in chat after executing a plan with undo_plan", async ({ page }) => {
    const entryId = "test-entry-001";

    await page.route("**/api/kyber/execute", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          results: [{ status: "ok" }],
          history_entry: {
            id: entryId,
            summary: "Turn on kitchen light",
            status: "applied",
            undo_plan: [
              { type: "call_service", domain: "light", service: "turn_off", entity_id: "light.kitchen" },
            ],
          },
        }),
      })
    );

    await gotoHarness(page);
    await injectPlanCard(page, {
      summary: "Turn on kitchen light",
      actions: [{ type: "call_service", domain: "light", service: "turn_on", entity_id: "light.kitchen" }],
    });

    await page.locator(".btn-execute").click();
    await expect(page.locator(".plan-result.success")).toBeVisible({ timeout: 5_000 });

    // Undo button should appear in the plan card area after a successful execute
    const undoBtn = page.locator(".btn-undo");
    await expect(undoBtn).toBeVisible({ timeout: 5_000 });
    await expect(undoBtn).toContainText("Undo");
    await expect(undoBtn).not.toBeDisabled();

    await page.screenshot({ path: "screenshots/chat-undo-button-after-execute.png" });
  });
});

// ---------------------------------------------------------------------------
// Undo button restored on reload
// ---------------------------------------------------------------------------

test.describe("Undo button — restored from persisted history", () => {
  test("Undo button is restored for a [CHANGE] message with history_entry_id on page load", async ({ page }) => {
    const entryId = "restore-entry-001";

    await routeHistoryWithMeta(page, entryId);
    await page.route(`**/api/kyber/history/actions/${entryId}`, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: entryId,
          status: "applied",
          undo_plan: [
            { type: "call_service", domain: "light", service: "turn_off", entity_id: "light.kitchen" },
          ],
        }),
      })
    );

    await gotoHarness(page);

    // Undo button should be restored in the chat
    const undoBtn = page.locator(".chat-message-wrap.assistant .btn-undo").first();
    await expect(undoBtn).toBeVisible({ timeout: 8_000 });
    await expect(undoBtn).toContainText("Undo");
    await expect(undoBtn).not.toBeDisabled();

    await page.screenshot({ path: "screenshots/chat-undo-restored.png" });
  });

  test("Restored Undo button is greyed-out when entry is already undone", async ({ page }) => {
    const entryId = "restore-entry-undone";

    await routeHistoryWithMeta(page, entryId);
    await page.route(`**/api/kyber/history/actions/${entryId}`, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: entryId,
          status: "undone",
          undo_plan: [],
        }),
      })
    );

    await gotoHarness(page);

    const undoBtn = page.locator(".chat-message-wrap.assistant .btn-undo").first();
    await expect(undoBtn).toBeVisible({ timeout: 8_000 });
    await expect(undoBtn).toContainText("Undone");
    await expect(undoBtn).toBeDisabled();

    await page.screenshot({ path: "screenshots/chat-undo-already-undone.png" });
  });

  test("No Undo button when history entry is not found (404)", async ({ page }) => {
    const entryId = "missing-entry";

    await routeHistoryWithMeta(page, entryId);
    await page.route(`**/api/kyber/history/actions/${entryId}`, (route) =>
      route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ message: "not found" }) })
    );

    await gotoHarness(page);

    // Wait for messages to appear
    await expect(page.locator(".chat-message.user")).toBeVisible({ timeout: 5_000 });

    // No Undo button should appear
    const undoBtn = page.locator(".chat-message-wrap.assistant .btn-undo");
    await expect(undoBtn).toHaveCount(0);

    await page.screenshot({ path: "screenshots/chat-undo-404.png" });
  });

  test("Clicking restored Undo button calls the undo endpoint and updates button", async ({ page }) => {
    const entryId = "undo-click-entry";
    let undoCalled = false;

    await routeHistoryWithMeta(page, entryId);

    await page.route(`**/api/kyber/history/actions/${entryId}/undo`, async (route) => {
      undoCalled = true;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ status: "ok", entry: { id: entryId, status: "undone" } }),
      });
    });

    await page.route(`**/api/kyber/history/actions/${entryId}`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: entryId,
          status: "applied",
          undo_plan: [
            { type: "call_service", domain: "light", service: "turn_off", entity_id: "light.kitchen" },
          ],
        }),
      });
    });

    await gotoHarness(page);

    const undoBtn = page.locator(".chat-message-wrap.assistant .btn-undo").first();
    await expect(undoBtn).toBeVisible({ timeout: 8_000 });
    await undoBtn.click();

    await expect(undoBtn).toContainText("Undone ✓", { timeout: 5_000 });
    await expect(undoBtn).toBeDisabled();
    expect(undoCalled).toBe(true);

    await page.screenshot({ path: "screenshots/chat-undo-clicked.png" });
  });
});
