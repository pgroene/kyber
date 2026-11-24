/**
 * Regression tests for four panel bugs:
 *   1. ReferenceError "promptInput" in _appendAIResponse / _autoExecuteToolPlan
 *      (ai-mixin.js) — read-only plans auto-execute, errors must not be treated
 *      as success.
 *   2. "/session delete" confirmation card crashed on session.history.length
 *      (session-mixin.js) — must use this._chatHistory.
 *   3. Entity-list picker closed on every click inside it (editor-mixin.js) —
 *      outside-click detection must use e.composedPath() (shadow DOM retargeting).
 *   4. Debug pane timers kept fighting the active tab (debug-mixin.js) —
 *      explorer status interval and deep-analysis polling must stop when the
 *      user switched to another tab; the memory text filter must be debounced.
 */

import { makePanel } from "../helpers.js";

// ---------------------------------------------------------------------------
// Bug 1 — _appendAIResponse with a read-only tool plan / _autoExecuteToolPlan
// ---------------------------------------------------------------------------
describe("Bug 1: auto-executing read-only tool plans", () => {
  const readOnlyPlan = {
    actions: [
      { type: "list_entities_by_domain", domain: "light" },
      { type: "get_entity_state", entity_id: "light.desk" },
    ],
  };

  it("_appendAIResponse with a read-only plan auto-executes without ReferenceError", async () => {
    const { element } = makePanel();
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        results: [
          { type: "get_entity_state", tool_result: { "light.desk": { state: "on" } } },
        ],
      }),
    });

    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    element._appendAIResponse("Looking it up.", [], readOnlyPlan, null, null, []);
    await new Promise((res) => setTimeout(res, 0));

    const history = element.shadowRoot.getElementById("chat-history");
    expect(history.textContent).not.toMatch(/promptInput is not defined/);
    expect(history.textContent).not.toMatch(/Tool fetch failed/);
    const bar = element.shadowRoot.getElementById("status-bar");
    expect(bar.textContent).not.toMatch(/promptInput is not defined/);
    // The tool result was rendered
    expect(history.textContent).toContain("get_entity_state");
    expect(errSpy.mock.calls.flat().join(" ")).not.toMatch(/promptInput is not defined/);
    errSpy.mockRestore();
  });

  it("_autoExecuteToolPlan works with a single argument", async () => {
    const { element } = makePanel();
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ results: [] }),
    });
    await expect(element._autoExecuteToolPlan(readOnlyPlan)).resolves.toBeUndefined();
  });

  it("_autoExecuteToolPlan shows an error when the response is not ok", async () => {
    const { element } = makePanel();
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => ({ results: [{ type: "get_entity_state", tool_result: { "light.desk": { state: "on" } } }] }),
    });

    await element._autoExecuteToolPlan(readOnlyPlan);

    const history = element.shadowRoot.getElementById("chat-history");
    expect(history.textContent).toContain("Tool fetch failed");
    expect(history.textContent).not.toContain("light.desk");
    const bar = element.shadowRoot.getElementById("status-bar");
    expect(bar.className).toContain("error");
    expect(bar.textContent).toContain("Tool fetch failed");
  });
});

// ---------------------------------------------------------------------------
// Bug 2 — "/session delete" confirmation card
// ---------------------------------------------------------------------------
describe("Bug 2: /session delete confirmation card", () => {
  // makePanel() starts an async history restore that resets the session state;
  // let it settle before setting up the session under test.
  const settle = () => new Promise((r) => setTimeout(r, 0));

  it("builds a confirmation card whose detail contains the message count", async () => {
    const { element } = makePanel();
    await settle();
    element._activeSessionId = "session-1";
    element._activeSessionName = "My Session";
    element._chatHistory = [
      { role: "user", content: "Hello" },
      { role: "assistant", content: "Hi" },
      { role: "user", content: "Turn on lights" },
    ];

    await element._handleSessionCommand("delete");

    const card = element.shadowRoot.querySelector(".command-card");
    expect(card).not.toBeNull();
    expect(card.textContent).toContain("Delete session: My Session");
    expect(card.textContent).toContain("3 messages will be lost.");
  });

  it("uses 0 as message count when _chatHistory is undefined", async () => {
    const { element } = makePanel();
    await settle();
    element._activeSessionId = "session-1";
    element._activeSessionName = "My Session";
    element._chatHistory = undefined;

    await element._handleSessionCommand("delete");

    const card = element.shadowRoot.querySelector(".command-card");
    expect(card).not.toBeNull();
    expect(card.textContent).toContain("0 messages will be lost.");
  });
});

