/**
 * The generic proposal card and most other panel texts were hard-coded in
 * English ("Proposal", "What will change", "Execute", "1 action(s) failed: …",
 * raw type codes like "EDIT_AUTOMATION"). They now come from i18n.js.
 *
 * Also covers the automation edit card reading the current config from HA
 * when a plan has no original_config, so Undo restores the real old state.
 */

import { makePanel } from "../helpers.js";
import { EN, NL, DE, getT } from "kyber-www/src/i18n.js";

const flushPromises = () => new Promise((resolve) => setTimeout(resolve, 0));

const editActionPlan = {
  summary: "Korrigiert die Automatisierung",
  actions: [{ type: "edit_automation", modified_config: { alias: "Heizung", trigger: [], action: [] } }],
  warnings: ["Reagiert auch auf manuelle Änderungen"],
};

describe("getT placeholders", () => {
  it("fills named placeholders", () => {
    expect(getT("en")("pc_failed", { n: 2, msg: "boom" })).toBe(EN.pc_failed.replace("{n}", "2").replace("{msg}", "boom"));
  });

  it("leaves unknown placeholders and plain lookups alone", () => {
    const t = getT("en");
    expect(t("pc_failed", {})).toBe(EN.pc_failed);
    expect(t("btn_ask")).toBe("Ask");
  });
});

describe("locales stay complete", () => {
  it("NL and DE define every EN key and keep its placeholders", () => {
    const ph = (s) => (s.match(/\{\w+\}/g) || []).sort().join(",");
    for (const locale of [NL, DE]) {
      const broken = Object.keys(EN).filter((k) => !(k in locale) || ph(locale[k]) !== ph(EN[k]));
      expect(broken).toEqual([]);
    }
  });

  it("DE uses no long dash", () => {
    expect(Object.entries(DE).filter(([, v]) => v.includes("—"))).toEqual([]);
  });
});

describe("proposal card in German", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => vi.unstubAllGlobals());

  it("translates the card chrome and the edit_automation badge", () => {
    const { element } = makePanel({ language: "de" });
    const card = element._buildPlanCard(editActionPlan);

    expect(card.querySelector(".plan-overview-label").textContent).toBe(DE.pc_proposal);
    expect(card.querySelector(".plan-changes-header").textContent).toBe(DE.pc_what_will_change);
    expect(card.querySelector(".btn-execute").textContent).toBe(DE.pc_execute);
    expect(card.querySelector(".change-type-badge").textContent).toBe(DE.pc_type_edit_automation);
    expect(card.textContent).not.toMatch(/Proposal|What will change|Execute/);
  });

  it("reports failed actions in German", async () => {
    fetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ results: [{ status: "error", message: "boom" }] }),
    });
    const { element } = makePanel({ language: "de" });
    const card = element._buildPlanCard(editActionPlan);
    element.shadowRoot.getElementById("chat-history").appendChild(card);
    card.querySelector(".btn-execute").click();
    await flushPromises();

    const resultEl = card.querySelector(".plan-result");
    expect(resultEl.textContent).toContain("boom");
    expect(resultEl.textContent).not.toContain("action(s) failed");
  });
});

describe("automation edit card without original_config", () => {
  const plan = {
    edit_automation: true,
    automation_id: "1712345678901",
    entity_id: "automation.heizung",
    modified_config: { alias: "Heizung", trigger: [{ platform: "state" }], action: [] },
  };
  const current = { id: "1712345678901", alias: "Heizung", trigger: [], action: [] };

  it("reads the current config before saving and undoes to it", async () => {
    const { element, hass } = makePanel({ language: "de" });
    hass.callApi.mockImplementation(async (method) => (method === "GET" ? current : {}));
    hass.callApi.mockClear();
    const card = element._buildEditAutomationCard(plan);

    card.querySelector(".ae-btn-apply").click();
    await flushPromises();
    expect(hass.callApi.mock.calls[0]).toEqual(["GET", "config/automation/config/1712345678901"]);
    expect(hass.callApi.mock.calls[1][0]).toBe("POST");
    expect(hass.callApi.mock.calls[1][2].trigger).toEqual(plan.modified_config.trigger);

    const undo = card.querySelector(".ae-btn-cancel");
    expect(undo.textContent).toBe(DE.ae_undo);
    await undo.onclick();
    expect(hass.callApi.mock.calls[2]).toEqual(["POST", "config/automation/config/1712345678901", current]);
  });

  it("hides Undo when the current config cannot be read", async () => {
    const { element, hass } = makePanel({ language: "de" });
    hass.callApi.mockImplementation(async (method) => {
      if (method === "GET") throw new Error("404");
      return {};
    });
    hass.callApi.mockClear();
    const card = element._buildEditAutomationCard(plan);
    card.querySelector(".ae-btn-apply").click();
    await flushPromises();

    expect(card.querySelector(".ae-btn-apply").textContent).toBe(DE.ae_saved);
    expect(card.querySelector(".ae-btn-cancel").style.display).toBe("none");
  });
});
