/**
 * Kyber — AI-powered Smart Home Assistant Panel
 *
 * A Home Assistant custom panel web component that provides:
 *   - Automation selector (loads from HA state machine)
 *   - CodeMirror 6 YAML editor with HA automation YAML
 *   - AI chat sidebar powered by the kyber backend
 *   - Apply suggestion and Save to HA buttons
 */

import {
  EditorState,
  EditorView,
  keymap,
  lineNumbers,
  highlightActiveLine,
  drawSelection,
  history,
  historyKeymap,
  defaultKeymap,
  indentWithTab,
  yaml,
  oneDark,
  syntaxHighlighting,
  defaultHighlightStyle,
  bracketMatching,
  foldGutter,
  autocompletion,
  closeBrackets,
} from "./codemirror-bundle.js";

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------
import { STYLES } from "./src/styles.js?v=82";

import { UtilsMixin } from "./src/utils-mixin.js?v=82";
import { SessionMixin } from "./src/session-mixin.js?v=82";
import { KnowledgeMixin } from "./src/knowledge-mixin.js?v=82";
import { DebugMixin } from "./src/debug-mixin.js?v=82";
import { SlashMixin } from "./src/slash-commands-mixin.js?v=82";
import { EditorMixin } from "./src/editor-mixin.js?v=82";
import { AIMixin } from "./src/ai-mixin.js?v=82";
import { PlanCardsMixin } from "./src/plan-cards-mixin.js?v=82";

