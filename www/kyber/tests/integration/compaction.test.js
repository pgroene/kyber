/**
 * Integration tests for _maybeCompact (history compaction) in KyberPanel.
 *
 * Compaction strategy (new, size-based):
 *   - Triggers when total message chars > _COMPACT_SIZE_TRIGGER (12000)
 *     OR message count > _COMPACT_COUNT_TRIGGER (20)
 *   - Compacts oldest whole-messages (never splits) until ~_COMPACT_OLDEST_CHARS (6000) freed
 *   - When count-triggered, compacts oldest half of messages
 *   - Shows a banner in the chat DOM after successful compaction
 *   - Banner is NOT added to _chatHistory (must not pollute AI context)
 *   - Non-fatal: restores messages on network or server failure
 *   - Passes previous_summary + compacted messages to /api/kyber/summarize
 *   - Updates _compactedSummary from response
 *   - Calls _persistHistory after successful compaction
 */

import { makePanel } from "../helpers.js";

// ── helpers ──────────────────────────────────────────────────────────────────

/** Create `count` messages each with `contentLength` chars of content. */
function makeMessages(count, contentLength = 10) {
  return Array.from({ length: count }, (_, i) => ({
    role: i % 2 === 0 ? "user" : "assistant",
    content: "x".repeat(contentLength),
  }));
}

/** Create messages that total at least `targetChars` chars (few large messages). */
function makeMessagesWithTotalChars(targetChars, msgCount = 5) {
  const perMsg = Math.ceil(targetChars / msgCount);
  return Array.from({ length: msgCount }, (_, i) => ({
    role: i % 2 === 0 ? "user" : "assistant",
    content: "y".repeat(perMsg),
  }));
}

function totalChars(messages) {
  return messages.reduce((sum, m) => sum + m.content.length, 0);
}

function mockSummarize(summary = "Compacted summary") {
  return vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ summary }),
  });
}

// ── not triggered ─────────────────────────────────────────────────────────────

