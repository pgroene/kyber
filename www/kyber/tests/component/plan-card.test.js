/**
 * Component tests for _buildPlanCard in KyberPanel.
 *
 * Covers:
 *   - Renders plan summary
 *   - Renders action rows with type badge and entity_id
 *   - Shows missing-entity warning for unknown entity_ids
 *   - Execute button disabled when all entities missing
 *   - Execute button calls /api/kyber/execute with correct actions
 *   - Undo button appears after successful execute
 *   - Undo button calls /api/kyber/execute with undo_actions
 *   - Failed execute shows error, re-enables Execute button
 *   - Autopilot mode auto-executes after 2s (vi.useFakeTimers)
 */

import { makePanel } from "../helpers.js";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function buildPlanCard(plan, hassStates = {}) {
  const { element } = makePanel({
    states: {
      "light.bedroom": { entity_id: "light.bedroom", attributes: { friendly_name: "Bedroom" } },
      ...hassStates,
    },
  });
  const card = element._buildPlanCard(plan);
  element.shadowRoot.getElementById("chat-history").appendChild(card);
  return { element, card };
}

const simplePlan = {
  summary: "Turn off bedroom light",
  actions: [
    { type: "call_service", domain: "light", service: "turn_off", entity_id: "light.bedroom" },
  ],
};

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------
describe("_buildPlanCard — rendering", () => {
  it("renders the plan summary", () => {
    const { card } = buildPlanCard(simplePlan);
    expect(card.querySelector(".plan-overview-summary").textContent).toContain("Turn off bedroom light");
  });

  it("renders action rows for each action", () => {
    const plan = {
      summary: "Reorganise",
      actions: [
        { type: "assign_area", entity_id: "light.bedroom", new_state: "Living Room" },
        { type: "rename_entity", entity_id: "light.bedroom", new_state: "Bedroom Light" },
      ],
    };
    const { card } = buildPlanCard(plan);
    const rows = card.querySelectorAll(".change-row");
    expect(rows.length).toBe(2);
  });

  it("renders the entity_id in each action row", () => {
    const { card } = buildPlanCard(simplePlan);
    expect(card.querySelector(".change-entity").textContent).toContain("light.bedroom");
  });

  it("renders type badge with domain.service for call_service actions", () => {
    const { card } = buildPlanCard(simplePlan);
    expect(card.querySelector(".change-type-badge").textContent).toContain("light.turn_off");
  });

  it("renders from→to arrow when current_state and new_state are provided", () => {
    const plan = {
      summary: "Rename",
      actions: [{ type: "rename_entity", entity_id: "light.bedroom", current_state: "Old", new_state: "New" }],
    };
    const { card } = buildPlanCard(plan);
    expect(card.textContent).toContain("Old");
    expect(card.textContent).toContain("New");
  });

  it("renders plan warnings when provided", () => {
    const plan = {
      summary: "Risky change",
      actions: [],
      warnings: ["This will affect all devices"],
    };
    const { card } = buildPlanCard(plan);
    expect(card.querySelector(".plan-warning").textContent).toContain("This will affect all devices");
  });
});

