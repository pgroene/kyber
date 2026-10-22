/**
 * Chat cards survive a page reload.
 *
 * Background: the persisted history only held role/content and was restored via
 * _appendMessage (textContent), so after a reload every reply lost its markdown,
 * suggestion chips and all cards (plan, automation, clarify, memory, YAML).
 * Now an AI reply persists its cards in meta.render and is rebuilt through
 * _appendAIResponse in restored mode: nothing runs on its own, and a card that
 * was executed or dismissed keeps that state.
 */

import { makePanel } from "../helpers.js";

const flushPromises = () => new Promise((resolve) => setTimeout(resolve, 0));

const STATES = { "light.kitchen": { state: "off", attributes: { friendly_name: "Kitchen" } } };

const PLAN = {
  summary: "Turn on the kitchen light",
  actions: [{ type: "call_service", domain: "light", service: "turn_on", entity_id: "light.kitchen" }],
};

function makeCallApi(history) {
  return vi.fn().mockImplementation((method, path) => {
    if (method === "GET" && path === "kyber/history") {
      return Promise.resolve({ history, compacted_summary: "" });
    }
    return Promise.resolve({});
  });
}

async function restoredPanel(history, extra = {}) {
  const { element, hass } = makePanel({ callApi: makeCallApi(history), states: STATES, ...extra });
  await flushPromises();
  return { element, hass, root: element.shadowRoot };
}

function persistedHistoryPosts(callApi) {
  return callApi.mock.calls.filter(([m, p]) => m === "POST" && p === "kyber/history");
}

describe("restored replies are rendered, not dumped as text", () => {
  it("renders a restored reply through the markdown pipeline (bold → choice button)", async () => {
    const { root } = await restoredPanel([
      { role: "user", content: "what is on?" },
      { role: "assistant", content: "Pick one:\n- **Kitchen**\n- **Hallway**" },
    ]);
    const bubble = root.querySelector(".ai-message-wrap .chat-message.assistant");
    expect(bubble).not.toBeNull();
    const choices = [...bubble.querySelectorAll("li .inline-choice")].map((b) => b.textContent);
    expect(choices).toEqual(["Kitchen", "Hallway"]);
    expect(root.querySelector(".ai-message-wrap .chat-feedback-row .chat-copy-btn")).not.toBeNull();
  });

  it("restores suggestion chips of a question reply", async () => {
    const { root } = await restoredPanel([
      { role: "assistant", content: 'Which one do you want: "Kitchen" or "Hallway"?' },
    ]);
    const chips = [...root.querySelectorAll(".suggestion-chip")].map((c) => c.textContent);
    expect(chips).toEqual(["Kitchen", "Hallway"]);
  });

  it("keeps [CHANGE] log lines as plain messages with their undo lookup", async () => {
    const { element } = makePanel({ callApi: makeCallApi([]) });
    await flushPromises();
    const spy = vi.spyOn(element, "_restoreActionUndoButton").mockResolvedValue(undefined);
    element._renderRestoredMessage({ role: "assistant", content: "[CHANGE] lights off", meta: { history_entry_id: "e1" } });
    expect(spy).toHaveBeenCalledWith(expect.any(HTMLElement), "e1");
  });
});

