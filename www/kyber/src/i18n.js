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

// ?? German (de) ?????????????????????????????????????????????????????????????
export const DE = {
  // Sidebar / header
  brand: "Kyber Assistent",
  memory_badge_title: "Erinnerungsfakten ? klicken, um abgerufene Fakten anzuzeigen",
  update_badge: "Update",
  autopilot_badge: "? Autopilot",
  btn_clear_history: "Verlauf l?schen",
  btn_debug_title: "Debug-/Speicherinspektor ?ffnen",

  // Editor toolbar
  btn_new_dashboard: "? Neues Dashboard",
  btn_save: "Speichern",
  btn_close_editor: "? Editor schlie?en",

  // Chat input
  placeholder: "Frag mich alles ?ber dein Smart Home? (f?r Befehle / eingeben)",
  btn_ask: "Fragen",

  // Greeting
  greeting: "Hallo! Frag mich alles ?ber dein Smart Home ? ich kann Entit?ten, Bereiche, Labels verwalten oder Automationen zum Bearbeiten ?ffnen.",

  // Explorer banner
  exploring: "Dein Zuhause wird erkundet?",

  // Debug panel
  debug_title: "?? Kyber Debug",
  debug_tab_memory: "?? Speicher",
  debug_tab_last: "?? Letzte Runde",
  debug_tab_status: "?? Status",
  debug_tab_logs: "?? Protokolle",
  debug_tab_tests: "?? Tests",
  debug_loading: "Wird geladen?",

  // Memory popover
  memory_popover_header: "?? In dieser Runde abgerufen",
  memory_popover_empty: "Keine Fakten abgerufen.",
  memory_popover_view_all: "Alles im Speicher-Tab anzeigen ?",

  // Status / AI
  thinking: "Denke nach?",
  cancelling: "Wird abgebrochen?",
  loading: "Wird geladen?",
  copy_title: "Kopieren",
  copy_failed_title: "Kopieren fehlgeschlagen ? Zwischenablage nicht verf?gbar",
  retry_btn: "? Erneut versuchen",

  // Copy feedback
  copy_done: "?",
  copy_fail: "?",

  // Knowledge tab
  knowledge_empty: "Noch kein Wissen gespeichert.",
  knowledge_loading: "Wissen wird geladen?",

  // Slash commands
  cmd_confirm_execute: "? Ausf?hren",
  cmd_cancel: "Abbrechen",

  // Restart overlay
  restart_title: "Home Assistant wird neu gestartet?",
  restart_subtitle: "Diese Seite wird automatisch neu geladen.",
  restart_waiting: "Warte auf Home Assistant?",
  restart_back: "? Home Assistant ist zur?ck ? neu laden?",
  restart_slow: "Dauert l?nger als erwartet ? manuell neu laden.",

  // Update
  update_installing: "? Installation",
  update_installed: "? Installiert",
  update_downloading: "? Herunterladen",
  update_updated: "? Aktualisiert",

  // Errors
  err_update_failed: "Update fehlgeschlagen",
  err_force_update_failed: "Erzwungenes Update fehlgeschlagen",
};

