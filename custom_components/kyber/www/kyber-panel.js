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
const STYLES = `
  :host {
    display: block;
    height: 100%;
    font-family: var(--paper-font-body1_-_font-family, sans-serif);
    --panel-bg: var(--primary-background-color, #1c1c1e);
    --sidebar-bg: var(--secondary-background-color, #2c2c2e);
    --border-color: var(--divider-color, #3a3a3c);
    --text-color: var(--primary-text-color, #f5f5f5);
    --accent: var(--primary-color, #03a9f4);
    --danger: var(--error-color, #cf6679);
    --success: var(--success-color, #4caf50);
  }

  .container {
    display: grid;
    grid-template-rows: 56px 1fr;
    grid-template-columns: 1fr;
    height: 100%;
    background: var(--panel-bg);
    color: var(--text-color);
  }

  .container.editor-open {
    grid-template-columns: 1fr 1fr;
  }

  .toolbar {
    grid-column: 1 / -1;
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 0 16px;
    border-bottom: 1px solid var(--border-color);
    background: var(--sidebar-bg);
  }

  .toolbar h2 {
    margin: 0;
    font-size: 18px;
    font-weight: 500;
    flex: 0 0 auto;
  }

  .brand-title {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .brand-icon {
    width: 20px;
    height: 20px;
    border-radius: 4px;
  }

  .toolbar select {
    flex: 1;
    max-width: 400px;
    height: 32px;
    background: var(--panel-bg);
    color: var(--text-color);
    border: 1px solid var(--border-color);
    border-radius: 4px;
    padding: 0 8px;
    font-size: 14px;
  }

  .toolbar button {
    padding: 6px 16px;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-size: 14px;
    font-weight: 500;
  }

  .btn-save {
    background: var(--accent);
    color: white;
  }

  .btn-save:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .editor-pane {
    overflow: hidden;
    display: none;
    flex-direction: column;
    border-left: 1px solid var(--border-color);
  }

  .editor-pane.open {
    display: flex;
  }

  .editor-pane .cm-editor {
    height: 100%;
    font-size: 13px;
  }

  .chat-pane {
    display: flex;
    flex-direction: column;
    background: var(--panel-bg);
    overflow: hidden;
  }

  .sidebar-brand {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 12px;
    border-bottom: 1px solid var(--border-color);
    background: var(--sidebar-bg);
    font-size: 13px;
    font-weight: 600;
  }

  .chat-history {
    flex: 1;
    overflow-y: auto;
    padding: 12px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .chat-message {
    border-radius: 8px;
    padding: 10px 12px;
    font-size: 13px;
    line-height: 1.5;
    white-space: pre-wrap;
    word-break: break-word;
  }

  .chat-message.user {
    background: var(--accent);
    color: white;
    align-self: flex-end;
    max-width: 90%;
  }

  .chat-message.assistant {
    background: var(--panel-bg);
    border: 1px solid var(--border-color);
    align-self: flex-start;
    max-width: 100%;
  }

  .chat-message.error {
    background: var(--danger);
    color: white;
  }

  .suggestion-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 6px;
    align-self: flex-start;
    max-width: 85%;
  }
  .suggestion-chip {
    background: transparent;
    border: 1px solid var(--accent);
    color: var(--accent);
    border-radius: 16px;
    padding: 4px 12px;
    font-size: 12px;
    cursor: pointer;
    white-space: nowrap;
    transition: background 0.15s;
  }
  .suggestion-chip:hover {
    background: color-mix(in srgb, var(--accent) 15%, transparent);
  }

  /* Inline adornment buttons — rendered in-place inside the AI message text */
  .inline-choice {
    display: inline;
    background: color-mix(in srgb, var(--accent) 9%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent) 40%, transparent);
    color: var(--accent);
    border-radius: 4px;
    padding: 1px 8px;
    font-size: inherit;
    font-weight: 600;
    cursor: pointer;
    line-height: 1.8;
    white-space: nowrap;
    transition: background 0.15s, border-color 0.15s;
  }
  .inline-choice:hover {
    background: color-mix(in srgb, var(--accent) 22%, transparent);
    border-color: var(--accent);
  }
  .inline-choice.used {
    opacity: 0.4;
    cursor: default;
    pointer-events: none;
  }

  .yaml-suggestion {
    background: #1e2a1e;
    border: 1px solid var(--success);
    border-radius: 6px;
    margin-top: 6px;
    overflow: hidden;
  }

  .yaml-suggestion pre {
    margin: 0;
    padding: 8px;
    font-size: 12px;
    overflow-x: auto;
    color: #a8d8a8;
    font-family: monospace;
  }

  .yaml-suggestion button {
    width: 100%;
    padding: 6px;
    background: var(--success);
    color: white;
    border: none;
    cursor: pointer;
    font-size: 12px;
    font-weight: 600;
  }

  .yaml-suggestion button:hover {
    opacity: 0.9;
  }

  .plan-card {
    background: var(--sidebar-bg);
    border: 1px solid var(--accent);
    border-radius: 8px;
    padding: 12px;
    margin: 8px 0;
    font-size: 13px;
  }

  .plan-header {
    font-weight: 600;
    font-size: 14px;
    margin-bottom: 8px;
    color: var(--accent);
  }

  .plan-actions {
    margin: 0 0 8px 0;
    padding-left: 18px;
    line-height: 1.7;
  }

  .plan-from { color: var(--danger); text-decoration: line-through; }
  .plan-to   { color: var(--success); font-weight: 600; }

  .plan-warning {
    color: var(--warning-color, #ff9800);
    font-size: 12px;
    margin-bottom: 6px;
  }

  .plan-warning-error {
    color: var(--danger);
    background: color-mix(in srgb, var(--danger) 10%, transparent);
    border: 1px solid var(--danger);
    border-radius: 4px;
    padding: 6px 10px;
    margin-bottom: 8px;
  }

  .entity-missing {
    color: var(--danger);
    border-color: var(--danger);
  }

  .row-invalid {
    opacity: 0.55;
  }

  .plan-overview {
    background: color-mix(in srgb, var(--accent) 10%, transparent);
    border-left: 3px solid var(--accent);
    padding: 10px 12px;
    border-radius: 4px;
    margin-bottom: 10px;
  }

  .plan-overview-label {
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--accent);
    margin-bottom: 4px;
  }

  .plan-overview-summary {
    font-size: 14px;
    font-weight: 500;
  }

  .plan-changes-header {
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--secondary-text-color, #aaa);
    margin-bottom: 6px;
  }

  .plan-changes {
    list-style: none;
    margin: 0 0 10px 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .change-row {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 12px;
    flex-wrap: wrap;
  }

  .change-entity {
    font-family: monospace;
    font-size: 11px;
    background: var(--panel-bg);
    padding: 2px 5px;
    border-radius: 3px;
    border: 1px solid var(--border-color);
  }

  .change-type-badge {
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    background: var(--accent);
    color: white;
    padding: 1px 5px;
    border-radius: 3px;
  }

  .change-delta { flex: 1; }

  .btn-execute {
    width: 100%;
    padding: 10px;
    background: var(--success);
    color: white;
    border: none;
    border-radius: 6px;
    cursor: pointer;
    font-size: 14px;
    font-weight: 700;
    margin-top: 4px;
  }

  .btn-execute:hover { filter: brightness(1.1); }
  .btn-execute:disabled { opacity: 0.5; cursor: default; filter: none; }

  .btn-undo {
    margin-top: 6px;
    background: transparent;
    border: 1px solid var(--warning-color, #ff9800);
    color: var(--warning-color, #ff9800);
    border-radius: 4px;
    padding: 4px 12px;
    font-size: 12px;
    cursor: pointer;
    font-weight: 600;
  }
  .btn-undo:hover { background: color-mix(in srgb, var(--warning-color, #ff9800) 15%, transparent); }
  .btn-undo:disabled { opacity: 0.4; cursor: default; }

  .plan-result {
    margin-top: 8px;
    font-size: 13px;
    font-style: italic;
  }

  .plan-result.success { color: var(--success); }
  .plan-result.error   { color: var(--danger); }

  .open-editor-prompt {
    background: color-mix(in srgb, var(--accent) 8%, var(--panel-bg));
    border: 1px solid var(--accent);
    border-radius: 8px;
    padding: 12px;
    margin: 4px 0;
  }

  .open-editor-summary {
    font-size: 13px;
    margin-bottom: 10px;
    line-height: 1.4;
  }

  .btn-open-editor {
    width: 100%;
    padding: 8px;
    background: var(--accent);
    color: white;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-size: 13px;
    font-weight: 600;
  }

  .btn-open-editor:hover { filter: brightness(1.1); }
  .btn-open-editor:disabled { opacity: 0.6; cursor: default; filter: none; }

  /* ── Command accept card ──────────────────────────────────────── */
  .command-card {
    background: color-mix(in srgb, var(--accent) 6%, var(--panel-bg));
    border: 1px solid var(--border-color);
    border-radius: 8px;
    padding: 12px;
    margin: 4px 0;
  }
  .command-card.danger { border-color: var(--danger, #e53935); }
  .command-card-title { font-size: 14px; font-weight: 600; margin-bottom: 4px; }
  .command-card-detail {
    font-size: 12px; color: var(--secondary-text-color, #888); margin-bottom: 10px;
    font-family: monospace;
  }
  .command-card-warning {
    font-size: 12px; color: var(--danger, #e53935); margin-bottom: 10px;
  }
  .command-card-actions { display: flex; gap: 8px; }
  .btn-cmd-execute {
    flex: 1; padding: 7px 12px; background: var(--accent); color: white;
    border: none; border-radius: 4px; cursor: pointer; font-size: 13px; font-weight: 600;
  }
  .btn-cmd-execute.danger { background: var(--danger, #e53935); }
  .btn-cmd-execute:disabled { opacity: 0.5; cursor: default; }
  .btn-cmd-cancel {
    padding: 7px 12px; background: transparent; color: var(--secondary-text-color, #888);
    border: 1px solid var(--border-color); border-radius: 4px; cursor: pointer; font-size: 13px;
  }
  .btn-cmd-cancel:hover { background: var(--border-color); }

  .editor-controls { display: none; }

  .editor-context-label {
    flex: 0 0 auto;
    font-size: 14px;
    font-weight: 400;
    color: var(--secondary-text-color, #aaa);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 220px;
  }

  .editor-title {
    flex: 1;
    font-size: 14px;
    font-weight: 500;
    color: var(--secondary-text-color, #aaa);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .dashboard-select {
    background: var(--panel-bg);
    color: var(--primary-text-color);
    border: 1px solid var(--border-color);
    border-radius: 4px;
    padding: 3px 8px;
    font-size: 13px;
    cursor: pointer;
    max-width: 220px;
  }
  .dashboard-select:focus { outline: 1px solid var(--accent); }

  .btn-new-dashboard {
    background: transparent;
    color: var(--accent);
    border: 1px dashed var(--accent);
    padding: 3px 10px;
    border-radius: 4px;
    font-size: 12px;
    cursor: pointer;
    white-space: nowrap;
  }
  .btn-new-dashboard:hover { background: color-mix(in srgb, var(--accent) 15%, transparent); }

  .btn-close-editor {
    background: transparent;
    color: var(--secondary-text-color, #aaa);
    border: 1px solid var(--border-color);
    padding: 5px 12px;
    border-radius: 4px;
    cursor: pointer;
    font-size: 13px;
  }

  .btn-close-editor:hover { background: var(--border-color); }

  .chat-input-area {
    flex: 0 0 auto;
    padding: 10px;
    border-top: 1px solid var(--border-color);
    display: flex;
    gap: 8px;
  }

  .chat-input-area textarea {
    flex: 1;
    resize: none;
    height: 64px;
    background: var(--panel-bg);
    color: var(--text-color);
    border: 1px solid var(--border-color);
    border-radius: 4px;
    padding: 8px;
    font-size: 13px;
    font-family: inherit;
  }

  .chat-input-area textarea:focus {
    outline: none;
    border-color: var(--accent);
  }

  .btn-ask {
    background: var(--accent);
    color: white;
    align-self: flex-end;
    height: 36px;
    padding: 0 16px;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-size: 13px;
    font-weight: 600;
  }

  .btn-ask:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .btn-clear-history {
    background: transparent;
    color: var(--secondary-text-color, #aaa);
    align-self: flex-end;
    height: 36px;
    padding: 0 12px;
    border: 1px solid var(--border-color);
    border-radius: 4px;
    cursor: pointer;
    font-size: 12px;
    font-weight: 600;
  }

  .btn-clear-history:hover {
    background: var(--border-color);
  }

  .status-bar {
    font-size: 12px;
    padding: 4px 16px;
    grid-column: 1 / -1;
    background: var(--sidebar-bg);
    border-top: 1px solid var(--border-color);
    color: var(--secondary-text-color, #aaa);
    min-height: 22px;
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .status-bar.success { color: var(--success); }
  .status-bar.error   { color: var(--danger); }

  .autopilot-badge {
    display: none;
    align-items: center;
    gap: 4px;
    background: #ff6b00;
    color: white;
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    padding: 2px 7px;
    border-radius: 10px;
    animation: pulse-autopilot 2s ease-in-out infinite;
  }

  .autopilot-badge.active { display: flex; }

  @keyframes pulse-autopilot {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.6; }
  }

  .loading-spinner {
    display: inline-block;
    width: 14px;
    height: 14px;
    border: 2px solid var(--accent);
    border-top-color: transparent;
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
    vertical-align: middle;
    margin-left: 8px;
  }

  @keyframes spin { to { transform: rotate(360deg); } }

  /* ── Session indicator ───────────────────────────────────────── */
  .session-label {
    font-size: 11px;
    color: var(--secondary-text-color, #888);
    opacity: 0.75;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    margin-left: 8px;
  }
  .session-label:empty { display: none; }

  /* ── Entity autocomplete dropdown ────────────────────────────── */
  .autocomplete-list {
    position: absolute;
    bottom: calc(100% + 2px);
    left: 10px;
    right: 10px;
    background: var(--card-background-color, #2c2c2e);
    border: 1px solid var(--accent);
    border-radius: 4px;
    max-height: 220px;
    overflow-y: auto;
    z-index: 999;
    box-shadow: 0 -4px 12px rgba(0,0,0,.4);
    display: none;
  }

  .autocomplete-list.open { display: block; }

  .ac-item {
    padding: 6px 10px;
    font-size: 12px;
    cursor: pointer;
    display: flex;
    flex-direction: column;
    gap: 1px;
    border-bottom: 1px solid var(--border-color);
  }
  .ac-item:last-child { border-bottom: none; }
  .ac-item:hover,
  .ac-item.active {
    background: var(--accent);
    color: white;
  }
  .ac-item .ac-id   { font-family: monospace; font-weight: 600; }
  .ac-item .ac-name { opacity: .75; font-size: 11px; }
`;

