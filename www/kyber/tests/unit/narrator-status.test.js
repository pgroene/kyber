/**
 * Narrator status in the debug panel.
 *
 * The status used to depend on "total" alone, which stays 0 while the first
 * batch runs and when nothing was due. After "Run narrator now" the panel
 * therefore showed "Not yet run" next to a last-run timestamp. The rows read
 * accepted_first / accepted_retry / rejected, which the backend never sends.
 */

import { makePanel } from "../helpers.js";

const started = Date.UTC(2026, 9, 9, 14, 51, 32) / 1000;

describe("_narratorStatusView", () => {
  let view;
  beforeEach(() => {
    const { element } = makePanel({ language: "de" });
    view = (ns) => element._narratorStatusView(ns);
  });

  it("no stats: not yet run, no timestamp", () => {
    expect(view({})).toEqual({ label: "Noch nicht ausgeführt", lastRun: "", rows: [] });
  });

  it("finished with nothing due: up to date, not 'not yet run'", () => {
    const v = view({ running: false, due: 0, total: 0, started_at: started, last_run: "2026-10-09T14:51:32" });
    expect(v.label).toBe("Alles aktuell: keine Entität musste beschrieben werden");
    expect(v.rows).toEqual([]);
  });

  it("the timestamp is shown in local time, not as the raw backend string", () => {
    const v = view({ running: false, due: 0, started_at: started, last_run: "2026-10-09T14:51:32" });
    expect(v.lastRun).toBe(new Date(started * 1000).toLocaleString());
    expect(v.lastRun).not.toContain("T14:51");
  });

  it("running: progress against the due count", () => {
    const v = view({ running: true, due: 112, total: 40, started_at: started });
    expect(v.label).toBe("Läuft: 40 von 112 Entitäten …");
  });

  it("done: counts come from the fields the backend sends", () => {
    const v = view({
      running: false, due: 112, total: 112, started_at: started,
      accepted: 108, low_quality: 3, parse_failures: 1, errors: 0,
    });
    expect(v.label).toBe("108 von 112 Entitäten beschrieben (96 %)");
    expect(v.rows).toEqual([
      ["dbg_st_ns_accepted", 108],
      ["dbg_st_ns_low_quality", 3],
      ["dbg_st_ns_parse_failures", 1],
      ["dbg_st_errors", 0],
    ]);
  });

  it("stats from an older backend (no due/running) fall back to total", () => {
    const v = view({ total: 5, accepted: 5, last_run: "2026-10-09T14:51:32" });
    expect(v.label).toBe("5 von 5 Entitäten beschrieben (100 %)");
    expect(v.lastRun).toBe("2026-10-09T14:51:32");
  });
});
