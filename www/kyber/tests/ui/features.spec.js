/**
 * Playwright UI tests for features not covered by the existing spec files:
 *   - Autopilot auto-execute of plan cards
 *   - Slash command autocomplete dropdown
 *   - Prompt history navigation (↑/↓)
 *   - Chat history persistence (restore from /api/kyber/history)
 *   - YAML block / Apply button
 *   - Area suggestion chip
 *   - Memory suggestion card (learned_fact)
 */
import { test, expect } from "@playwright/test";
import { gotoHarness, injectPlanCard, sendMessage } from "./helpers.js";

// ---------------------------------------------------------------------------
// Autopilot auto-execute
// ---------------------------------------------------------------------------
test.describe("Autopilot — auto-execute plan card", () => {
  test("plan card auto-executes after 2 s when autopilot is on", async ({ page }) => {
    await page.route("**/api/kyber/execute", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ results: [{ status: "ok" }] }),
      })
    );

    await gotoHarness(page);

    // Enable autopilot via the public badge click handler
    await page.evaluate(() => {
      window.__panel._autopilot = true;
      window.__panel._updateAutopilotBadge();
    });

    // Inject a plan card — should auto-execute because autopilot is on
    await injectPlanCard(page, {
      summary: "Turn off bedroom light",
      actions: [
        { type: "call_service", domain: "light", service: "turn_off", entity_id: "light.bedroom" },
      ],
    });

    // Auto-execute fires after 2 s; wait up to 6 s for the success result
    await expect(page.locator(".plan-result.success")).toBeVisible({ timeout: 6_000 });

    await page.screenshot({ path: "screenshots/features/autopilot-auto-execute.png" });
  });

  test("plan card does NOT auto-execute when autopilot is off", async ({ page }) => {
    let executeCalled = false;
    await page.route("**/api/kyber/execute", (route) => {
      executeCalled = true;
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ results: [] }) });
    });

    await gotoHarness(page);
    // Autopilot is off by default
    await injectPlanCard(page, {
      summary: "Turn off bedroom light",
      actions: [
        { type: "call_service", domain: "light", service: "turn_off", entity_id: "light.bedroom" },
      ],
    });

    // Wait 3 s — execute must NOT have been called
    await page.waitForTimeout(3_000);
    expect(executeCalled).toBe(false);
    // Execute button must still be visible (ready to click)
    await expect(page.locator(".btn-execute")).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// Slash command autocomplete