describe("restored plan card", () => {
  it("is shown with a hint and a working Execute button", async () => {
    const { root } = await restoredPanel([
      { role: "assistant", content: "I can do that.", meta: { render: { plan: PLAN } } },
    ]);
    const card = root.querySelector(".plan-card");
    expect(card).not.toBeNull();
    expect(card.querySelector(".restored-card-note")).not.toBeNull();
    expect(card.querySelector(".btn-execute").disabled).toBe(false);
  });

  it("does not run on autopilot after a reload", async () => {
    vi.useFakeTimers();
    try {
      const { element } = makePanel({ callApi: makeCallApi([]), states: STATES });
      element._autopilot = true;
      global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ results: [] }) });
      element._renderRestoredMessage({ role: "assistant", content: "On it.", meta: { render: { plan: PLAN } } });
      vi.advanceTimersByTime(5000);
      expect(global.fetch).not.toHaveBeenCalledWith("/api/kyber/execute", expect.anything());
      expect(element.shadowRoot.querySelector(".plan-card .btn-execute")).not.toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("stays locked when it was executed before", async () => {
    const { root } = await restoredPanel([
      { role: "assistant", content: "Done.", meta: { render: { plan: PLAN, status: { plan: "done" } } } },
    ]);
    const btn = root.querySelector(".plan-card .btn-execute");
    expect(btn.disabled).toBe(true);
    expect(btn.textContent).toContain("Already executed");
    expect(root.querySelector(".plan-card .restored-card-note")).toBeNull();
  });

  it("records a successful execute so a reload locks it", async () => {
    const { element, hass } = makePanel({ callApi: makeCallApi([]), states: STATES });
    await flushPromises();
    const entry = element._addChatHistory("assistant", "I can do that.", { render: { plan: PLAN } });
    element._appendAIResponse("I can do that.", [], PLAN, null, null, [], { historyEntry: entry });

    global.fetch = vi.fn().mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({ results: [{ status: "ok", entity_id: "light.kitchen" }] }),
    });
    element.shadowRoot.querySelector(".plan-card .btn-execute").click();
    await flushPromises();
    await flushPromises();

    expect(entry.meta.render.status).toEqual({ plan: "done" });
    const lastPost = persistedHistoryPosts(hass.callApi).at(-1);
    const persisted = lastPost[2].history.find((m) => m.content === "I can do that.");
    expect(persisted.meta.render.status).toEqual({ plan: "done" });
  });
});

describe("restored side-effect plans do not fire again", () => {
  it("open_editor shows a button instead of opening the editor", async () => {
    const { element } = makePanel({ callApi: makeCallApi([]) });
    await flushPromises();
    const spy = vi.spyOn(element, "_openEditor").mockImplementation(() => {});
    element._renderRestoredMessage({
      role: "assistant", content: "Opening it.",
      meta: { render: { plan: { open_editor: true, automation_id: "a1", summary: "Edit a1" } } },
    });
    expect(spy).not.toHaveBeenCalled();
    expect(element.shadowRoot.querySelector(".open-editor-prompt .btn-open-editor")).not.toBeNull();
  });

  it("read-only tool plans are not re-fetched", async () => {
    const { element } = makePanel({ callApi: makeCallApi([]) });
    await flushPromises();
    const spy = vi.spyOn(element, "_autoExecuteToolPlan").mockResolvedValue(undefined);
    element._renderRestoredMessage({
      role: "assistant", content: "Here are your lights.",
      meta: { render: { plan: { actions: [{ type: "list_entities_by_domain", domain: "light" }] } } },
    });
    expect(spy).not.toHaveBeenCalled();
  });

  it("run_simulation is not replayed", async () => {
    const { element } = makePanel({ callApi: makeCallApi([]) });
    await flushPromises();
    const spy = vi.spyOn(element, "_handleRunSimulation").mockImplementation(() => {});
    element._renderRestoredMessage({
      role: "assistant", content: "Simulating.",
      meta: { render: { plan: { run_simulation: true, automation_id: "a1" } } },
    });
    expect(spy).not.toHaveBeenCalled();
  });
});

describe("restored automation cards", () => {
  const CREATE = { create_automation: true, alias: "Night light", summary: "New automation", config: { alias: "Night light" } };

  it("a created automation cannot be created a second time", async () => {
    const { root } = await restoredPanel([
      { role: "assistant", content: "Created.", meta: { render: { plan: CREATE, status: { plan: "done" } } } },
    ]);
    const apply = root.querySelector(".automation-edit-card .ae-btn-apply");
    expect(apply.disabled).toBe(true);
    expect(root.querySelector(".automation-edit-card .ae-btn-cancel")).toBeNull();
  });

  it("a dismissed card stays gone", async () => {
    const { root } = await restoredPanel([
      { role: "assistant", content: "Proposal.", meta: { render: { plan: CREATE, status: { plan: "dismissed" } } } },
    ]);
    expect(root.querySelector(".automation-edit-card")).toBeNull();
    expect(root.textContent).toContain("Proposal.");
  });

  it("cancel records the dismissal", async () => {
    const { element } = makePanel({ callApi: makeCallApi([]) });
    await flushPromises();
    const entry = element._addChatHistory("assistant", "Proposal.", { render: { plan: CREATE } });
    element._appendAIResponse("Proposal.", [], CREATE, null, null, [], { historyEntry: entry });
    element.shadowRoot.querySelector(".automation-edit-card .ae-btn-cancel").click();
    expect(entry.meta.render.status).toEqual({ plan: "dismissed" });
  });
});

