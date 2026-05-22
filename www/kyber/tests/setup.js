/**
 * Vitest global setup — runs before each test file.
 *
 * Imports kyber-panel.js so the custom element is registered in the jsdom registry.
 * The codemirror-bundle alias in vitest.config.js redirects the bundle import to
 * our no-op mock, so tests run without the real editor.
 */

// Register the custom element
await import("kyber-www/kyber-panel.js");

/**
 * Clean up all appended elements after each test so DOM is fresh.
 */
afterEach(() => {
  document.body.innerHTML = "";
});
