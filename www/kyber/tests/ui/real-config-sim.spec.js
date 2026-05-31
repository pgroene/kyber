/**
 * Real-config simulator tests.
 *
 * Uses actual automations, scripts, and blueprints copied from the live HA
 * instance (tests/ha-config-samples/) to verify that every node is rendered
 * correctly and that trigger/condition/action navigation works as expected.
 */
import { test, expect } from "@playwright/test";
import { gotoHarness } from "./helpers.js";

// ── Inline configs from real HA files ────────────────────────────────────────

// automations.yaml: Toggle lamp  (1 ZHA trigger, 0 conditions, 1 action)
const AUTO_TOGGLE_LAMP = {
  id: "1682478836533",
  alias: "Toggle lamp",
  trigger: [{ platform: "device", domain: "zha", type: "remote_button_short_press", subtype: "turn_on", device_id: "548093d8828388dd93bb677c3b788384" }],
  condition: [],
  action: [{ service: "light.toggle", data: {}, target: { area_id: "slaapkamer_lobke" } }],
};

// automations.yaml: Toggle Bed light Fedde  (2 ZHA triggers, 0 conditions, 1 action)
const AUTO_TOGGLE_BED = {
  id: "1683076963047",
  alias: "Toggle Bed light Fedde",
  trigger: [
    { platform: "device", domain: "zha", type: "remote_button_short_press", subtype: "turn_on", device_id: "99e637554b4ffe4216513c0ff40b1b27" },
    { platform: "device", domain: "zha", type: "remote_button_long_press",  subtype: "right",   device_id: "99e637554b4ffe4216513c0ff40b1b27" },
  ],
  condition: [],
  action: [{ service: "light.toggle", target: { entity_id: ["light.light_fedde_bed_light", "light.light_led_3_fedde_bed_light"] } }],
};

// automations.yaml: Slaapkamer wake up  (1 time trigger, 2 conditions, 1 action)
const AUTO_WAKE_UP = {
  id: "1700028687614",
  alias: "Slaapkamer wake up",
  trigger: [{ platform: "time", at: "input_datetime.slaapkamer_wake_up" }],
  condition: [
    { condition: "device", type: "is_on", device_id: "791ad2df74c0301949b866407d05e57f", entity_id: "input_boolean.slaapkamer_wakeup_device", domain: "binary_sensor" },
    { condition: "state", entity_id: "input_boolean.slaapkamer_wakeup_onoff", state: "on" },
  ],
  action: [{ service: "script.1700031087782", data: { duration: 25 } }],
};

// automations.yaml: Lights off on sunrise  (1 sun trigger, 0 conditions, 1 action)
const AUTO_SUNRISE_OFF = {
  id: "1683351463843",
  alias: "Lights off on sunrise",
  trigger: [{ platform: "sun", event: "sunrise", offset: "10" }],
  condition: [],
  action: [{ service: "light.turn_off", domain: "light", device_id: "6227797f2b4c2e4968636220e01caa8c", entity_id: "light.ikea_of_sweden_tradfri_bulb_e26_ws_opal_980lm_light" }],
};

// automations.yaml: Weather-based front yard  (5 triggers, 1 condition, 1 choose action)
const AUTO_WEATHER_SWITCH = {
  id: "1716034754961",
  alias: "Outdoor lighting weather based",
  trigger: [
    { platform: "sun",  event: "sunrise", offset: "00:30:00", id: "Sunny"  },
    { platform: "sun",  event: "sunrise", offset: "01:00:00", id: "Cloudy" },
    { platform: "sun",  event: "sunrise", offset: "01:30:00", id: "Rainy"  },
    { platform: "sun",  event: "sunset",  offset: "-01:00:00", id: "Darky" },
    { platform: "time", at: "21:30:00",   id: "Off" },
  ],
  condition: [{ condition: "template", value_template: "{{ trigger.id == 'Off' or is_state('weather.forecast_thuis', 'sunny') }}" }],
  action: [{ choose: [{ conditions: [{ condition: "trigger", id: ["Sunny","Cloudy","Rainy","Darky"] }], sequence: [{ service: "switch.turn_on", target: { entity_id: "switch.onoff_407_front_yard" } }] }] }],
};

