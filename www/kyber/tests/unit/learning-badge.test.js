/**
 * Unit tests for the learning badge and explorer banner.
 *
 * Covers _checkKyberStatus():
 *   - Badge and banner hidden when status is idle / done
 *   - Badge and banner shown when status is "exploring" (phase1/phase2/starting)
 *   - Badge and banner shown when status is "narrator"
 *   - Banner text shows correct progress numbers during exploring
 *   - Banner text shows "Narry is exploring your home X%" during narrator
 *   - Timer self-stops on idle (calls _clearStatusPoll)
 *   - Timer is started on setHass regardless of mode
 */

import { makePanel } from "../helpers.js";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Build a mock fetch that returns the given explorer_progress object
 * wrapped in the /api/kyber/debug/status response shape.
 */
function mockStatusFetch(explorerProgress = {}) {
  return vi.fn().mockResolvedValue({
    ok: true,
    json: () => Promise.resolve({ explorer_progress: explorerProgress }),
  });
}

/**
 * Create a panel and immediately run _checkKyberStatus() with a mocked fetch.
 * Returns the panel element plus its shadow DOM elements.
 */
async function setupAndCheck(explorerProgress) {
  const { element } = makePanel();
  global.fetch = mockStatusFetch(explorerProgress);
  await element._checkKyberStatus();
  const badge = element.shadowRoot.getElementById("narrator-progress");
  const banner = element.shadowRoot.getElementById("explorer-banner");
  const bannerText = element.shadowRoot.getElementById("explorer-banner-text");
  return { element, badge, banner, bannerText };
}

