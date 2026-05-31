/**
 * Playwright tests for choose / if-then-else / repeat / parallel node expansion
 * in the automation simulator.
 *
 * All tests use a lightweight mock harness — no real HA backend needed.
 */
import { test, expect } from "@playwright/test";
import { gotoHarness, sendMessage } from "./helpers.js";

/* ── Helpers ────────────────────────────────────────────────────────────── */

async function openSim(page, config) {
  await gotoHarness(page);
  // Inject a plan card with an edit_automation block that will open the sim tab
  await page.evaluate((cfg) => {
    const panel = document.querySelector("kyber-panel");
    const shadow = panel.shadowRoot;
    const history = shadow.getElementById("chat-history");

    // Build a minimal plan card that triggers _buildAutomationTester
    const card = document.createElement("div");
    card.className = "plan-card";

    const simPane = document.createElement("div");
    simPane.id = "sim-pane-test";
    simPane.style.cssText = "width:600px;background:#1a1a2e;padding:16px;";

    // Call the tester builder directly
    panel._buildAutomationTester(cfg, "test_automation", simPane);
    card.appendChild(simPane);
    history.appendChild(card);
  }, config);
}

/* ── Choose node ────────────────────────────────────────────────────────── */

test("choose node renders branches", async ({ page }) => {
  await openSim(page, {
    trigger: [{ platform: "state", entity_id: "binary_sensor.door" }],
    condition: [],
    action: [
      {
        choose: [
          {
            conditions: [{ condition: "state", entity_id: "input_select.mode", state: "home" }],
            sequence: [{ service: "light.turn_on", target: { entity_id: "light.living" } }],
          },
          {
            conditions: [{ condition: "state", entity_id: "input_select.mode", state: "away" }],
            sequence: [{ service: "light.turn_off", target: { entity_id: "light.living" } }],
          },
        ],
        default: [{ service: "notify.mobile", data: { message: "default" } }],
      },
    ],
  });

  // The choose action node should exist
  const simPane = page.locator("#sim-pane-test");
  await expect(simPane).toBeVisible();

  // Two option branches + one default branch
  const branches = simPane.locator(".sim-branch");
  await expect(branches).toHaveCount(3);
});

test("choose branch labels show option number and condition", async ({ page }) => {
  await openSim(page, {
    trigger: [{ platform: "state", entity_id: "sensor.x" }],
    condition: [],
    action: [
      {
        choose: [
          {
            conditions: [{ condition: "state", entity_id: "sensor.x", state: "on" }],
            sequence: [{ service: "switch.turn_on", entity_id: "switch.fan" }],
          },
          {
            conditions: [],
            sequence: [{ service: "switch.turn_off", entity_id: "switch.fan" }],
          },
        ],
      },
    ],
  });

  const labels = page.locator(".sim-branch-label");
  const first = labels.first();
  await expect(first).toContainText("Option 1");

  // Option 2 has empty conditions → "Always"
  const second = labels.nth(1);
  await expect(second).toContainText("Option 2");
  await expect(second).toContainText("Always");
});

test("choose sub-nodes are rendered inside branches", async ({ page }) => {
  await openSim(page, {
    trigger: [{ platform: "state", entity_id: "binary_sensor.motion" }],
    condition: [],
    action: [
      {
        choose: [
          {
            conditions: [{ condition: "state", entity_id: "binary_sensor.motion", state: "on" }],
            sequence: [
              { service: "light.turn_on", target: { entity_id: "light.hall" } },
              { service: "script.turn_on", entity_id: "script.welcome" },
            ],
          },
        ],
      },
    ],
  });

  const simPane = page.locator("#sim-pane-test");
  const subNodes = simPane.locator(".sim-sub-node");
  // Two sub-nodes inside the single option
  await expect(subNodes).toHaveCount(2);
});

test("choose default branch renders when present", async ({ page }) => {
  await openSim(page, {
    trigger: [{ platform: "state", entity_id: "sensor.temp" }],
    condition: [],
    action: [
      {
        choose: [
          {
            conditions: [{ condition: "state", entity_id: "sensor.temp", state: "hot" }],
            sequence: [{ service: "climate.set_temperature", entity_id: "climate.ac" }],
          },
        ],
        default: [
          { service: "notify.mobile", data: { message: "Default action" } },
        ],
      },
    ],
  });

  const defaultLabel = page.locator(".sim-branch-default-label");
  await expect(defaultLabel).toBeVisible();
  await expect(defaultLabel).toContainText("Default");
});

