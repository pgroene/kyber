/**
 * Integration tests for _saveAutomation in KyberPanel.
 *
 * Covers:
 *   - POSTs YAML to /api/kyber/parse_yaml for server-side parsing
 *   - Uses direct fetch POST to HA config endpoint (not hass.callApi)
 *   - Strips 'id' field from config body before posting
 *   - Shows success status and saves [CHANGE] entry in chat history
 *   - Shows error when parse_yaml fails
 *   - Shows meaningful error (not "undefined") when HA API returns error
 *   - Re-enables Save button on failure
 *   - Works for scripts (uses config/script/config/ API path)
 *   - Save button label reflects editor mode (automation / script / dashboard)
 */

import { makePanel } from "../helpers.js";

describe("_saveAutomation", () => {
  function setupWithEditor(editorYaml = "alias: my test\nmode: single") {
    const { element, hass } = makePanel();
    element._currentAutomationId = "my_test";
    element._editorMode = "automation";
    // Stub editor to return test YAML
    element._editor = {
      state: { doc: { toString: () => editorYaml } },
    };
    return { element, hass };
  }

  /** Build a fetch mock that succeeds for both parse_yaml and the HA save API. */
  function mockFetchSuccess(configFromParse = { alias: "my test", mode: "single" }) {
    return vi.fn().mockImplementation((url) => {
      if (url.includes("parse_yaml")) {
        return Promise.resolve({
          ok: true,
          text: async () => JSON.stringify({ config: configFromParse }),
          json: async () => ({ config: configFromParse }),
        });
      }
      // HA config API success
      return Promise.resolve({
        ok: true,
        status: 200,
        text: async () => JSON.stringify({ result: "ok" }),
        json: async () => ({ result: "ok" }),
      });
    });
  }

  beforeEach(() => {
    vi.stubGlobal("fetch", mockFetchSuccess());
  });
  afterEach(() => vi.unstubAllGlobals());

  it("calls /api/kyber/parse_yaml with the YAML content", async () => {
    const { element } = setupWithEditor("alias: my test");
    await element._saveAutomation();
    expect(fetch).toHaveBeenCalledWith("/api/kyber/parse_yaml", expect.any(Object));
    const body = JSON.parse(fetch.mock.calls[0][1].body);
    expect(body.yaml).toContain("alias: my test");
  });

  it("POSTs to the HA automation config API path via fetch", async () => {
    const { element } = setupWithEditor();
    await element._saveAutomation();
    const saveCalls = fetch.mock.calls.filter(([url]) =>
      url.includes("config/automation/config")
    );
    expect(saveCalls).toHaveLength(1);
    expect(saveCalls[0][0]).toContain("config/automation/config/my_test");
    expect(saveCalls[0][1].method).toBe("POST");
  });

  it("strips the 'id' field from the config body before saving", async () => {
    vi.stubGlobal("fetch", mockFetchSuccess({ alias: "my test", mode: "single", id: "my_test" }));
    const { element } = setupWithEditor();
    await element._saveAutomation();
    const saveCalls = fetch.mock.calls.filter(([url]) =>
      url.includes("config/automation")
    );
    const body = JSON.parse(saveCalls[0][1].body);
    expect(body.id).toBeUndefined();
    expect(body.alias).toBe("my test");
  });

  it("uses script API path when editorMode is script", async () => {
    const { element } = setupWithEditor();
    element._editorMode = "script";
    element._currentAutomationId = "my_script";
    await element._saveAutomation();
    const saveCalls = fetch.mock.calls.filter(([url]) =>
      url.includes("config/script/config")
    );
    expect(saveCalls).toHaveLength(1);
    expect(saveCalls[0][0]).toContain("config/script/config/my_script");
  });

  it("adds [CHANGE] entry to chat history after success", async () => {
    const { element } = setupWithEditor();
    await element._saveAutomation();
    const changeEntry = element._chatHistory.find(
      (m) => m.role === "assistant" && m.content.includes("[CHANGE]")
    );
    expect(changeEntry).not.toBeUndefined();
    expect(changeEntry.content).toContain("my_test");
  });

  it("shows success status after saving", async () => {
    const { element } = setupWithEditor();
    await element._saveAutomation();
    const bar = element.shadowRoot.getElementById("status-bar");
    expect(bar.textContent).toContain("Saved");
  });

  it("shows error status and re-enables button on parse_yaml failure", async () => {
    fetch.mockResolvedValue({ ok: false, status: 400, text: async () => "Invalid YAML" });
    const { element } = setupWithEditor("invalid: [unclosed");
    await element._saveAutomation();
    const bar = element.shadowRoot.getElementById("status-bar");
    expect(bar.textContent).toContain("Save failed");
    const saveBtn = element.shadowRoot.getElementById("btn-save");
    expect(saveBtn.disabled).toBe(false);
  });

  it("shows HTTP error message when HA config API returns non-2xx", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url) => {
      if (url.includes("parse_yaml")) {
        return Promise.resolve({
          ok: true,
          text: async () => JSON.stringify({ config: { alias: "test" } }),
          json: async () => ({ config: { alias: "test" } }),
        });
      }
      return Promise.resolve({
        ok: false,
        status: 400,
        text: async () => JSON.stringify({ message: "Invalid automation config" }),
      });
    }));
    const { element } = setupWithEditor();
    await element._saveAutomation();
    const bar = element.shadowRoot.getElementById("status-bar");
    expect(bar.textContent).toContain("Save failed");
    expect(bar.textContent).toContain("Invalid automation config");
    expect(bar.textContent).not.toContain("undefined");
  });

  it("shows HTTP status when HA config API returns empty error body", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url) => {
      if (url.includes("parse_yaml")) {
        return Promise.resolve({
          ok: true,
          text: async () => JSON.stringify({ config: { alias: "test" } }),
          json: async () => ({ config: { alias: "test" } }),
        });
      }
      return Promise.resolve({ ok: false, status: 500, text: async () => "" });
    }));
    const { element } = setupWithEditor();
    await element._saveAutomation();
    const bar = element.shadowRoot.getElementById("status-bar");
    expect(bar.textContent).toContain("Save failed");
    expect(bar.textContent).toContain("500");
    expect(bar.textContent).not.toContain("undefined");
  });

  it("does nothing when currentAutomationId is null", async () => {
    const { element } = setupWithEditor();
    element._currentAutomationId = null;
    await element._saveAutomation();
    expect(fetch).not.toHaveBeenCalled();
  });
});

