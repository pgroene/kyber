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
    grid-column: 2;
    grid-row: 2;
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
    cursor: default;
    line-height: 1.6;
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
  }
  .entity-result-card .erc-icon { font-size: 18px; flex-shrink: 0; }
  .entity-result-card .erc-body { overflow: hidden; }
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
    flex: 1; display: flex; flex-direction: column; height: 100%;
    padding: 12px; box-sizing: border-box; overflow: auto;
  }
  .debug-pane--standalone {
    position: absolute; inset: 0;
    background: var(--primary-background-color, #fafafa);
    z-index: 5;
  }
  .debug-header {
    display: flex; align-items: center; gap: 8px;
    border-bottom: 1px solid var(--divider-color);
    padding-bottom: 8px; margin-bottom: 12px;
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
  .debug-body { flex: 1; overflow: auto; }
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

  .memory-badge--recalled {
    animation: pulse-memory 1.5s ease-in-out 2;
  }

  @keyframes pulse-memory {
    0%, 100% { opacity: 1; box-shadow: none; }
    50%       { opacity: 0.75; box-shadow: 0 0 10px color-mix(in srgb, var(--accent, #03a9f4) 70%, transparent); }
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
    gap: 10px;
  }
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
`;

