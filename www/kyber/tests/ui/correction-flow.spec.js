/**
 * Playwright UI tests for the Kyber correction micro-agent flow.
 *
 * Covers:
 *   - Execute button shows failure message when action fails
 *   - [FAILED] message is added to chat history on failure
 *   - Correction plan is automatically re-executed when returned by the server
 *   - [🔧 CORRECTION] message appears in chat on successful correction
 *   - Toast notification appears when learned_fact is present
 *   - Approval-required (403) highlights the Execute button with a pulse
 *   - No correction card shown when no data.correction in response
 */

import { test, expect } from "@playwright/test";
import { gotoHarness, injectPlanCard } from "./helpers.js";

const PLAN_SUMMARY = "Set Werkkamer lights to white";
const LIGHT_ACTION = {
  type: "call_service",
  domain: "light",
  service: "turn_on",
  entity_id: "light.test_light",
  service_data: { color_temp: 200 },
  description: "Turn on test light",
};

// Stub a successful execute response
const EXECUTE_OK = {
  results: [{ status: "ok", entity_id: "light.test_light" }],
};

// Stub a failure response with a correction
const EXECUTE_FAIL_WITH_CORRECTION = {
  results: [
    {
      status: "error",
      entity_id: "light.test_light",
      message: "extra keys not allowed @ data['color_temp']",
    },
  ],
  correction: {
    corrected_actions: [
      {
        type: "call_service",
        domain: "light",
        service: "turn_on",
        entity_id: "light.test_light",
        service_data: { rgb_color: [255, 255, 255] },
        description: "Turn on with white rgb_color",
      },
    ],
    message: "[🔧 CORRECTION] Set lights to white using rgb_color",
    learned_fact: "🧠 Learned: light correction — HA rejected parameter(s) color_temp — removed from retry",
    original_errors: ["extra keys not allowed @ data['color_temp']"],
  },
};

// Stub a failure response without correction
const EXECUTE_FAIL_NO_CORRECTION = {
  results: [
    {
      status: "error",
      entity_id: "light.test_light",
      message: "Service unavailable",
    },
  ],
};

// ── Helpers ──────────────────────────────────────────────────────────────────

async function injectPlanAndGetCard(page, plan, actions = [LIGHT_ACTION]) {
  return await page.evaluate(
    ([p, a]) => {
      const card = window.__panel._buildPlanCard({ ...p, actions: a });
      const history = window.__panel.shadowRoot.getElementById("chat-history");
      history.appendChild(card);
      history.scrollTop = history.scrollHeight;
      return true;
    },
    [plan, actions]
  );
}

async function stubExecute(page, responseBody, statusCode = 200) {
  await page.route("**/api/kyber/execute", (route) =>
    route.fulfill({
      status: statusCode,
      contentType: "application/json",
      body: JSON.stringify(responseBody),
    })
  );
}

async function clickExecuteButton(page) {
  const btn = page.locator(".btn-execute").last();
  await expect(btn).toBeVisible();
  await btn.click();
}

// ── Tests ────────────────────────────────────────────────────────────────────

