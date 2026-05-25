import { test, expect } from "@playwright/test";
import { gotoRealEditorHarness } from "./helpers.js";

const YAML_UNDER_TEST = `id: "1724834508486"
alias: Auto limit Goodwe by Negative energy prices
description:
triggers:
  - trigger: state
    entity_id:
      - sensor.house_energy_management_mode
conditions: []
actions:
  - choose:
      - conditions:
          - condition: template
            value_template: "{{ states('sensor.house_energy_management_mode') == \\"GRID_ONLY\\" }}"
        sequence:
          - action: switch.turn_on
            target:
              entity_id: switch.goodwe_grid_export_limit_switch
      - conditions:
          - condition: template
            value_template: "{{ states('sensor.house_energy_management_mode') == \\"SOLAR_OK\\" }}"
        sequence:
          - action: number.set_value
            target:
              entity_id: number.goodwe_grid_export_limit
            data:
              value: "200"
      - conditions:
          - condition: template
            value_template: "{{ states('sensor.house_energy_management_mode') == \\"BALANCE\\" }}"
        sequence:
          - action: switch.turn_on
            target:
              entity_id: switch.goodwe_grid_export_limit_switch
          - repeat:
              while:
                - condition: template
                  value_template: "{{ states('sensor.house_energy_management_mode') == \\"BALANCE\\" }}"
              sequence:
                - action: number.set_value
                  target:
                    entity_id: number.goodwe_grid_export_limit
                  data:
                    value: "50"
                - delay:
                    seconds: 5
mode: restart
`;

const CONFIG_UNDER_TEST = {
  id: "1724834508486",
  alias: "Auto limit Goodwe by Negative energy prices",
  description: null,
  triggers: [
    {
      trigger: "state",
      entity_id: ["sensor.house_energy_management_mode"],
    },
  ],
  conditions: [],
  actions: [
    {
      choose: [
        {
          conditions: [{ condition: "template", value_template: "{{ states('sensor.house_energy_management_mode') == \"GRID_ONLY\" }}" }],
          sequence: [
            {
              action: "switch.turn_on",
              target: { entity_id: "switch.goodwe_grid_export_limit_switch" },
            },
          ],
        },
        {
          conditions: [{ condition: "template", value_template: "{{ states('sensor.house_energy_management_mode') == \"SOLAR_OK\" }}" }],
          sequence: [
            {
              action: "number.set_value",
              target: { entity_id: "number.goodwe_grid_export_limit" },
              data: { value: "200" },
            },
          ],
        },
        {
          conditions: [{ condition: "template", value_template: "{{ states('sensor.house_energy_management_mode') == \"BALANCE\" }}" }],
          sequence: [
            {
              action: "switch.turn_on",
              target: { entity_id: "switch.goodwe_grid_export_limit_switch" },
            },
            {
              repeat: {
                while: [{ condition: "template", value_template: "{{ states('sensor.house_energy_management_mode') == \"BALANCE\" }}" }],
                sequence: [
                  {
                    action: "number.set_value",
                    target: { entity_id: "number.goodwe_grid_export_limit" },
                    data: { value: "50" },
                  },
                  { delay: { seconds: 5 } },
                ],
              },
            },
          ],
        },
      ],
    },
  ],
  mode: "restart",
};

async function openEditorWithYaml(page) {
  await page.evaluate(({ yaml, config }) => {
    const panel = window.__panel;
    const editorPane = panel.shadowRoot.getElementById("editor-container");
    const container = panel.shadowRoot.getElementById("app-container");
    container.classList.add("editor-open");
    editorPane.classList.add("open");
    if (!panel._editor) panel._initEditor(editorPane);
    panel._editorMode = "automation";
    panel._currentAutomationConfig = config;
    panel._setEditorContent(yaml);
    panel._renderAutomationDiagram(yaml);
  }, { yaml: YAML_UNDER_TEST, config: CONFIG_UNDER_TEST });
}

async function showTemplateInspector(page) {
  await page.evaluate(() => {
    const panel = window.__panel;
    const yaml = panel._editor.state.doc.toString();
    const lines = yaml.split("\n");
    const lineIndex = lines.findIndex((l) => l.includes("SOLAR_OK"));
    const pos = panel._editor.state.doc.line(lineIndex + 1).from;
    panel._editor.dispatch({ selection: { anchor: pos }, scrollIntoView: true });
    panel._updateTemplateInspector(lineIndex, yaml, pos);
  });
}

async function showEntityListPicker(page) {
  await page.evaluate(() => {
    const panel = window.__panel;
    const yaml = panel._editor.state.doc.toString();
    const lines = yaml.split("\n");
    const lineIndex = lines.findIndex((l) => l.includes("sensor.house_energy_management_mode"));
    const pos = panel._editor.state.doc.line(lineIndex + 1).from;
    panel._editor.dispatch({ selection: { anchor: pos }, scrollIntoView: true });
    panel._updateEntityListPicker(lineIndex, yaml, pos);
  });
}

