import { describe, it, expect } from "vitest";
import { ChatHttpError, chatErrorDetail, chatErrorMessage } from "../../src/ai-mixin.js";
import { getT } from "../../src/i18n.js";

const NGINX_504 = `<html>
<head><title>504 Gateway Time-out</title></head>
<body>
<center><h1>504 Gateway Time-out</h1></center>
<hr><center>nginx</center>
</body>
</html>`;

describe("chatErrorDetail", () => {
  it("takes Kyber's JSON message without the provider prefix", () => {
    expect(chatErrorDetail('{"message":"AI provider error: overloaded"}'))
      .toEqual({ text: "overloaded", fromKyber: true });
  });

  it("takes only the title of a proxy's HTML page", () => {
    expect(chatErrorDetail(NGINX_504)).toEqual({ text: "Gateway Time-out", fromKyber: false });
  });

  it("keeps plain text as it is", () => {
    expect(chatErrorDetail("Service unavailable")).toEqual({ text: "Service unavailable", fromKyber: false });
  });
});

describe("chatErrorMessage", () => {
  const t = getT("de");

  it("explains a proxy timeout instead of showing its HTML", () => {
    const msg = chatErrorMessage(new ChatHttpError(504, NGINX_504), t);
    expect(msg).toContain("Proxy");
    expect(msg).toContain("proxy_read_timeout");
    expect(msg).not.toContain("<");
  });

  it("shows status and title for another proxy page", () => {
    const html = "<html><head><title>502 Bad Gateway</title></head><body></body></html>";
    expect(chatErrorMessage(new ChatHttpError(502, html), t)).toBe("Fehler: HTTP 502 (Bad Gateway)");
  });

  it("shows Kyber's own message", () => {
    const err = new ChatHttpError(503, '{"message":"AI provider error: model not loaded"}');
    expect(chatErrorMessage(err, t)).toBe("Fehler: model not loaded");
  });

  it("drops an overlong non-Kyber body", () => {
    expect(chatErrorMessage(new ChatHttpError(500, "x".repeat(400)), t)).toBe("Fehler: HTTP 500");
  });

  it("keeps the rate-limit hint", () => {
    const err = new ChatHttpError(503, '{"message":"AI provider error: 429 Too Many Requests"}');
    expect(chatErrorMessage(err, t)).toBe(t("ai_azure_rate_limit"));
  });

  it("uses the message of a network error", () => {
    expect(chatErrorMessage(new TypeError("Failed to fetch"), t)).toBe("Fehler: Failed to fetch");
  });
});
