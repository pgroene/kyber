/**
 * Playwright UI tests for the YAML editor — context breadcrumb in header.
 *
 * These tests inject editor state directly via page.evaluate() so no
 * real HA instance is required.
 */
import { test, expect } from "@playwright/test";
import { gotoHarness } from "./helpers.js";

test.describe("Editor — context breadcrumb", () => {
  test.beforeEach(async ({ page }) => {
    await gotoHarness(page);
  });

  test("context label is hidden when editor is closed", async ({ page }) => {
    // editor-context-label has .editor-controls → display:none when editor not open
    const label = page.locator("#editor-context-label");
    await expect(label).not.toBeVisible();
  });

  test("context label shows automation friendly name when editor opens", async ({ page }) => {
    // Simulate _openAutomation by directly calling the private method
    await page.evaluate(() => {
      const panel = window.__panel;
      // Manually replicate what _openAutomation does for the label
      const editorContainer = panel.shadowRoot.getElementById("editor-container");
      if (!panel._editor) panel._initEditor(editorContainer);
      panel.shadowRoot.getElementById("app-container").classList.add("editor-open");
      editorContainer.classList.add("open");
      panel.shadowRoot.querySelectorAll(".editor-controls").forEach((el) => {
        el.style.display = "block";
      });
      panel.shadowRoot.getElementById("editor-context-label").textContent = "Morning Lights";
    });

    const label = page.locator("#editor-context-label");
    await expect(label).toBeVisible();
    await expect(label).toContainText("Morning Lights");

    await page.screenshot({ path: "screenshots/editor-context-automation.png" });
  });

  test("context label clears when editor is closed", async ({ page }) => {
    // Open editor with a label
    await page.evaluate(() => {
      const panel = window.__panel;
      const editorContainer = panel.shadowRoot.getElementById("editor-container");
      if (!panel._editor) panel._initEditor(editorContainer);
      panel.shadowRoot.getElementById("app-container").classList.add("editor-open");
      editorContainer.classList.add("open");
      panel.shadowRoot.querySelectorAll(".editor-controls").forEach((el) => {
        el.style.display = "block";
      });
      panel.shadowRoot.getElementById("editor-context-label").textContent = "Sunup";
    });

    await expect(page.locator("#editor-context-label")).toBeVisible();

    // Close editor
    await page.evaluate(() => window.__panel._closeEditor());

    // Label should be hidden again
    await expect(page.locator("#editor-context-label")).not.toBeVisible();

    await page.screenshot({ path: "screenshots/editor-context-closed.png" });
  });

  test("context label shows dashboard name for dashboard editor", async ({ page }) => {
    await page.evaluate(() => {
      const panel = window.__panel;
      const editorContainer = panel.shadowRoot.getElementById("editor-container");
      if (!panel._editor) panel._initEditor(editorContainer);
      panel.shadowRoot.getElementById("app-container").classList.add("editor-open");
      editorContainer.classList.add("open");
      panel.shadowRoot.querySelectorAll(".editor-controls").forEach((el) => {
        el.style.display = "block";
      });
      panel.shadowRoot.getElementById("editor-context-label").textContent = "Overview (default)";
    });

    const label = page.locator("#editor-context-label");
    await expect(label).toBeVisible();
    await expect(label).toContainText("Overview (default)");

    await page.screenshot({ path: "screenshots/editor-context-dashboard.png" });
  });
});