describe("_maybeCompact — not triggered", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("does not compact when chars < SIZE_TRIGGER and count < COUNT_TRIGGER", async () => {
    vi.stubGlobal("fetch", mockSummarize());
    const { element } = makePanel();
    // 10 messages × 100 chars = 1000 total — well under both triggers
    element._chatHistory = makeMessages(10, 100);
    await element._maybeCompact();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("does not compact at exactly COMPACT_COUNT_TRIGGER messages", async () => {
    vi.stubGlobal("fetch", mockSummarize());
    const { element } = makePanel();
    element._chatHistory = makeMessages(element._COMPACT_COUNT_TRIGGER, 10);
    await element._maybeCompact();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("does not compact at exactly COMPACT_SIZE_TRIGGER chars", async () => {
    vi.stubGlobal("fetch", mockSummarize());
    const { element } = makePanel();
    // Create messages summing to exactly COMPACT_SIZE_TRIGGER
    const trigger = element._COMPACT_SIZE_TRIGGER;
    const msgs = makeMessages(4, Math.floor(trigger / 4));
    // Adjust last message so total is exactly trigger (not over)
    const remainder = trigger - totalChars(msgs);
    if (remainder > 0) msgs[msgs.length - 1].content += "z".repeat(remainder);
    element._chatHistory = msgs;
    expect(totalChars(element._chatHistory)).toBe(trigger);
    await element._maybeCompact();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("does not compact an empty history", async () => {
    vi.stubGlobal("fetch", mockSummarize());
    const { element } = makePanel();
    element._chatHistory = [];
    await element._maybeCompact();
    expect(fetch).not.toHaveBeenCalled();
  });
});

// ── triggered by size ────────────────────────────────────────────────────────

describe("_maybeCompact — triggered by size (chars > SIZE_TRIGGER)", () => {
  let element;

  beforeEach(() => {
    vi.stubGlobal("fetch", mockSummarize());
    ({ element } = makePanel());
    // 5 messages × 3000 chars = 15000 — over 12000 trigger
    element._chatHistory = makeMessages(5, 3000);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("calls /api/kyber/summarize when size exceeds SIZE_TRIGGER", async () => {
    expect(totalChars(element._chatHistory)).toBeGreaterThan(element._COMPACT_SIZE_TRIGGER);
    await element._maybeCompact();
    expect(fetch).toHaveBeenCalledWith("/api/kyber/summarize", expect.any(Object));
  });

  it("compacts oldest whole messages up to COMPACT_OLDEST_CHARS", async () => {
    await element._maybeCompact();
    const body = JSON.parse(fetch.mock.calls[0][1].body);
    // Compacted messages should cover >= COMPACT_OLDEST_CHARS chars (whole blocks)
    const compactedChars = totalChars(body.messages);
    expect(compactedChars).toBeGreaterThanOrEqual(element._COMPACT_OLDEST_CHARS);
  });

  it("never splits a message — compacted set contains only whole messages", async () => {
    const originalMessages = element._chatHistory.map(m => m.content);
    await element._maybeCompact();
    const body = JSON.parse(fetch.mock.calls[0][1].body);
    // Every compacted message must exactly match an original message
    for (const msg of body.messages) {
      expect(originalMessages).toContain(msg.content);
    }
  });

  it("retains recent messages verbatim after size-triggered compaction", async () => {
    const originalLast = element._chatHistory[element._chatHistory.length - 1].content;
    await element._maybeCompact();
    const lastRemaining = element._chatHistory[element._chatHistory.length - 1].content;
    expect(lastRemaining).toBe(originalLast);
  });

  it("reduces total message count after compaction", async () => {
    const before = element._chatHistory.length;
    await element._maybeCompact();
    expect(element._chatHistory.length).toBeLessThan(before);
  });

  it("sends previous_summary to /summarize", async () => {
    element._compactedSummary = "Earlier context";
    await element._maybeCompact();
    const body = JSON.parse(fetch.mock.calls[0][1].body);
    expect(body.previous_summary).toBe("Earlier context");
  });

  it("updates _compactedSummary from response", async () => {
    await element._maybeCompact();
    expect(element._compactedSummary).toBe("Compacted summary");
  });

  it("uses Authorization header with hass token", async () => {
    await element._maybeCompact();
    expect(fetch.mock.calls[0][1].headers.Authorization).toBe("Bearer test-token");
  });

  it("sends POST to /api/kyber/summarize with JSON content-type", async () => {
    await element._maybeCompact();
    expect(fetch.mock.calls[0][1].method).toBe("POST");
    expect(fetch.mock.calls[0][1].headers["Content-Type"]).toBe("application/json");
  });
});

// ── triggered by count ───────────────────────────────────────────────────────

describe("_maybeCompact — triggered by count (messages > COUNT_TRIGGER)", () => {
  let element;

  beforeEach(() => {
    vi.stubGlobal("fetch", mockSummarize());
    ({ element } = makePanel());
    // 21 messages × 50 chars = 1050 total — under size trigger but over count trigger
    element._chatHistory = makeMessages(element._COMPACT_COUNT_TRIGGER + 1, 50);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("fires when count > COUNT_TRIGGER even if total chars < SIZE_TRIGGER", async () => {
    expect(totalChars(element._chatHistory)).toBeLessThan(element._COMPACT_SIZE_TRIGGER);
    expect(element._chatHistory.length).toBeGreaterThan(element._COMPACT_COUNT_TRIGGER);
    await element._maybeCompact();
    expect(fetch).toHaveBeenCalledWith("/api/kyber/summarize", expect.any(Object));
  });

  it("compacts oldest half of messages when count-triggered", async () => {
    const before = element._chatHistory.length;
    await element._maybeCompact();
    // After compaction: at most half the original messages remain
    expect(element._chatHistory.length).toBeLessThanOrEqual(Math.ceil(before / 2));
  });

  it("keeps the most recent messages after count-triggered compaction", async () => {
    const lastMsg = element._chatHistory[element._chatHistory.length - 1].content;
    await element._maybeCompact();
    const lastRemaining = element._chatHistory[element._chatHistory.length - 1].content;
    expect(lastRemaining).toBe(lastMsg);
  });
});

// ── compaction banner ────────────────────────────────────────────────────────

describe("_maybeCompact — compaction banner", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows a compaction banner in the chat DOM after successful compaction", async () => {
    vi.stubGlobal("fetch", mockSummarize());
    const { element } = makePanel();
    element._chatHistory = makeMessages(5, 3000); // size-triggered
    await element._maybeCompact();
    const banners = element.shadowRoot.querySelectorAll(".system-compact, .chat-message-wrap.system-compact");
    expect(banners.length).toBeGreaterThan(0);
  });

  it("banner text mentions summarized context", async () => {
    vi.stubGlobal("fetch", mockSummarize());
    const { element } = makePanel();
    element._chatHistory = makeMessages(5, 3000);
    await element._maybeCompact();
    const chatHistory = element.shadowRoot.getElementById("chat-history");
    expect(chatHistory.textContent).toMatch(/summarized|compacted/i);
  });

  it("banner suggests starting a new conversation", async () => {
    vi.stubGlobal("fetch", mockSummarize());
    const { element } = makePanel();
    element._chatHistory = makeMessages(5, 3000);
    await element._maybeCompact();
    const chatHistory = element.shadowRoot.getElementById("chat-history");
    expect(chatHistory.textContent).toMatch(/new conversation/i);
  });

  it("banner is NOT added to _chatHistory (must not reach AI context)", async () => {
    vi.stubGlobal("fetch", mockSummarize());
    const { element } = makePanel();
    element._chatHistory = makeMessages(5, 3000);
    const beforeCount = element._chatHistory.length;
    await element._maybeCompact();
    // chatHistory should have FEWER messages after compaction, not more
    expect(element._chatHistory.length).toBeLessThan(beforeCount);
    // None of the remaining messages should contain the banner text
    const bannerInHistory = element._chatHistory.some(m =>
      /summarized|new conversation/i.test(m.content)
    );
    expect(bannerInHistory).toBe(false);
  });

  it("no banner is shown when compaction is not triggered", async () => {
    vi.stubGlobal("fetch", mockSummarize());
    const { element } = makePanel();
    element._chatHistory = makeMessages(3, 100); // well under triggers
    const chatBefore = element.shadowRoot.getElementById("chat-history").innerHTML;
    await element._maybeCompact();
    const chatAfter = element.shadowRoot.getElementById("chat-history").innerHTML;
    expect(chatAfter).toBe(chatBefore);
  });
});

// ── persistence ──────────────────────────────────────────────────────────────

describe("_maybeCompact — persistence", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("calls _persistHistory after successful compaction", async () => {
    vi.stubGlobal("fetch", mockSummarize());
    const { element } = makePanel();
    element._chatHistory = makeMessages(5, 3000);
    const spy = vi.spyOn(element, "_persistHistory").mockResolvedValue();
    await element._maybeCompact();
    expect(spy).toHaveBeenCalled();
  });

  it("does not call _persistHistory when not triggered", async () => {
    vi.stubGlobal("fetch", mockSummarize());
    const { element } = makePanel();
    element._chatHistory = makeMessages(3, 10);
    const spy = vi.spyOn(element, "_persistHistory").mockResolvedValue();
    await element._maybeCompact();
    expect(spy).not.toHaveBeenCalled();
  });
});

// ── failure resilience ───────────────────────────────────────────────────────

describe("_maybeCompact — failure resilience", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("restores messages on network failure (non-fatal)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Network error")));
    const { element } = makePanel();
    const msgs = makeMessages(5, 3000);
    element._chatHistory = [...msgs];
    await element._maybeCompact();
    expect(element._chatHistory.length).toBe(5);
  });

  it("restores messages when /summarize returns non-ok response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 500 }));
    const { element } = makePanel();
    const msgs = makeMessages(5, 3000);
    element._chatHistory = [...msgs];
    await element._maybeCompact();
    expect(element._chatHistory.length).toBe(5);
  });

  it("preserves exact message content after failure restore", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Network error")));
    const { element } = makePanel();
    const msgs = makeMessages(5, 3000);
    element._chatHistory = [...msgs];
    const originalContents = msgs.map(m => m.content);
    await element._maybeCompact();
    expect(element._chatHistory.map(m => m.content)).toEqual(originalContents);
  });

  it("does not update _compactedSummary on failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Network error")));
    const { element } = makePanel();
    element._compactedSummary = "Existing summary";
    element._chatHistory = makeMessages(5, 3000);
    await element._maybeCompact();
    expect(element._compactedSummary).toBe("Existing summary");
  });

  it("does not show banner on failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Network error")));
    const { element } = makePanel();
    element._chatHistory = makeMessages(5, 3000);
    await element._maybeCompact();
    const chatHistory = element.shadowRoot.getElementById("chat-history");
    expect(chatHistory.textContent).not.toMatch(/summarized|new conversation/i);
  });
});

