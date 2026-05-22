import { makePanel } from "../helpers.js";

const flushPromises = () => new Promise((resolve) => setTimeout(resolve, 0));

/**
 * Re-usable callApi mock that returns persisted history on GET kyber/history,
 * optionally with a meta field on an assistant message.
 */
function makeCallApi(historyOverride = null) {
  return vi.fn().mockImplementation((method, path) => {
    if (method === "GET" && path === "kyber/history") {
      return Promise.resolve({
        history: historyOverride ?? [
          { role: "user", content: "persisted user message" },
          { role: "assistant", content: "persisted assistant message" },
        ],
        compacted_summary: "",
      });
    }
    if (method === "POST" && path === "kyber/history") return Promise.resolve({});
    return Promise.resolve({});
  });
}

describe("chat history persistence", () => {
  it("loads persisted history on panel render", async () => {
    const callApi = vi.fn().mockImplementation((method, path) => {
      if (method === "GET" && path === "kyber/history") {
        return Promise.resolve({
          history: [
            { role: "user", content: "persisted user message" },
            { role: "assistant", content: "persisted assistant message" },
          ],
          compacted_summary: "persisted summary",
        });
      }
      return Promise.resolve({});
    });

    const { element } = makePanel({ callApi });
    await flushPromises();

    expect(callApi).toHaveBeenCalledWith("GET", "kyber/history");
    expect(element._chatHistory).toEqual([
      { role: "user", content: "persisted user message" },
      { role: "assistant", content: "persisted assistant message" },
    ]);
    expect(element._compactedSummary).toBe("persisted summary");

    const userMsg = element.shadowRoot.querySelector(".chat-message.user");
    const assistantMsgs = element.shadowRoot.querySelectorAll(".chat-message.assistant");
    expect(userMsg?.textContent).toContain("persisted user message");
    expect(assistantMsgs[assistantMsgs.length - 1]?.textContent).toContain("persisted assistant message");
  });

  it("clears persisted history when Clear history is clicked", async () => {
    const callApi = vi.fn().mockImplementation((method, path) => {
      if (method === "GET" && path === "kyber/history") {
        return Promise.resolve({
          history: [{ role: "user", content: "old message" }],
          compacted_summary: "old summary",
        });
      }
      if (method === "DELETE" && path === "kyber/history") {
        return Promise.resolve({ status: "ok" });
      }
      return Promise.resolve({});
    });

    const { element } = makePanel({ callApi });
    await flushPromises();

    element.shadowRoot.getElementById("btn-clear-history").click();
    await flushPromises();

    expect(callApi).toHaveBeenCalledWith("DELETE", "kyber/history");
    expect(element._chatHistory).toEqual([]);
    expect(element._compactedSummary).toBe("");

    const msgs = element.shadowRoot.querySelectorAll(".chat-message.assistant");
    expect(msgs.length).toBe(1);
    expect(msgs[0].textContent).toContain("Hi! Ask me anything about your smart home");
  });
});

// ── meta field: _addChatHistory + _sanitizeHistoryForPersistence ──────────────

describe("chat history meta field", () => {
  it("_addChatHistory stores meta.history_entry_id in _chatHistory", async () => {
    const { element } = makePanel({ callApi: makeCallApi([]) });
    await flushPromises();

    element._addChatHistory("assistant", "[CHANGE] lights turned off", { history_entry_id: "abc-123" });

    const last = element._chatHistory[element._chatHistory.length - 1];
    expect(last.meta).toEqual({ history_entry_id: "abc-123" });
  });

  it("_addChatHistory without meta stores no meta key", async () => {
    const { element } = makePanel({ callApi: makeCallApi([]) });
    await flushPromises();

    element._addChatHistory("user", "hello");

    const last = element._chatHistory[element._chatHistory.length - 1];
    expect(last.meta).toBeUndefined();
  });

  it("_sanitizeHistoryForPersistence preserves meta.history_entry_id", async () => {
    const { element } = makePanel({ callApi: makeCallApi([]) });
    await flushPromises();

    const messages = [
      { role: "user", content: "hi" },
      { role: "assistant", content: "[CHANGE] did something", meta: { history_entry_id: "xyz-456" } },
    ];
    const sanitized = element._sanitizeHistoryForPersistence(messages);

    expect(sanitized[0].meta).toBeUndefined();
    expect(sanitized[1].meta).toEqual({ history_entry_id: "xyz-456" });
  });

  it("_sanitizeHistoryForPersistence ignores meta without history_entry_id", async () => {
    const { element } = makePanel({ callApi: makeCallApi([]) });
    await flushPromises();

    const messages = [
      { role: "user", content: "hi", meta: { unrelated: "value" } },
    ];
    const sanitized = element._sanitizeHistoryForPersistence(messages);
    expect(sanitized[0].meta).toBeUndefined();
  });

  it("persisted history with meta is restored to _chatHistory including meta", async () => {
    const callApi = makeCallApi([
      { role: "user", content: "I executed a plan" },
      {
        role: "assistant",
        content: "[CHANGE] lights turned on",
        meta: { history_entry_id: "entry-999" },
      },
    ]);
    const { element } = makePanel({ callApi });
    await flushPromises();

    const changeMsg = element._chatHistory.find((m) => m.content.includes("[CHANGE]"));
    expect(changeMsg?.meta).toEqual({ history_entry_id: "entry-999" });
  });
});