// ?? French (fr) ?????????????????????????????????????????????????????????????
export const FR = {
  // Sidebar / header
  brand: "Assistant Kyber",
  memory_badge_title: "Faits m?moris?s ? cliquez pour pr?visualiser les faits rappel?s",
  update_badge: "Mise ? jour",
  autopilot_badge: "? Autopilot",
  btn_clear_history: "Effacer l?historique",
  btn_debug_title: "Ouvrir le d?bogage / inspecteur m?moire",

  // Editor toolbar
  btn_new_dashboard: "? Nouveau tableau de bord",
  btn_save: "Enregistrer",
  btn_close_editor: "? Fermer l??diteur",

  // Chat input
  placeholder: "Demandez-moi n?importe quoi sur votre maison connect?e? (tapez / pour les commandes)",
  btn_ask: "Demander",

  // Greeting
  greeting: "Bonjour ! Demandez-moi n?importe quoi sur votre maison connect?e ? je peux g?rer des entit?s, des zones, des ?tiquettes ou ouvrir des automatisations pour les modifier.",

  // Explorer banner
  exploring: "Exploration de votre maison?",

  // Debug panel
  debug_title: "?? Kyber Debug",
  debug_tab_memory: "?? M?moire",
  debug_tab_last: "?? Dernier tour",
  debug_tab_status: "?? Statut",
  debug_tab_logs: "?? Journaux",
  debug_tab_tests: "?? Tests",
  debug_loading: "Chargement?",

  // Memory popover
  memory_popover_header: "?? Rappel? ? ce tour",
  memory_popover_empty: "Aucun fait rappel?.",
  memory_popover_view_all: "Tout voir dans l?onglet M?moire ?",

  // Status / AI
  thinking: "R?flexion?",
  cancelling: "Annulation?",
  loading: "Chargement?",
  copy_title: "Copier",
  copy_failed_title: "?chec de la copie ? presse-papiers indisponible",
  retry_btn: "? R?essayer",

  // Copy feedback
  copy_done: "?",
  copy_fail: "?",

  // Knowledge tab
  knowledge_empty: "Aucune connaissance enregistr?e pour le moment.",
  knowledge_loading: "Chargement des connaissances?",

  // Slash commands
  cmd_confirm_execute: "? Ex?cuter",
  cmd_cancel: "Annuler",

  // Restart overlay
  restart_title: "Home Assistant red?marre?",
  restart_subtitle: "Cette page se rechargera automatiquement.",
  restart_waiting: "En attente de Home Assistant?",
  restart_back: "? Home Assistant est de retour ? rechargement?",
  restart_slow: "Cela prend plus de temps que pr?vu ? rechargez manuellement.",

  // Update
  update_installing: "? Installation",
  update_installed: "? Install?",
  update_downloading: "? T?l?chargement",
  update_updated: "? Mis ? jour",

  // Errors
  err_update_failed: "?chec de la mise ? jour",
  err_force_update_failed: "?chec de la mise ? jour forc?e",
};

// ?? Spanish (es) ?????????????????????????????????????????????????????????????
export const ES = {
  // Sidebar / header
  brand: "Asistente Kyber",
  memory_badge_title: "Datos de memoria ? haz clic para previsualizar los datos recordados",
  update_badge: "Actualizar",
  autopilot_badge: "? Autopilot",
  btn_clear_history: "Borrar historial",
  btn_debug_title: "Abrir depuraci?n / inspector de memoria",

  // Editor toolbar
  btn_new_dashboard: "? Nuevo panel",
  btn_save: "Guardar",
  btn_close_editor: "? Cerrar editor",

  // Chat input
  placeholder: "Preg?ntame cualquier cosa sobre tu hogar inteligente? (escribe / para ver los comandos)",
  btn_ask: "Preguntar",

  // Greeting
  greeting: "?Hola! Preg?ntame cualquier cosa sobre tu hogar inteligente ? puedo gestionar entidades, ?reas, etiquetas o abrir automatizaciones para editarlas.",

  // Explorer banner
  exploring: "Explorando tu hogar?",

  // Debug panel
  debug_title: "?? Kyber Debug",
  debug_tab_memory: "?? Memoria",
  debug_tab_last: "?? ?ltimo turno",
  debug_tab_status: "?? Estado",
  debug_tab_logs: "?? Registros",
  debug_tab_tests: "?? Pruebas",
  debug_loading: "Cargando?",

  // Memory popover
  memory_popover_header: "?? Recordado en este turno",
  memory_popover_empty: "No se recordaron datos.",
  memory_popover_view_all: "Ver todo en la pesta?a Memoria ?",

  // Status / AI
  thinking: "Pensando?",
  cancelling: "Cancelando?",
  loading: "Cargando?",
  copy_title: "Copiar",
  copy_failed_title: "Error al copiar ? portapapeles no disponible",
  retry_btn: "? Reintentar",

  // Copy feedback
  copy_done: "?",
  copy_fail: "?",

  // Knowledge tab
  knowledge_empty: "A?n no hay conocimiento guardado.",
  knowledge_loading: "Cargando conocimiento?",

  // Slash commands
  cmd_confirm_execute: "? Ejecutar",
  cmd_cancel: "Cancelar",

  // Restart overlay
  restart_title: "Home Assistant se est? reiniciando?",
  restart_subtitle: "Esta p?gina se recargar? autom?ticamente.",
  restart_waiting: "Esperando a Home Assistant?",
  restart_back: "? Home Assistant ha vuelto ? recargando?",
  restart_slow: "Est? tardando m?s de lo esperado ? recarga manualmente.",

  // Update
  update_installing: "? Instalando",
  update_installed: "? Instalado",
  update_downloading: "? Descargando",
  update_updated: "? Actualizado",

  // Errors
  err_update_failed: "La actualizaci?n fall?",
  err_force_update_failed: "La actualizaci?n forzada fall?",
};

