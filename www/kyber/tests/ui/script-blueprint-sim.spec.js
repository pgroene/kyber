/**
 * Playwright UI tests for the Script and Blueprint simulator tabs.
 *
 * Tests the 🧪 Test tab behaviour for script and blueprint editor modes,
 * including flow node rendering, AI-driven run_simulation, and the mock panel.
 */
import { test, expect } from "@playwright/test";
import { gotoHarness } from "./helpers.js";

// ── Script config ─────────────────────────────────────────────────────────────

const SCRIPT_CONFIG = {
  alias: "Test Script",
  description: "A test script",
  fields: {
    brightness: {
      name: "Brightness",
      description: "Light brightness (0-255)",
      example: "128",
    },
    room: {
      name: "Room",
      description: "Target room",
      example: "living_room",
    },
  },
  sequence: [
    { service: "light.turn_on", target: { entity_id: "light.living_room" }, data: { brightness: 128 } },
    { delay: "00:00:05" },
    { service: "light.turn_off", entity_id: "light.living_room" },
  ],
};

// ── Blueprint config ──────────────────────────────────────────────────────────

const BLUEPRINT_CONFIG = {
  blueprint: {
    name: "Motion-activated light",
    domain: "automation",
    input: {
      motion_sensor: {
        name: "Motion Sensor",
        description: "The motion sensor entity",
        selector: { entity: { domain: "binary_sensor" } },
      },
      light_target: {
        name: "Light",
        description: "The light to control",
        default: "light.living_room",
      },
      no_motion_wait: {
        name: "Wait time",
        description: "Seconds to wait after motion clears",
        default: 120,
        selector: { number: { min: 0, max: 3600 } },
      },
    },
  },
  trigger: [{ platform: "state", entity_id: "!input motion_sensor", to: "on" }],
  condition: [],
  action: [
    { service: "light.turn_on", target: { entity_id: "!input light_target" } },
    { wait_for_trigger: [{ platform: "state", entity_id: "!input motion_sensor", to: "off" }] },
    { delay: "00:02:00" },
    { service: "light.turn_off", target: { entity_id: "!input light_target" } },
  ],
};

// ── Helpers ──────────────────────────────────────────────────────────────────

async function openScriptEditor(page) {
  await page.evaluate((cfg) => {
    const panel = window.__panel;
    window.__hass.states["light.living_room"] = { entity_id: "light.living_room", state: "off" };
    panel._hass = window.__hass;
    panel._currentAutomationConfig = cfg;
    panel._currentAutomationId = "test_script";
    panel._editorMode = "script";
    panel.shadowRoot.getElementById("app-container").classList.add("editor-open");
    panel.shadowRoot.getElementById("editor-container").classList.add("open");
    panel.shadowRoot.querySelectorAll(".editor-controls").forEach((el) => (el.style.display = "block"));
    panel._showYamlTab();
    const testBtn = panel.shadowRoot.getElementById("btn-tab-test");
    if (testBtn) testBtn.style.display = "";
    const yamlBtn = panel.shadowRoot.getElementById("btn-tab-yaml");
    if (yamlBtn) yamlBtn.style.display = "";
  }, SCRIPT_CONFIG);
}

async function openBlueprintEditor(page) {
  await page.evaluate((cfg) => {
    const panel = window.__panel;
    panel._hass = window.__hass;
    panel._currentAutomationConfig = cfg;
    panel._currentAutomationId = null;
    panel._currentBlueprintPath = "homeassistant/motion_light.yaml";
    panel._editorMode = "blueprint";
    panel.shadowRoot.getElementById("app-container").classList.add("editor-open");
    panel.shadowRoot.getElementById("editor-container").classList.add("open");
    panel.shadowRoot.querySelectorAll(".editor-controls").forEach((el) => (el.style.display = "block"));
    panel._showYamlTab();
    const testBtn = panel.shadowRoot.getElementById("btn-tab-test");
    if (testBtn) testBtn.style.display = "";
    const yamlBtn = panel.shadowRoot.getElementById("btn-tab-yaml");
    if (yamlBtn) yamlBtn.style.display = "";
  }, BLUEPRINT_CONFIG);
}

async function openTestTab(page) {
  await page.locator("#btn-tab-test").click();
  await expect(page.locator("#sim-pane")).toBeVisible();
}

// ═════════════════════════════════════════════════════════════════════════════
// SCRIPT tests
// ═════════════════════════════════════════════════════════════════════════════