test("complex node has expand/collapse toggle", async ({ page }) => {
  await openSim(page, {
    trigger: [{ platform: "state", entity_id: "sensor.x" }],
    condition: [],
    action: [
      {
        choose: [
          {
            conditions: [],
            sequence: [{ service: "light.toggle", entity_id: "light.x" }],
          },
        ],
      },
    ],
  });

  const toggle = page.locator(".sim-expand-btn").first();
  await expect(toggle).toBeVisible();
  await expect(toggle).toContainText("▾");
});

test("collapse toggle hides sub-flow", async ({ page }) => {
  await openSim(page, {
    trigger: [{ platform: "state", entity_id: "sensor.x" }],
    condition: [],
    action: [
      {
        choose: [
          {
            conditions: [],
            sequence: [{ service: "light.toggle", entity_id: "light.x" }],
          },
        ],
      },
    ],
  });

  const body = page.locator(".sim-complex-body").first();
  // Initially visible
  await expect(body).toBeVisible();

  // Click toggle to collapse
  await page.locator(".sim-expand-btn").first().click();
  await expect(body).toBeHidden();

  // Click again to expand
  await page.locator(".sim-expand-btn").first().click();
  await expect(body).toBeVisible();
});

/* ── Simulation highlighting for choose ────────────────────────────────── */

test("run simulation: matched choose branch gets sim-pass", async ({ page }) => {
  await openSim(page, {
    trigger: [{ platform: "state", entity_id: "input_select.mode" }],
    condition: [],
    action: [
      {
        choose: [
          {
            conditions: [{ condition: "state", entity_id: "input_select.mode", state: "home" }],
            sequence: [{ service: "light.turn_on", entity_id: "light.living" }],
          },
          {
            conditions: [{ condition: "state", entity_id: "input_select.mode", state: "away" }],
            sequence: [{ service: "light.turn_off", entity_id: "light.living" }],
          },
        ],
      },
    ],
  });

  // Mock the entity so first option matches
  const simPane = page.locator("#sim-pane-test");
  const modeInput = simPane.locator(`input[data-eid="input_select.mode"]`);
  if (await modeInput.count() > 0) {
    await modeInput.fill("home");
    await modeInput.dispatchEvent("input");
  }

  // Fire trigger
  const fireBtn = simPane.locator(".sim-fire-btn").first();
  if (await fireBtn.count() > 0) await fireBtn.click();

  // Run simulation
  await simPane.locator("#sim-run-btn").click();

  // First branch should be sim-pass, second sim-skip
  const branches = simPane.locator(".sim-branch");
  await expect(branches.nth(0)).toHaveClass(/sim-pass/);
  await expect(branches.nth(1)).toHaveClass(/sim-skip/);
});

test("run simulation: unmatched choose → default branch gets sim-pass", async ({ page }) => {
  await openSim(page, {
    trigger: [{ platform: "state", entity_id: "input_select.mode" }],
    condition: [],
    action: [
      {
        choose: [
          {
            conditions: [{ condition: "state", entity_id: "input_select.mode", state: "home" }],
            sequence: [{ service: "light.turn_on", entity_id: "light.living" }],
          },
        ],
        default: [{ service: "notify.mobile", data: { message: "default" } }],
      },
    ],
  });

  // Mock entity to "away" (no option matches)
  const simPane = page.locator("#sim-pane-test");
  const modeInput = simPane.locator(`input[data-eid="input_select.mode"]`);
  if (await modeInput.count() > 0) {
    await modeInput.fill("away");
    await modeInput.dispatchEvent("input");
  }

  const fireBtn = simPane.locator(".sim-fire-btn").first();
  if (await fireBtn.count() > 0) await fireBtn.click();

  await simPane.locator("#sim-run-btn").click();

  // Option 1 skipped, default passes
  const branches = simPane.locator(".sim-branch");
  await expect(branches.nth(0)).toHaveClass(/sim-skip/);
  // Default branch (last) should be sim-pass
  const defaultBranch = simPane.locator(".sim-branch-default");
  await expect(defaultBranch).toHaveClass(/sim-pass/);
});