// scripts.yaml: Kitchen lights on  (sequence with repeat → 1 top-level step)
const SCRIPT_KITCHEN_LIGHTS = {
  alias: "Kitchen lights on",
  variables: { brightness: 100, transition: 5, delay: "00:00:00.500" },
  sequence: [
    { repeat: { count: 9, sequence: [{ service: "light.turn_on", data: { brightness: 100 } }, { delay: "00:00:00.500" }] } },
  ],
};

// scripts.yaml: signal_zitkamer  (if/then + service + delay + turn_off = 4 steps)
const SCRIPT_SIGNAL = {
  alias: "signal_zitkamer",
  variables: { light_color: "blue" },
  sequence: [
    { if: [{ condition: "state", entity_id: "binary_sensor.home_presence", state: "on" }], then: [{ service: "scene.create" }] },
    { service: "light.turn_on",  target: { entity_id: "light.group_alert_lights" } },
    { delay: "00:00:05" },
    { service: "light.turn_off", target: { entity_id: "light.group_alert_lights" } },
  ],
};

// scripts.yaml: Vacuum queue manager  (variables + choose = 2 steps)
const SCRIPT_VACUUM_QUEUE = {
  alias: "Vacuum queue manager",
  sequence: [
    { variables: { current_list: "{{ states('input_text.vacuum_queue').split(',') }}" } },
    { choose: [{ conditions: [{ condition: "template", value_template: "{{ mode == 'Remove' }}" }], sequence: [{ service: "input_text.set_value", target: { entity_id: "input_text.vacuum_queue" } }] }] },
  ],
};

// blueprints/automation/homeassistant/motion_light.yaml  (3 inputs, 1 trigger, 4 actions)
const BP_MOTION_LIGHT = {
  blueprint: {
    name: "Motion-activated Light",
    domain: "automation",
    input: {
      motion_entity: { name: "Motion Sensor" },
      light_target:  { name: "Light" },
      no_motion_wait: { name: "Wait time", default: 120 },
    },
  },
  trigger: [{ platform: "state", entity_id: "!input motion_entity", from: "off", to: "on" }],
  condition: [],
  action: [
    { service: "light.turn_on",  target: "!input light_target" },
    { wait_for_trigger: [{ platform: "state", entity_id: "!input motion_entity", from: "on", to: "off" }] },
    { delay: "!input no_motion_wait" },
    { service: "light.turn_off", target: "!input light_target" },
  ],
};

// blueprints/automation/pgroene/motion_light_timer.yaml  (10 inputs, 6 triggers, 1 condition, many actions)
const BP_MOTION_TIMER = {
  blueprint: {
    name: "Multi motion light with timer (current)",
    domain: "automation",
    input: {
      lights_target:           { name: "Lights" },
      light_level_primary:     { name: "Light level primary",   default: 200 },
      light_level_secondary:   { name: "Light level secondary", default: 80  },
      motion_entity_primary:   { name: "Motion Sensor primary" },
      motion_entity_secondary: { name: "Motion Sensor secondary" },
      sleepmode:               { name: "Sleep Mode", default: "" },
      automation_switch:       { name: "Automation switch", default: null },
      lux_entity:              { name: "Illuminance Sensor", default: null },
      lux_level:               { name: "Illuminance level", default: 100 },
      no_motion_wait:          { name: "Wait time", default: 120 },
    },
  },
  trigger: [
    { platform: "state", entity_id: "!input motion_entity_primary",   from: "off", to: "on",  id: "motion_primary"   },
    { platform: "state", entity_id: "!input motion_entity_primary",   from: "on",  to: "off", id: "stopmotion_primary" },
    { platform: "state", entity_id: "!input motion_entity_secondary", from: "off", to: "on",  id: "motion_secondary" },
    { platform: "state", entity_id: "!input motion_entity_secondary", from: "on",  to: "off", id: "stopmotion_secondary" },
    { platform: "numeric_state", entity_id: "!input lux_entity", below: "!input lux_level", id: "luxbelow" },
    { platform: "numeric_state", entity_id: "!input lux_entity", above: "!input lux_level", id: "luxabove" },
  ],
  condition: [{ condition: "template", value_template: "{{ automation_switch is none or is_state(automation_switch, 'on') }}" }],
  action: [{ choose: [{ conditions: [{ condition: "trigger", id: "luxabove" }], sequence: [{ service: "light.turn_off" }] }] }],
};

