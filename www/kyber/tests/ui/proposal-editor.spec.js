import { test, expect } from "@playwright/test";
import { gotoRealEditorHarness } from "./helpers.js";

// "Open in editor" on a proposal card, end to end with the real CodeMirror:
// the proposal lands in the editor unsaved, Save writes it to HA.

const ORIGINAL = {
  alias: "Heating",
  trigger: [{ platform: "state", entity_id: "input_select.mode" }],
  condition: [],
  action: [{ service: "climate.set_temperature", data: { temperature: 18 } }],
};
const MODIFIED = {
  ...ORIGINAL,
  action: [{ service: "climate.set_temperature", data: { temperature: 21 } }],
};

test("open in editor shows the proposal unsaved and Save writes it", async ({ page }) => {
  await gotoRealEditorHarness(page);
  let saved = null;
  await page.route("**/api/config/automation/config/**", (route) => {
    if (route.request().method() === "POST") {
      saved = route.request().postDataJSON();
      return route.fulfill({ status: 200, contentType: "application/json", body: '{"result":"ok"}' });
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(ORIGINAL) });
  });
  await page.route("**/api/kyber/parse_yaml", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ config: MODIFIED }) })
  );

  await page.evaluate((plan) => {
    const card = window.__panel._buildEditAutomationCard(plan);
    window.__panel.shadowRoot.getElementById("chat-history").appendChild(card);
  }, {
    edit_automation: true,
    entity_id: "automation.heating",
    automation_id: "heating",
    summary: "Raise comfort temperature",
    original_config: ORIGINAL,
    modified_config: MODIFIED,
  });

  await page.locator(".automation-edit-card .ae-btn-editor").click();

  const editorText = page.locator("#editor-container .cm-content");
  await expect(editorText).toContainText("temperature: 21");
  await expect(editorText).toContainText("condition: []");
  await expect(page.locator("#btn-save")).toBeEnabled();
  await expect(page.locator(".automation-edit-card .ae-btn-apply")).toBeDisabled();
  await page.screenshot({ path: "screenshots/proposal-open-in-editor.png" });

  await page.locator("#btn-save").click();
  await expect.poll(() => saved).not.toBeNull();
  expect(saved.id).toBe("heating");
  expect(saved.action[0].data.temperature).toBe(21);
});