describe("save button label", () => {
  function stubEditor(element) {
    // Pre-stub _editor so _initEditor (which uses CodeMirror) is not called
    element._editor = {
      state: { doc: { toString: () => "" } },
      requestMeasure: vi.fn(),
      dispatch: vi.fn(),
    };
  }

  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      text: async () => "",
      json: async () => ({ config: {} }),
    }));
  });
  afterEach(() => vi.unstubAllGlobals());

  it("shows 'Save automation' when opening an automation", async () => {
    const { element, hass } = makePanel({
      states: { "automation.sunup": { attributes: { id: "sunup", friendly_name: "Sunup" } } },
    });
    stubEditor(element);
    hass.callApi.mockResolvedValue({ alias: "sunup", mode: "single" });
    await element._openEditor("automation.sunup");
    const btn = element.shadowRoot.getElementById("btn-save");
    expect(btn.textContent).toBe("Save automation");
  });

  it("shows 'Save script' when opening a script", async () => {
    const { element, hass } = makePanel({
      states: { "script.my_script": { attributes: { id: "my_script", friendly_name: "My Script" } } },
    });
    stubEditor(element);
    hass.callApi.mockResolvedValue({ alias: "my script", mode: "single" });
    await element._openEditor("script.my_script");
    const btn = element.shadowRoot.getElementById("btn-save");
    expect(btn.textContent).toBe("Save script");
  });

  it("shows 'Save dashboard' when opening a dashboard", async () => {
    const { element, hass } = makePanel();
    stubEditor(element);
    hass.callWS = vi.fn().mockResolvedValue([]);
    hass.callApi.mockResolvedValue({ views: [] });
    await element._openDashboard(null);
    const btn = element.shadowRoot.getElementById("btn-save");
    expect(btn.textContent).toBe("Save dashboard");
  });

  it("resets label to 'Save' when editor is closed", async () => {
    const { element, hass } = makePanel({
      states: { "automation.sunup": { attributes: { id: "sunup", friendly_name: "Sunup" } } },
    });
    stubEditor(element);
    hass.callApi.mockResolvedValue({ alias: "sunup", mode: "single" });
    await element._openEditor("automation.sunup");
    element._closeEditor();
    const btn = element.shadowRoot.getElementById("btn-save");
    expect(btn.textContent).toBe("Save");
  });
});
