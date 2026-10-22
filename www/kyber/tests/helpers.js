/**
 * Shared test helpers for kyber-panel tests.
 *
 * Import this in individual test files:
 *   import { makePanel } from "../helpers.js";
 */

/**
 * Stand-in for HA's hass.fetchWithAuth: adds the bearer header the way HA does
 * (lowercase key) and calls global.fetch, which the tests mock. global.fetch is
 * looked up per call, so tests may swap it after makePanel().
 */
export function fetchWithAuthFor(hass) {
  return (path, init = {}) =>
    global.fetch(path, {
      ...init,
      headers: { ...(init.headers || {}), authorization: `Bearer ${hass.auth?.data?.access_token}` },
    });
}

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
  hass.fetchWithAuth ??= fetchWithAuthFor(hass);

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
  element._hass.fetchWithAuth ??= fetchWithAuthFor(element._hass);
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
