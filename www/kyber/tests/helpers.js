/**
 * Shared test helpers for kyber-panel tests.
 *
 * Import this in individual test files:
 *   import { makePanel } from "../helpers.js";
 */

/**
 * Create a KyberPanel element, append to DOM, and set a mock hass object.
 * Setting hass triggers _render() which builds the full Shadow DOM.
 *
 * @param {object} hassOverrides - Merged into the default hass mock
 * @returns {{ element: KyberPanel, hass: object }}
 */
export function makePanel(hassOverrides = {}) {
  const element = document.createElement("kyber-panel");
  document.body.appendChild(element);

  const hass = {
    auth: { data: { access_token: "test-token" } },
    states: {},
    panels: {},
    callApi: vi.fn().mockResolvedValue({}),
    ...hassOverrides,
  };

  // Set a default fetch mock BEFORE assigning hass.
  // Setting hass triggers _render() → _startStatusPolling() → _checkKyberStatus()
  // which calls fetch("/api/kyber/debug/status") immediately.
  // Without a mock, JSDOM's native fetch will hang the test suite.
  if (typeof global.fetch?.mockClear !== "function") {
    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 404 });
  }

  element.hass = hass;
  // Clear fetch calls from setup so individual tests start counting from a clean slate.
  if (typeof global.fetch?.mockClear === "function") global.fetch.mockClear();
  return { element, hass };
}

/**
 * Create a panel without triggering render (for testing pure functions only).
 * Sets _hass directly without going through the setter.
 */
export function makeUnrenderedPanel(hassOverrides = {}) {
  const element = document.createElement("kyber-panel");
  element._hass = {
    auth: { data: { access_token: "test-token" } },
    states: {},
    panels: {},
    callApi: vi.fn().mockResolvedValue({}),
    ...hassOverrides,
  };
  return element;
}

/**
 * Build a mock textarea-like object for _getTokenAtCursor tests.
 */
export function mockTextarea(value, selectionStart = null) {
  return {
    value,
    selectionStart: selectionStart ?? value.length,
  };
}