// ---------------------------------------------------------------------------
// Custom Element
// ---------------------------------------------------------------------------
class KyberPanel extends HTMLElement {
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

  connectedCallback() {
    // Block keyboard events at the shadow host so HA's global shortcuts don't fire while typing
    const stopKey = (e) => {
      console.log("[CopilotAssist] stopKey fired for", e.key, "stopping propagation");
      e.stopPropagation();
    };
    this.addEventListener("keydown", stopKey);
    this.addEventListener("keyup", stopKey);
    this.addEventListener("keypress", stopKey);
    console.log("[CopilotAssist] connectedCallback - keyboard listeners attached to", this.tagName);
    if (!this._rendered) this._render();
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
            <img id="kyber-header-icon" class="brand-icon" src="icon.png" alt="Kyber icon">
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
            <img id="kyber-sidebar-icon" class="brand-icon" src="icon.png" alt="Kyber icon">
            <span>Kyber Assistant</span>
            <span class="session-label" id="session-indicator"></span>
          </div>
          <div class="chat-history" id="chat-history">
            <div class="chat-message assistant">${this._DEFAULT_GREETING}</div>
          </div>
          <div class="chat-input-area" style="position:relative;">
            <div class="autocomplete-list" id="ac-list"></div>
            <textarea id="prompt-input" placeholder="Ask me anything about your smart home… (type / for commands)" rows="3"></textarea>
            <button class="btn-clear-history" id="btn-clear-history" title="Clear persisted chat history">Clear history</button>
            <button class="btn-ask" id="btn-ask">Ask</button>
          </div>
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
  }

  _initEditor(container) {
    const self = this;
    const extensions = [
      lineNumbers(),
      highlightActiveLine(),
      drawSelection(),
      history(),
      bracketMatching(),
      closeBrackets(),
      foldGutter(),
      autocompletion(),
      syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
      yaml(),
      oneDark,
      keymap.of([indentWithTab, ...defaultKeymap, ...historyKeymap]),
      EditorView.updateListener.of((update) => {
        if (update.docChanged) {
          self._dirty = true;
          self.shadowRoot.getElementById("btn-save").disabled = false;
        }
      }),
    ];

    this._editor = new EditorView({
      state: EditorState.create({ doc: "", extensions }),
      parent: container,
    });

    // Prevent HA's global keyboard shortcuts from firing while typing in the editor
    container.addEventListener("keydown", (e) => e.stopPropagation());
    container.addEventListener("keyup", (e) => e.stopPropagation());
    container.addEventListener("keypress", (e) => e.stopPropagation());
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

  _sanitizeHistoryForPersistence(messages) {
    if (!Array.isArray(messages)) return [];
    return messages
      .map((msg) => ({
        role: msg?.role === "user" ? "user" : "assistant",
        content: String(msg?.content || "").trim(),
      }))
      .filter((msg) => msg.content.length > 0)
      .slice(-200);
  }

  _resetChatView() {
    const history = this.shadowRoot.getElementById("chat-history");
    if (!history) return;
    history.innerHTML = `<div class="chat-message assistant">${this._escapeHtml(this._DEFAULT_GREETING)}</div>`;
  }

  _addChatHistory(role, content) {
    const text = String(content || "").trim();
    if (!text) return;
    this._chatHistory.push({ role: role === "user" ? "user" : "assistant", content: text });
    this._persistHistory();
  }

  async _persistHistory() {
    if (!this._hass) return;
    try {
      const token = this._hass.auth.data.access_token;
      const resp = await fetch("/api/kyber/history", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({
          history: this._sanitizeHistoryForPersistence(this._chatHistory),
          compacted_summary: String(this._compactedSummary || "").trim(),
        }),
      });
      if (!resp.ok) {
        const body = await resp.text().catch(() => "");
        console.warn("[Kyber] _persistHistory failed:", resp.status, body);
      }
    } catch (err) {
      console.warn("[Kyber] _persistHistory error:", err);
    }
  }

