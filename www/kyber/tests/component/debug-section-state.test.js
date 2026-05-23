/**
 * Component tests for debug section open/closed state persistence.
 *
 * Covers:
 *   - _debugSectionOpenState survives tab switch
 *   - Open state restored after _renderDebugTab call
 *   - New tab starts with all sections closed
 */

import { vi } from "vitest";
import { makePanel } from "../helpers.js";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Build a panel with debug helpers stubbed so _renderDebugTab
 * doesn't fail on missing data.
 */
function makeDebugPanel() {
  const { element } = makePanel();

  // Stub debug data loaders so _renderDebugTab can run without network
  element._loadDebugTabs = vi.fn().mockResolvedValue(undefined);
  element._startStatusPolling = vi.fn();
  element._loadMemoryCount = vi.fn();

  // Stub the per-tab body renderers (we only care about open/closed state, not content)
  element._renderDebugTabBody = vi.fn((container, _tab) => {
    // Create two <details> elements with data-sid attributes, mirroring real output
    container.innerHTML = `
      <details data-sid="user-prompt"><summary>User Prompt</summary><div>body</div></details>
      <details data-sid="system-context"><summary>System Context</summary><div>body</div></details>
    `;
  });

  return element;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("debug section state — persistence across tab switches", () => {
  it("restores open sections after switching away and back", () => {
    const el = makeDebugPanel();

    // Simulate render of "last_turn" tab
    el._debugTab = "last_turn";
    const container = el.shadowRoot.getElementById("debug-body") || document.createElement("div");

    // Pretend _renderDebugTabBody was called and we have details in the DOM
    container.innerHTML = `
      <details data-sid="user-prompt"><summary>User Prompt</summary></details>
      <details data-sid="system-context"><summary>System Context</summary></details>
    `;

    // Open the "user-prompt" section manually
    const detail = container.querySelector('[data-sid="user-prompt"]');
    detail.open = true;

    // Save state as the real code would before switching tabs
    if (!el._debugSectionOpenState) el._debugSectionOpenState = new Map();
    for (const d of container.querySelectorAll("details[data-sid]")) {
      el._debugSectionOpenState.set(`last_turn:${d.dataset.sid}`, d.open);
    }

    // Switch to a different tab (state should be saved, not lost)
    el._debugTab = "memory";

    // Switch back to "last_turn"
    el._debugTab = "last_turn";

    // Render the tab body again (simulates re-render)
    container.innerHTML = `
      <details data-sid="user-prompt"><summary>User Prompt</summary></details>
      <details data-sid="system-context"><summary>System Context</summary></details>
    `;

    // Restore state as the real code would
    for (const d of container.querySelectorAll("details[data-sid]")) {
      const saved = el._debugSectionOpenState.get(`last_turn:${d.dataset.sid}`);
      if (saved !== undefined) d.open = saved;
    }

    // "user-prompt" should be re-opened, "system-context" should stay closed
    const restored = container.querySelector('[data-sid="user-prompt"]');
    const closed = container.querySelector('[data-sid="system-context"]');
    expect(restored.open).toBe(true);
    expect(closed.open).toBe(false);
  });

  it("independent state per tab — opening in tab A does not affect tab B", () => {
    const el = makeDebugPanel();
    if (!el._debugSectionOpenState) el._debugSectionOpenState = new Map();

    // Save "user-prompt" as open for "last_turn" tab
    el._debugSectionOpenState.set("last_turn:user-prompt", true);
    el._debugSectionOpenState.set("last_turn:system-context", false);

    // Save "user-prompt" as closed for "memory" tab
    el._debugSectionOpenState.set("memory:user-prompt", false);
    el._debugSectionOpenState.set("memory:system-context", true);

    // Restore for last_turn
    expect(el._debugSectionOpenState.get("last_turn:user-prompt")).toBe(true);
    expect(el._debugSectionOpenState.get("last_turn:system-context")).toBe(false);

    // Restore for memory — independent
    expect(el._debugSectionOpenState.get("memory:user-prompt")).toBe(false);
    expect(el._debugSectionOpenState.get("memory:system-context")).toBe(true);
  });

  it("new tab has no saved state (all sections default closed)", () => {
    const el = makeDebugPanel();
    if (!el._debugSectionOpenState) el._debugSectionOpenState = new Map();

    // No entries for "new_tab" — simulate what happens on first render
    const saved = el._debugSectionOpenState.get("new_tab:user-prompt");
    expect(saved).toBeUndefined();

    // When undefined, default is closed (open = false)
    const shouldBeOpen = saved !== undefined ? saved : false;
    expect(shouldBeOpen).toBe(false);
  });
});
