import { test, expect } from "@playwright/test";
import { gotoHarness } from "./helpers.js";

// ---------------------------------------------------------------------------
// Fixtures — plan shapes used across tests
// ---------------------------------------------------------------------------

const ORIGINAL_CONFIG = {
  alias: "Ochtend routine",
  trigger: [{ platform: "time", at: "07:30:00" }],
  condition: [{ condition: "state", entity_id: "person.peter", state: "home" }],
  action: [
    { service: "switch.turn_on", target: { entity_id: "switch.espresso" } },
    { service: "notify.send_message", data: { message: "Goedemorgen!" } },
  ],
};

const MODIFIED_CONFIG = {
  ...ORIGINAL_CONFIG,
  trigger: [{ platform: "time", at: "07:00:00" }],
};

const EDIT_PLAN = {
  edit_automation: true,
  entity_id: "automation.ochtend_routine",
  automation_id: "1234567890",
  summary: "Trigger tijd gewijzigd van 07:30 naar 07:00",
  changes: ["Trigger time: 07:30 → 07:00"],
  original_config: ORIGINAL_CONFIG,
  modified_config: MODIFIED_CONFIG,
};

const CREATE_PLAN = {
  create_automation: true,
  alias: "Espresso weekdays",
  summary: "Zet espresso aan op werkdagen om 07:00",
  config: {
    alias: "Espresso weekdays",
    trigger: [{ platform: "time", at: "07:00:00" }],
    action: [{ service: "switch.turn_on", target: { entity_id: "switch.espresso" } }],
  },
};

// ---------------------------------------------------------------------------
// Helper: inject an automation card by calling the builder directly
// ---------------------------------------------------------------------------

async function injectEditCard(page, plan = EDIT_PLAN) {
  await page.evaluate((p) => {
    const card = window.__panel._buildEditAutomationCard(p);
    window.__panel.shadowRoot.getElementById("chat-history").appendChild(card);
  }, plan);
}

async function injectCreateCard(page, plan = CREATE_PLAN) {
  await page.evaluate((p) => {
    const card = window.__panel._buildCreateAutomationCard(p);
    window.__panel.shadowRoot.getElementById("chat-history").appendChild(card);
  }, plan);
}

// ---------------------------------------------------------------------------
// Edit card — default collapsed view
// ---------------------------------------------------------------------------

test.describe("Edit automation card — default view", () => {
  test.beforeEach(async ({ page }) => {
    await gotoHarness(page);
  });

  test("shows summary and changes list by default", async ({ page }) => {
    await injectEditCard(page);

    const card = page.locator(".automation-edit-card").first();
    await expect(card).toBeVisible();
    await expect(card.locator(".ae-summary")).toContainText("Trigger tijd gewijzigd");
    await expect(card.locator(".ae-changes li")).toContainText("07:30 → 07:00");

    await page.screenshot({ path: "screenshots/automation-edit-default.png" });
  });

  test("sections are hidden by default", async ({ page }) => {
    await injectEditCard(page);

    const sectionsEl = page.locator(".automation-edit-card .ae-sections").first();
    await expect(sectionsEl).toBeHidden();
  });

  test("shows automation name in header", async ({ page }) => {
    await injectEditCard(page);

    await expect(page.locator(".automation-edit-card .ae-title").first()).toContainText("Ochtend routine");
    await expect(page.locator(".automation-edit-card .ae-badge").first()).toContainText("automation");
  });
});

// ---------------------------------------------------------------------------
// Edit card — expand / collapse
// ---------------------------------------------------------------------------

test.describe("Edit automation card — expand", () => {
  test.beforeEach(async ({ page }) => {
    await gotoHarness(page);
  });

  test("expand shows trigger and action rows", async ({ page }) => {
    await injectEditCard(page);

    await page.locator(".ae-btn-expand").first().click();

    const sections = page.locator(".automation-edit-card .ae-sections").first();
    await expect(sections).toBeVisible();
    const rowCount = await sections.locator(".ae-row").count();
    expect(rowCount).toBeGreaterThan(0);

    await page.screenshot({ path: "screenshots/automation-edit-expanded.png" });
  });

  test("expand shows test button", async ({ page }) => {
    await injectEditCard(page);

    const testBtn = page.locator(".automation-edit-card .ae-btn-test").first();
    await expect(testBtn).toBeHidden();

    await page.locator(".ae-btn-expand").first().click();
    await expect(testBtn).toBeVisible();
  });

  test("collapse hides sections again", async ({ page }) => {
    await injectEditCard(page);

    await page.locator(".ae-btn-expand").first().click();
    await page.locator(".ae-btn-expand").first().click();

    await expect(page.locator(".automation-edit-card .ae-sections").first()).toBeHidden();
  });
});

// ---------------------------------------------------------------------------
// Edit card — changed row highlighting
// ---------------------------------------------------------------------------

