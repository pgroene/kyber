/**
 * Component tests for _buildCommandCard in KyberPanel.
 *
 * Covers:
 *   - Renders title, detail, and warning sections
 *   - danger class applied when danger: true
 *   - Execute button triggers onConfirm callback with the card
 *   - Execute and Cancel buttons are disabled after Execute is clicked
 *   - Cancel button removes the card from DOM
 *   - Card is appended to #chat-history and scrolled into view
 */

import { makePanel } from "../helpers.js";

describe("_buildCommandCard", () => {
  function buildCard(opts = {}) {
    const { element } = makePanel();
    const defaults = {
      title: "Test Action",
      onConfirm: vi.fn(),
      ...opts,
    };
    element._buildCommandCard(defaults);
    const card = element.shadowRoot.querySelector(".command-card");
    return { element, card, onConfirm: defaults.onConfirm };
  }

  it("renders the card title", () => {
    const { card } = buildCard({ title: "Rename entity" });
    expect(card.querySelector(".command-card-title").textContent).toContain("Rename entity");
  });

  it("renders optional detail text", () => {
    const { card } = buildCard({ detail: "sensor.temperature → Indoor Temp" });
    expect(card.querySelector(".command-card-detail").textContent).toContain("sensor.temperature");
  });

  it("renders optional warning text", () => {
    const { card } = buildCard({ warning: "This cannot be undone" });
    expect(card.querySelector(".command-card-warning").textContent).toContain("cannot be undone");
  });

  it("omits detail div when detail not provided", () => {
    const { card } = buildCard();
    expect(card.querySelector(".command-card-detail")).toBeNull();
  });

  it("omits warning div when warning not provided", () => {
    const { card } = buildCard();
    expect(card.querySelector(".command-card-warning")).toBeNull();
  });

  it("applies danger class when danger: true", () => {
    const { card } = buildCard({ danger: true });
    expect(card.classList.contains("danger")).toBe(true);
  });

  it("does not apply danger class by default", () => {
    const { card } = buildCard();
    expect(card.classList.contains("danger")).toBe(false);
  });

  it("calls onConfirm with the card element when Execute is clicked", () => {
    const { card, onConfirm } = buildCard();
    card.querySelector(".btn-cmd-execute").click();
    expect(onConfirm).toHaveBeenCalledWith(card);
  });

  it("disables Execute and Cancel buttons after Execute is clicked", () => {
    const { card } = buildCard();
    card.querySelector(".btn-cmd-execute").click();
    expect(card.querySelector(".btn-cmd-execute").disabled).toBe(true);
    expect(card.querySelector(".btn-cmd-cancel").disabled).toBe(true);
  });

  it("removes the card from DOM when Cancel is clicked", () => {
    const { element, card } = buildCard();
    card.querySelector(".btn-cmd-cancel").click();
    expect(element.shadowRoot.querySelector(".command-card")).toBeNull();
  });

  it("appends the card to #chat-history", () => {
    const { element } = makePanel();
    element._buildCommandCard({ title: "Test", onConfirm: vi.fn() });
    const history = element.shadowRoot.getElementById("chat-history");
    expect(history.querySelector(".command-card")).not.toBeNull();
  });

  it("escapes HTML in title to prevent XSS", () => {
    const { card } = buildCard({ title: "<script>alert(1)</script>" });
    expect(card.innerHTML).not.toContain("<script>");
    expect(card.querySelector(".command-card-title").textContent).toContain("<script>");
  });
});
