/**
 * Browser-compatible CodeMirror stub for UI test harness.
 * Exports no-op replacements for every named export used by kyber-panel.js.
 * The panel creates an EditorView lazily (only when the YAML editor opens),
 * so tests that don't open the editor never exercise these stubs.
 */

export class EditorState {
  static create() { return new EditorState(); }
}

export class EditorView {
  constructor(opts) {
    this.dom = document.createElement("div");
  }
  destroy() {}
  dispatch() {}
  focus() {}
  requestMeasure() {}
  get state() { return { doc: { toString: () => "", lines: 1, line: () => ({ from: 0, to: 0 }), lineAt: () => ({ number: 1 }) }, selection: { main: { head: 0 } } }; }
  static updateListener = { of: () => ({}) };
}

export const keymap          = { of: () => ({}) };
export const lineNumbers     = () => ({});
export const highlightActiveLine = () => ({});
export const drawSelection   = () => ({});
export const history         = () => ({});
export const historyKeymap   = [];
export const defaultKeymap   = [];
export const indentWithTab   = {};
export const yaml            = () => ({});
export const oneDark         = {};
export const syntaxHighlighting = () => ({});
export const defaultHighlightStyle = {};
export const bracketMatching = () => ({});
export const foldGutter      = () => ({});
export const autocompletion  = () => ({});
export const closeBrackets   = () => ({});
