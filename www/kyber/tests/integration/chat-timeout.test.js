/**
 * Integration tests for the configurable chat timeout.
 *
 * Covers:
 *   - _loadChatSettings reads chat_timeout from /api/kyber/chat_settings
 *   - _loadChatSettings keeps the previous value when the request fails
 *   - _askAI aborts after the configured timeout (not after a fixed 90s)
 *   - _askAI falls back to DEFAULT_CHAT_TIMEOUT_SEC when nothing was loaded
 */

import { makePanel } from "../helpers.js";
import { DEFAULT_CHAT_TIMEOUT_SEC } from "kyber-www/src/ai-mixin.js";

/**
 * fetch mock: /complete hangs until aborted, chat_settings returns `settings`,
 * everything else answers with an empty JSON object.
 */
function hangingFetch(settings = { chat_timeout: 600 }) {
  return vi.fn((url, opts = {}) => {
    if (url === "/api/kyber/complete") {
      return new Promise((_resolve, reject) => {
        opts.signal?.addEventListener("abort", () => reject(opts.signal.reason));
      });
    }
    if (url === "/api/kyber/chat_settings") {
      return Promise.resolve({ ok: true, json: async () => settings });
    }
    return Promise.resolve({ ok: true, text: async () => "", json: async () => ({}) });
  });
}

function startAsk(element, prompt = "Hello") {
  element._lovelaceResources = [];
  element._dashboardList = [];
  element.shadowRoot.getElementById("prompt-input").value = prompt;
  return element._askAI();
}

describe("_loadChatSettings", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("stores chat_timeout from the backend", async () => {
    vi.stubGlobal("fetch", hangingFetch({ chat_timeout: 420 }));
    const { element } = makePanel();
    await element._loadChatSettings();
    expect(fetch).toHaveBeenCalledWith("/api/kyber/chat_settings", expect.any(Object));
    expect(element._chatTimeoutSec).toBe(420);
  });

  it("keeps the previous value when the request fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 500 }));
    const { element } = makePanel();
    element._chatTimeoutSec = 300;
    await element._loadChatSettings();
    expect(element._chatTimeoutSec).toBe(300);
  });

  it("ignores invalid values", async () => {
    vi.stubGlobal("fetch", hangingFetch({ chat_timeout: "abc" }));
    const { element } = makePanel();
    element._chatTimeoutSec = 300;
    await element._loadChatSettings();
    expect(element._chatTimeoutSec).toBe(300);
  });
});

describe("_askAI — configurable timeout", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("does not abort at 90s when a longer timeout is configured", async () => {
    vi.stubGlobal("fetch", hangingFetch());
    const { element } = makePanel();
    element._chatTimeoutSec = 600;
    const done = startAsk(element);

    await vi.advanceTimersByTimeAsync(599_000);
    expect(element.shadowRoot.getElementById("btn-ask").disabled).toBe(true);

    await vi.advanceTimersByTimeAsync(1_000);
    await done;
    expect(element.shadowRoot.getElementById("btn-ask").disabled).toBe(false);
    expect(element.shadowRoot.textContent).toContain("Request timed out (600s)");
  });

  it("falls back to the default timeout when no setting was loaded", async () => {
    vi.stubGlobal("fetch", hangingFetch());
    const { element } = makePanel();
    element._chatTimeoutSec = undefined;
    const done = startAsk(element);

    await vi.advanceTimersByTimeAsync(DEFAULT_CHAT_TIMEOUT_SEC * 1000 - 1_000);
    expect(element.shadowRoot.getElementById("btn-ask").disabled).toBe(true);

    await vi.advanceTimersByTimeAsync(1_000);
    await done;
    expect(element.shadowRoot.textContent).toContain(`Request timed out (${DEFAULT_CHAT_TIMEOUT_SEC}s)`);
  });

  it("re-reads a stale timeout before the request so a changed option applies at once", async () => {
    vi.stubGlobal("fetch", hangingFetch({ chat_timeout: 300 }));
    const { element } = makePanel();
    element._chatTimeoutSec = 30;                          // old option value
    element._chatSettingsTriedAt = Date.now() - 60_000;    // loaded a minute ago
    const done = startAsk(element);

    await vi.advanceTimersByTimeAsync(31_000);             // old value would have aborted here
    expect(element.shadowRoot.getElementById("btn-ask").disabled).toBe(true);
    const urls = fetch.mock.calls.map((c) => c[0]);
    expect(urls.indexOf("/api/kyber/chat_settings")).toBeLessThan(urls.indexOf("/api/kyber/complete"));

    await vi.advanceTimersByTimeAsync(270_000);
    await done;
    expect(element.shadowRoot.textContent).toContain("Request timed out (300s)");
  });

  it("does not re-read a fresh timeout before the request", async () => {
    vi.stubGlobal("fetch", hangingFetch({ chat_timeout: 300 }));
    const { element } = makePanel();
    element._chatTimeoutSec = 60;
    element._chatSettingsTriedAt = Date.now();
    const done = startAsk(element);
    await vi.advanceTimersByTimeAsync(0);
    expect(fetch.mock.calls[0][0]).toBe("/api/kyber/complete");
    await vi.advanceTimersByTimeAsync(60_000);
    await done;
    expect(element.shadowRoot.textContent).toContain("Request timed out (60s)");
  });

  it("refreshes the setting after a request so option changes apply without reload", async () => {
    vi.stubGlobal("fetch", hangingFetch({ chat_timeout: 900 }));
    const { element } = makePanel();
    element._chatTimeoutSec = 60;
    const done = startAsk(element);
    await vi.advanceTimersByTimeAsync(60_000);
    await done;
    await vi.advanceTimersByTimeAsync(0);
    expect(element._chatTimeoutSec).toBe(900);
  });
});
