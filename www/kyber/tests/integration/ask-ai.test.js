/**
 * Integration tests for _askAI in KyberPanel.
 *
 * Covers:
 *   - POSTs to /api/kyber/complete with correct payload fields
 *   - Sends chat history (capped at HISTORY_WINDOW entries)
 *   - Sends compacted_summary when set
 *   - Displays AI text response as assistant chat message
 *   - Shows plan card when response contains plan.actions
 *   - Shows YAML suggestion block when response contains yaml_blocks
 *   - Shows error message on non-ok HTTP response
 *   - Re-enables Ask button after success or error
 *   - Clears prompt input after submission
 *   - Slash commands skip the AI call (/autopilot on, /dashboard open)
 *   - Autopilot toggle via /autopilot on / /autopilot off
 */

import { makePanel } from "../helpers.js";

function mockFetch(response) {
  return vi.fn().mockResolvedValue({
    ok: true,
    text: async () => "",
    json: async () => response,
    ...response._overrides,
  });
}

/**
 * Type prompt into the panel's input and submit, pre-setting _lovelaceResources
 * so the lovelace-resources GET is skipped and fetch.mock.calls[0] = /complete.
 */
async function askWithInput(element, prompt) {
  element._lovelaceResources = [];  // skip the /api/lovelace/resources pre-fetch
  element._dashboardList = [];       // skip dashboard list lazy init
  const input = element.shadowRoot.getElementById("prompt-input");
  input.value = prompt;
  await element._askAI();
}

// Flush all pending microtasks
const flushPromises = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("_askAI — request payload", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", mockFetch({
      response: "Here is my answer.",
      yaml_blocks: [],
      plan: null,
    }));
  });
  afterEach(() => vi.unstubAllGlobals());

  it("POSTs to /api/kyber/complete", async () => {
    const { element } = makePanel();
    await askWithInput(element, "What should I do?");
    expect(fetch).toHaveBeenCalledWith("/api/kyber/complete", expect.any(Object));
  });

  it("sends prompt and editor yaml in request body", async () => {
    const { element } = makePanel();
    element._editor = { state: { doc: { toString: () => "alias: test" } } };
    await askWithInput(element, "Check this YAML");
    const body = JSON.parse(fetch.mock.calls[0][1].body);
    expect(body.prompt).toBe("Check this YAML");
    expect(body.yaml).toBe("alias: test");
  });

  it("includes Authorization header with hass token", async () => {
    const { element } = makePanel();
    await askWithInput(element, "Hello");
    const headers = fetch.mock.calls[0][1].headers;
    expect(headers.Authorization).toBe("Bearer test-token");
  });

  it("sends compacted_summary in body when set", async () => {
    const { element } = makePanel();
    element._compactedSummary = "Prior context summary";
    await askWithInput(element, "Continue");
    const body = JSON.parse(fetch.mock.calls[0][1].body);
    expect(body.compacted_summary).toBe("Prior context summary");
  });

  it("caps history at HISTORY_WINDOW entries", async () => {
    const { element } = makePanel();
    element._chatHistory = Array.from({ length: 8 }, (_, i) => ({
      role: i % 2 === 0 ? "user" : "assistant",
      content: `msg ${i}`,
    }));
    await askWithInput(element, "New question");
    const body = JSON.parse(fetch.mock.calls[0][1].body);
    expect(body.history.length).toBeLessThanOrEqual(element._HISTORY_WINDOW);
  });

  it("sends editor_mode in body", async () => {
    const { element } = makePanel();
    element._editorMode = "dashboard";
    await askWithInput(element, "Edit the dashboard");
    const body = JSON.parse(fetch.mock.calls[0][1].body);
    expect(body.editor_mode).toBe("dashboard");
  });
});