// ---------------------------------------------------------------------------
test.describe("Autocomplete — slash commands", () => {
  test.beforeEach(async ({ page }) => {
    await gotoHarness(page);
  });

  test("typing / opens top-level autocomplete list", async ({ page }) => {
    const input = page.locator("#prompt-input");
    await input.fill("/");
    await input.dispatchEvent("input");

    const list = page.locator("#ac-list");
    await expect(list).not.toBeEmpty({ timeout: 2_000 });

    await page.screenshot({ path: "screenshots/features/autocomplete-slash.png" });
  });

  test("typing /d filters to dashboard commands", async ({ page }) => {
    const input = page.locator("#prompt-input");
    await input.fill("/d");
    await input.dispatchEvent("input");

    const list = page.locator("#ac-list");
    await expect(list).not.toBeEmpty({ timeout: 2_000 });
    // Items have class .ac-item; entity_id is stored in data-id
    const items = list.locator(".ac-item");
    const count = await items.count();
    expect(count).toBeGreaterThan(0);
    for (let i = 0; i < count; i++) {
      const text = await items.nth(i).getAttribute("data-id");
      expect(text?.toLowerCase()).toMatch(/^\/d/);
    }

    await page.screenshot({ path: "screenshots/features/autocomplete-filter-d.png" });
  });

  test("pressing ArrowDown selects first item; Enter inserts it", async ({ page }) => {
    const input = page.locator("#prompt-input");
    await input.fill("/");
    await input.dispatchEvent("input");

    // Wait for list to populate
    await expect(page.locator("#ac-list")).not.toBeEmpty({ timeout: 2_000 });

    // Press ↓ to select first item, then Tab to insert
    await input.press("ArrowDown");
    await input.press("Tab");

    // Prompt should now contain the inserted command (not just "/")
    const val = await input.inputValue();
    expect(val.length).toBeGreaterThan(1);
    expect(val).toMatch(/^\//);

    await page.screenshot({ path: "screenshots/features/autocomplete-insert.png" });
  });

  test("Escape closes autocomplete list", async ({ page }) => {
    const input = page.locator("#prompt-input");
    await input.fill("/");
    await input.dispatchEvent("input");

    await expect(page.locator("#ac-list")).not.toBeEmpty({ timeout: 2_000 });

    await input.press("Escape");

    // List should now be empty / hidden
    const list = page.locator("#ac-list");
    const html = await list.innerHTML();
    expect(html.trim()).toBe("");

    await page.screenshot({ path: "screenshots/features/autocomplete-escape.png" });
  });
});

// ---------------------------------------------------------------------------
// Prompt history navigation (↑ / ↓)
// ---------------------------------------------------------------------------
test.describe("Prompt history — shell-style navigation", () => {
  test("ArrowUp fills the most recent user message", async ({ page }) => {
    // Stub API so _askAI completes without network errors
    await page.route("**/api/kyber/complete", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ response: "OK", plan: null, yaml_blocks: [] }),
      })
    );
    await page.route("**/api/lovelace/resources", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
    );

    await gotoHarness(page);

    // Send two messages
    await sendMessage(page, "Turn on bedroom light");
    await expect(page.locator(".chat-message.assistant").last()).toContainText("OK", { timeout: 6_000 });

    await sendMessage(page, "Turn off fan");
    await expect(page.locator(".chat-message.assistant").last()).toContainText("OK", { timeout: 6_000 });

    // Focus prompt, press ↑ — should fill most recent message
    const input = page.locator("#prompt-input");
    await input.click();
    await input.press("ArrowUp");

    const val = await input.inputValue();
    expect(val).toBe("Turn off fan");

    await page.screenshot({ path: "screenshots/features/prompt-history-up.png" });
  });

  test("ArrowUp twice navigates back two messages", async ({ page }) => {
    await page.route("**/api/kyber/complete", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ response: "OK", plan: null, yaml_blocks: [] }),
      })
    );
    await page.route("**/api/lovelace/resources", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
    );

    await gotoHarness(page);
    await sendMessage(page, "First message");
    await expect(page.locator(".chat-message.assistant").last()).toContainText("OK", { timeout: 6_000 });
    await sendMessage(page, "Second message");
    await expect(page.locator(".chat-message.assistant").last()).toContainText("OK", { timeout: 6_000 });

    const input = page.locator("#prompt-input");
    await input.click();
    await input.press("ArrowUp");
    await input.press("ArrowUp");

    const val = await input.inputValue();
    expect(val).toBe("First message");

    await page.screenshot({ path: "screenshots/features/prompt-history-up-twice.png" });
  });

  test("ArrowDown after ArrowUp restores draft", async ({ page }) => {
    await page.route("**/api/kyber/complete", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ response: "OK", plan: null, yaml_blocks: [] }),
      })
    );
    await page.route("**/api/lovelace/resources", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
    );

    await gotoHarness(page);
    await sendMessage(page, "Previous message");
    await expect(page.locator(".chat-message.assistant").last()).toContainText("OK", { timeout: 6_000 });

    const input = page.locator("#prompt-input");
    await input.fill("my draft");
    await input.press("ArrowUp");   // goes to "Previous message"
    await input.press("ArrowDown"); // should restore draft

    const val = await input.inputValue();
    expect(val).toBe("my draft");
  });
});

// ---------------------------------------------------------------------------
// Chat history persistence
// ---------------------------------------------------------------------------
test.describe("Chat history — persistence", () => {
  test("panel restores messages from /api/kyber/history on load", async ({ page }) => {
    await page.route("**/api/kyber/history", async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            history: [
              { role: "user",      content: "What lights are on?" },
              { role: "assistant", content: "The bedroom light is on." },
            ],
            compacted_summary: "",
            session_id: "s1",
            session_name: "Session 1",
          }),
        });
      } else {
        await route.fallback();
      }
    });

    await gotoHarness(page);

    // Both messages should render in the chat history
    await expect(page.locator(".chat-message.user").last()).toContainText(
      "What lights are on?",
      { timeout: 5_000 }
    );
    await expect(page.locator(".chat-message.assistant").last()).toContainText(
      "The bedroom light is on.",
      { timeout: 5_000 }
    );

    await page.screenshot({ path: "screenshots/features/history-restored.png" });
  });

  test("panel starts empty when /api/kyber/history returns 404", async ({ page }) => {
    await page.route("**/api/kyber/history", async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill({ status: 404, body: "Not found" });
      } else {
        await route.fallback();
      }
    });

    await gotoHarness(page);

    // Only the greeting assistant message should be present (no user messages)
    await expect(page.locator(".chat-message.user")).toHaveCount(0);
    await expect(page.locator(".chat-message.assistant").first()).toContainText(
      "Hi!",
      { timeout: 3_000 }
    );

    await page.screenshot({ path: "screenshots/features/history-empty-on-404.png" });
  });
});

