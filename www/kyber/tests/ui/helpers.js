/**
 * Shared helpers for Kyber UI tests.
 *
 * Usage:
 *   import { gotoHarness, injectPlanCard, injectCommandCard } from "./helpers.js";
 */

/** Navigate to the harness and wait for the panel to be ready. */
export async function gotoHarness(page) {
  await page.goto("/www/kyber/tests/ui/harness.html");
  // Wait until the custom element is defined and rendered
  await page.waitForFunction(() => window.__panel && window.__panel.shadowRoot);
}

/** Navigate to the real-editor harness (uses actual CodeMirror bundle). */
export async function gotoRealEditorHarness(page) {
  await page.goto("/www/kyber/tests/ui/harness-real-editor.html");
  await page.waitForFunction(() => window.__panel && window.__panel.shadowRoot);
}

/**
 * Inject a plan card directly into the panel's chat history.
 * @param {import("@playwright/test").Page} page
 * @param {object} plan - { overview, actions }
 */
export async function injectPlanCard(page, plan) {
  await page.evaluate((p) => {
    const card = window.__panel._buildPlanCard(p);
    const history = window.__panel.shadowRoot.getElementById("chat-history");
    history.appendChild(card);
  }, plan);
}

/**
 * Inject a command card directly into the panel's chat history.
 * @param {import("@playwright/test").Page} page
 * @param {object} opts - { icon, title, detail, danger }
 */
export async function injectCommandCard(page, opts) {
  await page.evaluate((o) => {
    window.__panel._buildCommandCard({
      icon: o.icon || "🔧",
      title: o.title || "Test command",
      detail: o.detail || "detail",
      danger: o.danger || false,
      onConfirm: (card) => {
        fetch("/api/kyber/test-confirm", { method: "POST" });
        card.querySelector(".btn-cmd-execute").textContent = "✓ Done";
      },
    });
  }, opts);
}

/** Click the prompt input, type a message, and submit. */
export async function sendMessage(page, text) {
  const input = page.locator("#prompt-input");
  await input.fill(text);
  await page.locator("#btn-ask").click();
}

/** Pierce Shadow DOM to locate an element inside the panel's shadow root. */
export function shadowLocator(page, selector) {
  return page.locator(`kyber-panel >> css=${selector}`);
}