// ?? Italian (it) ?????????????????????????????????????????????????????????????
export const IT = {
  // Sidebar / header
  brand: "Assistente Kyber",
  memory_badge_title: "Fatti in memoria ? fai clic per visualizzare in anteprima i fatti richiamati",
  update_badge: "Aggiorna",
  autopilot_badge: "? Autopilot",
  btn_clear_history: "Cancella cronologia",
  btn_debug_title: "Apri debug / ispettore memoria",

  // Editor toolbar
  btn_new_dashboard: "? Nuova dashboard",
  btn_save: "Salva",
  btn_close_editor: "? Chiudi editor",

  // Chat input
  placeholder: "Chiedimi qualsiasi cosa sulla tua casa intelligente? (digita / per i comandi)",
  btn_ask: "Chiedi",

  // Greeting
  greeting: "Ciao! Chiedimi qualsiasi cosa sulla tua casa intelligente ? posso gestire entit?, aree, etichette o aprire automazioni per modificarle.",

  // Explorer banner
  exploring: "Esplorazione della tua casa?",

  // Debug panel
  debug_title: "?? Kyber Debug",
  debug_tab_memory: "?? Memoria",
  debug_tab_last: "?? Ultimo turno",
  debug_tab_status: "?? Stato",
  debug_tab_logs: "?? Log",
  debug_tab_tests: "?? Test",
  debug_loading: "Caricamento?",

  // Memory popover
  memory_popover_header: "?? Richiamato in questo turno",
  memory_popover_empty: "Nessun fatto richiamato.",
  memory_popover_view_all: "Vedi tutto nella scheda Memoria ?",

  // Status / AI
  thinking: "Sto pensando?",
  cancelling: "Annullamento?",
  loading: "Caricamento?",
  copy_title: "Copia",
  copy_failed_title: "Copia non riuscita ? appunti non disponibili",
  retry_btn: "? Riprova",

  // Copy feedback
  copy_done: "?",
  copy_fail: "?",

  // Knowledge tab
  knowledge_empty: "Nessuna conoscenza salvata.",
  knowledge_loading: "Caricamento conoscenza?",

  // Slash commands
  cmd_confirm_execute: "? Esegui",
  cmd_cancel: "Annulla",

  // Restart overlay
  restart_title: "Home Assistant si sta riavviando?",
  restart_subtitle: "Questa pagina verr? ricaricata automaticamente.",
  restart_waiting: "In attesa di Home Assistant?",
  restart_back: "? Home Assistant ? tornato ? ricaricamento?",
  restart_slow: "Sta richiedendo pi? tempo del previsto ? ricarica manualmente.",

  // Update
  update_installing: "? Installazione",
  update_installed: "? Installato",
  update_downloading: "? Download",
  update_updated: "? Aggiornato",

  // Errors
  err_update_failed: "Aggiornamento non riuscito",
  err_force_update_failed: "Aggiornamento forzato non riuscito",
};