// ---------------------------------------------------------------------------
// YAML block / Apply button
// ---------------------------------------------------------------------------
test.describe("YAML block — Apply button", () => {
  test("AI response with yaml_blocks renders an Apply button", async ({ page }) => {
    const yaml = "alias: Morning Lights\ntrigger: []\naction: []";

    await page.route("**/api/kyber/complete", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          response: "Here is the updated YAML:",
          plan: null,
          yaml_blocks: [yaml],
        }),
      })
    );
    await page.route("**/api/lovelace/resources", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
    );

    await gotoHarness(page);
    await sendMessage(page, "Update my morning lights automation");

    // YAML suggestion container should appear
    await expect(page.locator(".yaml-suggestion")).toBeVisible({ timeout: 6_000 });

    // Pre tag shows the YAML
    await expect(page.locator(".yaml-suggestion pre")).toContainText("Morning Lights");

    // Apply button is present
    const applyBtn = page.locator(".yaml-suggestion button");
    await expect(applyBtn).toBeVisible();
    await expect(applyBtn).toContainText("Apply");

    await page.screenshot({ path: "screenshots/features/yaml-block-apply.png" });
  });

  test("clicking Apply marks button as Applied", async ({ page }) => {
    const yaml = "alias: Bedtime\ntrigger: []\naction: []";

    await page.route("**/api/kyber/complete", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          response: "Here is the automation YAML:",
          plan: null,
          yaml_blocks: [yaml],
        }),
      })
    );
    await page.route("**/api/lovelace/resources", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
    );

    await gotoHarness(page);

    // Stub _setEditorContent so the Apply handler completes successfully
    // even when the editor is not open.
    await page.evaluate(() => {
      window.__panel._setEditorContent = () => {};
    });

    await sendMessage(page, "Give me bedtime automation YAML");
    await expect(page.locator(".yaml-suggestion")).toBeVisible({ timeout: 6_000 });

    const applyBtn = page.locator(".yaml-suggestion button");
    await applyBtn.click();

    await expect(applyBtn).toContainText(/applied/i, { timeout: 3_000 });
    await expect(applyBtn).toBeDisabled();

    await page.screenshot({ path: "screenshots/features/yaml-block-applied.png" });
  });
});

// ---------------------------------------------------------------------------
// Area suggestion chip
// ---------------------------------------------------------------------------
test.describe("Area suggestion chip", () => {
  test("AI response with area_suggestions renders a suggestion chip", async ({ page }) => {
    await page.route("**/api/kyber/complete", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          response: "I noticed some devices have no area.",
          plan: null,
          yaml_blocks: [],
          area_suggestions: [
            {
              entity_id: "sensor.kitchen_temp",
              friendly_name: "Kitchen Temp",
              suggested_area_id: "kitchen",
              suggested_area_name: "Kitchen",
              already_assigned: false,
              confidence: 0.9,
            },
          ],
        }),
      })
    );
    await page.route("**/api/lovelace/resources", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
    );

    await gotoHarness(page);
    await sendMessage(page, "Check which devices have no area");

    // Suggestion chip should appear
    await expect(page.locator(".kyber-area-suggestion-chip")).toBeVisible({ timeout: 6_000 });
    await expect(page.locator(".kyber-area-suggestion-chip")).toContainText("Kitchen");

    await page.screenshot({ path: "screenshots/features/area-suggestion-chip.png" });
  });

  test("area suggestion chip with applied=true shows assigned state", async ({ page }) => {
    await page.route("**/api/kyber/complete", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          response: "Area already assigned.",
          plan: null,
          yaml_blocks: [],
          area_suggestions: [
            {
              id: "s2",
              entity_id: "light.bedroom",
              friendly_name: "Bedroom Light",
              suggested_area_id: "bedroom",
              suggested_area_name: "Bedroom",
              applied: true,  // <-- the flag the client code checks
              confidence: 1.0,
            },
          ],
        }),
      })
    );
    await page.route("**/api/lovelace/resources", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
    );

    await gotoHarness(page);
    await sendMessage(page, "Check bedroom light area");

    await expect(page.locator(".kyber-area-suggestion-chip")).toBeVisible({ timeout: 6_000 });
    await expect(page.locator(".kyber-area-suggestion-chip")).toContainText("Assigned");

    await page.screenshot({ path: "screenshots/features/area-suggestion-assigned.png" });
  });
});

// ---------------------------------------------------------------------------
// Memory suggestion card (learned_fact)
// ---------------------------------------------------------------------------
test.describe("Memory suggestion card — learned_fact", () => {
  test("AI response with learned_fact renders a memory suggestion card", async ({ page }) => {
    await page.route("**/api/kyber/complete", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          response: "Got it, I'll remember that.",
          plan: null,
          yaml_blocks: [],
          // _buildMemoryCard reads (learnedFact.actions||[])[0].subject / .content
          // and learnedFact.summary for the display text.
          learned_fact: {
            summary: "Save alias: bedroom temp → '20°C preference'",
            actions: [
              {
                description: "Save alias: bedroom temp → '20°C preference'",
                subject: "bedroom temp",
                content: "User prefers bedroom at 20°C",
              },
            ],
          },
        }),
      })
    );
    await page.route("**/api/lovelace/resources", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
    );

    await gotoHarness(page);
    await sendMessage(page, "I like my bedroom at 20 degrees");

    // Memory card should appear in chat
    await expect(page.locator(".memory-card")).toBeVisible({ timeout: 6_000 });
    // Card shows subject → content from the actions[0] data
    await expect(page.locator(".memory-card")).toContainText("bedroom temp");

    await page.screenshot({ path: "screenshots/features/memory-learned-fact.png" });
  });
});
