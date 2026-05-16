/**
 * Integration tests for _maybeCompact (history compaction) in KyberPanel.
 *
 * Covers:
 *   - Does NOT call /summarize when history <= COMPACT_TRIGGER
 *   - Calls /api/kyber/summarize when history exceeds COMPACT_TRIGGER
 *   - Sends previous_summary and the overflow messages to /summarize
 *   - Updates _compactedSummary from the response
 *   - Keeps HISTORY_WINDOW most-recent messages after compaction
 *   - Restores compacted messages on network failure (non-fatal)
 */

import { makePanel } from "../helpers.js";

function makeMsgs(count) {
  return Array.from({ length: count }, (_, i) => ({
    role: i % 2 === 0 ? "user" : "assistant",
    content: `Message ${i}`,
  }));
}

describe("_maybeCompact", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ summary: "Compacted history summary" }),
    }));
  });
  afterEach(() => vi.unstubAllGlobals());

  it("does not call /summarize when history is at or below COMPACT_TRIGGER", async () => {
    const { element } = makePanel();
    // COMPACT_TRIGGER is 7 — fill to exactly 7
    element._chatHistory = makeMsgs(7);
    await element._maybeCompact();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("calls /api/kyber/summarize when history exceeds COMPACT_TRIGGER", async () => {
    const { element } = makePanel();
    element._chatHistory = makeMsgs(8); // 8 > 7
    await element._maybeCompact();
    expect(fetch).toHaveBeenCalledWith("/api/kyber/summarize", expect.any(Object));
  });

  it("sends previous_summary and the overflow messages", async () => {
    const { element } = makePanel();
    element._compactedSummary = "Earlier context";
    element._chatHistory = makeMsgs(8);
    await element._maybeCompact();
    const body = JSON.parse(fetch.mock.calls[0][1].body);
    expect(body.previous_summary).toBe("Earlier context");
    // Should have sent 8 - 5 (HISTORY_WINDOW) = 3 messages for compaction
    expect(body.messages.length).toBe(3);
  });

  it("updates _compactedSummary from response", async () => {
    const { element } = makePanel();
    element._chatHistory = makeMsgs(8);
    await element._maybeCompact();
    expect(element._compactedSummary).toBe("Compacted history summary");
  });

  it("keeps only HISTORY_WINDOW messages after compaction", async () => {
    const { element } = makePanel();
    element._chatHistory = makeMsgs(8);
    await element._maybeCompact();
    // After compaction: 8 - 3 overflow = 5 messages remain in history
    expect(element._chatHistory.length).toBe(element._HISTORY_WINDOW);
  });

  it("restores messages on network failure (non-fatal)", async () => {
    fetch.mockRejectedValue(new Error("Network error"));
    const { element } = makePanel();
    const msgs = makeMsgs(8);
    element._chatHistory = [...msgs];
    await element._maybeCompact();
    // Messages should be restored to their original count
    expect(element._chatHistory.length).toBe(8);
  });

  it("uses Authorization header with hass token", async () => {
    const { element } = makePanel();
    element._chatHistory = makeMsgs(8);
    await element._maybeCompact();
    const headers = fetch.mock.calls[0][1].headers;
    expect(headers.Authorization).toBe("Bearer test-token");
  });
});