// ?? Portuguese (pt) ?????????????????????????????????????????????????????????????
export const PT = {
  // Sidebar / header
  brand: "Assistente Kyber",
  memory_badge_title: "Factos da mem?ria ? clique para pr?-visualizar os factos recordados",
  update_badge: "Atualiza??o",
  autopilot_badge: "? Autopilot",
  btn_clear_history: "Limpar hist?rico",
  btn_debug_title: "Abrir depura??o / inspetor de mem?ria",

  // Editor toolbar
  btn_new_dashboard: "? Novo painel",
  btn_save: "Guardar",
  btn_close_editor: "? Fechar editor",

  // Chat input
  placeholder: "Pergunte-me qualquer coisa sobre a sua casa inteligente? (digite / para comandos)",
  btn_ask: "Perguntar",

  // Greeting
  greeting: "Ol?! Pergunte-me qualquer coisa sobre a sua casa inteligente ? posso gerir entidades, ?reas, etiquetas ou abrir automatiza??es para edi??o.",

  // Explorer banner
  exploring: "A explorar a sua casa?",

  // Debug panel
  debug_title: "?? Kyber Debug",
  debug_tab_memory: "?? Mem?ria",
  debug_tab_last: "?? ?ltima intera??o",
  debug_tab_status: "?? Estado",
  debug_tab_logs: "?? Registos",
  debug_tab_tests: "?? Testes",
  debug_loading: "A carregar?",

  // Memory popover
  memory_popover_header: "?? Recordado neste turno",
  memory_popover_empty: "Nenhum facto recordado.",
  memory_popover_view_all: "Ver tudo no separador Mem?ria ?",

  // Status / AI
  thinking: "A pensar?",
  cancelling: "A cancelar?",
  loading: "A carregar?",
  copy_title: "Copiar",
  copy_failed_title: "Falha ao copiar ? ?rea de transfer?ncia indispon?vel",
  retry_btn: "? Tentar novamente",

  // Copy feedback
  copy_done: "?",
  copy_fail: "?",

  // Knowledge tab
  knowledge_empty: "Ainda n?o h? conhecimento guardado.",
  knowledge_loading: "A carregar conhecimento?",

  // Slash commands
  cmd_confirm_execute: "? Executar",
  cmd_cancel: "Cancelar",

  // Restart overlay
  restart_title: "O Home Assistant est? a reiniciar?",
  restart_subtitle: "Esta p?gina ser? recarregada automaticamente.",
  restart_waiting: "A aguardar o Home Assistant?",
  restart_back: "? O Home Assistant voltou ? a recarregar?",
  restart_slow: "Est? a demorar mais do que o esperado ? recarregue manualmente.",

  // Update
  update_installing: "? A instalar",
  update_installed: "? Instalado",
  update_downloading: "? A transferir",
  update_updated: "? Atualizado",

  // Errors
  err_update_failed: "A atualiza??o falhou",
  err_force_update_failed: "A atualiza??o for?ada falhou",
};

// ?? Polish (pl) ?????????????????????????????????????????????????????????????
export const PL = {
  // Sidebar / header
  brand: "Asystent Kyber",
  memory_badge_title: "Fakty pami?ci ? kliknij, aby podejrze? przywo?ane fakty",
  update_badge: "Aktualizacja",
  autopilot_badge: "? Autopilot",
  btn_clear_history: "Wyczy?? histori?",
  btn_debug_title: "Otw?rz debugowanie / inspektor pami?ci",

  // Editor toolbar
  btn_new_dashboard: "? Nowy pulpit",
  btn_save: "Zapisz",
  btn_close_editor: "? Zamknij edytor",

  // Chat input
  placeholder: "Zapytaj mnie o cokolwiek dotycz?cego Twojego inteligentnego domu? (wpisz /, aby zobaczy? polecenia)",
  btn_ask: "Zapytaj",

  // Greeting
  greeting: "Cze??! Zapytaj mnie o cokolwiek dotycz?cego Twojego inteligentnego domu ? mog? zarz?dza? encjami, obszarami, etykietami albo otwiera? automatyzacje do edycji.",

  // Explorer banner
  exploring: "Poznaj? Tw?j dom?",

  // Debug panel
  debug_title: "?? Kyber Debug",
  debug_tab_memory: "?? Pami??",
  debug_tab_last: "?? Ostatnia tura",
  debug_tab_status: "?? Status",
  debug_tab_logs: "?? Logi",
  debug_tab_tests: "?? Testy",
  debug_loading: "?adowanie?",

  // Memory popover
  memory_popover_header: "?? Przywo?ane w tej turze",
  memory_popover_empty: "Nie przywo?ano ?adnych fakt?w.",
  memory_popover_view_all: "Zobacz wszystko w karcie Pami?? ?",

  // Status / AI
  thinking: "My?l??",
  cancelling: "Anulowanie?",
  loading: "?adowanie?",
  copy_title: "Kopiuj",
  copy_failed_title: "Kopiowanie nie powiod?o si? ? schowek jest niedost?pny",
  retry_btn: "? Spr?buj ponownie",

  // Copy feedback
  copy_done: "?",
  copy_fail: "?",

  // Knowledge tab
  knowledge_empty: "Nie ma jeszcze zapisanej wiedzy.",
  knowledge_loading: "?adowanie wiedzy?",

  // Slash commands
  cmd_confirm_execute: "? Wykonaj",
  cmd_cancel: "Anuluj",

  // Restart overlay
  restart_title: "Home Assistant uruchamia si? ponownie?",
  restart_subtitle: "Ta strona zostanie automatycznie od?wie?ona.",
  restart_waiting: "Oczekiwanie na Home Assistant?",
  restart_back: "? Home Assistant wr?ci? ? od?wie?anie?",
  restart_slow: "Trwa to d?u?ej ni? oczekiwano ? od?wie? r?cznie.",

  // Update
  update_installing: "? Instalowanie",
  update_installed: "? Zainstalowano",
  update_downloading: "? Pobieranie",
  update_updated: "? Zaktualizowano",

  // Errors
  err_update_failed: "Aktualizacja nie powiod?a si?",
  err_force_update_failed: "Wymuszona aktualizacja nie powiod?a si?",
};