test.describe("Script Simulator", () => {
  test.beforeEach(async ({ page }) => {
    await gotoHarness(page);
    await openScriptEditor(page);
  });

  test("test tab is visible for script editor", async ({ page }) => {
    await expect(page.locator("#btn-tab-test")).toBeVisible();
  });

  test("clicking Test tab shows sim-pane with Script Simulator title", async ({ page }) => {
    await openTestTab(page);
    await expect(page.locator("#sim-pane")).toContainText("Script Simulator");
    await page.screenshot({ path: "screenshots/script-sim-open.png" });
  });

  test("script sim shows SEQUENCE section (not TRIGGERS)", async ({ page }) => {
    await openTestTab(page);
    await expect(page.locator(".sim-section-label").first()).toContainText("SEQUENCE");
    // No TRIGGERS section for scripts
    const labels = await page.locator(".sim-section-label").allTextContents();
    expect(labels.some((l) => l.includes("TRIGGER"))).toBe(false);
  });

  test("script sim shows one node per sequence step", async ({ page }) => {
    await openTestTab(page);
    // SCRIPT_CONFIG has 3 sequence steps
    await expect(page.locator(".sim-node-action")).toHaveCount(3);
  });

  test("script sim action nodes show correct descriptions", async ({ page }) => {
    await openTestTab(page);
    const nodes = page.locator(".sim-node-action");
    await expect(nodes.first()).toContainText("light.turn_on");
    await expect(nodes.nth(1)).toContainText("Delay");
    await expect(nodes.nth(2)).toContainText("light.turn_off");
  });

  test("Run marks all sequence steps sim-pass (scripts always execute)", async ({ page }) => {
    await openTestTab(page);
    // Auto-run already fired; all nodes should be sim-pass
    const nodes = page.locator(".sim-node-action");
    const count = await nodes.count();
    for (let i = 0; i < count; i++) {
      await expect(nodes.nth(i)).toHaveClass(/sim-pass/);
    }
    await page.screenshot({ path: "screenshots/script-sim-pass.png" });
  });

  test("Run button result badge shows Script executed", async ({ page }) => {
    await openTestTab(page);
    await expect(page.locator("#sim-result-badge")).toContainText("Script executed");
    await expect(page.locator("#sim-result-badge")).toHaveClass(/pass/);
  });

  test("script fields are shown in mock panel", async ({ page }) => {
    await openTestTab(page);
    // SCRIPT_CONFIG has two fields: brightness and room
    await expect(page.locator("#sim-mock-panel")).toBeVisible();
    await expect(page.locator("#sim-mock-rows")).toContainText("Brightness");
    await expect(page.locator("#sim-mock-rows")).toContainText("Room");
    await page.screenshot({ path: "screenshots/script-sim-fields.png" });
  });

  test("script field input persists value on change", async ({ page }) => {
    await openTestTab(page);
    const input = page.locator(".sim-script-input[data-key='brightness']").first();
    await input.fill("200");
    await expect(input).toHaveValue("200");
  });

  test("no trigger nodes for scripts", async ({ page }) => {
    await openTestTab(page);
    await expect(page.locator(".sim-node-trigger")).toHaveCount(0);
  });

  test("back button returns to YAML tab", async ({ page }) => {
    await openTestTab(page);
    await page.locator("#sim-back-btn").click();
    await expect(page.locator("#sim-pane")).toBeHidden();
    await expect(page.locator("#btn-tab-test")).not.toHaveClass(/active/);
  });
});

// ═════════════════════════════════════════════════════════════════════════════
// BLUEPRINT tests
// ═════════════════════════════════════════════════════════════════════════════