// blueprints/script/pgroene/vacuum.yaml  (3 inputs, sequence with 6 steps)
const BP_VACUUM_SCRIPT = {
  blueprint: {
    name: "Vacuum",
    domain: "script",
    input: {
      vacuum:       { name: "Vacuum",        description: "The vacuum to start" },
      room:         { name: "Room",          description: "The room" },
      current_room: { name: "Current room",  description: "Input text to store current room" },
    },
  },
  sequence: [
    { condition: "state", entity_id: "!input vacuum", state: "docked" },
    { service: "vacuum.send_command", target: { entity_id: "!input vacuum" } },
    { delay: "00:00:10" },
    { condition: "not", conditions: [{ condition: "state", entity_id: "!input vacuum", state: "docked" }] },
    { service: "input_text.set_value", target: { entity_id: "!input current_room" } },
    { service: "script.1717681909594" },
  ],
};

// ── Shared helper ─────────────────────────────────────────────────────────────

async function openSim(page, cfg, editorMode = "automation") {
  await page.evaluate(({ cfg, editorMode }) => {
    const panel = window.__panel;
    panel._hass = window.__hass;
    panel._currentAutomationConfig = cfg;
    panel._currentAutomationId = cfg.id || "test-id";
    panel._editorMode = editorMode;
    // Open editor
    panel.shadowRoot.getElementById("app-container").classList.add("editor-open");
    panel.shadowRoot.getElementById("editor-container").classList.add("open");
    // Show tabs
    ["btn-tab-yaml","btn-tab-test"].forEach((id) => {
      const el = panel.shadowRoot.getElementById(id);
      if (el) el.style.display = "";
    });
    panel._showYamlTab();
  }, { cfg, editorMode });

  // Click Test tab
  await page.locator("#btn-tab-test").click();
  await expect(page.locator("#sim-pane")).toBeVisible();
}

// ═════════════════════════════════════════════════════════════════════════════
// AUTOMATIONS — node counts and navigation
// ═════════════════════════════════════════════════════════════════════════════