test("sub-nodes in active branch get sim-pass", async ({ page }) => {
  await openSim(page, {
    trigger: [{ platform: "state", entity_id: "binary_sensor.motion" }],
    condition: [],
    action: [
      {
        choose: [
          {
            conditions: [],
            sequence: [
              { service: "light.turn_on", target: { entity_id: "light.hall" } },
              { delay: { seconds: 5 } },
            ],
          },
        ],
      },
    ],
  });

  const fireBtn = page.locator("#sim-pane-test .sim-fire-btn").first();
  if (await fireBtn.count() > 0) await fireBtn.click();

  await page.locator("#sim-pane-test #sim-run-btn").click();

  // Both sub-nodes should be sim-pass
  const subNodes = page.locator("#sim-pane-test .sim-sub-node");
  await expect(subNodes.nth(0)).toHaveClass(/sim-pass/);
  await expect(subNodes.nth(1)).toHaveClass(/sim-pass/);
});

/* ── If-then-else node ──────────────────────────────────────────────────── */

test("if-then-else: then and else branches rendered", async ({ page }) => {
  await openSim(page, {
    trigger: [{ platform: "state", entity_id: "binary_sensor.door" }],
    condition: [],
    action: [
      {
        if: [{ condition: "state", entity_id: "binary_sensor.door", state: "on" }],
        then: [{ service: "alarm.arm", entity_id: "alarm_control_panel.home" }],
        else: [{ service: "alarm.disarm", entity_id: "alarm_control_panel.home" }],
      },
    ],
  });

  const simPane = page.locator("#sim-pane-test");
  const thenLabel = simPane.locator(".sim-branch-then-label");
  const elseLabel = simPane.locator(".sim-branch-else-label");
  await expect(thenLabel).toBeVisible();
  await expect(thenLabel).toContainText("Then");
  await expect(elseLabel).toBeVisible();
  await expect(elseLabel).toContainText("Else");
});

test("if-then-else: if condition true → then-pass, else-skip", async ({ page }) => {
  await openSim(page, {
    trigger: [{ platform: "state", entity_id: "binary_sensor.door" }],
    condition: [],
    action: [
      {
        if: [{ condition: "state", entity_id: "binary_sensor.door", state: "on" }],
        then: [{ service: "notify.mobile", data: { message: "open" } }],
        else: [{ service: "notify.mobile", data: { message: "closed" } }],
      },
    ],
  });

  const simPane = page.locator("#sim-pane-test");
  const doorInput = simPane.locator(`input[data-eid="binary_sensor.door"]`);
  if (await doorInput.count() > 0) {
    await doorInput.fill("on");
    await doorInput.dispatchEvent("input");
  }

  const fireBtn = simPane.locator(".sim-fire-btn").first();
  if (await fireBtn.count() > 0) await fireBtn.click();

  await simPane.locator("#sim-run-btn").click();

  const thenBranch = simPane.locator(".sim-branch-then");
  const elseBranch = simPane.locator(".sim-branch-else");
  await expect(thenBranch).toHaveClass(/sim-pass/);
  await expect(elseBranch).toHaveClass(/sim-skip/);
});

test("if-then-else: if condition false → then-skip, else-pass", async ({ page }) => {
  await openSim(page, {
    trigger: [{ platform: "state", entity_id: "binary_sensor.door" }],
    condition: [],
    action: [
      {
        if: [{ condition: "state", entity_id: "binary_sensor.door", state: "on" }],
        then: [{ service: "notify.mobile", data: { message: "open" } }],
        else: [{ service: "notify.mobile", data: { message: "closed" } }],
      },
    ],
  });

  const simPane = page.locator("#sim-pane-test");
  const doorInput = simPane.locator(`input[data-eid="binary_sensor.door"]`);
  if (await doorInput.count() > 0) {
    await doorInput.fill("off");
    await doorInput.dispatchEvent("input");
  }

  const fireBtn = simPane.locator(".sim-fire-btn").first();
  if (await fireBtn.count() > 0) await fireBtn.click();

  await simPane.locator("#sim-run-btn").click();

  const thenBranch = simPane.locator(".sim-branch-then");
  const elseBranch = simPane.locator(".sim-branch-else");
  await expect(thenBranch).toHaveClass(/sim-skip/);
  await expect(elseBranch).toHaveClass(/sim-pass/);
});

/* ── Repeat node ────────────────────────────────────────────────────────── */

