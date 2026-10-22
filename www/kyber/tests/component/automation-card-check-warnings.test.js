/**
 * The backend checks a proposed automation and asks the model for up to two
 * corrections. What is still wrong afterwards arrives as
 * plan.check_warnings and must be visible on the card, translated, before
 * the user applies it.
 */

import { makePanel } from "../helpers.js";

const warnings = [
  {
    severity: "error", key: "bad_value", text: "'Lower' is not a valid state of input_select.heating_mode.",
    params: { entity_id: "input_select.heating_mode", attribute: "", value: "Lower", valid: ["Heat", "Setback"] },
  },
  {
    severity: "error", key: "bad_value", text: "'Day' is not a valid attribute 'mode' of schedule.heating_schedule.",
    params: { entity_id: "schedule.heating_schedule", attribute: "mode", value: "Day", valid: ["Auto", "Setback"] },
  },
  { severity: "error", key: "rule_hvac_mode", text: "climate.set_temperature without hvac_mode …", params: {} },
  { severity: "error", key: "unknown_future_key", text: "A finding the panel has no text for.", params: {} },
];

const editPlan = {
  edit_automation: true,
  entity_id: "automation.heating",
  automation_id: "heating",
  summary: "Heating",
  original_config: { alias: "Heating", triggers: [], actions: [] },
  modified_config: { alias: "Heating", triggers: [], actions: [] },
  check_warnings: warnings,
};

const items = (card) => [...card.querySelectorAll(".ae-check-warnings li")].map((li) => li.textContent);

describe("automation cards: remaining check findings", () => {
  it("German edit card lists every finding, translated where a text exists", () => {
    const { element } = makePanel({ language: "de" });
    const card = element._buildEditAutomationCard(editPlan);
    expect(card.querySelector(".ae-check-title").textContent).toBe("⚠ Bei der Prüfung dieses Vorschlags sind Probleme geblieben:");
    expect(items(card)).toEqual([
      "„Lower“ ist kein gültiger Zustand von input_select.heating_mode. Gültig: Heat, Setback.",
      "„Day“ ist kein gültiger Wert von „mode“ bei schedule.heating_schedule. Gültig: Auto, Setback.",
      "climate.set_temperature ohne hvac_mode schaltet ein ausgeschaltetes Thermostat nicht ein.",
      "A finding the panel has no text for.",
    ]);
  });

  it("create card shows them too", () => {
    const { element } = makePanel({ language: "en" });
    const card = element._buildCreateAutomationCard({ create_automation: true, summary: "x", config: {}, check_warnings: warnings.slice(2, 3) });
    expect(items(card)).toEqual(["climate.set_temperature without hvac_mode does not switch on a thermostat that is off."]);
  });

  it("a plan without findings has no warning block", () => {
    const { element } = makePanel({ language: "de" });
    const card = element._buildEditAutomationCard({ ...editPlan, check_warnings: undefined });
    expect(card.querySelector(".ae-check-warnings")).toBeNull();
  });

  it("finding texts are escaped", () => {
    const { element } = makePanel({ language: "en" });
    const card = element._buildEditAutomationCard({
      ...editPlan,
      check_warnings: [{ severity: "error", key: "schema", text: "x", params: { message: "<img src=x onerror=alert(1)>" } }],
    });
    expect(card.querySelector(".ae-check-warnings img")).toBeNull();
    expect(items(card)[0]).toContain("<img src=x onerror=alert(1)>");
  });
});
