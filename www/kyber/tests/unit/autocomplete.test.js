/**
 * Unit tests for _onPromptInput autocomplete logic in KyberPanel.
 *
 * Covers:
 *   - Slash prefix (/d, /auto) shows matching command list
 *   - Sub-action autocomplete (/automation open <partial>) shows entity matches
 *   - Entity token autocomplete (when typing entity_id prefix)
 *   - Short token (< 2 chars) or no hass → dropdown closes
 */

import { makePanel } from "../helpers.js";

function setup() {
  return makePanel({
    states: {
      "automation.morning_lights": {
        entity_id: "automation.morning_lights",
        attributes: { friendly_name: "Morning Lights" },
      },
      "light.bedroom": {
        entity_id: "light.bedroom",
        attributes: { friendly_name: "Bedroom" },
      },
      "light.lounge": {
        entity_id: "light.lounge",
        attributes: { friendly_name: "Lounge" },
      },
    },
    panels: {
      energy: { component_name: "lovelace", url_path: "energy", title: "Energy" },
    },
  });
}

// ---------------------------------------------------------------------------
// Slash prefix autocomplete
// ---------------------------------------------------------------------------
describe("_onPromptInput — slash prefix", () => {
  it("shows autocomplete list when typing /a", () => {
    const { element } = setup();
    const textarea = { value: "/a", selectionStart: 2 };
    element._onPromptInput(textarea);
    const list = element.shadowRoot.querySelector(".autocomplete-list");
    expect(list.classList.contains("open")).toBe(true);
    expect(element._acItems.length).toBeGreaterThan(0);
  });

  it("matches /automation command", () => {
    const { element } = setup();
    element._onPromptInput({ value: "/auto", selectionStart: 5 });
    expect(element._acItems.some((i) => i.entity_id.includes("automation"))).toBe(true);
  });

  it("shows all commands when typing just /", () => {
    const { element } = setup();
    element._onPromptInput({ value: "/", selectionStart: 1 });
    // "/" matches all commands since empty partial = all start with ""
    expect(element._acItems.length).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// Sub-action entity autocomplete
// ---------------------------------------------------------------------------
describe("_onPromptInput — sub-action autocomplete", () => {
  it("lists automations when typing /automation open <partial>", () => {
    const { element } = setup();
    element._onPromptInput({ value: "/automation open morn", selectionStart: 21 });
    // entity_id is now the full command with friendly name: "/automation open Morning Lights"
    expect(element._acItems.some((i) => i.entity_id.toLowerCase().includes("morning"))).toBe(true);
  });

  it("lists dashboards when typing /dashboard open <partial>", () => {
    const { element } = setup();
    element._onPromptInput({ value: "/dashboard open en", selectionStart: 18 });
    // entity_id is now "/dashboard open Energy"; friendly_name holds the url_path
    expect(element._acItems.some((i) => i.entity_id.toLowerCase().includes("energy"))).toBe(true);
  });

  it("lists scripts when typing /script open <partial>", () => {
    // No scripts in state — should produce empty match (closes list)
    const { element } = setup();
    const closeSpy = vi.spyOn(element, "_closeAc");
    element._onPromptInput({ value: "/script open xyz", selectionStart: 16 });
    expect(closeSpy).toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// Entity token autocomplete
// ---------------------------------------------------------------------------
describe("_onPromptInput — entity token autocomplete", () => {
  it("shows matching entities for 'li' prefix", () => {
    const { element } = setup();
    element._onPromptInput({ value: "turn on li", selectionStart: 10 });
    const list = element.shadowRoot.querySelector(".autocomplete-list");
    expect(list.classList.contains("open")).toBe(true);
    expect(element._acItems.some((i) => i.entity_id.startsWith("light."))).toBe(true);
  });

  it("closes autocomplete for a token shorter than 2 chars", () => {
    const { element } = setup();
    const closeSpy = vi.spyOn(element, "_closeAc");
    element._onPromptInput({ value: "l", selectionStart: 1 });
    expect(closeSpy).toHaveBeenCalled();
  });

  it("closes autocomplete when token matches nothing", () => {
    const { element } = setup();
    const closeSpy = vi.spyOn(element, "_closeAc");
    element._onPromptInput({ value: "zzz_no_match", selectionStart: 12 });
    expect(closeSpy).toHaveBeenCalled();
  });
});