test("repeat: sequence branch is rendered", async ({ page }) => {
  await openSim(page, {
    trigger: [{ platform: "time", at: "07:00" }],
    condition: [],
    action: [
      {
        repeat: {
          count: 3,
          sequence: [
            { service: "light.toggle", entity_id: "light.bedroom" },
          ],
        },
      },
    ],
  });

  const simPane = page.locator("#sim-pane-test");
  const branch = simPane.locator(".sim-branch");
  await expect(branch).toBeVisible();

  // Label should mention count
  const label = simPane.locator(".sim-branch-label");
  await expect(label).toContainText("3");

  // Sub-node for the toggle
  const subNode = simPane.locator(".sim-sub-node");
  await expect(subNode).toBeVisible();
});

test("repeat: sub-nodes get sim-pass when action executes", async ({ page }) => {
  await openSim(page, {
    trigger: [{ platform: "time", at: "07:00" }],
    condition: [],
    action: [
      {
        repeat: {
          count: 2,
          sequence: [
            { service: "script.turn_on", entity_id: "script.flash" },
          ],
        },
      },
    ],
  });

  const simPane = page.locator("#sim-pane-test");
  await simPane.locator("#sim-run-btn").click();

  const subNode = simPane.locator(".sim-sub-node").first();
  await expect(subNode).toHaveClass(/sim-pass/);
});

/* ── Parallel node ──────────────────────────────────────────────────────── */

test("parallel: multiple branches rendered", async ({ page }) => {
  await openSim(page, {
    trigger: [{ platform: "state", entity_id: "binary_sensor.arrive" }],
    condition: [],
    action: [
      {
        parallel: [
          { sequence: [{ service: "light.turn_on", entity_id: "light.hall" }] },
          { sequence: [{ service: "media_player.play_media", entity_id: "media_player.speaker" }] },
        ],
      },
    ],
  });

  const simPane = page.locator("#sim-pane-test");
  const branches = simPane.locator(".sim-branch");
  await expect(branches).toHaveCount(2);

  const labels = simPane.locator(".sim-branch-label");
  await expect(labels.nth(0)).toContainText("Branch 1");
  await expect(labels.nth(1)).toContainText("Branch 2");
});

/* ── Real config: Weather switch automation (has choose) ─────────────────── */

test("weather switch automation: choose branches expand correctly", async ({ page }) => {
  // Real automation from Z: drive fixture (simplified for test)
  await openSim(page, {
    trigger: [{ platform: "state", entity_id: "weather.forecast_thuis" }],
    condition: [],
    action: [
      {
        choose: [
          {
            conditions: [{ condition: "state", entity_id: "weather.forecast_thuis", state: "rainy" }],
            sequence: [{ service: "notify.mobile_app_pixel_8_pro", data: { message: "Regen verwacht" } }],
          },
          {
            conditions: [{ condition: "state", entity_id: "weather.forecast_thuis", state: "sunny" }],
            sequence: [{ service: "notify.mobile_app_pixel_8_pro", data: { message: "Mooi weer" } }],
          },
          {
            conditions: [{ condition: "state", entity_id: "weather.forecast_thuis", state: "windy" }],
            sequence: [{ service: "notify.mobile_app_pixel_8_pro", data: { message: "Winderig" } }],
          },
        ],
      },
    ],
  });

  const simPane = page.locator("#sim-pane-test");
  const branches = simPane.locator(".sim-branch");
  await expect(branches).toHaveCount(3);

  // Labels
  await expect(branches.nth(0).locator(".sim-branch-label")).toContainText("Option 1");
  await expect(branches.nth(1).locator(".sim-branch-label")).toContainText("Option 2");
  await expect(branches.nth(2).locator(".sim-branch-label")).toContainText("Option 3");

  // Each option has one sub-node (notify)
  for (let i = 0; i < 3; i++) {
    const subNode = branches.nth(i).locator(".sim-sub-node");
    await expect(subNode).toHaveCount(1);
  }
});

