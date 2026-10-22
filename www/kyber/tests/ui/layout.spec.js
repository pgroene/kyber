/**
 * Playwright UI tests for the 3-column layout and debug panel placement.
 *
 * Layout rules:
 *   - 1 col:  chat only (no editor)
 *   - 2 cols: chat | editor
 *   - 3 cols: chat | editor | simulator
 *
 * Debug pane spans all columns below chat and editor, with or without editor.
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

test.describe("Layout — independent scroll areas", () => {
  test("long chat scrolls inside its pane while the editor stays in view", async ({ page }) => {
    await gotoHarness(page);
    // HA does not always give the panel element a definite height. Drop the
    // harness' fixed height so the panel has to bind itself to the viewport.
    await page.evaluate(() => { window.__panel.style.height = "auto"; });
    await openEditor(page);
    await page.evaluate(() => {
      const history = window.__panel.shadowRoot.getElementById("chat-history");
      for (let i = 0; i < 60; i++) {
        const m = document.createElement("div");
        m.className = "chat-message assistant";
        m.textContent = `Message ${i} ` + "lorem ipsum ".repeat(20);
        history.appendChild(m);
      }
      history.scrollTop = history.scrollHeight;
    });

    const metrics = await page.evaluate(() => {
      const root = window.__panel.shadowRoot;
      const history = root.getElementById("chat-history");
      return {
        docHeight: document.documentElement.scrollHeight,
        viewport: window.innerHeight,
        historyClient: history.clientHeight,
        historyScroll: history.scrollHeight,
        editorTop: root.getElementById("editor-container").getBoundingClientRect().top,
      };
    });

    // The page itself must not scroll; the chat history scrolls on its own.
    expect(metrics.docHeight).toBeLessThanOrEqual(metrics.viewport);
    expect(metrics.historyScroll).toBeGreaterThan(metrics.historyClient);
    // The editor pane starts right below the toolbar and stays visible.
    expect(metrics.editorTop).toBeGreaterThanOrEqual(0);
    expect(metrics.editorTop).toBeLessThan(metrics.viewport);
    await page.screenshot({ path: "screenshots/layout-independent-scroll.png" });
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

  async function boxes(page) {
    return page.evaluate(() => {
      const root = window.__panel.shadowRoot;
      const box = (sel) => {
        const r = root.querySelector(sel).getBoundingClientRect();
        return { x: r.x, y: r.y, right: r.right, bottom: r.bottom, width: r.width };
      };
      return {
        container: box("#app-container"),
        chat: box(".chat-pane"),
        editor: box("#editor-container"),
        debug: box("#debug-pane"),
      };
    });
  }

  test("debug pane spans the full width without editor", async ({ page }) => {
    await gotoHarness(page);
    await showDebugPane(page);

    const b = await boxes(page);
    expect(b.debug.x).toBeLessThanOrEqual(b.container.x + 2);
    expect(b.debug.right).toBeGreaterThanOrEqual(b.container.right - 2);
    expect(b.debug.y).toBeGreaterThanOrEqual(b.chat.bottom - 2);
    await page.screenshot({ path: "screenshots/layout-debug-under-chat.png" });
  });

  test("debug pane keeps the full width when the editor opens", async ({ page }) => {
    await gotoHarness(page);
    await showDebugPane(page);
    const before = await boxes(page);
    await openEditor(page);

    const b = await boxes(page);
    // Same horizontal extent as before: it does not move into the chat column.
    expect(Math.abs(b.debug.x - before.debug.x)).toBeLessThanOrEqual(2);
    expect(Math.abs(b.debug.width - before.debug.width)).toBeLessThanOrEqual(2);
    // Below both chat and editor; the editor ends where the debug pane starts,
    // so no empty cell is left under the editor.
    expect(b.debug.y).toBeGreaterThanOrEqual(b.chat.bottom - 2);
    expect(b.debug.y).toBeGreaterThanOrEqual(b.editor.bottom - 2);
    expect(Math.abs(b.editor.bottom - b.chat.bottom)).toBeLessThanOrEqual(2);
    await page.screenshot({ path: "screenshots/layout-debug-full-width-editor.png" });
  });

  test("debug pane spans all three columns with the simulator open", async ({ page }) => {
    await gotoHarness(page);
    await showDebugPane(page);
    await openEditor(page);
    await openSimulator(page);

    const b = await boxes(page);
    const sim = await page.locator("#sim-pane").boundingBox();
    expect(b.debug.x).toBeLessThanOrEqual(b.container.x + 2);
    expect(b.debug.right).toBeGreaterThanOrEqual(sim.x + sim.width - 2);
    expect(b.debug.y).toBeGreaterThanOrEqual(sim.y + sim.height - 2);
  });

  test("standalone debug panel still fills the area below the toolbar", async ({ page }) => {
    // The Kyber Debug sidebar panel sets .debug-mode; its more specific rule
    // must win over the row-3 placement of the regular panel.
    await gotoHarness(page);
    await page.evaluate(() => {
      window.__panel.shadowRoot.getElementById("app-container").classList.add("debug-mode");
    });
    await showDebugPane(page);

    const b = await boxes(page);
    const toolbarBottom = await page.evaluate(
      () => window.__panel.shadowRoot.querySelector(".toolbar").getBoundingClientRect().bottom,
    );
    expect(b.debug.x).toBeLessThanOrEqual(b.container.x + 2);
    expect(b.debug.right).toBeGreaterThanOrEqual(b.container.right - 2);
    expect(Math.abs(b.debug.y - toolbarBottom)).toBeLessThanOrEqual(2);
    expect(b.debug.bottom).toBeGreaterThanOrEqual(b.container.bottom - 2);
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

  test("debug pane stays visible when editor opens", async ({ page }) => {
    await gotoHarness(page);
    // First open the debug pane
    await showDebugPane(page);
    // Then open the editor — previously this would close the debug pane
    await openEditor(page);
    // Debug pane must still be visible
    await expect(page.locator("#debug-pane")).toBeVisible();
    await page.screenshot({ path: "screenshots/layout-debug-with-editor-open.png" });
  });
});

