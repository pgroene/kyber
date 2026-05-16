/**
 * Unit tests for _onPromptInput autocomplete logic in KyberPanel.
 *
 * Covers:
 *   - Slash prefix (/d, /auto) shows matching command list
 *   - Sub-action autocomplete (/automation open <partial>) shows entity matches
 *   - Entity token autocomplete (when typing entity_id prefix)
 *   - Short token (< 2 chars) or no hass → dropdown closes
 *   - Hovering an item updates _acIndex so Enter accepts the selection
 *   - Moving mouse off list resets _acIndex to -1
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
    expect(element._acItems.some((i) => i.entity_id.includes("morning"))).toBe(true);
  });

  it("lists dashboards when typing /dashboard open <partial>", () => {
    const { element } = setup();
    element._onPromptInput({ value: "/dashboard open en", selectionStart: 18 });
    expect(element._acItems.some((i) => i.entity_id === "energy")).toBe(true);
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

// ---------------------------------------------------------------------------
// Hover → Enter acceptance
// ---------------------------------------------------------------------------
describe("_buildAcList — hover updates _acIndex", () => {
  it("hovering an item sets _acIndex to that item's index", () => {
    const { element } = setup();
    element._onPromptInput({ value: "turn on li", selectionStart: 10 });
    expect(element._acItems.length).toBeGreaterThan(0);

    const list = element.shadowRoot.getElementById("ac-list");
    const items = list.querySelectorAll(".ac-item");
    expect(items.length).toBeGreaterThan(0);

    // Simulate hover on the second item (index 1) if it exists, else first
    const targetIdx = items.length > 1 ? 1 : 0;
    items[targetIdx].dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));

    expect(element._acIndex).toBe(targetIdx);
    expect(items[targetIdx].classList.contains("active")).toBe(true);
  });

  it("mousing out of the list resets _acIndex to -1", () => {
    const { element } = setup();
    element._onPromptInput({ value: "turn on li", selectionStart: 10 });

    const list = element.shadowRoot.getElementById("ac-list");
    const items = list.querySelectorAll(".ac-item");
    items[0].dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
    expect(element._acIndex).toBe(0);

    list.dispatchEvent(new MouseEvent("mouseleave", { bubbles: false }));
    expect(element._acIndex).toBe(-1);
  });

  it("Enter applies hovered item when _acIndex was set by hover", () => {
    const { element } = setup();
    const textarea = element.shadowRoot.getElementById("prompt-input");
    textarea.value = "turn on li";
    textarea.selectionStart = 10;
    element._onPromptInput(textarea);

    const list = element.shadowRoot.getElementById("ac-list");
    const items = list.querySelectorAll(".ac-item");
    const hovered = items[0];
    hovered.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
    expect(element._acIndex).toBe(0);

    const expectedId = element._acItems[0].entity_id;
    const enterEvent = new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true });
    textarea.dispatchEvent(enterEvent);

    expect(textarea.value).toContain(expectedId);
    expect(list.classList.contains("open")).toBe(false);
  });
});
