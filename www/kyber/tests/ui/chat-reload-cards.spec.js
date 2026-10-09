/**
 * UX test — chat cards survive a real page reload
 *
 * Emulates the backend history store, asks one question whose reply carries
 * suggestion chips and a plan card, reloads the page and checks that the reply
 * comes back as cards (not as plain text). Executing the restored plan locks
 * it on the next reload.
 */

import { test, expect } from "@playwright/test";
import { gotoHarness, sendMessage } from "./helpers.js";

const PLAN = {
  summary: "Turn on the bedroom light",
  actions: [{ type: "call_service", domain: "light", service: "turn_on", entity_id: "light.bedroom" }],
};

/** In-memory stand-in for /api/kyber/history (GET returns what POST stored). */
async function routeHistoryStore(page, store) {
  await page.route("**/api/kyber/history", async (route) => {
    const req = route.request();
    if (req.method() === "POST") {
      const body = req.postDataJSON();
      store.history = body.history;
      store.compacted_summary = body.compacted_summary;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(req.method() === "GET" ? store : { status: "ok" }),
    });
  });
}

test("reply cards and suggestions are rebuilt after a reload", async ({ page }) => {
  const store = { history: [], compacted_summary: "" };
  await routeHistoryStore(page, store);
  await page.route("**/api/lovelace/resources", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
  );
  await page.route("**/api/kyber/complete", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        response: "Which room?\n- **Bedroom**\n- **Living room**\n\n```plan\n{}\n```",
        yaml_blocks: [],
        plan: PLAN,
      }),
    })
  );
  await page.route("**/api/kyber/execute", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ results: [{ status: "ok", entity_id: "light.bedroom" }] }),
    })
  );

  await gotoHarness(page);
  await sendMessage(page, "turn on a light");
  await expect(page.locator("kyber-panel >> css=.plan-card")).toHaveCount(1);
  await expect.poll(() => store.history.length).toBe(2);

  // ── first reload: everything is back, nothing ran on its own ──
  await page.reload();
  await page.waitForFunction(() => window.__panel?._historyRestored);
  const choices = page.locator("kyber-panel >> css=.ai-message-wrap .inline-choice");
  await expect(choices).toHaveText(["Bedroom", "Living room"]);
  const card = page.locator("kyber-panel >> css=.plan-card");
  await expect(card).toHaveCount(1);
  await expect(card.locator(".restored-card-note")).toBeVisible();
  await expect(card.locator(".btn-execute")).toBeEnabled();
  await page.screenshot({ path: "screenshots/chat-reload-cards-restored.png" });

  // ── execute the restored plan, reload again: it stays locked ──
  await card.locator(".btn-execute").click();
  await expect(card.locator(".plan-result.success")).toBeVisible();
  await expect.poll(() => store.history[1]?.meta?.render?.status?.plan).toBe("done");

  await page.reload();
  await page.waitForFunction(() => window.__panel?._historyRestored);
  const lockedBtn = page.locator("kyber-panel >> css=.plan-card .btn-execute");
  await expect(lockedBtn).toBeDisabled();
  await expect(lockedBtn).toContainText("Already executed");
  await page.screenshot({ path: "screenshots/chat-reload-cards-done.png" });
});
