/**
 * Unit tests for _configToYaml string quoting in KyberPanel.
 *
 * The panel serializes automation config to YAML; the backend parses it with
 * PyYAML yaml.safe_load (YAML 1.1). A plain string must be emitted QUOTED
 * whenever YAML 1.1 would read it as something else (bool/null/number) or
 * cut it off (comments, flow indicators, leading/trailing whitespace, ...).
 *
 * Quoting spec (R1..R7 — a string is quoted if ANY rule matches):
 *   R1 empty string
 *   R2 equals (case-insensitive) true false yes no on off y n null ~
 *   R3 starts with a digit, or with "-", "+", "." followed by a digit
 *   R4 contains one of : { } [ ] , & * ? | < > = ! % @ ` # ' "
 *   R5 starts or ends with a space or a tab
 *   R6 starts with "- " or equals "-"
 *   R7 contains a newline or any other control character (escaped)
 *
 * Non-strings (true/false/numbers/null) are never quoted.
 *
 * NOTE: several cases intentionally FAIL against the current serializer
 * (notably R2 "on"/"off"/"y"/"n" and R6 "- item"). The serializer fix lands
 * separately; do not weaken these expectations.
 */

import { makeUnrenderedPanel } from "../helpers.js";

describe("_configToYaml string quoting", () => {
  let el;
  beforeEach(() => { el = makeUnrenderedPanel(); });

  const cases = [
    // R1 — empty string
    ["", '""', "R1"],

    // R2 — YAML 1.1 booleans / null (case-insensitive)
    ["true", '"true"', "R2"],
    ["false", '"false"', "R2"],
    ["yes", '"yes"', "R2"],
    ["no", '"no"', "R2"],
    ["on", '"on"', "R2"],
    ["off", '"off"', "R2"],
    ["On", '"On"', "R2"],
    ["NO", '"NO"', "R2"],
    ["y", '"y"', "R2"],
    ["N", '"N"', "R2"],
    ["null", '"null"', "R2"],
    ["~", '"~"', "R2"],

    // R3 — number-like
    ["21", '"21"', "R3"],
    ["-5", '"-5"', "R3"],
    [".5", '".5"', "R3"],
    ["1e3", '"1e3"', "R3"],
    ["07:30", '"07:30"', "R3"],
    ["+3", '"+3"', "R3"],

    // R4 — special characters (comment cut-off, flow indicators, anchors, ...)
    ["#ff0000", '"#ff0000"', "R4"],
    ["Lights #2", '"Lights #2"', "R4"],
    ['say "hi"', '"say \\"hi\\""', "R4"],
    ["a: b", '"a: b"', "R4"],
    ["a,b", '"a,b"', "R4"],
    ["a{b}", '"a{b}"', "R4"],
    ["a[b]", '"a[b]"', "R4"],
    ["a&b", '"a&b"', "R4"],
    ["a*b", '"a*b"', "R4"],
    ["a?b", '"a?b"', "R4"],
    ["a|b", '"a|b"', "R4"],
    ["a<b", '"a<b"', "R4"],
    ["a=b", '"a=b"', "R4"],
    ["a!b", '"a!b"', "R4"],
    ["a%b", '"a%b"', "R4"],
    ["a@b", '"a@b"', "R4"],
    ["a`b", '"a`b"', "R4"],
    ["it's", "\"it's\"", "R4"],

    // R5 — leading/trailing space or tab
    [" led", '" led"', "R5"],
    ["led ", '"led "', "R5"],
    ["\tlead", '"\\tlead"', "R5"],
    ["trail\t", '"trail\\t"', "R5"],

    // R6 — sequence item prefix
    ["- item", '"- item"', "R6"],
    ["-", '"-"', "R6"],

    // R7 — newline (escaped as \n in the quoted form)
    ["a\nb", '"a\\nb"', "R7"],
    ["line1\nline2\n", '"line1\\nline2\\n"', "R7"],
    ["a\rb", '"a\\rb"', "R7"],
    ["a\u0001b", '"a\\u0001b"', "R7"],

    // Bare (unquoted) — no rule matches
    ["kitchen", "kitchen", "bare"],
    ["Woonkamer lamp", "Woonkamer lamp", "bare"],
    ["light.kitchen", "light.kitchen", "bare"],
    ["turn_on", "turn_on", "bare"],
    ["Lights 2", "Lights 2", "bare"],
    ["über", "über", "bare"],
  ];

  // [input, expected scalar after "value: ", rule]
  cases.forEach(([input, expected, rule]) => {
    it(`quotes ${JSON.stringify(input)} as ${JSON.stringify(expected)} (${rule})`, () => {
      expect(el._configToYaml({ value: input })).toBe(`value: ${expected}`);
    });
  });

  it("quotes non-string scalars never", () => {
    expect(el._configToYaml({ value: true })).toBe("value: true");
    expect(el._configToYaml({ value: false })).toBe("value: false");
    expect(el._configToYaml({ value: 21 })).toBe("value: 21");
    expect(el._configToYaml({ value: 1.5 })).toBe("value: 1.5");
    expect(el._configToYaml({ value: null })).toBe("value: null");
  });
});

describe("_configToYaml structure", () => {
  let el;
  beforeEach(() => { el = makeUnrenderedPanel(); });

  it("indents nested objects and quotes reserved values inside them", () => {
    const out = el._configToYaml({ trigger: { platform: "state", to: "on" } });
    expect(out).toContain('  to: "on"');
    expect(out).toContain("  platform: state");
  });

  it("emits sequences with '- ' items and quotes reserved entries", () => {
    const out = el._configToYaml({ list: ["on", "kitchen"] });
    expect(out).toContain('- "on"');
    expect(out).toContain("- kitchen");
  });

  it("keeps booleans, numbers and null unquoted", () => {
    const out = el._configToYaml({ a: true, b: 21, c: null });
    expect(out).toContain("a: true");
    expect(out).toContain("b: 21");
    expect(out).toContain("c: null");
  });
});