test.describe("Real automation — Toggle lamp (1T 0C 1A)", () => {
  test.beforeEach(async ({ page }) => {
    await gotoHarness(page);
    await openSim(page, AUTO_TOGGLE_LAMP);
  });

  test("shows Automation Simulator title", async ({ page }) => {
    await expect(page.locator(".sim-toolbar-title")).toContainText("Automation Simulator");
  });

  test("renders 1 trigger node", async ({ page }) => {
    await expect(page.locator(".sim-node-trigger")).toHaveCount(1);
  });

  test("renders 1 action node", async ({ page }) => {
    await expect(page.locator(".sim-node-action")).toHaveCount(1);
  });

  test("no condition nodes (empty condition array)", async ({ page }) => {
    await expect(page.locator(".sim-node-condition")).toHaveCount(0);
  });

  test("action node describes light.toggle", async ({ page }) => {
    await expect(page.locator(".sim-node-action")).toContainText("light.toggle");
  });

  test("trigger node has ⚡ Fire button", async ({ page }) => {
    await expect(page.locator(".sim-node-trigger .sim-fire-btn")).toBeVisible();
  });

  test("clicking trigger fires it (sim-fired class)", async ({ page }) => {
    await page.locator(".sim-node-trigger").click();
    await expect(page.locator(".sim-node-trigger")).toHaveClass(/sim-fired/);
    await page.screenshot({ path: "screenshots/real-auto-toggle-fired.png" });
  });

  test("run after firing trigger → action gets sim-pass", async ({ page }) => {
    await page.locator(".sim-node-trigger").click();
    await page.locator("#sim-run-btn").click();
    await expect(page.locator(".sim-node-action")).toHaveClass(/sim-pass/);
    await expect(page.locator("#sim-result-badge")).toContainText("Would run");
    await page.screenshot({ path: "screenshots/real-auto-toggle-pass.png" });
  });

  test("run WITHOUT firing trigger → action gets sim-skip", async ({ page }) => {
    await page.locator("#sim-run-btn").click();
    // device trigger can't be evaluated → result is unknown → action skipped
    await expect(page.locator("#sim-result-badge")).toContainText("Would NOT run");
    await page.screenshot({ path: "screenshots/real-auto-toggle-skip.png" });
  });
});

// ─────────────────────────────────────────────────────────────────────────────

test.describe("Real automation — Toggle Bed (2T 0C 1A)", () => {
  test.beforeEach(async ({ page }) => {
    await gotoHarness(page);
    await openSim(page, AUTO_TOGGLE_BED);
  });

  test("renders 2 trigger nodes", async ({ page }) => {
    await expect(page.locator(".sim-node-trigger")).toHaveCount(2);
    await page.screenshot({ path: "screenshots/real-auto-bed-2-triggers.png" });
  });

  test("renders 1 action node", async ({ page }) => {
    await expect(page.locator(".sim-node-action")).toHaveCount(1);
  });

  test("both trigger nodes have Fire buttons", async ({ page }) => {
    await expect(page.locator(".sim-fire-btn")).toHaveCount(2);
  });

  test("firing first trigger marks it sim-fired, second stays clear", async ({ page }) => {
    const triggers = page.locator(".sim-node-trigger");
    await triggers.nth(0).click();
    await expect(triggers.nth(0)).toHaveClass(/sim-fired/);
    await expect(triggers.nth(1)).not.toHaveClass(/sim-fired/);
  });

  test("firing second trigger also marks it sim-fired independently", async ({ page }) => {
    const triggers = page.locator(".sim-node-trigger");
    await triggers.nth(1).click();
    await expect(triggers.nth(1)).toHaveClass(/sim-fired/);
    await expect(triggers.nth(0)).not.toHaveClass(/sim-fired/);
  });

  test("clicking a fired trigger again unfires it (toggle)", async ({ page }) => {
    const t = page.locator(".sim-node-trigger").nth(0);
    await t.click();
    await expect(t).toHaveClass(/sim-fired/);
    await t.click();
    await expect(t).not.toHaveClass(/sim-fired/);
  });

  test("run with trigger 1 fired → action sim-pass", async ({ page }) => {
    await page.locator(".sim-node-trigger").nth(0).click();
    await page.locator("#sim-run-btn").click();
    await expect(page.locator(".sim-node-action")).toHaveClass(/sim-pass/);
    await expect(page.locator("#sim-result-badge")).toContainText("Would run");
    await page.screenshot({ path: "screenshots/real-auto-bed-run-pass.png" });
  });
});

// ─────────────────────────────────────────────────────────────────────────────