  async _restorePersistedHistory() {
    if (!this._hass) return;
    try {
      const token = this._hass.auth.data.access_token;
      const resp = await fetch("/api/kyber/history", {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!resp.ok) {
        console.warn("[Kyber] _restorePersistedHistory failed:", resp.status);
        throw new Error(`HTTP ${resp.status}`);
      }
      const data = await resp.json();
      const persistedHistory = this._sanitizeHistoryForPersistence(data?.history || []);
      const persistedSummary = String(data?.compacted_summary || "").trim();

      // Capture session metadata
      this._activeSessionId = data?.session_id || null;
      this._activeSessionName = data?.session_name || "Session 1";

      // Only apply restored data if nothing has been written in-memory yet.
      // This avoids races with tests and with very early user interactions.
      if (this._chatHistory.length === 0 && !this._compactedSummary) {
        this._chatHistory = persistedHistory;
        this._compactedSummary = persistedSummary;
        this._resetChatView();
        this._chatHistory.forEach((msg) => this._appendMessage(msg.content, msg.role === "user" ? "user" : "assistant"));
        console.log("[Kyber] restored", persistedHistory.length, "messages from history");
      }
      this._historyRestored = true;
      this._updateSessionIndicator();
    } catch (_) {
      // Non-fatal: start with empty in-memory history
      this._chatHistory = [];
      this._compactedSummary = "";
      this._resetChatView();
      this._historyRestored = true;
    }
  }

  async _clearHistory() {
    this._chatHistory = [];
    this._compactedSummary = "";
    this._resetChatView();
    try {
      const token = this._hass.auth.data.access_token;
      const resp = await fetch("/api/kyber/history", {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (resp.ok) {
        this._setStatus("History cleared");
      } else {
        this._setStatus(`History clear failed: HTTP ${resp.status}`, "error");
      }
    } catch (err) {
      this._setStatus(`History clear failed: ${err.message || String(err)}`, "error");
    }
  }

  _getActiveSession() {
    return this._activeSessionId ? { id: this._activeSessionId, name: this._activeSessionName || "Session 1" } : null;
  }

  _updateSessionIndicator() {
    // Show session name as a subtle subtitle under the chat header if there are multiple sessions
    const name = this._activeSessionName || "Session 1";
    const indicator = this.shadowRoot?.getElementById("session-indicator");
    if (indicator) indicator.textContent = name;
  }

  async _loadSessionList() {
    if (!this._hass) return [];
    try {
      const token = this._hass.auth.data.access_token;
      const resp = await fetch("/api/kyber/sessions", { headers: { Authorization: `Bearer ${token}` } });
      if (!resp.ok) return [];
      const data = await resp.json();
      this._sessions = (data.sessions || []).map((s) => ({ id: s.id, name: s.name, history: Array(s.message_count), active: s.active }));
      return this._sessions;
    } catch (_) {
      return [];
    }
  }

  async _createSession(name) {
    if (!this._hass) return;
    const token = this._hass.auth.data.access_token;
    const resp = await fetch("/api/kyber/sessions", {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ name, switch: true }),
    });
    if (!resp.ok) {
      this._appendMessage(`Failed to create session (HTTP ${resp.status})`, "assistant");
      return;
    }
    const data = await resp.json();
    this._activeSessionId = data.session_id;
    this._activeSessionName = data.name;
    // Clear in-memory history for the new session
    this._chatHistory = [];
    this._compactedSummary = "";
    this._resetChatView();
    this._updateSessionIndicator();
  }

  async _switchSession(nameOrId) {
    if (!this._hass) return;
    const sessions = await this._loadSessionList();
    const target = sessions.find((s) => s.name.toLowerCase() === nameOrId.toLowerCase() || s.id === nameOrId);
    if (!target) {
      this._appendMessage(`Session not found: "${nameOrId}". Use \`/session list\` to see available sessions.`, "assistant");
      return;
    }
    const token = this._hass.auth.data.access_token;
    await fetch("/api/kyber/sessions", {
      method: "PATCH",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ action: "switch", session_id: target.id }),
    });
    this._activeSessionId = target.id;
    this._activeSessionName = target.name;
    // Reload history for this session
    this._chatHistory = [];
    this._compactedSummary = "";
    await this._restorePersistedHistory();
    this._appendMessage(`Switched to session: **${target.name}**`, "assistant");
  }

  async _renameSession(newName) {
    if (!this._hass) return;
    const token = this._hass.auth.data.access_token;
    const resp = await fetch("/api/kyber/sessions", {
      method: "PATCH",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ action: "rename", name: newName }),
    });
    if (!resp.ok) {
      this._appendMessage(`Failed to rename session (HTTP ${resp.status})`, "assistant");
      return;
    }
    const oldName = this._activeSessionName;
    this._activeSessionName = newName;
    this._updateSessionIndicator();
    this._appendMessage(`Session renamed from **${oldName}** to **${newName}**`, "assistant");
  }

  async _deleteSession(sessionId) {
    if (!this._hass) return;
    const token = this._hass.auth.data.access_token;
    const resp = await fetch("/api/kyber/sessions", {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId }),
    });
    if (!resp.ok) {
      this._appendMessage(`Failed to delete session (HTTP ${resp.status})`, "assistant");
      return;
    }
    const data = await resp.json();
    this._activeSessionId = data.active_session;
    this._chatHistory = [];
    this._compactedSummary = "";
    await this._restorePersistedHistory();
    this._appendMessage("Session deleted. Switched to previous session.", "assistant");
  }

  _showHelp(topic) {
    const HELP = {
      autopilot: `**autopilot** — Toggle auto-execution of AI proposals.\n\n\`/autopilot on\` — Enable autopilot. Proposals from the AI execute automatically without confirmation.\n\`/autopilot off\` — Disable autopilot. You'll see a confirm card before any change is applied.\n\nUseful when you trust the AI and want fast iteration.`,
      dashboard: `**dashboard** — Manage Lovelace dashboards from the chat.\n\n\`/dashboard open [name]\` — Load a dashboard into the YAML editor. Omit name for the default Overview.\n\`/dashboard close\` — Close the editor without saving.\n\`/dashboard save\` — Save current editor content back to HA.\n\`/dashboard new\` — Create a new storage-mode dashboard.\n\`/dashboard delete\` — Permanently delete the open dashboard.`,
      automation: `**automation** — Open, edit, save, create and delete automations.\n\n\`/automation open <name>\` — Fuzzy-find and open an automation in the YAML editor.\n\`/automation close\` — Close editor without saving.\n\`/automation save\` — Save current automation YAML.\n\`/automation new\` — Open HA's automation editor in a new tab.\n\`/automation delete <name>\` — Permanently delete an automation.`,
      script: `**script** — Same as automation commands but for scripts.\n\n\`/script open <name>\`, \`/script close\`, \`/script save\`, \`/script new\`, \`/script delete <name>\``,
      blueprint: `**blueprint** — Open HA's Blueprint management page.\n\n\`/blueprint browse\` — Opens /config/blueprint in a new tab.`,
      area: `**area** — Manage Home Assistant areas.\n\n\`/area new <name>\` — Create a new area.\n\`/area delete <name>\` — Delete an area (entities become unassigned).\n\`/area rename <old> to <new>\` — Rename an area.\n\`/area list\` — List all areas with their IDs.`,
      reset: `**reset** — Clear the current chat and start over.\n\n\`/reset\` — Shows a danger confirm card. On Execute, clears all messages and persisted history for this session.`,
      session: `**session** — Manage multiple named chat sessions. Each session has its own message history and AI context.\n\n\`/session new [name]\` — Create a new session and switch to it.\n\`/session list\` — Show all sessions with their message counts.\n\`/session switch <name>\` — Switch to a different session.\n\`/session rename <new name>\` — Rename the current session.\n\`/session delete\` — Delete the current session and switch to the previous one.`,
      help: `**help** — Show help for Kyber slash commands.\n\n\`/help\` — List all commands with one-line descriptions.\n\`/help <command>\` — Detailed documentation for a specific command (e.g. /help automation).`,
    };

    if (topic && HELP[topic]) {
      this._appendMessage(HELP[topic], "assistant");
      return;
    }
    if (topic && !HELP[topic]) {
      this._appendMessage(`No help found for "${topic}". Try: ${Object.keys(HELP).join(", ")}`, "assistant");
      return;
    }
    // /help with no argument — show command table
    const lines = [
      "**Kyber Slash Commands** — type / to autocomplete\n",
      "| Command | Description |",
      "|---|---|",
      "| `/autopilot on/off` | Toggle auto-execute for AI proposals |",
      "| `/dashboard open/save/new/delete` | Manage Lovelace dashboards |",
      "| `/automation open/save/new/delete` | Manage automations |",
      "| `/script open/save/new/delete` | Manage scripts |",
      "| `/blueprint browse` | Open HA blueprint page |",
      "| `/area new/delete/rename/list` | Manage areas |",
      "| `/session new/list/switch/rename/delete` | Manage chat sessions |",
      "| `/reset` | Clear chat and start over |",
      "| `/help [command]` | Show this help or help for a specific command |",
    ];
    this._appendMessage(lines.join("\n"), "assistant");
  }

  async _handleSessionCommand(argStr) {
    const parts = argStr.match(/^(\w+)(?:\s+(.*))?$/i);
    const sub = parts ? parts[1].toLowerCase() : "";
    const rest = parts ? (parts[2] || "").trim() : "";

    if (!sub || sub === "list") {
      const sessions = this._sessions || [];
      if (!sessions.length) {
        this._appendMessage("No sessions yet. Use `/session new [name]` to create one.", "assistant");
        return;
      }
      const lines = sessions.map((s, i) => {
        const active = s.id === this._activeSessionId ? " ← active" : "";
        return `${i + 1}. **${s.name}** (${s.history.length} messages)${active}`;
      });
      this._appendMessage("**Chat Sessions:**\n" + lines.join("\n"), "assistant");
      return;
    }
    if (sub === "new") {
      const name = rest || `Session ${(this._sessions || []).length + 1}`;
      await this._createSession(name);
      this._appendMessage(`Started new session: **${name}**`, "assistant");
      return;
    }
    if (sub === "switch") {
      if (!rest) { this._appendMessage("Usage: `/session switch <name>`", "assistant"); return; }
      await this._switchSession(rest);
      return;
    }
    if (sub === "rename") {
      if (!rest) { this._appendMessage("Usage: `/session rename <new name>`", "assistant"); return; }
      await this._renameSession(rest);
      return;
    }
    if (sub === "delete") {
      const session = this._getActiveSession();
      if (!session) { this._appendMessage("No active session to delete.", "assistant"); return; }
      this._buildCommandCard({
        icon: "🗑",
        title: `Delete session: ${session.name}`,
        detail: `${session.history.length} messages will be lost.`,
        danger: true,
        onConfirm: async () => { await this._deleteSession(session.id); },
      });
      return;
    }
    this._appendMessage(`Unknown session sub-command: "${sub}". Try: new, list, switch, rename, delete`, "assistant");
  }

  /** Extract the token the cursor is currently inside in a textarea. */
  _getTokenAtCursor(textarea) {
    const pos = textarea.selectionStart;
    const text = textarea.value.slice(0, pos);
    const m = text.match(/[\w.\-]+$/);
    return m ? m[0] : "";
  }

  _onPromptInput(textarea) {
    const val = textarea.value;

    // ── Slash command autocomplete ─────────────────────────────────
    const slashAc = val.match(/^\/(\w*)$/);
    if (slashAc) {
      const partial = slashAc[1].toLowerCase();
      const cmds = ["autopilot on", "autopilot off", "dashboard", "automation", "script", "blueprint", "area", "reset", "help", "session"];
      const matches = cmds.filter((c) => c.startsWith(partial)).map((c) => ({
        entity_id: "/" + c,
        friendly_name: "",
      }));
      if (matches.length) {
        this._acItems = matches;
        this._acToken = val;
        this._acIndex = -1;
        this._buildAcList(true);
        return;
      }
    }

    // ── Slash command sub-action autocomplete (e.g. /automation open <name>) ──
    const slashSub = val.match(/^\/(automation|script|dashboard|area)\s+(\w+)\s+(.*)$/i);
    if (slashSub) {
      const cmd = slashSub[1].toLowerCase();
      const action = slashSub[2].toLowerCase();
      const partial = slashSub[3].toLowerCase();
      if (action === "open" || action === "delete" || action === "rename") {
        let candidates = [];
        if (cmd === "automation") {
          candidates = Object.values(this._hass.states || {})
            .filter((s) => s.entity_id.startsWith("automation."))
            .map((s) => ({ entity_id: s.entity_id, friendly_name: s.attributes.friendly_name || "" }));
        } else if (cmd === "script") {
          candidates = Object.values(this._hass.states || {})
            .filter((s) => s.entity_id.startsWith("script."))
            .map((s) => ({ entity_id: s.entity_id, friendly_name: s.attributes.friendly_name || "" }));
        } else if (cmd === "dashboard") {
          const panels = this._hass.panels || {};
          candidates = Object.values(panels)
            .filter((p) => p.component_name === "lovelace" && p.url_path && p.url_path !== "kyber")
            .map((p) => ({ entity_id: p.url_path, friendly_name: p.title || "" }));
        } else if (cmd === "area") {
          // No hass.areas in all versions — use textarea as-is
        }
        const filtered = candidates.filter((c) =>
          c.entity_id.toLowerCase().includes(partial) ||
          c.friendly_name.toLowerCase().includes(partial)
        ).slice(0, 8);
        if (filtered.length) {
          this._acItems = filtered;
          this._acToken = slashSub[3];
          this._acIndex = -1;
          this._buildAcList(false);
          return;
        }
      }
    }

    const token = this._getTokenAtCursor(textarea);
    if (!token || token.length < 2 || !this._hass) {
      this._closeAc();
      return;
    }
    const lower = token.toLowerCase();
    const matches = Object.keys(this._hass.states)
      .filter((id) => id.toLowerCase().startsWith(lower))
      .slice(0, 10)
      .map((id) => ({
        entity_id: id,
        friendly_name: this._hass.states[id].attributes.friendly_name || "",
      }));

    if (matches.length === 0) {
      this._closeAc();
      return;
    }
    this._acItems = matches;
    this._acToken = token;
    this._acIndex = -1;
    this._buildAcList(false);
  }

  /** Build the full dropdown DOM (called when items change). */
  _buildAcList(replaceAll = false) {
    const list = this.shadowRoot.getElementById("ac-list");
    list.innerHTML = this._acItems.map((item, i) => `
      <div class="ac-item" data-id="${item.entity_id}" data-idx="${i}" data-replace-all="${replaceAll}">
        <span class="ac-id">${item.entity_id}</span>
        ${item.friendly_name ? `<span class="ac-name">${item.friendly_name}</span>` : ""}
      </div>
    `).join("");

    list.querySelectorAll(".ac-item").forEach((el) => {
      el.addEventListener("mousedown", (e) => {
        e.preventDefault();
        this._applyAcItem(el.dataset.id, el.dataset.replaceAll === "true");
      });
    });

    list.classList.add("open");
  }

  /** Only update which item has the active class — no DOM rebuild. */
  _updateAcActive() {
    const list = this.shadowRoot.getElementById("ac-list");
    if (!list) return;
    list.querySelectorAll(".ac-item").forEach((el, i) => {
      el.classList.toggle("active", i === this._acIndex);
    });
    if (this._acIndex >= 0) {
      const active = list.querySelector(".active");
      if (active) active.scrollIntoView({ block: "nearest" });
    }
  }

  _applyAcItem(entityId, replaceAll = false) {
    const textarea = this.shadowRoot.getElementById("prompt-input");
    if (replaceAll) {
      textarea.value = entityId;
    } else {
      const pos = textarea.selectionStart;
      const before = textarea.value.slice(0, pos);
      const after = textarea.value.slice(pos);
      const newBefore = before.replace(/[\w.\-]+$/, entityId);
      textarea.value = newBefore + after;
      const newPos = newBefore.length;
      textarea.setSelectionRange(newPos, newPos);
    }
    textarea.focus();
    this._closeAc();
  }

  _closeAc() {
    this._acItems = [];
    this._acIndex = -1;
    this._acToken = "";
    const list = this.shadowRoot.getElementById("ac-list");
    if (list) { list.classList.remove("open"); list.innerHTML = ""; }
  }

  // ── Slash command engine ──────────────────────────────────────────

  /** Build a confirm card for slash commands. onConfirm(card) is called when Execute is clicked. */
  _buildCommandCard({ icon = "▶", title, detail, warning, danger = false, onConfirm }) {
    const history = this.shadowRoot.getElementById("chat-history");
    const card = document.createElement("div");
    card.className = `command-card${danger ? " danger" : ""}`;
    card.innerHTML = `
      <div class="command-card-title">${icon} ${this._escapeHtml(title)}</div>
      ${detail ? `<div class="command-card-detail">${this._escapeHtml(detail)}</div>` : ""}
      ${warning ? `<div class="command-card-warning">⚠ ${this._escapeHtml(warning)}</div>` : ""}
      <div class="command-card-actions">
        <button class="btn-cmd-execute${danger ? " danger" : ""}">▶ Execute</button>
        <button class="btn-cmd-cancel">✕ Cancel</button>
      </div>
    `;
    card.querySelector(".btn-cmd-execute").addEventListener("click", () => {
      card.querySelector(".btn-cmd-execute").disabled = true;
      card.querySelector(".btn-cmd-cancel").disabled = true;
      onConfirm(card);
    });
    card.querySelector(".btn-cmd-cancel").addEventListener("click", () => card.remove());
    history.appendChild(card);
    history.scrollTop = history.scrollHeight;
  }

  _showMsg(text, role = "assistant") {
    this._appendMessage(text, role);
  }

  /** Find an automation/script by partial name or entity_id. Returns state object or null. */
  _findEntity(prefix, nameArg) {
    if (!nameArg) return null;
    const lower = nameArg.toLowerCase();
    const states = Object.values(this._hass.states || {});
    const pool = states.filter((s) => s.entity_id.startsWith(prefix + "."));
    // Exact entity_id match first
    const exact = pool.find((s) => s.entity_id === nameArg || s.entity_id === prefix + "." + nameArg);
    if (exact) return exact;
    // Friendly name contains
    const byName = pool.filter((s) =>
      (s.attributes.friendly_name || "").toLowerCase().includes(lower) ||
      s.entity_id.toLowerCase().includes(lower)
    );
    return byName.length === 1 ? byName[0] : byName[0] || null; // best guess
  }

  _handleSlashCommand(cmd, argStr) {
    const parts = argStr.trim().split(/\s+/);
    const action = (parts[0] || "").toLowerCase();
    const nameArg = parts.slice(1).join(" ").trim();

    this._appendMessage(`/${cmd} ${argStr}`, "user");

    switch (cmd) {
      case "dashboard": return this._cmdDashboard(action, nameArg);
      case "automation": return this._cmdAutomation(action, nameArg);
      case "script":     return this._cmdScript(action, nameArg);
      case "blueprint":  return this._cmdBlueprint(action, nameArg);
      case "area":       return this._cmdArea(action, nameArg);
    }
  }

  // ──── /dashboard ─────────────────────────────────────────────────

  _cmdDashboard(action, nameArg) {
    switch (action) {
      case "open": {
        const panels = this._hass.panels || {};
        const all = Object.values(panels).filter((p) => p.component_name === "lovelace" && p.url_path !== "kyber");
        const lower = nameArg.toLowerCase();
        const match = nameArg
          ? (all.find((p) => p.url_path === lower) ||
             all.find((p) => (p.title || "").toLowerCase().includes(lower)) ||
             all.find((p) => p.url_path.includes(lower)))
          : null;
        const urlPath = match ? (match.url_path === "lovelace" ? null : match.url_path) : null;
        const label = match ? (match.title || match.url_path) : "Overview (default)";
        this._buildCommandCard({
          icon: "📊", title: `Open dashboard editor`,
          detail: label,
          onConfirm: (card) => {
            this._openDashboard(urlPath);
            card.querySelector(".btn-cmd-execute").textContent = "✓ Opened";
          },
        });
        break;
      }
      case "close":
        this._closeEditor();
        this._showMsg("Dashboard editor closed.");
        break;
      case "save":
        if (this._editorMode !== "dashboard") { this._showMsg("No dashboard is currently open."); return; }
        this._buildCommandCard({
          icon: "💾", title: "Save dashboard",
          detail: this.shadowRoot.getElementById("dashboard-select")?.options[
            this.shadowRoot.getElementById("dashboard-select")?.selectedIndex]?.textContent || "",
          onConfirm: (card) => {
            this._saveDashboard().then(() => { card.querySelector(".btn-cmd-execute").textContent = "✓ Saved"; });
          },
        });
        break;
      case "new":
        this._buildCommandCard({
          icon: "＋", title: "Create new dashboard",
          detail: nameArg || "(enter title when prompted)",
          onConfirm: () => this._createNewDashboard(),
        });
        break;
      case "delete": {
        const sel = this.shadowRoot.getElementById("dashboard-select");
        const urlPath = this._currentDashboardPath;
        const label = sel?.options[sel?.selectedIndex]?.textContent || urlPath || "(none)";
        if (!urlPath) { this._showMsg("No specific dashboard is open (can't delete the default Overview)."); return; }
        this._buildCommandCard({
          icon: "🗑", title: "Delete dashboard",
          detail: label, danger: true,
          warning: "This permanently removes the dashboard from the sidebar.",
          onConfirm: async (card) => {
            try {
              const panels = this._hass.panels || {};
              const p = Object.values(panels).find((x) => x.url_path === urlPath);
              if (p) await this._hass.callWS({ type: "lovelace/dashboards/delete", dashboard_id: p.id || urlPath });
              this._closeEditor();
              card.querySelector(".btn-cmd-execute").textContent = "✓ Deleted";
              this._showMsg(`Dashboard "${label}" deleted.`);
            } catch (err) {
              this._setStatus(`Delete failed: ${err.message}`, "error");
              card.querySelector(".btn-cmd-execute").disabled = false;
            }
          },
        });
        break;
      }
      default:
        this._showMsg(`/dashboard commands: open [name], close, save, new, delete`);
    }
  }

  // ──── /automation ────────────────────────────────────────────────

  _cmdAutomation(action, nameArg) {
    switch (action) {
      case "open": {
        const state = this._findEntity("automation", nameArg);
        if (!state) { this._showMsg(`Automation not found: "${nameArg}". Try a partial name.`); return; }
        const friendly = state.attributes.friendly_name || state.entity_id;
        const configId = state.attributes.id || state.entity_id.replace("automation.", "");
        this._buildCommandCard({
          icon: "📝", title: "Open automation editor",
          detail: `${state.entity_id} — ${friendly}`,
          onConfirm: (card) => {
            this._openEditor(state.entity_id);
            card.querySelector(".btn-cmd-execute").textContent = "✓ Opened";
          },
        });
        break;
      }
      case "close":
        this._closeEditor();
        this._showMsg("Editor closed.");
        break;
      case "save":
        if (!this._currentAutomationId) { this._showMsg("No automation is currently open."); return; }
        this._buildCommandCard({
          icon: "💾", title: "Save automation",
          detail: this._currentAutomationId,
          onConfirm: (card) => {
            this._saveAutomation().then(() => { card.querySelector(".btn-cmd-execute").textContent = "✓ Saved"; });
          },
        });
        break;
      case "new":
        this._buildCommandCard({
          icon: "＋", title: "Create new automation",
          detail: "Opens HA's automation editor in a new tab",
          onConfirm: (card) => {
            window.open("/config/automation/edit/new", "_blank");
            card.querySelector(".btn-cmd-execute").textContent = "✓ Opened";
          },
        });
        break;
      case "delete": {
        const state = this._findEntity("automation", nameArg);
        if (!state) { this._showMsg(`Automation not found: "${nameArg}".`); return; }
        const friendly = state.attributes.friendly_name || state.entity_id;
        const configId = state.attributes.id;
        this._buildCommandCard({
          icon: "🗑", title: "Delete automation",
          detail: `${state.entity_id} — ${friendly}`,
          danger: true,
          warning: "This permanently deletes the automation.",
          onConfirm: async (card) => {
            try {
              await this._hass.callApi("DELETE", `config/automation/config/${configId}`);
              card.querySelector(".btn-cmd-execute").textContent = "✓ Deleted";
              this._showMsg(`Automation "${friendly}" deleted.`);
            } catch (err) {
              this._setStatus(`Delete failed: ${err.message}`, "error");
              card.querySelector(".btn-cmd-execute").disabled = false;
            }
          },
        });
        break;
      }
      default:
        this._showMsg(`/automation commands: open <name>, close, save, new, delete <name>`);
    }
  }

  // ──── /script ────────────────────────────────────────────────────

  _cmdScript(action, nameArg) {
    switch (action) {
      case "open": {
        const state = this._findEntity("script", nameArg);
        if (!state) { this._showMsg(`Script not found: "${nameArg}".`); return; }
        const friendly = state.attributes.friendly_name || state.entity_id;
        this._buildCommandCard({
          icon: "📜", title: "Open script editor",
          detail: `${state.entity_id} — ${friendly}`,
          onConfirm: (card) => {
            this._openEditor(state.entity_id);
            card.querySelector(".btn-cmd-execute").textContent = "✓ Opened";
          },
        });
        break;
      }
      case "close":
        this._closeEditor();
        this._showMsg("Editor closed.");
        break;
      case "save":
        this._buildCommandCard({
          icon: "💾", title: "Save script",
          detail: this._currentAutomationId || "(current)",
          onConfirm: (card) => {
            this._saveAutomation().then(() => { card.querySelector(".btn-cmd-execute").textContent = "✓ Saved"; });
          },
        });
        break;
      case "new":
        this._buildCommandCard({
          icon: "＋", title: "Create new script",
          detail: "Opens HA's script editor in a new tab",
          onConfirm: (card) => {
            window.open("/config/script/edit/new", "_blank");
            card.querySelector(".btn-cmd-execute").textContent = "✓ Opened";
          },
        });
        break;
      case "delete": {
        const state = this._findEntity("script", nameArg);
        if (!state) { this._showMsg(`Script not found: "${nameArg}".`); return; }
        const friendly = state.attributes.friendly_name || state.entity_id;
        const configId = state.entity_id.replace("script.", "");
        this._buildCommandCard({
          icon: "🗑", title: "Delete script",
          detail: `${state.entity_id} — ${friendly}`,
          danger: true,
          warning: "This permanently deletes the script.",
          onConfirm: async (card) => {
            try {
              await this._hass.callApi("DELETE", `config/script/config/${configId}`);
              card.querySelector(".btn-cmd-execute").textContent = "✓ Deleted";
              this._showMsg(`Script "${friendly}" deleted.`);
            } catch (err) {
              this._setStatus(`Delete failed: ${err.message}`, "error");
              card.querySelector(".btn-cmd-execute").disabled = false;
            }
          },
        });
        break;
      }
      default:
        this._showMsg(`/script commands: open <name>, close, save, new, delete <name>`);
    }
  }

  // ──── /blueprint ─────────────────────────────────────────────────

  _cmdBlueprint(action) {
    switch (action) {
      case "open":
      case "browse":
        this._buildCommandCard({
          icon: "🗺", title: "Browse blueprints",
          detail: "Opens HA's Blueprint page in a new tab",
          onConfirm: (card) => {
            window.open("/config/blueprint", "_blank");
            card.querySelector(".btn-cmd-execute").textContent = "✓ Opened";
          },
        });
        break;
      default:
        this._showMsg(`/blueprint commands: browse (opens HA blueprint page)`);
    }
  }

  // ──── /area ──────────────────────────────────────────────────────

  _cmdArea(action, nameArg) {
    switch (action) {
      case "new":
      case "create": {
        const name = nameArg;
        if (!name) { this._showMsg(`Usage: /area new <name>`); return; }
        this._buildCommandCard({
          icon: "＋", title: "Create area",
          detail: name,
          onConfirm: async (card) => {
            try {
              await this._executeActions([{ type: "create_area", name }]);
              card.querySelector(".btn-cmd-execute").textContent = "✓ Created";
              this._showMsg(`Area "${name}" created.`);
            } catch (err) {
              this._setStatus(`Failed: ${err.message}`, "error");
              card.querySelector(".btn-cmd-execute").disabled = false;
            }
          },
        });
        break;
      }
      case "delete": {
        if (!nameArg) { this._showMsg(`Usage: /area delete <name>`); return; }
        // Find area by name
        this._buildCommandCard({
          icon: "🗑", title: "Delete area",
          detail: nameArg,
          danger: true,
          warning: "Entities assigned to this area will become unassigned.",
          onConfirm: async (card) => {
            try {
              await this._executeActions([{ type: "delete_area", area_id: nameArg.toLowerCase().replace(/\s+/g, "_") }]);
              card.querySelector(".btn-cmd-execute").textContent = "✓ Deleted";
            } catch (err) {
              this._setStatus(`Failed: ${err.message}`, "error");
              card.querySelector(".btn-cmd-execute").disabled = false;
            }
          },
        });
        break;
      }
      case "rename": {
        const parts = nameArg.split(/\s+to\s+/i);
        if (parts.length < 2) { this._showMsg(`Usage: /area rename <old> to <new>`); return; }
        const [oldName, newName] = parts;
        this._buildCommandCard({
          icon: "✏", title: "Rename area",
          detail: `"${oldName}" → "${newName}"`,
          onConfirm: async (card) => {
            try {
              await this._executeActions([{
                type: "rename_area",
                area_id: oldName.trim().toLowerCase().replace(/\s+/g, "_"),
                name: newName.trim(),
              }]);
              card.querySelector(".btn-cmd-execute").textContent = "✓ Renamed";
            } catch (err) {
              this._setStatus(`Failed: ${err.message}`, "error");
              card.querySelector(".btn-cmd-execute").disabled = false;
            }
          },
        });
        break;
      }
      case "list": {
        const areaReg = Object.values(this._hass.areas || {});
        if (areaReg.length) {
          this._showMsg("Areas:\n" + areaReg.map((a) => `• ${a.name} (${a.area_id})`).join("\n"));
        } else {
          this._showMsg("No areas found. (HA areas may not be exposed to custom panels in all versions.)");
        }
        break;
      }
      default:
        this._showMsg(`/area commands: new <name>, delete <name>, rename <old> to <new>, list`);
    }
  }

  /** Execute a list of plan actions via the /execute endpoint. */
  async _executeActions(actions) {
    const token = this._hass.auth.data.access_token;
    const resp = await fetch("/api/kyber/execute", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ actions }),
    });
    if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`);
    return resp.json();
  }

  async _openEditor(entityId) {
    if (!this._hass) return;

    const editorPane = this.shadowRoot.getElementById("editor-container");
    if (!this._editor) {
      this._initEditor(editorPane);
    }

    // Resolve entity_id → HA config id and API path
    const state = this._hass.states[entityId];
    const isScript = entityId.startsWith("script.");
    const configId = (state && state.attributes.id)
      ? state.attributes.id
      : entityId.replace(/^(automation|script)\./, "");
    const friendlyName = (state && state.attributes.friendly_name) || entityId;

    const container = this.shadowRoot.getElementById("app-container");
    container.classList.add("editor-open");
    editorPane.classList.add("open");

    this.shadowRoot.querySelectorAll(".editor-controls").forEach((el) => {
      el.style.display = "block";
    });
    this._setEditorContextLabel(isScript ? "script" : "automation", friendlyName);
    const sel = this.shadowRoot.getElementById("dashboard-select");
    if (sel) sel.style.display = "none";
    const newDashBtn = this.shadowRoot.getElementById("btn-new-dashboard");
    if (newDashBtn) newDashBtn.style.display = "none";

    this._currentAutomationId = configId;
    this._editorMode = isScript ? "script" : "automation";
    this.shadowRoot.getElementById("btn-save").textContent = isScript ? "Save script" : "Save automation";
    await this._loadAutomation(configId);

    if (this._editor) {
      setTimeout(() => this._editor.requestMeasure(), 50);
    }
  }

  _closeEditor() {
    const container = this.shadowRoot.getElementById("app-container");
    container.classList.remove("editor-open");
    const editorPane = this.shadowRoot.getElementById("editor-container");
    editorPane.classList.remove("open");

    this.shadowRoot.querySelectorAll(".editor-controls").forEach((el) => {
      el.style.display = "";
    });
    const ctxLabel = this.shadowRoot.getElementById("editor-context-label");
    if (ctxLabel) ctxLabel.textContent = "";

    this._currentAutomationId = null;
    this._currentDashboardPath = null;
    this._editorMode = "automation";
    this._dirty = false;
    this._setStatus("");
    // Restore button labels
    const saveBtn = this.shadowRoot.getElementById("btn-save");
    if (saveBtn) { saveBtn.textContent = "Save"; saveBtn.disabled = true; }
    // Hide dashboard-specific controls
    const sel = this.shadowRoot.getElementById("dashboard-select");
    if (sel) sel.style.display = "none";
    const newDashBtn = this.shadowRoot.getElementById("btn-new-dashboard");
    if (newDashBtn) newDashBtn.style.display = "none";
  }

  async _openDashboard(targetUrlPath = null) {
    if (!this._hass) return;

    const editorPane = this.shadowRoot.getElementById("editor-container");
    if (!this._editor) this._initEditor(editorPane);

    this._editorMode = "dashboard";
    this._currentDashboardPath = null;
    const container = this.shadowRoot.getElementById("app-container");
    container.classList.add("editor-open");
    editorPane.classList.add("open");

    this.shadowRoot.querySelectorAll(".editor-controls").forEach((el) => {
      el.style.display = "block";
    });
    this.shadowRoot.getElementById("btn-save").textContent = "Save dashboard";
    this._setEditorContextLabel("dashboard", "Dashboard editor");
    this._setStatus("Opening…");
    this.shadowRoot.getElementById("btn-save").disabled = true;
    const newDashBtn = this.shadowRoot.getElementById("btn-new-dashboard");
    if (newDashBtn) newDashBtn.style.display = "inline-block";

    // Fetch list of all dashboards and populate selector
    this._setStatus("Loading dashboards…");
    try {
      const token = this._hass.auth.data.access_token;
      // Use hass.panels — always available, no extra API call
      // Exclude "lovelace" (the default Overview) — it's handled by __default__
      const panels = this._hass.panels || {};
      const dashboards = Object.values(panels)
        .filter((p) => p.component_name === "lovelace" && p.url_path
          && p.url_path !== "kyber" && p.url_path !== "lovelace");
      // Invalidate AI context cache so next ask re-reads panels
      this._dashboardList = null;

      // Build select options: default dashboard first, then storage-mode ones
      const sel = this.shadowRoot.getElementById("dashboard-select");
      sel.innerHTML = "";
      // Default Overview dashboard
      const defOpt = document.createElement("option");
      defOpt.value = "__default__";
      defOpt.textContent = "Overview (default)";
      sel.appendChild(defOpt);
      // All lovelace panels (already filtered above — no mode check needed)
      (dashboards || []).forEach((d) => {
          const opt = document.createElement("option");
          opt.value = d.url_path;
          opt.textContent = d.title || d.url_path;
          sel.appendChild(opt);
        });
      sel.style.display = "block";

      // If a target url_path was specified (from AI plan), load that directly
      if (targetUrlPath) {
        sel.value = targetUrlPath;
        const ctxLabel = sel.options[sel.selectedIndex]?.textContent || targetUrlPath;
        this._setEditorContextLabel("dashboard", ctxLabel);
        await this._loadDashboard(targetUrlPath);
      } else {
        // Load the first available dashboard with actual stored config
        const orderedPaths = [null, ...(dashboards || []).map((d) => d.url_path)];
        let loaded = false;
        for (const path of orderedPaths) {
          try {
            const apiPath = path ? `lovelace/config?url_path=${path}` : "lovelace/config";
            const config = await this._hass.callApi("GET", apiPath);
            sel.value = path || "__default__";
            this._currentDashboardPath = path;
            this._setEditorContent(this._configToYaml(config));
            this._dirty = false;
            this.shadowRoot.getElementById("btn-save").disabled = false;
            const dashTitle = sel.options[sel.selectedIndex]?.textContent || "";
            this._setEditorContextLabel("dashboard", dashTitle);
            this._setStatus(`Editing: ${dashTitle}`);
            loaded = true;
            break;
          } catch (_e) {
            // This path has no stored config; try next
          }
        }
        if (!loaded) {
          sel.value = "__default__";
          this._currentDashboardPath = null;
          const starter = { title: "Home", views: [{ title: "Home", cards: [] }] };
          this._setEditorContent(this._configToYaml(starter));
          this._dirty = false;
          this.shadowRoot.getElementById("btn-save").disabled = false;
          this._setEditorContextLabel("dashboard", "Overview (default)");
          this._setStatus("No stored dashboard config yet — edit this template and save.");
        }
      }
    } catch (err) {
      this._setStatus(`Error loading dashboard: ${err.message || String(err)}`, "error");
    }

    if (this._editor) setTimeout(() => this._editor.requestMeasure(), 50);
  }

  async _loadDashboard(urlPath) {
    if (!this._hass) return;
    this._currentDashboardPath = urlPath;
    this._setStatus("Loading…");
    this.shadowRoot.getElementById("btn-save").disabled = true;
    try {
      const token = this._hass.auth.data.access_token;
      const apiPath = urlPath ? `lovelace/config?url_path=${urlPath}` : "lovelace/config";
      const resp = await fetch(`/api/${apiPath}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      let config;
      if (resp.status === 404) {
        // Dashboard exists as a panel but has no stored config yet (or is in yaml mode).
        // Show a starter so the user can create initial config.
        config = { title: urlPath || "Home", views: [{ title: "Home", cards: [] }] };
        this._setStatus(`No stored config for "${urlPath || "default"}" — edit this starter and save.`);
      } else if (!resp.ok) {
        let errMsg = `HTTP ${resp.status}`;
        try {
          const body = await resp.text();
          if (body) { const j = JSON.parse(body); errMsg = j.message || body; }
        } catch (_) { /* use status */ }
        throw new Error(errMsg);
      } else {
        config = await resp.json();
        const sel = this.shadowRoot.getElementById("dashboard-select");
        const label = sel ? sel.options[sel.selectedIndex]?.textContent : urlPath || "default";
        this._setStatus(`Editing: ${label}`);
      }
      this._setEditorContent(this._configToYaml(config));
      this._dirty = false;
      this.shadowRoot.getElementById("btn-save").disabled = false;
    } catch (err) {
      const msg = err instanceof Error ? err.message : (err != null ? String(err) : "unknown error");
      this._setStatus(`Error loading dashboard: ${msg}`, "error");
    }
  }

  async _saveDashboard() {
    if (!this._hass) return;
    const yamlText = this._editor.state.doc.toString().trim();
    const btn = this.shadowRoot.getElementById("btn-save");

    if (!yamlText) {
      this._setStatus("Cannot save: dashboard config is empty.", "error");
      return;
    }

    btn.disabled = true;
    this._setStatus("Saving dashboard…");

    try {
      const token = this._hass.auth.data.access_token;

      // Parse YAML server-side → JSON
      const parseResp = await fetch("/api/kyber/parse_yaml", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ yaml: yamlText }),
      });
      if (!parseResp.ok) {
        const errText = await parseResp.text();
        let errMsg = errText;
        try { errMsg = JSON.parse(errText).message || errText; } catch (_) { /* use raw */ }
        throw new Error(`YAML parse error: ${errMsg}`);
      }
      const { config } = await parseResp.json();

      // Save to the currently selected dashboard path via direct fetch.
      // hass.callApi rejects with undefined on empty error bodies, so we
      // use fetch directly to get a meaningful error message.
      const path = this._currentDashboardPath;
      const apiPath = path ? `lovelace/config?url_path=${path}` : "lovelace/config";
      const saveResp = await fetch(`/api/${apiPath}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify(config),
      });

      if (!saveResp.ok) {
        let errMsg = `HTTP ${saveResp.status}`;
        try {
          const errBody = await saveResp.text();
          if (errBody) {
            const errJson = JSON.parse(errBody);
            errMsg = errJson.message || errJson.body || errBody;
          }
        } catch (_) { /* keep HTTP status as fallback */ }
        if (saveResp.status === 404) {
          errMsg = `Dashboard not found in HA storage. Make sure it is in storage mode (not YAML mode). Create it first with "New Dashboard" if needed.`;
        }
        console.error("_saveDashboard: HA API error", saveResp.status, errMsg);
        throw new Error(errMsg);
      }

      const sel = this.shadowRoot.getElementById("dashboard-select");
      const label = sel ? sel.options[sel.selectedIndex]?.textContent : (path || "default");
      this._dirty = false;
      btn.disabled = false;
      this._addChatHistory("user", `I saved the "${label}" dashboard YAML.`);
      this._addChatHistory("assistant", `[CHANGE] Dashboard "${label}" saved successfully.`);
      this._setStatus(`${label} saved ✓ — reload the browser tab to see changes`, "success");
    } catch (err) {
      btn.disabled = false;
      const msg = err instanceof Error ? err.message : (err != null ? String(err) : "unknown error");
      this._setStatus(`Save failed: ${msg}`, "error");
    }
  }

  async _createNewDashboard() {
    const title = prompt("New dashboard title (e.g. \"My Dashboard\"):");
    if (!title || !title.trim()) return;
    // Generate a url_path slug from the title
    const slug = title.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    if (!slug) { alert("Invalid title — please use letters or numbers."); return; }

    this._setStatus("Creating dashboard…");
    try {
      // Use WebSocket API — the REST endpoint doesn't exist in all HA versions
      await this._hass.callWS({
        type: "lovelace/dashboards/create",
        url_path: slug,
        title: title.trim(),
        mode: "storage",
        show_in_sidebar: true,
        require_admin: false,
      });

      // Add to selector and switch to it
      const sel = this.shadowRoot.getElementById("dashboard-select");
      const opt = document.createElement("option");
      opt.value = slug;
      opt.textContent = title.trim();
      sel.appendChild(opt);
      sel.value = slug;

      // Load empty config for the new dashboard
      this._currentDashboardPath = slug;
      const starter = { title: title.trim(), views: [{ title: "Home", cards: [] }] };
      this._setEditorContent(this._configToYaml(starter));
      this.shadowRoot.getElementById("btn-save").disabled = false;
      // Invalidate dashboard cache so AI sees the new dashboard
      this._dashboardList = null;
      this._setStatus(`New dashboard "${title.trim()}" created — edit and save to populate it.`);
    } catch (err) {
      this._setStatus(`Failed to create dashboard: ${err.message || String(err)}`, "error");
    }
  }

  async _maybeCompact() {
    if (this._chatHistory.length <= this._COMPACT_TRIGGER) return;

    const overflow = this._chatHistory.length - this._HISTORY_WINDOW;
    const toCompact = this._chatHistory.splice(0, overflow);

    try {
      const token = this._hass.auth.data.access_token;
      const resp = await fetch("/api/kyber/summarize", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          previous_summary: this._compactedSummary,
          messages: toCompact,
        }),
      });

      if (resp.ok) {
        const data = await resp.json();
        this._compactedSummary = data.summary || this._compactedSummary;
        this._persistHistory();
      }
    } catch (err) {
      // Compaction failure is non-fatal — messages just stay in history
      this._chatHistory.unshift(...toCompact);
    }
  }

  _logChange(description) {
    const entry = { role: "assistant", content: `[CHANGE] ${description}` };
    this._addChatHistory(entry.role, entry.content);
  }

  _setEditorContextLabel(mode, label) {
    const ctxLabel = this.shadowRoot.getElementById("editor-context-label");
    if (!ctxLabel) return;
    ctxLabel.textContent = `${mode} > ${label}`;
  }

  async _loadAutomation(configId) {
    if (!configId || !this._hass) return;
    const isScript = this._editorMode === "script";
    const apiPath = isScript ? `config/script/config/${configId}` : `config/automation/config/${configId}`;
    this._setStatus(`Loading ${isScript ? "script" : "automation"}…`);

    try {
      const config = await this._hass.callApi("GET", apiPath);
      const yamlText = this._configToYaml(config);
      this._setEditorContent(yamlText);
      this._currentAutomationId = configId;
      this._dirty = false;
      this.shadowRoot.getElementById("btn-save").disabled = true;
      this._setStatus(`Loaded: ${configId}`);
    } catch (err) {
      const msg = err instanceof Error ? err.message : (err != null ? String(err) : "unknown error");
      this._setStatus(`Error loading: ${msg}`, "error");
    }
  }

  async _saveAutomation() {
    if (!this._currentAutomationId || !this._hass) return;
    const yamlText = this._editor.state.doc.toString();
    const isScript = this._editorMode === "script";

    this._setStatus("Saving…");
    const btn = this.shadowRoot.getElementById("btn-save");
    btn.disabled = true;

    try {
      const token = this._hass.auth.data.access_token;

      // Step 1: Parse YAML server-side → get JSON config
      const parseResp = await fetch("/api/kyber/parse_yaml", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ yaml: yamlText }),
      });

      if (!parseResp.ok) {
        const err = await parseResp.text();
        throw new Error(`YAML parse error: ${err}`);
      }

      const { config } = await parseResp.json();

      // Step 2: Write JSON config via HA's config REST API.
      // Use fetch directly instead of hass.callApi — callApi rejects with
      // `undefined` when the response body is empty, making the error
      // undiagnosable. Direct fetch lets us extract a meaningful message.
      const apiPath = isScript
        ? `config/script/config/${this._currentAutomationId}`
        : `config/automation/config/${this._currentAutomationId}`;

      // HA's automation config POST requires the id field as a STRING in the
      // body. YAML parses bare numbers as integers, so we must override it
      // with _currentAutomationId (always a string).
      const configToSave = { ...config, id: this._currentAutomationId };

      const saveResp = await fetch(`/api/${apiPath}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(configToSave),
      });

      if (!saveResp.ok) {
        let errMsg = `HTTP ${saveResp.status}`;
        try {
          const errBody = await saveResp.text();
          if (errBody) {
            const errJson = JSON.parse(errBody);
            errMsg = errJson.message || errJson.body || errBody;
          }
        } catch (_) { /* keep HTTP status as fallback */ }
        console.error("_saveAutomation: HA API error", saveResp.status, errMsg);
        throw new Error(errMsg);
      }

      this._dirty = false;
      const kind = isScript ? "script" : "automation";
      this._addChatHistory("user", `I saved the YAML for ${this._currentAutomationId}.`);
      this._addChatHistory("assistant", `[CHANGE] ${kind} YAML saved: ${this._currentAutomationId}`);
      this._setStatus("Saved ✓", "success");
    } catch (err) {
      btn.disabled = false;
      const msg = err instanceof Error ? err.message : (err != null ? String(err) : "unknown error");
      this._setStatus(`Save failed: ${msg}`, "error");
    }
  }

  async _askAI() {
    const promptInput = this.shadowRoot.getElementById("prompt-input");
    const prompt = promptInput.value.trim();
    if (!prompt) return;

    // ── Slash commands ────────────────────────────────────────────
    const slashMatch = prompt.match(/^\/(\w+)(?:\s+(.*))?$/i);
    if (slashMatch) {
      const cmd = slashMatch[1].toLowerCase();
      const argStr = (slashMatch[2] || "").trim();
      if (cmd === "autopilot") {
        const arg = argStr.toLowerCase();
        promptInput.value = "";
        if (arg === "on") {
          this._autopilot = true;
          this._updateAutopilotBadge();
          this._appendMessage("⚡ Autopilot is now ON — proposals will execute automatically.", "assistant");
        } else if (arg === "off") {
          this._autopilot = false;
          this._updateAutopilotBadge();
          this._appendMessage("Autopilot is now OFF — you'll review proposals before executing.", "assistant");
        } else {
          this._appendMessage(`Autopilot is currently ${this._autopilot ? "ON ⚡" : "OFF"}. Use /autopilot on or /autopilot off.`, "assistant");
        }
        return;
      }
      if (cmd === "reset") {
        promptInput.value = "";
        this._buildCommandCard({
          icon: "🗑",
          title: "Reset chat",
          detail: "This will clear all messages and start a fresh conversation.",
          danger: true,
          onConfirm: async () => {
            await this._clearHistory();
          },
        });
        return;
      }
      if (cmd === "help") {
        promptInput.value = "";
        this._showHelp(argStr.trim());
        return;
      }
      if (cmd === "session") {
        promptInput.value = "";
        this._handleSessionCommand(argStr.trim());
        return;
      }
      if (["dashboard", "automation", "script", "blueprint", "area"].includes(cmd)) {
        promptInput.value = "";
        this._handleSlashCommand(cmd, argStr);
        return;
      }
    }
    // ─────────────────────────────────────────────────────────────

    const yamlText = this._editor ? this._editor.state.doc.toString() : "";
    const askBtn = this.shadowRoot.getElementById("btn-ask");
    askBtn.disabled = true;
    promptInput.value = "";

    // Add user message to history before sending
    this._addChatHistory("user", prompt);

    this._appendMessage(prompt, "user");
    this._setStatus("Asking AI…");

    try {
      const token = this._hass.auth.data.access_token;

      // Build dashboard list from hass.panels (always available, no API call needed)
      if (this._dashboardList === null) {
        const panels = this._hass.panels || {};
        this._dashboardList = Object.values(panels)
          .filter((p) => p.component_name === "lovelace" && p.url_path
            && p.url_path !== "kyber" && p.url_path !== "lovelace")
          .map((p) => ({
            title: p.title || p.url_path,
            url_path: p.url_path,
            mode: "storage",
          }));
      }

      // Fetch custom Lovelace resources (custom cards) once per session
      if (this._lovelaceResources === undefined) {
        this._lovelaceResources = [];
        try {
          const resResp = await fetch("/api/lovelace/resources", {
            headers: { Authorization: `Bearer ${token}` },
          });
          if (resResp.ok) {
            const resources = await resResp.json();
            // Extract custom card names from JS resource URLs
            // e.g. /hacsfiles/lovelace-mushroom/mushroom.js → mushroom cards
            this._lovelaceResources = (resources || [])
              .filter((r) => r.type === "module" && r.url)
              .map((r) => r.url);
          }
        } catch (_) { /* non-fatal */ }
      }

      const resp = await fetch("/api/kyber/complete", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          yaml: yamlText,
          prompt,
          editor_mode: this._editorMode,
          dashboards: this._dashboardList,
          lovelace_resources: this._lovelaceResources || [],
          // Send all prior messages (everything except the just-pushed current user msg),
          // capped at HISTORY_WINDOW most recent entries.
          history: this._chatHistory.slice(0, -1).slice(-this._HISTORY_WINDOW),
          compacted_summary: this._compactedSummary,
        }),
      });

      if (!resp.ok) {
        const err = await resp.text();
        throw new Error(`${resp.status}: ${err}`);
      }

      const data = await resp.json();
      // Store the assistant's text reply in history
      const textOnly = data.response
        .replace(/```yaml[\s\S]*?```/gi, "")
        .replace(/```plan[\s\S]*?```/gi, "")
        .trim();
      if (textOnly) {
        this._addChatHistory("assistant", textOnly);
      }
      this._appendAIResponse(data.response, data.yaml_blocks || [], data.plan || null);
      this._setStatus("Done");

      // Compact overflow messages in the background
      this._maybeCompact();
    } catch (err) {
      this._appendMessage(`Error: ${err.message}`, "error");
      this._setStatus(`AI error: ${err.message}`, "error");
    } finally {
      askBtn.disabled = false;
    }
  }

  // Render text with **bold** words as inline clickable adornment buttons.
  // onChoiceClick receives the label text when a button is clicked.
  _renderTextWithAdornments(text, onChoiceClick) {
    const frag = document.createDocumentFragment();
    // Split on **bold** markers, keeping delimiters
    const parts = text.split(/(\*\*[^*\n]+\*\*)/g);
    parts.forEach((part) => {
      const boldMatch = part.match(/^\*\*([^*]+)\*\*$/);
      if (boldMatch) {
        const btn = document.createElement("button");
        btn.className = "inline-choice";
        btn.textContent = boldMatch[1];
        btn.addEventListener("click", () => {
          // Mark all sibling inline-choices as used so only one fires per message
          const msg = btn.closest(".chat-message");
          if (msg) msg.querySelectorAll(".inline-choice").forEach((b) => b.classList.add("used"));
          onChoiceClick(boldMatch[1]);
        });
        frag.appendChild(btn);
      } else {
        frag.appendChild(document.createTextNode(part));
      }
    });
    return frag;
  }

  _extractSuggestions(text) {
    const chips = [];

    // Strategy 1: **bold** action words from bullet list items
    const bulletLines = text.match(/^[\-\*•]\s+.+$/gm) || [];
    if (bulletLines.length >= 2) {
      bulletLines.forEach((line) => {
        const boldMatch = line.match(/\*\*([^*]{1,30})\*\*/);
        if (boldMatch) {
          const label = boldMatch[1].charAt(0).toUpperCase() + boldMatch[1].slice(1);
          if (!chips.includes(label)) chips.push(label);
        }
      });
      if (chips.length >= 2) return chips.slice(0, 6);

      // No bold — extract short verb phrase from each bullet
      chips.length = 0;
      bulletLines.forEach((line) => {
        const cleaned = line
          .replace(/^[\-\*•]\s+/, "")
          .replace(/^(or |and |also )?(do you want to |would you prefer to |would you like to |please |i can )/i, "")
          .replace(/\?.*$/, "")
          .trim();
        const words = cleaned.split(/\s+/).slice(0, 3);
        const label = words[0].charAt(0).toUpperCase() + words[0].slice(1) + (words[1] ? " " + words[1] : "");
        if (label.length > 1 && label.length < 35 && !chips.includes(label)) chips.push(label);
      });
      if (chips.length >= 2) return chips.slice(0, 6);
      chips.length = 0;
    }

    // Strategy 2: Yes/No binary confirm
    if (/\b(yes|no)\b/i.test(text) && /confirm|proceed|sure/i.test(text)) {
      return ["Yes", "No"];
    }

    // Strategy 3: Quoted strings, strip (e.g., ...) first
    const strippedText = text
      .replace(/\(e\.g\.[^)]*\)/gi, "")
      .replace(/for example[^.,]*/gi, "")
      .replace(/such as[^.,]*/gi, "");
    const allQuoted = [...strippedText.matchAll(/"([^"]{1,40})"/g)].map((m) => m[1]);
    if (allQuoted.length >= 2) {
      allQuoted.forEach((v) => { if (!chips.includes(v)) chips.push(v); });
      return chips.slice(0, 6);
    }

    return chips;
  }

  _appendMessage(text, type) {
    const history = this.shadowRoot.getElementById("chat-history");
    const msg = document.createElement("div");
    msg.className = `chat-message ${type}`;
    msg.textContent = text;
    history.appendChild(msg);
    history.scrollTop = history.scrollHeight;
  }

  _appendAIResponse(fullText, yamlBlocks, plan) {
    const history = this.shadowRoot.getElementById("chat-history");

    // Show the text portion (strip yaml/plan blocks for cleaner display)
    const textOnly = fullText
      .replace(/```yaml[\s\S]*?```/gi, "")
      .replace(/```plan[\s\S]*?```/gi, "")
      .trim();
    if (textOnly) {
      const msg = document.createElement("div");
      msg.className = "chat-message assistant";

      const hasBold = /\*\*[^*\n]+\*\*/.test(textOnly);
      const isQuestion = /\?/.test(textOnly);

      if (hasBold) {
        // Render **bold** words as inline adornment buttons
        const onChoiceClick = (label) => {
          const input = this.shadowRoot.getElementById("prompt-input");
          if (input) input.value = label;
          this._askAI();
        };
        msg.appendChild(this._renderTextWithAdornments(textOnly, onChoiceClick));
      } else {
        msg.textContent = textOnly;
      }

      history.appendChild(msg);

      // Fallback chips for non-bold question responses (e.g. Yes/No or quoted options)
      if (isQuestion && !hasBold && !plan) {
        const chips = this._extractSuggestions(textOnly);
        if (chips.length >= 2) {
          const chipRow = document.createElement("div");
          chipRow.className = "suggestion-chips";
          chips.forEach((label) => {
            const btn = document.createElement("button");
            btn.className = "suggestion-chip";
            btn.textContent = label;
            btn.addEventListener("click", () => {
              const input = this.shadowRoot.getElementById("prompt-input");
              if (input) input.value = label;
              chipRow.remove();
              this._askAI();
            });
            chipRow.appendChild(btn);
          });
          history.appendChild(chipRow);
        }
      }
    }

    // Handle plan blocks
    if (plan) {
      if (plan.open_dashboard) {
        const card = this._buildOpenDashboardPrompt(plan);
        history.appendChild(card);
        if (this._autopilot) {
          setTimeout(() => card.querySelector(".btn-open-editor")?.click(), 300);
        }
      } else if (plan.open_editor) {
        const card = this._buildOpenEditorPrompt(plan);
        history.appendChild(card);
        if (this._autopilot) {
          setTimeout(() => card.querySelector(".btn-open-editor")?.click(), 300);
        }
      } else if (plan.actions && plan.actions.length > 0) {
        history.appendChild(this._buildPlanCard(plan));
      }
    }

    // Show each YAML block with an Apply button (when editor is open)
    yamlBlocks.forEach((block) => {
      const container = document.createElement("div");
      container.className = "yaml-suggestion";
      const label = this._editorMode === "dashboard" ? "⬆ Apply to dashboard" : "⬆ Apply to editor";
      container.innerHTML = `
        <pre>${this._escapeHtml(block)}</pre>
        <button>${label}</button>
      `;
      const applyBtn = container.querySelector("button");
      applyBtn.addEventListener("click", () => {
        this._setEditorContent(block);
        applyBtn.disabled = true;
        applyBtn.textContent = "✓ Applied";
        this._setStatus(this._editorMode === "dashboard"
          ? "Dashboard YAML applied — review and Save when ready."
          : "Suggestion applied — review and save when ready.");
      });
      history.appendChild(container);
      // Autopilot: auto-apply YAML when editor is already open
      if (this._autopilot && this.shadowRoot.getElementById("editor-container")?.classList.contains("open")) {
        setTimeout(() => applyBtn.click(), 300);
      }
    });

    history.scrollTop = history.scrollHeight;
  }

  _buildOpenDashboardPrompt(plan) {
    const card = document.createElement("div");
    card.className = "open-editor-prompt";
    const targetLabel = plan.url_path ? ` (${plan.url_path})` : "";
    card.innerHTML = `
      <div class="open-editor-summary">${this._escapeHtml(plan.summary || "Edit dashboard")}</div>
      <button class="btn-open-editor">📊 Open dashboard editor${this._escapeHtml(targetLabel)}</button>
    `;
    card.querySelector(".btn-open-editor").addEventListener("click", () => {
      this._openDashboard(plan.url_path || null);
      const btn = card.querySelector(".btn-open-editor");
      btn.disabled = true;
      btn.textContent = "✓ Dashboard editor opened";
    });
    return card;
  }

  _buildOpenEditorPrompt(plan) {
    const card = document.createElement("div");
    card.className = "open-editor-prompt";

    card.innerHTML = `
      <div class="open-editor-summary">${this._escapeHtml(plan.summary || "Edit automation")}</div>
      <button class="btn-open-editor">📝 Open YAML editor</button>
    `;

    card.querySelector(".btn-open-editor").addEventListener("click", () => {
      this._openEditor(plan.automation_id);
      const btn = card.querySelector(".btn-open-editor");
      btn.disabled = true;
      btn.textContent = "✓ Editor opened";
    });

    return card;
  }

  _buildPlanCard(plan) {
    const card = document.createElement("div");
    card.className = "plan-card";

    const typeLabels = {
      assign_area: "Area",
      rename_entity: "Name",
      assign_label: "Label",
      remove_label: "Remove label",
      create_area: "Create area",
      rename_area: "Rename area",
      delete_area: "Delete area",
      call_service: "Service",
    };

    // Area-only action types don't need an entity_id
    const areaOnlyTypes = new Set(["create_area", "rename_area", "delete_area"]);
    // Service calls validate entity_id differently (may be optional)
    const serviceTypes = new Set(["call_service"]);

    // Validate entity_ids before rendering
    const invalidEntities = new Set();
    (plan.actions || []).forEach((a) => {
      if (a.entity_id && !areaOnlyTypes.has(a.type) && !serviceTypes.has(a.type)) {
        if (!this._hass || !this._hass.states[a.entity_id]) {
          invalidEntities.add(a.entity_id);
        }
      }
    });

    const changeRows = (plan.actions || [])
      .map((a) => {
        const missing = a.entity_id && invalidEntities.has(a.entity_id);
        const entityHtml = a.entity_id
          ? `<span class="change-entity${missing ? " entity-missing" : ""}">${this._escapeHtml(a.entity_id)}${missing ? " ⚠" : ""}</span>`
          : "";
        // For service calls, show domain.service as the badge
        const typeLabel = a.type === "call_service"
          ? `${a.domain || "?"}.${a.service || "?"}`
          : (typeLabels[a.type] || a.type);
        const from = a.current_state
          ? `<span class="plan-from">${this._escapeHtml(String(a.current_state))}</span>`
          : "";
        const to = a.new_state
          ? `<span class="plan-to">${this._escapeHtml(String(a.new_state))}</span>`
          : "";
        const arrow = from && to ? `${from} → ${to}` : from || to;
        return `
          <li class="change-row${missing ? " row-invalid" : ""}">
            ${entityHtml}
            <span class="change-type-badge">${this._escapeHtml(typeLabel)}</span>
            <span class="change-delta">${arrow}</span>
          </li>`;
      })
      .join("");

    const warnings = (plan.warnings || [])
      .map((w) => `<div class="plan-warning">⚠ ${this._escapeHtml(w)}</div>`)
      .join("");

    const missingWarning = invalidEntities.size > 0
      ? `<div class="plan-warning plan-warning-error">⛔ ${invalidEntities.size} entity ID(s) not found in Home Assistant: ${[...invalidEntities].map((e) => this._escapeHtml(e)).join(", ")}. These actions will be skipped.</div>`
      : "";

    // Only allow executing actions whose entity_ids are valid (or are area-only / service calls)
    const executableActions = (plan.actions || []).filter(
      (a) => !a.entity_id || areaOnlyTypes.has(a.type) || serviceTypes.has(a.type) || !invalidEntities.has(a.entity_id)
    );
    const hasExecutable = executableActions.length > 0;

    card.innerHTML = `
      <div class="plan-overview">
        <div class="plan-overview-label">📋 Proposal</div>
        <div class="plan-overview-summary">${this._escapeHtml(plan.summary || "")}</div>
      </div>
      <div class="plan-changes-header">What will change</div>
      <ul class="plan-changes">${changeRows}</ul>
      ${missingWarning}
      ${warnings}
      ${this._autopilot && hasExecutable
        ? `<div class="plan-result" style="color:var(--warning-color,#ff9800);font-size:12px">⚡ Autopilot: executing in 2s…</div>`
        : `<button class="btn-execute"${hasExecutable ? "" : " disabled"}>✅ Execute${invalidEntities.size > 0 && hasExecutable ? ` (${executableActions.length} of ${(plan.actions || []).length})` : ""}</button>`
      }
      <div class="plan-result" id="plan-result-${Date.now()}"></div>
    `;

    // Grab the result element (last .plan-result in card)
    const allResults = card.querySelectorAll(".plan-result");
    const resultEl = allResults[allResults.length - 1];

    const doExecute = async () => {
      if (card.querySelector(".btn-execute")) {
        card.querySelector(".btn-execute").disabled = true;
      }
      resultEl.textContent = "Executing…";
      resultEl.className = "plan-result";
      try {
        const token = this._hass.auth.data.access_token;
        const resp = await fetch("/api/kyber/execute", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({ actions: executableActions }),
        });
        const data = await resp.json();
        const failed = (data.results || []).filter((r) => r.status !== "ok");
        if (failed.length === 0) {
          resultEl.textContent = `✅ Done — ${executableActions.length} action(s) applied.`;
          resultEl.className = "plan-result success";

          const ok = (data.results || []).filter((r) => r.status === "ok");
          const changeLines = ok.map((r) => {
            const action = executableActions.find(
              (a) => (a.entity_id && a.entity_id === r.entity_id) ||
                      (a.area_id && a.area_id === r.area_id) ||
                      (!a.entity_id && !a.area_id && r.type === a.type)
            ) || executableActions[ok.indexOf(r)] || {};
            const desc = action.description || "";
            const fromTo = action.current_state && action.new_state
              ? `${action.current_state} → ${action.new_state}`
              : "";
            const target = action.entity_id || action.area_id || r.entity_id || r.area_id || "";
            const svcLabel = action.type === "call_service"
              ? `${action.domain}.${action.service}`
              : (action.type || "change");
            return `- ${svcLabel}${target ? " on " + target : ""}${fromTo ? ": " + fromTo : ""}${desc ? " (" + desc + ")" : ""}`;
          });

          this._addChatHistory("user", `I clicked Execute on the proposal: "${plan.summary || ""}".`);
          this._addChatHistory("assistant", `[CHANGE] The following changes were successfully applied:\n${changeLines.join("\n")}`);

          // Collect undo actions from results and show Undo button
          const undoActions = ok
            .map((r) => r.undo_action)
            .filter(Boolean);
          if (undoActions.length > 0) {
            const undoBtn = document.createElement("button");
            undoBtn.className = "btn-undo";
            undoBtn.textContent = `↩ Undo (${undoActions.length} action${undoActions.length > 1 ? "s" : ""})`;
            resultEl.after(undoBtn);
            undoBtn.addEventListener("click", async () => {
              undoBtn.disabled = true;
              undoBtn.textContent = "Undoing…";
              try {
                const token2 = this._hass.auth.data.access_token;
                const r2 = await fetch("/api/kyber/execute", {
                  method: "POST",
                  headers: { "Content-Type": "application/json", Authorization: `Bearer ${token2}` },
                  body: JSON.stringify({ actions: undoActions }),
                });
                const d2 = await r2.json();
                const f2 = (d2.results || []).filter((r) => r.status !== "ok");
                if (f2.length === 0) {
                  undoBtn.textContent = "↩ Undone ✓";
                  resultEl.textContent = "↩ Changes undone.";
                  resultEl.className = "plan-result";
                  this._addChatHistory("assistant", `[CHANGE] Undid: ${plan.summary || "previous changes"}`);
                } else {
                  undoBtn.textContent = `↩ Undo failed (${f2.length} error${f2.length > 1 ? "s" : ""})`;
                  undoBtn.disabled = false;
                }
              } catch (e) {
                undoBtn.textContent = `↩ Undo error: ${e.message}`;
                undoBtn.disabled = false;
              }
            });
          }
        } else {
          resultEl.textContent = `⚠ ${failed.length} action(s) failed: ${failed.map((r) => r.message).join("; ")}`;
          resultEl.className = "plan-result error";
          if (card.querySelector(".btn-execute")) card.querySelector(".btn-execute").disabled = false;
        }
      } catch (err) {
        resultEl.textContent = `Error: ${err.message}`;
        resultEl.className = "plan-result error";
        if (card.querySelector(".btn-execute")) card.querySelector(".btn-execute").disabled = false;
      }
    };

    if (card.querySelector(".btn-execute")) {
      card.querySelector(".btn-execute").addEventListener("click", doExecute);
    }

    // Autopilot: auto-execute after 2s
    if (this._autopilot && hasExecutable) {
      setTimeout(() => doExecute(), 2000);
    }

    return card;
  }

  _setEditorContent(text) {
    this._editor.dispatch({
      changes: {
        from: 0,
        to: this._editor.state.doc.length,
        insert: text,
      },
    });
  }

  _setStatus(message, type = "") {
    const bar = this.shadowRoot.getElementById("status-bar");
    if (!bar) return;
    const txt = bar.querySelector("#status-text");
    if (txt) {
      txt.textContent = message;
    } else {
      bar.textContent = message;
    }
    bar.className = `status-bar ${type}`;
  }

  _updateAutopilotBadge() {
    const badge = this.shadowRoot.getElementById("autopilot-badge");
    if (badge) badge.classList.toggle("active", this._autopilot);
  }

  _configToYaml(config) {
    // Lightweight JSON→YAML serialiser (sufficient for HA automation objects)
    return this._jsonToYaml(config, 0);
  }

  _jsonToYaml(obj, indent) {
    const pad = "  ".repeat(indent);
    if (obj === null || obj === undefined) return "null";
    if (typeof obj === "boolean") return String(obj);
    if (typeof obj === "number") return String(obj);
    if (typeof obj === "string") {
      if (/[\n:{}[\],&*#?|<>=!%@`]/.test(obj) || obj === "") {
        return JSON.stringify(obj);
      }
      return obj;
    }
    if (Array.isArray(obj)) {
      if (obj.length === 0) return "[]";
      return obj
        .map((item) => `\n${pad}- ${this._jsonToYaml(item, indent + 1).trimStart()}`)
        .join("");
    }
    if (typeof obj === "object") {
      const entries = Object.entries(obj);
      if (entries.length === 0) return "{}";
      return entries
        .map(([k, v]) => {
          const val = this._jsonToYaml(v, indent + 1);
          if (typeof v === "object" && v !== null && !Array.isArray(v) && Object.keys(v).length > 0) {
            return `\n${pad}${k}:${val}`;
          }
          if (Array.isArray(v) && v.length > 0) {
            return `\n${pad}${k}:${val}`;
          }
          return `\n${pad}${k}: ${val}`;
        })
        .join("")
        .trimStart();
    }
    return String(obj);
  }

  _parseYaml(_text) {
    // YAML parsing is handled server-side by the /api/kyber/save endpoint.
    throw new Error("Client-side YAML parsing not implemented.");
  }

  _escapeHtml(str) {
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }
}

customElements.define("kyber-panel", KyberPanel);