test.describe("Editor regressions (real CodeMirror)", () => {
  test.beforeEach(async ({ page }) => {
    await gotoRealEditorHarness(page);
    await page.route("**/api/kyber/parse_yaml", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ config: CONFIG_UNDER_TEST }),
      })
    );
    await page.route("**/api/template", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify("BALANCE"),
      })
    );
    await openEditorWithYaml(page);
  });

  test("template inspector is high-contrast and wrapped", async ({ page }) => {
    await showTemplateInspector(page);

    const expr = page.locator("#template-inspector .ti-expr");
    await expect(expr).toBeVisible();

    const styles = await expr.evaluate((el) => {
      const s = getComputedStyle(el);
      return { bg: s.backgroundColor, fg: s.color, fs: s.fontSize, ws: s.whiteSpace };
    });
    expect(styles.bg).not.toMatch(/255,\s*255,\s*255/);
    expect(styles.fs).not.toBe("11px");
    expect(styles.ws).toMatch(/pre-wrap|normal/);

    await page.screenshot({ path: "screenshots/ui-template-inspector-regression.png" });
  });

  test("add-entity panel uses same visual style and close stays closed on same block", async ({ page }) => {
    await showTemplateInspector(page);
    await showEntityListPicker(page);

    const picker = page.locator("#entity-list-picker");
    const tpl = page.locator("#template-inspector");
    await expect(picker).toBeVisible();
    await expect(tpl).toBeVisible();

    const styleParity = await page.evaluate(() => {
      const root = window.__panel.shadowRoot;
      const tplInsp = root.getElementById("template-inspector");
      const pickerEl = root.getElementById("entity-list-picker");
      const tplHeader = tplInsp?.querySelector(".ti-header");
      const pickerHeader = pickerEl?.querySelector(".elp-header");
      const t = getComputedStyle(tplInsp);
      const p = getComputedStyle(pickerEl);
      const th = getComputedStyle(tplHeader);
      const ph = getComputedStyle(pickerHeader);
      return {
        panelBgMatch: t.backgroundColor === p.backgroundColor,
        panelBorderMatch: t.borderColor === p.borderColor,
        headerBgMatch: th.backgroundColor === ph.backgroundColor,
      };
    });
    expect(styleParity.panelBgMatch).toBe(true);
    expect(styleParity.panelBorderMatch).toBe(true);
    expect(styleParity.headerBgMatch).toBe(true);

    await page.locator("#entity-list-picker .elp-close").click();
    await expect.poll(async () => page.evaluate(() =>
      !!window.__panel.shadowRoot.getElementById("entity-list-picker")?.hidden
    )).toBe(true);

    await showEntityListPicker(page);
    await expect.poll(async () => page.evaluate(() =>
      !!window.__panel.shadowRoot.getElementById("entity-list-picker")?.hidden
    )).toBe(true);

    await page.evaluate(() => {
      const panel = window.__panel;
      const yaml = panel._editor.state.doc.toString();
      const lines = yaml.split("\n");
      const aliasLine = lines.findIndex((l) => l.startsWith("alias:"));
      const listLine = lines.findIndex((l) => l.includes("sensor.house_energy_management_mode"));
      const aliasPos = panel._editor.state.doc.line(aliasLine + 1).from;
      const listPos = panel._editor.state.doc.line(listLine + 1).from;
      panel._editor.dispatch({ selection: { anchor: aliasPos }, scrollIntoView: true });
      panel._updateEntityListPicker(aliasLine, yaml, aliasPos);
      panel._editor.dispatch({ selection: { anchor: listPos }, scrollIntoView: true });
      panel._updateEntityListPicker(listLine, yaml, listPos);
    });
    await expect.poll(async () => page.evaluate(() =>
      !!window.__panel.shadowRoot.getElementById("entity-list-picker") &&
      !window.__panel.shadowRoot.getElementById("entity-list-picker").hidden
    )).toBe(true);

    await page.screenshot({ path: "screenshots/ui-picker-style-close-regression.png" });
  });

  test("template and add-entity panels can be moved", async ({ page }) => {
    await showTemplateInspector(page);
    await showEntityListPicker(page);

    const dragBy = async (panelSelector, headerSelector, dx, dy) => {
      return page.evaluate(({ panelSelector, headerSelector, dx, dy }) => {
        const root = window.__panel.shadowRoot;
        const panel = root.querySelector(panelSelector);
        const header = panel?.querySelector(headerSelector);
        if (!panel || !header) return { movedX: 0, movedY: 0 };
        const before = panel.getBoundingClientRect();
        const startX = before.left + 20;
        const startY = before.top + 14;
        const eventInit = (x, y, buttons = 1) => ({
          bubbles: true,
          composed: true,
          pointerId: 1,
          pointerType: "mouse",
          isPrimary: true,
          button: 0,
          buttons,
          clientX: x,
          clientY: y,
        });
        header.dispatchEvent(new PointerEvent("pointerdown", eventInit(startX, startY)));
        panel.dispatchEvent(new PointerEvent("pointermove", eventInit(startX + dx, startY + dy)));
        panel.dispatchEvent(new PointerEvent("pointerup", eventInit(startX + dx, startY + dy, 0)));
        const after = panel.getBoundingClientRect();
        return { movedX: Math.abs(after.left - before.left), movedY: Math.abs(after.top - before.top) };
      }, { panelSelector, headerSelector, dx, dy });
    };

    const tplMove = await dragBy("#template-inspector", ".ti-header", -80, 40);
    const pickerMove = await dragBy("#entity-list-picker", ".elp-header", -120, 70);
    expect(tplMove.movedX + tplMove.movedY).toBeGreaterThan(20);
    expect(pickerMove.movedX + pickerMove.movedY).toBeGreaterThan(20);

    await page.screenshot({ path: "screenshots/ui-panels-draggable-regression.png" });
  });

  test("YAML error marker overlay and badge are visible", async ({ page }) => {
    await page.evaluate(() => {
      const panel = window.__panel;
      panel._showYamlError("Invalid YAML: while parsing a block collection in \"<unicode string>\", line 27, column 11:", panel._editor.state.doc.toString());
    });

    const overlay = page.locator("#yaml-error-line-overlay");
    const badge = page.locator("#yaml-error-line-badge");
    await expect(overlay).toBeVisible();
    await expect(badge).toBeVisible();
    await expect(badge).toContainText("line 27");

    const dims = await overlay.evaluate((el) => ({
      hidden: el.hidden,
      width: Number.parseFloat(el.style.width || "0"),
      height: Number.parseFloat(el.style.height || "0"),
      top: Number.parseFloat(el.style.top || "0"),
    }));
    expect(dims.hidden).toBe(false);
    expect(dims.width).toBeGreaterThan(20);
    expect(dims.height).toBeGreaterThan(10);

    const before = await page.evaluate(() => {
      const panel = window.__panel;
      const line = panel._editor.state.doc.line(panel._errorLineNum);
      const coords = panel._editor.coordsAtPos(line.from);
      const overlay = panel.shadowRoot.getElementById("yaml-error-line-overlay");
      const overlayRect = overlay?.getBoundingClientRect();
      return {
        diff: Math.abs((overlayRect?.top ?? 0) - (coords?.top ?? 0)),
      };
    });
    expect(before.diff).toBeLessThan(12);

    await page.evaluate(() => {
      const panel = window.__panel;
      const scroller = panel._editor.dom.querySelector(".cm-scroller");
      if (scroller) scroller.scrollTop += 220;
      panel._applyErrorDecorations();
    });
    await page.waitForTimeout(60);

    const after = await page.evaluate(() => {
      const panel = window.__panel;
      const line = panel._editor.state.doc.line(panel._errorLineNum);
      const coords = panel._editor.coordsAtPos(line.from);
      const overlay = panel.shadowRoot.getElementById("yaml-error-line-overlay");
      const overlayRect = overlay?.getBoundingClientRect();
      return {
        hidden: !!overlay?.hidden,
        diff: Math.abs((overlayRect?.top ?? 0) - (coords?.top ?? 0)),
      };
    });
    expect(after.hidden).toBe(false);
    expect(after.diff).toBeLessThan(12);

    await page.screenshot({ path: "screenshots/ui-yaml-error-marker-regression.png" });
  });

  test("choose/repeat drilldown stays expanded after clicking nested set_value", async ({ page }) => {
    const chooseNode = page.locator(".adg-node.adg-expandable", { hasText: "choose" }).first();
    await expect(chooseNode).toBeVisible();
    await chooseNode.click();

    const option3 = page.locator(".adg-option", { hasText: /option 3/i }).first();
    await expect(option3).toBeVisible();
    await option3.click();

    const repeatNode = page.locator(".adg-node.adg-expandable", { hasText: "repeat" }).first();
    await expect(repeatNode).toBeVisible();
    await repeatNode.click();

    const beforeCount = await page.locator(".adg-section.adg-dd").count();
    const setValueLeaf = page.locator(".adg-node", { hasText: /set[_\s]?value|number\.set_value/i }).first();
    await expect(setValueLeaf).toBeVisible();
    await setValueLeaf.click();
    // Wait past debounce windows (350ms render, 1200ms reparse) to catch delayed collapse regressions.
    await page.waitForTimeout(1500);
    const afterCount = await page.locator(".adg-section.adg-dd").count();

    expect(afterCount).toBeGreaterThanOrEqual(beforeCount);
    await page.screenshot({ path: "screenshots/ui-choose-repeat-drilldown-regression.png" });
  });
});
