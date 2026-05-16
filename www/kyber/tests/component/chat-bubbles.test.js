/**
 * Component tests for _appendMessage and _appendAIResponse in KyberPanel.
 *
 * Covers:
 *   - _appendMessage: correct CSS role class (user, assistant, error)
 *   - _appendMessage: text content is set
 *   - _appendAIResponse: strips yaml/plan fences from displayed text
 *   - _appendAIResponse: shows YAML block with "Apply" button when yaml_blocks provided
 *   - _appendAIResponse: renders **bold** words as inline-choice buttons
 *   - _appendAIResponse: shows suggestion chips for Yes/No question responses
 *   - _appendAIResponse: appends plan card when plan.actions provided
 *   - _appendAIResponse: appends open-editor prompt when plan.open_editor = true
 */

import { makePanel } from "../helpers.js";

describe("panel branding", () => {
  it("renders the Kyber icon in both header and sidebar", () => {
    const { element } = makePanel();
    const headerIcon = element.shadowRoot.getElementById("kyber-header-icon");
    const sidebarIcon = element.shadowRoot.getElementById("kyber-sidebar-icon");

    expect(headerIcon).not.toBeNull();
    expect(sidebarIcon).not.toBeNull();
    expect(headerIcon.getAttribute("src")).toContain("icon.png");
    expect(sidebarIcon.getAttribute("src")).toContain("icon.png");
  });
});

describe("_appendMessage", () => {
  it("appends message with 'user' class", () => {
    const { element } = makePanel();
    element._appendMessage("Hello world", "user");
    const msg = element.shadowRoot.querySelector(".chat-message.user");
    expect(msg).not.toBeNull();
    expect(msg.textContent).toBe("Hello world");
  });

  it("appends message with 'assistant' class", () => {
    const { element } = makePanel();
    element._appendMessage("Response here", "assistant");
    // shadowRoot has the initial "Hi!" greeting plus our appended message
    const msgs = element.shadowRoot.querySelectorAll(".chat-message.assistant");
    expect(msgs[msgs.length - 1].textContent).toBe("Response here");
  });

  it("appends message with 'error' class", () => {
    const { element } = makePanel();
    element._appendMessage("Something went wrong", "error");
    const msg = element.shadowRoot.querySelector(".chat-message.error");
    expect(msg).not.toBeNull();
    expect(msg.textContent).toContain("Something went wrong");
  });

  it("appends to #chat-history container", () => {
    const { element } = makePanel();
    const history = element.shadowRoot.getElementById("chat-history");
    const before = history.querySelectorAll(".chat-message").length;
    element._appendMessage("Test", "assistant");
    expect(history.querySelectorAll(".chat-message").length).toBe(before + 1);
  });

  it("appends multiple messages in order", () => {
    const { element } = makePanel();
    element._appendMessage("first", "user");
    element._appendMessage("second", "assistant");
    const msgs = [...element.shadowRoot.querySelectorAll(".chat-message")];
    const newMsgs = msgs.filter((m) => m.textContent === "first" || m.textContent === "second");
    expect(newMsgs[0].textContent).toBe("first");
    expect(newMsgs[1].textContent).toBe("second");
  });
});

describe("_appendAIResponse", () => {
  it("displays text content stripped of yaml and plan fences", () => {
    const { element } = makePanel();
    const fullText = "Here is my suggestion:\n```yaml\nalias: test\n```\nLet me know.";
    element._appendAIResponse(fullText, [], null);
    // Find last assistant message (skips the initial greeting from _render())
    const msgs = element.shadowRoot.querySelectorAll(".chat-message.assistant");
    const lastMsg = msgs[msgs.length - 1];
    expect(lastMsg.textContent).toContain("Here is my suggestion");
    expect(lastMsg.textContent).toContain("Let me know");
    expect(lastMsg.textContent).not.toContain("```yaml");
  });

  it("shows YAML block with Apply button when yaml_blocks provided", () => {
    const { element } = makePanel();
    element._appendAIResponse("Check this YAML", ["alias: test\nmode: single"], null);
    const container = element.shadowRoot.querySelector(".yaml-suggestion");
    expect(container).not.toBeNull();
    const btn = container.querySelector("button");
    expect(btn.textContent).toContain("Apply");
  });

  it("Apply button marks itself as applied after click", () => {
    const { element } = makePanel();
    // Open editor so editor content can be set
    element._editor = { state: { doc: { toString: () => "" } }, dispatch: vi.fn() };
    element._appendAIResponse("Here is YAML", ["alias: test"], null);
    const applyBtn = element.shadowRoot.querySelector(".yaml-suggestion button");
    applyBtn.click();
    expect(applyBtn.disabled).toBe(true);
    expect(applyBtn.textContent).toContain("Applied");
  });

  it("renders **bold** words as inline-choice buttons", () => {
    const { element } = makePanel();
    element._appendAIResponse("Would you like to **turn on lights** or **set a timer**?", [], null);
    const choices = element.shadowRoot.querySelectorAll(".inline-choice");
    expect(choices.length).toBeGreaterThanOrEqual(2);
    expect(choices[0].textContent).toBe("turn on lights");
  });

  it("shows suggestion chips for Yes/No question when response has no bold", () => {
    const { element } = makePanel();
    element._appendAIResponse("Should I proceed? You can confirm with yes or no.", [], null);
    const chips = element.shadowRoot.querySelectorAll(".suggestion-chip");
    expect(chips.length).toBe(2);
    const labels = [...chips].map((c) => c.textContent);
    expect(labels).toContain("Yes");
    expect(labels).toContain("No");
  });

  it("does not show text div when fullText is empty after stripping", () => {
    const { element } = makePanel();
    const history = element.shadowRoot.getElementById("chat-history");
    const before = history.querySelectorAll(".chat-message.assistant").length;
    element._appendAIResponse("```yaml\nalias: test\n```", [], null);
    // No new assistant message should be added
    expect(history.querySelectorAll(".chat-message.assistant").length).toBe(before);
  });

  it("appends plan card when plan has actions", () => {
    const { element } = makePanel({
      states: { "light.bedroom": { entity_id: "light.bedroom", attributes: {} } },
    });
    const plan = {
      summary: "Test plan",
      actions: [{ type: "assign_area", entity_id: "light.bedroom", new_state: "Office" }],
    };
    element._appendAIResponse("Here is my plan:", [], plan);
    expect(element.shadowRoot.querySelector(".plan-card")).not.toBeNull();
  });

  it("appends open-editor prompt when plan.open_editor = true", () => {
    const { element } = makePanel();
    const plan = { summary: "Edit automation", open_editor: true, automation_id: "automation.test" };
    element._appendAIResponse("Opening editor", [], plan);
    expect(element.shadowRoot.querySelector(".open-editor-prompt")).not.toBeNull();
  });

  it("appends open-dashboard prompt when plan.open_dashboard = true", () => {
    const { element } = makePanel();
    const plan = { summary: "Edit dashboard", open_dashboard: true };
    element._appendAIResponse("Opening dashboard", [], plan);
    expect(element.shadowRoot.querySelector(".open-editor-prompt")).not.toBeNull();
  });
});
