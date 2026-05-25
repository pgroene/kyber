/**
 * Playwright UI tests for the 3-column layout and debug panel placement.
 *
 * Layout rules:
 *   - 1 col:  chat only (no editor)
 *   - 2 cols: chat | editor
 *   - 3 cols: chat | editor | simulator
 *
 * Debug pane must render inside the chat column (below the chat input).
 */
import { test, expect } from "@playwright/test";
import { gotoHarness } from "./helpers.js";

const AUTOMATION = {
  id: "layout_test",
  alias: "Layout Test",
  trigger: [{ platform: "time", at: "08:00:00" }],
  condition: [],
  action: [{ service: "light.turn_on", entity_id: "light.test" }],
};

async function openEditor(page, cfg = AUTOMATION) {
  await page.evaluate((config) => {
    const panel = window.__panel;
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

async function openSimulator(page) {
  await page.locator("#btn-tab-test").click();
  await expect(page.locator("#sim-pane")).toBeVisible();
}

test.describe("Layout — column order", () => {
  test("chat pane is leftmost column", async ({ page }) => {
    await gotoHarness(page);
    await openEditor(page);
    const chatBox   = await page.locator(".chat-pane").boundingBox();
    const editorBox = await page.locator("#editor-container").boundingBox();
    expect(chatBox).toBeTruthy();
    expect(editorBox).toBeTruthy();
    // Chat must be to the left of the editor
    expect(chatBox.x).toBeLessThan(editorBox.x);
    await page.screenshot({ path: "screenshots/layout-2col.png" });
  });

  test("editor is in the middle column when simulator is open", async ({ page }) => {
    await gotoHarness(page);
    await openEditor(page);
    await openSimulator(page);

    const chatBox   = await page.locator(".chat-pane").boundingBox();
    const editorBox = await page.locator("#editor-container").boundingBox();
    const simBox    = await page.locator("#sim-pane").boundingBox();

    expect(chatBox).toBeTruthy();
    expect(editorBox).toBeTruthy();
    expect(simBox).toBeTruthy();

    // Order: chat < editor < sim  (left → right)
    expect(chatBox.x).toBeLessThan(editorBox.x);
    expect(editorBox.x).toBeLessThan(simBox.x);
    await page.screenshot({ path: "screenshots/layout-3col.png" });
  });

  test("simulator is the rightmost column when open", async ({ page }) => {
    await gotoHarness(page);
    await openEditor(page);
    await openSimulator(page);

    const editorBox = await page.locator("#editor-container").boundingBox();
    const simBox    = await page.locator("#sim-pane").boundingBox();

    // Simulator right-edge must be >= editor right-edge
    expect(simBox.x + simBox.width).toBeGreaterThanOrEqual(editorBox.x + editorBox.width);
    await page.screenshot({ path: "screenshots/layout-sim-rightmost.png" });
  });
});

test.describe("Layout — debug pane placement", () => {
  async function showDebugPane(page) {
    await page.evaluate(() => {
      const panel = window.__panel;
      const pane = panel.shadowRoot.getElementById("debug-pane");
      if (pane) {
        pane.hidden = false;
        pane.removeAttribute("hidden");
      }
    });
    await expect(page.locator("#debug-pane")).toBeVisible();
  }

  test("debug pane is inside the chat column", async ({ page }) => {
    await gotoHarness(page);
    await showDebugPane(page);

    const chatBox  = await page.locator(".chat-pane").boundingBox();
    const debugBox = await page.locator("#debug-pane").boundingBox();

    expect(chatBox).toBeTruthy();
    expect(debugBox).toBeTruthy();

    // Debug pane left-edge must be >= chat left-edge
    expect(debugBox.x).toBeGreaterThanOrEqual(chatBox.x - 2);
    // Debug pane right-edge must be <= chat right-edge
    expect(debugBox.x + debugBox.width).toBeLessThanOrEqual(chatBox.x + chatBox.width + 2);
    await page.screenshot({ path: "screenshots/layout-debug-under-chat.png" });
  });

  test("debug pane is below the chat input area", async ({ page }) => {
    await gotoHarness(page);
    await showDebugPane(page);

    const inputBox = await page.locator(".chat-input-area").boundingBox();
    const debugBox = await page.locator("#debug-pane").boundingBox();

    expect(inputBox).toBeTruthy();
    expect(debugBox).toBeTruthy();

    // Debug pane top must be >= input area top (i.e., below or at same level)
    expect(debugBox.y).toBeGreaterThanOrEqual(inputBox.y);
    await page.screenshot({ path: "screenshots/layout-debug-below-input.png" });
  });

  test("debug pane is still in chat column when editor is open", async ({ page }) => {
    await gotoHarness(page);
    await openEditor(page);
    await showDebugPane(page);

    const chatBox  = await page.locator(".chat-pane").boundingBox();
    const debugBox = await page.locator("#debug-pane").boundingBox();

    expect(chatBox).toBeTruthy();
    expect(debugBox).toBeTruthy();
    expect(debugBox.x).toBeGreaterThanOrEqual(chatBox.x - 2);
    expect(debugBox.x + debugBox.width).toBeLessThanOrEqual(chatBox.x + chatBox.width + 2);
    await page.screenshot({ path: "screenshots/layout-debug-with-editor.png" });
  });
});