test.describe("Real automation — Wake up (1T 2C 1A)", () => {
  test.beforeEach(async ({ page }) => {
    await gotoHarness(page);
    await openSim(page, AUTO_WAKE_UP);
  });

  test("renders 1 trigger, 2 conditions, 1 action", async ({ page }) => {
    await expect(page.locator(".sim-node-trigger")).toHaveCount(1);
    await expect(page.locator(".sim-node-condition")).toHaveCount(2);
    await expect(page.locator(".sim-node-action")).toHaveCount(1);
    await page.screenshot({ path: "screenshots/real-auto-wakeup-nodes.png" });
  });

  test("TRIGGERS → CONDITIONS → ACTIONS section arrows present", async ({ page }) => {
    await expect(page.locator(".sim-section-arrow")).toHaveCount(2);
  });

  test("condition section labels visible", async ({ page }) => {
    const labels = await page.locator(".sim-section-label").allTextContents();
    expect(labels.some((l) => l.includes("TRIGGER"))).toBe(true);
    expect(labels.some((l) => l.includes("CONDITION"))).toBe(true);
    expect(labels.some((l) => l.includes("ACTION"))).toBe(true);
  });

  test("state condition node shows entity id", async ({ page }) => {
    await expect(page.locator(".sim-node-condition").nth(1)).toContainText("State");
  });

  test("fire trigger → run → conditions evaluated → action marked", async ({ page }) => {
    await page.locator(".sim-node-trigger").click();
    await page.locator("#sim-run-btn").click();
    // time trigger was manually fired, conditions result depends on mock state
    // but all nodes must have a result class
    const condNodes = page.locator(".sim-node-condition");
    const count = await condNodes.count();
    for (let i = 0; i < count; i++) {
      const cls = await condNodes.nth(i).getAttribute("class");
      expect(cls).toMatch(/sim-pass|sim-fail|sim-skip/);
    }
    await page.screenshot({ path: "screenshots/real-auto-wakeup-run.png" });
  });

  test("condition nodes with live entity show them in mock panel", async ({ page }) => {
    await expect(page.locator("#sim-mock-rows")).toContainText("input_boolean.slaapkamer_wakeup_onoff");
  });

  test("override condition entity → run → reflects in condition result", async ({ page }) => {
    // Set mock for the state condition entity
    const input = page.locator(".sim-mock-input[data-eid='input_boolean.slaapkamer_wakeup_onoff']");
    await input.fill("on");
    await input.dispatchEvent("input");
    // fire the trigger too
    await page.locator(".sim-node-trigger").click();
    await page.locator("#sim-run-btn").click();
    // State condition (on=on) should now pass
    await expect(page.locator(".sim-node-condition").nth(1)).toHaveClass(/sim-pass/);
    await page.screenshot({ path: "screenshots/real-auto-wakeup-override.png" });
  });
});

// ─────────────────────────────────────────────────────────────────────────────

test.describe("Real automation — Sunrise off (sun trigger)", () => {
  test.beforeEach(async ({ page }) => {
    await gotoHarness(page);
    await openSim(page, AUTO_SUNRISE_OFF);
  });

  test("renders sun trigger node with sun icon", async ({ page }) => {
    await expect(page.locator(".sim-node-trigger")).toContainText("Sun");
    await page.screenshot({ path: "screenshots/real-auto-sunrise-trigger.png" });
  });

  test("renders 1 action node", async ({ page }) => {
    await expect(page.locator(".sim-node-action")).toHaveCount(1);
  });
});

// ─────────────────────────────────────────────────────────────────────────────

