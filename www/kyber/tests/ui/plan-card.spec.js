import { test, expect } from "@playwright/test";
import { gotoHarness, injectPlanCard } from "./helpers.js";

const SIMPLE_PLAN = {
  summary: "Rename the bedroom light",
  actions: [
    { type: "rename_entity", entity_id: "light.bedroom", name: "Bedroom Lamp" },
  ],
};

test.describe("Plan card — execute button", () => {
  test.beforeEach(async ({ page }) => {
    await gotoHarness(page);
  });

  test("execute button is visible and labelled correctly", async ({ page }) => {
    await injectPlanCard(page, SIMPLE_PLAN);

    const btn = page.locator(".btn-execute");
    await expect(btn).toBeVisible();
    await expect(btn).toContainText("Execute");

    await page.screenshot({ path: "screenshots/plan-execute-before.png" });
  });

  test("execute button shows ✓ Done after a successful API response", async ({ page }) => {
    // Mock the execute endpoint
    await page.route("**/api/kyber/execute", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ results: [{ status: "ok" }] }),
      })
    );

    await injectPlanCard(page, SIMPLE_PLAN);
    await page.locator(".btn-execute").click();

    // Wait for the success indicator to appear
    await expect(page.locator(".plan-result.success")).toBeVisible({ timeout: 5_000 });

    await page.screenshot({ path: "screenshots/plan-execute-success.png" });

    await expect(page.locator(".plan-result")).toContainText("Done");
  });

  test("execute button shows error message on API failure", async ({ page }) => {
    await page.route("**/api/kyber/execute", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ results: [{ status: "error", message: "Entity not found" }] }),
      })
    );

    await injectPlanCard(page, SIMPLE_PLAN);
    await page.locator(".btn-execute").click();

    await expect(page.locator(".plan-result.error")).toBeVisible({ timeout: 5_000 });

    await page.screenshot({ path: "screenshots/plan-execute-error.png" });
  });

  test("undo button is shown after execution and fires undo API", async ({ page }) => {
    let executeCalled = false;
    let undoCalled = false;

    await page.route("**/api/kyber/execute", (route) => {
      executeCalled = true;
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          results: [{ status: "ok", undo_action: { type: "rename_entity", entity_id: "light.bedroom", name: "Bedroom" } }],
        }),
      });
    });

    await injectPlanCard(page, SIMPLE_PLAN);
    await page.locator(".btn-execute").click();
    await expect(page.locator(".plan-result.success")).toBeVisible({ timeout: 5_000 });

    // Second route for undo
    await page.route("**/api/kyber/execute", (route) => {
      undoCalled = true;
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ results: [{ status: "ok" }] }),
      });
    });

    await page.locator(".btn-undo").click();
    await expect(page.locator(".plan-result.success")).toBeVisible({ timeout: 5_000 });

    await page.screenshot({ path: "screenshots/plan-undo.png" });

    expect(executeCalled).toBe(true);
    expect(undoCalled).toBe(true);
  });
});

test.describe("Plan card — rendering", () => {
  test("shows plan overview text", async ({ page }) => {
    await gotoHarness(page);
    await injectPlanCard(page, SIMPLE_PLAN);

    await expect(page.locator(".plan-overview-summary")).toContainText("Rename the bedroom light");
    await page.screenshot({ path: "screenshots/plan-overview.png" });
  });

  test("shows warning for missing entities", async ({ page }) => {
    await gotoHarness(page);
    await injectPlanCard(page, {
      summary: "Fix a missing entity",
      actions: [{ type: "rename_entity", entity_id: "light.nonexistent", name: "Ghost" }],
    });

    await expect(page.locator(".plan-warning")).toBeVisible();
    await page.screenshot({ path: "screenshots/plan-missing-entity.png" });
  });
});
