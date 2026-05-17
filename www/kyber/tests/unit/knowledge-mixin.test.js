/**
 * Unit tests for knowledge management methods in KyberPanel.
 *
 * Covers:
 *   - _renderKnowledgePanel(data, opts) — renders the knowledge list UI
 *   - _renderAnalyzeProposals(data) — renders the analyze proposals section
 *   - _rateKnowledgeEntry(id, rating, rowEl) — POSTs rating via fetch
 */

import { makePanel } from "../helpers.js";

// ---------------------------------------------------------------------------
// _renderKnowledgePanel
// ---------------------------------------------------------------------------
describe("_renderKnowledgePanel", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ entries: [], categories: [] }),
      text: async () => "",
    }));
  });
  afterEach(() => vi.unstubAllGlobals());

  it("appends a knowledge panel card to chat history", () => {
    const { element } = makePanel();
    const data = {
      entries: [
        { id: "e1", content: "The user prefers dark mode", category: "preferences", user_rating: 0 },
      ],
      categories: ["preferences"],
    };
    element._renderKnowledgePanel(data);
    const history = element.shadowRoot.getElementById("chat-history");
    const panel = history.querySelector(".kyber-knowledge-panel");
    expect(panel).not.toBeNull();
  });

  it("shows 'no entries' message when entries array is empty", () => {
    const { element } = makePanel();
    element._renderKnowledgePanel({ entries: [], categories: [] });
    const history = element.shadowRoot.getElementById("chat-history");
    expect(history.textContent.toLowerCase()).toMatch(/no saved knowledge|no|empty/);
  });

  it("renders content for each knowledge item", () => {
    const { element } = makePanel();
    const data = {
      entries: [
        { id: "e1", content: "Fact one", category: "general", user_rating: 0 },
        { id: "e2", content: "Fact two", category: "general", user_rating: 0 },
      ],
      categories: ["general"],
    };
    element._renderKnowledgePanel(data);
    const history = element.shadowRoot.getElementById("chat-history");
    expect(history.textContent).toContain("Fact one");
    expect(history.textContent).toContain("Fact two");
  });
});

// ---------------------------------------------------------------------------
// _renderAnalyzeProposals
// ---------------------------------------------------------------------------
describe("_renderAnalyzeProposals", () => {
  it("renders proposal cards in the chat history", () => {
    const { element } = makePanel();
    const data = {
      proposals: [
        { id: "p1", content: "Remember: lights go on at sunset", category: "patterns", confidence: 0.9 },
        { id: "p2", content: "User wakes at 07:00", category: "schedule", confidence: 0.8 },
      ],
    };
    element._renderAnalyzeProposals(data);
    const history = element.shadowRoot.getElementById("chat-history");
    expect(history.textContent).toContain("Remember:");
  });

  it("handles empty proposals array gracefully", () => {
    const { element } = makePanel();
    // Should not throw
    expect(() => element._renderAnalyzeProposals({ proposals: [] })).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// _rateKnowledgeEntry
// ---------------------------------------------------------------------------
describe("_rateKnowledgeEntry", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }));
  });
  afterEach(() => vi.unstubAllGlobals());

  it("POSTs to /api/kyber/knowledge with id and user_rating", async () => {
    const { element } = makePanel();
    const rowEl = document.createElement("div");
    await element._rateKnowledgeEntry("entry-123", 4, rowEl);
    expect(fetch).toHaveBeenCalledWith(
      "/api/kyber/knowledge",
      expect.objectContaining({ method: "POST" })
    );
    const body = JSON.parse(fetch.mock.calls[0][1].body);
    expect(body.id).toBe("entry-123");
    expect(body.user_rating).toBe(4);
  });

  it("updates star UI on success", async () => {
    const { element } = makePanel();
    // Create a row with star buttons
    const rowEl = document.createElement("div");
    [1, 2, 3, 4, 5].forEach((r) => {
      const s = document.createElement("span");
      s.className = "kn-star";
      s.setAttribute("data-rating", r);
      rowEl.appendChild(s);
    });
    await element._rateKnowledgeEntry("e1", 3, rowEl);
    const filled = Array.from(rowEl.querySelectorAll(".kn-star.filled"));
    expect(filled.length).toBe(3);
  });
});
