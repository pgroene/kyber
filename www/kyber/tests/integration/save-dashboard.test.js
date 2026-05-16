/**
 * Integration tests for _saveDashboard in KyberPanel.
 *
 * Covers:
 *   - POSTs YAML to /api/kyber/parse_yaml for server-side parsing
 *   - Uses direct fetch POST to HA Lovelace config endpoint (not hass.callApi)
 *   - Saves to url_path-specific endpoint when _currentDashboardPath is set
 *   - Saves to default endpoint when _currentDashboardPath is null
 *   - Shows success status and saves [CHANGE] entry in chat history
 *   - Shows meaningful error (not "undefined") when HA API returns error
 *   - Shows HTTP status when HA API returns empty error body
 *   - Re-enables Save button on failure
 */

import { makePanel } from "../helpers.js";

describe("_saveDashboard", () => {
  function setupWithEditor(dashboardPath = "my_dash", yaml = "title: My Dashboard\nviews: []") {
    const { element, hass } = makePanel();
    element._currentDashboardPath = dashboardPath;
    element._editorMode = "dashboard";
    element._editor = {
      state: { doc: { toString: () => yaml } },
    };
    return { element, hass };
  }

  function mockFetchSuccess(configFromParse = { title: "My Dashboard", views: [] }) {
    return vi.fn().mockImplementation((url) => {
      if (url.includes("parse_yaml")) {
        return Promise.resolve({
          ok: true,
          text: async () => JSON.stringify({ config: configFromParse }),
          json: async () => ({ config: configFromParse }),
        });
      }
      return Promise.resolve({ ok: true, status: 200, text: async () => "{}", json: async () => ({}) });
    });
  }

  beforeEach(() => vi.stubGlobal("fetch", mockFetchSuccess()));
  afterEach(() => vi.unstubAllGlobals());

  it("calls /api/kyber/parse_yaml with the YAML content", async () => {
    const { element } = setupWithEditor();
    await element._saveDashboard();
    expect(fetch).toHaveBeenCalledWith("/api/kyber/parse_yaml", expect.any(Object));
    const body = JSON.parse(fetch.mock.calls[0][1].body);
    expect(body.yaml).toContain("title: My Dashboard");
  });

  it("POSTs to /api/lovelace/config with url_path when path is set", async () => {
    const { element } = setupWithEditor("my_dash");
    await element._saveDashboard();
    const saveCalls = fetch.mock.calls.filter(([url]) => url.includes("lovelace/config"));
    expect(saveCalls).toHaveLength(1);
    expect(saveCalls[0][0]).toContain("lovelace/config?url_path=my_dash");
    expect(saveCalls[0][1].method).toBe("POST");
  });

  it("POSTs to /api/lovelace/config without url_path for default dashboard", async () => {
    const { element } = setupWithEditor(null);
    await element._saveDashboard();
    const saveCalls = fetch.mock.calls.filter(([url]) => url.includes("lovelace/config"));
    expect(saveCalls[0][0]).toBe("/api/lovelace/config");
  });

  it("shows success status after saving", async () => {
    const { element } = setupWithEditor();
    await element._saveDashboard();
    const bar = element.shadowRoot.getElementById("status-bar");
    expect(bar.textContent).toContain("saved ✓");
  });

  it("adds [CHANGE] entry to chat history after success", async () => {
    const { element } = setupWithEditor();
    await element._saveDashboard();
    const changeEntry = element._chatHistory.find(
      (m) => m.role === "assistant" && m.content.includes("[CHANGE]")
    );
    expect(changeEntry).not.toBeUndefined();
  });

  it("shows HTTP error message when HA API returns non-2xx", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url) => {
      if (url.includes("parse_yaml")) {
        return Promise.resolve({
          ok: true, text: async () => '{"config":{}}', json: async () => ({ config: {} }),
        });
      }
      return Promise.resolve({
        ok: false, status: 400,
        text: async () => JSON.stringify({ message: "Invalid dashboard config" }),
      });
    }));
    const { element } = setupWithEditor();
    await element._saveDashboard();
    const bar = element.shadowRoot.getElementById("status-bar");
    expect(bar.textContent).toContain("Save failed");
    expect(bar.textContent).toContain("Invalid dashboard config");
    expect(bar.textContent).not.toContain("undefined");
  });

  it("shows HTTP status when HA API returns empty error body", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url) => {
      if (url.includes("parse_yaml")) {
        return Promise.resolve({
          ok: true, text: async () => '{"config":{}}', json: async () => ({ config: {} }),
        });
      }
      return Promise.resolve({ ok: false, status: 500, text: async () => "" });
    }));
    const { element } = setupWithEditor();
    await element._saveDashboard();
    const bar = element.shadowRoot.getElementById("status-bar");
    expect(bar.textContent).toContain("Save failed");
    expect(bar.textContent).toContain("500");
    expect(bar.textContent).not.toContain("undefined");
  });

  it("re-enables save button on failure", async () => {
    fetch.mockResolvedValue({ ok: false, status: 400, text: async () => "bad" });
    const { element } = setupWithEditor();
    await element._saveDashboard();
    expect(element.shadowRoot.getElementById("btn-save").disabled).toBe(false);
  });
});
