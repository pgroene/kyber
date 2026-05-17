import { describe, it, expect, vi, afterEach } from "vitest";
import { makePanel } from "../helpers.js";

describe("debug pane visibility", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("keeps debug pane hidden in chat mode when debug mode is disabled", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ enabled: false }) }));

    const { element } = makePanel();
    await new Promise((resolve) => setTimeout(resolve, 0));

    const pane = element.shadowRoot.getElementById("debug-pane");
    expect(pane.hasAttribute("hidden")).toBe(true);
    expect(getComputedStyle(pane).display).toBe("none");
  });

  it("does not show the standalone debug controls when debug mode is disabled", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ enabled: false }) }));

    const element = document.createElement("kyber-panel");
    element.panel = { config: { mode: "debug" } };
    document.body.appendChild(element);
    element.hass = { auth: { data: { access_token: "test-token" } }, states: {}, panels: {}, callApi: vi.fn() };

    await new Promise((resolve) => setTimeout(resolve, 0));

    const pane = element.shadowRoot.getElementById("debug-pane");
    expect(pane.hasAttribute("hidden")).toBe(true);
    expect(getComputedStyle(pane).display).toBe("none");
  });
});