test("weather switch: rainy mock → option 1 sim-pass, others skip", async ({ page }) => {
  await openSim(page, {
    trigger: [{ platform: "state", entity_id: "weather.forecast_thuis" }],
    condition: [],
    action: [
      {
        choose: [
          {
            conditions: [{ condition: "state", entity_id: "weather.forecast_thuis", state: "rainy" }],
            sequence: [{ service: "notify.mobile_app_pixel_8_pro", data: { message: "Regen verwacht" } }],
          },
          {
            conditions: [{ condition: "state", entity_id: "weather.forecast_thuis", state: "sunny" }],
            sequence: [{ service: "notify.mobile_app_pixel_8_pro", data: { message: "Mooi weer" } }],
          },
          {
            conditions: [{ condition: "state", entity_id: "weather.forecast_thuis", state: "windy" }],
            sequence: [{ service: "notify.mobile_app_pixel_8_pro", data: { message: "Winderig" } }],
          },
        ],
      },
    ],
  });

  const simPane = page.locator("#sim-pane-test");

  const weatherInput = simPane.locator(`input[data-eid="weather.forecast_thuis"]`);
  if (await weatherInput.count() > 0) {
    await weatherInput.fill("rainy");
    await weatherInput.dispatchEvent("input");
  }

  const fireBtn = simPane.locator(".sim-fire-btn").first();
  if (await fireBtn.count() > 0) await fireBtn.click();

  await simPane.locator("#sim-run-btn").click();

  const branches = simPane.locator(".sim-branch");
  await expect(branches.nth(0)).toHaveClass(/sim-pass/);
  await expect(branches.nth(1)).toHaveClass(/sim-skip/);
  await expect(branches.nth(2)).toHaveClass(/sim-skip/);

  // Sub-node in option 1 should also be sim-pass
  const firstSubNode = branches.nth(0).locator(".sim-sub-node");
  await expect(firstSubNode).toHaveClass(/sim-pass/);
});

/* ── Choose horizontal layout ────────────────────────────────────────────── */

test("choose branches are laid out in a row (horizontal)", async ({ page }) => {
  await openSim(page, {
    trigger: [{ platform: "state", entity_id: "sensor.x" }],
    condition: [],
    action: [
      {
        choose: [
          { conditions: [], sequence: [{ service: "light.turn_on", entity_id: "light.a" }] },
          { conditions: [], sequence: [{ service: "light.turn_off", entity_id: "light.b" }] },
          { conditions: [], sequence: [{ service: "notify.mobile", data: { message: "c" } }] },
        ],
      },
    ],
  });

  const chooseBody = page.locator(".sim-complex-body-choose").first();
  await expect(chooseBody).toBeVisible();

  // Verify branches are laid out horizontally — second branch should NOT be below the first
  const branches = chooseBody.locator(".sim-branch");
  const box0 = await branches.nth(0).boundingBox();
  const box1 = await branches.nth(1).boundingBox();
  expect(box0).toBeTruthy();
  expect(box1).toBeTruthy();
  // In a row layout the y-positions are approximately equal (within 20px)
  expect(Math.abs(box0.y - box1.y)).toBeLessThan(20);
  await page.screenshot({ path: "screenshots/choose-horizontal.png" });
});

/* ── Inactive option opacity ──────────────────────────────────────────────── */

test("skipped choose branch has readable opacity (>=0.6)", async ({ page }) => {
  await openSim(page, {
    trigger: [{ platform: "state", entity_id: "input_select.mode" }],
    condition: [],
    action: [
      {
        choose: [
          {
            conditions: [{ condition: "state", entity_id: "input_select.mode", state: "home" }],
            sequence: [{ service: "light.turn_on", entity_id: "light.living" }],
          },
          {
            conditions: [{ condition: "state", entity_id: "input_select.mode", state: "away" }],
            sequence: [{ service: "light.turn_off", entity_id: "light.living" }],
          },
        ],
      },
    ],
  });

  const simPane = page.locator("#sim-pane-test");
  // Run with first option matching
  const modeInput = simPane.locator(`input[data-eid="input_select.mode"]`);
  if (await modeInput.count() > 0) {
    await modeInput.fill("home");
    await modeInput.dispatchEvent("input");
  }
  const fireBtn = simPane.locator(".sim-fire-btn").first();
  if (await fireBtn.count() > 0) await fireBtn.click();
  await simPane.locator("#sim-run-btn").click();

  // Second branch should be sim-skip with readable opacity
  const skippedBranch = simPane.locator(".sim-branch.sim-skip").first();
  await expect(skippedBranch).toBeVisible();
  const opacity = await skippedBranch.evaluate((el) => parseFloat(window.getComputedStyle(el).opacity));
  expect(opacity).toBeGreaterThanOrEqual(0.6);
  await page.screenshot({ path: "screenshots/choose-skip-opacity.png" });
});

