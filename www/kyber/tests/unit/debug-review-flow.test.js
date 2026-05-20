import { makePanel, makeUnrenderedPanel } from "../helpers.js";

describe("debug review flow", () => {
  const flushPromises = () => new Promise((resolve) => setTimeout(resolve, 0));

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders proposal review cards with action and memory preview", () => {
    const element = makeUnrenderedPanel();
    const html = element._renderReviewCardHTML([
      {
        id: "p1",
        category: "proposal",
        proposal_type: "area_assignment",
        subject: "switch.koffiezetapparaat",
        entity_name: "koffiezetapparaat",
        area_name: "keuken",
        confidence: 0.9,
      },
    ], []);
    const wrapper = document.createElement("div");
    wrapper.innerHTML = html;

    expect(wrapper.querySelector(".review-flow-proposal-icon").textContent).toContain("📍");
    expect(wrapper.querySelector(".review-flow-proposal-action").innerHTML).toContain("Wijs <strong>koffiezetapparaat</strong> toe aan gebied <strong>keuken</strong>");
    expect(wrapper.querySelector(".review-flow-proposal-memory").textContent).toContain("De koffiezetapparaat (switch.koffiezetapparaat) staat in de keuken.");
  });

  it("approves proposal entries through the proposal endpoint", async () => {
    const { element } = makePanel();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ memory: "De koffiezetapparaat (switch.koffiezetapparaat) staat in de keuken." }),
    }));
    element._setStatus = vi.fn();
    element._renderDebugTab = vi.fn();

    const queue = [{
      id: "p1",
      category: "proposal",
      proposal_type: "area_assignment",
      subject: "switch.koffiezetapparaat",
      entity_name: "koffiezetapparaat",
      area_name: "keuken",
      confidence: 0.9,
    }];
    const body = document.createElement("div");
    body.innerHTML = element._renderReviewCardHTML(queue, []);
    document.body.appendChild(body);

    element._wireReviewCard(body, queue, [], []);
    body.querySelector("#review-approve").click();
    await flushPromises();

    const [url, opts] = fetch.mock.calls[0];
    expect(url).toBe("/api/kyber/proposals/approve");
    expect(JSON.parse(opts.body)).toEqual({ entry_id: "p1" });
    expect(element._setStatus).toHaveBeenCalledWith(
      "✓ De koffiezetapparaat (switch.koffiezetapparaat) staat in de keuken.",
      "ok",
    );
    expect(queue).toHaveLength(0);
    expect(element._renderDebugTab).toHaveBeenCalledWith("memory");
  });
});
