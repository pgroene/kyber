/**
 * Editing inside the automation proposal card: reorder by drag and drop,
 * delete, expand a row, the YAML preview, and "Open in editor".
 *
 * Before the fix a drop only reordered the data: the rows stayed where they
 * were and kept their old index, so the next delete removed the wrong item.
 */

import { makePanel } from "../helpers.js";

const plan = () => ({
  type: "edit_automation",
  entity_id: "automation.heating",
  automation_id: "heating",
  summary: "Heating by schedule",
  original_config: { alias: "Heating", trigger: [], condition: [], action: [] },
  modified_config: {
    alias: "Heating",
    trigger: [{ platform: "state", entity_id: "schedule.heating", attribute: "modus" }],
    condition: [],
    action: [
      { service: "light.turn_on", target: { entity_id: "light.a" } },
      { service: "light.turn_on", target: { entity_id: "light.b" } },
      { service: "light.turn_on", target: { entity_id: "light.c" } },
    ],
  },
});

const dragEvent = (type) => {
  const e = new Event(type, { bubbles: true, cancelable: true });
  Object.defineProperty(e, "dataTransfer", {
    value: { setData: vi.fn(), setDragImage: vi.fn(), effectAllowed: "", dropEffect: "" },
  });
  return e;
};

const actionRows = (card) => [...card.querySelectorAll('.ae-rows[data-section="action"] .ae-row')];
const actionTexts = (card) => actionRows(card).map((r) => r.querySelector(".ae-row-desc").textContent);

function openCard(p = plan()) {
  const { element } = makePanel({ language: "de" });
  const card = element._buildEditAutomationCard(p);
  document.body.appendChild(card);
  card.querySelector(".ae-btn-expand").click();
  return { element, card };
}

function drag(card, from, to) {
  const handle = actionRows(card)[from].querySelector(".ae-drag-handle");
  handle.dispatchEvent(dragEvent("dragstart"));
  actionRows(card)[to].dispatchEvent(dragEvent("drop"));
  handle.dispatchEvent(dragEvent("dragend"));
}

describe("automation card — reorder and delete", () => {
  it("a drop moves the row on screen, not only in the YAML", () => {
    const { card } = openCard();
    drag(card, 0, 2);
    expect(actionTexts(card).map((s) => s.match(/\[(light\.\w)\]/)[1])).toEqual(["light.b", "light.c", "light.a"]);
    expect(card.querySelector(".ae-yaml-preview").textContent.indexOf("light.b"))
      .toBeLessThan(card.querySelector(".ae-yaml-preview").textContent.indexOf("light.a"));
  });

  it("delete after a drop removes the row that was clicked", () => {
    const { card } = openCard();
    drag(card, 0, 2);
    // Row 0 now shows light.b
    actionRows(card)[0].querySelector(".ae-row-delete").click();
    expect(actionTexts(card).map((s) => s.match(/\[(light\.\w)\]/)[1])).toEqual(["light.c", "light.a"]);
  });

  it("dragstart sets data so Firefox starts the drag", () => {
    const { card } = openCard();
    const e = dragEvent("dragstart");
    actionRows(card)[0].querySelector(".ae-drag-handle").dispatchEvent(e);
    expect(e.dataTransfer.setData).toHaveBeenCalled();
  });

  it("only the handle is draggable, so expanded YAML stays selectable", () => {
    const { card } = openCard();
    const row = actionRows(card)[0];
    expect(row.getAttribute("draggable")).toBeNull();
    expect(row.querySelector(".ae-drag-handle").getAttribute("draggable")).toBe("true");
  });

  it("the delete button is an icon with a label, not a faint emoji", () => {
    const { card } = openCard();
    const btn = actionRows(card)[0].querySelector(".ae-row-delete");
    expect(btn.querySelector("svg path")).not.toBeNull();
    expect(btn.textContent).not.toContain("🗑");
    expect(btn.getAttribute("aria-label")).toBe("Löschen");
  });
});

