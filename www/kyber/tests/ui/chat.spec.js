import { test, expect } from "@playwright/test";
import { gotoHarness, sendMessage } from "./helpers.js";

test.describe("Chat — send button and AI response", () => {
  test.beforeEach(async ({ page }) => {
    await gotoHarness(page);
  });

  test("send button is visible and prompt input is present", async ({ page }) => {
    await expect(page.locator("#btn-ask")).toBeVisible();
    await expect(page.locator("#prompt-input")).toBeVisible();
    await page.screenshot({ path: "screenshots/chat-initial.png" });
  });

  test("debug tabs do not show memory option", async ({ page }) => {
    await expect(page.locator("button[data-debug-tab='memory']")).toHaveCount(0);
    await expect(page.locator("button[data-debug-tab='last_turn']")).toHaveCount(1);
  });

  test("typing a message and sending shows a user bubble", async ({ page }) => {
    await page.route("**/api/kyber/complete", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ response: "Sure, I can help with that!", plan: null, yaml_blocks: [] }),
      })
    );
    // Also stub lovelace resources so _askAI doesn't fail before the POST
    await page.route("**/api/lovelace/resources", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
    );

    await sendMessage(page, "Turn off bedroom light");

    // User bubble should appear
    await expect(page.locator(".chat-message.user").last()).toContainText("Turn off bedroom light");

    await page.screenshot({ path: "screenshots/chat-user-bubble.png" });
  });

  test("AI response appears as assistant bubble", async ({ page }) => {
    await page.route("**/api/kyber/complete", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ response: "I've turned off the bedroom light.", plan: null, yaml_blocks: [] }),
      })
    );
    await page.route("**/api/lovelace/resources", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
    );

    await sendMessage(page, "Help me");

    // Wait for assistant response
    await expect(page.locator(".chat-message.assistant").last()).toContainText(
      "I've turned off the bedroom light.",
      { timeout: 8_000 }
    );

    await page.screenshot({ path: "screenshots/chat-ai-response.png" });
  });

  test("plan card appears when AI responds with a plan", async ({ page }) => {
    const plan = {
      summary: "Turn off bedroom light",
      actions: [{ type: "call_service", domain: "light", service: "turn_off", entity_id: "light.bedroom" }],
    };

    await page.route("**/api/kyber/complete", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          response: `Here's my plan:\n\`\`\`plan\n${JSON.stringify(plan)}\n\`\`\``,
          plan,
          yaml_blocks: [],
        }),
      })
    );
    await page.route("**/api/lovelace/resources", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
    );

    await sendMessage(page, "Turn off bedroom light");

    await expect(page.locator(".plan-card")).toBeVisible({ timeout: 8_000 });
    await expect(page.locator(".btn-execute")).toBeVisible();

    await page.screenshot({ path: "screenshots/chat-plan-card.png" });
  });

  test("clear history button resets restored chat history", async ({ page }) => {
    await page.route("**/api/kyber/history", async (route) => {
      const method = route.request().method();
      if (method === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            history: [{ role: "user", content: "persisted message" }],
            compacted_summary: "persisted summary",
          }),
        });
        return;
      }
      if (method === "DELETE") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ status: "ok" }),
        });
        return;
      }
      await route.fallback();
    });

    await gotoHarness(page);
    await expect(page.locator(".chat-message.user").last()).toContainText("persisted message");

    await page.locator("#btn-clear-history").click();
    await expect(page.locator(".chat-message.user")).toHaveCount(0);
    await expect(page.locator(".chat-message.assistant").first()).toContainText("Hi! Ask me anything about your smart home");

    await page.screenshot({ path: "screenshots/chat-clear-history.png" });
  });
});
