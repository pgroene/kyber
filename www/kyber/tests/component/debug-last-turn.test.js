import { makePanel } from "../helpers.js";

describe("_renderDebugLastTurn logs", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("renders captured logs and escapes log message HTML", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        snapshot: {
          ts: 1715971200,
          request_id: "req-1",
          elapsed_ms: 123,
          intent: "chat",
          char_count: 10,
          approx_tokens: 5,
          user_prompt: "hello",
          response_text: "done",
          picked_knowledge: [],
          tool_log: [],
          logs: [
            { ts: 1715971200, level: "ERROR", logger: "custom_components.kyber.http_api", message: "Boom" },
            { ts: 1715971201, level: "WARNING", logger: "custom_components.kyber", message: "<script>alert(1)</script>" },
          ],
        },
      }),
    }));

    const { element } = makePanel();
    const body = element.shadowRoot.getElementById("debug-body");
    await element._renderDebugLastTurn(body);

    const summaryText = [...body.querySelectorAll("summary")].map((s) => s.textContent || "").join(" ");
    expect(summaryText).toContain("Logs (2)");
    const logsPre = [...body.querySelectorAll("details .dbg-pre")]
      .find((pre) => (pre.textContent || "").includes("custom_components.kyber.http_api"));
    expect(logsPre).toBeTruthy();
    expect(logsPre.innerHTML).not.toContain("<script>");
    expect(logsPre.textContent).toContain("<script>alert(1)</script>");
  });
});
