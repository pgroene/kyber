import { vi } from "vitest";

function renderPanel(mode = "chat", debugEnabled = false) {
  const element = document.createElement("kyber-panel");
  element.panel = { config: { mode } };
  document.body.appendChild(element);

  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ enabled: debugEnabled }),
  });
  vi.stubGlobal("fetch", fetchMock);

  element._loadMemoryCount = vi.fn();
  element._startStatusPolling = vi.fn();
  element._renderDebugTab = vi.fn();

  element.hass = {
    auth: { data: { access_token: "test-token" } },
    states: {},
    panels: {},
    callApi: vi.fn().mockResolvedValue({}),
  };

  return { element, fetchMock };
}

describe("debug pane visibility", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("keeps the debug pane hidden in chat mode", async () => {
    const { element } = renderPanel("chat");
    await element._applyModeAndDebugFlag();

    const pane = element.shadowRoot.getElementById("debug-pane");
    const chat = element.shadowRoot.querySelector(".chat-pane");

    expect(pane.hasAttribute("hidden")).toBe(true);
    expect(pane.classList.contains("debug-pane--standalone")).toBe(false);
    expect(chat.style.display).toBe("");
  });

  it("resets a stale open debug pane when applying chat mode", async () => {
    const { element } = renderPanel("chat");
    const pane = element.shadowRoot.getElementById("debug-pane");
    const chat = element.shadowRoot.querySelector(".chat-pane");
    const closeBtn = element.shadowRoot.getElementById("btn-debug-close");

    pane.removeAttribute("hidden");
    pane.classList.add("debug-pane--standalone");
    chat.style.display = "none";
    closeBtn.style.display = "none";

    await element._applyModeAndDebugFlag();

    expect(pane.hasAttribute("hidden")).toBe(true);
    expect(pane.classList.contains("debug-pane--standalone")).toBe(false);
    expect(chat.style.display).toBe("");
    expect(closeBtn.style.display).toBe("");
  });

  it("shows the debug pane in debug mode", async () => {
    const { element } = renderPanel("debug", true);
    await element._applyModeAndDebugFlag();

    const pane = element.shadowRoot.getElementById("debug-pane");
    const chat = element.shadowRoot.querySelector(".chat-pane");
    const closeBtn = element.shadowRoot.getElementById("btn-debug-close");

    expect(pane.hasAttribute("hidden")).toBe(false);
    expect(pane.classList.contains("debug-pane--standalone")).toBe(true);
    expect(chat.style.display).toBe("none");
    expect(closeBtn.style.display).toBe("none");
  });
});