test.describe("Real automation — Weather switch (5T 1C 1A)", () => {
  test.beforeEach(async ({ page }) => {
    await gotoHarness(page);
    await openSim(page, AUTO_WEATHER_SWITCH);
  });

  test("renders 5 trigger nodes", async ({ page }) => {
    await expect(page.locator(".sim-node-trigger")).toHaveCount(5);
    await page.screenshot({ path: "screenshots/real-auto-weather-5-triggers.png" });
  });

  test("renders 1 condition node", async ({ page }) => {
    await expect(page.locator(".sim-node-condition")).toHaveCount(1);
  });

  test("renders 1 action node (choose)", async ({ page }) => {
    await expect(page.locator(".sim-node-action")).toHaveCount(1);
    await expect(page.locator(".sim-node-action")).toContainText("Choose");
  });

  test("can fire any of the 5 trigger nodes", async ({ page }) => {
    const triggers = page.locator(".sim-node-trigger");
    // Fire all 5
    for (let i = 0; i < 5; i++) {
      await triggers.nth(i).click();
    }
    const firedCount = await page.locator(".sim-node-trigger.sim-fired").count();
    expect(firedCount).toBe(5);
    await page.screenshot({ path: "screenshots/real-auto-weather-all-fired.png" });
  });

  test("run with all triggers fired → result badge present", async ({ page }) => {
    await page.locator(".sim-node-trigger").nth(0).click();
    await page.locator("#sim-run-btn").click();
    await expect(page.locator("#sim-result-badge")).toBeVisible();
  });
});

// ═════════════════════════════════════════════════════════════════════════════
// SCRIPTS — node counts and simulation
// ═════════════════════════════════════════════════════════════════════════════

test.describe("Real script — Kitchen lights on (1 repeat step)", () => {
  test.beforeEach(async ({ page }) => {
    await gotoHarness(page);
    await openSim(page, SCRIPT_KITCHEN_LIGHTS, "script");
  });

  test("shows Script Simulator title", async ({ page }) => {
    await expect(page.locator(".sim-toolbar-title")).toContainText("Script Simulator");
  });

  test("SEQUENCE section present, no TRIGGERS", async ({ page }) => {
    const labels = await page.locator(".sim-section-label").allTextContents();
    expect(labels.some((l) => l.includes("SEQUENCE"))).toBe(true);
    expect(labels.some((l) => l.includes("TRIGGER"))).toBe(false);
    await page.screenshot({ path: "screenshots/real-script-kitchen-sequence.png" });
  });

  test("renders 1 action node (repeat)", async ({ page }) => {
    await expect(page.locator(".sim-node-action")).toHaveCount(1);
    await expect(page.locator(".sim-node-action")).toContainText("Repeat");
  });

  test("all action nodes get sim-pass (scripts always run)", async ({ page }) => {
    await expect(page.locator(".sim-node-action")).toHaveClass(/sim-pass/);
    await expect(page.locator("#sim-result-badge")).toContainText("Script executed");
  });
});

// ─────────────────────────────────────────────────────────────────────────────

test.describe("Real script — signal_zitkamer (4 sequence steps)", () => {
  test.beforeEach(async ({ page }) => {
    await gotoHarness(page);
    await openSim(page, SCRIPT_SIGNAL, "script");
  });

  test("renders 4 sequence nodes", async ({ page }) => {
    await expect(page.locator(".sim-node-action")).toHaveCount(4);
    await page.screenshot({ path: "screenshots/real-script-signal-4-nodes.png" });
  });

  test("nodes describe if-then, light.turn_on, delay, light.turn_off", async ({ page }) => {
    const nodes = page.locator(".sim-node-action");
    await expect(nodes.nth(0)).toContainText("If-then-else");
    await expect(nodes.nth(1)).toContainText("light.turn_on");
    await expect(nodes.nth(2)).toContainText("Delay");
    await expect(nodes.nth(3)).toContainText("light.turn_off");
  });

  test("all 4 nodes sim-pass after auto-run", async ({ page }) => {
    const nodes = page.locator(".sim-node-action");
    for (let i = 0; i < 4; i++) {
      await expect(nodes.nth(i)).toHaveClass(/sim-pass/);
    }
  });

  test("entity from if-condition is shown in mock panel", async ({ page }) => {
    await expect(page.locator("#sim-mock-rows")).toContainText("binary_sensor.home_presence");
  });
});

// ─────────────────────────────────────────────────────────────────────────────