// ---------------------------------------------------------------------------
// Bug 3 — entity-list picker outside-click detection (shadow DOM retargeting)
// ---------------------------------------------------------------------------
describe("Bug 3: entity-list picker outside-click uses composedPath", () => {
  const pathEvent = (type, path) => {
    const ev = new Event(type, { bubbles: true, cancelable: true, composed: true });
    ev.composedPath = () => path;
    return ev;
  };

  it("keeps the picker open for clicks inside it and hides it for clicks outside", () => {
    const { element } = makePanel();
    // _initEditor needs a real CodeMirror; test the extracted handler directly.
    const picker = document.createElement("div");
    const search = document.createElement("input");
    picker.appendChild(search);
    element.shadowRoot.appendChild(picker);

    // Click on a child inside the picker: e.target is retargeted to the host,
    // so contains(e.target) would be false — composedPath still has the picker.
    picker.hidden = false;
    element._entityListPickerOpen = true;
    const inside = pathEvent("click", [search, picker, element.shadowRoot, element, document]);
    Object.defineProperty(inside, "target", { value: element });
    element._handleEntityPickerOutsideClick(inside, picker);
    expect(picker.hidden).toBe(false);
    expect(element._entityListPickerOpen).toBe(true);

    // Click outside the picker
    const outside = pathEvent("click", [document.body, document.documentElement, document]);
    element._handleEntityPickerOutsideClick(outside, picker);
    expect(picker.hidden).toBe(true);
    expect(element._entityListPickerOpen).toBe(false);
    expect(element._entityListPickerDismissed).toBe(true);
  });

  it("update-badge popover stays open for clicks inside it and closes outside", () => {
    const { element } = makePanel();
    const badge = element.shadowRoot.getElementById("update-badge");
    badge.dispatchEvent(new Event("click", { bubbles: true, composed: true }));

    const pop = element.shadowRoot.getElementById("update-badge-popover");
    expect(pop).not.toBeNull();

    // Click on a button inside the popover (path includes the popover element)
    const btn = pop.querySelector("#ubp-update");
    document.dispatchEvent(pathEvent("click", [btn, pop, badge, element, document]));
    expect(element.shadowRoot.getElementById("update-badge-popover")).not.toBeNull();

    // Click outside (only the host is in the path)
    document.dispatchEvent(pathEvent("click", [document.body, document.documentElement, document]));
    expect(element.shadowRoot.getElementById("update-badge-popover")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Bug 4 — debug pane timers must not fight the active tab
// ---------------------------------------------------------------------------
describe("Bug 4: debug pane timers respect the active tab", () => {
  const statusBody = () => {
    const div = document.createElement("div");
    div.innerHTML = "<div id='dbg-run-explorer'></div>";
    return div;
  };

  const runningStatus = () => ({
    ok: true,
    status: 200,
    json: async () => ({ explorer_progress: { status: "phase2_entities", done: 1, total: 10 } }),
  });

  it("explorer status interval renders while on the status tab and stops after switching away", async () => {
    vi.useFakeTimers();
    try {
      const { element } = makePanel();
      element._debugTab = "status";
      global.fetch = vi.fn().mockResolvedValue(runningStatus());

      const liveBody = element.shadowRoot.getElementById("debug-body");
      element._renderDebugStatus(liveBody);
      await vi.advanceTimersByTimeAsync(0);
      expect(element._explorerStatusTimer).toBeTruthy();
      expect(liveBody.textContent).toContain("Indexing");

      // User switches to the logs tab → interval cleared, no further rendering
      element._debugTab = "logs";
      liveBody.innerHTML = "<em>logs view</em>";
      await vi.advanceTimersByTimeAsync(9000);
      expect(element._explorerStatusTimer).toBeNull();
      expect(liveBody.textContent).toContain("logs view");
      expect(liveBody.textContent).not.toContain("Indexing");
    } finally {
      vi.useRealTimers();
    }
  });

  it("_renderDebugTab clears the explorer interval when switching to another tab", async () => {
    vi.useFakeTimers();
    try {
      const { element } = makePanel();
      element._debugTab = "status";
      global.fetch = vi.fn().mockResolvedValue(runningStatus());

      element._renderDebugStatus(statusBody());
      await vi.advanceTimersByTimeAsync(0);
      expect(element._explorerStatusTimer).toBeTruthy();

      global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({}) });
      await element._renderDebugTab("logs");
      expect(element._explorerStatusTimer).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("_renderDebugTab clears deep-analysis polling started on another tab", async () => {
    vi.useFakeTimers();
    try {
      const { element } = makePanel();
      element._debugTab = "status";
      element._startDeepAnalysisPolling(element.shadowRoot.getElementById("debug-body"));
      expect(element._deepPollTimer).toBeTruthy();

      global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({}) });
      await element._renderDebugTab("logs");
      expect(element._deepPollTimer).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("deep-analysis polling stops on tab switch instead of pulling the user back to memory", async () => {
    vi.useFakeTimers();
    try {
      const { element } = makePanel();
      element._debugTab = "memory";
      const memBody = element.shadowRoot.getElementById("debug-body");
      memBody.innerHTML = "<div id='dbg-deep-status'></div><button id='dbg-mem-deep-analyze'></button>";

      element._startDeepAnalysisPolling(memBody);
      expect(element._deepPollTimer).toBeTruthy();

      // Poll ticks with no status element left → job considered finished
      memBody.querySelector("#dbg-deep-status").remove();
      global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({}) });
      const renderSpy = vi.spyOn(element, "_renderDebugTab").mockResolvedValue(undefined);

      // User switches to the status tab before the next tick
      element._debugTab = "status";
      await vi.advanceTimersByTimeAsync(4000);

      expect(element._deepPollTimer).toBeNull();
      expect(renderSpy).not.toHaveBeenCalled();
      renderSpy.mockRestore();
    } finally {
      vi.useRealTimers();
    }
  });

  it("memory text filter debounces re-renders and restores focus and caret", async () => {
    vi.useFakeTimers();
    try {
      const { element } = makePanel();
      element._debugTab = "memory";
      const memBody = element.shadowRoot.getElementById("debug-body");
      memBody.innerHTML = "<input type='text' id='dbg-mem-text'>";
      // Like the real render: rebuild the input, prefilled with the current filter text
      const renderSpy = vi.spyOn(element, "_renderDebugTab").mockImplementation(async () => {
        memBody.innerHTML = "<input type='text' id='dbg-mem-text'>";
        memBody.querySelector("#dbg-mem-text").value = element._debugMemText;
      });

      const input = memBody.querySelector("#dbg-mem-text");
      input.focus();
      // Two keystrokes in quick succession → one re-render (debounced)
      input.value = "l";
      element._onDebugMemTextInput({ target: input });
      input.value = "li";
      input.setSelectionRange(1, 1);
      element._onDebugMemTextInput({ target: input });
      expect(element._debugMemText).toBe("li");

      await vi.advanceTimersByTimeAsync(100);
      expect(renderSpy).not.toHaveBeenCalled();

      await vi.advanceTimersByTimeAsync(300);
      expect(renderSpy).toHaveBeenCalledTimes(1);
      expect(renderSpy).toHaveBeenCalledWith("memory");

      const newInput = memBody.querySelector("#dbg-mem-text");
      expect(element.shadowRoot.activeElement).toBe(newInput);
      expect(newInput.selectionStart).toBe(1);
      expect(newInput.selectionEnd).toBe(1);
      renderSpy.mockRestore();
    } finally {
      vi.useRealTimers();
    }
  });
});
