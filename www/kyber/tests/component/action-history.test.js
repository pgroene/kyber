import { makePanel } from "../helpers.js";

const flushPromises = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("action history panel", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders stored history entries with summary and entity chips", () => {
    const { element } = makePanel();
    element._actionHistory = [{
      id: "entry-1",
      ts: Math.floor(Date.now() / 1000) - 300,
      summary: "Turn on espresso machine",
      status: "applied",
      entity_changes: [
        { entity_id: "switch.espresso", from_state: "off", to_state: "on" },
      ],
      undo_plan: [],
    }];

    element._renderActionHistory();

    const panel = element.shadowRoot.getElementById("action-history-list");
    expect(panel.textContent).toContain("Turn on espresso machine");
    expect(panel.textContent).toContain("switch.espresso");
    expect(panel.textContent).toContain("Applied");
  });

  it("calls the undo endpoint for reversible applied entries", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ status: "ok", entry: { summary: "Turn on espresso machine" } }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ entries: [] }),
      });
    vi.stubGlobal("fetch", fetchMock);

    const { element } = makePanel();
    element._actionHistory = [{
      id: "entry-1",
      ts: Math.floor(Date.now() / 1000) - 60,
      summary: "Turn on espresso machine",
      status: "applied",
      entity_changes: [],
      undo_plan: [{ type: "call_service", domain: "switch", service: "turn_off", entity_id: "switch.espresso" }],
    }];

    element._renderActionHistory();
    element.shadowRoot.querySelector(".action-history-undo").click();
    await flushPromises();
    await flushPromises();

    expect(fetchMock.mock.calls[0][0]).toBe("/api/kyber/history/actions/entry-1/undo");
    expect(fetchMock.mock.calls[0][1].method).toBe("POST");
  });
});
