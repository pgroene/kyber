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
    // Auto-generate session title every 5 messages
    if (this._chatHistory.length % 5 === 0) {
      this._autoNameSession();
    }
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
        this._showContextRefreshedMessage("History cleared");
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
    const name = this._activeSessionName || "";
    const indicator = this.shadowRoot?.getElementById("session-indicator");
    if (indicator) indicator.textContent = name;
  }

  async _autoNameSession() {
    if (!this._hass || !this._activeSessionId) return;
    // Only use real user/assistant exchanges (skip internal [CHANGE] messages)
    const messages = this._chatHistory.filter(
      (m) => !m.content.startsWith("[CHANGE]") && !m.content.startsWith("I saved")
    );
    if (messages.length < 2) return;
    try {
      const token = this._hass.auth.data.access_token;
      const resp = await fetch("/api/kyber/sessions/name", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ messages }),
      });
      if (!resp.ok) return;
      const data = await resp.json();
      if (data.name) {
        this._activeSessionName = data.name;
        this._updateSessionIndicator();
      }
    } catch (_) {
      // Non-fatal — session keeps its current name
    }
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
    this._showContextRefreshedMessage("New session started");
  }

  async _switchSession(nameOrId) {
    if (!this._hass) return;
    const sessions = await this._loadSessionList();
    const num = parseInt(nameOrId, 10);
    const target = !isNaN(num) && num >= 1 && num <= sessions.length
      ? sessions[num - 1]
      : sessions.find((s) => s.name.toLowerCase() === nameOrId.toLowerCase() || s.id === nameOrId);
    if (!target) {
      this._appendMessage(`Session not found: "${nameOrId}". Use \`/session list\` to see available sessions.`, "assistant");
      return;
    }
    const token = this._hass.auth.data.access_token;
    const switchResp = await fetch("/api/kyber/sessions", {
      method: "PUT",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ action: "switch", session_id: target.id }),
    });
    if (!switchResp.ok) {
      this._appendMessage(`Failed to switch session (HTTP ${switchResp.status})`, "assistant");
      return;
    }
    this._activeSessionId = target.id;
    this._activeSessionName = target.name;
    // Reload history for this session
    this._chatHistory = [];
    this._compactedSummary = "";
    await this._restorePersistedHistory();
    this._appendMessage(`Switched to session: **${target.name}**`, "assistant");
    this._showContextRefreshedMessage("Session switched");
  }

  async _renameSession(newName) {
    if (!this._hass) return;
    const token = this._hass.auth.data.access_token;
    const resp = await fetch("/api/kyber/sessions", {
      method: "PUT",
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
      session: `**session** — Manage multiple named chat sessions. Each session has its own message history and AI context. Session titles are automatically generated by AI every 5 messages.\n\n\`/session new [name]\` — Create a new session and switch to it.\n\`/session list\` — Show all sessions with their message counts.\n\`/session switch <name>\` — Switch to a different session.\n\`/session delete\` — Delete the current session and switch to the previous one.`,
      help: `**help** — Show help for Kyber slash commands.\n\n\`/help\` — List all commands with one-line descriptions.\n\`/help <command>\` — Detailed documentation for a specific command (e.g. /help automation).`,
      knowledge: `**knowledge** — View and manage Kyber's learned knowledge ("memory") about your home.\n\n\`/knowledge\` — Open the memory panel in a new tab (lists all saved facts: area aliases, entity notes, procedures, device chains).\n\`/knowledge list\` — Show all saved entries inline in the chat.\n\`/knowledge search <query>\` — Search saved entries.\n\`/knowledge analyze\` — Scan your automations / scenes / scripts and propose new knowledge entries to save (you approve each).\n\`/knowledge delete <id>\` — Delete an entry by id.`,
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
      "| `/session new/list/switch/delete` | Manage chat sessions (AI names sessions) |",
      "| `/knowledge` | View / edit / rate / analyze Kyber's learned memory |",
      "| `/reset` | Clear chat and start over |",
      "| `/help [command]` | Show this help or help for a specific command |",
    ];
    this._appendMessage(lines.join("\n"), "assistant");
  }

  // ────────────────────────────────────────────────────────────────────
  // Knowledge / memory panel
  // ────────────────────────────────────────────────────────────────────
  async _downloadDebugBundle(requestId, btn) {
    const token = this._hass.auth.data.access_token;
    const orig = btn ? btn.textContent : "";
    if (btn) { btn.disabled = true; btn.textContent = "⏳ packing…"; }
    try {
      const resp = await fetch(`/api/kyber/debug/bundle?request_id=${encodeURIComponent(requestId)}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `kyber-debug-${requestId}.zip`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      if (btn) btn.textContent = "✓ downloaded";
      setTimeout(() => { if (btn) { btn.textContent = orig; btn.disabled = false; } }, 1500);
    } catch (err) {
      if (btn) { btn.textContent = `⚠ ${err.message}`; btn.disabled = false; }
    }
  }

        async _openBugReportFlow(requestId, btn) {
          const token = this._hass.auth.data.access_token;
          const shadow = this.shadowRoot;

          // Build and mount the overlay
          const overlay = document.createElement("div");
          overlay.className = "bug-report-overlay";
          overlay.innerHTML = `
            <div class="bug-report-dialog" id="br-dialog">
              <h3>🐛 Create Bug Report</h3>
              <label>What did you ask Kyber?
                <textarea id="br-asked" rows="2" placeholder="e.g. Turn on the kitchen lights"></textarea>
              </label>
              <label>What did you expect to happen?
                <textarea id="br-expected" rows="2" placeholder="e.g. Kitchen lights turn on"></textarea>
              </label>
              <label>What actually happened?
                <textarea id="br-happened" rows="3" placeholder="e.g. Nothing happened / wrong room / error message"></textarea>
              </label>
              <label class="bug-report-checkbox">
                <input type="checkbox" id="br-include-bundle" checked>
                Include debug bundle summary (PII will be redacted)
              </label>
              <div class="bug-report-actions">
                <button class="bug-report-btn-cancel" id="br-cancel">Cancel</button>
                <button class="bug-report-btn-submit" id="br-submit">Generate report →</button>
              </div>
            </div>`;
          shadow.appendChild(overlay);

          const close = () => overlay.remove();
          overlay.querySelector("#br-cancel").addEventListener("click", close);
          overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });

          overlay.querySelector("#br-submit").addEventListener("click", async () => {
            const asked = overlay.querySelector("#br-asked").value.trim();
            const expected = overlay.querySelector("#br-expected").value.trim();
            const happened = overlay.querySelector("#br-happened").value.trim();
            const includeBundle = overlay.querySelector("#br-include-bundle").checked;

            if (!asked && !happened) {
              overlay.querySelector("#br-happened").focus();
              return;
            }

            // Step 2: spinner
            const dlg = overlay.querySelector("#br-dialog");
            dlg.innerHTML = `<div class="bug-report-spinner">⏳ Generating bug report…</div>`;

            let data;
            try {
              const resp = await fetch("/api/kyber/debug/bug-report", {
                method: "POST",
                headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
                body: JSON.stringify({ request_id: requestId, what_asked: asked, what_expected: expected, what_happened: happened, include_bundle: includeBundle }),
              });
              if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
              data = await resp.json();
            } catch (err) {
              dlg.innerHTML = `<h3>🐛 Bug Report</h3><p style="color:var(--error-color,#f44)">Failed: ${this._escapeHtml(err.message)}</p><div class="bug-report-actions"><button class="bug-report-btn-cancel" id="br-cancel2">Close</button></div>`;
              dlg.querySelector("#br-cancel2").addEventListener("click", close);
              return;
            }

            // Step 3: review
            const similar = (data.similar_issues || []);
            const similarHtml = similar.length
              ? `<div class="bug-report-similar"><strong>Similar open issues:</strong><ul style="margin:4px 0 0;padding-left:18px">${similar.map(i => `<li><a href="${this._escapeHtml(i.url)}" target="_blank">#${i.number} ${this._escapeHtml(i.title)}</a> [${i.state}]</li>`).join("")}</ul></div>`
              : "";

            const encodedTitle = encodeURIComponent(data.title || "");
            const encodedBody = encodeURIComponent(data.body || "");
            const ghUrl = `https://github.com/pgroene/kyber/issues/new?title=${encodedTitle}&body=${encodedBody}`;

            dlg.innerHTML = `
              <h3>🐛 Review Bug Report</h3>
              ${similarHtml}
              <label class="bug-report-result-title">Title
                <input type="text" id="br-title" value="${this._escapeHtml(data.title || "")}">
              </label>
              <label>Body (markdown)
                <textarea id="br-body" rows="12">${this._escapeHtml(data.body || "")}</textarea>
              </label>
              <div class="bug-report-actions">
                <button class="bug-report-btn-cancel" id="br-close">Close</button>
                <button class="bug-report-btn-submit" id="br-copy">📋 Copy</button>
                <button class="bug-report-btn-submit" id="br-open-gh">Open on GitHub ↗</button>
              </div>`;

            dlg.querySelector("#br-close").addEventListener("click", close);
            dlg.querySelector("#br-copy").addEventListener("click", () => {
              const title = dlg.querySelector("#br-title").value;
              const body = dlg.querySelector("#br-body").value;
              navigator.clipboard.writeText(`## ${title}\n\n${body}`).then(() => {
                const btn2 = dlg.querySelector("#br-copy");
                btn2.textContent = "✓ Copied!";
                setTimeout(() => { btn2.textContent = "📋 Copy"; }, 2000);
              });
            });
            dlg.querySelector("#br-open-gh").addEventListener("click", () => {
              const t = encodeURIComponent(dlg.querySelector("#br-title").value);
              const b = encodeURIComponent(dlg.querySelector("#br-body").value);
              window.open(`https://github.com/pgroene/kyber/issues/new?title=${t}&body=${b}`, "_blank");
            });
          });
        }

  async _submitTurnFeedback(rating, knowledgeIds, btnsRoot) {
    const status = btnsRoot.querySelector(".tf-status");
    btnsRoot.querySelectorAll(".tf-btn-rate").forEach((b) => (b.disabled = true));
    try {
      const token = this._hass.auth.data.access_token;
      const resp = await fetch("/api/kyber/knowledge/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ rating, knowledge_ids: knowledgeIds || [], auto: false }),
      });
      const data = await resp.json();
      if (status) {
        status.textContent = rating >= 4
          ? `✓ thanks — boosted ${data.count || 0} fact(s)`
          : `📝 flagged ${data.count || 0} fact(s) for review`;
        status.classList.add(rating >= 4 ? "ok" : "flag");
      }
      // Refresh the picked-knowledge list so stars/needs_review badges update
      setTimeout(() => this._renderDebugTab("last_turn"), 600);
    } catch (err) {
      if (status) status.textContent = `feedback failed: ${err.message}`;
    }
  }

  async _handleKnowledgeCommand(argStr) {
    const parts = argStr.split(/\s+/);
    const sub = (parts[0] || "").toLowerCase();
    const rest = parts.slice(1).join(" ").trim();
    const token = this._hass.auth.data.access_token;

    if (sub === "list" || sub === "") {
      const data = await this._fetchKnowledge();
      this._renderKnowledgePanel(data, { interactive: true });
      return;
    }
    if (sub === "search") {
      const data = await this._fetchKnowledge(rest);
      this._renderKnowledgePanel(data, { interactive: true, query: rest });
      return;
    }
    if (sub === "analyze") {
      this._appendMessage("🔍 Analyzing automations, scenes, and scripts…", "assistant");
      try {
        const resp = await fetch("/api/kyber/knowledge/analyze", {
          headers: { Authorization: `Bearer ${token}` },
        });
        const data = await resp.json();
        this._renderAnalyzeProposals(data);
      } catch (err) {
        this._appendMessage(`Analyze failed: ${err.message}`, "assistant");
      }
      return;
    }
    if (sub === "delete" && rest) {
      try {
        const resp = await fetch(`/api/kyber/knowledge?id=${encodeURIComponent(rest)}`, {
          method: "DELETE",
          headers: { Authorization: `Bearer ${token}` },
        });
        if (resp.ok) {
          this._appendMessage(`✓ Deleted memory entry \`${rest}\``, "assistant");
        } else {
          this._appendMessage(`Delete failed: ${resp.status}`, "assistant");
        }
      } catch (err) {
        this._appendMessage(`Delete failed: ${err.message}`, "assistant");
      }
      return;
    }
    this._appendMessage(
      "Usage: `/knowledge` (list), `/knowledge search <q>`, `/knowledge analyze`, `/knowledge delete <id>`",
      "assistant",
    );
  }

  async _fetchKnowledge(query = "") {
    const token = this._hass.auth.data.access_token;
    const url = query
      ? `/api/kyber/knowledge?q=${encodeURIComponent(query)}`
      : "/api/kyber/knowledge";
    const resp = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
    return resp.json();
  }

  _renderKnowledgePanel(data, opts = {}) {
    const entries = data.entries || [];
    const categories = data.categories || ["area_alias", "entity_note", "procedure", "device_chain", "general"];
    const history = this.shadowRoot.getElementById("chat-history");
    if (!history) return;

    const card = document.createElement("div");
    card.className = "chat-message assistant kyber-knowledge-panel";
    const reviewCount = data.needs_review_count || 0;
    const header = `
      <div class="kn-header">
        <strong>🧠 Memory${opts.query ? ` — results for "${this._escapeHtml(opts.query)}"` : ""}</strong>
        <span class="kn-count">${entries.length} entr${entries.length === 1 ? "y" : "ies"}</span>
        ${reviewCount > 0 ? `<button class="btn-kn-review-filter" title="Show only entries flagged by feedback">⚠ ${reviewCount} need review</button>` : ""}
      </div>
      <div class="kn-actions-bar">
        <button class="btn-kn-analyze">🔍 Analyze my home</button>
        <button class="btn-kn-add">➕ Add fact</button>
      </div>
    `;
    if (entries.length === 0) {
      card.innerHTML = header + `<div class="kn-empty">No saved knowledge yet. Click "Analyze my home" or "Add fact".</div>`;
    } else {
      const rows = entries.map((e) => this._renderKnowledgeRow(e, categories)).join("");
      card.innerHTML = header + `<div class="kn-list">${rows}</div>`;
    }
    history.appendChild(card);
    history.scrollTop = history.scrollHeight;

    card.querySelector(".btn-kn-analyze")?.addEventListener("click", () => this._handleKnowledgeCommand("analyze"));
    card.querySelector(".btn-kn-add")?.addEventListener("click", () => this._showKnowledgeEditor(null, categories, card));
    card.querySelector(".btn-kn-review-filter")?.addEventListener("click", async () => {
      const token = this._hass.auth.data.access_token;
      const resp = await fetch("/api/kyber/knowledge?needs_review=1", { headers: { Authorization: `Bearer ${token}` } });
      const d = await resp.json();
      card.remove();
      this._renderKnowledgePanel(d, { interactive: true, query: "needs review" });
    });
    card.querySelectorAll("[data-kn-id]").forEach((row) => {
      const id = row.getAttribute("data-kn-id");
      row.querySelector(".btn-kn-edit")?.addEventListener("click", () => {
        const entry = entries.find((e) => e.id === id);
        this._showKnowledgeEditor(entry, categories, card);
      });
      row.querySelector(".btn-kn-del")?.addEventListener("click", () => this._deleteKnowledgeEntry(id, row));
      row.querySelector(".btn-kn-clear")?.addEventListener("click", async () => {
        const token = this._hass.auth.data.access_token;
        await fetch("/api/kyber/knowledge", {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
          body: JSON.stringify({ id, needs_review: false }),
        });
        row.classList.remove("kn-row-flagged");
        row.querySelector(".kn-needs-review")?.remove();
        row.querySelector(".btn-kn-clear")?.remove();
      });
      row.querySelectorAll(".kn-star").forEach((star) => {
        star.addEventListener("click", () => {
          const r = parseInt(star.getAttribute("data-rating"), 10);
          this._rateKnowledgeEntry(id, r, row);
        });
      });
    });
  }

  _renderKnowledgeRow(e, categories) {
    const tags = (e.tags || []).map((t) => `<span class="kn-tag">${this._escapeHtml(t)}</span>`).join("");
    const stars = [1, 2, 3, 4, 5].map((i) =>
      `<span class="kn-star ${(e.user_rating || 0) >= i ? "filled" : ""}" data-rating="${i}" title="Rate ${i}/5">★</span>`,
    ).join("");
    const conf = Math.round((e.confidence || 0) * 100);
    const prov = e.provenance ? `<div class="kn-prov">📌 ${this._escapeHtml(e.provenance)}</div>` : "";
    const reviewBadge = e.needs_review ? `<span class="kn-needs-review" title="Flagged by feedback — please verify">⚠ needs review</span>` : "";
    const fb = (e.feedback || []).slice(-3).reverse();
    const fbBlock = fb.length
      ? `<details class="kn-fb"><summary>Feedback (${(e.feedback || []).length})</summary>${fb.map((f) => `<div class="kn-fb-item">${f.auto ? "🤖" : "👤"} ${f.rating}/5 ${f.notes ? "— " + this._escapeHtml(f.notes) : ""}</div>`).join("")}</details>`
      : "";
    return `
      <div class="kn-row ${e.needs_review ? "kn-row-flagged" : ""}" data-kn-id="${e.id}">
        <div class="kn-row-head">
          <span class="kn-cat">${this._escapeHtml(e.category || "general")}</span>
          ${e.subject ? `<span class="kn-subj">${this._escapeHtml(e.subject)}</span>` : ""}
          ${reviewBadge}
          <span class="kn-conf" title="Confidence">${conf}%</span>
          <span class="kn-stars" title="Your rating">${stars}</span>
          <span class="kn-row-actions">
            ${e.needs_review ? `<button class="btn-kn-clear" title="Mark resolved">✓</button>` : ""}
            <button class="btn-kn-edit" title="Edit / hint">✏️</button>
            <button class="btn-kn-del" title="Delete">🗑️</button>
          </span>
        </div>
        <div class="kn-content">${this._escapeHtml(e.content || "")}</div>
        ${tags ? `<div class="kn-tags">${tags}</div>` : ""}
        ${prov}
        ${fbBlock}
        <div class="kn-meta">id: <code>${e.id}</code> · source: ${this._escapeHtml(e.source || "manual")} · hits: ${e.hits || 0}</div>
      </div>
    `;
  }

  _showKnowledgeEditor(entry, categories, parentCard) {
    const isNew = !entry;
    const e = entry || { category: "general", subject: "", content: "", tags: [], confidence: 0.9, provenance: "" };
    const dlg = document.createElement("div");
    dlg.className = "kn-editor";
    dlg.innerHTML = `
      <div class="kn-editor-inner">
        <h3>${isNew ? "Add memory entry" : "Edit memory entry"}</h3>
        <label>Category
          <select class="kn-f-cat">${categories.map((c) => `<option ${c === e.category ? "selected" : ""}>${c}</option>`).join("")}</select>
        </label>
        <label>Subject (entity_id, area, or term)
          <input class="kn-f-subj" value="${this._escapeAttr(e.subject || "")}" placeholder="e.g. werkkamer or light.tv">
        </label>
        <label>Content / fact
          <textarea class="kn-f-content" rows="3" placeholder="What should Kyber remember?">${this._escapeHtml(e.content || "")}</textarea>
        </label>
        <label>Tags (comma-separated)
          <input class="kn-f-tags" value="${this._escapeAttr((e.tags || []).join(", "))}">
        </label>
        <label>Provenance / hint — where did this come from? how to verify?
          <input class="kn-f-prov" value="${this._escapeAttr(e.provenance || "")}" placeholder="e.g. User said in chat 2025-05-17">
        </label>
        <label>Confidence (0–100%)
          <input type="range" min="0" max="100" value="${Math.round((e.confidence || 0.9) * 100)}" class="kn-f-conf">
          <output class="kn-f-conf-val">${Math.round((e.confidence || 0.9) * 100)}%</output>
        </label>
        <div class="kn-editor-buttons">
          <button class="btn-kn-cancel">Cancel</button>
          <button class="btn-kn-save">${isNew ? "Add" : "Save"}</button>
        </div>
      </div>
    `;
    this.shadowRoot.appendChild(dlg);
    const confSlider = dlg.querySelector(".kn-f-conf");
    const confOut = dlg.querySelector(".kn-f-conf-val");
    confSlider.addEventListener("input", () => (confOut.textContent = confSlider.value + "%"));
    dlg.querySelector(".btn-kn-cancel").addEventListener("click", () => dlg.remove());
    dlg.querySelector(".btn-kn-save").addEventListener("click", async () => {
      const body = {
        ...(isNew ? {} : { id: e.id }),
        category: dlg.querySelector(".kn-f-cat").value,
        subject: dlg.querySelector(".kn-f-subj").value.trim(),
        content: dlg.querySelector(".kn-f-content").value.trim(),
        tags: dlg.querySelector(".kn-f-tags").value.split(",").map((t) => t.trim()).filter(Boolean),
        provenance: dlg.querySelector(".kn-f-prov").value.trim(),
        confidence: parseInt(confSlider.value, 10) / 100,
      };
      if (!body.content) {
        dlg.querySelector(".kn-f-content").focus();
        return;
      }
      try {
        const token = this._hass.auth.data.access_token;
        const resp = await fetch("/api/kyber/knowledge", {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
          body: JSON.stringify(body),
        });
        if (!resp.ok) {
          alert(`Save failed: ${resp.status}`);
          return;
        }
        dlg.remove();
        parentCard?.remove();
        await this._handleKnowledgeCommand("list");
      } catch (err) {
        alert(`Save failed: ${err.message}`);
      }
    });
  }

  async _deleteKnowledgeEntry(id, rowEl) {
    if (!confirm("Delete this memory entry?")) return;
    try {
      const token = this._hass.auth.data.access_token;
      const resp = await fetch(`/api/kyber/knowledge?id=${encodeURIComponent(id)}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (resp.ok) rowEl.remove();
    } catch (err) {
      alert(`Delete failed: ${err.message}`);
    }
  }

  async _rateKnowledgeEntry(id, rating, rowEl) {
    try {
      const token = this._hass.auth.data.access_token;
      const resp = await fetch("/api/kyber/knowledge", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ id, user_rating: rating }),
      });
      if (resp.ok) {
        rowEl.querySelectorAll(".kn-star").forEach((s) => {
          const r = parseInt(s.getAttribute("data-rating"), 10);
          s.classList.toggle("filled", r <= rating);
        });
      }
    } catch (err) {
      console.error("Rate failed", err);
    }
  }

  _renderAnalyzeProposals(data) {
    const history = this.shadowRoot.getElementById("chat-history");
    if (!history) return;
    const proposals = data.proposals || [];
    const stats = data.stats || {};
    const card = document.createElement("div");
    card.className = "chat-message assistant kyber-knowledge-panel";
    if (proposals.length === 0) {
      card.innerHTML = `<div class="kn-header"><strong>🔍 Analysis complete</strong></div>
        <div class="kn-empty">No new proposals. Scanned ${stats.automations_scanned || 0} automations, ${stats.scenes_scanned || 0} scenes, ${stats.scripts_scanned || 0} scripts.</div>`;
      history.appendChild(card);
      return;
    }
    const rows = proposals.map((p, idx) => `
      <div class="kn-row kn-proposal" data-idx="${idx}">
        <div class="kn-row-head">
          <input type="checkbox" class="kn-prop-check" checked />
          <span class="kn-cat">${this._escapeHtml(p.category || "general")}</span>
          ${p.subject ? `<span class="kn-subj">${this._escapeHtml(p.subject)}</span>` : ""}
          <span class="kn-conf">${Math.round((p.confidence || 0) * 100)}%</span>
        </div>
        <div class="kn-content">${this._escapeHtml(p.content || "")}</div>
        ${p.provenance ? `<div class="kn-prov">📌 ${this._escapeHtml(p.provenance)}</div>` : ""}
      </div>
    `).join("");
    card.innerHTML = `
      <div class="kn-header">
        <strong>🔍 Analyzed your home — ${proposals.length} proposal${proposals.length === 1 ? "" : "s"}</strong>
      </div>
      <div class="kn-empty">Scanned ${stats.automations_scanned || 0} automations, ${stats.scenes_scanned || 0} scenes, ${stats.scripts_scanned || 0} scripts. Untick anything you don't want saved.</div>
      <div class="kn-list">${rows}</div>
      <div class="kn-editor-buttons">
        <button class="btn-kn-cancel">Cancel</button>
        <button class="btn-kn-save-selected">Save selected</button>
      </div>
    `;
    history.appendChild(card);
    history.scrollTop = history.scrollHeight;
    card.querySelector(".btn-kn-cancel").addEventListener("click", () => card.remove());
    card.querySelector(".btn-kn-save-selected").addEventListener("click", async () => {
      const selected = [];
      card.querySelectorAll(".kn-prop-check").forEach((cb, i) => {
        if (cb.checked) selected.push(proposals[i]);
      });
      if (selected.length === 0) {
        card.remove();
        return;
      }
      try {
        const token = this._hass.auth.data.access_token;
        const resp = await fetch("/api/kyber/knowledge/analyze", {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
          body: JSON.stringify({ proposals: selected }),
        });
        const result = await resp.json();
        card.querySelector(".kn-empty").textContent = `✓ Saved ${result.count || 0} entries to memory.`;
        card.querySelector(".kn-editor-buttons").remove();
      } catch (err) {
        alert(`Save failed: ${err.message}`);
      }
    });
  }

  _escapeAttr(s) {
    return String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
  }

  // ────────────────────────────────────────────────────────────────────
  // Debug pane
  // ────────────────────────────────────────────────────────────────────
  _toggleDebugPane(force) {
    const pane = this.shadowRoot.getElementById("debug-pane");
    const chat = this.shadowRoot.querySelector(".chat-pane");
    if (!pane || !chat) return;
    const wantOpen = force === undefined ? pane.hasAttribute("hidden") : !!force;
    if (wantOpen) {
      pane.removeAttribute("hidden");
      chat.style.display = "none";
      this._debugTab = this._debugTab || "memory";
      this._renderDebugTab(this._debugTab);
    } else {
      pane.setAttribute("hidden", "");
      chat.style.display = "";
    }
  }

  async _renderDebugTab(tab) {
    this._debugTab = tab;
    const body = this.shadowRoot.getElementById("debug-body");
    if (!body) return;
    body.innerHTML = "<em>Loading…</em>";
    try {
      if (tab === "memory") {
        await this._renderDebugMemory(body);
      } else if (tab === "last_turn") {
        await this._renderDebugLastTurn(body);
      } else if (tab === "status") {
        await this._renderDebugStatus(body);
      }
    } catch (err) {
      body.innerHTML = `<div class="debug-error">Error: ${this._escapeHtml(err.message)}</div>`;
    }
  }

  async _renderDebugMemory(body) {
    const token = this._hass.auth.data.access_token;
    const resp = await fetch("/api/kyber/knowledge", { headers: { Authorization: `Bearer ${token}` } });
    const data = await resp.json();
    const entries = data.entries || [];
    const categories = data.categories || [];
    const filtered = (this._debugMemFilter || "all") === "review"
      ? entries.filter((e) => e.needs_review)
      : entries;
    const sortKey = this._debugMemSort || "updated";
    filtered.sort((a, b) => {
      if (sortKey === "hits") return (b.hits || 0) - (a.hits || 0);
      if (sortKey === "confidence") return (a.confidence || 0) - (b.confidence || 0);
      if (sortKey === "rating") return (b.user_rating || 0) - (a.user_rating || 0);
      return (b.updated || 0) - (a.updated || 0);
    });
    const reviewCount = data.needs_review_count || 0;
    const catCounts = {};
    entries.forEach((e) => { catCounts[e.category] = (catCounts[e.category] || 0) + 1; });
    const catBadges = Object.entries(catCounts).map(([k, v]) => `<span class="kn-tag">${this._escapeHtml(k)}: ${v}</span>`).join("");
    body.innerHTML = `
      <div class="debug-stats">
        <strong>${entries.length}</strong> entries · ${reviewCount} need review · ${catBadges}
      </div>
      <div class="debug-toolbar">
        <label>Filter
          <select id="dbg-mem-filter">
            <option value="all" ${(this._debugMemFilter||'all')==='all'?'selected':''}>All</option>
            <option value="review" ${this._debugMemFilter==='review'?'selected':''}>⚠ needs review</option>
          </select>
        </label>
        <label>Sort
          <select id="dbg-mem-sort">
            <option value="updated" ${(this._debugMemSort||'updated')==='updated'?'selected':''}>Most recent</option>
            <option value="hits" ${this._debugMemSort==='hits'?'selected':''}>Most hits</option>
            <option value="confidence" ${this._debugMemSort==='confidence'?'selected':''}>Lowest confidence</option>
            <option value="rating" ${this._debugMemSort==='rating'?'selected':''}>Highest rating</option>
          </select>
        </label>
        <button id="dbg-mem-add">➕ Add fact</button>
        <button id="dbg-mem-analyze">🔍 Analyze my home</button>
        <button id="dbg-mem-deep-analyze" title="AI-driven deep analysis of automations/scripts/blueprints with content-hash memoization">🧬 Deep analyze</button>
      </div>
      <div class="kn-list">${filtered.map((e) => this._renderKnowledgeRow(e, categories)).join("")}</div>
    `;
    body.querySelector("#dbg-mem-filter").addEventListener("change", (e) => {
      this._debugMemFilter = e.target.value;
      this._renderDebugTab("memory");
    });
    body.querySelector("#dbg-mem-sort").addEventListener("change", (e) => {
      this._debugMemSort = e.target.value;
      this._renderDebugTab("memory");
    });
    body.querySelector("#dbg-mem-add").addEventListener("click", () => this._showKnowledgeEditor(null, categories, null));
    body.querySelector("#dbg-mem-analyze").addEventListener("click", async () => {
      this._toggleDebugPane(false);
      await this._handleKnowledgeCommand("analyze");
    });
    body.querySelector("#dbg-mem-deep-analyze").addEventListener("click", async () => {
      const btn = body.querySelector("#dbg-mem-deep-analyze");
      const orig = btn.textContent;
      btn.disabled = true;
      btn.textContent = "🧬 Analyzing…";
      try {
        const token = this._hass.auth.data.access_token;
        const r = await fetch("/api/kyber/knowledge/analyze_deep", {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
          body: JSON.stringify({ limit: 5 }),
        });
        const j = await r.json();
        if (!r.ok) {
          alert("Deep analyze failed: " + (j.message || r.statusText));
        } else {
          const analyzed = (j.analyzed || []).length;
          const newFacts = (j.analyzed || []).reduce((n, a) => n + (a.fact_ids || []).length, 0);
          alert(`Deep analyze: ${analyzed} items processed, ${newFacts} new facts added, ${j.skipped_unchanged || 0} unchanged (skipped).`);
        }
      } catch (err) {
        alert("Deep analyze error: " + err);
      } finally {
        btn.disabled = false;
        btn.textContent = orig;
        this._renderDebugTab("memory");
      }
    });
    this._wireKnowledgeRowEvents(body, filtered, categories);
  }

  _wireKnowledgeRowEvents(root, entries, categories) {
    root.querySelectorAll("[data-kn-id]").forEach((row) => {
      const id = row.getAttribute("data-kn-id");
      row.querySelector(".btn-kn-edit")?.addEventListener("click", () => {
        const entry = entries.find((e) => e.id === id);
        this._showKnowledgeEditor(entry, categories, null);
      });
      row.querySelector(".btn-kn-del")?.addEventListener("click", () => this._deleteKnowledgeEntry(id, row));
      row.querySelector(".btn-kn-clear")?.addEventListener("click", async () => {
        const token = this._hass.auth.data.access_token;
        await fetch("/api/kyber/knowledge", {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
          body: JSON.stringify({ id, needs_review: false }),
        });
        this._renderDebugTab(this._debugTab);
      });
      row.querySelectorAll(".kn-star").forEach((star) => {
        star.addEventListener("click", () => {
          const r = parseInt(star.getAttribute("data-rating"), 10);
          this._rateKnowledgeEntry(id, r, row);
        });
      });
    });
  }

  async _renderDebugLastTurn(body) {
    const token = this._hass.auth.data.access_token;
    const resp = await fetch("/api/kyber/debug/last_turn", { headers: { Authorization: `Bearer ${token}` } });
    const data = await resp.json();
    const snap = data.snapshot;
    if (!snap) {
      body.innerHTML = `<div class="debug-empty">No turn captured yet. Ask Kyber something and come back.</div>`;
      return;
    }
    const picked = snap.picked_knowledge || [];
    const toolRows = (snap.tool_log || []).map((t) => `
      <tr>
        <td><code>${this._escapeHtml(t.name || t.tool || "?")}</code></td>
        <td class="dbg-mono">${this._escapeHtml(JSON.stringify(t.args || t.arguments || {}))}</td>
        <td>${t.status === "error" ? "❌" : "✓"}</td>
        <td>${t.ms ?? ""}</td>
      </tr>`).join("");
    const ts = snap.ts ? new Date(snap.ts * 1000).toLocaleTimeString() : "—";
    const knowledgeIds = (picked || []).map((p) => p.id).filter(Boolean);
    const hasKnowledge = knowledgeIds.length > 0;
    const autoNote = snap.auto_rating
      ? `<span class="tf-auto" title="Auto-flagged because the response looked uncertain">⚠ auto-rated ${snap.auto_rating}/5</span>`
      : "";
    const feedbackBar = `
      <div class="dbg-turn-feedback" id="dbg-turn-feedback" data-request-id="${this._escapeHtml(snap.request_id || "")}">
        <span class="tf-label">How was this turn?</span>
        <button class="tf-btn tf-btn-rate tf-up" title="Helpful — boost related memory" ${hasKnowledge ? "" : "disabled"}>👍 helpful</button>
        <button class="tf-btn tf-btn-rate tf-down" title="Not helpful — flag related memory for review" ${hasKnowledge ? "" : "disabled"}>👎 not helpful</button>
        ${autoNote}
        <span class="tf-status"></span>
        <button class="tf-btn tf-bundle" title="Download a zip with the full snapshot + logs of this turn" ${snap.request_id ? "" : "disabled"}>⬇ download bundle</button>
        <button class="tf-btn tf-bug-report" title="Create a GitHub bug report from this turn" ${snap.request_id ? "" : "disabled"}>🐛 bug report</button>
      </div>`;
    body.innerHTML = `
      ${feedbackBar}
      <div class="debug-stats">
        <strong>Turn at ${ts}</strong> · ${snap.elapsed_ms ?? "?"} ms · intent: <code>${this._escapeHtml(snap.intent || "?")}</code>
        · prompt: ${snap.char_count?.toLocaleString() ?? "?"} chars (~${snap.approx_tokens?.toLocaleString() ?? "?"} tokens)
        · auto_rating: ${snap.auto_rating ? `⚠ ${snap.auto_rating}/5` : "—"}
      </div>
      <details class="debug-section" open>
        <summary><strong>User prompt</strong></summary>
        <pre class="dbg-pre">${this._escapeHtml(snap.user_prompt || "")}</pre>
      </details>
      <details class="debug-section" open>
        <summary><strong>📌 Knowledge entries used this turn (${picked.length})</strong></summary>
        ${picked.length === 0 ? '<em>None injected.</em>' : '<div class="kn-list" id="dbg-picked-list"></div>'}
      </details>
      <details class="debug-section">
        <summary><strong>🔧 Tool calls (${(snap.tool_log || []).length})</strong></summary>
        ${toolRows ? `<table class="dbg-tools"><thead><tr><th>tool</th><th>args</th><th>status</th><th>ms</th></tr></thead><tbody>${toolRows}</tbody></table>` : '<em>No tool calls.</em>'}
      </details>
      <details class="debug-section">
        <summary><strong>📜 Expanded system prompt</strong> (what the model actually saw)</summary>
        <pre class="dbg-pre">${this._escapeHtml(snap.expanded_prompt || "")}</pre>
      </details>
      <details class="debug-section">
        <summary><strong>💬 Response text</strong></summary>
        <pre class="dbg-pre">${this._escapeHtml(snap.response_text || "")}</pre>
      </details>
    `;
    // Wire turn-feedback banner buttons
    const bar = body.querySelector("#dbg-turn-feedback");
    if (bar) {
      const reqId = bar.getAttribute("data-request-id");
      bar.querySelector(".tf-up")?.addEventListener("click", () => this._submitTurnFeedback(5, knowledgeIds, bar));
      bar.querySelector(".tf-down")?.addEventListener("click", () => this._submitTurnFeedback(2, knowledgeIds, bar));
      const dl = bar.querySelector(".tf-bundle");
      if (dl && reqId) dl.addEventListener("click", () => this._downloadDebugBundle(reqId, dl));
      const br = bar.querySelector(".tf-bug-report");
      if (br && reqId) br.addEventListener("click", () => this._openBugReportFlow(reqId, br));
    }
    if (picked.length > 0) {
      const list = body.querySelector("#dbg-picked-list");
      // Fetch full entries so we get tags + feedback log for rendering
      const fullResp = await fetch("/api/kyber/knowledge", { headers: { Authorization: `Bearer ${token}` } });
      const fullData = await fullResp.json();
      const byId = new Map((fullData.entries || []).map((e) => [e.id, e]));
      const fullPicked = picked.map((p) => byId.get(p.id) || p);
      list.innerHTML = fullPicked.map((e) => this._renderKnowledgeRowWithScore(e, picked.find((p) => p.id === e.id))).join("");
      this._wireKnowledgeRowEvents(list, fullPicked, fullData.categories || []);
      // Refine-with-hint inline action per row
      list.querySelectorAll("[data-kn-id]").forEach((row) => {
        const id = row.getAttribute("data-kn-id");
        row.querySelector(".btn-kn-refine")?.addEventListener("click", () => this._showRefineDialog(id, fullPicked.find((e) => e.id === id)));
      });
    }
  }

  _renderKnowledgeRowWithScore(entry, picked) {
    // Same as _renderKnowledgeRow but adds a similarity-score badge and a Refine button
    const base = this._renderKnowledgeRow(entry, []);
    const scoreBadge = (picked && typeof picked.score === "number")
      ? `<span class="kn-score" title="similarity score for last turn">score ${picked.score.toFixed(2)}</span>`
      : "";
    // Inject score badge + refine button into the row head
    return base
      .replace(
        '<span class="kn-row-actions">',
        `${scoreBadge}<button class="btn-kn-refine" title="Refine this fact — tell Kyber how it should be">✎ refine</button><span class="kn-row-actions">`,
      );
  }

  _showRefineDialog(id, entry) {
    const dlg = document.createElement("div");
    dlg.className = "kn-editor";
    dlg.innerHTML = `
      <div class="kn-editor-inner">
        <h3>Refine memory entry</h3>
        <p style="margin:0;color:var(--secondary-text-color);font-size:11px;">
          ${this._escapeHtml(entry.content || "")}
        </p>
        <label>How should Kyber update this fact?
          <textarea class="kn-f-refine" rows="4" placeholder="e.g. werkkamer is actually called 'home office' and contains light.desk + light.ceiling_office"></textarea>
        </label>
        <label>Optional new rating
          <select class="kn-f-rate">
            <option value="">— keep as is —</option>
            <option value="5">5 — perfect</option>
            <option value="4">4 — good</option>
            <option value="3">3 — okay</option>
            <option value="2">2 — wrong, please fix</option>
            <option value="1">1 — useless</option>
          </select>
        </label>
        <div class="kn-editor-buttons">
          <button class="btn-kn-cancel">Cancel</button>
          <button class="btn-kn-save">Apply refinement</button>
        </div>
      </div>
    `;
    this.shadowRoot.appendChild(dlg);
    dlg.querySelector(".btn-kn-cancel").addEventListener("click", () => dlg.remove());
    dlg.querySelector(".btn-kn-save").addEventListener("click", async () => {
      const hint = dlg.querySelector(".kn-f-refine").value.trim();
      const ratingStr = dlg.querySelector(".kn-f-rate").value;
      if (!hint && !ratingStr) { dlg.remove(); return; }
      const token = this._hass.auth.data.access_token;
      try {
        if (hint) {
          const newContent = (entry.content || "") + "\n\nRefinement: " + hint;
          const newProv = (entry.provenance ? entry.provenance + "; " : "") + `User refined ${new Date().toISOString().slice(0, 10)}`;
          await fetch("/api/kyber/knowledge", {
            method: "POST",
            headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
            body: JSON.stringify({ id, content: newContent, provenance: newProv, needs_review: false }),
          });
        }
        if (ratingStr) {
          await fetch("/api/kyber/knowledge/feedback", {
            method: "POST",
            headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
            body: JSON.stringify({ rating: parseInt(ratingStr, 10), knowledge_ids: [id], auto: false }),
          });
        }
        dlg.remove();
        this._renderDebugTab("last_turn");
      } catch (err) {
        alert(`Refine failed: ${err.message}`);
      }
    });
  }

  async _renderDebugStatus(body) {
    const token = this._hass.auth.data.access_token;
    const resp = await fetch("/api/kyber/debug/status", { headers: { Authorization: `Bearer ${token}` } });
    const data = await resp.json();
    const k = data.knowledge || {};
    const lt = data.last_turn;
    const catRows = Object.entries(k.by_category || {}).map(([cat, n]) =>
      `<tr><td><code>${this._escapeHtml(cat)}</code></td><td>${n}</td></tr>`,
    ).join("");
    body.innerHTML = `
      <h3>Runtime</h3>
      <table class="dbg-kv">
        <tr><th>AI Task entity</th><td><code>${this._escapeHtml(data.ai_task_entity || "—")}</code></td></tr>
        <tr><th>Autopilot</th><td>${this._autopilot ? "ON ⚡" : "OFF"}</td></tr>
        <tr><th>Session</th><td>${this._escapeHtml(this._sessionName || "—")}</td></tr>
        <tr><th>Tool history size</th><td>${data.tool_history_size}</td></tr>
      </table>
      <h3>Knowledge store</h3>
      <table class="dbg-kv">
        <tr><th>Total entries</th><td>${k.total ?? 0}</td></tr>
        <tr><th>Needs review</th><td>${k.needs_review ?? 0}</td></tr>
        <tr><th>Total hits</th><td>${k.total_hits ?? 0}</td></tr>
      </table>
      ${catRows ? `<h4>By category</h4><table class="dbg-kv">${catRows}</table>` : ""}
      <h3>Last turn</h3>
      ${lt ? `
        <table class="dbg-kv">
          <tr><th>When</th><td>${lt.ts ? new Date(lt.ts * 1000).toLocaleString() : "—"}</td></tr>
          <tr><th>Elapsed</th><td>${lt.elapsed_ms} ms</td></tr>
          <tr><th>Intent</th><td><code>${this._escapeHtml(lt.intent || "—")}</code></td></tr>
          <tr><th>Prompt size</th><td>${lt.char_count?.toLocaleString() ?? "?"} chars (~${lt.approx_tokens?.toLocaleString() ?? "?"} tokens)</td></tr>
        </table>
      ` : "<em>No turn captured yet.</em>"}
    `;
  }

  async _handleSessionCommand(argStr) {
    const parts = argStr.match(/^(\w+)(?:\s+(.*))?$/i);
    const sub = parts ? parts[1].toLowerCase() : "";
    const rest = parts ? (parts[2] || "").trim() : "";

    if (!sub || sub === "list") {
      const sessions = await this._loadSessionList();
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
    this._appendMessage(`Unknown session sub-command: "${sub}". Try: new, list, switch, delete`, "assistant");
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
      const cmds = ["autopilot on", "autopilot off", "dashboard", "automation", "script", "blueprint", "area", "knowledge", "memory", "reset", "help", "session"];
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

    // If the debug pane is visible, close it so the editor can occupy column 2.
    const debugPaneCheck = this.shadowRoot.getElementById("debug-pane");
    if (debugPaneCheck && !debugPaneCheck.hasAttribute("hidden")) {
      this._debugWasVisible = true;
      this._toggleDebugPane(false);
    }

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

    // Restore the debug pane if it was open when the editor was launched.
    if (this._debugWasVisible) {
      this._debugWasVisible = false;
      this._toggleDebugPane(true);
    }

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

    // If the debug pane is visible, close it so the editor can occupy column 2.
    const debugPaneCheckD = this.shadowRoot.getElementById("debug-pane");
    if (debugPaneCheckD && !debugPaneCheckD.hasAttribute("hidden")) {
      this._debugWasVisible = true;
      this._toggleDebugPane(false);
    }

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
      if (cmd === "knowledge" || cmd === "memory") {
        promptInput.value = "";
        await this._handleKnowledgeCommand(argStr.trim());
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
    this._showThinking();
    const requestId = (crypto.randomUUID && crypto.randomUUID()) || (Date.now() + "-" + Math.random().toString(36).slice(2));

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

      const resp_promise = fetch("/api/kyber/complete", {
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
          request_id: requestId,
          // Send all prior messages (everything except the just-pushed current user msg),
          // capped at HISTORY_WINDOW most recent entries.
          history: this._chatHistory.slice(0, -1).slice(-this._HISTORY_WINDOW),
          compacted_summary: this._compactedSummary,
        }),
      });

      // Poll progress while the main request is in flight
      let chatDone = false;
      this._pollProgress(requestId, () => chatDone).catch((err) => {
        console.error("[kyber] poll progress crashed", err);
      });
      console.debug("[kyber] started progress polling for", requestId);

      const resp = await resp_promise;
      chatDone = true;

      if (!resp.ok) {
        const err = await resp.text();
        throw new Error(`${resp.status}: ${err}`);
      }

      const data = await resp.json();
      this._hideThinking();
      // Store the assistant's text reply in history
      const textOnly = data.response
        .replace(/```yaml[\s\S]*?```/gi, "")
        .replace(/```plan[\s\S]*?```/gi, "")
        .trim();
      if (textOnly) {
        this._addChatHistory("assistant", textOnly);
      }
      this._appendAIResponse(data.response, data.yaml_blocks || [], data.plan || null, data.learned_fact || null);

      // Per-turn metadata is captured for the Debug tab ("Last turn") instead
      // of being attached to the chat message. The chat panel stays clean;
      // all feedback / debug-bundle UI lives in /kyber-debug.
      this._lastTurnMeta = {
        request_id: data.request_id || null,
        knowledge_used: data.knowledge_used || [],
        auto_rating: data.auto_rating || null,
        ts: Date.now(),
      };
      // Auto-refresh debug 'Last turn' pane if it is currently open
      const debugPane = this.shadowRoot.getElementById("debug-pane");
      if (debugPane && !debugPane.hasAttribute("hidden") && this._debugTab === "last_turn") {
        this._renderDebugTab("last_turn");
      }

      // Show tool call feedback pills above the response
      if (data.tool_log && data.tool_log.length > 0) {
        this._showToolLog(data.tool_log);
      }

      this._setStatus("Done");

      // Update context badge with live entity/automation counts
      if (data.context_stats) {
        this._updateContextBadge(data.context_stats);
      }

      // Compact overflow messages in the background
      this._maybeCompact();
    } catch (err) {
      this._hideThinking();
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

  _appendAIResponse(fullText, yamlBlocks, plan, learnedFact = null) {
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
        const READ_TOOL_TYPES = new Set([
          "list_entities_by_domain", "get_entity_state", "get_area_entities",
          "list_entities_by_label", "search_entities", "get_areas", "get_labels",
        ]);
        const allToolCalls = plan.actions.every((a) => READ_TOOL_TYPES.has(a.type));
        if (allToolCalls) {
          // Auto-execute read-only tool calls without showing proposal card
          this._autoExecuteToolPlan(plan, promptInput);
        } else {
          history.appendChild(this._buildPlanCard(plan));
        }
      }
    }

    // Show memory suggestion card if the backend extracted a learned fact
    if (learnedFact) {
      history.appendChild(this._buildMemoryCard(learnedFact));
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

  /** Auto-execute read-only tool calls (no user approval needed) and display results. */
  async _autoExecuteToolPlan(plan, _originalPrompt) {
    const history = this.shadowRoot?.getElementById("chat-history");
    if (!history) return;

    const spinner = document.createElement("div");
    spinner.className = "chat-message assistant";
    spinner.textContent = `🔍 Fetching data…`;
    history.appendChild(spinner);
    history.scrollTop = history.scrollHeight;

    try {
      const token = this._hass.auth.data.access_token;
      const resp = await fetch("/api/kyber/execute", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ actions: plan.actions }),
      });
      const data = await resp.json();
      const results = data.results || [];
      spinner.remove();

      // Display the tool results as formatted assistant messages
      results.forEach((r) => {
        const msg = document.createElement("div");
        msg.className = "chat-message assistant";
        const toolData = r.tool_result || r;
        const formatted = JSON.stringify(toolData, null, 2);
        msg.textContent = `📋 ${r.type}:\n${formatted}`;
        history.appendChild(msg);
      });
      history.scrollTop = history.scrollHeight;
    } catch (err) {
      spinner.textContent = `⚠ Tool fetch failed: ${err.message}`;
    }
  }

  }

  _buildMemoryCard(learnedFact) {
    const action = (learnedFact.actions || [])[0] || {};
    const userTerm = action.description?.match(/Save alias: (.+?) →/)?.[1]
      || learnedFact.summary?.match(/'(.+?)'/)?.[1]
      || "?";
    const haTerm = action.subject || learnedFact.summary?.match(/→ '(.+?)'/)?.[1] || "?";

    const card = document.createElement("div");
    card.className = "memory-card";
    card.innerHTML = `
      <div class="memory-card-header">🧠 Suggested memory</div>
      <div class="memory-card-content">
        "${userTerm}" → <strong>${haTerm}</strong><br>
        <small style="opacity:0.75">${action.content || learnedFact.summary || ""}</small>
      </div>
      <button class="btn-remember">💾 Remember</button>
    `;

    const btn = card.querySelector(".btn-remember");
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      btn.textContent = "Saving…";
      try {
        const token = this._hass?.auth?.data?.access_token;
        const resp = await fetch("/api/kyber/plan/execute", {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
          body: JSON.stringify({ plan: learnedFact }),
        });
        if (resp.ok) {
          btn.textContent = "✅ Remembered!";
          btn.style.background = "var(--success, #4caf50)";
        } else {
          btn.textContent = "⚠️ Failed";
          btn.disabled = false;
        }
      } catch (err) {
        btn.textContent = "⚠️ Error";
        btn.disabled = false;
      }
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

    // Split executable actions by approval requirement.
    // Config/destructive actions (assign_area, rename_entity, lock unlock, etc.)
    // ALWAYS need an explicit user click — autopilot cannot bypass them.
    const approvalActions = executableActions.filter((a) => a.requires_approval === true);
    const autoActions = executableActions.filter((a) => a.requires_approval !== true);
    const requiresApproval = plan.requires_approval === true || approvalActions.length > 0;
    const autopilotCanRun = this._autopilot && autoActions.length > 0;
    const approvalBadge = requiresApproval
      ? `<div class="plan-approval-note">🔒 ${approvalActions.length} action(s) change Home Assistant configuration and require your explicit approval.</div>`
      : "";

    card.innerHTML = `
      <div class="plan-overview">
        <div class="plan-overview-label">📋 Proposal</div>
        <div class="plan-overview-summary">${this._escapeHtml(plan.summary || "")}</div>
      </div>
      <div class="plan-changes-header">What will change</div>
      <ul class="plan-changes">${changeRows}</ul>
      ${missingWarning}
      ${warnings}
      ${approvalBadge}
      ${autopilotCanRun && !requiresApproval
        ? `<div class="plan-result" style="color:var(--warning-color,#ff9800);font-size:12px">⚡ Autopilot: executing in 2s…</div>`
        : `<button class="btn-execute"${hasExecutable ? "" : " disabled"}>✅ Execute${invalidEntities.size > 0 && hasExecutable ? ` (${executableActions.length} of ${(plan.actions || []).length})` : ""}</button>`
      }
      <div class="plan-result" id="plan-result-${Date.now()}"></div>
    `;

    // Grab the result element (last .plan-result in card)
    const allResults = card.querySelectorAll(".plan-result");
    const resultEl = allResults[allResults.length - 1];

    // doExecute(opts): user click = approved:true (runs all incl. config changes).
    // Autopilot path passes approved:false and only the safe subset.
    const doExecute = async (opts = {}) => {
      const approved = opts.approved !== false; // default: user-approved
      const actionsToRun = opts.actions || executableActions;
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
          body: JSON.stringify({ actions: actionsToRun, approved }),
        });
        if (resp.status === 403) {
          const blocked = await resp.json().catch(() => ({}));
          resultEl.textContent = `🔒 Approval required for ${(blocked.blocked_actions || []).length} action(s). Click Execute to approve.`;
          resultEl.className = "plan-result";
          if (card.querySelector(".btn-execute")) card.querySelector(".btn-execute").disabled = false;
          return;
        }
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
      card.querySelector(".btn-execute").addEventListener("click", () => doExecute({ approved: true }));
    }

    // Autopilot: only auto-execute the SAFE subset (runtime state changes).
    // Config-changing/destructive actions always wait for explicit approval.
    if (this._autopilot && autoActions.length > 0 && !requiresApproval) {
      setTimeout(() => doExecute({ approved: false, actions: autoActions }), 2000);
    } else if (this._autopilot && autoActions.length > 0 && requiresApproval) {
      // Mixed plan: auto-run safe ones, leave Execute button for the rest.
      setTimeout(() => {
        resultEl.textContent = `⚡ Autopilot: running ${autoActions.length} safe action(s); config changes await your approval…`;
        doExecute({ approved: false, actions: autoActions });
      }, 2000);
    }

    return card;
  }

  _showThinking() {
    const history = this.shadowRoot?.getElementById("chat-history");
    if (!history) return;
    this._hideThinking(); // ensure no duplicate
    const bubble = document.createElement("div");
    bubble.id = "kyber-thinking-bubble";
    bubble.className = "chat-message assistant";
    bubble.innerHTML = `
      <div class="thinking-bubble">
        <div class="thinking-header">
          <div class="thinking-dots">
            <span></span><span></span><span></span>
          </div>
          <span class="thinking-label">Thinking…</span>
        </div>
        <div class="thinking-events" id="kyber-thinking-events"></div>
      </div>
    `;
    history.appendChild(bubble);
    history.scrollTop = history.scrollHeight;
  }

  _setThinkingLabel(label) {
    const el = this.shadowRoot?.querySelector("#kyber-thinking-bubble .thinking-label");
    if (el) el.textContent = label;
  }

  _appendThinkingEvent(html) {
    const events = this.shadowRoot?.getElementById("kyber-thinking-events");
    if (!events) return;
    const item = document.createElement("div");
    item.className = "thinking-event";
    item.innerHTML = html;
    events.appendChild(item);
    const history = this.shadowRoot?.getElementById("chat-history");
    if (history) history.scrollTop = history.scrollHeight;
  }

  _renderProgressEvent(ev) {
    if (!ev || !ev.type) return;
    if (ev.type === "info") {
      this._appendThinkingEvent(
        `<span class="thinking-info">ℹ️ ${this._escapeHTML(ev.message || "")}</span>`
      );
    } else if (ev.type === "tool_call") {
      const args = ev.args ? Object.entries(ev.args).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ") : "";
      this._setThinkingLabel("Calling tool…");
      this._appendThinkingEvent(
        `<span class="thinking-tool-name">🔧 ${this._escapeHTML(ev.name || "?")}</span>` +
        (args ? `<span class="thinking-tool-args"> (${this._escapeHTML(args)})</span>` : "") +
        `<span class="thinking-tool-status thinking-tool-running"> …</span>`
      );
    } else if (ev.type === "tool_result") {
      // Update the most recent matching tool_call event in-place
      const events = this.shadowRoot?.getElementById("kyber-thinking-events");
      if (events) {
        const items = events.querySelectorAll(".thinking-event");
        for (let i = items.length - 1; i >= 0; i--) {
          const nameEl = items[i].querySelector(".thinking-tool-name");
          const statusEl = items[i].querySelector(".thinking-tool-status");
          if (nameEl && statusEl && nameEl.textContent.includes(ev.name) &&
              statusEl.classList.contains("thinking-tool-running")) {
            statusEl.classList.remove("thinking-tool-running");
            statusEl.classList.add("thinking-tool-done");
            statusEl.textContent = ` → ${ev.summary || "done"}`;
            if (ev.preview) {
              items[i].dataset.preview = ev.preview;
              items[i].style.cursor = "pointer";
              items[i].title = "Click to view raw result";
              items[i].addEventListener("click", () => {
                let pre = items[i].querySelector("pre.thinking-tool-preview");
                if (pre) { pre.remove(); return; }
                pre = document.createElement("pre");
                pre.className = "thinking-tool-preview";
                pre.textContent = items[i].dataset.preview;
                items[i].appendChild(pre);
              });
            }
            break;
          }
        }
      }
      this._setThinkingLabel("Thinking…");
    } else if (ev.type === "thinking") {
      this._setThinkingLabel(ev.stage === "follow_up" ? "Reasoning over results…" : "Thinking…");
    } else if (ev.type === "error") {
      this._appendThinkingEvent(`<span class="thinking-error">⚠️ ${this._escapeHTML(ev.message || "error")}</span>`);
    }
  }

  _escapeHTML(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
  }

  async _pollProgress(requestId, isDone) {
    let cursor = 0;
    let polls = 0;
    while (!isDone()) {
      try {
        const token = this._hass.auth.data.access_token;
        const r = await fetch(`/api/kyber/progress?id=${encodeURIComponent(requestId)}&since=${cursor}`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (r.ok) {
          const data = await r.json();
          polls += 1;
          if (data.events && data.events.length) {
            console.debug("[kyber] progress", data.events.length, "new events, status:", data.status);
          }
          for (const ev of (data.events || [])) {
            try { this._renderProgressEvent(ev); }
            catch (err) { console.error("[kyber] render progress event failed", err, ev); }
          }
          cursor = data.next || cursor;
          if (data.status === "done") return;
        } else {
          console.warn("[kyber] progress fetch HTTP", r.status);
        }
      } catch (err) {
        console.warn("[kyber] progress poll error", err);
      }
      await new Promise((res) => setTimeout(res, 200));
    }
    console.debug("[kyber] progress polling stopped after", polls, "polls");
  }

  _hideThinking() {
    this.shadowRoot?.getElementById("kyber-thinking-bubble")?.remove();
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

  _showToolLog(toolLog) {
    const history = this.shadowRoot?.getElementById("chat-history");
    if (!history || !toolLog || toolLog.length === 0) return;
    const toolIcons = {
      list_entities_by_domain: "🔍",
      get_entity_state: "📡",
      get_area_entities: "🏠",
      list_entities_by_label: "🏷",
      search_entities: "🔎",
      get_areas: "🗺",
      get_labels: "🏷",
    };
    const container = document.createElement("div");
    container.className = "tool-log";
    toolLog.forEach((entry) => {
      const icon = toolIcons[entry.name] || "🔧";
      const argsStr = Object.entries(entry.args || {})
        .map(([k, v]) => `${k}="${v}"`)
        .join(", ");
      const pill = document.createElement("span");
      pill.className = "tool-pill";
      pill.title = argsStr ? `${entry.name}(${argsStr})` : entry.name;
      pill.innerHTML = `<span class="tool-icon">${icon}</span><span class="tool-name">${this._escapeHtml(entry.name)}</span><span>→ ${this._escapeHtml(entry.summary)}</span>`;
      container.appendChild(pill);
    });
    history.appendChild(container);
    history.scrollTop = history.scrollHeight;
  }

  _updateContextBadge(stats) {
    const badge = this.shadowRoot?.getElementById("context-badge");
    if (!badge) return;
    const parts = [`${stats.entity_count || 0} entities`];
    if (stats.automation_count) parts.push(`${stats.automation_count} automations`);
    if (stats.lights_on) parts.push(`💡 ${stats.lights_on} on`);
    badge.textContent = parts.join(" · ");
    badge.title = [
      `Entities: ${stats.entity_count || 0}`,
      `Automations: ${stats.automation_count || 0}`,
      `Areas: ${stats.area_count || 0}`,
      stats.lights_on ? `Lights on: ${stats.lights_on}` : null,
      stats.unavailable_count ? `⚠️ Unavailable: ${stats.unavailable_count}` : null,
      stats.low_battery_count ? `🪫 Low battery: ${stats.low_battery_count}` : null,
    ].filter(Boolean).join("\n");
  }

  _showContextRefreshedMessage(label = "Context refreshed") {
    const history = this.shadowRoot?.getElementById("chat-history");
    if (!history) return;
    const div = document.createElement("div");
    div.className = "chat-message system-info";
    const badge = this.shadowRoot?.getElementById("context-badge");
    const detail = badge?.textContent ? ` — ${badge.textContent}` : "";
    div.textContent = `🔄 ${label}${detail}`;
    history.appendChild(div);
    history.scrollTop = history.scrollHeight;
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

if (!customElements.get("kyber-panel")) {
  customElements.define("kyber-panel", KyberPanel);
}
