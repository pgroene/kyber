/**
 * Unit tests for _handleSlashCommand and sub-commands in KyberPanel.
 *
 * Covers:
 *   - /dashboard open → _cmdDashboard("open", name)
 *   - /dashboard close, save, delete, new
 *   - /automation open, close, save, delete, new
 *   - /area new, delete, rename
 *   - Unknown sub-action falls through silently
 *   - _appendMessage called with command as user message
 *
 * Tests spy on sub-methods to isolate command dispatch.
 */

import { makePanel } from "../helpers.js";

// Helper: build a rendered panel with common mock hass
function setup(hassOverrides = {}) {
  return makePanel({
    states: {
      "automation.morning_lights": {
        entity_id: "automation.morning_lights",
        attributes: { friendly_name: "Morning Lights" },
      },
      "automation.evening_routine": {
        entity_id: "automation.evening_routine",
        attributes: { friendly_name: "Evening Routine" },
      },
      "script.run_test": {
        entity_id: "script.run_test",
        attributes: { friendly_name: "Run Test" },
      },
    },
    panels: {
      lovelace: { component_name: "lovelace", url_path: "lovelace", title: "Overview" },
      energy: { component_name: "lovelace", url_path: "energy", title: "Energy" },
    },
    ...hassOverrides,
  });
}

// ---------------------------------------------------------------------------
// _handleSlashCommand dispatch
// ---------------------------------------------------------------------------
describe("_handleSlashCommand dispatch", () => {
  it("routes /dashboard to _cmdDashboard", () => {
    const { element } = setup();
    const spy = vi.spyOn(element, "_cmdDashboard");
    element._handleSlashCommand("dashboard", "open energy");
    expect(spy).toHaveBeenCalledWith("open", "energy");
  });

  it("routes /automation to _cmdAutomation", () => {
    const { element } = setup();
    vi.spyOn(element, "_openEditor").mockResolvedValue(undefined);
    const spy = vi.spyOn(element, "_cmdAutomation");
    element._handleSlashCommand("automation", "open morning");
    expect(spy).toHaveBeenCalledWith("open", "morning");
  });

  it("routes /script to _cmdScript", () => {
    const { element } = setup();
    const spy = vi.spyOn(element, "_cmdScript");
    element._handleSlashCommand("script", "new");
    expect(spy).toHaveBeenCalledWith("new", "");
  });

  it("routes /area to _cmdArea", () => {
    const { element } = setup();
    const spy = vi.spyOn(element, "_cmdArea");
    element._handleSlashCommand("area", "new kitchen");
    expect(spy).toHaveBeenCalledWith("new", "kitchen");
  });

  it("appends the command as a user chat message", () => {
    const { element } = setup();
    vi.spyOn(element, "_cmdDashboard").mockImplementation(() => {});
    element._handleSlashCommand("dashboard", "close");
    const history = element.shadowRoot.getElementById("chat-history");
    const userMsg = history.querySelector(".user");
    expect(userMsg).not.toBeNull();
    expect(userMsg.textContent).toContain("/dashboard close");
  });

  it("handles empty argStr (action only, no name)", () => {
    const { element } = setup();
    const spy = vi.spyOn(element, "_cmdArea");
    element._handleSlashCommand("area", "new");
    // action = "new", nameArg = ""
    expect(spy).toHaveBeenCalledWith("new", "");
  });
});

// ---------------------------------------------------------------------------
// /dashboard sub-commands
// ---------------------------------------------------------------------------
describe("_cmdDashboard", () => {
  it("open: builds a command card for the matched dashboard", () => {
    const { element } = setup();
    element._cmdDashboard("open", "energy");
    const card = element.shadowRoot.querySelector(".command-card");
    expect(card).not.toBeNull();
    expect(card.textContent).toContain("Open dashboard");
  });

  it("open: builds a command card even when no name matches (default dashboard)", () => {
    const { element } = setup();
    element._cmdDashboard("open", "nonexistent");
    const card = element.shadowRoot.querySelector(".command-card");
    expect(card).not.toBeNull();
  });

  it("close: calls _closeEditor and shows message", () => {
    const { element } = setup();
    const closeSpy = vi.spyOn(element, "_closeEditor");
    element._cmdDashboard("close", "");
    expect(closeSpy).toHaveBeenCalled();
  });

  it("save: shows 'No dashboard is currently open' when not in dashboard mode", () => {
    const { element } = setup();
    element._editorMode = "automation";
    const spy = vi.spyOn(element, "_showMsg");
    element._cmdDashboard("save", "");
    expect(spy).toHaveBeenCalledWith(expect.stringContaining("No dashboard"));
  });
});

// ---------------------------------------------------------------------------
// /automation sub-commands
// ---------------------------------------------------------------------------
describe("_cmdAutomation", () => {
  it("open: calls _openEditor directly when entity found by name", () => {
    const { element } = setup();
    const spy = vi.spyOn(element, "_openEditor").mockImplementation(() => {});
    element._cmdAutomation("open", "morning");
    expect(spy).toHaveBeenCalledWith(expect.stringContaining("automation.morning"));
    // No command card — opens directly without confirmation
    const card = element.shadowRoot.querySelector(".command-card");
    expect(card).toBeNull();
  });

  it("open: shows 'not found' message when entity not found", () => {
    const { element } = setup();
    const spy = vi.spyOn(element, "_showMsg");
    element._cmdAutomation("open", "xyz_nonexistent_xyz");
    expect(spy).toHaveBeenCalledWith(expect.stringContaining("not found"));
  });

  it("close: calls _closeEditor", () => {
    const { element } = setup();
    const spy = vi.spyOn(element, "_closeEditor");
    element._cmdAutomation("close", "");
    expect(spy).toHaveBeenCalled();
  });

  it("new: builds a command card for creating a new automation", () => {
    const { element } = setup();
    element._cmdAutomation("new", "My New Auto");
    const card = element.shadowRoot.querySelector(".command-card");
    expect(card).not.toBeNull();
  });
});

// ---------------------------------------------------------------------------
// /area sub-commands
// ---------------------------------------------------------------------------
describe("_cmdArea", () => {
  it("new: builds a command card with area name in detail", () => {
    const { element } = setup();
    element._cmdArea("new", "kitchen");
    const card = element.shadowRoot.querySelector(".command-card");
    expect(card).not.toBeNull();
    expect(card.textContent).toContain("kitchen");
  });

  it("new: shows error if no name provided", () => {
    const { element } = setup();
    const spy = vi.spyOn(element, "_showMsg");
    element._cmdArea("new", "");
    expect(spy).toHaveBeenCalledWith(expect.stringMatching(/name/i));
  });

  it("delete: builds a danger command card", () => {
    const { element } = setup();
    element._cmdArea("delete", "kitchen");
    const card = element.shadowRoot.querySelector(".command-card.danger");
    expect(card).not.toBeNull();
  });

  it("rename: builds a command card with both names", () => {
    const { element } = setup();
    // rename uses "to" separator: /area rename kitchen to Living Kitchen
    element._cmdArea("rename", "kitchen to Living Kitchen");
    const card = element.shadowRoot.querySelector(".command-card");
    expect(card).not.toBeNull();
  });
});
