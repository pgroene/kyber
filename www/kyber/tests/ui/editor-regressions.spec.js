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
    await page.evaluate(() => {
      const panel = window.__panel;
      const yaml = panel._editor.state.doc.toString();
      const lines = yaml.split("\n");
      const lineIndex = lines.findIndex((l) => l.includes("SOLAR_OK"));
      const pos = panel._editor.state.doc.line(lineIndex + 1).from;
      panel._editor.dispatch({ selection: { anchor: pos }, scrollIntoView: true });
      panel._updateTemplateInspector(lineIndex, yaml, pos);
    });

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
    await page.waitForTimeout(120);
    const afterCount = await page.locator(".adg-section.adg-dd").count();

    expect(afterCount).toBeGreaterThanOrEqual(beforeCount);
    await page.screenshot({ path: "screenshots/ui-choose-repeat-drilldown-regression.png" });
  });
});