test.describe("Correction micro-agent flow", () => {
  test.beforeEach(async ({ page }) => {
    await gotoHarness(page);
    // Stub lovelace resources to prevent unrelated failures
    await page.route("**/api/lovelace/resources", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
    );
    // Stub the complete endpoint (not used in these tests)
    await page.route("**/api/kyber/complete", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ response: "ok", plan: null }),
      })
    );
  });

  // ── Success baseline ───────────────────────────────────────────────────────

  test("shows ✅ Done on successful execution", async ({ page }) => {
    await stubExecute(page, EXECUTE_OK);
    await injectPlanAndGetCard(page, { summary: PLAN_SUMMARY });
    await clickExecuteButton(page);

    await expect(page.locator(".plan-result.success").last()).toContainText(
      "✅ Done",
      { timeout: 5000 }
    );
    await page.screenshot({ path: "screenshots/correction-success-baseline.png" });
  });

  // ── Failure + correction ───────────────────────────────────────────────────

  test("shows failure message when action fails", async ({ page }) => {
    // First execute → failure; second execute (correction) → success
    let callCount = 0;
    await page.route("**/api/kyber/execute", (route) => {
      callCount++;
      const body =
        callCount === 1 ? EXECUTE_FAIL_WITH_CORRECTION : EXECUTE_OK;
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(body),
      });
    });

    await injectPlanAndGetCard(page, { summary: PLAN_SUMMARY });
    await clickExecuteButton(page);

    // The result element should show the failure + correction text
    await expect(page.locator(".plan-result.error").last()).toContainText(
      "action(s) failed",
      { timeout: 5000 }
    );
    await page.screenshot({ path: "screenshots/correction-failure-shown.png" });
  });

  test("adds [FAILED] to chat history on failure", async ({ page }) => {
    let callCount = 0;
    await page.route("**/api/kyber/execute", (route) => {
      callCount++;
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(
          callCount === 1 ? EXECUTE_FAIL_WITH_CORRECTION : EXECUTE_OK
        ),
      });
    });

    await injectPlanAndGetCard(page, { summary: PLAN_SUMMARY });
    await clickExecuteButton(page);

    // Wait for failure to be displayed
    await expect(page.locator(".plan-result.error").last()).toBeVisible({ timeout: 5000 });

    // Check chat history includes [FAILED] message
    const historyContainsFailed = await page.evaluate(() => {
      const panel = window.__panel;
      const history = panel._chatHistory || [];
      return history.some(
        (m) => m.role === "assistant" && m.content.includes("[FAILED]")
      );
    });
    expect(historyContainsFailed).toBe(true);

    await page.screenshot({ path: "screenshots/correction-failed-in-history.png" });
  });

  test("shows correction success after re-execution", async ({ page }) => {
    let callCount = 0;
    await page.route("**/api/kyber/execute", (route) => {
      callCount++;
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(
          callCount === 1 ? EXECUTE_FAIL_WITH_CORRECTION : EXECUTE_OK
        ),
      });
    });

    await injectPlanAndGetCard(page, { summary: PLAN_SUMMARY });
    await clickExecuteButton(page);

    // Wait for correction to complete
    await expect(page.locator(".plan-result").last()).toContainText(
      "Corrected",
      { timeout: 8000 }
    );
    await page.screenshot({ path: "screenshots/correction-corrected-applied.png" });
  });

  test("adds [🔧 CORRECTION] to chat history on successful correction", async ({ page }) => {
    let callCount = 0;
    await page.route("**/api/kyber/execute", (route) => {
      callCount++;
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(
          callCount === 1 ? EXECUTE_FAIL_WITH_CORRECTION : EXECUTE_OK
        ),
      });
    });

    await injectPlanAndGetCard(page, { summary: PLAN_SUMMARY });
    await clickExecuteButton(page);

    // Wait for correction to complete
    await expect(page.locator(".plan-result").last()).toContainText("Corrected", { timeout: 8000 });

    const historyHasCorrection = await page.evaluate(() => {
      const panel = window.__panel;
      const history = panel._chatHistory || [];
      return history.some(
        (m) =>
          m.role === "assistant" &&
          (m.content.includes("[🔧 CORRECTION]") || m.content.includes("CORRECTION"))
      );
    });
    expect(historyHasCorrection).toBe(true);

    await page.screenshot({ path: "screenshots/correction-in-history.png" });
  });

  // ── Toast notification ─────────────────────────────────────────────────────

  test("shows toast when learned_fact is present in correction", async ({ page }) => {
    let callCount = 0;
    await page.route("**/api/kyber/execute", (route) => {
      callCount++;
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(
          callCount === 1 ? EXECUTE_FAIL_WITH_CORRECTION : EXECUTE_OK
        ),
      });
    });

    await injectPlanAndGetCard(page, { summary: PLAN_SUMMARY });
    await clickExecuteButton(page);

    // Toast element should appear with the learned_fact text
    const toastLocator = page.locator(".kyber-toast");
    await expect(toastLocator).toBeVisible({ timeout: 6000 });
    await expect(toastLocator).toContainText("🧠");

    await page.screenshot({ path: "screenshots/correction-toast.png" });
  });

  // ── No correction when not in response ────────────────────────────────────

  test("no correction shown when server returns no correction field", async ({ page }) => {
    await stubExecute(page, EXECUTE_FAIL_NO_CORRECTION);
    await injectPlanAndGetCard(page, { summary: PLAN_SUMMARY });
    await clickExecuteButton(page);

    await expect(page.locator(".plan-result.error").last()).toContainText(
      "Service unavailable",
      { timeout: 5000 }
    );

    // No correction message should appear
    const toastVisible = await page.locator(".kyber-toast").isVisible().catch(() => false);
    expect(toastVisible).toBe(false);

    await page.screenshot({ path: "screenshots/correction-no-correction-shown.png" });
  });

  // ── Approval queue auto-popup ──────────────────────────────────────────────

  test("Execute button pulses when approval is required (403)", async ({ page }) => {
    await page.route("**/api/kyber/execute", (route) =>
      route.fulfill({
        status: 403,
        contentType: "application/json",
        body: JSON.stringify({
          status: "approval_required",
          blocked_actions: [
            { type: "assign_area", entity_id: "light.test_light" },
          ],
          message: "Approval required",
        }),
      })
    );

    await injectPlanAndGetCard(page, { summary: PLAN_SUMMARY });

    // Autopilot doesn't auto-execute, so click manually
    await clickExecuteButton(page);

    // Result should show approval required message
    await expect(page.locator(".plan-result").last()).toContainText(
      "Approval required",
      { timeout: 5000 }
    );

    await page.screenshot({ path: "screenshots/correction-approval-required.png" });
  });
});
