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
    expect(getT("en")("pc_failed", { n: 2, msg: "boom" })).toBe("⚠ 2 actions failed: boom");
  });

  it("leaves unknown placeholders and plain lookups alone", () => {
    const t = getT("en");
    expect(t("pc_failed", {})).toBe(EN.pc_failed);
    expect(t("btn_ask")).toBe("Ask");
  });
});

describe("getT plurals", () => {
  it("picks the singular form for 1 and the plural otherwise", () => {
    expect(getT("en")("ss_delete_detail", { n: 1 })).toBe("1 message will be lost.");
    expect(getT("en")("ss_delete_detail", { n: 2 })).toBe("2 messages will be lost.");
    expect(getT("en")("ss_delete_detail", { n: 0 })).toBe("0 messages will be lost.");
    expect(getT("de")("ss_delete_detail", { n: 1 })).toBe("1 Nachricht geht verloren.");
    expect(getT("de")("ss_delete_detail", { n: 3 })).toBe("3 Nachrichten gehen verloren.");
    expect(getT("nl")("ut_ctx_entities", { n: 1 })).toBe("1 entiteit");
  });

  it("accepts a numeric string and leaves non-numbers plural", () => {
    expect(getT("en")("ut_ctx_entities", { n: "1" })).toBe("1 entity");
    expect(getT("en")("dbg_chars_tokens", { chars: "1,234", tokens: "1" })).toBe("1,234 chars (~1 token)");
  });

  it("handles several counts in one text, verbs included", () => {
    expect(getT("en")("dbg_dj_progress", { analyzed: 4, facts: 1, errors: 2 })).toBe("4 analyzed · 1 fact · 2 errors");
    expect(getT("de")("dbg_dj_progress", { analyzed: 4, facts: 1, errors: 1 })).toBe("4 analysiert · 1 Fakt · 1 Fehler");
    expect(getT("de")("pc_approval_required", { n: 1 })).toBe("🔒 1 Aktion erfordert eine Freigabe.");
    expect(getT("en")("pc_missing_entities", { n: 1, ids: "light.x" }))
      .toBe("⛔ 1 entity ID not found in Home Assistant: light.x. This action will be skipped.");
    expect(getT("de")("kn_no_proposals", { automations: 1, scenes: 0, scripts: 2 }))
      .toBe("Keine neuen Vorschläge. 1 Automatisierung, 0 Szenen und 2 Skripte durchsucht.");
  });

  it("leaves a plural placeholder alone when its value is missing", () => {
    expect(getT("en")("dbg_hits", { other: 1 })).toBe(EN.dbg_hits);
  });

  it("no EN text puts a plain count before a plural word", () => {
    // "{x} <word>s" reads "1 messages" for x = 1: use "{x|# message|# messages}"
    // (or an explicit singular key the caller picks, like ed_n_action).
    const allowed = new Set([
      "ed_n_conditions", "sc_msg_count_other",  // caller picks ed_n_condition / sc_msg_count_one
      "dbg_rv_hide_for_days",                   // {input} is an <input> field, not a number
      "sc_cmd_list",                            // {cmd} is a command name
    ]);
    const plainCount = /(?<!v)\{\w+\}\s+[A-Za-z]+s\b/;  // not "v{ver} is"
    const offenders = Object.entries(EN)
      .filter(([k, v]) => plainCount.test(v) && !allowed.has(k) && !/_(other|many)$/.test(k))
      .map(([k]) => k);
    expect(offenders).toEqual([]);
  });

  it("no hedged plurals like action(s) or Aktion(en)", () => {
    const hedge = /\w\((s|en|n|'s)\)/;
    for (const locale of [EN, NL, DE]) {
      expect(Object.entries(locale).filter(([, v]) => hedge.test(v)).map(([k]) => k)).toEqual([]);
    }
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
    // Placeholder names, plain "{n}" and plural "{n|…|…}" alike.
    const ph = (s) => [...new Set([...s.matchAll(/\{(\w+)(?:\}|\|)/g)].map((m) => m[1]))].sort().join(",");
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

describe("thinking lines from backend events", () => {
  const lines = (element) =>
    [...element.shadowRoot.getElementById("kyber-thinking-events").querySelectorAll(".thinking-event")]
      .map((el) => el.textContent);

  it("translates info, warning and tool results by key", () => {
    const { element } = makePanel({ language: "de" });
    element._showThinking();
    element._renderProgressEvent({ type: "info", message: "Asking AI (round 2)…", key: "ev_asking_ai", params: { round: 2 } });
    element._renderProgressEvent({
      type: "info", message: "Built context: 1200 entities, 18 areas",
      key: "ev_built_context", params: { entities: 1200, areas: 18 },
    });
    element._renderProgressEvent({ type: "tool_call", name: "get_area_entities", args: { area: "schlafzimmer" } });
    element._renderProgressEvent({
      type: "tool_result", name: "get_area_entities", summary: "1 entities in Schlafzimmer",
      summary_key: "ts_area_entities", summary_params: { count: 1, area: "Schlafzimmer" },
    });
    expect(lines(element)).toEqual([
      "ℹ️ KI wird gefragt (Runde 2) …",
      "ℹ️ Kontext aufgebaut: 1200 Entitäten, 18 Bereiche",
      '🔧 get_area_entities (area="schlafzimmer") → 1 Entität in Schlafzimmer',
    ]);
  });

  it("falls back to the English message for an unknown key or none", () => {
    const { element } = makePanel({ language: "de" });
    element._showThinking();
    element._renderProgressEvent({ type: "warning", message: "Something new", key: "ev_not_there_yet" });
    element._renderProgressEvent({ type: "info", message: "Old backend text" });
    expect(lines(element)).toEqual(["⚠️ Something new", "ℹ️ Old backend text"]);
  });
});