describe("automation card — inspect", () => {
  it("clicking a row shows its YAML and collapses again", () => {
    const { card } = openCard();
    const row = actionRows(card)[1];
    const detail = row.querySelector(".ae-row-detail");
    expect(detail.hidden).toBe(true);
    row.querySelector(".ae-row-desc").click();
    expect(detail.hidden).toBe(false);
    expect(detail.textContent).toContain("entity_id: light.b");
    row.querySelector(".ae-row-toggle").click();
    expect(detail.hidden).toBe(true);
  });

  it("a state trigger on an attribute names the attribute", () => {
    const { card } = openCard();
    const trig = card.querySelector('.ae-rows[data-section="trigger"] .ae-row-desc').textContent;
    expect(trig).toContain("schedule.heating · modus");
  });

  it("the YAML preview keeps empty lists on the key line", () => {
    const { card } = openCard();
    const yaml = card.querySelector(".ae-yaml-preview").textContent;
    expect(yaml).toMatch(/^condition: \[\]$/m);
    expect(yaml).not.toMatch(/^\[\]$/m);
  });
});

describe("automation card — open in editor", () => {
  it("loads the proposal as an unsaved draft and locks Apply", async () => {
    const { element, card } = openCard();
    const open = vi.spyOn(element, "_openEditor").mockResolvedValue(undefined);
    const setContent = vi.spyOn(element, "_setEditorContent").mockImplementation(() => {});
    // An edit in the card before opening must reach the editor
    actionRows(card)[0].querySelector(".ae-row-delete").click();
    card.querySelector(".ae-btn-editor").click();
    await vi.waitFor(() => expect(setContent).toHaveBeenCalled());
    expect(open).toHaveBeenCalledWith("automation.heating", { entityId: "automation.heating" });
    const yaml = setContent.mock.calls[0][0];
    expect(yaml).toContain("light.b");
    expect(yaml).not.toContain("light.a");
    expect(card.querySelector(".ae-btn-apply").disabled).toBe(true);
    expect(card.querySelector(".ae-result").textContent).toContain("Im Editor");
  });

  it("a create card opens a new draft under one stable id with an alias", async () => {
    const { element } = makePanel({ language: "de" });
    const card = element._buildCreateAutomationCard({
      type: "create_automation", alias: "Neu", config: { trigger: [], action: [] },
    });
    const open = vi.spyOn(element, "_openEditor").mockResolvedValue(undefined);
    const setContent = vi.spyOn(element, "_setEditorContent").mockImplementation(() => {});
    card.querySelector(".ae-btn-editor").click();
    card.querySelector(".ae-btn-editor").click();
    await vi.waitFor(() => expect(setContent).toHaveBeenCalledTimes(2));
    const [first, second] = open.mock.calls;
    expect(first[1].newConfigId).toBeTruthy();
    expect(second[1].newConfigId).toBe(first[1].newConfigId);
    expect(first[0]).toBe(`automation.${first[1].newConfigId}`);
    expect(setContent.mock.calls[0][0]).toMatch(/^alias: Neu$/m);
    expect(card.querySelector(".ae-btn-apply").disabled).toBe(true);
  });

  it("the editor opens a new automation without loading it from HA", async () => {
    const { element, hass } = makePanel();
    element._editor = { state: { doc: { toString: () => "" } }, requestMeasure: vi.fn(), dispatch: vi.fn() };
    const load = vi.spyOn(element, "_loadAutomation");
    await element._openEditor("automation.123", { newConfigId: "123", name: "Neu" });
    expect(load).not.toHaveBeenCalled();
    expect(hass.callApi.mock.calls.filter(([, path]) => path.startsWith("config/"))).toEqual([]);
    expect(element._currentAutomationId).toBe("123");
    expect(element._savedYaml).toBeNull();
    expect(element.shadowRoot.getElementById("editor-context-label").textContent).toBe("automation > Neu");
  });
});
