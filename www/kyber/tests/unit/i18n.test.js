/**
 * Regression tests for the panel translations (src/i18n.js).
 *
 * Background: the non-English locales were committed with every non-ASCII
 * character replaced by "?" (e.g. "Verlauf l?schen"). DE has been restored;
 * these tests keep it — and the intact EN/NL locales — from regressing.
 */

import { EN, NL, DE, FR, ES, IT, PT, PL, HU, SV, RU, ZH, getT } from "kyber-www/src/i18n.js";

// Locales known to be intact. Add a locale here once it has been restored.
const CLEAN_LOCALES = { en: EN, nl: NL, de: DE };

// A "?" glued to letters ("l?schen") or several in a row ("?? Status") is the
// replacement character of a lossy encode, never real punctuation.
const REPLACEMENT_Q = /[\p{L}]\?[\p{L}]|\?\?|^\? |\? $|^\?$/u;
// UTF-8 decoded as cp1252/latin-1, e.g. "Ã¤" for "ä" or "â†’" for "→".
const MOJIBAKE = /Ã[\u0080-¿]|Â[\u0080-¿]|â[\u0080-¿€]|ðŸ/;

describe("i18n — intact locales", () => {
  for (const [lang, locale] of Object.entries(CLEAN_LOCALES)) {
    it(`${lang}: no "?" replacement characters`, () => {
      const bad = Object.entries(locale).filter(([, v]) => REPLACEMENT_Q.test(v));
      expect(bad).toEqual([]);
    });

    it(`${lang}: no mojibake`, () => {
      const bad = Object.entries(locale).filter(([, v]) => MOJIBAKE.test(v));
      expect(bad).toEqual([]);
    });

    it(`${lang}: defines every key of EN`, () => {
      const missing = Object.keys(EN).filter((k) => !(k in locale));
      expect(missing).toEqual([]);
    });
  }

  it("de: uses real umlauts", () => {
    const t = getT("de");
    expect(t("btn_clear_history")).toBe("Verlauf löschen");
    expect(t("btn_close_editor")).toBe("✕ Editor schließen");
    expect(t("cmd_confirm_execute")).toBe("▶ Ausführen");
    expect(t("greeting")).toContain("Entitäten");
  });

  it("de-AT falls back to de", () => {
    expect(getT("de-AT")("btn_clear_history")).toBe("Verlauf löschen");
  });
});

describe("i18n — autopilot button", () => {
  it("every locale shows the lightning symbol, not a replacement \"?\"", () => {
    for (const [lang, locale] of Object.entries({ EN, NL, DE, FR, ES, IT, PT, PL, HU, SV, RU, ZH })) {
      expect(locale.autopilot_badge, lang).toBe("⚡ Autopilot");
    }
  });

  it("the tooltip says what runs alone and what still needs approval", () => {
    const de = getT("de")("panel_autopilot_title");
    expect(de).toContain("ohne Klick");
    expect(de).toContain("Freigabe");
    expect(de).toContain("Neuladen");
    for (const locale of [EN, NL, DE]) {
      // Inserted into a title="…" attribute without escaping
      expect(locale.panel_autopilot_title).not.toContain('"');
      expect(locale.panel_autopilot_title).not.toContain("—");
    }
  });
});
