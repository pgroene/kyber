// CSS styles for the KyberPanel shadow DOM
// Extracted from kyber-panel.js — edit here, then rebuild

export const STYLES = `
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
    --card-bg: var(--card-background-color, var(--primary-background-color, #fff));
    --input-bg: var(--secondary-background-color, #f5f5f5);
    --text-muted: var(--secondary-text-color, #888);
  }

  .container {
    display: grid;
    grid-template-rows: 56px 1fr;
    grid-template-columns: 1fr;
    height: 100%;
    position: relative;
    background: var(--panel-bg);
    color: var(--text-color);
  }

  .container.editor-open {
    grid-template-columns: 1fr 1fr;
  }

  .container:not(.editor-open) .editor-controls { display: none !important; }
  /* Hide editor completely in standalone debug mode */
  .container.debug-mode .editor-pane { display: none !important; }
  .container.debug-mode .editor-controls { display: none !important; }
  .container.debug-mode .status-bar { display: none !important; }

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
    position: relative;
  }

  .editor-pane.open {
    display: flex;
    grid-column: 2;
    grid-row: 2;
  }

  .editor-pane .cm-editor {
    flex: 1;
    min-height: 0;
    font-size: 13px;
  }

  /* ── Automation diagram ─────────────────────────────────── */
  .automation-diagram {
    flex: 0 0 auto;
    display: flex;
    flex-direction: row;
    align-items: flex-start;
    gap: 6px;
    padding: 10px 12px;
    background: var(--sidebar-bg);
    border-bottom: 2px solid var(--border-color);
    overflow-x: auto;
    overflow-y: auto;
    min-height: 90px;
    max-height: 50vh;
    scrollbar-width: thin;
  }
  .adg-section {
    display: flex;
    flex-direction: column;
    align-items: stretch;
    gap: 4px;
    min-width: 130px;
    max-width: 170px;
    flex-shrink: 0;
  }
  .adg-label {
    font-size: 9px;
    font-weight: 800;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    color: var(--text-muted, #888);
    text-align: center;
    padding: 2px 4px 5px;
    border-bottom: 1px solid var(--border-color);
    margin-bottom: 3px;
  }
  .adg-nodes { display: flex; flex-direction: column; gap: 5px; }
  .adg-node-wrapper { display: flex; flex-direction: column; gap: 3px; }
  .adg-children { display: flex; flex-direction: column; gap: 3px; padding-left: 2px; border-left: 2px solid var(--accent, #03a9f4); margin-left: 8px; }
  .adg-node {
    display: flex;
    flex-direction: column;
    padding: 7px 10px;
    background: var(--card-bg, #1e1e2e);
    border: 1px solid var(--border-color);
    border-radius: 7px;
    cursor: pointer;
    transition: border-color 0.15s, background 0.15s, box-shadow 0.15s;
    min-width: 120px;
    max-width: 165px;
    user-select: none;
    position: relative;
  }
  .adg-expand-btn {
    position: absolute; top: 4px; right: 6px;
    font-size: 9px; color: var(--accent);
    padding: 1px 3px; border-radius: 3px;
    transition: transform 0.15s;
  }
  .adg-expanded .adg-expand-btn { transform: rotate(90deg); }
  .adg-node:hover {
    border-color: var(--accent);
    background: color-mix(in srgb, var(--accent) 10%, var(--card-bg, #1e1e2e));
  }
  .adg-trigger  { border-left: 3px solid #4caf50; }
  .adg-condition{ border-left: 3px solid #ff9800; }
  .adg-action   { border-left: 3px solid #2196f3; }
  .adg-trigger.adg-active  { border-color: #4caf50; background: rgba(76,175,80,0.18); box-shadow: 0 0 0 2px rgba(76,175,80,0.3); }
  .adg-condition.adg-active{ border-color: #ff9800; background: rgba(255,152,0,0.18); box-shadow: 0 0 0 2px rgba(255,152,0,0.3); }
  .adg-action.adg-active   { border-color: #2196f3; background: rgba(33,150,243,0.18); box-shadow: 0 0 0 2px rgba(33,150,243,0.3); }
  .adg-sub-node { opacity: 0.85; border-left-width: 2px; border-left-style: dashed; padding: 5px 8px; }
  .adg-expandable { cursor: pointer; }
  .adg-icon  { font-size: 14px; line-height: 1; margin-bottom: 4px; }
  .adg-title { font-size: 11px; font-weight: 600; color: var(--text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 145px; }
  .adg-sub   { font-size: 10px; color: var(--text-muted, #999); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 145px; margin-top: 2px; }
  .adg-arrow {
    display: flex;
    align-items: flex-start;
    justify-content: center;
    font-size: 20px;
    color: var(--text-muted, #666);
    padding: 28px 4px 0;
    flex-shrink: 0;
  }

  /* Blueprint info panel (shown instead of diagram for use_blueprint automations) */
  .adg-blueprint-info {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 4px 2px;
    min-width: 260px;
  }
  .adg-bp-header { font-size: 12px; color: var(--text-color); }
  .adg-bp-inputs { display: flex; flex-direction: column; gap: 3px; }
  .adg-bp-row { font-size: 11px; }
  .adg-bp-key { color: var(--text-muted, #888); }
  .adg-bp-val { color: var(--accent); }

  /* ── Entity inspector (floating overlay) ────────────────── */
  .entity-inspector {
    position: absolute;
    right: 12px;
    top: 80px;
    width: 230px;
    max-height: 260px;
    overflow-y: auto;
    background: var(--card-bg, #1e1e2e);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    box-shadow: 0 4px 16px rgba(0,0,0,0.35);
    font-size: 12px;
    z-index: 20;
    scrollbar-width: thin;
  }
  .ei-header {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 6px 10px;
    background: var(--sidebar-bg);
    border-bottom: 1px solid var(--border-color);
    border-radius: 8px 8px 0 0;
    position: sticky;
    top: 0;
    z-index: 1;
  }
  .ei-header-main { display: flex; flex-direction: column; flex: 1; min-width: 0; }
  .ei-friendly { font-size: 12px; font-weight: 600; color: var(--text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .ei-entity { font-weight: 400; font-size: 10px; color: var(--text-muted, #999); font-family: monospace; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .ei-state  { font-size: 11px; padding: 2px 7px; border-radius: 10px; background: var(--border-color); flex-shrink: 0; }
  .ei-on  { background: rgba(76,175,80,0.25); color: #4caf50; }
  .ei-off { background: rgba(255,82,82,0.15); color: #ff5252; }
  .ei-close { margin-left: 2px; background: none; border: none; cursor: pointer; color: var(--text-muted); font-size: 14px; padding: 0 2px; flex-shrink: 0; }
  .ei-body { padding: 4px 0; }
  .ei-table { width: 100%; border-collapse: collapse; }
  .ei-table td { padding: 2px 10px; vertical-align: top; border-bottom: 1px solid color-mix(in srgb, var(--border-color) 40%, transparent); }
  .ei-key { color: var(--text-muted); white-space: nowrap; font-family: monospace; font-size: 10px; width: 40%; }
  .ei-val { color: var(--text-color); word-break: break-all; font-size: 11px; }

  /* ── Entity list picker (floating add-entity widget) ────── */
  .entity-list-picker {
    position: absolute;
    right: 12px;
    top: 80px;
    width: 240px;
    max-height: 300px;
    display: flex;
    flex-direction: column;
    background: var(--card-bg, #1e1e2e);
    border: 1px solid var(--accent, #03a9f4);
    border-radius: 8px;
    box-shadow: 0 4px 18px rgba(0,0,0,0.4);
    font-size: 12px;
    z-index: 21;
    overflow: hidden;
  }
  .elp-header {
    display: flex;
    align-items: center;
    padding: 6px 10px;
    background: var(--sidebar-bg);
    border-bottom: 1px solid var(--border-color);
    border-radius: 8px 8px 0 0;
    gap: 6px;
  }
  .elp-title { font-size: 11px; font-weight: 700; flex: 1; color: var(--accent, #03a9f4); }
  .elp-close { background: none; border: none; cursor: pointer; color: var(--text-muted); font-size: 13px; padding: 0 2px; }
  .elp-search {
    width: 100%; box-sizing: border-box;
    border: none; border-bottom: 1px solid var(--border-color);
    background: var(--input-bg, #2a2a3e);
    color: var(--text-color);
    padding: 6px 10px;
    font-size: 12px;
    outline: none;
  }
  .elp-results { flex: 1; overflow-y: auto; scrollbar-width: thin; }
  .elp-item {
    display: flex; align-items: center; gap: 6px;
    padding: 5px 10px; cursor: pointer;
    border-bottom: 1px solid color-mix(in srgb, var(--border-color) 40%, transparent);
  }
  .elp-item:hover { background: color-mix(in srgb, var(--accent) 12%, var(--card-bg, #1e1e2e)); }
  .elp-name { font-weight: 500; font-size: 11px; flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .elp-id { font-size: 10px; color: var(--text-muted); font-family: monospace; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 80px; }
  .elp-empty { padding: 12px; color: var(--text-muted); font-size: 11px; text-align: center; }
  .elp-current { border-bottom: 1px solid var(--border-color); padding: 4px 6px; display: flex; flex-wrap: wrap; gap: 4px; }
  .elp-current-item {
    display: flex; align-items: center; gap: 4px;
    background: color-mix(in srgb, var(--accent) 14%, var(--card-bg, #1e1e2e));
    border: 1px solid var(--accent, #03a9f4); border-radius: 12px;
    padding: 2px 6px; font-size: 10px; max-width: 180px;
  }
  .elp-current-item .elp-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .elp-remove { background: none; border: none; cursor: pointer; color: var(--text-muted); font-size: 10px; padding: 0; line-height: 1; flex-shrink: 0; }

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
    padding: 6px 12px;
    border-bottom: 1px solid var(--border-color);
    background: var(--sidebar-bg);
    font-size: 13px;
    font-weight: 600;
  }

  .sidebar-brand .btn-clear-history {
    margin-left: auto;
    height: 28px;
    padding: 0 10px;
    font-size: 11px;
    font-weight: 500;
    background: transparent;
    color: var(--secondary-text-color, #aaa);
    border: 1px solid var(--border-color);
    border-radius: 4px;
    cursor: pointer;
  }

  .sidebar-brand .btn-clear-history:hover {
    background: var(--border-color);
  }

  .explorer-banner {
    padding: 6px 12px;
    font-size: 12px;
    color: var(--primary-color, #03a9f4);
    background: color-mix(in srgb, var(--primary-color, #03a9f4) 12%, transparent);
    border-left: 3px solid var(--primary-color, #03a9f4);
  }

  .warning-banner {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    font-size: 13px;
    color: #fff;
    background: #c0392b;
    border-left: 4px solid #922b21;
  }
  .warning-banner span { flex: 1; }
  .warning-banner button {
    background: none;
    border: none;
    color: #fff;
    font-size: 16px;
    cursor: pointer;
    padding: 0 4px;
    opacity: 0.8;
  }
  .warning-banner button:hover { opacity: 1; }

  .chat-history {
    flex: 1;
    min-height: 0;
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

  /* Markdown-rendered content inside assistant messages */
  .chat-message.assistant ul,
  .chat-message.assistant ol {
    margin: 4px 0;
    padding-left: 18px;
  }
  .chat-message.assistant li { margin: 2px 0; line-height: 1.4; }
  .chat-message.assistant ul li::marker { color: var(--primary-color, #03a9f4); }
  .chat-message.assistant li > ul,
  .chat-message.assistant li > ol { margin: 2px 0; }
  .chat-message.assistant p { margin: 4px 0; line-height: 1.5; }
  .chat-message.assistant p:first-child { margin-top: 0; }
  .chat-message.assistant p:last-child  { margin-bottom: 0; }
  .chat-message.assistant h4,
  .chat-message.assistant h5,
  .chat-message.assistant h6 {
    margin: 8px 0 2px 0;
    font-size: 13px;
    font-weight: 600;
    color: var(--primary-text-color);
  }
  .chat-message.assistant strong { font-weight: 600; }

  .chat-message.error {
    background: var(--danger);
    color: white;
  }

  .chat-message.system-info {
    align-self: center;
    font-size: 11px;
    color: var(--secondary-text-color, #888);
    background: transparent;
    border: 1px solid var(--border-color);
    border-radius: 10px;
    padding: 3px 10px;
    max-width: 90%;
    text-align: center;
  }

  .tool-log {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    align-self: flex-start;
    margin: 2px 0 4px 0;
  }

  .tool-pill {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 11px;
    color: var(--secondary-text-color, #888);
    background: var(--secondary-background-color, #2c2c2e);
    border: 1px solid var(--border-color);
    border-radius: 10px;
    padding: 2px 8px;
    white-space: nowrap;
  }

  .tool-pill .tool-icon { opacity: 0.7; }
  .tool-pill .tool-name { font-weight: 600; color: var(--accent, #03a9f4); }

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
  .suggestion-chip.chip-more {
    border-style: dashed; opacity: 0.7;
  }
  .suggestion-chip.chip-more:hover { opacity: 1; }

  /* Entity chips — inline entity references with icon + name + state */
  .entity-chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    background: color-mix(in srgb, var(--primary-color, #03a9f4) 10%, var(--card-background-color, #1e2530));
    border: 1px solid color-mix(in srgb, var(--primary-color, #03a9f4) 35%, transparent);
    border-radius: 12px;
    padding: 1px 8px 1px 4px;
    font-size: 12px;
    vertical-align: middle;
    white-space: nowrap;
    cursor: pointer;
    line-height: 1.6;
    transition: background 0.15s, border-color 0.15s;
  }
  .entity-chip:hover {
    background: color-mix(in srgb, var(--primary-color, #03a9f4) 20%, var(--card-background-color, #1e2530));
    border-color: color-mix(in srgb, var(--primary-color, #03a9f4) 55%, transparent);
  }
  .entity-chip .entity-chip-icon { font-size: 13px; }
  .entity-chip .entity-chip-name { font-weight: 600; color: var(--primary-text-color, #e0e0e0); }
  .entity-chip .entity-chip-state {
    font-size: 11px;
    opacity: 0.7;
    margin-left: 2px;
  }

  /* Entity grid in tool result previews */
  .entity-result-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 6px;
    padding: 8px 0;
  }
  .entity-result-card {
    display: flex;
    align-items: center;
    gap: 8px;
    background: color-mix(in srgb, var(--primary-color, #03a9f4) 6%, var(--card-background-color, #1e2530));
    border: 1px solid color-mix(in srgb, var(--primary-color, #03a9f4) 20%, transparent);
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 12px;
    overflow: hidden;
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s;
  }
  .entity-result-card:hover {
    background: color-mix(in srgb, var(--primary-color, #03a9f4) 14%, var(--card-background-color, #1e2530));
    border-color: color-mix(in srgb, var(--primary-color, #03a9f4) 45%, transparent);
  }
  .entity-result-card .erc-icon { font-size: 18px; flex-shrink: 0; }
  .entity-result-card .erc-body { overflow: hidden; min-width: 0; flex: 1; }
  .entity-result-card .erc-name { font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .entity-result-card .erc-id { font-size: 10px; opacity: 0.55; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .entity-result-card .erc-state { font-size: 11px; opacity: 0.75; margin-top: 1px; }

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

  .memory-card {
    background: rgba(103, 58, 183, 0.07);
    border: 1px solid rgba(103, 58, 183, 0.30);
    border-radius: 8px;
    padding: 10px 14px;
    margin: 6px 0;
    font-size: 13px;
  }
  .memory-card-header {
    font-weight: 600;
    font-size: 13px;
    color: rgb(149, 117, 205);
    margin-bottom: 6px;
  }
  .memory-card-content {
    margin-bottom: 8px;
    line-height: 1.4;
  }
  .btn-remember {
    background: linear-gradient(135deg, #673ab7, #9c27b0);
    color: #fff;
    border: none;
    border-radius: 6px;
    padding: 5px 14px;
    font-size: 12px;
    cursor: pointer;
    font-weight: 600;
  }
  .btn-remember:hover { filter: brightness(1.15); }
  .btn-remember:disabled { opacity: 0.5; cursor: default; filter: none; }

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

  .plan-approval-note {
    background: rgba(255, 152, 0, 0.12);
    border-left: 3px solid var(--warning-color, #ff9800);
    color: var(--primary-text-color, #ddd);
    padding: 8px 10px;
    margin: 8px 0;
    font-size: 12px;
    border-radius: 4px;
  }

  /* Per-turn feedback banner (Debug → Last turn) */
  .dbg-turn-feedback {
    display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
    padding: 10px 12px; margin-bottom: 12px;
    background: var(--card-background-color, rgba(255,255,255,0.04));
    border: 1px solid var(--divider-color); border-radius: 6px;
    font-size: 12px;
  }
  .dbg-turn-feedback .tf-label { font-weight: 600; }
  .dbg-turn-feedback .tf-btn {
    background: transparent; border: 1px solid var(--divider-color);
    color: inherit; cursor: pointer; padding: 4px 10px; border-radius: 4px;
    font-size: 14px; line-height: 1;
  }
  .dbg-turn-feedback .tf-btn:hover:not(:disabled) { background: rgba(255,255,255,0.08); }
  .dbg-turn-feedback .tf-btn:disabled { opacity: 0.4; cursor: default; }
  .dbg-turn-feedback .tf-btn.tf-bundle { font-size: 12px; margin-left: auto; }
  .dbg-turn-feedback .tf-btn.tf-bug-report { font-size: 12px; }
  /* Bug report modal */
  .bug-report-overlay {
    position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: 9999;
    display: flex; align-items: center; justify-content: center;
  }
  .bug-report-dialog {
    background: var(--card-background-color, #1e1e2e);
    border: 1px solid var(--divider-color, #444);
    border-radius: 12px; padding: 24px; width: 560px; max-width: 95vw;
    max-height: 90vh; overflow-y: auto; box-shadow: 0 8px 32px rgba(0,0,0,0.4);
    display: flex; flex-direction: column; gap: 14px;
    color: var(--primary-text-color, #e0e0e0);
  }
  .bug-report-dialog h3 { margin: 0; font-size: 16px; }
  .bug-report-dialog label { font-size: 13px; display: flex; flex-direction: column; gap: 4px; }
  .bug-report-dialog textarea {
    background: var(--secondary-background-color, #2a2a3e);
    border: 1px solid var(--divider-color, #444); border-radius: 6px;
    color: inherit; padding: 8px; font-size: 13px; resize: vertical; font-family: inherit;
  }
  .bug-report-dialog textarea:focus { outline: none; border-color: var(--primary-color, #4a9eff); }
  .bug-report-checkbox { flex-direction: row !important; align-items: center; gap: 8px !important; }
  .bug-report-actions { display: flex; gap: 8px; justify-content: flex-end; }
  .bug-report-actions button { padding: 8px 16px; border-radius: 6px; cursor: pointer; font-size: 13px; border: none; }
  .bug-report-btn-submit { background: var(--primary-color, #4a9eff); color: #fff; }
  .bug-report-btn-submit:disabled { opacity: 0.5; cursor: default; }
  .bug-report-btn-cancel { background: var(--secondary-background-color, #2a2a3e); color: inherit; border: 1px solid var(--divider-color, #444) !important; }
  .bug-report-similar { font-size: 12px; }
  .bug-report-similar a { color: var(--primary-color, #4a9eff); }
  .bug-report-result-title input {
    width: 100%; background: var(--secondary-background-color, #2a2a3e);
    border: 1px solid var(--divider-color, #444); border-radius: 6px;
    color: inherit; padding: 8px; font-size: 13px; box-sizing: border-box;
  }
  .bug-report-spinner { text-align: center; padding: 24px; font-size: 14px; }
  .dbg-turn-feedback .tf-auto { color: var(--warning-color, #ff9800); font-size: 11px; }
  .dbg-turn-feedback .tf-status { color: var(--secondary-text-color, #aaa); font-size: 11px; }
  .dbg-turn-feedback .tf-status.ok { color: var(--success-color, #4caf50); }
  .dbg-turn-feedback .tf-status.flag { color: var(--warning-color, #ff9800); }

  /* Wrapper for AI message + its action row (enables hover-to-reveal) */
  .ai-message-wrap {
    display: flex; flex-direction: column; align-items: flex-start;
  }

  /* Inline chat feedback row (thumbs up/down under AI responses) */
  .chat-feedback-row {
    display: flex; align-items: center; gap: 4px;
    margin: 2px 0 6px 4px; opacity: 0;
    transition: opacity 0.15s;
    align-self: flex-start;
  }
  .ai-message-wrap:hover .chat-feedback-row { opacity: 1; }
  .chat-feedback-row:hover { opacity: 1; }
  .chat-feedback-row .tf-btn-rate {
    background: none; border: none; cursor: pointer;
    font-size: 14px; padding: 1px 4px; border-radius: 4px;
    line-height: 1;
  }
  .chat-feedback-row .tf-btn-rate:hover:not(:disabled) { background: rgba(255,255,255,0.08); }
  .chat-feedback-row .tf-btn-rate:disabled { opacity: 0.35; cursor: default; }
  .chat-feedback-row .tf-status {
    font-size: 11px; color: var(--secondary-text-color, #aaa); margin-left: 2px;
  }
  .chat-feedback-row .tf-status.ok { color: var(--success-color, #4caf50); }
  .chat-feedback-row .tf-status.flag { color: var(--warning-color, #ff9800); }

  /* Copy button on user messages */
  .chat-message-wrap { position: relative; display: flex; align-items: center; gap: 4px; }
  .chat-message-wrap .chat-copy-btn {
    flex-shrink: 0; align-self: center;
    background: none; border: none; cursor: pointer; font-size: 13px;
    opacity: 0; transition: opacity 0.15s; padding: 1px 3px; border-radius: 3px;
  }
  .chat-message-wrap:hover .chat-copy-btn { opacity: 0.6; }
  .chat-message-wrap .chat-copy-btn:hover { opacity: 1 !important; background: rgba(255,255,255,0.08); }

  /* Retry button on error messages */
  .chat-retry-btn {
    display: inline-block; margin-top: 4px;
    background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.25);
    color: inherit; border-radius: 4px; padding: 2px 10px;
    cursor: pointer; font-size: 12px;
  }
  .chat-retry-btn:hover { background: rgba(255,255,255,0.18); }

  /* Alias-learned chip shown after AI response */
  .chat-alias-learned {
    font-size: 11px; color: var(--success-color, #4caf50);
    background: rgba(76,175,80,0.1); border-radius: 4px;
    padding: 2px 8px; margin: 2px 0 6px 4px; display: inline-block;
  }

  /* Knowledge panel */
  .kyber-knowledge-panel { font-size: 12px; }
  .kn-header { display: flex; gap: 10px; align-items: center; margin-bottom: 6px; }
  .kn-header .kn-count { color: var(--secondary-text-color, #aaa); font-size: 11px; }
  .btn-kn-review-filter {
    margin-left: auto;
    background: rgba(255,152,0,0.15); border: 1px solid var(--warning-color, #ff9800);
    color: var(--warning-color, #ff9800); border-radius: 4px;
    padding: 2px 8px; cursor: pointer; font-size: 11px;
  }
  .kn-actions-bar { display: flex; gap: 6px; margin-bottom: 8px; }
  .kn-actions-bar button {
    background: var(--primary-color, #03a9f4); border: none; color: white;
    padding: 4px 10px; border-radius: 4px; cursor: pointer; font-size: 11px;
  }
  .kn-empty { color: var(--secondary-text-color, #888); padding: 8px 0; }
  .kn-list { display: flex; flex-direction: column; gap: 6px; }

  .btn-debug {
    background: transparent; color: var(--secondary-text-color);
    border: 1px solid var(--divider-color); padding: 4px 8px;
    border-radius: 4px; cursor: pointer; font-size: 13px;
  }
  .btn-debug:hover { color: var(--primary-color); border-color: var(--primary-color); }
  .debug-pane {
    flex: 0 0 auto;
    display: flex;
    flex-direction: column;
    height: 260px;
    border-top: 2px solid var(--divider-color);
    background: var(--primary-background-color, #fafafa);
    overflow: hidden;
  }
  .debug-pane[hidden] { display: none !important; }
  .chat-pane.debug-standalone > *:not(#debug-pane) { display: none !important; }
  .chat-pane.debug-standalone > #debug-pane { flex: 1; height: auto; border-top: none; }
  .debug-pane--standalone {
    position: absolute; inset: 0;
    height: 100%;
    background: var(--primary-background-color, #fafafa);
    z-index: 5;
    border-top: none;
  }
  .debug-header {
    display: flex; align-items: center; gap: 8px;
    border-bottom: 1px solid var(--divider-color);
    padding: 6px 10px;
    flex: 0 0 auto;
  }
  .debug-header h2 { margin: 0; font-size: 16px; flex: 0 0 auto; }
  .debug-tabs { display: flex; gap: 4px; flex: 1; margin-left: 12px; }
  .debug-tab {
    background: transparent; border: 1px solid var(--divider-color);
    padding: 4px 10px; border-radius: 4px; cursor: pointer;
    color: var(--secondary-text-color); font-size: 12px;
  }
  .debug-tab.active {
    background: var(--primary-color); color: white;
    border-color: var(--primary-color);
  }
  .debug-body { flex: 1; overflow: auto; padding: 8px 12px; }
  .debug-stats {
    background: var(--card-background-color); padding: 8px 10px;
    border-radius: 4px; margin-bottom: 10px; font-size: 12px;
  }
  .debug-toolbar { display: flex; gap: 10px; align-items: center; margin-bottom: 10px; flex-wrap: wrap; font-size: 12px; }
  .debug-toolbar select { font-size: 12px; padding: 2px 4px; }
  .debug-section { margin: 8px 0; border: 1px solid var(--divider-color); border-radius: 4px; padding: 6px 10px; }
  .debug-section summary { cursor: pointer; font-size: 13px; }
  .debug-error { color: var(--error-color); padding: 12px; }
  .debug-empty { color: var(--secondary-text-color); padding: 20px; text-align: center; font-style: italic; }
  .dbg-pre {
    background: var(--code-editor-background-color, #1e1e1e);
    color: var(--code-editor-text-color, #d4d4d4);
    padding: 8px; border-radius: 4px;
    font-size: 11px; max-height: 320px; overflow: auto;
    white-space: pre-wrap; word-break: break-word;
  }
  .dbg-tools { width: 100%; border-collapse: collapse; font-size: 11px; margin-top: 4px; }
  .dbg-tools th, .dbg-tools td { text-align: left; padding: 3px 6px; border-bottom: 1px solid var(--divider-color); }
  .dbg-mono { font-family: monospace; max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .dbg-kv { width: 100%; border-collapse: collapse; font-size: 12px; margin: 4px 0 10px 0; }
  .dbg-kv th { text-align: left; padding: 3px 8px; font-weight: normal; color: var(--secondary-text-color); width: 160px; }
  .dbg-kv td { padding: 3px 8px; }
  .kn-score { background: var(--primary-color); color: white; font-size: 10px; padding: 1px 6px; border-radius: 8px; margin-right: 4px; }
  .btn-kn-refine { background: transparent; border: 1px solid var(--divider-color); color: var(--primary-color); padding: 2px 6px; border-radius: 3px; cursor: pointer; font-size: 11px; margin-right: 4px; }
  .btn-kn-refine:hover { background: var(--primary-color); color: white; }
  .kn-row {
    background: rgba(255,255,255,0.04);
    border-left: 3px solid var(--primary-color, #03a9f4);
    border-radius: 4px; padding: 6px 8px;
  }
  .kn-row-flagged { border-left-color: var(--warning-color, #ff9800); }
  .kn-row-head { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
  .kn-cat {
    background: rgba(3,169,244,0.2); color: var(--primary-color, #03a9f4);
    padding: 1px 6px; border-radius: 3px; font-size: 10px; text-transform: uppercase;
  }
  .kn-subj { font-weight: 600; }
  .kn-needs-review {
    background: rgba(255,152,0,0.2); color: var(--warning-color, #ff9800);
    padding: 1px 6px; border-radius: 3px; font-size: 10px;
  }

  /* ── Review flow (compact rv-* classes) ── */
  .chat-review-queue { border-bottom: 1px solid var(--divider-color, #3a3a3c); }

  /* ── Area approval bar (pinned above chat history) ─────────────────── */
  .area-approval-bar {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 4px 8px;
    border-bottom: 1px solid var(--divider-color, #3a3a3c);
    background: var(--secondary-background-color, #1e1e1e);
  }
  .area-approval-bar:empty { display: none; }
  .area-approval-bar .kyber-area-suggestion-chip {
    margin: 2px 0;
    border-radius: 8px;
  }
  .rv-wrap {
    background: var(--card-background-color, var(--secondary-background-color));
    border-left: 3px solid var(--warning-color, #ff9800);
    padding: 8px 10px;
  }
  .rv-head {
    display: flex; align-items: center; gap: 6px; margin-bottom: 6px; flex-wrap: wrap;
  }
  .rv-title {
    font-weight: 600; font-size: 0.82em; color: var(--warning-color, #ff9800); white-space: nowrap;
  }
  .rv-prog {
    font-size: 0.78em; color: var(--secondary-text-color);
    background: var(--secondary-background-color, rgba(255,255,255,0.08));
    padding: 1px 6px; border-radius: 10px; white-space: nowrap;
  }
  .rv-bar {
    flex: 1; height: 3px; background: var(--divider-color, rgba(255,255,255,0.1));
    border-radius: 2px; overflow: hidden; min-width: 30px;
  }
  .rv-bar-fill {
    height: 100%; background: var(--warning-color, #ff9800);
    border-radius: 2px; transition: width 0.25s;
  }
  .rv-badge {
    font-size: 0.75em; padding: 1px 7px; border-radius: 10px; cursor: pointer;
    border: none; font-weight: 500; white-space: nowrap;
  }
  .rv-badge:hover { opacity: 0.8; }
  .rv-badge--auto   { background: var(--success-color, #4caf50); color: #fff; }
  .rv-badge--reject { background: var(--error-color, #f44336); color: #fff; }
  .rv-card {
    background: var(--secondary-background-color, rgba(255,255,255,0.05));
    border-radius: 5px; padding: 6px 9px; margin-bottom: 6px;
  }
  .rv-content { font-size: 0.9em; line-height: 1.4; color: var(--primary-text-color); }
  .rv-meta { font-size: 0.76em; color: var(--secondary-text-color); margin-top: 3px; }
  /* entity_alias review layout */
  .rv-alias-question { font-size: 0.75em; color: var(--secondary-text-color); margin-bottom: 2px; }
  .rv-alias-term {
    font-size: 1.05em; font-weight: 600; color: var(--primary-text-color);
    margin-bottom: 3px;
  }
  .rv-alias-arrow { font-size: 0.82em; color: var(--secondary-text-color); }
  .rv-entity-id { opacity: 0.65; font-size: 0.9em; }
  .rv-actions {
    display: flex; gap: 5px; align-items: center; flex-wrap: wrap; margin-bottom: 5px;
  }
  .rv-btn {
    padding: 3px 10px; border-radius: 5px; border: none; cursor: pointer;
    font-size: 0.8em; font-weight: 500; transition: opacity 0.15s;
  }
  .rv-btn:hover { opacity: 0.85; }
  .rv-btn-approve { background: var(--success-color, #4caf50); color: #fff; }
  .rv-btn-reject  { background: var(--error-color, #f44336); color: #fff; }
  .rv-btn-skip    { background: transparent; color: var(--secondary-text-color); border: 1px solid var(--divider-color); }
  .rv-skip-group {
    display: flex; align-items: center; gap: 5px; margin-left: auto;
  }
  .review-flow-proposal-icon {
    font-size: 2rem;
    text-align: center;
    margin-bottom: 8px;
  }
  .review-flow-proposal-action {
    font-size: 1rem;
    text-align: center;
    margin-bottom: 6px;
    line-height: 1.4;
  }
  .review-flow-proposal-entity {
    font-size: 0.78rem;
    color: var(--secondary-text-color, #888);
    text-align: center;
    margin-bottom: 10px;
    font-family: monospace;
  }
  .review-flow-proposal-memory {
    background: var(--secondary-background-color, #f5f5f5);
    border-left: 3px solid var(--primary-color, #03a9f4);
    border-radius: 4px;
    padding: 8px 10px;
    font-size: 0.82rem;
    color: var(--primary-text-color);
    margin-top: 4px;
  }
  .review-flow-memory-label {
    font-weight: bold;
    margin-right: 4px;
  }
  .review-flow-actions {
    display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
  }
  .review-btn {
    padding: 5px 14px; border-radius: 6px; border: none; cursor: pointer;
    font-size: 0.85em; font-weight: 500; transition: opacity 0.15s;
  }
  .review-btn:hover { opacity: 0.85; }
  .review-btn-approve { background: var(--success-color, #4caf50); color: #fff; }
  .review-btn-reject  { background: var(--error-color, #f44336); color: #fff; }
  .review-btn-skip    { background: var(--secondary-background-color, rgba(255,255,255,0.1)); color: var(--primary-text-color); border: 1px solid var(--divider-color); }
  .review-skip-days-label {
    font-size: 0.8em; color: var(--secondary-text-color); display: flex;
    align-items: center; gap: 4px; margin-left: auto;
  }
  .review-skip-days-label input {
    border: 1px solid var(--divider-color, #ccc); border-radius: 3px;
    background: transparent; color: var(--primary-text-color);
  }
  .rv-skip-days {
    font-size: 0.75em; color: var(--secondary-text-color); display: flex;
    align-items: center; gap: 3px;
  }
  .rv-skip-days input {
    border: 1px solid var(--divider-color, #ccc); border-radius: 3px;
    background: transparent; color: var(--primary-text-color);
  }
  .rv-bulk {
    font-size: 0.78em; color: var(--secondary-text-color);
    display: flex; align-items: center; gap: 5px; flex-wrap: wrap;
    padding-top: 4px; border-top: 1px solid var(--divider-color, rgba(255,255,255,0.08));
  }
  .rv-bulk-btn {
    padding: 2px 8px; border-radius: 4px; border: none; cursor: pointer;
    font-size: 0.9em; font-weight: 500; transition: opacity 0.15s;
  }
  .rv-bulk-btn:hover { opacity: 0.8; }
  .rv-bulk-approve { background: rgba(76,175,80,0.18); color: var(--success-color, #4caf50); border: 1px solid var(--success-color, #4caf50); }
  .rv-bulk-reject  { background: rgba(244,67,54,0.12); color: var(--error-color, #f44336); border: 1px solid var(--error-color, #f44336); }
  .kn-conf { color: var(--secondary-text-color, #aaa); font-size: 10px; }
  .kn-stars { cursor: pointer; }
  .kn-star { color: #555; font-size: 12px; cursor: pointer; }
  .kn-star.filled { color: #ffc107; }
  .kn-row-actions { margin-left: auto; display: flex; gap: 4px; }
  .kn-row-actions button {
    background: transparent; border: none; cursor: pointer; font-size: 13px; padding: 0 2px;
  }
  .kn-content { margin: 4px 0; color: var(--primary-text-color, #ddd); }
  .kn-tag {
    background: rgba(255,255,255,0.08); padding: 1px 5px; margin-right: 3px;
    border-radius: 3px; font-size: 10px;
  }
  .kn-prov { color: var(--secondary-text-color, #888); font-size: 10px; font-style: italic; }
  .kn-meta { color: var(--secondary-text-color, #666); font-size: 10px; margin-top: 4px; }
  .kn-fb { margin-top: 4px; font-size: 10px; color: var(--secondary-text-color, #aaa); }
  .kn-fb-item { padding: 2px 0; }
  .kn-editor {
    position: fixed; inset: 0; background: rgba(0,0,0,0.6);
    display: flex; align-items: center; justify-content: center; z-index: 9999;
  }
  .kn-editor-inner {
    background: var(--card-background-color, #1f1f1f);
    padding: 16px 20px; border-radius: 8px; min-width: 420px; max-width: 520px;
    display: flex; flex-direction: column; gap: 8px;
  }
  .kn-editor-inner label { display: flex; flex-direction: column; gap: 2px; font-size: 11px; color: var(--secondary-text-color, #aaa); }
  .kn-editor-inner input, .kn-editor-inner select, .kn-editor-inner textarea {
    background: rgba(255,255,255,0.06); border: 1px solid var(--divider-color, #444);
    color: var(--primary-text-color, #ddd); padding: 4px 6px; border-radius: 3px;
    font: inherit;
  }
  .kn-editor-buttons { display: flex; gap: 8px; justify-content: flex-end; margin-top: 6px; }
  .kn-editor-buttons button {
    padding: 4px 12px; border-radius: 4px; cursor: pointer; border: none;
  }
  .btn-kn-cancel { background: var(--divider-color, #444); color: var(--primary-text-color, #ddd); }
  .btn-kn-save, .btn-kn-save-selected { background: var(--primary-color, #03a9f4); color: white; }

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

  /* ── Entity chips — rich adornments in plan card rows ── */
  .entity-chip {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 3px 8px 3px 6px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 500;
    transition: transform 0.18s ease, box-shadow 0.18s ease;
    background: var(--panel-bg);
    border: 1px solid var(--border-color);
    color: var(--secondary-text-color, #9e9e9e);
    max-width: 200px;
    cursor: default;
    flex-shrink: 0;
  }

  .entity-chip-icon {
    --mdc-icon-size: 14px;
    width: 14px;
    height: 14px;
    flex-shrink: 0;
    opacity: 0.65;
    transition: opacity 0.18s, filter 0.18s;
  }

  .entity-chip-name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 150px;
  }

  .entity-chip-warn {
    font-size: 10px;
    color: var(--warning-color, #ff9800);
  }

  /* "Off" / closed / inactive — muted */
  .entity-chip.state-off {
    opacity: 0.7;
  }

  /* "On" / active — lights: warm amber glow */
  .entity-chip.state-on {
    background: rgba(255, 180, 0, 0.09);
    border-color: rgba(255, 180, 0, 0.35);
    color: #ffb300;
  }
  .entity-chip.state-on .entity-chip-icon {
    opacity: 1;
    color: #ffb300;
    filter: drop-shadow(0 0 3px rgba(255, 180, 0, 0.55));
  }

  /* Switches / input_boolean → green */
  .entity-chip.state-on.domain-switch,
  .entity-chip.state-on.domain-input-boolean {
    background: rgba(67, 160, 71, 0.1);
    border-color: rgba(67, 160, 71, 0.35);
    color: #43a047;
  }
  .entity-chip.state-on.domain-switch .entity-chip-icon,
  .entity-chip.state-on.domain-input-boolean .entity-chip-icon {
    color: #43a047;
    filter: drop-shadow(0 0 3px rgba(67, 160, 71, 0.5));
  }

  /* Media player → blue */
  .entity-chip.state-on.domain-media-player {
    background: rgba(30, 136, 229, 0.1);
    border-color: rgba(30, 136, 229, 0.35);
    color: #1e88e5;
  }
  .entity-chip.state-on.domain-media-player .entity-chip-icon {
    color: #1e88e5;
    filter: drop-shadow(0 0 3px rgba(30, 136, 229, 0.5));
  }

  /* Climate → orange */
  .entity-chip.state-on.domain-climate,
  .entity-chip.state-on.domain-water-heater {
    background: rgba(251, 140, 0, 0.1);
    border-color: rgba(251, 140, 0, 0.35);
    color: #fb8c00;
  }
  .entity-chip.state-on.domain-climate .entity-chip-icon,
  .entity-chip.state-on.domain-water-heater .entity-chip-icon {
    color: #fb8c00;
    filter: drop-shadow(0 0 3px rgba(251, 140, 0, 0.5));
  }

  /* Lock unlocked → red (security alert) */
  .entity-chip.state-on.domain-lock {
    background: rgba(229, 57, 53, 0.1);
    border-color: rgba(229, 57, 53, 0.35);
    color: #e53935;
  }
  .entity-chip.state-on.domain-lock .entity-chip-icon {
    color: #e53935;
    filter: drop-shadow(0 0 3px rgba(229, 57, 53, 0.5));
  }

  /* Cover open → teal */
  .entity-chip.state-on.domain-cover {
    background: rgba(0, 150, 136, 0.1);
    border-color: rgba(0, 150, 136, 0.35);
    color: #00897b;
  }
  .entity-chip.state-on.domain-cover .entity-chip-icon {
    color: #00897b;
    filter: drop-shadow(0 0 3px rgba(0, 150, 136, 0.5));
  }

  /* Unavailable */
  .entity-chip.state-unavailable {
    opacity: 0.4;
    font-style: italic;
  }

  /* Missing entity */
  .entity-chip.entity-chip-missing {
    background: rgba(207, 102, 121, 0.1);
    border-color: rgba(207, 102, 121, 0.4);
    color: var(--danger);
  }

  /* Hover: scale + domain-tinted glow */
  .change-row:hover .entity-chip {
    transform: scale(1.05);
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.25);
  }
  .change-row:hover .entity-chip.state-on {
    box-shadow: 0 2px 8px rgba(255, 180, 0, 0.28);
  }
  .change-row:hover .entity-chip.state-on.domain-switch,
  .change-row:hover .entity-chip.state-on.domain-input-boolean {
    box-shadow: 0 2px 8px rgba(67, 160, 71, 0.28);
  }
  .change-row:hover .entity-chip.state-on.domain-media-player {
    box-shadow: 0 2px 8px rgba(30, 136, 229, 0.28);
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

  /* ── Automation editing cards ─────────────────────────────────────────── */
  .automation-edit-card {
    background: color-mix(in srgb, var(--accent) 5%, var(--panel-bg));
    border: 1px solid var(--accent);
    border-radius: 10px;
    padding: 12px;
    margin: 6px 0;
    font-size: 13px;
  }
  .ae-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 6px;
  }
  .ae-icon { font-size: 16px; }
  .ae-title { font-weight: 600; font-size: 14px; flex: 1; }
  .ae-badge {
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    background: var(--accent);
    color: white;
    border-radius: 4px;
    padding: 2px 6px;
  }
  .ae-summary { color: var(--secondary-text-color, #aaa); margin-bottom: 6px; line-height: 1.4; }
  .ae-changes {
    margin: 0 0 8px 0;
    padding-left: 18px;
    color: var(--secondary-text-color, #aaa);
    font-size: 12px;
    line-height: 1.6;
  }
  .ae-section { margin-bottom: 10px; }
  .ae-section-header {
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.8px;
    text-transform: uppercase;
    color: var(--secondary-text-color, #888);
    margin-bottom: 4px;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .ae-section-header.changed { color: var(--accent); }
  .ae-btn-test-section {
    font-size: 11px; padding: 2px 8px; background: transparent;
    color: var(--accent); border: 1px solid var(--accent); border-radius: 4px; cursor: pointer;
  }
  .ae-rows { display: flex; flex-direction: column; gap: 4px; }
  .ae-row {
    display: flex;
    align-items: center;
    gap: 8px;
    background: var(--sidebar-bg);
    border: 1px solid var(--border-color);
    border-radius: 6px;
    padding: 7px 8px;
    cursor: default;
    user-select: none;
  }
  .ae-row.dragging { opacity: 0.4; }
  .ae-row.drag-over { border-color: var(--accent); border-style: dashed; background: color-mix(in srgb, var(--accent) 10%, var(--sidebar-bg)); }
  .ae-drag-handle { cursor: grab; color: var(--secondary-text-color, #888); font-size: 14px; flex: 0 0 auto; }
  .ae-drag-handle:active { cursor: grabbing; }
  .ae-row-desc { flex: 1; font-size: 13px; }
  .ae-row-desc.changed {
    background: color-mix(in srgb, orange 15%, transparent);
    border-radius: 3px;
    padding: 1px 4px;
  }
  .ae-row-delete {
    background: none; border: none; cursor: pointer; opacity: 0.4; font-size: 14px; padding: 2px;
    flex: 0 0 auto;
  }
  .ae-row-delete:hover { opacity: 1; }
  .ae-yaml-details {
    margin: 8px 0;
    font-size: 12px;
  }
  .ae-yaml-details summary { cursor: pointer; color: var(--secondary-text-color, #888); }
  .ae-yaml-preview {
    background: var(--sidebar-bg);
    border: 1px solid var(--border-color);
    border-radius: 6px;
    padding: 8px;
    font-size: 11px;
    font-family: monospace;
    overflow-x: auto;
    white-space: pre;
    margin-top: 6px;
    max-height: 200px;
    overflow-y: auto;
  }
  .ae-actions { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 10px; }
  .ae-btn-expand, .ae-btn-test {
    padding: 6px 12px; background: transparent; color: var(--accent);
    border: 1px solid var(--accent); border-radius: 4px; cursor: pointer; font-size: 12px;
  }
  .ae-btn-apply {
    padding: 6px 14px; background: var(--accent); color: white;
    border: none; border-radius: 4px; cursor: pointer; font-size: 13px; font-weight: 600;
  }
  .ae-btn-apply:disabled { opacity: 0.6; cursor: default; }
  .ae-btn-cancel {
    padding: 6px 12px; background: transparent; color: var(--secondary-text-color, #888);
    border: 1px solid var(--border-color); border-radius: 4px; cursor: pointer; font-size: 13px;
  }
  .ae-result { margin-top: 6px; font-size: 12px; }
  .ae-result.error { color: var(--danger, #e53935); }

  /* Automation tester */
  .ae-tester {
    background: color-mix(in srgb, #673ab7 8%, var(--panel-bg));
    border: 1px solid rgba(103, 58, 183, 0.3);
    border-radius: 8px;
    padding: 10px;
    margin: 8px 0;
    font-size: 12px;
  }
  .ae-tester-header { font-weight: 600; font-size: 13px; margin-bottom: 6px; }
  .ae-tester-desc { color: var(--secondary-text-color, #aaa); margin-bottom: 8px; }
  .ae-tester-mocks { display: flex; flex-direction: column; gap: 6px; margin-bottom: 10px; }
  .ae-mock-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .ae-mock-eid { font-family: monospace; font-size: 11px; flex: 1; min-width: 120px; color: var(--accent); }
  .ae-mock-live { font-size: 11px; color: var(--secondary-text-color, #888); white-space: nowrap; }
  .ae-mock-input {
    width: 110px; padding: 3px 6px; background: var(--sidebar-bg); color: var(--text-color);
    border: 1px solid var(--border-color); border-radius: 4px; font-size: 12px; font-family: monospace;
  }
  .ae-tester-run {
    padding: 5px 14px; background: rgba(103, 58, 183, 0.7); color: white;
    border: none; border-radius: 4px; cursor: pointer; font-size: 12px; font-weight: 600;
    margin-bottom: 10px;
  }
  .ae-tester-run:hover { background: rgba(103, 58, 183, 0.9); }
  .ae-tester-results { display: flex; flex-direction: column; gap: 8px; }
  .ae-sim-section { font-size: 12px; }
  .ae-sim-label {
    font-size: 10px; font-weight: 700; letter-spacing: 0.8px; text-transform: uppercase;
    color: var(--secondary-text-color, #888); margin-bottom: 4px;
  }
  .ae-sim-item { padding: 3px 0; line-height: 1.4; }
  .ae-sim-result {
    font-weight: 700; font-size: 13px; padding: 6px 10px;
    border-radius: 6px; margin-top: 4px;
  }
  .ae-sim-result.pass { background: color-mix(in srgb, #4caf50 15%, transparent); color: var(--success, #4caf50); }
  .ae-sim-result.fail { background: color-mix(in srgb, #e53935 15%, transparent); color: var(--danger, #e53935); }



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
    display: flex;
    align-items: center;
    gap: 4px;
    background: transparent;
    color: var(--secondary-text-color, #888);
    border: 1px solid var(--border-color, #3a3a3c);
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    padding: 2px 7px;
    border-radius: 10px;
    opacity: 0.4;
    cursor: pointer;
    transition: opacity 0.2s, background 0.2s, color 0.2s, border-color 0.2s;
    outline: none;
  }

  /* ── Update-available badge ─────────────────────────────────────── */
  .update-badge {
    display: flex;
    align-items: center;
    gap: 4px;
    background: #e8a000;
    color: #fff;
    border: 1px solid #e8a000;
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    padding: 2px 8px;
    border-radius: 10px;
    cursor: pointer;
    transition: opacity 0.2s, transform 0.15s;
    animation: pulse-update 2.5s ease-in-out infinite;
    white-space: nowrap;
    outline: none;
  }
  /* display:flex above overrides the browser's [hidden]{display:none} — must re-apply */
  .update-badge[hidden] { display: none !important; }
  .update-badge:hover { opacity: 0.85; transform: scale(1.05); }

  #update-badge-popover {
    position: absolute;
    z-index: 999;
    background: var(--card-background-color, #fff);
    border: 1px solid var(--divider-color, #e0e0e0);
    border-radius: 8px;
    box-shadow: 0 4px 16px rgba(0,0,0,0.15);
    padding: 8px;
    min-width: 180px;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .ubp-title {
    font-size: 11px;
    font-weight: 600;
    color: var(--secondary-text-color, #666);
    padding: 2px 4px 6px;
    border-bottom: 1px solid var(--divider-color, #e0e0e0);
    margin-bottom: 2px;
  }
  .ubp-btn {
    background: none;
    border: 1px solid var(--divider-color, #e0e0e0);
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
    font-weight: 500;
    cursor: pointer;
    text-align: left;
    color: var(--primary-text-color, #333);
    transition: background 0.15s;
  }
  .ubp-btn:hover { background: var(--secondary-background-color, #f5f5f5); }
  .ubp-restart { color: #e8a000; }
  @keyframes pulse-update {
    0%, 100% { box-shadow: 0 0 0 0 rgba(232,160,0,0.5); }
    50%       { box-shadow: 0 0 0 5px rgba(232,160,0,0); }
  }

  .autopilot-badge:hover { opacity: 0.7; }

  .autopilot-badge.active {
    background: #ff6b00;
    color: white;
    border-color: #ff6b00;
    opacity: 1;
    animation: pulse-autopilot 2s ease-in-out infinite;
  }

  @keyframes pulse-autopilot {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.6; }
  }

  /* ── Memory badge ──────────────────────────────────────────────── */
  .memory-badge {
    display: flex;
    align-items: center;
    gap: 4px;
    background: color-mix(in srgb, var(--accent, #03a9f4) 15%, transparent);
    color: var(--accent, #03a9f4);
    border: 1px solid color-mix(in srgb, var(--accent, #03a9f4) 40%, transparent);
    font-size: 11px;
    font-weight: 600;
    padding: 2px 8px;
    border-radius: 10px;
    cursor: pointer;
    white-space: nowrap;
    transition: background 0.15s;
    outline: none;
  }

  .memory-badge:hover {
    background: color-mix(in srgb, var(--accent, #03a9f4) 28%, transparent);
  }

  .token-badge {
    display: flex;
    align-items: center;
    gap: 4px;
    background: color-mix(in srgb, var(--secondary-text-color, #9aa0a6) 12%, transparent);
    color: var(--secondary-text-color, #c5c9ce);
    border: 1px solid color-mix(in srgb, var(--secondary-text-color, #9aa0a6) 30%, transparent);
    font-size: 11px;
    font-weight: 600;
    padding: 2px 8px;
    border-radius: 10px;
    cursor: default;
    white-space: nowrap;
    transition: background 0.15s, border-color 0.15s, color 0.15s;
    outline: none;
  }

  .token-badge--warning {
    color: #f0b429;
    border-color: color-mix(in srgb, #f0b429 55%, transparent);
    background: color-mix(in srgb, #f0b429 16%, transparent);
  }

  .token-badge--danger {
    color: #ff6b6b;
    border-color: color-mix(in srgb, #ff6b6b 60%, transparent);
    background: color-mix(in srgb, #ff6b6b 16%, transparent);
  }

  .history-badge {
    display: flex;
    align-items: center;
    gap: 4px;
    background: transparent;
    color: var(--secondary-text-color, #aaa);
    border: 1px solid var(--border-color, #3a3a3c);
    font-size: 11px;
    font-weight: 600;
    padding: 2px 8px;
    border-radius: 10px;
    cursor: pointer;
    white-space: nowrap;
  }

  .history-badge:hover,
  .history-badge.active {
    color: var(--text-color, #f5f5f5);
    background: color-mix(in srgb, var(--accent, #03a9f4) 16%, transparent);
    border-color: color-mix(in srgb, var(--accent, #03a9f4) 40%, transparent);
  }

  .memory-badge--recalled {
    animation: pulse-memory 1.5s ease-in-out 2;
  }

  @keyframes pulse-memory {
    0%, 100% { opacity: 1; box-shadow: none; }
    50%       { opacity: 0.75; box-shadow: 0 0 10px color-mix(in srgb, var(--accent, #03a9f4) 70%, transparent); }
  }

  .action-history-panel {
    margin: 0 12px 8px;
    border: 1px solid var(--border-color, #3a3a3c);
    border-radius: 10px;
    background: color-mix(in srgb, var(--sidebar-bg, #2c2c2e) 70%, transparent);
    overflow: hidden;
  }

  .action-history-panel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 10px;
    font-size: 12px;
    border-bottom: 1px solid var(--border-color, #3a3a3c);
  }

  .action-history-refresh,
  .action-history-undo {
    background: transparent;
    color: var(--text-color, #f5f5f5);
    border: 1px solid var(--border-color, #3a3a3c);
    border-radius: 8px;
    padding: 4px 8px;
    cursor: pointer;
    font-size: 11px;
  }

  .action-history-list {
    max-height: 220px;
    overflow-y: auto;
    padding: 8px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .action-history-entry {
    border: 1px solid var(--border-color, #3a3a3c);
    border-radius: 8px;
    padding: 8px;
    display: flex;
    flex-direction: column;
    gap: 6px;
    background: var(--panel-bg, #1c1c1e);
  }

  .action-history-meta {
    display: flex;
    justify-content: space-between;
    gap: 8px;
    font-size: 11px;
    color: var(--secondary-text-color, #aaa);
  }

  .action-history-status {
    border-radius: 999px;
    padding: 2px 8px;
    border: 1px solid var(--border-color, #3a3a3c);
  }

  .action-history-status.status-applied { color: var(--success, #4caf50); }
  .action-history-status.status-undone { color: var(--accent, #03a9f4); }
  .action-history-status.status-failed { color: var(--danger, #cf6679); }

  .action-history-summary {
    font-size: 13px;
    line-height: 1.4;
  }

  .action-history-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .action-history-chip,
  .action-history-empty-inline,
  .action-history-empty {
    font-size: 11px;
    color: var(--secondary-text-color, #aaa);
  }

  .action-history-chip {
    border: 1px solid var(--border-color, #3a3a3c);
    border-radius: 999px;
    padding: 3px 8px;
    background: var(--sidebar-bg, #2c2c2e);
  }

  /* ── Memory popover (position:fixed — escapes overflow:hidden parents) ── */
  .memory-popover {
    position: fixed;
    z-index: 10000;
    background: var(--card-background-color, #2c2c2e);
    border: 1px solid var(--border-color, #3a3a3c);
    border-radius: 8px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.35);
    min-width: 260px;
    max-width: 380px;
    font-size: 12px;
  }

  .memory-popover-header {
    padding: 8px 12px;
    font-size: 12px;
    font-weight: 700;
    border-bottom: 1px solid var(--border-color, #3a3a3c);
    color: var(--text-color, #f5f5f5);
  }

  .memory-popover-body {
    padding: 8px 12px;
    max-height: 200px;
    overflow-y: auto;
    color: var(--text-color, #f5f5f5);
  }

  .memory-popover-entry {
    padding: 5px 0;
    border-bottom: 1px solid var(--border-color, #3a3a3c);
    font-size: 11px;
    line-height: 1.45;
  }

  .memory-popover-entry:last-child { border-bottom: none; }

  .mem-cat {
    font-size: 10px;
    font-weight: 700;
    color: var(--accent, #03a9f4);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .memory-popover-footer {
    padding: 6px 12px;
    border-top: 1px solid var(--border-color, #3a3a3c);
  }

  .memory-popover-footer button {
    background: none;
    border: none;
    color: var(--accent, #03a9f4);
    font-size: 11px;
    cursor: pointer;
    padding: 0;
  }

  .memory-popover-footer button:hover { text-decoration: underline; }

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

  /* ── Thinking bubble ─────────────────────────────────────────── */
  .thinking-bubble {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 10px 14px;
    background: var(--secondary-background-color, #f5f5f5);
    border-radius: 12px;
    border-bottom-left-radius: 4px;
    max-width: 80%;
    margin: 4px 0;
  }
  .thinking-header {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: nowrap;
  }
  .thinking-cancel {
    margin-left: auto;
    background: none;
    border: none;
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 0.78em;
    color: var(--secondary-text-color, #888);
    cursor: pointer;
    opacity: 0.75;
    white-space: nowrap;
    transition: opacity 0.15s;
  }
  .thinking-cancel:hover { opacity: 1; color: var(--error-color, #f44336); }
  .thinking-dots {
    display: flex;
    gap: 5px;
    align-items: center;
  }
  .thinking-dots span {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--primary-color, #03a9f4);
    opacity: 0.3;
    animation: thinking-bounce 1.2s ease-in-out infinite;
  }
  .thinking-dots span:nth-child(1) { animation-delay: 0s; }
  .thinking-dots span:nth-child(2) { animation-delay: 0.2s; }
  .thinking-dots span:nth-child(3) { animation-delay: 0.4s; }
  @keyframes thinking-bounce {
    0%, 80%, 100% { opacity: 0.2; transform: scale(0.85); }
    40% { opacity: 1; transform: scale(1.15); }
  }
  .thinking-label {
    font-size: 12px;
    color: var(--secondary-text-color, #888);
    font-style: italic;
  }
  .thinking-events {
    display: flex;
    flex-direction: column;
    gap: 3px;
    font-size: 12px;
    font-family: monospace;
  }
  .thinking-events:empty { display: none; }
  .thinking-event {
    color: var(--primary-text-color, #333);
    line-height: 1.4;
    word-break: break-word;
  }
  .thinking-tool-name { font-weight: 600; }
  .thinking-tool-args {
    color: var(--secondary-text-color, #888);
    font-size: 11px;
  }
  .thinking-tool-running { color: var(--primary-color, #03a9f4); }
  .thinking-tool-done { color: var(--success-color, #4caf50); }
  .thinking-info {
    color: var(--secondary-text-color, #888);
    font-style: italic;
  }
  .thinking-tool-preview {
    margin: 4px 0 0;
    padding: 6px 8px;
    background: var(--code-editor-background-color, #fafafa);
    border-radius: 4px;
    font-size: 11px;
    white-space: pre-wrap;
    max-height: 180px;
    overflow: auto;
  }
  .thinking-error { color: var(--error-color, #f44336); }
  .thinking-warning { color: var(--warning-color, #ff9800); font-weight: 500; }

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

  .context-badge {
    font-size: 10px;
    color: var(--secondary-text-color, #888);
    background: var(--secondary-background-color, rgba(0,0,0,0.06));
    border-radius: 10px;
    padding: 1px 7px;
    white-space: nowrap;
    margin-left: 2px;
  }
  .context-badge:empty { display: none; }

  .narrator-progress {
    font-size: 0.78em;
    padding: 2px 8px;
    border-radius: 10px;
    background: color-mix(in srgb, var(--primary-color) 15%, transparent);
    color: var(--primary-text-color);
    cursor: default;
    animation: pulse-badge 2s ease-in-out infinite;
  }

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
  .ac-item .ac-badge {
    display: inline-block; font-size: 10px; padding: 1px 5px;
    border-radius: 3px; background: rgba(0,0,0,.15); margin-left: 5px; vertical-align: middle;
  }
  .ac-item.active .ac-badge { background: rgba(255,255,255,.25); }

  /* ── Help detail card ───────────────────────────────────────────── */
  .kyber-help-card { padding: 0 !important; overflow: hidden; max-width: 520px; }
  .kh-header {
    display: flex; align-items: center; gap: 10px;
    padding: 12px 16px 10px;
    background: var(--primary-color, #448aff); color: white;
    border-radius: 10px 10px 0 0;
  }
  .kh-icon  { font-size: 22px; line-height: 1; }
  .kh-title { font-size: 16px; font-weight: 700; flex-shrink: 0; }
  .kh-subtitle { font-size: 12px; opacity: .85; }
  .kh-rows  { padding: 6px 8px 2px; }
  .kh-row {
    display: flex; align-items: baseline; gap: 10px;
    padding: 6px 8px; border-radius: 6px; cursor: pointer; transition: background .12s;
  }
  .kh-row:hover { background: var(--primary-color, #448aff); color: white; }
  .kh-usage {
    font-size: 12px; min-width: 210px; white-space: nowrap;
    background: rgba(0,0,0,.07); padding: 2px 6px; border-radius: 4px; font-family: monospace;
  }
  .kh-row:hover .kh-usage { background: rgba(255,255,255,.2); color: white; }
  .kh-row-desc { font-size: 12px; opacity: .72; }
  .kh-row:hover .kh-row-desc { opacity: 1; }
  .kh-footer { padding: 6px 14px 10px; font-size: 11px; opacity: .55; border-top: 1px solid var(--divider-color,#eee); margin-top: 4px; }

  /* ── Help overview grid ─────────────────────────────────────────── */
  .kyber-help-overview { padding: 0 !important; overflow: hidden; max-width: 520px; }
  .kho-title {
    padding: 12px 16px 10px; font-size: 15px; font-weight: 700;
    background: var(--primary-color, #448aff); color: white; border-radius: 10px 10px 0 0;
  }
  .kho-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; padding: 10px; }
  .kho-item {
    display: flex; flex-direction: column; gap: 2px; padding: 8px 10px; border-radius: 8px;
    cursor: pointer; background: var(--secondary-background-color, #f5f5f5);
    transition: background .12s; border: 1px solid var(--divider-color, #e0e0e0);
  }
  .kho-item:hover { background: var(--primary-color, #448aff); color: white; }
  .kho-icon { font-size: 18px; }
  .kho-name { font-size: 13px; font-weight: 600; font-family: monospace; }
  .kho-desc { font-size: 11px; opacity: .72; }
  .kho-item:hover .kho-desc { opacity: 1; }
  .kho-footer { padding: 6px 14px 10px; font-size: 11px; opacity: .55; border-top: 1px solid var(--divider-color,#eee); }

  .kyber-label-applied-chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    border-radius: 16px;
    background: var(--primary-color, #03a9f4);
    color: white;
    font-size: 12px;
    margin-top: 6px;
  }
  .kyber-label-applied-chip ha-icon { --mdc-icon-size: 16px; }
  .kyber-undo-label-btn {
    background: none;
    border: 1px solid rgba(255,255,255,0.5);
    color: white;
    border-radius: 10px;
    padding: 1px 8px;
    cursor: pointer;
    font-size: 11px;
  }
  .kyber-undo-label-btn:hover { background: rgba(0,0,0,0.15); }

  .kyber-area-suggestion-chip {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    border-radius: 10px;
    background: var(--card-background-color, #f5f5f5);
    border: 1px solid var(--divider-color, #e0e0e0);
    font-size: 13px;
    margin: 6px 0;
    flex-wrap: wrap;
  }
  .kyber-area-suggestion-chip.area-chip-done {
    opacity: 0.65;
    pointer-events: none;
  }
  .area-chip-icon { font-size: 16px; flex-shrink: 0; }
  .area-chip-text { flex: 1; color: var(--primary-text-color, #333); }
  .kyber-area-apply-btn, .kyber-area-undo-btn {
    background: var(--primary-color, #03a9f4);
    color: white;
    border: none;
    border-radius: 8px;
    padding: 4px 12px;
    cursor: pointer;
    font-size: 12px;
    white-space: nowrap;
  }
  .kyber-area-apply-btn:hover, .kyber-area-undo-btn:hover { filter: brightness(1.1); }
  .kyber-area-dismiss-btn {
    background: none;
    border: 1px solid var(--divider-color, #ccc);
    border-radius: 8px;
    padding: 4px 10px;
    cursor: pointer;
    font-size: 12px;
    color: var(--secondary-text-color, #888);
  }
  .kyber-area-dismiss-btn:hover { background: var(--divider-color, #eee); }

  /* ── Restart overlay ─────────────────────────────────────────── */
  .restart-overlay {
    position: fixed;
    inset: 0;
    z-index: 99999;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 24px;
    background: var(--primary-background-color, #1c1c1e);
    animation: restart-fadein 0.4s ease both;
  }

  @keyframes restart-fadein {
    from { opacity: 0; }
    to   { opacity: 1; }
  }

  .restart-logo {
    font-size: 52px;
    line-height: 1;
    animation: restart-spin-bounce 2.5s ease-in-out infinite;
  }

  @keyframes restart-spin-bounce {
    0%   { transform: rotate(0deg) scale(1); }
    40%  { transform: rotate(360deg) scale(1.1); }
    60%  { transform: rotate(360deg) scale(0.95); }
    100% { transform: rotate(360deg) scale(1); animation-name: restart-spin-bounce2; }
  }

  .restart-title {
    font-size: 22px;
    font-weight: 700;
    color: var(--primary-text-color, #f0f0f0);
    letter-spacing: -0.02em;
  }

  .restart-subtitle {
    font-size: 14px;
    color: var(--secondary-text-color, #888);
    text-align: center;
    max-width: 340px;
    line-height: 1.5;
  }

  .restart-progress {
    width: 280px;
    height: 3px;
    background: var(--divider-color, #333);
    border-radius: 99px;
    overflow: hidden;
  }

  .restart-progress-bar {
    height: 100%;
    width: 0%;
    background: var(--primary-color, #03a9f4);
    border-radius: 99px;
    animation: restart-progress 18s cubic-bezier(0.25, 0, 0.6, 1) forwards;
  }

  @keyframes restart-progress {
    0%   { width: 0%; }
    60%  { width: 75%; }
    90%  { width: 88%; }
    100% { width: 92%; }
  }

  .restart-dots {
    display: flex;
    gap: 6px;
    align-items: center;
  }

  .restart-dots span {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--primary-color, #03a9f4);
    opacity: 0.3;
    animation: restart-dot-bounce 1.4s ease-in-out infinite;
  }

  .restart-dots span:nth-child(1) { animation-delay: 0s; }
  .restart-dots span:nth-child(2) { animation-delay: 0.2s; }
  .restart-dots span:nth-child(3) { animation-delay: 0.4s; }

  @keyframes restart-dot-bounce {
    0%, 80%, 100% { opacity: 0.3; transform: scale(1); }
    40%            { opacity: 1;   transform: scale(1.3); }
  }

  .restart-status {
    font-size: 12px;
    color: var(--secondary-text-color, #666);
    letter-spacing: 0.02em;
  }

  /* ── Toast notification (correction micro-agent learned facts) ──────────── */
  .kyber-toast {
    position: fixed;
    top: 16px;
    left: 50%;
    transform: translateX(-50%) translateY(-80px);
    background: var(--primary-color, #03a9f4);
    color: #fff;
    padding: 10px 20px;
    border-radius: 24px;
    font-size: 13px;
    font-weight: 500;
    box-shadow: 0 4px 16px rgba(0,0,0,0.25);
    z-index: 9999;
    pointer-events: none;
    opacity: 0;
    transition: opacity 0.3s ease, transform 0.3s ease;
    max-width: 80%;
    text-align: center;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .kyber-toast--visible {
    opacity: 1;
    transform: translateX(-50%) translateY(0);
  }

  /* ── Approval-required pulse animation on the Execute button ────────────── */
  @keyframes kyber-approval-pulse {
    0%, 100% { box-shadow: 0 0 0 0 rgba(255,152,0,0.7); }
    50%       { box-shadow: 0 0 0 8px rgba(255,152,0,0); }
  }
  .kyber-approval-pulse {
    animation: kyber-approval-pulse 0.8s ease-in-out 3;
    border-color: var(--warning-color, #ff9800) !important;
  }
`;

