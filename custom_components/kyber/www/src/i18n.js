/**
 * Kyber i18n — lightweight localisation for the panel UI.
 *
 * Usage:
 *   import { getT } from "./i18n.js?v=1";
 *   const t = getT("nl");
 *   t("ask")  // → "Vraag"
 *
 * - Falls back to English for any missing key.
 * - Language code matched as full tag first ("nl-BE"), then base ("nl").
 * - Add a new locale by exporting a constant and adding it to LOCALES.
 */

// ── English (default) ────────────────────────────────────────────────────────
export const EN = {
  // Sidebar / header
  brand:              "Kyber Assistant",
  memory_badge_title: "Memory facts — click to preview recalled facts",
  update_badge:       "Update",
  autopilot_badge:    "⚡ Autopilot",
  btn_clear_history:  "Clear history",
  btn_debug_title:    "Open debug / memory inspector",

  // Editor toolbar
  btn_new_dashboard:  "＋ New dashboard",
  btn_save:           "Save",
  btn_close_editor:   "✕ Close editor",

  // Chat input
  placeholder:        "Ask me anything about your smart home… (type / for commands)",
  btn_ask:            "Ask",

  // Greeting
  greeting:           "Hi! Ask me anything about your smart home — I can manage entities, areas, labels, or open automations for editing.",

  // Explorer banner
  exploring:          "Exploring your home…",

  // Debug panel
  debug_title:        "🐞 Kyber Debug",
  debug_tab_memory:   "🧠 Memory",
  debug_tab_last:     "📥 Last turn",
  debug_tab_status:   "⚙️ Status",
  debug_tab_logs:     "📋 Logs",
  debug_tab_tests:    "🧪 Tests",
  debug_loading:      "Loading…",

  // Memory popover
  memory_popover_header:  "🧠 Recalled this turn",
  memory_popover_empty:   "No facts recalled.",
  memory_popover_view_all:"View all in Memory tab →",

  // Status / AI
  thinking:           "Thinking…",
  cancelling:         "Cancelling…",
  loading:            "Loading…",
  copy_title:         "Copy",
  copy_failed_title:  "Copy failed — clipboard unavailable",
  retry_btn:          "↺ Retry",

  // Copy feedback
  copy_done:          "✓",
  copy_fail:          "✗",

  // Knowledge tab
  knowledge_empty:    "No saved knowledge yet.",
  knowledge_loading:  "Loading knowledge…",

  // Slash commands
  cmd_confirm_execute: "▶ Execute",
  cmd_cancel:          "Cancel",

  // Restart overlay
  restart_title:        "Home Assistant is restarting…",
  restart_subtitle:     "This page will reload automatically.",
  restart_waiting:      "Waiting for Home Assistant…",
  restart_back:         "✅ Home Assistant is back — reloading…",
  restart_slow:         "Taking longer than expected — reload manually.",

  // Update
  update_installing:    "⏳ Installing",
  update_installed:     "✅ Installed",
  update_downloading:   "⏳ Downloading",
  update_updated:       "✅ Updated",

  // Errors
  err_update_failed:    "Update failed",
  err_force_update_failed: "Force-update failed",
};

// ── Dutch (nl) ───────────────────────────────────────────────────────────────
export const NL = {
  // Sidebar / header
  brand:              "Kyber Assistent",
  memory_badge_title: "Geheugenfeiten — klik om herinnerde feiten te bekijken",
  update_badge:       "Update",
  autopilot_badge:    "⚡ Autopilot",
  btn_clear_history:  "Geschiedenis wissen",
  btn_debug_title:    "Open debug / geheugeninspecteur",

  // Editor toolbar
  btn_new_dashboard:  "＋ Nieuw dashboard",
  btn_save:           "Opslaan",
  btn_close_editor:   "✕ Editor sluiten",

  // Chat input
  placeholder:        "Stel me alles over je slimme thuis… (typ / voor opdrachten)",
  btn_ask:            "Vraag",

  // Greeting
  greeting:           "Hoi! Stel me alles over je slimme thuis — ik kan apparaten, zones, labels en automaties beheren.",

  // Explorer banner
  exploring:          "Je thuis verkennen…",

  // Debug panel
  debug_title:        "🐞 Kyber Debug",
  debug_tab_memory:   "🧠 Geheugen",
  debug_tab_last:     "📥 Laatste beurt",
  debug_tab_status:   "⚙️ Status",
  debug_tab_logs:     "📋 Logboek",
  debug_tab_tests:    "🧪 Tests",
  debug_loading:      "Laden…",

  // Memory popover
  memory_popover_header:   "🧠 Herinnerd deze beurt",
  memory_popover_empty:    "Geen feiten herinnerd.",
  memory_popover_view_all: "Bekijk alles in het Geheugen tabblad →",

  // Status / AI
  thinking:           "Bezig…",
  cancelling:         "Annuleren…",
  loading:            "Laden…",
  copy_title:         "Kopiëren",
  copy_failed_title:  "Kopiëren mislukt — klembord niet beschikbaar",
  retry_btn:          "↺ Opnieuw",

  // Copy feedback
  copy_done:          "✓",
  copy_fail:          "✗",

  // Knowledge tab
  knowledge_empty:    "Nog geen opgeslagen kennis.",
  knowledge_loading:  "Kennis laden…",

  // Slash commands
  cmd_confirm_execute: "▶ Uitvoeren",
  cmd_cancel:          "Annuleren",

  // Restart overlay
  restart_title:        "Home Assistant herstart…",
  restart_subtitle:     "Deze pagina wordt automatisch herladen.",
  restart_waiting:      "Wachten op Home Assistant…",
  restart_back:         "✅ Home Assistant is terug — herladen…",
  restart_slow:         "Duurt langer dan verwacht — herlaad handmatig.",

  // Update
  update_installing:    "⏳ Installeren",
  update_installed:     "✅ Geïnstalleerd",
  update_downloading:   "⏳ Downloaden",
  update_updated:       "✅ Bijgewerkt",

  // Errors
  err_update_failed:       "Update mislukt",
  err_force_update_failed: "Geforceerde update mislukt",
};

// ── Locale registry ──────────────────────────────────────────────────────────
const LOCALES = { en: EN, nl: NL };

/**
 * Returns a translation function for the given language tag.
 * Falls back gracefully: "nl-BE" → nl → en.
 *
 * @param {string} lang  e.g. "nl", "nl-BE", "en", "de"
 * @returns {function(string): string}
 */
export function getT(lang = "en") {
  const base = (lang || "en").split("-")[0].toLowerCase();
  const locale = LOCALES[lang] || LOCALES[base] || {};
  return (key) => locale[key] ?? EN[key] ?? key;
}
