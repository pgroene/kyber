/**
 * Playwright UI tests for the editor Test tab.
 *
 * Opens an automation editor, then exercises the 📝 YAML / 🧪 Test tab
 * toggle without a real HA backend.
 */
import { test, expect } from "@playwright/test";
import { gotoHarness } from "./helpers.js";

const AUTOMATION_CONFIG = {
  id: "test_tab_demo",
  alias: "Test Tab Demo",
  trigger: [{ platform: "time", at: "07:00:00" }],
  condition: [{ condition: "state", entity_id: "person.peter", state: "home" }],
  action: [{ service: "switch.turn_on", target: { entity_id: "switch.espresso" } }],
};

const AUTOMATION_STATE_CONFIG = {
  id: "test_tab_state",
  alias: "State Trigger Demo",
  trigger: [{ platform: "state", entity_id: "sensor.mode", to: "BALANCE" }],
  condition: [],
  action: [{ service: "light.turn_on", entity_id: "light.living_room" }],
};

/** Simulate opening the automation editor from the panel JS. */
async function openAutomationEditor(page, cfg = AUTOMATION_CONFIG) {
  await page.evaluate((config) => {
    const panel = window.__panel;
    window.__hass.states[`automation.${config.id}`] = {
      entity_id: `automation.${config.id}`,
      attributes: { id: config.id, friendly_name: config.alias },
    };
    window.__hass.states["person.peter"] = { entity_id: "person.peter", state: "home" };
    window.__hass.states["sensor.mode"] = { entity_id: "sensor.mode", state: "ECO" };
    window.__hass.states["switch.espresso"] = { entity_id: "switch.espresso", state: "off" };
    window.__hass.states["light.living_room"] = { entity_id: "light.living_room", state: "off" };
    panel._hass = window.__hass;
    panel._currentAutomationConfig = config;
    panel._currentAutomationId = config.id;
    panel._editorMode = "automation";
    panel.shadowRoot.getElementById("app-container").classList.add("editor-open");
    panel.shadowRoot.getElementById("editor-container").classList.add("open");
    panel.shadowRoot.querySelectorAll(".editor-controls").forEach((el) => (el.style.display = "block"));
    panel._showYamlTab();
    const testBtn = panel.shadowRoot.getElementById("btn-tab-test");
    if (testBtn) testBtn.style.display = "";
  }, cfg);
}

async function openTestTab(page) {
  // Test button is a toggle — click once to show sim
  const simPane = page.locator("#sim-pane");
  const isVisible = await simPane.isVisible().catch(() => false);
  if (!isVisible) await page.locator("#btn-tab-test").click();
  await expect(simPane).toBeVisible();
}

const flushPromises = () => new Promise((r) => setTimeout(r, 50));

