/**
 * "Last turn" shows a turn the browser gave up on (chat timeout, Stop) with
 * a notice; the backend now keeps such a turn instead of nothing.
 */

import { makePanel } from "../helpers.js";

function lastTurn(snapshot) {
  return vi.fn((url) => Promise.resolve({
    ok: true,
    json: async () => (url === "/api/kyber/debug/last_turn" ? { snapshot } : {}),
  }));
}

const SNAP = {
  request_id: "r1", ts: 1793630749, user_prompt: "How many lamps are on?", elapsed_ms: 299800,
  tool_log: [{ type: "tool_call", name: "search_entities", args: { query: "lamp" } }],
  char_count: 1000, approx_tokens: 250, response_text: "",
};

describe("debug last turn — aborted turns", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("says the turn was aborted, after how long, and shows what it had", async () => {
    vi.stubGlobal("fetch", lastTurn({ ...SNAP, aborted: { after_ms: 299800, reason: "client_gone" } }));
    const { element } = makePanel({ language: "de" });
    const body = document.createElement("div");
    await element._renderDebugLastTurn(body);
    expect(body.querySelector(".dbg-aborted").textContent).toContain("Abgebrochen nach 300 s");
    expect(body.textContent).toContain("How many lamps are on?");
    expect(body.textContent).toContain("search_entities");
  });

  it("a finished turn has no notice", async () => {
    vi.stubGlobal("fetch", lastTurn(SNAP));
    const { element } = makePanel({ language: "de" });
    const body = document.createElement("div");
    await element._renderDebugLastTurn(body);
    expect(body.querySelector(".dbg-aborted")).toBeNull();
  });
});
