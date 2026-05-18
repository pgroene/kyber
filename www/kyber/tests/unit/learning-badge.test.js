/**
 * Unit tests for the learning badge and explorer banner.
 *
 * Covers _checkExplorerBanner():
 *   - Badge and banner hidden when status is idle / done
 *   - Badge and banner shown when status is "exploring" (phase1/phase2/starting)
 *   - Badge and banner shown when status is "narrator"
 *   - Banner text shows correct progress numbers during exploring
 *   - Banner text shows correct progress + entity name during narrator
 *   - Timer keeps running after idle check (doesn't stop itself)
 *   - Timer is started on setHass regardless of mode
 */

import { makePanel } from "../helpers.js";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Build a mock fetch that returns the given explorer_progress object.
 */
function mockStatusFetch(explorerProgress = {}) {
  return vi.fn().mockResolvedValue({
    ok: true,
    json: () => Promise.resolve({ explorer_progress: explorerProgress }),
  });
}

/**
 * Create a panel and immediately run _checkExplorerBanner() with a mocked fetch.
 * Returns the panel element plus its shadow DOM elements.
 */
async function setupAndCheck(explorerProgress) {
  const { element } = makePanel();
  global.fetch = mockStatusFetch(explorerProgress);
  await element._checkExplorerBanner();
  const badge = element.shadowRoot.getElementById("learning-badge");
  const banner = element.shadowRoot.getElementById("explorer-banner");
  const bannerText = element.shadowRoot.getElementById("explorer-banner-text");
  return { element, badge, banner, bannerText };
}

// ---------------------------------------------------------------------------
// DOM presence
// ---------------------------------------------------------------------------
describe("learning badge DOM elements", () => {
  it("learning-badge element exists in shadow DOM", () => {
    const { element } = makePanel();
    expect(element.shadowRoot.getElementById("learning-badge")).not.toBeNull();
  });

  it("explorer-banner element exists in shadow DOM", () => {
    const { element } = makePanel();
    expect(element.shadowRoot.getElementById("explorer-banner")).not.toBeNull();
  });

  it("learning-badge starts hidden", () => {
    const { element } = makePanel();
    const badge = element.shadowRoot.getElementById("learning-badge");
    expect(badge.style.display).toBe("none");
  });

  it("explorer-banner starts hidden", () => {
    const { element } = makePanel();
    const banner = element.shadowRoot.getElementById("explorer-banner");
    expect(banner.style.display).toBe("none");
  });
});

// ---------------------------------------------------------------------------
// Idle / done — nothing shown
// ---------------------------------------------------------------------------
describe("_checkExplorerBanner — idle/done", () => {
  it("hides badge and banner when explorer_progress is empty", async () => {
    const { badge, banner } = await setupAndCheck({});
    expect(badge.style.display).toBe("none");
    expect(banner.style.display).toBe("none");
  });

  it("hides badge and banner when status is 'done'", async () => {
    const { badge, banner } = await setupAndCheck({ status: "done", done: 50, total: 50 });
    expect(badge.style.display).toBe("none");
    expect(banner.style.display).toBe("none");
  });

  it("hides badge and banner when status is unknown string", async () => {
    const { badge, banner } = await setupAndCheck({ status: "idle" });
    expect(badge.style.display).toBe("none");
    expect(banner.style.display).toBe("none");
  });
});

// ---------------------------------------------------------------------------
// Exploring phases — badge + banner shown
// ---------------------------------------------------------------------------
describe("_checkExplorerBanner — exploring", () => {
  for (const status of ["starting", "phase1_summaries", "phase2_entities"]) {
    it(`shows badge and banner when status='${status}'`, async () => {
      const { badge, banner } = await setupAndCheck({ status, done: 3, total: 10 });
      expect(badge.style.display).toBe("flex");
      expect(banner.style.display).toBe("");
    });
  }

  it("banner text includes progress numbers during exploring", async () => {
    const { bannerText } = await setupAndCheck({
      status: "phase2_entities",
      done: 7,
      total: 20,
    });
    expect(bannerText.textContent).toContain("7");
    expect(bannerText.textContent).toContain("20");
  });

  it("banner text includes 'Exploring' during exploring phase", async () => {
    const { bannerText } = await setupAndCheck({ status: "phase2_entities", done: 0, total: 5 });
    expect(bannerText.textContent).toMatch(/exploring/i);
  });
});