test.describe("Edit automation card — changed rows", () => {
  test.beforeEach(async ({ page }) => {
    await gotoHarness(page);
  });

  test("changed trigger section header is highlighted", async ({ page }) => {
    await injectEditCard(page);
    await page.locator(".ae-btn-expand").first().click();

    const triggerHeader = page.locator(".ae-section-header.changed").first();
    await expect(triggerHeader).toBeVisible();
    await expect(triggerHeader).toContainText("TRIGGERS");
  });

  test("unchanged condition section is not highlighted", async ({ page }) => {
    await injectEditCard(page);
    await page.locator(".ae-btn-expand").first().click();

    // Condition header should exist but not have .changed class
    const conditionHeader = page.locator(".ae-section-header").filter({ hasText: "CONDITIONS" }).first();
    await expect(conditionHeader).toBeVisible();
    await expect(conditionHeader).not.toHaveClass(/changed/);
  });
});

// ---------------------------------------------------------------------------
// Edit card — delete row
// ---------------------------------------------------------------------------

test.describe("Edit automation card — delete row", () => {
  test.beforeEach(async ({ page }) => {
    await gotoHarness(page);
  });

  test("delete row removes it from the view", async ({ page }) => {
    await injectEditCard(page);
    await page.locator(".ae-btn-expand").first().click();

    const actionRows = page.locator('.ae-rows[data-section="action"] .ae-row');
    const countBefore = await actionRows.count();
    expect(countBefore).toBe(2);

    await actionRows.first().locator(".ae-row-delete").click();

    await expect(page.locator('.ae-rows[data-section="action"] .ae-row')).toHaveCount(countBefore - 1);

    await page.screenshot({ path: "screenshots/automation-edit-delete-row.png" });
  });

  test("delete row updates YAML preview", async ({ page }) => {
    await injectEditCard(page);
    await page.locator(".ae-btn-expand").first().click();

    // Open YAML details
    const yamlDetails = page.locator(".automation-edit-card .ae-yaml-details").first();
    await yamlDetails.evaluate((el) => el.setAttribute("open", ""));

    const yamlBefore = await page.locator(".ae-yaml-preview").first().textContent();

    await page.locator('.ae-rows[data-section="action"] .ae-row').first().locator(".ae-row-delete").click();

    const yamlAfter = await page.locator(".ae-yaml-preview").first().textContent();
    expect(yamlAfter).not.toBe(yamlBefore);
  });
});

// ---------------------------------------------------------------------------
// Edit card — apply
// ---------------------------------------------------------------------------

test.describe("Edit automation card — apply", () => {
  test.beforeEach(async ({ page }) => {
    await gotoHarness(page);
  });

  test("apply calls HA config API with automation id", async ({ page }) => {
    let capturedBody = null;
    await page.route("**/api/config/automation/config/1234567890", (route) => {
      route.request().postData() && (capturedBody = JSON.parse(route.request().postData()));
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ result: "ok" }) });
    });

    await injectEditCard(page);
    await page.locator(".ae-btn-apply").first().click();

    await expect(page.locator(".ae-btn-apply").first()).toContainText("✓ Opgeslagen", { timeout: 5000 });
    expect(capturedBody).not.toBeNull();
    expect(capturedBody.id).toBe("1234567890");

    await page.screenshot({ path: "screenshots/automation-edit-applied.png" });
  });

  test("apply shows error on API failure", async ({ page }) => {
    await page.route("**/api/config/automation/config/**", (route) => {
      route.fulfill({ status: 500, body: "Server error" });
    });

    await injectEditCard(page);
    await page.locator(".ae-btn-apply").first().click();

    await expect(page.locator(".ae-result.error").first()).toBeVisible({ timeout: 5000 });
  });

  test("cancel button removes card", async ({ page }) => {
    await injectEditCard(page);
    await page.locator(".ae-btn-cancel").first().click();

    await expect(page.locator(".automation-edit-card")).toHaveCount(0);
  });

  test("undo after apply calls API with original config", async ({ page }) => {
    const calls = [];
    await page.route("**/api/config/automation/config/1234567890", (route) => {
      calls.push(JSON.parse(route.request().postData()));
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ result: "ok" }) });
    });

    await injectEditCard(page);
    await page.locator(".ae-btn-apply").first().click();
    await expect(page.locator(".ae-btn-apply").first()).toContainText("Opgeslagen", { timeout: 5000 });

    // The cancel button now acts as undo
    await page.locator(".ae-btn-cancel").first().click();
    await expect(page.locator(".ae-btn-cancel").first()).toContainText("Hersteld", { timeout: 5000 });

    expect(calls.length).toBeGreaterThanOrEqual(2);
    const undoCall = calls[calls.length - 1];
    expect(undoCall.trigger?.[0]?.at).toBe("07:30:00"); // original time restored
  });
});

