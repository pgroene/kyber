// No-op stubs for CodeMirror — tests don't exercise the editor widget,
// so we export lightweight stand-ins that satisfy all the imports in kyber-panel.js.

export const EditorState = {
  create: () => ({ doc: { toString: () => "" } }),
};
export const EditorView = class EditorView {
  constructor() {
    this.state = { doc: { toString: () => "" } };
    this.dom = document.createElement("div");
  }
  dispatch() {}
  destroy() {}
};
export const keymap = { of: () => ({}) };
export const lineNumbers = () => ({});
export const highlightActiveLine = () => ({});
export const drawSelection = () => ({});
export const history = () => ({});
export const historyKeymap = [];
export const defaultKeymap = [];
export const indentWithTab = {};
export const yaml = () => ({});
export const oneDark = {};
export const syntaxHighlighting = () => ({});
export const defaultHighlightStyle = {};
export const bracketMatching = () => ({});
export const foldGutter = () => ({});
export const autocompletion = () => ({});
export const closeBrackets = () => ({});
