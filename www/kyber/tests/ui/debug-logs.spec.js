import { test, expect } from "@playwright/test";
import { gotoHarness, shadowLocator } from "./helpers.js";

test.describe("Debug last-turn logs", () => {
  test("shows captured logs for the last turn", async ({ page }) => {
    await page.route("**/api/kyber/debug/mode", async (route) => {
      await route.fulfill({ json: { enabled: true } });
    });
    await page.route("**/api/kyber/debug/last_turn", async (route) => {
      await route.fulfill({
        json: {
          snapshot: {
            ts: 1715971200,
            request_id: "req-logs-1",
            elapsed_ms: 250,
            intent: "chat",
            char_count: 16,
            approx_tokens: 7,
            user_prompt: "why did this fail?",
            response_text: "I could not finish the action.",
            picked_knowledge: [],
            tool_log: [],
            logs: [
              { ts: 1715971200, level: "ERROR", logger: "custom_components.kyber.http_api", message: "Execution failed for light.kitchen_main" },
              { ts: 1715971201, level: "WARNING", logger: "custom_components.kyber", message: "Retry requested" },
            ],
          },
        },
      });
    });

    await gotoHarness(page);
    await page.evaluate(async () => {
      const body = window.__panel.shadowRoot.getElementById("debug-body");
      await window.__panel._renderDebugLastTurn(body);
    });

    await expect(shadowLocator(page, "#debug-body")).toContainText("Logs (2)");
    await expect(shadowLocator(page, "#debug-body")).toContainText("Execution failed for light.kitchen_main");

    await page.screenshot({ path: "screenshots/debug-last-turn-logs.png", fullPage: true });
  });
});
