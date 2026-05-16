import { makePanel } from "../helpers.js";

const flushPromises = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("chat history persistence", () => {
  it("loads persisted history on panel render", async () => {
    const callApi = vi.fn().mockImplementation((method, path) => {
      if (method === "GET" && path === "kyber/history") {
        return Promise.resolve({
          history: [
            { role: "user", content: "persisted user message" },
            { role: "assistant", content: "persisted assistant message" },
          ],
          compacted_summary: "persisted summary",
        });
      }
      return Promise.resolve({});
    });

    const { element } = makePanel({ callApi });
    await flushPromises();

    expect(callApi).toHaveBeenCalledWith("GET", "kyber/history");
    expect(element._chatHistory).toEqual([
      { role: "user", content: "persisted user message" },
      { role: "assistant", content: "persisted assistant message" },
    ]);
    expect(element._compactedSummary).toBe("persisted summary");

    const userMsg = element.shadowRoot.querySelector(".chat-message.user");
    const assistantMsgs = element.shadowRoot.querySelectorAll(".chat-message.assistant");
    expect(userMsg?.textContent).toContain("persisted user message");
    expect(assistantMsgs[assistantMsgs.length - 1]?.textContent).toContain("persisted assistant message");
  });

  it("clears persisted history when Clear history is clicked", async () => {
    const callApi = vi.fn().mockImplementation((method, path) => {
      if (method === "GET" && path === "kyber/history") {
        return Promise.resolve({
          history: [{ role: "user", content: "old message" }],
          compacted_summary: "old summary",
        });
      }
      if (method === "DELETE" && path === "kyber/history") {
        return Promise.resolve({ status: "ok" });
      }
      return Promise.resolve({});
    });

    const { element } = makePanel({ callApi });
    await flushPromises();

    element.shadowRoot.getElementById("btn-clear-history").click();
    await flushPromises();

    expect(callApi).toHaveBeenCalledWith("DELETE", "kyber/history");
    expect(element._chatHistory).toEqual([]);
    expect(element._compactedSummary).toBe("");

    const msgs = element.shadowRoot.querySelectorAll(".chat-message.assistant");
    expect(msgs.length).toBe(1);
    expect(msgs[0].textContent).toContain("Hi! Ask me anything about your smart home");
  });
});