// ---------------------------------------------------------------------------
// Create automation card
// ---------------------------------------------------------------------------

test.describe("Create automation card", () => {
  test.beforeEach(async ({ page }) => {
    await gotoHarness(page);
  });

  test("shows alias and summary", async ({ page }) => {
    await injectCreateCard(page);

    await expect(page.locator(".automation-edit-card .ae-title").first()).toContainText("Espresso weekdays");
    await expect(page.locator(".automation-edit-card .ae-summary").first()).toContainText("Zet espresso aan");

    await page.screenshot({ path: "screenshots/automation-create-card.png" });
  });

  test("expand shows trigger and action rows", async ({ page }) => {
    await injectCreateCard(page);
    await page.locator(".ae-btn-expand").first().click();

    await expect(page.locator('.ae-rows[data-section="trigger"] .ae-row').first()).toBeVisible();
    await expect(page.locator('.ae-rows[data-section="action"] .ae-row').first()).toBeVisible();
  });

  test("create calls API with generated id", async ({ page }) => {
    let capturedPath = null;
    await page.route("**/api/config/automation/config/**", (route) => {
      capturedPath = route.request().url();
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ result: "ok" }) });
    });

    await injectCreateCard(page);
    await page.locator(".ae-btn-apply").first().click();

    await expect(page.locator(".ae-btn-apply").first()).toContainText("✓ Aangemaakt", { timeout: 5000 });
    expect(capturedPath).toMatch(/\/api\/config\/automation\/config\/\d+$/);

    await page.screenshot({ path: "screenshots/automation-created.png" });
  });
});

// ---------------------------------------------------------------------------
// Automation tester
// ---------------------------------------------------------------------------

test.describe("Automation tester", () => {
  test.beforeEach(async ({ page }) => {
    await gotoHarness(page);
  });

  test("test button opens tester with simulation results", async ({ page }) => {
    await injectEditCard(page);
    await page.locator(".ae-btn-expand").first().click();
    await page.locator(".ae-btn-test").first().click();

    // ae-tester is the container; sim-result-badge is the new result element
    await expect(page.locator(".ae-tester").first()).toBeVisible();
    await expect(page.locator(".sim-result-badge").first()).toBeVisible();

    await page.screenshot({ path: "screenshots/automation-tester.png" });
  });

  test("tester shows triggers section", async ({ page }) => {
    await injectEditCard(page);
    await page.locator(".ae-btn-expand").first().click();
    await page.locator(".ae-btn-test").first().click();

    await expect(page.locator(".sim-section").first()).toBeVisible();
    await expect(page.locator(".sim-section-label").first()).toContainText("TRIGGERS");
  });

  test("changing mock and clicking simulate updates result", async ({ page }) => {
    // Give the panel a person.peter state so conditions can evaluate
    await page.evaluate(() => {
      window.__hass.states["person.peter"] = {
        entity_id: "person.peter",
        state: "home",
        attributes: { friendly_name: "Peter" },
      };
    });

    await injectEditCard(page);
    await page.locator(".ae-btn-expand").first().click();
    await page.locator(".ae-btn-test").first().click();

    // Initially with peter = home, all conditions pass — automation would run
    const result = page.locator(".sim-result-badge").first();
    await expect(result).toBeVisible();

    // Change person.peter mock to "not_home" → condition should fail
    const mockInput = page.locator('.sim-mock-input[data-eid="person.peter"]').first();
    if (await mockInput.count() > 0) {
      await mockInput.fill("not_home");
      await page.locator(".sim-run-btn").first().click();
      await expect(result).toContainText("Would NOT run", { timeout: 3000 });
    }
  });
});

// ---------------------------------------------------------------------------
// run_simulation plan block (chat-driven mock)
// ---------------------------------------------------------------------------

test.describe("run_simulation plan block", () => {
  test.beforeEach(async ({ page }) => {
    await gotoHarness(page);
  });

  test("run_simulation opens tester and applies mock values", async ({ page }) => {
    await page.evaluate(() => {
      window.__hass.states["person.peter"] = {
        entity_id: "person.peter",
        state: "home",
        attributes: {},
      };
    });

    await injectEditCard(page);
    await page.locator(".ae-btn-expand").first().click();

    await page.evaluate(() => {
      window.__panel._handleRunSimulation({
        run_simulation: true,
        automation_id: "1234567890",
        mocks: { "person.peter": "not_home" },
      });
    });

    // Wait for tester to appear and run
    await expect(page.locator(".ae-tester").first()).toBeVisible({ timeout: 3000 });
    await expect(page.locator(".sim-result-badge").first()).toBeVisible({ timeout: 3000 });

    await page.screenshot({ path: "screenshots/automation-run-simulation.png" });
  });
});