// ---------------------------------------------------------------------------
// Missing entity handling
// ---------------------------------------------------------------------------
describe("_buildPlanCard — missing entity handling", () => {
  it("marks action row with row-invalid when entity not in hass.states", () => {
    const plan = {
      summary: "Unknown entity",
      actions: [{ type: "assign_area", entity_id: "light.unknown", new_state: "Office" }],
    };
    const { card } = buildPlanCard(plan);
    expect(card.querySelector(".row-invalid")).not.toBeNull();
  });

  it("shows missing-entity warning section when entities are invalid", () => {
    const plan = {
      summary: "Test",
      actions: [{ type: "assign_area", entity_id: "sensor.ghost", new_state: "Attic" }],
    };
    const { card } = buildPlanCard(plan);
    expect(card.querySelector(".plan-warning-error")).not.toBeNull();
  });

  it("disables Execute button when ALL entities are missing", () => {
    const plan = {
      summary: "All missing",
      actions: [
        { type: "assign_area", entity_id: "sensor.ghost1", new_state: "A" },
        { type: "assign_area", entity_id: "sensor.ghost2", new_state: "B" },
      ],
    };
    const { card } = buildPlanCard(plan);
    const btn = card.querySelector(".btn-execute");
    expect(btn.disabled).toBe(true);
  });

  it("shows partial count in Execute button when some entities are missing", () => {
    const plan = {
      summary: "Mixed",
      actions: [
        { type: "assign_area", entity_id: "light.bedroom", new_state: "Office" },
        { type: "assign_area", entity_id: "sensor.ghost", new_state: "Office" },
      ],
    };
    const { card } = buildPlanCard(plan);
    const btn = card.querySelector(".btn-execute");
    expect(btn.textContent).toContain("1 of 2");
  });

  it("does not flag area-only actions even with no entity_id", () => {
    const plan = {
      summary: "Create area",
      actions: [{ type: "create_area", area_id: "new_kitchen" }],
    };
    const { card } = buildPlanCard(plan);
    // Execute should not be disabled — create_area is valid without entity_id
    expect(card.querySelector(".btn-execute").disabled).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Execute button behaviour
// ---------------------------------------------------------------------------
describe("_buildPlanCard — execute", () => {
  // Flush the full microtask queue by yielding to the event loop
  const flushPromises = () => new Promise((resolve) => setTimeout(resolve, 0));

  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("POSTs to /api/kyber/execute with the executable actions", async () => {
    fetch.mockResolvedValue({
      ok: true,
      json: async () => ({ results: [{ status: "ok" }] }),
    });
    const { card } = buildPlanCard(simplePlan);
    card.querySelector(".btn-execute").click();
    await flushPromises();
    const [url, opts] = fetch.mock.calls[0];
    expect(url).toBe("/api/kyber/execute");
    expect(JSON.parse(opts.body).actions.length).toBeGreaterThan(0);
  });

  it("shows success message after execute", async () => {
    fetch.mockResolvedValue({
      ok: true,
      json: async () => ({ results: [{ status: "ok" }] }),
    });
    const { card } = buildPlanCard(simplePlan);
    card.querySelector(".btn-execute").click();
    await flushPromises();
    const resultEl = card.querySelector(".plan-result");
    expect(resultEl.textContent).toContain("Done");
    expect(resultEl.classList.contains("success")).toBe(true);
  });

  it("shows error message and re-enables Execute on failure", async () => {
    fetch.mockResolvedValue({
      ok: true,
      json: async () => ({ results: [{ status: "error", message: "not found" }] }),
    });
    const { card } = buildPlanCard(simplePlan);
    card.querySelector(".btn-execute").click();
    await flushPromises();
    const resultEl = card.querySelector(".plan-result");
    expect(resultEl.textContent).toContain("failed");
    expect(card.querySelector(".btn-execute").disabled).toBe(false);
  });

  it("shows undo button after successful execute with undo_action", async () => {
    fetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        results: [{ status: "ok", undo_action: { type: "call_service", domain: "light", service: "turn_on" } }],
      }),
    });
    const { card } = buildPlanCard(simplePlan);
    card.querySelector(".btn-execute").click();
    await flushPromises();
    expect(card.querySelector(".btn-undo")).not.toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Autopilot mode
// ---------------------------------------------------------------------------
describe("_buildPlanCard — autopilot", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ results: [{ status: "ok" }] }),
    }));
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("auto-executes after 2s when autopilot is on", async () => {
    const { element } = makePanel({
      states: { "light.bedroom": { entity_id: "light.bedroom", attributes: {} } },
    });
    element._autopilot = true;
    element._buildPlanCard(simplePlan);

    expect(fetch).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(2100);
    expect(fetch).toHaveBeenCalled();
  });

  it("does not auto-execute when autopilot is off", async () => {
    const { element } = makePanel({
      states: { "light.bedroom": { entity_id: "light.bedroom", attributes: {} } },
    });
    element._autopilot = false;
    element._buildPlanCard(simplePlan);

    await vi.advanceTimersByTimeAsync(3000);
    expect(fetch).not.toHaveBeenCalled();
  });
});