// ?? Hungarian (hu) ?????????????????????????????????????????????????????????????
export const HU = {
  // Sidebar / header
  brand: "Kyber Asszisztens",
  memory_badge_title: "Mem?riaadatok ? kattintson a felid?zett t?nyek el?n?zet?hez",
  update_badge: "Friss?t?s",
  autopilot_badge: "? Autopilot",
  btn_clear_history: "El?zm?nyek t?rl?se",
  btn_debug_title: "Hibakeres?s / mem?riaellen?rz? megnyit?sa",

  // Editor toolbar
  btn_new_dashboard: "? ?j ir?ny?t?pult",
  btn_save: "Ment?s",
  btn_close_editor: "? Szerkeszt? bez?r?sa",

  // Chat input
  placeholder: "K?rdezz b?rmit az okosotthonodr?l? (parancsokhoz ?rj / jelet)",
  btn_ask: "K?rdez?s",

  // Greeting
  greeting: "Szia! K?rdezz b?rmit az okosotthonodr?l ? kezelhetek entit?sokat, ter?leteket, c?mk?ket, vagy megnyithatok automatiz?l?sokat szerkeszt?sre.",

  // Explorer banner
  exploring: "Otthonod felt?rk?pez?se?",

  // Debug panel
  debug_title: "?? Kyber Debug",
  debug_tab_memory: "?? Mem?ria",
  debug_tab_last: "?? Utols? k?r",
  debug_tab_status: "?? ?llapot",
  debug_tab_logs: "?? Napl?k",
  debug_tab_tests: "?? Tesztek",
  debug_loading: "Bet?lt?s?",

  // Memory popover
  memory_popover_header: "?? Ebben a k?rben felid?zve",
  memory_popover_empty: "Nem lett felid?zve t?ny.",
  memory_popover_view_all: "?sszes megtekint?se a Mem?ria lapon ?",

  // Status / AI
  thinking: "Gondolkodom?",
  cancelling: "Megszak?t?s?",
  loading: "Bet?lt?s?",
  copy_title: "M?sol?s",
  copy_failed_title: "A m?sol?s sikertelen ? a v?g?lap nem ?rhet? el",
  retry_btn: "? ?jra",

  // Copy feedback
  copy_done: "?",
  copy_fail: "?",

  // Knowledge tab
  knowledge_empty: "M?g nincs mentett tud?s.",
  knowledge_loading: "Tud?s bet?lt?se?",

  // Slash commands
  cmd_confirm_execute: "? V?grehajt?s",
  cmd_cancel: "M?gse",

  // Restart overlay
  restart_title: "A Home Assistant ?jraindul?",
  restart_subtitle: "Ez az oldal automatikusan ?jrat?lt?dik.",
  restart_waiting: "V?rakoz?s a Home Assistantre?",
  restart_back: "? A Home Assistant visszat?rt ? ?jrat?lt?s?",
  restart_slow: "A v?rtn?l tov?bb tart ? t?ltsd ?jra k?zzel.",

  // Update
  update_installing: "? Telep?t?s",
  update_installed: "? Telep?tve",
  update_downloading: "? Let?lt?s",
  update_updated: "? Friss?tve",

  // Errors
  err_update_failed: "A friss?t?s sikertelen",
  err_force_update_failed: "A k?nyszer?tett friss?t?s sikertelen",
};