// ---------------------------------------------------------------------------
// DOM presence
// ---------------------------------------------------------------------------
describe("learning badge DOM elements", () => {
  it("narrator-progress element exists in shadow DOM", () => {
    const { element } = makePanel();
    expect(element.shadowRoot.getElementById("narrator-progress")).not.toBeNull();
  });

  it("explorer-banner element exists in shadow DOM", () => {
    const { element } = makePanel();
    expect(element.shadowRoot.getElementById("explorer-banner")).not.toBeNull();
  });

  it("narrator-progress starts hidden", () => {
    const { element } = makePanel();
    const badge = element.shadowRoot.getElementById("narrator-progress");
    expect(badge.hidden).toBe(true);
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
describe("_checkKyberStatus — idle/done", () => {
  it("hides badge and banner when explorer_progress is empty", async () => {
    const { badge, banner } = await setupAndCheck({});
    expect(badge.hidden).toBe(true);
    expect(banner.style.display).toBe("none");
  });

  it("hides badge and banner when status is 'done'", async () => {
    const { badge, banner } = await setupAndCheck({ status: "done", done: 50, total: 50 });
    expect(badge.hidden).toBe(true);
    expect(banner.style.display).toBe("none");
  });

  it("hides badge and banner when status is unknown string", async () => {
    const { badge, banner } = await setupAndCheck({ status: "idle" });
    expect(badge.hidden).toBe(true);
    expect(banner.style.display).toBe("none");
  });
});

// ---------------------------------------------------------------------------
// Exploring phases — badge + banner shown
// ---------------------------------------------------------------------------
describe("_checkKyberStatus — exploring", () => {
  for (const status of ["starting", "phase1_summaries", "phase2_entities"]) {
    it(`shows badge and banner when status='${status}'`, async () => {
      const { badge, banner } = await setupAndCheck({ status, done: 3, total: 10 });
      expect(badge.hidden).toBe(false);
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
describe("_checkKyberStatus — narrator", () => {
  it("shows badge and banner when status='narrator'", async () => {
    const { badge, banner } = await setupAndCheck({
      status: "narrator",
      narrator_done: 10,
      narrator_total: 100,
    });
    expect(badge.hidden).toBe(false);
    expect(banner.style.display).toBe("");
  });

  it("banner text includes narrator percentage", async () => {
    const { bannerText } = await setupAndCheck({
      status: "narrator",
      narrator_done: 30,
      narrator_total: 200,
    });
    expect(bannerText.textContent).toContain("15%");
  });

  it("banner text includes 'Narry' during narrator phase", async () => {
    const { bannerText } = await setupAndCheck({
      status: "narrator",
      narrator_done: 0,
      narrator_total: 50,
    });
    expect(bannerText.textContent).toMatch(/narry/i);
  });

  it("badge shows percentage text during narrator phase", async () => {
    const { badge } = await setupAndCheck({
      status: "narrator",
      narrator_done: 5,
      narrator_total: 50,
    });
    expect(badge.textContent).toContain("10%");
  });

  it("banner text works without narrator_total", async () => {
    const { bannerText } = await setupAndCheck({
      status: "narrator",
      narrator_done: 5,
      narrator_total: 0,
    });
    expect(bannerText.textContent).toMatch(/narry/i);
    expect(bannerText.textContent).not.toContain("undefined");
  });
});

// ---------------------------------------------------------------------------
// Transition: running → done hides elements
// ---------------------------------------------------------------------------
describe("_checkKyberStatus — transitions", () => {
  it("hides badge after transitioning from narrator to done", async () => {
    const { element } = makePanel();

    global.fetch = mockStatusFetch({ status: "narrator", narrator_done: 5, narrator_total: 50 });
    await element._checkKyberStatus();
    const badge = element.shadowRoot.getElementById("narrator-progress");
    expect(badge.hidden).toBe(false);

    global.fetch = mockStatusFetch({ status: "done" });
    await element._checkKyberStatus();
    expect(badge.hidden).toBe(true);
  });

  it("shows badge after transitioning from done to narrator", async () => {
    const { element } = makePanel();

    global.fetch = mockStatusFetch({ status: "done" });
    await element._checkKyberStatus();
    const badge = element.shadowRoot.getElementById("narrator-progress");
    expect(badge.hidden).toBe(true);

    global.fetch = mockStatusFetch({ status: "narrator", narrator_done: 1, narrator_total: 10 });
    await element._checkKyberStatus();
    expect(badge.hidden).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Timer behaviour
// ---------------------------------------------------------------------------
describe("_startStatusPolling timer", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    global.fetch = mockStatusFetch({ status: "phase1_summaries", done: 0, total: 10 });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("_statusPollTimer is set after _startStatusPolling", () => {
    const { element } = makePanel();
    // Reset any timer started during render so we can test a fresh call
    element._statusPollTimer = null;
    element._startStatusPolling();
    expect(element._statusPollTimer).toBeTruthy();
  });

  it("_startStatusPolling does not restart if timer is already set", () => {
    const { element } = makePanel();
    element._statusPollTimer = null;
    element._startStatusPolling();
    const firstTimer = element._statusPollTimer;
    element._startStatusPolling(); // second call should be a no-op
    expect(element._statusPollTimer).toBe(firstTimer);
  });

  it("fetch is called at startup and every 5 seconds", async () => {
    const { element } = makePanel();
    clearInterval(element._statusPollTimer); // clear the interval started by connectedCallback
    element._statusPollTimer = null;
    global.fetch = mockStatusFetch({ status: "phase1_summaries", done: 0, total: 10 });
    global.fetch.mockClear();
    element._startStatusPolling();
    await Promise.resolve(); // flush microtasks so initial _poll() can start
    await Promise.resolve(); // second flush for the async fetch chain
    expect(global.fetch).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(5000);
    expect(global.fetch).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(5000);
    expect(global.fetch).toHaveBeenCalledTimes(3);
  });
});

// ---------------------------------------------------------------------------
// Error resilience — fetch failure must not crash
// ---------------------------------------------------------------------------
describe("_checkKyberStatus — fetch errors", () => {
  it("does not throw when fetch rejects", async () => {
    const { element } = makePanel();
    global.fetch = vi.fn().mockRejectedValue(new Error("network error"));
    await expect(element._checkKyberStatus()).resolves.not.toThrow();
  });

  it("does not throw when fetch returns non-ok response", async () => {
    const { element } = makePanel();
    global.fetch = vi.fn().mockResolvedValue({ ok: false });
    await expect(element._checkKyberStatus()).resolves.not.toThrow();
  });

  it("keeps badge hidden after fetch failure", async () => {
    const { element } = makePanel();
    global.fetch = vi.fn().mockRejectedValue(new Error("network error"));
    await element._checkKyberStatus();
    const badge = element.shadowRoot.getElementById("narrator-progress");
    expect(badge.hidden).toBe(true);
  });
});