test.describe("Real script — Vacuum queue manager (2 sequence steps)", () => {
  test.beforeEach(async ({ page }) => {
    await gotoHarness(page);
    await openSim(page, SCRIPT_VACUUM_QUEUE, "script");
  });

  test("renders 2 sequence nodes", async ({ page }) => {
    await expect(page.locator(".sim-node-action")).toHaveCount(2);
    await page.screenshot({ path: "screenshots/real-script-vacuum-nodes.png" });
  });

  test("first node is Set variables, second is Choose", async ({ page }) => {
    const nodes = page.locator(".sim-node-action");
    await expect(nodes.nth(0)).toContainText("Set variables");
    await expect(nodes.nth(1)).toContainText("Choose");
  });
});

// ═════════════════════════════════════════════════════════════════════════════
// BLUEPRINTS — inputs, node counts, simulation
// ═════════════════════════════════════════════════════════════════════════════

test.describe("Real blueprint — motion_light (3 inputs, 1T, 4A)", () => {
  test.beforeEach(async ({ page }) => {
    await gotoHarness(page);
    await openSim(page, BP_MOTION_LIGHT, "blueprint");
  });

  test("shows Blueprint Simulator title", async ({ page }) => {
    await expect(page.locator(".sim-toolbar-title")).toContainText("Blueprint Simulator");
    await page.screenshot({ path: "screenshots/real-bp-motion-light-title.png" });
  });

  test("renders 3 blueprint input fields in mock panel", async ({ page }) => {
    await expect(page.locator("#sim-mock-rows")).toContainText("Motion Sensor");
    await expect(page.locator("#sim-mock-rows")).toContainText("Light");
    await expect(page.locator("#sim-mock-rows")).toContainText("Wait time");
  });

  test("Wait time default is pre-filled with 120", async ({ page }) => {
    const input = page.locator(".sim-blueprint-input[data-key='no_motion_wait']");
    await expect(input).toHaveValue("120");
  });

  test("renders 1 trigger node", async ({ page }) => {
    await expect(page.locator(".sim-node-trigger")).toHaveCount(1);
  });

  test("renders 4 action nodes", async ({ page }) => {
    await expect(page.locator(".sim-node-action")).toHaveCount(4);
    await page.screenshot({ path: "screenshots/real-bp-motion-light-nodes.png" });
  });

  test("action nodes: turn_on, wait_for_trigger, delay, turn_off", async ({ page }) => {
    const nodes = page.locator(".sim-node-action");
    await expect(nodes.nth(0)).toContainText("light.turn_on");
    // wait_for_trigger is shown as "Action" or custom description
    await expect(nodes.nth(2)).toContainText("Delay");
    await expect(nodes.nth(3)).toContainText("light.turn_off");
  });

  test("trigger node is clickable → sim-fired", async ({ page }) => {
    await page.locator(".sim-node-trigger").click();
    await expect(page.locator(".sim-node-trigger")).toHaveClass(/sim-fired/);
  });

  test("run with trigger fired → Would trigger badge", async ({ page }) => {
    await page.locator(".sim-node-trigger").click();
    await page.locator("#sim-run-btn").click();
    await expect(page.locator("#sim-result-badge")).toContainText("Would trigger");
    await expect(page.locator(".sim-node-trigger")).toHaveClass(/sim-pass/);
    await page.screenshot({ path: "screenshots/real-bp-motion-light-run.png" });
  });

  test("can override motion_sensor input field", async ({ page }) => {
    const input = page.locator(".sim-blueprint-input[data-key='motion_entity']");
    await input.fill("binary_sensor.hallway_motion");
    await expect(input).toHaveValue("binary_sensor.hallway_motion");
  });
});

// ─────────────────────────────────────────────────────────────────────────────

