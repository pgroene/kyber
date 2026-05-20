/**
 * Feature screenshots — comprehensive visual documentation of the Kyber panel.
 *
 * Each test navigates to a specific UI state and saves a full-viewport screenshot
 * to screenshots/features/. Run with:
 *
 *   docker exec kyber-ha sh -c "cd /config/www/kyber && \
 *     PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium-browser npm run test:ui -- \
 *     --grep screenshots"
 *
 * Screenshots are saved to: www/kyber/screenshots/features/
 */

import { test, expect } from "@playwright/test";
import { gotoHarness, injectPlanCard, injectCommandCard, sendMessage } from "./helpers.js";
import path from "path";

const S = (name) => `screenshots/features/${name}.png`;

// Common stubs shared across tests
async function stubLovelace(page) {
  await page.route("**/api/lovelace/resources", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
  );
}

async function stubKnowledge(page, count = 42) {
  await page.route("**/api/kyber/knowledge", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        entries: Array.from({ length: count }, (_, i) => ({
          id: `fact-${i}`,
          category: i % 3 === 0 ? "entity_alias" : i % 3 === 1 ? "general" : "procedure",
          subject: `fact ${i}`,
          content: `Content of fact ${i}`,
        })),
        needs_review_count: 3,
        categories: ["entity_alias", "general", "procedure"],
      }),
    })
  );
}

// ── 1. Initial / empty panel ─────────────────────────────────────────────────

test("01 initial panel — empty chat", async ({ page }) => {
  await stubKnowledge(page);
  await gotoHarness(page);
  await page.waitForTimeout(600);
  await page.screenshot({ path: S("01-initial-panel"), fullPage: false });
});

// ── 2. Chat — user message ────────────────────────────────────────────────────

test("02 chat — user message bubble", async ({ page }) => {
  await stubKnowledge(page);
  await stubLovelace(page);
  await page.route("**/api/kyber/complete", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ response: "…", plan: null, yaml_blocks: [], knowledge_used: [] }),
    })
  );
  await gotoHarness(page);
  // Type but don't send yet — shows the prompt filled
  await page.locator("#prompt-input").fill("Turn off all lights in the living room");
  await page.screenshot({ path: S("02-prompt-filled"), fullPage: false });
});

// ── 3. Chat — AI text response ────────────────────────────────────────────────

test("03 chat — AI text response", async ({ page }) => {
  await stubKnowledge(page);
  await stubLovelace(page);
  await page.route("**/api/kyber/complete", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        response:
          "I've turned off all lights in the living room. " +
          "The following entities are now off: `light.living_room_main`, `light.living_room_lamp`.",
        plan: null,
        yaml_blocks: [],
        knowledge_used: [],
      }),
    })
  );
  await gotoHarness(page);
  await sendMessage(page, "Turn off all lights in the living room");
  await expect(page.locator(".chat-message.assistant").last()).toContainText(
    "turned off all lights",
    { timeout: 8_000 }
  );
  await page.screenshot({ path: S("03-chat-ai-response"), fullPage: false });
});

// ── 4. Chat — AI response with knowledge recall ───────────────────────────────

test("04 chat — knowledge recall (memory badge pulse)", async ({ page }) => {
  await stubKnowledge(page);
  await stubLovelace(page);
  await page.route("**/api/kyber/complete", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        response: "The espresso machine is in the kitchen on `switch.kitchen_espresso`.",
        plan: null,
        yaml_blocks: [],
        knowledge_used: [
          {
            id: "kn-1",
            category: "entity_alias",
            subject: "espresso machine",
            content: "switch.kitchen_espresso",
          },
          {
            id: "kn-2",
            category: "general",
            subject: "switch.kitchen_espresso",
            content: 'switch "Espresso" [switch.kitchen_espresso] in the Kitchen.',
          },
        ],
      }),
    })
  );
  await gotoHarness(page);
  await sendMessage(page, "Where is the espresso machine?");
  await expect(page.locator(".chat-message.assistant").last()).toContainText("espresso", {
    timeout: 8_000,
  });
  // Badge should be pulsing (recalled class)
  await expect(page.locator("#memory-badge")).toHaveClass(/memory-badge--recalled/, {
    timeout: 3_000,
  });
  await page.screenshot({ path: S("04-memory-recall-pulse"), fullPage: false });
});

// ── 5. Memory popover — recalled facts ───────────────────────────────────────

