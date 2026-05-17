/**
 * Unit tests for session management methods in KyberPanel.
 *
 * Covers:
 *   - _sanitizeHistoryForPersistence(messages)
 *   - _getActiveSession()
 *   - _resetChatView()
 *   - _addChatHistory(role, content)
 *   - _updateSessionIndicator()
 */

import { makePanel, makeUnrenderedPanel } from "../helpers.js";

// ---------------------------------------------------------------------------
// _sanitizeHistoryForPersistence
// ---------------------------------------------------------------------------
describe("_sanitizeHistoryForPersistence", () => {
  let el;
  beforeEach(() => { el = makeUnrenderedPanel(); });

  it("keeps user and assistant messages", () => {
    const msgs = [
      { role: "user", content: "Hello" },
      { role: "assistant", content: "Hi there" },
    ];
    const result = el._sanitizeHistoryForPersistence(msgs);
    expect(result).toHaveLength(2);
    expect(result[0].role).toBe("user");
    expect(result[1].role).toBe("assistant");
  });

  it("filters out messages with empty content", () => {
    const msgs = [
      { role: "user", content: "" },
      { role: "assistant", content: "  " },
      { role: "user", content: "Valid message" },
    ];
    const result = el._sanitizeHistoryForPersistence(msgs);
    expect(result).toHaveLength(1);
    expect(result[0].content).toBe("Valid message");
  });

  it("keeps only last 200 messages (slice limit)", () => {
    const msgs = Array.from({ length: 250 }, (_, i) => ({
      role: i % 2 === 0 ? "user" : "assistant",
      content: `message ${i}`,
    }));
    const result = el._sanitizeHistoryForPersistence(msgs);
    expect(result.length).toBeLessThanOrEqual(200);
  });

  it("returns empty array for empty input", () => {
    expect(el._sanitizeHistoryForPersistence([])).toEqual([]);
  });

  it("normalises role to 'user' or 'assistant'", () => {
    const msgs = [
      { role: "user", content: "Hi" },
      { role: "system", content: "System message" },
    ];
    const result = el._sanitizeHistoryForPersistence(msgs);
    // system role should either be excluded or converted
    result.forEach((m) => {
      expect(["user", "assistant"]).toContain(m.role);
    });
  });
});

// ---------------------------------------------------------------------------
// _getActiveSession
// ---------------------------------------------------------------------------
describe("_getActiveSession", () => {
  let el;
  beforeEach(() => { el = makeUnrenderedPanel(); });

  it("returns null when no active session", () => {
    el._activeSessionId = null;
    expect(el._getActiveSession()).toBeNull();
  });

  it("returns session id and name when active", () => {
    el._activeSessionId = "session-123";
    el._activeSessionName = "My Session";
    const session = el._getActiveSession();
    expect(session).not.toBeNull();
    expect(session.id).toBe("session-123");
    expect(session.name).toBe("My Session");
  });

  it("provides fallback name 'Session 1' when name is not set", () => {
    el._activeSessionId = "session-456";
    el._activeSessionName = null;
    const session = el._getActiveSession();
    expect(session.name).toBe("Session 1");
  });
});

// ---------------------------------------------------------------------------
// _addChatHistory
// ---------------------------------------------------------------------------
describe("_addChatHistory", () => {
  it("appends user message to _chatHistory", async () => {
    const { element } = makePanel();
    const initialLength = element._chatHistory.length;
    element._addChatHistory("user", "Hello world");
    expect(element._chatHistory.length).toBe(initialLength + 1);
    const last = element._chatHistory[element._chatHistory.length - 1];
    expect(last.role).toBe("user");
    expect(last.content).toBe("Hello world");
  });

  it("appends assistant message to _chatHistory", async () => {
    const { element } = makePanel();
    element._addChatHistory("assistant", "I can help with that.");
    const last = element._chatHistory[element._chatHistory.length - 1];
    expect(last.role).toBe("assistant");
  });

  it("does not append empty content", async () => {
    const { element } = makePanel();
    const before = element._chatHistory.length;
    element._addChatHistory("user", "");
    element._addChatHistory("user", "   ");
    expect(element._chatHistory.length).toBe(before);
  });

  it("normalises unknown role to 'assistant'", async () => {
    const { element } = makePanel();
    element._addChatHistory("system", "System msg");
    const last = element._chatHistory[element._chatHistory.length - 1];
    expect(last.role).toBe("assistant");
  });
});

// ---------------------------------------------------------------------------
// _updateSessionIndicator
// ---------------------------------------------------------------------------
describe("_updateSessionIndicator", () => {
  it("shows session name in indicator element", () => {
    const { element } = makePanel();
    element._activeSessionName = "Home Automation";
    element._updateSessionIndicator();
    const indicator = element.shadowRoot.getElementById("session-indicator");
    expect(indicator).not.toBeNull();
    expect(indicator.textContent).toContain("Home Automation");
  });

  it("clears indicator when session name is empty", () => {
    const { element } = makePanel();
    element._activeSessionName = "";
    element._updateSessionIndicator();
    const indicator = element.shadowRoot.getElementById("session-indicator");
    expect(indicator.textContent).toBe("");
  });
});

// ---------------------------------------------------------------------------
// _loadSessionList
// ---------------------------------------------------------------------------
describe("_loadSessionList", () => {
  it("loads sessions via hass.callApi even when auth token is unavailable", async () => {
    const callApi = vi.fn().mockResolvedValue({
      sessions: [
        { id: "s1", name: "Session 1", message_count: 2, active: true },
      ],
    });
    const el = makeUnrenderedPanel({ auth: undefined, callApi });

    const sessions = await el._loadSessionList();

    expect(callApi).toHaveBeenCalledWith("GET", "kyber/sessions");
    expect(sessions).toHaveLength(1);
    expect(sessions[0].id).toBe("s1");
    expect(sessions[0].history).toHaveLength(2);
  });
});