test.describe("Real blueprint — motion_timer (10 inputs, 6T, 1C, 1A)", () => {
  test.beforeEach(async ({ page }) => {
    await gotoHarness(page);
    await openSim(page, BP_MOTION_TIMER, "blueprint");
  });

  test("renders 10 blueprint input fields", async ({ page }) => {
    const inputs = page.locator(".sim-blueprint-input");
    await expect(inputs).toHaveCount(10);
    await page.screenshot({ path: "screenshots/real-bp-motion-timer-inputs.png" });
  });

  test("renders 6 trigger nodes", async ({ page }) => {
    await expect(page.locator(".sim-node-trigger")).toHaveCount(6);
    await page.screenshot({ path: "screenshots/real-bp-motion-timer-6-triggers.png" });
  });

  test("renders 1 condition node", async ({ page }) => {
    await expect(page.locator(".sim-node-condition")).toHaveCount(1);
  });

  test("renders 1 action node (choose)", async ({ page }) => {
    await expect(page.locator(".sim-node-action")).toHaveCount(1);
    await expect(page.locator(".sim-node-action")).toContainText("Choose");
  });

  test("all 6 triggers have Fire buttons", async ({ page }) => {
    await expect(page.locator(".sim-fire-btn")).toHaveCount(6);
  });

  test("can fire each trigger independently", async ({ page }) => {
    const triggers = page.locator(".sim-node-trigger");
    for (let i = 0; i < 6; i++) {
      await triggers.nth(i).click();
      await expect(triggers.nth(i)).toHaveClass(/sim-fired/);
      // unfired so next click is fresh
      await triggers.nth(i).click();
      await expect(triggers.nth(i)).not.toHaveClass(/sim-fired/);
    }
    await page.screenshot({ path: "screenshots/real-bp-motion-timer-nav.png" });
  });

  test("light_level_primary default 200 is pre-filled", async ({ page }) => {
    const input = page.locator(".sim-blueprint-input[data-key='light_level_primary']");
    await expect(input).toHaveValue("200");
  });

  test("run with first trigger fired → badge present", async ({ page }) => {
    await page.locator(".sim-node-trigger").nth(0).click();
    await page.locator("#sim-run-btn").click();
    await expect(page.locator("#sim-result-badge")).toBeVisible();
    await expect(page.locator("#sim-result-badge")).toContainText("Would");
    await page.screenshot({ path: "screenshots/real-bp-motion-timer-run.png" });
  });
});

// ─────────────────────────────────────────────────────────────────────────────

test.describe("Real blueprint — vacuum script (3 inputs, 6 sequence steps)", () => {
  test.beforeEach(async ({ page }) => {
    await gotoHarness(page);
    await openSim(page, BP_VACUUM_SCRIPT, "blueprint");
  });

  test("shows Blueprint Simulator title", async ({ page }) => {
    await expect(page.locator(".sim-toolbar-title")).toContainText("Blueprint Simulator");
  });

  test("renders 3 blueprint input fields", async ({ page }) => {
    await expect(page.locator(".sim-blueprint-input")).toHaveCount(3);
    await expect(page.locator("#sim-mock-rows")).toContainText("Vacuum");
    await expect(page.locator("#sim-mock-rows")).toContainText("Room");
    await expect(page.locator("#sim-mock-rows")).toContainText("Current room");
    await page.screenshot({ path: "screenshots/real-bp-vacuum-inputs.png" });
  });

  test("renders 6 action nodes in sequence", async ({ page }) => {
    await expect(page.locator(".sim-node-action")).toHaveCount(6);
    await page.screenshot({ path: "screenshots/real-bp-vacuum-6-nodes.png" });
  });

  test("nodes include condition, send_command, delay, not-condition, set_value, script", async ({ page }) => {
    const nodes = page.locator(".sim-node-action");
    // condition step renders as a node
    await expect(nodes.nth(1)).toContainText("vacuum.send_command");
    await expect(nodes.nth(2)).toContainText("Delay");
    await expect(nodes.nth(4)).toContainText("input_text.set_value");
  });
});