// ── edge cases ───────────────────────────────────────────────────────────────

describe("_maybeCompact — edge cases", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("handles a single very long message (> COMPACT_OLDEST_CHARS) as a whole block", async () => {
    vi.stubGlobal("fetch", mockSummarize());
    const { element } = makePanel();
    // One giant message + a few more to hit the size trigger
    element._chatHistory = [
      { role: "user", content: "a".repeat(7000) },
      { role: "assistant", content: "b".repeat(6000) },
    ];
    await element._maybeCompact();
    const body = JSON.parse(fetch.mock.calls[0][1].body);
    // The first message (7000 chars) should be compacted as a whole unit
    expect(body.messages[0].content).toBe("a".repeat(7000));
  });

  it("always keeps at least one message in history after compaction", async () => {
    vi.stubGlobal("fetch", mockSummarize());
    const { element } = makePanel();
    // Two huge messages that both exceed COMPACT_OLDEST_CHARS
    element._chatHistory = [
      { role: "user", content: "a".repeat(7000) },
      { role: "assistant", content: "b".repeat(7000) },
    ];
    await element._maybeCompact();
    expect(element._chatHistory.length).toBeGreaterThanOrEqual(1);
  });

  it("accumulates compaction summaries — previous summary is passed each round", async () => {
    vi.stubGlobal("fetch", mockSummarize("Round 2 summary"));
    const { element } = makePanel();
    element._compactedSummary = "Round 1 summary";
    element._chatHistory = makeMessages(5, 3000);
    await element._maybeCompact();
    const body = JSON.parse(fetch.mock.calls[0][1].body);
    expect(body.previous_summary).toBe("Round 1 summary");
    expect(element._compactedSummary).toBe("Round 2 summary");
  });

  it("does not fire a second time if called again immediately after compaction (below trigger)", async () => {
    vi.stubGlobal("fetch", mockSummarize());
    const { element } = makePanel();
    element._chatHistory = makeMessages(5, 3000);
    await element._maybeCompact();
    fetch.mockClear();
    // Calling again: history is now smaller, should not trigger
    await element._maybeCompact();
    expect(fetch).not.toHaveBeenCalled();
  });
});