// ---------------------------------------------------------------------------
// Custom Element
// ---------------------------------------------------------------------------
class KyberPanel extends AIMixin(PlanCardsMixin(SlashMixin(EditorMixin(DebugMixin(KnowledgeMixin(SessionMixin(UtilsMixin(HTMLElement)))))))) {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._editor = null;
    this._currentAutomationId = null;
    this._dirty = false;
    this._chatHistory = [];
    this._compactedSummary = "";
    // Keep last 5 messages verbatim; compact when total exceeds 7
    this._HISTORY_WINDOW = 5;
    this._COMPACT_TRIGGER = 7;
    // Autocomplete state
    this._acItems = [];
    this._acIndex = -1;
    this._acToken = "";
    // Input history navigation (like a shell: Up/Down when no autocomplete)
    this._historyNav = -1; // -1 = not browsing
    this._historyDraft = ""; // saves the current draft when browsing starts
    // Autopilot mode — auto-executes proposals without user clicking Execute
    this._autopilot = false;
    // Editor mode: "automation" | "dashboard"
    this._editorMode = "automation";
    // Cached list of dashboards [{title, url_path, mode}] — fetched lazily
    this._dashboardList = null;
    // Cached list of custom Lovelace resource URLs — fetched lazily
    this._lovelaceResources = undefined;
    this._historyRestored = false;
    this._DEFAULT_GREETING = "Hi! Ask me anything about your smart home — I can manage entities, areas, labels, or open automations for editing.";
  }

  // HA sets this property when hass state changes
  set hass(hass) {
    this._hass = hass;
    if (!this._rendered) {
      this._render();
    } else if (!this._historyRestored) {
      this._restorePersistedHistory();
    }
  }

  set panel(panel) {
    // HA passes panel.config when registering via panel_custom.
    this._panelConfig = panel?.config || {};
    this._mode = this._panelConfig.mode || "chat";
  }

  connectedCallback() {
    // Block keyboard events at the shadow host so HA's global shortcuts don't fire while typing
    const stopKey = (e) => {
      console.log("[CopilotAssist] stopKey fired for", e.key, "stopping propagation");
      e.stopPropagation();
    };
    this.addEventListener("keydown", stopKey);
    this.addEventListener("keyup", stopKey);
    this.addEventListener("keypress", stopKey);
    // Mode is also derivable from URL path so it works even when set panel runs late
    if (!this._mode) {
      try {
        const path = window.location?.pathname || "";
        this._mode = path.startsWith("/kyber-debug") ? "debug" : "chat";
      } catch (e) { this._mode = "chat"; }
    }
    console.log("[CopilotAssist] connectedCallback - mode:", this._mode);
    if (!this._rendered) {
      this._render();
    } else if (this._mode === "debug") {
      // HA reuses panel elements across navigation — re-fetch live backend data
      // so memory/last-turn/status are always fresh when the user arrives.
      this._renderDebugTab(this._debugTab || "memory");
    }
  }

  _render() {
    this._rendered = true;
    const shadow = this.shadowRoot;

    const style = document.createElement("style");
    style.textContent = STYLES;
    shadow.appendChild(style);

    shadow.innerHTML += `
      <div class="container" id="app-container">
        <div class="toolbar">
          <h2 class="brand-title">
            <img id="kyber-header-icon" class="brand-icon" src="/local/kyber/icon.png" alt="Kyber icon">
            <span>Kyber</span>
          </h2>
          <span class="editor-context-label editor-controls" id="editor-context-label"></span>
          <span class="editor-title editor-controls" id="editor-title">
            <select id="dashboard-select" class="dashboard-select" style="display:none"></select>
            <button class="btn-new-dashboard editor-controls" id="btn-new-dashboard" style="display:none" title="Create a new dashboard">＋ New dashboard</button>
          </span>
          <button class="btn-save editor-controls" id="btn-save" disabled>Save</button>
          <button class="btn-close-editor editor-controls" id="btn-close-editor">✕ Close editor</button>
        </div>
        <div class="chat-pane">
          <div class="sidebar-brand">
            <img id="kyber-sidebar-icon" class="brand-icon" src="/local/kyber/icon.png" alt="Kyber icon">
            <span>Kyber Assistant</span>
            <span class="session-label" id="session-indicator"></span>
            <span class="context-badge" id="context-badge" title="Entities and automations loaded into AI context"></span>
            <button class="btn-clear-history" id="btn-clear-history" title="Clear persisted chat history">Clear history</button>
            <button class="btn-debug" id="btn-debug" title="Open debug / memory inspector">🐞</button>
          </div>
          <div class="chat-history" id="chat-history">
            <div class="chat-message assistant">${this._DEFAULT_GREETING}</div>
          </div>
          <div class="chat-input-area" style="position:relative;">
            <div class="autocomplete-list" id="ac-list"></div>
            <textarea id="prompt-input" placeholder="Ask me anything about your smart home… (type / for commands)" rows="3"></textarea>
            <button class="btn-ask" id="btn-ask">Ask</button>
          </div>
        </div>
        <div class="debug-pane" id="debug-pane" hidden>
          <div class="debug-header">
            <strong>🐞 Kyber Debug</strong>
            <nav class="debug-tabs">
              <button class="debug-tab active" data-debug-tab="memory">🧠 Memory</button>
              <button class="debug-tab" data-debug-tab="last_turn">📥 Last turn</button>
              <button class="debug-tab" data-debug-tab="status">⚙️ Status</button>
            </nav>
            <button class="btn-debug-refresh" id="btn-debug-refresh" title="Refresh">↻</button>
            <button class="btn-debug-close" id="btn-debug-close" title="Back to chat">✕</button>
          </div>
          <div class="debug-body" id="debug-body"><em>Loading…</em></div>
        </div>
        <div class="editor-pane" id="editor-container"></div>
        <div class="status-bar" id="status-bar">
          <span class="autopilot-badge" id="autopilot-badge">⚡ Autopilot ON</span>
          <span id="status-text"></span>
        </div>
      </div>
    `;

    this._bindEvents(shadow);
    this._restorePersistedHistory();
    this._applyModeAndDebugFlag();
  }

  async _applyModeAndDebugFlag() {
    const shadow = this.shadowRoot;

    // Apply debug layout SYNCHRONOUSLY before any async work to avoid flash
    if (this._mode === "debug") {
      const chat = shadow.querySelector(".chat-pane");
      const pane = shadow.getElementById("debug-pane");
      if (chat) chat.style.display = "none";
      if (pane) {
        pane.removeAttribute("hidden");
        pane.classList.add("debug-pane--standalone");
        const closeBtn = shadow.getElementById("btn-debug-close");
        if (closeBtn) closeBtn.style.display = "none";
      }
      this._debugTab = this._debugTab || "memory";
    }

    // Fetch debug-mode flag from backend (async — layout already applied above)
    let debugEnabled = true; // default until we know
    try {
      const token = this._hass?.auth?.data?.access_token;
      if (token) {
        const resp = await fetch("/api/kyber/debug/mode", { headers: { Authorization: `Bearer ${token}` } });
        if (resp.ok) {
          const data = await resp.json();
          debugEnabled = !!data.enabled;
        }
      }
    } catch (e) { /* keep default */ }
    this._debugEnabled = debugEnabled;
    const btnDebug = shadow.getElementById("btn-debug");
    if (btnDebug) btnDebug.style.display = debugEnabled ? "" : "none";

    // Now render debug tab content (needs hass + debug flag confirmed)
    if (this._mode === "debug") {
      this._renderDebugTab(this._debugTab);
    }
  }


  _bindEvents(shadow) {
    shadow.getElementById("btn-save").addEventListener("click", () => {
      if (this._editorMode === "dashboard") {
        this._saveDashboard();
      } else {
        this._saveAutomation();
      }
    });

    shadow.getElementById("btn-close-editor").addEventListener("click", () => {
      this._closeEditor();
    });

    shadow.getElementById("btn-new-dashboard").addEventListener("click", () => {
      this._createNewDashboard();
    });

    shadow.getElementById("dashboard-select").addEventListener("change", (e) => {
      const urlPath = e.target.value === "__default__" ? null : e.target.value;
      const label = e.target.options[e.target.selectedIndex]?.textContent || "";
      this._setEditorContextLabel("dashboard", label);
      this._loadDashboard(urlPath);
    });

    shadow.getElementById("btn-ask").addEventListener("click", () => {
      this._askAI();
    });
    shadow.getElementById("btn-clear-history").addEventListener("click", () => {
      this._clearHistory();
    });
    shadow.getElementById("btn-debug").addEventListener("click", () => {
      // Always navigate to the dedicated debug page so the chat panel stays clean.
      if (this._mode === "debug") return;
      try {
        window.history.pushState({}, "", "/kyber-debug");
        window.dispatchEvent(new PopStateEvent("popstate"));
      } catch (e) {
        window.location.href = "/kyber-debug";
      }
    });
    shadow.getElementById("btn-debug-close").addEventListener("click", () => this._toggleDebugPane(false));
    shadow.getElementById("btn-debug-refresh").addEventListener("click", () => this._renderDebugTab(this._debugTab || "memory"));
    shadow.querySelectorAll(".debug-tab").forEach((b) => {
      b.addEventListener("click", () => {
        shadow.querySelectorAll(".debug-tab").forEach((x) => x.classList.remove("active"));
        b.classList.add("active");
        this._renderDebugTab(b.getAttribute("data-debug-tab"));
      });
    });

    shadow.getElementById("prompt-input").addEventListener("keydown", (e) => {
      e.stopPropagation();
      // Route arrow keys + Enter/Escape to autocomplete when list is open
      if (this._acItems.length > 0) {
        if (e.key === "ArrowDown") {
          e.preventDefault();
          this._acIndex = Math.min(this._acIndex + 1, this._acItems.length - 1);
          this._updateAcActive();
          return;
        }
        if (e.key === "ArrowUp") {
          e.preventDefault();
          this._acIndex = Math.max(this._acIndex - 1, 0);
          this._updateAcActive();
          return;
        }
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          if (this._acIndex >= 0) {
            const item = this._acItems[this._acIndex];
            const list = this.shadowRoot.getElementById("ac-list");
            const el = list?.querySelector(`[data-idx="${this._acIndex}"]`);
            this._applyAcItem(item.entity_id, el?.dataset.replaceAll === "true");
          } else {
            this._closeAc();
            this._askAI();
          }
          return;
        }
        if (e.key === "Escape") {
          e.preventDefault();
          this._closeAc();
          return;
        }
        if (e.key === "Tab") {
          e.preventDefault();
          const idx = this._acIndex >= 0 ? this._acIndex : 0;
          const item = this._acItems[idx];
          const list = this.shadowRoot.getElementById("ac-list");
          const el = list?.querySelector(`[data-idx="${idx}"]`);
          this._applyAcItem(item.entity_id, el?.dataset.replaceAll === "true");
          return;
        }
      }
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        this._historyNav = -1;
        this._historyDraft = "";
        this._askAI();
      }

      // ── Shell-style input history (Up/Down when no autocomplete) ──────
      if (e.key === "ArrowUp" || e.key === "ArrowDown") {
        const userMsgs = this._chatHistory
          .filter((m) => m.role === "user")
          .map((m) => m.content);
        if (userMsgs.length === 0) return;

        const textarea = this.shadowRoot.getElementById("prompt-input");

        if (e.key === "ArrowUp") {
          e.preventDefault();
          if (this._historyNav === -1) {
            // Save current draft and start at most recent
            this._historyDraft = textarea.value;
            this._historyNav = userMsgs.length - 1;
          } else {
            this._historyNav = Math.max(0, this._historyNav - 1);
          }
          textarea.value = userMsgs[this._historyNav];
          textarea.setSelectionRange(textarea.value.length, textarea.value.length);
        } else {
          e.preventDefault();
          if (this._historyNav === -1) return;
          if (this._historyNav >= userMsgs.length - 1) {
            // Reached the end — restore draft
            this._historyNav = -1;
            textarea.value = this._historyDraft;
            this._historyDraft = "";
          } else {
            this._historyNav += 1;
            textarea.value = userMsgs[this._historyNav];
          }
          textarea.setSelectionRange(textarea.value.length, textarea.value.length);
        }
      }
    });

    shadow.getElementById("prompt-input").addEventListener("input", (e) => {
      this._historyNav = -1; // typing breaks history browsing
      this._onPromptInput(e.target);
    });

    shadow.getElementById("prompt-input").addEventListener("keyup", (e) => e.stopPropagation());
    shadow.getElementById("prompt-input").addEventListener("keypress", (e) => e.stopPropagation());

    // Close autocomplete when clicking outside
    shadow.addEventListener("mousedown", (e) => {
      const list = this.shadowRoot.getElementById("ac-list");
      if (list && !list.contains(e.target) && e.target.id !== "prompt-input") {
        this._closeAc();
      }
    });
  }

}

if (!customElements.get("kyber-panel")) {
  customElements.define("kyber-panel", KyberPanel);
}