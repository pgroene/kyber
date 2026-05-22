import { test, expect } from "@playwright/test";
import { gotoHarness, injectPlanCard } from "./helpers.js";

test.describe("Guardrails", () => {
  const highRiskPlan = {
    summary: "Lock the front door",
    actions: [
      { type: "call_service", domain: "lock", service: "lock", entity_id: "light.bedroom", requires_approval: true, high_risk: true, risk_domain: "lock" },
    ],
    requires_approval: true,
    high_risk: true,
    high_risk_domains: ["lock"],
  };

  test("autopilot does not run high-risk plans without an override", async ({ page }) => {
    let executeCalled = false;
    await page.route("**/api/kyber/execute", (route) => {
      executeCalled = true;
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ results: [{ status: "ok" }] }) });
    });

    await gotoHarness(page);
    await page.evaluate(() => {
      window.__panel._autopilot = true;
      window.__panel._updateAutopilotBadge();
      window.localStorage.clear();
    });
    await injectPlanCard(page, highRiskPlan);

    await expect(page.locator(".plan-approval-note")).toContainText("high risk");
    await page.waitForTimeout(3000);
    expect(executeCalled).toBe(false);
    await expect(page.locator(".btn-execute")).toBeVisible();
  });

  test("stored override lets autopilot run a high-risk domain", async ({ page }) => {
    let approved = null;
    await page.route("**/api/kyber/execute", async (route) => {
      approved = JSON.parse(route.request().postData() || "{}").approved;
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ results: [{ status: "ok" }] }) });
    });

    await gotoHarness(page);
    await page.evaluate(() => {
      window.__panel._autopilot = true;
      window.__panel._updateAutopilotBadge();
      window.localStorage.setItem("kyber.autopilot.override.lock", "1");
    });
    await injectPlanCard(page, highRiskPlan);

    await expect(page.locator(".plan-result.success")).toBeVisible({ timeout: 6000 });
    expect(approved).toBe(true);
  });
});
