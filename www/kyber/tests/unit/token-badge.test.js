import { makePanel } from "../helpers.js";

function mockStatusFetch(tokenUsage = {}) {
  return vi.fn().mockResolvedValue({
    ok: true,
    json: () => Promise.resolve({ explorer_progress: {}, token_usage: tokenUsage }),
  });
}

describe("token badge", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("renders the token badge next to the memory badge", () => {
    const { element } = makePanel();
    expect(element.shadowRoot.getElementById("token-badge")).not.toBeNull();
    expect(element.shadowRoot.getElementById("token-count").textContent).toBe("0");
  });

  it("adds warning styling at 80 percent", () => {
    const { element } = makePanel();
    element._updateTokenBadgeFromUsage({ used: 800, budget: 1000, pct: 80 });
    const badge = element.shadowRoot.getElementById("token-badge");
    expect(badge.classList.contains("token-badge--warning")).toBe(true);
    expect(badge.classList.contains("token-badge--danger")).toBe(false);
    expect(element.shadowRoot.getElementById("token-count").textContent).toContain("800");
  });

  it("adds danger styling at 100 percent", () => {
    const { element } = makePanel();
    element._updateTokenBadgeFromUsage({ used: 1000, budget: 1000, pct: 100 });
    const badge = element.shadowRoot.getElementById("token-badge");
    expect(badge.classList.contains("token-badge--danger")).toBe(true);
  });

  it("updates from /api/kyber/debug/status responses", async () => {
    vi.stubGlobal("fetch", mockStatusFetch({ used: 2500, budget: 10000, pct: 25 }));
    const { element } = makePanel();
    await element._checkKyberStatus();
    expect(element.shadowRoot.getElementById("token-count").textContent).toBe("2.5k/10k");
  });
});