test.describe("Blueprint Simulator", () => {
  test.beforeEach(async ({ page }) => {
    await gotoHarness(page);
    await openBlueprintEditor(page);
  });

  test("test tab is visible for blueprint editor", async ({ page }) => {
    await expect(page.locator("#btn-tab-test")).toBeVisible();
    await page.screenshot({ path: "screenshots/blueprint-sim-tab-visible.png" });
  });

  test("clicking Test tab shows Blueprint Simulator title", async ({ page }) => {
    await openTestTab(page);
    await expect(page.locator("#sim-pane")).toContainText("Blueprint Simulator");
    await page.screenshot({ path: "screenshots/blueprint-sim-open.png" });
  });

  test("blueprint sim shows TRIGGERS section", async ({ page }) => {
    await openTestTab(page);
    const labels = await page.locator(".sim-section-label").allTextContents();
    expect(labels.some((l) => l.includes("TRIGGER"))).toBe(true);
  });

  test("blueprint sim shows ACTIONS section", async ({ page }) => {
    await openTestTab(page);
    const labels = await page.locator(".sim-section-label").allTextContents();
    expect(labels.some((l) => l.includes("ACTION"))).toBe(true);
  });

  test("blueprint sim shows trigger node", async ({ page }) => {
    await openTestTab(page);
    await expect(page.locator(".sim-node-trigger")).toHaveCount(1);
  });

  test("blueprint sim shows action nodes", async ({ page }) => {
    await openTestTab(page);
    // BLUEPRINT_CONFIG has 4 actions
    await expect(page.locator(".sim-node-action")).toHaveCount(4);
  });

  test("blueprint input fields are shown in mock panel", async ({ page }) => {
    await openTestTab(page);
    await expect(page.locator("#sim-mock-panel")).toBeVisible();
    await expect(page.locator("#sim-mock-rows")).toContainText("Motion Sensor");
    await expect(page.locator("#sim-mock-rows")).toContainText("Light");
    await expect(page.locator("#sim-mock-rows")).toContainText("Wait time");
    await page.screenshot({ path: "screenshots/blueprint-sim-inputs.png" });
  });

  test("blueprint input default value is pre-filled", async ({ page }) => {
    await openTestTab(page);
    const lightInput = page.locator(".sim-blueprint-input[data-key='light_target']");
    await expect(lightInput).toHaveValue("light.living_room");
    const waitInput = page.locator(".sim-blueprint-input[data-key='no_motion_wait']");
    await expect(waitInput).toHaveValue("120");
  });

  test("trigger node is clickable (fire) for blueprint", async ({ page }) => {
    await openTestTab(page);
    const trigNode = page.locator(".sim-node-trigger");
    await trigNode.click();
    await expect(trigNode).toHaveClass(/sim-fired/);
    await page.screenshot({ path: "screenshots/blueprint-sim-trigger-fired.png" });
  });

  test("run button marks actions sim-pass when trigger is fired", async ({ page }) => {
    await openTestTab(page);
    // Fire the trigger manually
    await page.locator(".sim-node-trigger").click();
    await page.locator("#sim-run-btn").click();
    // Trigger should be sim-pass, actions sim-pass
    await expect(page.locator(".sim-node-trigger")).toHaveClass(/sim-pass/);
    const actionNodes = page.locator(".sim-node-action");
    const count = await actionNodes.count();
    for (let i = 0; i < count; i++) {
      await expect(actionNodes.nth(i)).toHaveClass(/sim-pass/);
    }
    await page.screenshot({ path: "screenshots/blueprint-sim-run-pass.png" });
  });

  test("result badge shows Would trigger for blueprints", async ({ page }) => {
    await openTestTab(page);
    await page.locator(".sim-node-trigger").click();
    await page.locator("#sim-run-btn").click();
    await expect(page.locator("#sim-result-badge")).toContainText("Would trigger");
  });

  test("back button returns to YAML tab for blueprint", async ({ page }) => {
    await openTestTab(page);
    await page.locator("#sim-back-btn").click();
    await expect(page.locator("#sim-pane")).toBeHidden();
    await expect(page.locator("#btn-tab-test")).not.toHaveClass(/active/);
  });
});

// ═════════════════════════════════════════════════════════════════════════════
// AI-driven: run_simulation on scripts and blueprints
// ═════════════════════════════════════════════════════════════════════════════

test.describe("AI-driven simulation — scripts", () => {
  test("run_simulation plan block on edit card works for scripts", async ({ page }) => {
    await gotoHarness(page);

    // Inject an edit automation card with script config into chat history
    await page.evaluate((cfg) => {
      const panel = window.__panel;
      window.__hass.states["light.living_room"] = { entity_id: "light.living_room", state: "off" };
      panel._hass = window.__hass;
      // Build a fake automation-edit-card with script config
      const history = panel.shadowRoot.getElementById("chat-history");
      const card = document.createElement("div");
      card.className = "automation-edit-card";
      card.dataset.automationId = "script_test_ai";
      card.innerHTML = `<div class="ae-btn-expand" style="cursor:pointer">Expand</div>`;
      card.querySelector(".ae-btn-expand").addEventListener("click", () => {
        const testBtn = document.createElement("button");
        testBtn.className = "ae-btn-test";
        card.appendChild(testBtn);
        testBtn.addEventListener("click", () => {
          const tester = document.createElement("div");
          tester.className = "ae-tester";
          card.appendChild(tester);
          panel._buildAutomationTester(cfg, "script_test_ai", tester);
        });
      });
      history.appendChild(card);
    }, SCRIPT_CONFIG);

    // Expand the card
    await page.locator(".ae-btn-expand").first().click();

    // Trigger AI-driven simulation
    await page.evaluate(() => {
      window.__panel._handleRunSimulation({
        run_simulation: true,
        automation_id: "script_test_ai",
        mocks: {},
      });
    });

    // Tester should be visible with sim-result-badge
    await expect(page.locator(".ae-tester").first()).toBeVisible({ timeout: 3000 });
    await expect(page.locator(".sim-result-badge").first()).toBeVisible({ timeout: 3000 });
    await expect(page.locator(".sim-result-badge").first()).toContainText("Script executed");
    await page.screenshot({ path: "screenshots/script-sim-ai-run.png" });
  });
});