// ?? Swedish (sv) ?????????????????????????????????????????????????????????????
export const SV = {
  // Sidebar / header
  brand: "Kyber Assistent",
  memory_badge_title: "Minnesfakta ? klicka f?r att f?rhandsgranska ?terkallade fakta",
  update_badge: "Uppdatering",
  autopilot_badge: "? Autopilot",
  btn_clear_history: "Rensa historik",
  btn_debug_title: "?ppna fels?kning / minnesinspekt?r",

  // Editor toolbar
  btn_new_dashboard: "? Ny instrumentpanel",
  btn_save: "Spara",
  btn_close_editor: "? St?ng redigeraren",

  // Chat input
  placeholder: "Fr?ga mig vad som helst om ditt smarta hem? (skriv / f?r kommandon)",
  btn_ask: "Fr?ga",

  // Greeting
  greeting: "Hej! Fr?ga mig vad som helst om ditt smarta hem ? jag kan hantera entiteter, omr?den, etiketter eller ?ppna automationer f?r redigering.",

  // Explorer banner
  exploring: "Utforskar ditt hem?",

  // Debug panel
  debug_title: "?? Kyber Debug",
  debug_tab_memory: "?? Minne",
  debug_tab_last: "?? Senaste omg?ngen",
  debug_tab_status: "?? Status",
  debug_tab_logs: "?? Loggar",
  debug_tab_tests: "?? Tester",
  debug_loading: "Laddar?",

  // Memory popover
  memory_popover_header: "?? ?terkallat i denna omg?ng",
  memory_popover_empty: "Inga fakta ?terkallades.",
  memory_popover_view_all: "Visa allt i fliken Minne ?",

  // Status / AI
  thinking: "T?nker?",
  cancelling: "Avbryter?",
  loading: "Laddar?",
  copy_title: "Kopiera",
  copy_failed_title: "Kopiering misslyckades ? urklipp ej tillg?ngligt",
  retry_btn: "? F?rs?k igen",

  // Copy feedback
  copy_done: "?",
  copy_fail: "?",

  // Knowledge tab
  knowledge_empty: "Ingen sparad kunskap ?nnu.",
  knowledge_loading: "Laddar kunskap?",

  // Slash commands
  cmd_confirm_execute: "? K?r",
  cmd_cancel: "Avbryt",

  // Restart overlay
  restart_title: "Home Assistant startar om?",
  restart_subtitle: "Den h?r sidan laddas om automatiskt.",
  restart_waiting: "V?ntar p? Home Assistant?",
  restart_back: "? Home Assistant ?r tillbaka ? laddar om?",
  restart_slow: "Det tar l?ngre tid ?n v?ntat ? ladda om manuellt.",

  // Update
  update_installing: "? Installerar",
  update_installed: "? Installerad",
  update_downloading: "? Laddar ner",
  update_updated: "? Uppdaterad",

  // Errors
  err_update_failed: "Uppdateringen misslyckades",
  err_force_update_failed: "Tvingad uppdatering misslyckades",
};