// ---------------------------------------------------------------------------
// Narrator phase — badge + banner shown
// ---------------------------------------------------------------------------
describe("_checkExplorerBanner — narrator", () => {
  it("shows badge and banner when status='narrator'", async () => {
    const { badge, banner } = await setupAndCheck({
      status: "narrator",
      narrator_done: 10,
      narrator_total: 100,
    });
    expect(badge.style.display).toBe("flex");
    expect(banner.style.display).toBe("");
  });

  it("banner text includes narrator progress numbers", async () => {
    const { bannerText } = await setupAndCheck({
      status: "narrator",
      narrator_done: 30,
      narrator_total: 200,
    });
    expect(bannerText.textContent).toContain("30");
    expect(bannerText.textContent).toContain("200");
  });

  it("banner text includes 'Learning' during narrator phase", async () => {
    const { bannerText } = await setupAndCheck({
      status: "narrator",
      narrator_done: 0,
      narrator_total: 50,
    });
    expect(bannerText.textContent).toMatch(/learning/i);
  });

  it("banner text includes entity name when narrator_current is set", async () => {
    const { bannerText } = await setupAndCheck({
      status: "narrator",
      narrator_done: 5,
      narrator_total: 50,
      narrator_current: "Slaapkamer Lamp",
    });
    expect(bannerText.textContent).toContain("Slaapkamer Lamp");
  });

  it("banner text works without narrator_current", async () => {
    const { bannerText } = await setupAndCheck({
      status: "narrator",
      narrator_done: 5,
      narrator_total: 50,
    });
    expect(bannerText.textContent).toMatch(/learning/i);
    expect(bannerText.textContent).not.toContain("undefined");
  });
});

// ---------------------------------------------------------------------------
// Transition: running → done hides elements
// ---------------------------------------------------------------------------
describe("_checkExplorerBanner — transitions", () => {
  it("hides badge after transitioning from narrator to done", async () => {
    const { element } = makePanel();

    global.fetch = mockStatusFetch({ status: "narrator", narrator_done: 5, narrator_total: 50 });
    await element._checkExplorerBanner();
    const badge = element.shadowRoot.getElementById("learning-badge");
    expect(badge.style.display).toBe("flex");

    global.fetch = mockStatusFetch({ status: "done" });
    await element._checkExplorerBanner();
    expect(badge.style.display).toBe("none");
  });

  it("shows badge after transitioning from done to narrator", async () => {
    const { element } = makePanel();

    global.fetch = mockStatusFetch({ status: "done" });
    await element._checkExplorerBanner();
    const badge = element.shadowRoot.getElementById("learning-badge");
    expect(badge.style.display).toBe("none");

    global.fetch = mockStatusFetch({ status: "narrator", narrator_done: 1, narrator_total: 10 });
    await element._checkExplorerBanner();
    expect(badge.style.display).toBe("flex");
  });
});

// ---------------------------------------------------------------------------
// Timer behaviour — must NOT stop when idle
// ---------------------------------------------------------------------------
describe("_startExplorerBannerPolling timer", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    global.fetch = mockStatusFetch({});
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("timer is set after _startExplorerBannerPolling", () => {
    const { element } = makePanel();
    expect(element._explorerBannerTimer).toBeTruthy();
  });

  it("timer remains set after idle check (does not clear itself)", async () => {
    const { element } = makePanel();
    global.fetch = mockStatusFetch({ status: "done" });
    await element._checkExplorerBanner();
    expect(element._explorerBannerTimer).toBeTruthy();
  });

  it("timer fires _checkExplorerBanner every 5 seconds", async () => {
    const { element } = makePanel();
    const spy = vi.spyOn(element, "_checkExplorerBanner").mockResolvedValue();
    element._startExplorerBannerPolling();
    // _startExplorerBannerPolling calls _checkExplorerBanner immediately (1)
    // then setInterval fires at 5s, 10s, 15s (3 more) = 4 total
    vi.advanceTimersByTime(15000);
    expect(spy).toHaveBeenCalledTimes(4);
  });
});

// ---------------------------------------------------------------------------
// Error resilience — fetch failure must not crash
// ---------------------------------------------------------------------------
describe("_checkExplorerBanner — fetch errors", () => {
  it("does not throw when fetch rejects", async () => {
    const { element } = makePanel();
    global.fetch = vi.fn().mockRejectedValue(new Error("network error"));
    await expect(element._checkExplorerBanner()).resolves.not.toThrow();
  });

  it("does not throw when fetch returns non-ok response", async () => {
    const { element } = makePanel();
    global.fetch = vi.fn().mockResolvedValue({ ok: false });
    await expect(element._checkExplorerBanner()).resolves.not.toThrow();
  });

  it("keeps badge hidden after fetch failure", async () => {
    const { element } = makePanel();
    global.fetch = vi.fn().mockRejectedValue(new Error("network error"));
    await element._checkExplorerBanner();
    const badge = element.shadowRoot.getElementById("learning-badge");
    expect(badge.style.display).toBe("none");
  });
});
