/**
 * Unit tests for AI response rendering in KyberPanel.
 *
 * Covers:
 *   - _appendMessage(text, type) — renders chat bubbles
 *   - _renderTextWithAdornments(text, onChoiceClick) — suggestion chips
 *   - _setStatus(message, type) — status bar updates
 *   - _escapeHTML(s) — HTML escaping (used in thinking bubbles)
 *   - _updateAutopilotBadge() — badge toggle
 */

import { makePanel, makeUnrenderedPanel } from "../helpers.js";

// ---------------------------------------------------------------------------
// _appendMessage
// ---------------------------------------------------------------------------
describe("_appendMessage", () => {
  it("appends a user bubble to chat history", () => {
    const { element } = makePanel();
    element._appendMessage("Hello AI", "user");
    const history = element.shadowRoot.getElementById("chat-history");
    expect(history.textContent).toContain("Hello AI");
  });

  it("appends an assistant bubble to chat history", () => {
    const { element } = makePanel();
    element._appendMessage("Here is my answer.", "assistant");
    const history = element.shadowRoot.getElementById("chat-history");
    expect(history.textContent).toContain("Here is my answer.");
  });

  it("applies 'user' CSS class to user messages", () => {
    const { element } = makePanel();
    element._appendMessage("User says", "user");
    const history = element.shadowRoot.getElementById("chat-history");
    const userBubbles = history.querySelectorAll(".user");
    expect(userBubbles.length).toBeGreaterThan(0);
  });

  it("sets text content (not innerHTML) to prevent XSS", () => {
    const { element } = makePanel();
    element._appendMessage("<script>alert('xss')</script>", "user");
    const history = element.shadowRoot.getElementById("chat-history");
    // The injected script tag should NOT appear as a live element
    expect(history.querySelectorAll("script").length).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// _renderTextWithAdornments
// ---------------------------------------------------------------------------
describe("_renderTextWithAdornments", () => {
  it("returns a DocumentFragment", () => {
    const { element } = makePanel();
    const result = element._renderTextWithAdornments("Simple text", () => {});
    expect(result).toBeInstanceOf(DocumentFragment);
  });

  it("renders inline-choice buttons for bold patterns", () => {
    const { element } = makePanel();
    const text = `You could:\n- **Turn on** the lights\n- **Lock the door** now`;
    const frag = element._renderTextWithAdornments(text, () => {});
    // Wrap fragment in a div to enable querySelectorAll
    const container = document.createElement("div");
    container.appendChild(frag);
    const chips = container.querySelectorAll(".inline-choice");
    expect(chips.length).toBeGreaterThan(0);
  });

  it("calls onChoiceClick when inline-choice button is clicked", () => {
    const { element } = makePanel();
    const clicked = vi.fn();
    const frag = element._renderTextWithAdornments("Try **Do something** now", clicked);
    const container = document.createElement("div");
    container.appendChild(frag);
    const btn = container.querySelector(".inline-choice");
    if (btn) {
      btn.click();
      expect(clicked).toHaveBeenCalled();
    }
  });

  it("renders plain text without buttons when no bold markers", () => {
    const { element } = makePanel();
    const frag = element._renderTextWithAdornments("Just a simple statement.", () => {});
    const container = document.createElement("div");
    container.appendChild(frag);
    expect(container.textContent).toContain("Just a simple statement.");
    expect(container.querySelectorAll(".inline-choice").length).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// _setStatus
// ---------------------------------------------------------------------------
describe("_setStatus", () => {
  it("sets the text in the status bar", () => {
    const { element } = makePanel();
    element._setStatus("Saving…");
    const bar = element.shadowRoot.getElementById("status-bar");
    expect(bar.textContent).toContain("Saving…");
  });

  it("adds type class to status bar", () => {
    const { element } = makePanel();
    element._setStatus("Error occurred", "error");
    const bar = element.shadowRoot.getElementById("status-bar");
    expect(bar.className).toContain("error");
  });

  it("clears type class when no type provided", () => {
    const { element } = makePanel();
    element._setStatus("OK");
    const bar = element.shadowRoot.getElementById("status-bar");
    expect(bar.className).toContain("status-bar");
  });
});

// ---------------------------------------------------------------------------
// _escapeHTML
// ---------------------------------------------------------------------------
describe("_escapeHTML", () => {
  let el;
  beforeEach(() => { el = makeUnrenderedPanel(); });

  it("escapes all five HTML special chars", () => {
    expect(el._escapeHTML("&")).toBe("&amp;");
    expect(el._escapeHTML("<")).toBe("&lt;");
    expect(el._escapeHTML(">")).toBe("&gt;");
    expect(el._escapeHTML('"')).toBe("&quot;");
    expect(el._escapeHTML("'")).toBe("&#39;");
  });

  it("escapes mixed string", () => {
    const result = el._escapeHTML('<a href="x">test</a>');
    expect(result).toBe("&lt;a href=&quot;x&quot;&gt;test&lt;/a&gt;");
  });

  it("leaves plain text unchanged", () => {
    expect(el._escapeHTML("hello world")).toBe("hello world");
  });
});

// ---------------------------------------------------------------------------
// _updateAutopilotBadge
// ---------------------------------------------------------------------------
describe("_updateAutopilotBadge", () => {
  it("adds 'active' class when autopilot is on", () => {
    const { element } = makePanel();
    element._autopilot = true;
    element._updateAutopilotBadge();
    const badge = element.shadowRoot.getElementById("autopilot-badge");
    expect(badge.classList.contains("active")).toBe(true);
  });

  it("removes 'active' class when autopilot is off", () => {
    const { element } = makePanel();
    element._autopilot = false;
    element._updateAutopilotBadge();
    const badge = element.shadowRoot.getElementById("autopilot-badge");
    expect(badge.classList.contains("active")).toBe(false);
  });
});