// ── _restoreActionUndoButton ──────────────────────────────────────────────────

describe("_restoreActionUndoButton", () => {
  const makeWrap = () => document.createElement("div");

  it("appends live Undo button when entry is applied with undo_plan", async () => {
    const { element } = makePanel({ callApi: makeCallApi([]) });
    await flushPromises();

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        id: "e1", status: "applied",
        undo_plan: [{ type: "call_service", domain: "switch", service: "turn_off", entity_id: "switch.x" }],
      }),
    });

    const wrap = makeWrap();
    element._restoreActionUndoButton(wrap, "e1");
    await flushPromises();

    const btn = wrap.querySelector(".btn-undo");
    expect(btn).not.toBeNull();
    expect(btn.disabled).toBe(false);
    expect(btn.textContent).toContain("Undo");
    expect(btn.textContent).toContain("1 action");
  });

  it("undo button count reflects undo_plan length", async () => {
    const { element } = makePanel({ callApi: makeCallApi([]) });
    await flushPromises();

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        id: "e2", status: "applied",
        undo_plan: [
          { type: "call_service", domain: "light", service: "turn_off", entity_id: "light.a" },
          { type: "call_service", domain: "light", service: "turn_off", entity_id: "light.b" },
        ],
      }),
    });

    const wrap = makeWrap();
    element._restoreActionUndoButton(wrap, "e2");
    await flushPromises();

    const btn = wrap.querySelector(".btn-undo");
    expect(btn.textContent).toContain("2 actions");
  });

  it("renders greyed-out Undone label when entry is already undone", async () => {
    const { element } = makePanel({ callApi: makeCallApi([]) });
    await flushPromises();

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ id: "e3", status: "undone", undo_plan: [] }),
    });

    const wrap = makeWrap();
    element._restoreActionUndoButton(wrap, "e3");
    await flushPromises();

    const btn = wrap.querySelector(".btn-undo");
    expect(btn).not.toBeNull();
    expect(btn.disabled).toBe(true);
    expect(btn.textContent).toContain("Undone");
  });

  it("renders nothing when entry has empty undo_plan (not undoable)", async () => {
    const { element } = makePanel({ callApi: makeCallApi([]) });
    await flushPromises();

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ id: "e4", status: "applied", undo_plan: [] }),
    });

    const wrap = makeWrap();
    element._restoreActionUndoButton(wrap, "e4");
    await flushPromises();

    expect(wrap.querySelector(".btn-undo")).toBeNull();
  });

  it("renders nothing when entry is not found (404)", async () => {
    const { element } = makePanel({ callApi: makeCallApi([]) });
    await flushPromises();

    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 404 });

    const wrap = makeWrap();
    element._restoreActionUndoButton(wrap, "nonexistent");
    await flushPromises();

    expect(wrap.querySelector(".btn-undo")).toBeNull();
  });

  it("renders nothing on network error (silent non-fatal)", async () => {
    const { element } = makePanel({ callApi: makeCallApi([]) });
    await flushPromises();

    global.fetch = vi.fn().mockRejectedValue(new Error("Network error"));

    const wrap = makeWrap();
    element._restoreActionUndoButton(wrap, "e5");
    await flushPromises();

    expect(wrap.querySelector(".btn-undo")).toBeNull();
  });

  it("_appendMessage with meta triggers _restoreActionUndoButton", async () => {
    const { element } = makePanel({ callApi: makeCallApi([]) });
    await flushPromises();

    const spy = vi.spyOn(element, "_restoreActionUndoButton").mockResolvedValue(undefined);

    element._appendMessage("[CHANGE] lights off", "assistant", { history_entry_id: "e6" });

    expect(spy).toHaveBeenCalledWith(expect.any(HTMLElement), "e6");
  });

  it("_appendMessage without meta does NOT trigger _restoreActionUndoButton", async () => {
    const { element } = makePanel({ callApi: makeCallApi([]) });
    await flushPromises();

    const spy = vi.spyOn(element, "_restoreActionUndoButton").mockResolvedValue(undefined);

    element._appendMessage("regular message", "assistant");

    expect(spy).not.toHaveBeenCalled();
  });

  it("restoring persisted history with meta calls _restoreActionUndoButton per entry", async () => {
    const callApi = makeCallApi([
      { role: "assistant", content: "[CHANGE] did thing", meta: { history_entry_id: "entry-abc" } },
      { role: "user", content: "hi" },
    ]);
    const { element } = makePanel({ callApi });

    // Spy before restoration triggers
    const spy = vi.spyOn(element, "_restoreActionUndoButton").mockResolvedValue(undefined);

    // Manually trigger restore (element may not have been set up for it yet)
    element._chatHistory = [];
    element._compactedSummary = "";
    await element._restorePersistedHistory();

    // Should have called it once for the [CHANGE] message with entry ID
    expect(spy).toHaveBeenCalledWith(expect.any(HTMLElement), "entry-abc");
    // Should NOT have been called for the user message (no meta)
    expect(spy).toHaveBeenCalledTimes(1);
  });
});
