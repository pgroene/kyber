/**
 * The automation edit/create cards used hard-coded Dutch labels
 * ("▼ Bekijk", "✓ Toepassen", "✕ Annuleren", …) regardless of the HA language.
 * They now come from i18n.js; these tests pin German, English and Dutch.
 */

import { makePanel } from "../helpers.js";

const editPlan = {
  type: "edit_automation",
  entity_id: "automation.porch_light",
  automation_id: "porch_light",
  summary: "Turn on at sunset",
  original_config: { alias: "Porch light", trigger: [], action: [] },
  modified_config: { alias: "Porch light", trigger: [{ platform: "sun", event: "sunset" }], action: [] },
};

const createPlan = { type: "create_automation", summary: "New one", config: { trigger: [], action: [] } };

const buttons = (card) => ({
  expand: card.querySelector(".ae-btn-expand").textContent,
  apply: card.querySelector(".ae-btn-apply").textContent,
  cancel: card.querySelector(".ae-btn-cancel").textContent,
});

const DUTCH = /Bekijk|Toepassen|Annuleren|Aanmaken|Nieuwe automatisering/;

describe("automation cards — translated labels", () => {
  it("German edit card", () => {
    const { element } = makePanel({ language: "de" });
    const card = element._buildEditAutomationCard(editPlan);
    expect(buttons(card)).toEqual({ expand: "▼ Anzeigen", apply: "✓ Übernehmen", cancel: "✕ Abbrechen" });
    expect(card.textContent).not.toMatch(DUTCH);
  });

  it("German create card, including the default title", () => {
    const { element } = makePanel({ language: "de" });
    const card = element._buildCreateAutomationCard(createPlan);
    expect(buttons(card)).toEqual({ expand: "▼ Anzeigen", apply: "✓ Anlegen", cancel: "✕ Abbrechen" });
    expect(card.querySelector(".ae-title").textContent).toBe("Neue Automatisierung");
    expect(card.textContent).not.toMatch(DUTCH);
  });

  it("English is used when the language has no translation", () => {
    const { element } = makePanel({ language: "fi" });
    const card = element._buildEditAutomationCard(editPlan);
    expect(buttons(card)).toEqual({ expand: "▼ View", apply: "✓ Apply", cancel: "✕ Cancel" });
  });

  it("Dutch keeps the previous labels", () => {
    const { element } = makePanel({ language: "nl" });
    const card = element._buildCreateAutomationCard(createPlan);
    expect(buttons(card)).toEqual({ expand: "▼ Bekijk", apply: "✓ Aanmaken", cancel: "✕ Annuleren" });
  });

  it("expand toggles between the translated view/hide labels", () => {
    const { element } = makePanel({ language: "de" });
    const card = element._buildEditAutomationCard(editPlan);
    const btn = card.querySelector(".ae-btn-expand");
    btn.click();
    expect(btn.textContent).toBe("▲ Ausblenden");
    btn.click();
    expect(btn.textContent).toBe("▼ Anzeigen");
  });
});