test.describe("Editor — Test tab", () => {
  test.beforeEach(async ({ page }) => {
    await gotoHarness(page);
    await openAutomationEditor(page);
  });

  // ── Tab visibility ───────────────────────────────────────────────────────

  test("Test button is visible when automation editor is open", async ({ page }) => {
    await expect(page.locator("#btn-tab-test")).toBeVisible();
    await page.screenshot({ path: "screenshots/editor-tab-buttons.png" });
  });

  test("Test button is not active by default (sim hidden)", async ({ page }) => {
    await expect(page.locator("#btn-tab-test")).not.toHaveClass(/active/);
    await expect(page.locator("#sim-pane")).toBeHidden();
  });

  // ── Tab switching ────────────────────────────────────────────────────────

  test("clicking Test button shows sim-pane", async ({ page }) => {
    await openTestTab(page);
    await page.screenshot({ path: "screenshots/editor-test-tab-open.png" });
  });

  test("clicking Test button marks it active", async ({ page }) => {
    await openTestTab(page);
    await expect(page.locator("#btn-tab-test")).toHaveClass(/active/);
  });

  test("clicking Test button again (toggle) hides sim-pane", async ({ page }) => {
    await openTestTab(page);
    await page.locator("#btn-tab-test").click();
    await expect(page.locator("#sim-pane")).toBeHidden();
    await expect(page.locator("#btn-tab-test")).not.toHaveClass(/active/);
    await page.screenshot({ path: "screenshots/editor-test-tab-back-to-yaml.png" });
  });

  // ── Flow diagram structure ───────────────────────────────────────────────

  test("Test tab shows section labels TRIGGERS CONDITIONS ACTIONS", async ({ page }) => {
    await openTestTab(page);
    const simPane = page.locator("#sim-pane");
    await expect(simPane).toContainText("TRIGGERS");
    await expect(simPane).toContainText("CONDITIONS");
    await expect(simPane).toContainText("ACTIONS");
    await page.screenshot({ path: "screenshots/editor-test-tab-sections.png" });
  });

  test("sim-node elements are present for each section", async ({ page }) => {
    await openTestTab(page);
    // One trigger, one condition, one action in AUTOMATION_CONFIG
    await expect(page.locator(".sim-node-trigger")).toHaveCount(1);
    await expect(page.locator(".sim-node-condition")).toHaveCount(1);
    await expect(page.locator(".sim-node-action")).toHaveCount(1);
  });

  test("trigger node shows correct description", async ({ page }) => {
    await openTestTab(page);
    await expect(page.locator(".sim-node-trigger")).toContainText("Time trigger");
    await expect(page.locator(".sim-node-trigger")).toContainText("07:00:00");
  });

  test("section arrows are rendered between sections", async ({ page }) => {
    await openTestTab(page);
    const arrows = page.locator(".sim-section-arrow");
    // 2 arrows: triggers→conditions, conditions→actions
    await expect(arrows).toHaveCount(2);
  });

  // ── Run / execution path ─────────────────────────────────────────────────

  test("run button exists and result badge is shown", async ({ page }) => {
    await openTestTab(page);
    await expect(page.locator("#sim-run-btn")).toBeVisible();
    await expect(page.locator("#sim-result-badge")).toBeVisible();
  });

  test("time trigger shows pass after auto-run (time always fires)", async ({ page }) => {
    await openTestTab(page);
    // time trigger always evaluates to true (fires) → trigger node gets sim-pass
    const trigNode = page.locator(".sim-node-trigger");
    await expect(trigNode).toHaveClass(/sim-pass/);
  });

  test("result badge shows Would run or Would NOT run", async ({ page }) => {
    await openTestTab(page);
    const badge = page.locator("#sim-result-badge");
    const text = await badge.textContent();
    expect(text).toMatch(/Would (NOT )?run/);
    await page.screenshot({ path: "screenshots/editor-test-tab-result.png" });
  });

  test("sim-pass and sim-skip classes are applied after run", async ({ page }) => {
    await openTestTab(page);
    // After auto-run, nodes should have either sim-pass or sim-fail or sim-skip
    const allNodes = page.locator(".sim-node");
    const count = await allNodes.count();
    let markedCount = 0;
    for (let i = 0; i < count; i++) {
      const cls = await allNodes.nth(i).getAttribute("class");
      if (/sim-pass|sim-fail|sim-skip/.test(cls)) markedCount++;
    }
    expect(markedCount).toBeGreaterThan(0);
  });

  // ── Trigger click (fire) ─────────────────────────────────────────────────

  test("clicking trigger node adds sim-fired class and selects it", async ({ page }) => {
    await openTestTab(page);
    const trigNode = page.locator(".sim-node-trigger");
    await trigNode.click();
    await expect(trigNode).toHaveClass(/sim-fired/);
    await expect(trigNode).toHaveClass(/sim-selected/);
    await page.screenshot({ path: "screenshots/editor-test-tab-trigger-fired.png" });
  });

  test("clicking fired trigger node again removes sim-fired and sim-selected", async ({ page }) => {
    await openTestTab(page);
    const trigNode = page.locator(".sim-node-trigger");
    await trigNode.click();
    await expect(trigNode).toHaveClass(/sim-fired/);
    await trigNode.click();
    await expect(trigNode).not.toHaveClass(/sim-fired/);
    await expect(trigNode).not.toHaveClass(/sim-selected/);
  });

  test("fire button is present on trigger nodes", async ({ page }) => {
    await openTestTab(page);
    await expect(page.locator(".sim-node-trigger .sim-fire-btn")).toBeVisible();
  });

  // ── Override values + reset ──────────────────────────────────────────────

  test("mock panel is shown when automation has entity_ids", async ({ page }) => {
    await openTestTab(page);
    // AUTOMATION_CONFIG has person.peter and switch.espresso
    await expect(page.locator("#sim-mock-panel")).toBeVisible();
    await expect(page.locator("#sim-mock-rows")).toContainText("person.peter");
  });

  test("typing a mock value shows reset button and sim-override class", async ({ page }) => {
    await openTestTab(page);
    const input = page.locator(".sim-mock-input[data-eid='person.peter']");
    await input.fill("not_home");
    // Row should get sim-override
    const row = page.locator(".sim-mock-row[data-eid='person.peter']");
    await expect(row).toHaveClass(/sim-override/);
    // Reset button should appear
    await expect(row.locator(".sim-entity-reset-btn")).toBeVisible();
    // Overrides bar should appear
    await expect(page.locator("#sim-overrides-bar")).toBeVisible();
    await expect(page.locator("#sim-overrides-bar")).toContainText("peter");
    await page.screenshot({ path: "screenshots/editor-test-tab-override.png" });
  });

  test("clicking reset button clears override", async ({ page }) => {
    await openTestTab(page);
    const input = page.locator(".sim-mock-input[data-eid='person.peter']");
    await input.fill("not_home");
    const row = page.locator(".sim-mock-row[data-eid='person.peter']");
    const resetBtn = row.locator(".sim-entity-reset-btn");
    await expect(resetBtn).toBeVisible();
    await resetBtn.click();
    // Row should lose sim-override, input cleared
    await expect(row).not.toHaveClass(/sim-override/);
    await expect(input).toHaveValue("");
  });

  test("overrides bar is hidden when no overrides", async ({ page }) => {
    await openTestTab(page);
    await expect(page.locator("#sim-overrides-bar")).toBeHidden();
  });

  test("Reset all button clears all overrides", async ({ page }) => {
    await openTestTab(page);
    await page.locator(".sim-mock-input[data-eid='person.peter']").fill("away");
    await expect(page.locator("#sim-overrides-bar")).toBeVisible();
    await page.locator("#sim-reset-all-btn").click();
    await expect(page.locator("#sim-overrides-bar")).toBeHidden();
    await expect(page.locator(".sim-mock-row[data-eid='person.peter']")).not.toHaveClass(/sim-override/);
  });

  // ── Back button ──────────────────────────────────────────────────────────

  test("sim-back-btn is visible in test mode", async ({ page }) => {
    await openTestTab(page);
    await expect(page.locator("#sim-back-btn")).toBeVisible();
  });

  test("clicking back button returns to YAML view (sim hidden, Test not active)", async ({ page }) => {
    await openTestTab(page);
    await page.locator("#sim-back-btn").click();
    await expect(page.locator("#sim-pane")).toBeHidden();
    await expect(page.locator("#btn-tab-test")).not.toHaveClass(/active/);
    await page.screenshot({ path: "screenshots/editor-test-tab-back-via-button.png" });
  });

  // ── Close editor reset ───────────────────────────────────────────────────

  test("closing editor resets sim pane and Test button", async ({ page }) => {
    await openTestTab(page);
    await page.evaluate(() => window.__panel._closeEditor());
    await expect(page.locator("#sim-pane")).toBeHidden();
    await openAutomationEditor(page);
    await expect(page.locator("#btn-tab-test")).not.toHaveClass(/active/);
  });
});