test("05 memory popover — recalled facts", async ({ page }) => {
  await stubKnowledge(page);
  await stubLovelace(page);
  await page.route("**/api/kyber/complete", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        response: "The dishwasher button is `button.dishwasher_start`.",
        plan: null,
        yaml_blocks: [],
        knowledge_used: [
          {
            id: "kn-1",
            category: "entity_alias",
            subject: "start dishwasher",
            content: "button.dishwasher_start",
          },
        ],
      }),
    })
  );
  await gotoHarness(page);
  await sendMessage(page, "Start the dishwasher");
  await expect(page.locator(".chat-message.assistant").last()).toContainText("dishwasher", {
    timeout: 8_000,
  });
  await page.locator("#memory-badge").click();
  await expect(page.locator("#memory-popover")).toBeVisible();
  await page.screenshot({ path: S("05-memory-popover-recalled"), fullPage: false });
});

// ── 6. Plan card — before execute ────────────────────────────────────────────

test("06 plan card — ready to execute", async ({ page }) => {
  await stubKnowledge(page);
  await gotoHarness(page);
  await injectPlanCard(page, {
    summary: "Rename 'Bedroom Light' to 'Slaapkamer Lamp' and move it to the Slaapkamer area",
    actions: [
      { type: "rename_entity", entity_id: "light.bedroom", name: "Slaapkamer Lamp" },
      { type: "assign_area", entity_id: "light.bedroom", area_id: "slaapkamer" },
    ],
  });
  await expect(page.locator(".btn-execute")).toBeVisible();
  await page.screenshot({ path: S("06-plan-card-ready"), fullPage: false });
});

// ── 7. Plan card — after successful execution ─────────────────────────────────

test("07 plan card — execution success + undo button", async ({ page }) => {
  await stubKnowledge(page);
  await page.route("**/api/kyber/execute", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        results: [
          {
            status: "ok",
            undo_action: { type: "rename_entity", entity_id: "light.bedroom", name: "Bedroom Light" },
          },
          {
            status: "ok",
            undo_action: { type: "assign_area", entity_id: "light.bedroom", area_id: null },
          },
        ],
      }),
    })
  );
  await gotoHarness(page);
  await injectPlanCard(page, {
    summary: "Rename bedroom light and assign area",
    actions: [
      { type: "rename_entity", entity_id: "light.bedroom", name: "Slaapkamer Lamp" },
      { type: "assign_area", entity_id: "light.bedroom", area_id: "slaapkamer" },
    ],
  });
  await page.locator(".btn-execute").click();
  await expect(page.locator(".plan-result.success")).toBeVisible({ timeout: 5_000 });
  await expect(page.locator(".btn-undo")).toBeVisible();
  await page.screenshot({ path: S("07-plan-execute-success"), fullPage: false });
});

// ── 8. Plan card — execution error ───────────────────────────────────────────

test("08 plan card — execution error", async ({ page }) => {
  await stubKnowledge(page);
  await page.route("**/api/kyber/execute", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        results: [{ status: "error", message: "Service call failed: light.turn_off is unavailable" }],
      }),
    })
  );
  await gotoHarness(page);
  // Use an entity that exists in the harness mock states so the button is enabled
  await injectPlanCard(page, {
    summary: "Turn off bedroom light (simulated failure)",
    actions: [{ type: "call_service", domain: "light", service: "turn_off", entity_id: "light.bedroom" }],
  });
  await page.locator(".btn-execute").click();
  await expect(page.locator(".plan-result.error")).toBeVisible({ timeout: 5_000 });
  await page.screenshot({ path: S("08-plan-execute-error"), fullPage: false });
});

// ── 9. Plan card — missing entity warning ─────────────────────────────────────

test("09 plan card — missing entity warning", async ({ page }) => {
  await stubKnowledge(page);
  await gotoHarness(page);
  await injectPlanCard(page, {
    summary: "Configure an entity that doesn't exist yet",
    actions: [{ type: "rename_entity", entity_id: "light.nonexistent", name: "Future Lamp" }],
  });
  await expect(page.locator(".plan-warning")).toBeVisible();
  await page.screenshot({ path: S("09-plan-missing-entity"), fullPage: false });
});

// ── 10. Command card — safe action ────────────────────────────────────────────

test("10 command card — safe action ready", async ({ page }) => {
  await stubKnowledge(page);
  await gotoHarness(page);
  await injectCommandCard(page, {
    icon: "💡",
    title: "Turn on living room lights",
    detail: "Calls light.turn_on on light.living_room",
    danger: false,
  });
  await expect(page.locator(".btn-cmd-execute")).toBeVisible();
  await page.screenshot({ path: S("10-command-card-safe"), fullPage: false });
});

// ── 11. Command card — dangerous action ──────────────────────────────────────

test("11 command card — dangerous action", async ({ page }) => {
  await stubKnowledge(page);
  await gotoHarness(page);
  await injectCommandCard(page, {
    icon: "🗑️",
    title: "Delete automation 'Morning Lights'",
    detail: "automation.morning_lights will be permanently removed",
    danger: true,
  });
  const btn = page.locator(".btn-cmd-execute");
  await expect(btn).toHaveClass(/danger/);
  await page.screenshot({ path: S("11-command-card-danger"), fullPage: false });
});

