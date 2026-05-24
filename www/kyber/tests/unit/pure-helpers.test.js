/**
 * Unit tests for pure helper methods in KyberPanel.
 *
 * Covers:
 *   - _escapeHtml(str)
 *   - _getTokenAtCursor(textarea)
 *   - _extractSuggestions(text)
 *   - _jsonToYaml(obj, indent) / _configToYaml(config)
 *   - _findEntity(prefix, nameArg)
 *
 * These functions have no DOM side-effects and can be tested via
 * a bare element instance without triggering a full render.
 */

import { makeUnrenderedPanel, mockTextarea } from "../helpers.js";

// ---------------------------------------------------------------------------
// _escapeHtml
// ---------------------------------------------------------------------------
describe("_escapeHtml", () => {
  let el;
  beforeEach(() => { el = makeUnrenderedPanel(); });

  it("escapes ampersand", () => {
    expect(el._escapeHtml("a & b")).toBe("a &amp; b");
  });

  it("escapes less-than", () => {
    expect(el._escapeHtml("<script>")).toBe("&lt;script&gt;");
  });

  it("escapes greater-than", () => {
    expect(el._escapeHtml("a > b")).toBe("a &gt; b");
  });

  it("escapes all three in one string", () => {
    expect(el._escapeHtml('a & b < c > d')).toBe("a &amp; b &lt; c &gt; d");
  });

  it("leaves plain text unchanged", () => {
    expect(el._escapeHtml("hello world")).toBe("hello world");
  });

  it("handles empty string", () => {
    expect(el._escapeHtml("")).toBe("");
  });
});

describe("_escapeAttr", () => {
  let el;
  beforeEach(() => { el = makeUnrenderedPanel(); });

  it("escapes quotes for HTML attributes", () => {
    expect(el._escapeAttr('"hello" \'world\'')).toBe("&quot;hello&quot; &#39;world&#39;");
  });

  it("escapes html-special chars and handles null input", () => {
    expect(el._escapeAttr("<x&y>")).toBe("&lt;x&amp;y&gt;");
    expect(el._escapeAttr(null)).toBe("");
  });
});

// ---------------------------------------------------------------------------
// _getTokenAtCursor
// ---------------------------------------------------------------------------
describe("_getTokenAtCursor", () => {
  let el;
  beforeEach(() => { el = makeUnrenderedPanel(); });

  it("returns the word at end of input", () => {
    expect(el._getTokenAtCursor(mockTextarea("light.living_room"))).toBe("light.living_room");
  });

  it("returns the word before cursor, not after", () => {
    // cursor after "entity" in "entity.id more"
    expect(el._getTokenAtCursor(mockTextarea("entity.id more", 9))).toBe("entity.id");
  });

  it("stops at space boundary", () => {
    expect(el._getTokenAtCursor(mockTextarea("turn on light.bedroom"))).toBe("light.bedroom");
  });

  it("returns empty string when cursor is at start", () => {
    expect(el._getTokenAtCursor(mockTextarea("hello", 0))).toBe("");
  });

  it("returns empty string for empty input", () => {
    expect(el._getTokenAtCursor(mockTextarea(""))).toBe("");
  });

  it("matches dots and hyphens within the token", () => {
    expect(el._getTokenAtCursor(mockTextarea("sensor.my-device"))).toBe("sensor.my-device");
  });
});

// ---------------------------------------------------------------------------
// _extractSuggestions
// ---------------------------------------------------------------------------
describe("_extractSuggestions", () => {
  let el;
  beforeEach(() => { el = makeUnrenderedPanel(); });

  it("extracts bold words from bullet list (strategy 1)", () => {
    const text = `You could:
- **Turn on** the lights
- **Set temperature** to 22
- **Lock the door** now`;
    const chips = el._extractSuggestions(text);
    expect(chips).toContain("Turn on");
    expect(chips).toContain("Set temperature");
    expect(chips.length).toBeGreaterThanOrEqual(2);
  });

  it("returns yes/no for binary confirmation text", () => {
    const chips = el._extractSuggestions("Should I proceed? You can confirm with yes or no.");
    expect(chips).toEqual(["Yes", "No"]);
  });

  it("returns empty array for short plain text with no patterns", () => {
    const chips = el._extractSuggestions("Done.");
    expect(chips).toEqual([]);
  });

  it("extracts verb phrases from bullet list when no bold words", () => {
    const text = `Options:\n- Turn on the lights\n- Set a timer for 5 minutes\n- Lock the front door`;
    const chips = el._extractSuggestions(text);
    expect(chips.length).toBeGreaterThanOrEqual(2);
  });

  it("caps results at 6 suggestions", () => {
    const bullets = Array.from({ length: 8 }, (_, i) => `- **Option ${i + 1}** text`).join("\n");
    const chips = el._extractSuggestions(bullets);
    expect(chips.length).toBeLessThanOrEqual(6);
  });
});

