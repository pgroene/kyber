/**
 * Thinking check in the debug panel's status tab.
 *
 * "Let the model think" only tells Kyber that thinking is on in the service
 * behind the model; the backend compares it with what the chat calls showed
 * (thinking_check.py) and sends the result as `thinking`. The tab shows the
 * setting, what was observed and, on a mismatch, where to fix it.
 */

import { makePanel } from "../helpers.js";

const ts = Date.UTC(2026, 10, 2, 14, 5, 0) / 1000;

describe("_thinkingStatusView", () => {
  let view;
  beforeEach(() => {
    const { element } = makePanel({ language: "de" });
    view = (th) => element._thinkingStatusView(th);
  });

  it("an older backend without the field shows nothing", () => {
    expect(view(undefined)).toBeNull();
  });

  it("no chat call yet", () => {
    expect(view({ allow_thinking: true, model: null, observed: "unknown", counts: {} })).toEqual({
      setting: "an", seen: "noch kein Chat-Aufruf seit dem Start von Home Assistant", counts: "", hint: "",
    });
  });

  it("setting and behaviour agree: no hint", () => {
    const v = view({
      allow_thinking: true, model: "ai_task.qwen", observed: "thinking", source: "chat_log", ts,
      counts: { thinking: 3, not_thinking: 0, unknown: 0 }, hint: null,
    });
    expect(v.setting).toBe("an");
    expect(v.seen).toBe(`denkt (Denktext im Chatprotokoll der KI-Aufgabe, ${new Date(ts * 1000).toLocaleTimeString()})`);
    expect(v.counts).toBe("3 von 3 Aufrufen mit Denken");
    expect(v.hint).toBe("");
  });

  it("on, but the model does not think: the hint names where to switch it on", () => {
    const v = view({
      allow_thinking: true, model: "ai_task.qwen", observed: "not_thinking", source: "chat_log_empty", ts,
      counts: { thinking: 0, not_thinking: 1, unknown: 0 }, hint: "ev_thinking_on_local_openai",
    });
    expect(v.seen).toContain("denkt nicht (kein Denktext");
    expect(v.counts).toBe("0 von 1 Aufruf mit Denken");
    expect(v.hint).toContain("ai_task.qwen hat ohne Denken geantwortet");
    expect(v.hint).toContain("enable_thinking = true");
  });

  it("off, but the model thinks", () => {
    const v = view({
      allow_thinking: false, model: "openai/gpt", observed: "thinking", source: "reasoning_tokens", ts,
      counts: { thinking: 1, not_thinking: 0, unknown: 0 }, hint: "ev_thinking_off",
    });
    expect(v.setting).toBe("aus");
    expect(v.hint).toBe(
      "openai/gpt hat vor der Antwort gedacht, obwohl „Modell darf denken“ aus ist. Schalte die Option ein " +
      "(Kyber hängt dann kein /no_think mehr an) oder schalte das Denken im Dienst hinter dem Modell aus.",
    );
  });
});

describe("status tab", () => {
  it("renders the thinking rows with the hint, escaped", async () => {
    const { element } = makePanel({ language: "en" });
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        ai_task_entity: "ai_task.qwen",
        thinking: {
          allow_thinking: false, model: "ai_task.qwen", observed: "thinking", source: "think_tags", ts,
          counts: { thinking: 2, not_thinking: 0, unknown: 1 }, hint: "ev_thinking_off",
        },
      }),
    });
    const body = document.createElement("div");
    await element._renderDebugStatus(body);
    expect(body.querySelector(".dbg-think-setting").textContent).toBe("off");
    const seen = body.querySelector(".dbg-think-seen").textContent;
    expect(seen).toContain("thinks (<think> block in the answer");
    expect(seen).toContain("2 of 3 calls with thinking");
    expect(body.querySelector(".dbg-think-seen").innerHTML).toContain("&lt;think&gt;");
    expect(body.querySelector(".dbg-think-hint").textContent).toContain(
      "ai_task.qwen thought before answering, although 'Let the model think' is off.",
    );
  });

  it("no hint row while setting and behaviour agree", async () => {
    const { element } = makePanel({ language: "en" });
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        thinking: {
          allow_thinking: true, model: "ai_task.qwen", observed: "thinking", source: "chat_log", ts,
          counts: { thinking: 1, not_thinking: 0, unknown: 0 }, hint: null,
        },
      }),
    });
    const body = document.createElement("div");
    await element._renderDebugStatus(body);
    expect(body.querySelector(".dbg-think-setting").textContent).toBe("on");
    expect(body.querySelector(".dbg-think-hint")).toBeNull();
  });
});
