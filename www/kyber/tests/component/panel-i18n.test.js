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

describe("getT singular", () => {
  it("uses <key>_one when n is 1", () => {
    expect(getT("en")("ss_delete_detail", { n: 1 })).toBe("1 message will be lost.");
    expect(getT("en")("ss_delete_detail", { n: 2 })).toBe("2 messages will be lost.");
    expect(getT("en")("ss_delete_detail", { n: 0 })).toBe("0 messages will be lost.");
    expect(getT("de")("ss_delete_detail", { n: 1 })).toBe("1 Nachricht geht verloren.");
    expect(getT("de")("ss_delete_detail", { n: 3 })).toBe("3 Nachrichten gehen verloren.");
    expect(getT("nl")("ut_ctx_entities", { n: 1 })).toBe("1 entiteit");
  });

  it("accepts a numeric string", () => {
    expect(getT("en")("ut_ctx_entities", { n: "1" })).toBe("1 entity");
  });

  it("keeps a locale's plural instead of borrowing the English singular", () => {
    // FR has no ss_* texts of its own and falls back to English as a whole.
    expect(getT("fr")("ss_delete_detail", { n: 1 })).toBe("1 message will be lost.");
  });

  it("no EN text with a plain {n} count lacks a singular", () => {
    // "{n} <word>s" with n === 1 reads "1 messages"; such keys need a _one text
    // (or an explicit singular key the caller picks, like ed_n_action).
    const explicitPairs = new Set(["ed_n_actions", "ed_n_conditions", "sc_msg_count_other"]);
    const missing = Object.entries(EN)
      .filter(([k, v]) => !k.endsWith("_one") && /\{n\}\s+[A-Za-z]+s\b/.test(v))
      .filter(([k]) => !(`${k}_one` in EN) && !explicitPairs.has(k) && !/_(other|many)$/.test(k))
      .map(([k]) => k);
    expect(missing).toEqual([]);
  });
});

describe("session list and delete in the singular", () => {
  it("/session delete with one message", async () => {
    const { element } = makePanel({ language: "en" });
    element._chatHistory = [{ role: "user", content: "hi" }];
    element._getActiveSession = () => ({ id: "s1", name: "Test" });
    await element._handleSessionCommand("delete");
    const card = element.shadowRoot.querySelector(".command-card");
    expect(card.querySelector(".command-card-detail").textContent).toBe("1 message will be lost.");
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