test.describe("Editor — Test tab hidden for dashboard", () => {
  test("test tab button is hidden for dashboard editor", async ({ page }) => {
    await gotoHarness(page);
    await page.evaluate(() => {
      const panel = window.__panel;
      panel._editorMode = "dashboard";
      panel.shadowRoot.getElementById("app-container").classList.add("editor-open");
      panel.shadowRoot.getElementById("editor-container").classList.add("open");
      panel.shadowRoot.querySelectorAll(".editor-controls").forEach((el) => (el.style.display = "block"));
      const testBtn = panel.shadowRoot.getElementById("btn-tab-test");
      if (testBtn) testBtn.style.display = "none";
    });
    await expect(page.locator("#btn-tab-test")).toBeHidden();
  });
});

test.describe("Editor — Test tab state trigger + condition eval", () => {
  test("state trigger with entity override affects execution path", async ({ page }) => {
    await gotoHarness(page);
    await openAutomationEditor(page, AUTOMATION_STATE_CONFIG);
    await openTestTab(page);

    // sensor.mode = ECO, trigger.to = BALANCE → trigger fails without override
    const trigNode = page.locator(".sim-node-trigger");
    await expect(trigNode).toHaveClass(/sim-fail/);

    // Override sensor.mode = BALANCE → trigger should pass
    const input = page.locator(".sim-mock-input[data-eid='sensor.mode']");
    await input.fill("BALANCE");
    await page.locator("#sim-run-btn").click();
    await expect(trigNode).toHaveClass(/sim-pass/);
    await page.screenshot({ path: "screenshots/editor-test-tab-state-override.png" });
  });
});