// ?? Russian (ru) ?????????????????????????????????????????????????????????????
export const RU = {
  // Sidebar / header
  brand: "????????? Kyber",
  memory_badge_title: "????? ?????? ? ???????, ????? ??????????? ????????? ?????",
  update_badge: "??????????",
  autopilot_badge: "? Autopilot",
  btn_clear_history: "???????? ???????",
  btn_debug_title: "??????? ??????? / ????????? ??????",

  // Editor toolbar
  btn_new_dashboard: "? ????? ??????",
  btn_save: "?????????",
  btn_close_editor: "? ??????? ????????",

  // Chat input
  placeholder: "???????? ???? ? ??? ?????? ? ????? ????? ????? (??????? / ??? ??????)",
  btn_ask: "????????",

  // Greeting
  greeting: "??????! ???????? ???? ? ??? ?????? ? ????? ????? ???? ? ? ???? ????????? ??????????, ?????????, ??????? ??? ????????? ????????????? ??? ??????????????.",

  // Explorer banner
  exploring: "?????? ??? ????",

  // Debug panel
  debug_title: "?? Kyber Debug",
  debug_tab_memory: "?? ??????",
  debug_tab_last: "?? ????????? ???",
  debug_tab_status: "?? ??????",
  debug_tab_logs: "?? ???????",
  debug_tab_tests: "?? ?????",
  debug_loading: "?????????",

  // Memory popover
  memory_popover_header: "?? ????????? ? ???? ????",
  memory_popover_empty: "????? ?? ???? ???????.",
  memory_popover_view_all: "???????? ??? ?? ??????? ???????? ?",

  // Status / AI
  thinking: "??????",
  cancelling: "???????",
  loading: "?????????",
  copy_title: "??????????",
  copy_failed_title: "?? ??????? ??????????? ? ????? ?????? ??????????",
  retry_btn: "? ?????????",

  // Copy feedback
  copy_done: "?",
  copy_fail: "?",

  // Knowledge tab
  knowledge_empty: "??????????? ?????? ???? ???.",
  knowledge_loading: "???????? ???????",

  // Slash commands
  cmd_confirm_execute: "? ?????????",
  cmd_cancel: "??????",

  // Restart overlay
  restart_title: "Home Assistant ????????????????",
  restart_subtitle: "??? ???????? ????????????? ??????????????.",
  restart_waiting: "???????? Home Assistant?",
  restart_back: "? Home Assistant ????? ???????? ? ?????????????",
  restart_slow: "??? ???????? ?????? ???????, ??? ????????? ? ????????????? ???????? ???????.",

  // Update
  update_installing: "? ?????????",
  update_installed: "? ???????????",
  update_downloading: "? ????????",
  update_updated: "? ?????????",

  // Errors
  err_update_failed: "?? ??????? ????????? ??????????",
  err_force_update_failed: "?????????????? ?????????? ?? ???????",
};

// ?? Chinese Simplified (zh) ?????????????????????????????????????????????????????????????
export const ZH = {
  // Sidebar / header
  brand: "Kyber ??",
  memory_badge_title: "???? ? ???????????",
  update_badge: "??",
  autopilot_badge: "? Autopilot",
  btn_clear_history: "??????",
  btn_debug_title: "???? / ?????",

  // Editor toolbar
  btn_new_dashboard: "? ?????",
  btn_save: "??",
  btn_close_editor: "? ?????",

  // Chat input
  placeholder: "???????????????????? / ?????",
  btn_ask: "??",

  // Greeting
  greeting: "??????????????????????????????????????????????",

  // Explorer banner
  exploring: "????????",

  // Debug panel
  debug_title: "?? Kyber ??",
  debug_tab_memory: "?? ??",
  debug_tab_last: "?? ???",
  debug_tab_status: "?? ??",
  debug_tab_logs: "?? ??",
  debug_tab_tests: "?? ??",
  debug_loading: "????",

  // Memory popover
  memory_popover_header: "?? ????",
  memory_popover_empty: "?????????",
  memory_popover_view_all: "???????????? ?",

  // Status / AI
  thinking: "????",
  cancelling: "????",
  loading: "????",
  copy_title: "??",
  copy_failed_title: "???? ? ??????",
  retry_btn: "? ??",

  // Copy feedback
  copy_done: "?",
  copy_fail: "?",

  // Knowledge tab
  knowledge_empty: "????????",
  knowledge_loading: "???????",

  // Slash commands
  cmd_confirm_execute: "? ??",
  cmd_cancel: "??",

  // Restart overlay
  restart_title: "Home Assistant ?????",
  restart_subtitle: "???????????",
  restart_waiting: "???? Home Assistant?",
  restart_back: "? Home Assistant ??? ? ???????",
  restart_slow: "?????? ? ????????",

  // Update
  update_installing: "? ???",
  update_installed: "? ???",
  update_downloading: "? ???",
  update_updated: "? ???",

  // Errors
  err_update_failed: "????",
  err_force_update_failed: "??????",
};

// ?? Locale registry ??????????????????????????????????????????????????????????
const LOCALES = { en: EN, nl: NL, de: DE, fr: FR, es: ES, it: IT, pt: PT, pl: PL, hu: HU, sv: SV, ru: RU, zh: ZH };

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
