/**
 * HA's ip_ban counts every 401 as a failed login. The panel used to send
 * this._hass.auth.data.access_token with a raw fetch — that token expires after
 * 30 minutes and nothing refreshed it, so the 5 s status poll got the PC banned.
 *
 * Covers:
 *   - no bare fetch() left in the panel sources (all calls go through hass.fetchWithAuth)
 *   - pollers send nothing after a 401 until HA hands over a different token
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { makePanel } from "../helpers.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const wwwSrc = path.resolve(__dirname, "../../../../custom_components/kyber/www");

function sourceFiles() {
  const srcDir = path.join(wwwSrc, "src");
  return [
    path.join(wwwSrc, "kyber-panel.js"),
    ...fs.readdirSync(srcDir).filter((f) => f.endsWith(".js")).map((f) => path.join(srcDir, f)),
  ];
}

function statusResponse(status = 200, explorerProgress = { status: "narrator" }) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve({ explorer_progress: explorerProgress }),
  };
}

describe("panel sources", () => {
  it("contain no bare fetch() calls", () => {
    const offenders = [];
    for (const file of sourceFiles()) {
      fs.readFileSync(file, "utf8").split(/\r?\n/).forEach((line, i) => {
        if (/(^|[^\w.])fetch\(/.test(line)) offenders.push(`${path.basename(file)}:${i + 1}: ${line.trim()}`);
      });
    }
    expect(offenders).toEqual([]);
  });
});

describe("status poll and 401", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("goes through hass.fetchWithAuth", async () => {
    const { element, hass } = makePanel();
    hass.fetchWithAuth = vi.fn().mockResolvedValue(statusResponse());
    await element._checkKyberStatus();
    expect(hass.fetchWithAuth).toHaveBeenCalledWith("/api/kyber/debug/status");
  });

  it("sends nothing after a 401 until the token changes", async () => {
    const { element, hass } = makePanel();
    hass.fetchWithAuth = vi.fn().mockResolvedValue(statusResponse(401));
    await element._checkKyberStatus();
    await element._checkKyberStatus();
    await element._checkKyberStatus();
    expect(hass.fetchWithAuth).toHaveBeenCalledTimes(1);

    hass.auth.data.access_token = "fresh-token";
    hass.fetchWithAuth.mockResolvedValue(statusResponse());
    await element._checkKyberStatus();
    expect(hass.fetchWithAuth).toHaveBeenCalledTimes(2);
  });

  it("other errors do not silence the poll", async () => {
    const { element, hass } = makePanel();
    hass.fetchWithAuth = vi.fn().mockResolvedValue(statusResponse(500));
    await element._checkKyberStatus();
    await element._checkKyberStatus();
    expect(hass.fetchWithAuth).toHaveBeenCalledTimes(2);
  });
});

describe("progress poll and 401", () => {
  it("stops on a 401 and skips later polls with the same token", async () => {
    const { element, hass } = makePanel();
    hass.fetchWithAuth = vi.fn().mockResolvedValue({ ok: false, status: 401 });
    await element._pollProgress("req-1", () => false);
    expect(hass.fetchWithAuth).toHaveBeenCalledTimes(1);

    await element._pollProgress("req-2", () => false);
    expect(hass.fetchWithAuth).toHaveBeenCalledTimes(1);
  });
});

describe("deep analysis poll and 401", () => {
  it("reports not alive without a request once the token was rejected", async () => {
    const { element, hass } = makePanel();
    const body = document.createElement("div");
    body.innerHTML = '<div id="dbg-deep-status"></div>';
    hass.fetchWithAuth = vi.fn().mockResolvedValue({ ok: false, status: 401 });
    expect(await element._refreshDeepAnalysisStatus(body)).toBe(false);
    expect(await element._refreshDeepAnalysisStatus(body)).toBe(false);
    expect(hass.fetchWithAuth).toHaveBeenCalledTimes(1);
  });
});
