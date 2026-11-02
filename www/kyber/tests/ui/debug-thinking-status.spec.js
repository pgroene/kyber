import { test, expect } from "@playwright/test";
import { gotoHarness } from "./helpers.js";

/**
 * The status tab compares "Let the model think" with what the chat model's
 * calls showed, and says where to fix a mismatch.
 */
test.describe("Debug status: thinking check", () => {
  const status = (thinking) => ({
    ai_task_entity: "ai_task.qwen",
    ai_task_info: { entity_id: "ai_task.qwen", friendly_name: "Qwen", model: "qwen3.6-35b", server: "" },
    thinking,
  });

  test("on, but the model does not think: setting, observation and hint", async ({ page }) => {
    await page.route("**/api/kyber/debug/status", (route) => route.fulfill({
      json: status({
        allow_thinking: true, model: "ai_task.qwen", path: "local_openai",
        observed: "not_thinking", source: "chat_log_empty", ts: Date.now() / 1000,
        counts: { thinking: 0, not_thinking: 2, unknown: 0 }, hint: "ev_thinking_on_local_openai",
      }),
    }));
    await gotoHarness(page);
    await page.evaluate(() => window.__panel._toggleDebugPane(true));
    await page.locator('[data-debug-tab="status"]').click();

    await expect(page.locator(".dbg-think-setting")).toHaveText("on");
    await expect(page.locator(".dbg-think-seen")).toContainText("does not think (no thinking text in the AI task's chat log");
    await expect(page.locator(".dbg-think-seen")).toContainText("0 of 2 calls with thinking");
    const hint = page.locator(".dbg-think-hint");
    await expect(hint).toBeVisible();
    await expect(hint).toContainText("ai_task.qwen answered without thinking");
    await expect(hint).toContainText("enable_thinking = true under 'Chat Template Arguments'");
    await page.screenshot({ path: "screenshots/debug-thinking-mismatch.png" });
  });

  test("no chat call yet: no hint", async ({ page }) => {
    await page.route("**/api/kyber/debug/status", (route) => route.fulfill({
      json: status({ allow_thinking: false, model: null, observed: "unknown", counts: {}, hint: null }),
    }));
    await gotoHarness(page);
    await page.evaluate(() => window.__panel._toggleDebugPane(true));
    await page.locator('[data-debug-tab="status"]').click();

    await expect(page.locator(".dbg-think-setting")).toHaveText("off");
    await expect(page.locator(".dbg-think-seen")).toHaveText("no chat call since Home Assistant started");
    await expect(page.locator(".dbg-think-hint")).toHaveCount(0);
  });
});