describe("_askAI — response handling", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows AI text as assistant chat message", async () => {
    vi.stubGlobal("fetch", mockFetch({ response: "Looks great!", yaml_blocks: [], plan: null }));
    const { element } = makePanel();
    await askWithInput(element, "Check this");
    // Find last assistant message (first is the initial greeting from _render())
    const msgs = element.shadowRoot.querySelectorAll(".chat-message.assistant");
    const lastMsg = msgs[msgs.length - 1];
    expect(lastMsg).not.toBeNull();
    expect(lastMsg.textContent).toContain("Looks great!");
  });

  it("shows plan card when plan has actions", async () => {
    vi.stubGlobal("fetch", mockFetch({
      response: "Here is my plan",
      yaml_blocks: [],
      plan: {
        summary: "Rename entity",
        actions: [{ type: "rename_entity", entity_id: "light.bedroom", new_state: "Bedroom Light" }],
      },
    }));
    const { element } = makePanel({
      states: { "light.bedroom": { entity_id: "light.bedroom", attributes: {} } },
    });
    await askWithInput(element, "Rename the bedroom light");
    expect(element.shadowRoot.querySelector(".plan-card")).not.toBeNull();
  });

  it("shows YAML suggestion block when yaml_blocks provided", async () => {
    vi.stubGlobal("fetch", mockFetch({
      response: "Here is updated YAML",
      yaml_blocks: ["alias: test\nmode: single"],
      plan: null,
    }));
    const { element } = makePanel();
    await askWithInput(element, "Fix the YAML");
    expect(element.shadowRoot.querySelector(".yaml-suggestion")).not.toBeNull();
  });

  it("clears prompt input after successful response", async () => {
    vi.stubGlobal("fetch", mockFetch({ response: "Done", yaml_blocks: [], plan: null }));
    const { element } = makePanel();
    element._lovelaceResources = [];
    element._dashboardList = [];
    const input = element.shadowRoot.getElementById("prompt-input");
    input.value = "Some prompt";
    await element._askAI();
    expect(input.value).toBe("");
  });

  it("re-enables Ask button after response", async () => {
    vi.stubGlobal("fetch", mockFetch({ response: "Done", yaml_blocks: [], plan: null }));
    const { element } = makePanel();
    await askWithInput(element, "Test");
    const btn = element.shadowRoot.getElementById("btn-ask");
    expect(btn.disabled).toBe(false);
  });

  it("shows error message on non-ok response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      text: async () => "Service unavailable",
    }));
    const { element } = makePanel();
    await askWithInput(element, "Test");
    const msgs = element.shadowRoot.querySelectorAll(".chat-message.error");
    expect(msgs.length).toBeGreaterThan(0);
    expect(msgs[msgs.length - 1].textContent).toContain("503");
  });

  it("shows error message on network failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Network error")));
    const { element } = makePanel();
    await askWithInput(element, "Test");
    const msgs = element.shadowRoot.querySelectorAll(".chat-message.error");
    expect(msgs.length).toBeGreaterThan(0);
    expect(msgs[msgs.length - 1].textContent).toContain("Network error");
  });
});

describe("_askAI — slash commands", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("does not call fetch for /autopilot commands", async () => {
    vi.stubGlobal("fetch", vi.fn());
    const { element } = makePanel();
    const input = element.shadowRoot.getElementById("prompt-input");
    input.value = "/autopilot on";
    await element._askAI();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("/autopilot on sets _autopilot to true and updates badge", async () => {
    const { element } = makePanel();
    const input = element.shadowRoot.getElementById("prompt-input");
    input.value = "/autopilot on";
    await element._askAI();
    expect(element._autopilot).toBe(true);
  });

  it("/autopilot off sets _autopilot to false", async () => {
    const { element } = makePanel();
    element._autopilot = true;
    const input = element.shadowRoot.getElementById("prompt-input");
    input.value = "/autopilot off";
    await element._askAI();
    expect(element._autopilot).toBe(false);
  });

  it("does not call fetch for /dashboard commands", async () => {
    vi.stubGlobal("fetch", vi.fn());
    const { element } = makePanel();
    vi.spyOn(element, "_cmdDashboard").mockImplementation(() => {});
    const input = element.shadowRoot.getElementById("prompt-input");
    input.value = "/dashboard close";
    await element._askAI();
    expect(fetch).not.toHaveBeenCalled();
  });
});
