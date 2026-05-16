/**
 * Integration tests for _saveAutomation in KyberPanel.
 *
 * Covers:
 *   - POSTs YAML to /api/kyber/parse_yaml for server-side parsing
 *   - Uses parsed config to call hass.callApi POST to HA config endpoint
 *   - Shows success status and saves [CHANGE] entry in chat history
 *   - Shows error when parse_yaml fails
 *   - Re-enables Save button on failure
 *   - Works for scripts (uses config/script/config/ API path)
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

  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      text: async () => "",
      json: async () => ({ config: { alias: "my test", mode: "single" } }),
    }));
  });
  afterEach(() => vi.unstubAllGlobals());

  it("calls /api/kyber/parse_yaml with the YAML content", async () => {
    const { element } = setupWithEditor("alias: my test");
    await element._saveAutomation();
    expect(fetch).toHaveBeenCalledWith("/api/kyber/parse_yaml", expect.any(Object));
    const body = JSON.parse(fetch.mock.calls[0][1].body);
    expect(body.yaml).toContain("alias: my test");
  });

  it("calls hass.callApi POST with the parsed config", async () => {
    const { element, hass } = setupWithEditor();
    await element._saveAutomation();
    expect(hass.callApi).toHaveBeenCalledWith(
      "POST",
      "config/automation/config/my_test",
      { alias: "my test", mode: "single" }
    );
  });

  it("uses script API path when editorMode is script", async () => {
    const { element, hass } = setupWithEditor();
    element._editorMode = "script";
    element._currentAutomationId = "my_script";
    await element._saveAutomation();
    expect(hass.callApi).toHaveBeenCalledWith(
      "POST",
      "config/script/config/my_script",
      expect.any(Object)
    );
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
    fetch.mockResolvedValue({ ok: false, text: async () => "Invalid YAML" });
    const { element } = setupWithEditor("invalid: [unclosed");
    await element._saveAutomation();
    const bar = element.shadowRoot.getElementById("status-bar");
    expect(bar.textContent).toContain("Save failed");
    const saveBtn = element.shadowRoot.getElementById("btn-save");
    expect(saveBtn.disabled).toBe(false);
  });

  it("does nothing when currentAutomationId is null", async () => {
    const { element } = setupWithEditor();
    element._currentAutomationId = null;
    await element._saveAutomation();
    expect(fetch).not.toHaveBeenCalled();
  });
});