// ---------------------------------------------------------------------------
// _jsonToYaml / _configToYaml
// ---------------------------------------------------------------------------
describe("_jsonToYaml", () => {
  let el;
  beforeEach(() => { el = makeUnrenderedPanel(); });

  it("serialises null to 'null'", () => {
    expect(el._jsonToYaml(null, 0)).toBe("null");
  });

  it("serialises booleans", () => {
    expect(el._jsonToYaml(true, 0)).toBe("true");
    expect(el._jsonToYaml(false, 0)).toBe("false");
  });

  it("serialises numbers", () => {
    expect(el._jsonToYaml(42, 0)).toBe("42");
    expect(el._jsonToYaml(3.14, 0)).toBe("3.14");
  });

  it("serialises a plain string without quotes", () => {
    expect(el._jsonToYaml("hello", 0)).toBe("hello");
  });

  it("quotes strings with special YAML characters", () => {
    // colon in string requires quoting
    const result = el._jsonToYaml("value: here", 0);
    expect(result).toContain('"');
  });

  it("serialises an empty array as empty string", () => {
    expect(el._jsonToYaml([], 0)).toBe("");
  });

  it("serialises an array with items as YAML list", () => {
    const result = el._jsonToYaml(["a", "b"], 0);
    expect(result).toContain("- a");
    expect(result).toContain("- b");
  });

  it("serialises an empty object as empty string", () => {
    expect(el._jsonToYaml({}, 0)).toBe("");
  });

  it("serialises a flat object with key: value pairs", () => {
    const result = el._jsonToYaml({ alias: "test", mode: "single" }, 0);
    expect(result).toContain("alias: test");
    expect(result).toContain("mode: single");
  });

  it("handles nested objects with indentation", () => {
    const obj = { trigger: { platform: "state" } };
    const result = el._jsonToYaml(obj, 0);
    expect(result).toContain("trigger:");
    expect(result).toContain("platform: state");
  });
});

describe("_configToYaml", () => {
  let el;
  beforeEach(() => { el = makeUnrenderedPanel(); });

  it("produces YAML from a simple config object", () => {
    const config = { alias: "My Automation", mode: "single" };
    const result = el._configToYaml(config);
    expect(result).toContain("alias: My Automation");
    expect(result).toContain("mode: single");
  });
});

// ---------------------------------------------------------------------------
// _findEntity
// ---------------------------------------------------------------------------
describe("_findEntity", () => {
  const states = {
    "automation.morning_lights": {
      entity_id: "automation.morning_lights",
      attributes: { friendly_name: "Morning Lights" },
    },
    "automation.evening_routine": {
      entity_id: "automation.evening_routine",
      attributes: { friendly_name: "Evening Routine" },
    },
    "light.bedroom": {
      entity_id: "light.bedroom",
      attributes: { friendly_name: "Bedroom Light" },
    },
  };

  let el;
  beforeEach(() => {
    el = makeUnrenderedPanel({ states });
  });

  it("returns null when nameArg is falsy", () => {
    expect(el._findEntity("automation", "")).toBeNull();
    expect(el._findEntity("automation", null)).toBeNull();
  });

  it("returns null when no match found", () => {
    expect(el._findEntity("automation", "nonexistent")).toBeNull();
  });

  it("matches by exact entity_id", () => {
    const result = el._findEntity("automation", "automation.morning_lights");
    expect(result.entity_id).toBe("automation.morning_lights");
  });

  it("matches by entity_id suffix without prefix", () => {
    const result = el._findEntity("automation", "morning_lights");
    expect(result.entity_id).toBe("automation.morning_lights");
  });

  it("matches by friendly_name substring (case-insensitive)", () => {
    const result = el._findEntity("automation", "evening");
    expect(result.entity_id).toBe("automation.evening_routine");
  });

  it("only searches within the given prefix", () => {
    // "bedroom" matches light.bedroom but not automation.*
    const result = el._findEntity("automation", "bedroom");
    expect(result).toBeNull();
  });

  it("returns null for empty states", () => {
    el._hass.states = {};
    expect(el._findEntity("automation", "morning")).toBeNull();
  });
});

describe("_getDeepLearningRuns", () => {
  let el;
  beforeEach(() => { el = makeUnrenderedPanel(); });

  it("returns selected run count", () => {
    const root = { querySelector: () => ({ value: "4" }) };
    expect(el._getDeepLearningRuns(root)).toBe(4);
  });

  it("clamps invalid values to supported range", () => {
    const low = { querySelector: () => ({ value: "0" }) };
    const high = { querySelector: () => ({ value: "99" }) };
    expect(el._getDeepLearningRuns(low)).toBe(1);
    expect(el._getDeepLearningRuns(high)).toBe(10);
  });
});