// ── 12. Command card — confirmed (done state) ─────────────────────────────────

test("12 command card — confirmed done", async ({ page }) => {
  await stubKnowledge(page);
  await page.route("**/api/kyber/test-confirm", (route) =>
    route.fulfill({ status: 200, body: "{}" })
  );
  await gotoHarness(page);
  await injectCommandCard(page, {
    icon: "🔧",
    title: "Restart the vacuum",
    detail: "Calls vacuum.start on vacuum.roborock",
  });
  await page.locator(".btn-cmd-execute").click();
  await expect(page.locator(".btn-cmd-execute")).toContainText(/done|✓/i, { timeout: 5_000 });
  await page.screenshot({ path: S("12-command-card-done"), fullPage: false });
});

// ── 13. Autopilot badge active ────────────────────────────────────────────────

test("13 autopilot badge — active", async ({ page }) => {
  await stubKnowledge(page);
  await gotoHarness(page);
  await page.evaluate(() => {
    window.__panel._autopilot = true;
    window.__panel._updateAutopilotBadge();
  });
  await expect(page.locator("#autopilot-badge")).toBeVisible();
  await page.screenshot({ path: S("13-autopilot-badge-active"), fullPage: false });
});

// ── 14. YAML editor — automation context ─────────────────────────────────────

test("14 editor — automation breadcrumb", async ({ page }) => {
  await stubKnowledge(page);
  await gotoHarness(page);
  await page.evaluate(async () => {
    const panel = window.__panel;
    window.__hass.states["automation.morning_lights"] = {
      entity_id: "automation.morning_lights",
      attributes: { id: "morning_lights", friendly_name: "Morning Lights" },
    };
    panel._loadAutomation = async () => {};
    panel._editor = { requestMeasure: () => {} };
    await panel._openEditor("automation.morning_lights");
  });
  await expect(page.locator("#editor-context-label")).toContainText("automation > Morning Lights");
  await page.screenshot({ path: S("14-editor-automation"), fullPage: false });
});

// ── 15. YAML editor — dashboard context ──────────────────────────────────────

test("15 editor — dashboard breadcrumb", async ({ page }) => {
  await stubKnowledge(page);
  await gotoHarness(page);
  await page.evaluate(() => {
    const panel = window.__panel;
    const editorContainer = panel.shadowRoot.getElementById("editor-container");
    if (!panel._editor) panel._initEditor(editorContainer);
    panel.shadowRoot.getElementById("app-container").classList.add("editor-open");
    editorContainer.classList.add("open");
    panel.shadowRoot.querySelectorAll(".editor-controls").forEach((el) => {
      el.style.display = "block";
    });
    panel.shadowRoot.getElementById("editor-context-label").textContent = "Overview (default)";
  });
  await expect(page.locator("#editor-context-label")).toContainText("Overview (default)");
  await page.screenshot({ path: S("15-editor-dashboard"), fullPage: false });
});

// ── 16. Bug report dialog ─────────────────────────────────────────────────────

test("16 bug report dialog", async ({ page }) => {
  await stubKnowledge(page);
  await gotoHarness(page);
  await page.evaluate(async () => {
    await window.__panel._openBugReportFlow("req-abc123");
  });
  await expect(page.locator("#br-submit")).toBeVisible();
  await page.screenshot({ path: S("16-bug-report-dialog"), fullPage: false });
});

// ── 17. Conversation with plan from AI (full flow) ────────────────────────────

test("17 full flow — AI proposes plan via chat", async ({ page }) => {
  await stubKnowledge(page);
  await stubLovelace(page);
  const plan = {
    summary: "Rename 3 entities in the Werkkamer area to Dutch names",
    actions: [
      { type: "rename_entity", entity_id: "switch.monitors_dock", name: "Monitors en dock" },
      { type: "rename_entity", entity_id: "light.desk_lamp", name: "Bureau lamp" },
      { type: "assign_area", entity_id: "light.desk_lamp", area_id: "werkkamer" },
    ],
  };
  await page.route("**/api/kyber/complete", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        response: `Sure! Here's my plan:\n\`\`\`plan\n${JSON.stringify(plan)}\n\`\`\``,
        plan,
        yaml_blocks: [],
        knowledge_used: [],
      }),
    })
  );
  await gotoHarness(page);
  await sendMessage(page, "Rename the werkkamer entities to Dutch names");
  await expect(page.locator(".plan-card")).toBeVisible({ timeout: 8_000 });
  await expect(page.locator(".btn-execute")).toBeVisible();
  await page.screenshot({ path: S("17-full-flow-plan-from-chat"), fullPage: false });
});