describe("restored clarify, memory and YAML cards", () => {
  const CLARIFY = { question: "Which light?", options: ["Kitchen", "Hallway"] };

  it("an open question keeps its options", async () => {
    const { root } = await restoredPanel([
      { role: "assistant", content: "Which light?", meta: { render: { clarify: CLARIFY } } },
    ]);
    const card = root.querySelector(".clarify-card");
    expect(card.querySelector(".clarify-question").textContent).toBe("Which light?");
    expect(card.querySelectorAll(".suggestion-chip").length).toBe(2);
  });

  it("an answered question shows no options", async () => {
    const { root } = await restoredPanel([
      { role: "assistant", content: "Which light?", meta: { render: { clarify: CLARIFY, status: { clarify: "done" } } } },
    ]);
    expect(root.querySelector(".clarify-card")).not.toBeNull();
    expect(root.querySelectorAll(".clarify-card .suggestion-chip").length).toBe(0);
  });

  it("a remembered fact stays remembered", async () => {
    const fact = { summary: "'kitchen' → 'light.kitchen'", actions: [{ subject: "light.kitchen" }] };
    const { root } = await restoredPanel([
      { role: "assistant", content: "Noted.", meta: { render: { learned_fact: fact, status: { learned_fact: "done" } } } },
    ]);
    const btn = root.querySelector(".memory-card .btn-remember");
    expect(btn.disabled).toBe(true);
  });

  it("YAML suggestions come back but are not auto-applied", async () => {
    const { element } = makePanel({ callApi: makeCallApi([]) });
    await flushPromises();
    element._autopilot = true;
    const spy = vi.spyOn(element, "_setEditorContent").mockImplementation(() => {});
    element._renderRestoredMessage({
      role: "assistant", content: "Try this:",
      meta: { render: { yaml_blocks: ["alias: test"] } },
    });
    await new Promise((r) => setTimeout(r, 400));
    expect(element.shadowRoot.querySelector(".yaml-suggestion pre").textContent).toBe("alias: test");
    expect(spy).not.toHaveBeenCalled();
  });
});

describe("_askAI persists the cards of a reply", () => {
  afterEach(() => vi.unstubAllGlobals());

  async function ask(element, response) {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, text: async () => "", json: async () => response }));
    element._lovelaceResources = [];
    element._dashboardList = [];
    element.shadowRoot.getElementById("prompt-input").value = "turn on the kitchen";
    await element._askAI();
  }

  it("stores plan in meta.render and keeps meta out of the prompt history", async () => {
    const { element } = makePanel({ callApi: makeCallApi([]), states: STATES });
    await flushPromises();
    element._addChatHistory("assistant", "earlier", { render: { yaml_blocks: ["a: 1"] } });

    await ask(element, { response: "I can do that.", yaml_blocks: [], plan: PLAN, knowledge_used: ["k1"] });

    const last = element._chatHistory.at(-1);
    expect(last.content).toBe("I can do that.");
    expect(last.meta.render).toEqual({ plan: PLAN, knowledge_used: ["k1"] });

    const body = JSON.parse(fetch.mock.calls.find(([u]) => u === "/api/kyber/complete")[1].body);
    expect(body.history.every((m) => !("meta" in m))).toBe(true);
  });

  it("persists a card-only reply under its summary", async () => {
    const { element } = makePanel({ callApi: makeCallApi([]), states: STATES });
    await flushPromises();

    await ask(element, { response: "```plan\n{}\n```", yaml_blocks: [], plan: PLAN });

    const last = element._chatHistory.at(-1);
    expect(last.role).toBe("assistant");
    expect(last.content).toBe("Turn on the kitchen light");
    expect(last.meta.render.plan).toEqual(PLAN);
  });

  it("plain text replies get no render meta", async () => {
    const { element } = makePanel({ callApi: makeCallApi([]) });
    await flushPromises();

    await ask(element, { response: "All lights are off.", yaml_blocks: [], plan: null });

    expect(element._chatHistory.at(-1).meta).toBeUndefined();
  });
});
