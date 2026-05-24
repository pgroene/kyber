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
} from "../codemirror-bundle.js";

export const EditorMixin = (Base) => class extends Base {
  _initEditor(container) {
    const self = this;

    // Create diagram and inspector panels as flex siblings to the CodeMirror editor
    const diag = document.createElement("div");
    diag.id = "automation-diagram";
    diag.className = "automation-diagram";
    diag.hidden = true;
    container.appendChild(diag);

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
          clearTimeout(self._diagramDebounce);
          self._diagramDebounce = setTimeout(() => {
            self._renderAutomationDiagram(update.state.doc.toString());
          }, 350);
          // Re-parse YAML server-side so diagram reflects editor changes
          if (self._editorMode === "automation" || self._editorMode === "script") {
            clearTimeout(self._configReparseDebounce);
            self._configReparseDebounce = setTimeout(() => {
              self._reparseEditorConfig(update.state.doc.toString());
            }, 1200);
          }
          // Persist draft so navigating away and returning restores unsaved edits
          clearTimeout(self._draftSaveDebounce);
          self._draftSaveDebounce = setTimeout(() => {
            self._saveEditorDraft(update.state.doc.toString());
          }, 800);
        }
        if (update.selectionSet || update.docChanged) {
          const cursorLine = update.state.doc.lineAt(update.state.selection.main.head).number - 1;
          const cursorPos = update.state.selection.main.head;
          self._updateDiagramHighlight(cursorLine);
          if (self._errorLineNum) requestAnimationFrame(() => self._applyErrorLineStyle());
          clearTimeout(self._inspectorDebounce);
          self._inspectorDebounce = setTimeout(() => {
            const yamlText = update.state.doc.toString();
            self._updateTemplateInspector(cursorLine, yamlText, cursorPos);
            self._updateEntityInspector(cursorLine, yamlText, cursorPos);
            self._updateEntityListPicker(cursorLine, yamlText, cursorPos);
          }, 250);
        }
      }),
    ];

    this._editor = new EditorView({
      state: EditorState.create({ doc: "", extensions }),
      parent: container,
    });

    // Floating entity inspector — appended to editor-pane (position: relative)
    // so it can be absolutely positioned to the right of the cursor line
    const editorPane = container.closest
      ? container.closest(".editor-pane") || container
      : container;
    const insp = document.createElement("div");
    insp.id = "entity-inspector";
    insp.className = "entity-inspector";
    insp.hidden = true;
    editorPane.appendChild(insp);

    // Floating template inspector — shows live preview of value_template
    const tplInsp = document.createElement("div");
    tplInsp.id = "template-inspector";
    tplInsp.className = "template-inspector";
    tplInsp.hidden = true;
    editorPane.appendChild(tplInsp);

    // Floating entity-list picker — add entities to YAML lists
    const picker = document.createElement("div");
    picker.id = "entity-list-picker";
    picker.className = "entity-list-picker";
    picker.hidden = true;
    picker.innerHTML = `
      <div class="elp-header">
        <span class="elp-title">Add entity</span>
        <button class="elp-close" title="Close">✕</button>
      </div>
      <input class="elp-search" id="elp-search" type="text" placeholder="Search entities…" autocomplete="off">
      <div class="elp-results" id="elp-results"></div>
    `;
    editorPane.appendChild(picker);
    picker.querySelector(".elp-close").addEventListener("click", () => {
      picker.hidden = true;
      this._entityListPickerOpen = false;
    });
    picker.querySelector(".elp-search").addEventListener("input", (e) => {
      this._renderEntityPickerResults(e.target.value);
    });
    picker.querySelector(".elp-search").addEventListener("keydown", (e) => e.stopPropagation());

    // Close picker when clicking outside it
    document.addEventListener("click", (e) => {
      if (!picker.hidden && !picker.contains(e.target)) {
        picker.hidden = true;
        this._entityListPickerOpen = false;
      }
    }, true);

    container.addEventListener("keydown", (e) => e.stopPropagation());
    container.addEventListener("keyup", (e) => e.stopPropagation());
    container.addEventListener("keypress", (e) => e.stopPropagation());
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

    this._currentAutomationId = configId;
    this._editorTitle = friendlyName;
    this._editorMode = isScript ? "script" : "automation";
    this.shadowRoot.getElementById("btn-save").textContent = isScript ? "Save script" : "Save automation";
    this._saveEditorSession(configId, isScript ? "script" : "automation", friendlyName);
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
    this._currentAutomationConfig = null;
    this._savedYaml = null; // original YAML from last load/save for dirty tracking
    this._editorTitle = null;
    this._currentDashboardPath = null;
    this._currentBlueprintPath = null;
    this._editorMode = "automation";
    this._dirty = false;
    this._setStatus("");
    this._clearEditorSession();
    // Hide diagram and inspector
    const diag = this.shadowRoot.getElementById("automation-diagram");
    if (diag) diag.hidden = true;
    const insp = this.shadowRoot.getElementById("entity-inspector");
    if (insp) insp.hidden = true;
    // Restore button labels
    const saveBtn = this.shadowRoot.getElementById("btn-save");
    if (saveBtn) { saveBtn.textContent = "Save"; saveBtn.disabled = true; }
    // Hide dashboard/blueprint-specific controls
    const sel = this.shadowRoot.getElementById("dashboard-select");
    if (sel) sel.style.display = "none";
    this._updateBlueprintButton(null);
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
    const totalChars = this._chatHistory.reduce((sum, m) => sum + (m.content || "").length, 0);
    const sizeTriggered = totalChars > this._COMPACT_SIZE_TRIGGER;
    const countTriggered = this._chatHistory.length > this._COMPACT_COUNT_TRIGGER;
    if (!sizeTriggered && !countTriggered) return;

    // Determine cut point (whole messages only — never split a message)
    let cutIndex = 0;
    if (sizeTriggered) {
      // Walk from oldest; accumulate until we've covered >= COMPACT_OLDEST_CHARS
      let charCount = 0;
      for (let i = 0; i < this._chatHistory.length; i++) {
        charCount += (this._chatHistory[i].content || "").length;
        cutIndex = i + 1;
        if (charCount >= this._COMPACT_OLDEST_CHARS) break;
      }
    } else {
      // Count-triggered: compact oldest half
      cutIndex = Math.floor(this._chatHistory.length / 2);
    }

    // Always keep at least one message in the recent window
    cutIndex = Math.min(cutIndex, this._chatHistory.length - 1);
    if (cutIndex <= 0) return;

    const toCompact = this._chatHistory.splice(0, cutIndex);

    try {
      const token = this._hass.auth.data.access_token;
      const resp = await fetch("/api/kyber/summarize", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ previous_summary: this._compactedSummary, messages: toCompact }),
      });
      if (resp.ok) {
        const data = await resp.json();
        this._compactedSummary = data.summary || this._compactedSummary;
        this._showCompactionBanner();
        this._persistHistory();
      } else {
        this._chatHistory.unshift(...toCompact);
      }
    } catch (_err) {
      // Compaction failure is non-fatal — restore messages
      this._chatHistory.unshift(...toCompact);
    }
  }

  _showCompactionBanner() {
    const history = this.shadowRoot?.getElementById("chat-history");
    if (!history) return;
    const wrap = document.createElement("div");
    wrap.className = "chat-message-wrap system-compact";
    const msg = document.createElement("div");
    msg.className = "chat-message system-compact";
    msg.textContent = "💬 Older context was summarized to keep responses accurate. For a fresh start, begin a new conversation.";
    wrap.appendChild(msg);
    history.appendChild(wrap);
    history.scrollTop = history.scrollHeight;
  }

  // ─── Automation diagram ────────────────────────────────────────────────────

  /**
   * Parse YAML text into { alias, triggers, conditions, actions } where each
   * item has { from_line (0-based), to_line (0-based, inclusive), fields }.
   */
  _parseAutomationBlocks(yamlText) {
    const lines = yamlText.split("\n");
    const result = { alias: "", triggers: [], conditions: [], actions: [] };

    const aliasLine = lines.find((l) => /^alias\s*:/.test(l));
    if (aliasLine) result.alias = aliasLine.replace(/^alias\s*:\s*/, "").replace(/['"]/g, "").trim();

    const sectionMap = {
      trigger: "triggers", triggers: "triggers",
      condition: "conditions", conditions: "conditions",
      action: "actions", actions: "actions",
      sequence: "actions",  // scripts use sequence: instead of action:
    };

    let currentSection = null;
    let currentItem = null;
    let itemIndent = -1; // auto-detected indent level for list items in current section

    const pushItem = (endLine) => {
      if (currentItem && currentSection) {
        currentItem.to_line = endLine;
        result[currentSection].push(currentItem);
        currentItem = null;
      }
    };

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (!line.trim()) continue;
      // Skip inline flow values like {} or []
      if (/^\s*[\{\[]/.test(line)) continue;

      const indent = (line.match(/^(\s*)/) || ["", ""])[1].length;

      // Top-level section header (no indent, alphanumeric key)
      const secM = line.match(/^([a-z_]+)\s*:/);
      if (secM) {
        pushItem(i - 1);
        currentSection = sectionMap[secM[1]] || null;
        itemIndent = -1; // reset — will auto-detect from first list item
        continue;
      }

      if (!currentSection) continue;

      // Detect list item: "- " at any indent
      const listM = line.match(/^(\s*)-\s/);
      if (listM) {
        const listIndent = listM[1].length;
        // Auto-detect item indent from first list item in section
        if (itemIndent < 0) itemIndent = listIndent;
        // Only treat as a new top-level item if at the detected indent level
        if (listIndent === itemIndent) {
          pushItem(i - 1);
          currentItem = { from_line: i, to_line: i, fields: {} };
          const inline = line.slice(listM[0].length).trim();
          if (inline.includes(": ")) {
            const ci = inline.indexOf(": ");
            const k = inline.slice(0, ci).trim();
            const v = inline.slice(ci + 2).replace(/['"]/g, "").trim();
            if (k) currentItem.fields[k] = v;
          } else if (inline && inline.endsWith(":")) {
            const k = inline.slice(0, -1).trim();
            if (k) currentItem.fields[k] = true;
          } else if (inline && !inline.includes(":")) {
            currentItem.fields._value = inline;
          }
          continue;
        }
      }

      // Field lines: deeper than item indent, contain key: value
      if (currentItem && indent > itemIndent) {
        const trimmed = line.trim();
        // Only capture direct child key-value pairs (one indent level deeper)
        if (indent <= itemIndent + 4) {
          const ci = trimmed.indexOf(":");
          if (ci > 0) {
            const k = trimmed.slice(0, ci).trim();
            const rawV = trimmed.slice(ci + 1).trim();
            const v = rawV.replace(/['"]/g, "");
            currentItem.fields[k] = v;
            currentItem._lastKey = k;
          }
        }
        // Sub-list items: fill in empty parent key with first value
        if (/^\s*-\s/.test(line) && currentItem._lastKey && currentItem.fields[currentItem._lastKey] === "") {
          const val = line.replace(/^\s*-\s*/, "").trim().replace(/['"]/g, "");
          currentItem.fields[currentItem._lastKey] = val;
        }
      }
    }
    pushItem(lines.length - 1);
    return result;
  }

  _blockMeta(section, fields) {
    if (section === "triggers") {
      const p = fields.platform || fields.trigger || "";
      const ICONS = { sun: "🌅", state: "📡", time: "⏰", homeassistant: "🏠", webhook: "🌐", event: "⚡", template: "📋", zone: "📍", numeric_state: "🔢", device: "📱", calendar: "📅", tag: "🏷", geo_location: "🗺", persistent_notification: "🔔", conversation: "💬" };
      let sub;
      if (p === "state" || p === "numeric_state") {
        const entity = (fields.entity_id || "").split(",")[0].trim();
        const eName = entity.includes(".") ? entity.split(".")[1] : entity;
        const toStr = fields.to ? ` → ${fields.to}` : (fields.above || fields.below ? ` ${fields.above ?? ""}…${fields.below ?? ""}` : "");
        sub = eName + toStr;
      } else {
        sub = (fields.event || fields.entity_id || fields.at || fields.event_type || "").split(",")[0].trim();
      }
      return { icon: ICONS[p] || "⚡", title: p || "trigger", sub };
    }
    if (section === "conditions") {
      const c = fields.condition || "";
      const ICONS = { state: "✅", template: "📋", time: "⏰", numeric_state: "🔢", zone: "📍", and: "🔗", or: "🔀", not: "❌", device: "📱", trigger: "⚡" };
      const sub = (fields.entity_id || fields.value_template || "").split(",")[0].trim();
      return { icon: ICONS[c] || "❓", title: c || "condition", sub };
    }
    // actions
    if (fields.choose !== undefined) return { icon: "🔀", title: "choose", sub: "" };
    if (fields.if !== undefined) return { icon: "🔀", title: "if/then", sub: "" };
    if (fields.parallel !== undefined) return { icon: "⚡", title: "parallel", sub: "" };
    if (fields.repeat !== undefined) return { icon: "🔁", title: "repeat", sub: "" };
    if (fields.wait_template !== undefined || fields.wait_for_trigger !== undefined) return { icon: "⏳", title: "wait", sub: "" };
    if (fields.delay !== undefined) return { icon: "⏱", title: "delay", sub: String(fields.delay) };
    if (fields.stop !== undefined) return { icon: "🛑", title: "stop", sub: "" };
    if (fields.event !== undefined) return { icon: "📡", title: "fire event", sub: String(fields.event) };
    if (fields.variables !== undefined) return { icon: "📦", title: "variables", sub: "" };
    const svc = fields.service || fields.action || "";
    const SVC_ICONS = { "light.turn_on": "💡", "light.turn_off": "💡", "light.toggle": "💡", "switch.turn_on": "🔌", "switch.turn_off": "🔌", "media_player": "🎵", "notify": "📢", "script": "📜", "climate": "🌡️", "homeassistant": "🏠", "automation": "⚙️", "input_boolean": "🔘", "input_number": "🔢", "input_select": "📋", "cover": "🪟", "lock": "🔒", "alarm_control_panel": "🚨", "vacuum": "🤖", "fan": "💨", "button": "🔘", "scene": "🎨" };
    const icon = Object.keys(SVC_ICONS).find((k) => svc.startsWith(k));
    const sub = (fields.entity_id || "").split(",")[0].trim();
    return { icon: icon ? SVC_ICONS[icon] : "▶️", title: svc || "action", sub };
  }

  _renderAutomationDiagram(yamlText) {
    const diag = this.shadowRoot.getElementById("automation-diagram");
    if (!diag) return;
    if (!yamlText?.trim() || this._editorMode === "dashboard" || this._editorMode === "blueprint") {
      diag.hidden = true;
      return;
    }

    const cfg = this._currentAutomationConfig;
    if (cfg) {
      // Compare YAML block counts with JSON config to detect stale config
      const blocks = this._parseAutomationBlocks(yamlText);
      const isScript = this._editorMode === "script";
      const jsonTriggers = isScript ? [] : [].concat(cfg.triggers || cfg.trigger || []).filter(Boolean);
      const jsonActions = isScript
        ? [].concat(cfg.sequence || []).filter(Boolean)
        : [].concat(cfg.actions || cfg.action || []).filter(Boolean);
      if (blocks.triggers.length !== jsonTriggers.length || blocks.actions.length !== jsonActions.length) {
        // Config is stale — fall back to YAML-only rendering until reparse completes
        this._renderDiagramFromYaml(diag, yamlText);
      } else {
        this._renderDiagramFromJson(diag, cfg, yamlText);
      }
    } else {
      this._renderDiagramFromYaml(diag, yamlText);
    }
  }

  // ── Diagram from JSON config (accurate, expanded) ─────────────────────────

  _renderDiagramFromJson(diag, cfg, yamlText) {
    const isScript = this._editorMode === "script";

    // Scripts use sequence: instead of trigger:/action:
    const triggers    = isScript ? [] : [].concat(cfg.triggers || cfg.trigger || []).filter(Boolean);
    let   conditions  = isScript ? [] : [].concat(cfg.conditions || cfg.condition || []).filter(Boolean);
    const actions     = isScript
      ? [].concat(cfg.sequence || []).filter(Boolean)
      : [].concat(cfg.actions || cfg.action || []).filter(Boolean);

    // Build YAML line-range index for cursor ↔ node sync
    this._diagLineBlocks = this._parseAutomationBlocks(yamlText);

    // Fallback: if JSON config has no conditions but YAML parser found some,
    // use YAML-parsed fields (handles stale config when yaml.safe_load fails on HA's {} syntax)
    if (!conditions.length && this._diagLineBlocks.conditions.length) {
      conditions = this._diagLineBlocks.conditions.map((b) => ({ ...b.fields }));
    }

    const total = triggers.length + conditions.length + actions.length;
    if (!total) {
      // Blueprint automation — show blueprint info panel instead of hiding
      const bp = cfg.use_blueprint;
      if (bp) {
        diag.hidden = false;
        const inputs = bp.input || {};
        const inputRows = Object.entries(inputs)
          .map(([k, v]) => `<div class="adg-bp-row"><span class="adg-bp-key">${this._escH(k)}:</span> <span class="adg-bp-val">${this._escH(String(v))}</span></div>`)
          .join("");
        diag.innerHTML = `<div class="adg-blueprint-info">
          <div class="adg-bp-header">📋 <strong>${this._escH(bp.path || "Blueprint")}</strong></div>
          ${inputRows ? `<div class="adg-bp-inputs">${inputRows}</div>` : ""}
        </div>`;
        return;
      }
      diag.hidden = true;
      return;
    }
    diag.hidden = false;

    // ── Miller-column helpers ────────────────────────────────────────────────
    const COND_ICONS = { state: "✅", template: "📋", time: "⏰", numeric_state: "🔢", zone: "📍", and: "🔗", or: "🔀", not: "❌", device: "📱", trigger: "⚡", sun: "🌅" };

    // Remove all drilldown columns at level >= `fromLevel`
    const removeDrilldownCols = (fromLevel) => {
      diag.querySelectorAll(".adg-dd").forEach((el) => {
        if (parseInt(el.dataset.level || "0") >= fromLevel) el.remove();
      });
    };

    // Append a new drilldown column (arrow + section) to the diagram
    const addDrilldownCol = (level, label, nodes) => {
      removeDrilldownCols(level);
      const arrow = document.createElement("div");
      arrow.className = "adg-arrow adg-dd"; arrow.dataset.level = String(level); arrow.textContent = "→";
      const section = document.createElement("div");
      section.className = "adg-section adg-dd"; section.dataset.level = String(level);
      const lbl = document.createElement("div"); lbl.className = "adg-label"; lbl.textContent = label;
      const nodesEl = document.createElement("div"); nodesEl.className = "adg-nodes";
      nodes.forEach((n) => nodesEl.appendChild(n));
      section.appendChild(lbl); section.appendChild(nodesEl);
      diag.appendChild(arrow); diag.appendChild(section);
      setTimeout(() => { diag.scrollLeft = diag.scrollWidth; }, 10);
    };

    // Render a condition item — clickable if onClickFn is provided.
    // For and/or/not, recursively renders sub-conditions in a group.
    // fromLine/toLine are optional line ranges for cursor-based highlighting.
    const renderCondItem = (cond, onClickFn, fromLine, toLine) => {
      // Handle string shorthand (bare template)
      if (typeof cond === "string") {
        cond = { condition: "template", value_template: cond };
      }
      // Auto-detect condition type: HA may omit explicit `condition:` key
      let c = cond.condition || "";
      if (!c && cond.value_template) c = "template";
      if (!c && cond.entity_id && cond.state !== undefined) c = "state";

      // AND/OR/NOT: render as a group with nested conditions
      if (c === "and" || c === "or" || c === "not") {
        const subConds = [].concat(cond.conditions || []);
        const group = document.createElement("div");
        group.className = "adg-cond-group";
        const label = document.createElement("div");
        label.className = "adg-cond-group-label";
        label.textContent = c.toUpperCase();
        group.appendChild(label);
        subConds.forEach((sc) => group.appendChild(renderCondItem(sc, onClickFn)));
        return group;
      }

      let condSub = "";
      let condDetail = "";

      if (c === "template") {
        // Normalize escaped quotes — HA may store value_template with literal \" sequences
        const vt = (cond.value_template || "").replace(/\\"/g, '"').replace(/\\'/g, "'");
        const statesMatch = vt.match(/states\(\s*['"]([^'"]+)['"]\s*\)\s*(==|!=|>|<|>=|<=)\s*['"]?([^"'\\}\s]+)/);
        const isStateMatch = vt.match(/is_state\(\s*['"]([^'"]+)['"],\s*['"]([^'"]+)['"]\)/);
        if (statesMatch) {
          const entity = statesMatch[1];
          condSub = entity.includes(".") ? entity.split(".")[1] : entity;
          condDetail = `${statesMatch[2]} ${statesMatch[3]}`;
        } else if (isStateMatch) {
          const entity = isStateMatch[1];
          condSub = entity.includes(".") ? entity.split(".")[1] : entity;
          condDetail = `== ${isStateMatch[2]}`;
        } else {
          condSub = vt.replace(/\{\{|\}\}/g, "").trim().slice(0, 40);
        }
      } else if (c === "state") {
        const entityId = (Array.isArray(cond.entity_id) ? cond.entity_id[0] : cond.entity_id) || "";
        condSub = entityId.includes(".") ? entityId.split(".")[1] : entityId;
        if (cond.state !== undefined) condDetail = `== ${Array.isArray(cond.state) ? cond.state.join("|") : cond.state}`;
      } else if (c === "numeric_state") {
        const entityId = (Array.isArray(cond.entity_id) ? cond.entity_id[0] : cond.entity_id) || "";
        condSub = entityId.includes(".") ? entityId.split(".")[1] : entityId;
        const parts = [];
        if (cond.above !== undefined) parts.push(`> ${cond.above}`);
        if (cond.below !== undefined) parts.push(`< ${cond.below}`);
        condDetail = parts.join(", ");
      } else if (c === "time") {
        const parts = [];
        if (cond.after) parts.push(`after ${cond.after}`);
        if (cond.before) parts.push(`before ${cond.before}`);
        if (cond.weekday) condDetail = [].concat(cond.weekday).join(", ");
        condSub = parts.join(", ") || "";
      } else if (c === "sun") {
        const parts = [];
        if (cond.after) parts.push(`after ${cond.after}`);
        if (cond.before) parts.push(`before ${cond.before}`);
        condSub = parts.join(", ") || "";
      } else if (c === "zone") {
        const entityId = (Array.isArray(cond.entity_id) ? cond.entity_id[0] : cond.entity_id) || "";
        condSub = entityId.includes(".") ? entityId.split(".")[1] : entityId;
        condDetail = cond.zone || "";
      } else if (c === "trigger") {
        condSub = [].concat(cond.id || []).join(", ");
      } else if (c === "device") {
        condSub = (cond.type || "").replace(/_/g, " ");
      } else {
        const entityId = (Array.isArray(cond.entity_id) ? cond.entity_id[0] : cond.entity_id) || "";
        condSub = entityId.includes(".") ? entityId.split(".")[1] : (entityId || (cond.value_template || "").slice(0, 25));
      }

      const el = document.createElement("div"); el.className = "adg-cond-item" + (onClickFn ? " adg-cond-clickable" : "");
      if (fromLine != null) { el.dataset.from = String(fromLine); el.dataset.to = String(toLine ?? fromLine); }
      el.innerHTML = `<span class="adg-icon">${COND_ICONS[c] || "❓"}</span><span class="adg-title">${this._escH(c || "condition")}</span>${condSub ? `<span class="adg-sub">${this._escH(condSub)}</span>` : ""}${condDetail ? `<span class="adg-cond-detail">${this._escH(condDetail)}</span>` : ""}`;
      if (onClickFn) el.addEventListener("click", (e) => {
        diag.querySelectorAll(".adg-cond-selected").forEach((n) => n.classList.remove("adg-cond-selected"));
        el.classList.add("adg-cond-selected");
        onClickFn();
        e.stopPropagation();
      });
      return el;
    };

    const mkHeader = (text) => Object.assign(document.createElement("div"), { className: "adg-opt-header", textContent: text });

    // Render an option tile shown in a choose-column.
    // colLevel: the column level this tile lives in (default 1). Seq actions go into colLevel+1.
    const renderOptionTile = (optItem, chooseNodeEl, optBlock, colLevel = 1) => {
      const seq = optItem.sequence || []; const conds = optItem._conditions || [];
      const wrapper = document.createElement("div"); wrapper.className = "adg-node-wrapper";
      const nodeEl = document.createElement("div");
      const optCls = optItem._isDefault ? "adg-option-default" : "adg-option";
      nodeEl.className = `adg-node adg-action ${optCls} adg-expandable`;
      if (optBlock?.from_line != null) { nodeEl.dataset.from = String(optBlock.from_line); nodeEl.dataset.to = String(optBlock.to_line ?? optBlock.from_line); }
      const condStr = conds.length ? ` · ${conds.length} cond` : "";
      const seqStr = seq.length ? `${seq.length} action${seq.length !== 1 ? "s" : ""}${condStr}` : (conds.length ? `${conds.length} cond` : "");
      nodeEl.innerHTML = `<span class="adg-icon">${optItem._isDefault ? "↩" : "📋"}</span><span class="adg-title">${this._escH(optItem._label)}</span>${seqStr ? `<span class="adg-sub">${seqStr}</span>` : ""}`;
      nodeEl.addEventListener("click", (e) => {
        const col1NodesEl = wrapper.parentElement;
        col1NodesEl?.querySelectorAll(".adg-node").forEach((n) => n.classList.remove("adg-selected"));
        const wasSelected = nodeEl.classList.contains("adg-selected"); // already deselected above
        if (!wasSelected) {
          nodeEl.classList.add("adg-selected");
          // Jump editor to this option's line
          if (!this._suppressEditorJump && optBlock?.from_line != null) this._jumpEditorToBlock(optBlock.from_line, optBlock.to_line);
          // Build actions column — conditions are clickable (jump to specific condition line)
          const nodes = [];
          if (conds.length) {
           nodes.push(mkHeader("when:"));
           conds.forEach((c, ci) => {
             const condBlock = optBlock?.conditions?.[ci];
             const condClickFn = condBlock?.from_line != null
               ? () => { if (!this._suppressEditorJump) this._jumpEditorToBlock(condBlock.from_line, condBlock.to_line); }
               : (optBlock?.from_line != null ? () => { if (!this._suppressEditorJump) this._jumpEditorToBlock(optBlock.from_line, optBlock.to_line); } : null);
             nodes.push(renderCondItem(c, condClickFn, condBlock?.from_line, condBlock?.to_line));
           });
          }
          if (seq.length) {
            if (conds.length) nodes.push(mkHeader("then:"));
            seq.forEach((a, i) => {
              const lb = optBlock?.actions?.[i];
              nodes.push(renderActionNode(a, "adg-action", lb?.from_line ?? 0, lb?.to_line ?? 0, 0, null, colLevel + 1));
            });
          }
          addDrilldownCol(colLevel + 1, optItem._label, nodes);
          if (chooseNodeEl) chooseNodeEl.classList.add("adg-has-expanded-child");
        } else {
          removeDrilldownCols(colLevel + 1);
          if (chooseNodeEl) chooseNodeEl.classList.remove("adg-has-expanded-child");
        }
        e.stopPropagation();
      });
      wrapper.appendChild(nodeEl);
      return wrapper;
    };

    // Render a single action node. colLevel is the Miller-column level this node lives in.
    const renderActionNode = (item, cls, fromLine, toLine, depth, parentNodeEl, colLevel = 0) => {
      const { icon, title, sub } = this._blockMetaFromJson("actions", item);
      const safeTitle = this._escH(title);
      const safeSub = this._escH(sub);
      const indent = depth ? `margin-left:${depth * 14}px;` : "";
      const children = this._getActionChildren(item);
      // choose/if AND repeat/parallel use column drill-down
      const isChooseIf = item.choose !== undefined || item.if !== undefined;
      const usesColumns = isChooseIf || item.repeat !== undefined || item.parallel !== undefined;
      const isExpandable = children.length > 0;

      const wrapper = document.createElement("div"); wrapper.className = "adg-node-wrapper";
      const nodeEl = document.createElement("div");
      const dirty = isBlockDirty(fromLine, toLine) ? " adg-dirty" : "";
      nodeEl.className = `adg-node ${cls}${depth ? " adg-sub-node" : ""}${isExpandable ? " adg-expandable" : ""}${dirty}`;
      nodeEl.dataset.from = String(fromLine); nodeEl.dataset.to = String(toLine);
      nodeEl.setAttribute("style", indent);
      nodeEl.setAttribute("title", `${title}${sub ? ": " + sub : ""}${isExpandable ? " — click to expand" : ""}${dirty ? " (modified)" : ""}`);
      nodeEl.innerHTML = `<span class="adg-icon">${icon}</span><span class="adg-title">${safeTitle}</span>${sub ? `<span class="adg-sub">${safeSub}</span>` : ""}${isExpandable ? `<span class="adg-expand-btn">▶</span>` : ""}`;

      nodeEl.addEventListener("click", (e) => {
        if (isExpandable && usesColumns) {
          const wasSelected = nodeEl.classList.contains("adg-selected");
          // Deselect items in the same column only
          const mySection = nodeEl.closest(".adg-section");
          (mySection || diag).querySelectorAll(".adg-selected").forEach((n) => n.classList.remove("adg-selected", "adg-has-expanded-child"));
          removeDrilldownCols(colLevel + 1);
          if (!wasSelected) {
            nodeEl.classList.add("adg-selected");
            if (!this._suppressEditorJump && fromLine != null) this._jumpEditorToBlock(fromLine, toLine, false);
            if (isChooseIf) {
              const chooseBlocks = this._parseChooseBlocks(fromLine, toLine);
              addDrilldownCol(colLevel + 1, title, children.map((opt, i) => renderOptionTile(opt, nodeEl, chooseBlocks[i], colLevel + 1)));
            } else if (item.repeat !== undefined) {
              // repeat: show loop-type header + optional conditions + sequence
              const nodes = [];
              const whileConds = [].concat(item.repeat.while || []);
              const untilConds = [].concat(item.repeat.until || []);
              if (item.repeat.count !== undefined) {
                nodes.push(mkHeader(`count: ${item.repeat.count}`));
              } else if (item.repeat.for_each !== undefined) {
                const n = Array.isArray(item.repeat.for_each) ? item.repeat.for_each.length : "?";
                nodes.push(mkHeader(`for_each: ${n} items`));
              } else if (whileConds.length) {
                nodes.push(mkHeader("while:"));
                const condBlocks = this._parseRepeatCondBlocks(fromLine, toLine, "while");
                whileConds.forEach((c, ci) => {
                  const cb = condBlocks[ci];
                  const condClickFn = cb?.from_line != null
                    ? () => { if (!this._suppressEditorJump) this._jumpEditorToBlock(cb.from_line, cb.to_line); }
                    : (fromLine != null ? () => { if (!this._suppressEditorJump) this._jumpEditorToBlock(fromLine, toLine); } : null);
                  nodes.push(renderCondItem(c, condClickFn, cb?.from_line, cb?.to_line));
                });
              } else if (untilConds.length) {
                nodes.push(mkHeader("until:"));
                const condBlocks = this._parseRepeatCondBlocks(fromLine, toLine, "until");
                untilConds.forEach((c, ci) => {
                  const cb = condBlocks[ci];
                  const condClickFn = cb?.from_line != null
                    ? () => { if (!this._suppressEditorJump) this._jumpEditorToBlock(cb.from_line, cb.to_line); }
                    : (fromLine != null ? () => { if (!this._suppressEditorJump) this._jumpEditorToBlock(fromLine, toLine); } : null);
                  nodes.push(renderCondItem(c, condClickFn, cb?.from_line, cb?.to_line));
                });
              }
              if (children.length) nodes.push(mkHeader("sequence:"));
              // Parse per-action line ranges inside the repeat's sequence
              const seqBlocks = this._parseRepeatBlocks(fromLine, toLine);
              children.forEach((child, i) => {
                const lb = seqBlocks[i];
                nodes.push(renderActionNode(child, "adg-action", lb?.from_line ?? fromLine, lb?.to_line ?? toLine, 0, null, colLevel + 1));
              });
              addDrilldownCol(colLevel + 1, title, nodes);
            } else {
              // parallel: each element is a {sequence:[]} wrapper — flatten all sequences
              const nodes = [];
              [].concat(item.parallel || []).forEach((branch, bi) => {
                const seq = [].concat(branch.sequence || branch || []);
                if (item.parallel.length > 1) nodes.push(mkHeader(branch.alias || `branch ${bi + 1}`));
                seq.forEach((child) => nodes.push(renderActionNode(child, "adg-action", fromLine, toLine, 0, null, colLevel + 1)));
              });
              addDrilldownCol(colLevel + 1, title, nodes);
            }
          }
          e.stopPropagation(); return;
        }
        if (isExpandable) {
          // fallback inline toggle (depth > 0 sub-nodes)
          const childrenEl = wrapper.querySelector(":scope > .adg-children");
          if (childrenEl) {
            const open = !childrenEl.hidden; childrenEl.hidden = open;
            const btn = nodeEl.querySelector(".adg-expand-btn"); if (btn) btn.textContent = open ? "▶" : "▼";
            nodeEl.classList.toggle("adg-expanded", !open);
          }
          e.stopPropagation(); return;
        }
        // Leaf node: highlight + jump editor
        diag.querySelectorAll(".adg-node.adg-leaf-selected").forEach((n) => n.classList.remove("adg-leaf-selected"));
        nodeEl.classList.add("adg-leaf-selected");
        if (fromLine != null) this._jumpEditorToBlock(fromLine, toLine);
        e.stopPropagation();
      });

      wrapper.appendChild(nodeEl);
      if (isExpandable && !usesColumns) {
        const childrenEl = document.createElement("div");
        childrenEl.className = "adg-children"; childrenEl.hidden = true;
        children.forEach((child) => childrenEl.appendChild(renderActionNode(child, cls, 0, 0, depth + 1, nodeEl, colLevel)));
        wrapper.appendChild(childrenEl);
      }
      return wrapper;
    };

    // Check if a YAML block (from_line..to_line) has been modified vs saved YAML
    const isBlockDirty = (fromLine, toLine) => {
      if (!this._savedYaml || !this._dirty) return false;
      const savedLines = this._savedYaml.split("\n");
      const currentLines = yamlText.split("\n");
      const f = Math.max(0, fromLine);
      const t = Math.min(toLine, Math.max(savedLines.length, currentLines.length) - 1);
      for (let i = f; i <= t; i++) {
        if ((currentLines[i] || "") !== (savedLines[i] || "")) return true;
      }
      return false;
    };

    const renderSection = (items, sectionKey, label, cls, lineBlocks) => {
      if (!items.length) return null;
      const section = document.createElement("div");
      section.className = "adg-section";
      section.innerHTML = `<div class="adg-label">${label}</div>`;
      const nodesEl = document.createElement("div");
      nodesEl.className = "adg-nodes";
      items.forEach((item, idx) => {
        const lineBlock = lineBlocks ? lineBlocks[idx] : null;
        const fromLine = lineBlock ? lineBlock.from_line : 0;
        const toLine = lineBlock ? lineBlock.to_line : 0;
        if (sectionKey === "actions") {
          nodesEl.appendChild(renderActionNode(item, cls, fromLine, toLine, 0));
        } else if (sectionKey === "conditions") {
          // Use rich condition renderer for per-condition click navigation
          const clickFn = (fromLine > 0 || toLine > 0) ? () => this._jumpEditorToBlock(fromLine, toLine) : null;
          const condEl = renderCondItem(item, clickFn, fromLine, toLine);
          if (isBlockDirty(fromLine, toLine)) condEl.classList.add("adg-dirty");
          nodesEl.appendChild(condEl);
        } else {
          const { icon, title, sub } = this._blockMetaFromJson(sectionKey, item);
          const nodeEl = document.createElement("div");
          const dirty = isBlockDirty(fromLine, toLine) ? " adg-dirty" : "";
          nodeEl.className = `adg-node ${cls}${dirty}`;
          nodeEl.dataset.from = String(fromLine);
          nodeEl.dataset.to = String(toLine);
          nodeEl.setAttribute("title", `${title}${sub ? ": " + sub : ""}${dirty ? " (modified)" : ""}`);
          nodeEl.innerHTML = `<span class="adg-icon">${icon}</span><span class="adg-title">${this._escH(title)}</span>${sub ? `<span class="adg-sub">${this._escH(sub)}</span>` : ""}`;
          nodeEl.addEventListener("click", () => { if (fromLine != null) this._jumpEditorToBlock(fromLine, toLine); });
          nodesEl.appendChild(nodeEl);
        }
      });
      section.appendChild(nodesEl);
      return section;
    };

    // Script: optionally show PARAMETERS section from cfg.fields
    let fieldsSection = null;
    if (isScript && cfg.fields && typeof cfg.fields === "object") {
      const fieldEntries = Object.entries(cfg.fields);
      if (fieldEntries.length) {
        fieldsSection = document.createElement("div");
        fieldsSection.className = "adg-section";
        fieldsSection.innerHTML = `<div class="adg-label">PARAMETERS</div>`;
        const nodesEl = document.createElement("div");
        nodesEl.className = "adg-nodes";
        fieldEntries.forEach(([name, meta]) => {
          const desc = (meta && typeof meta === "object") ? (meta.description || meta.name || "") : String(meta || "");
          const nodeEl = document.createElement("div");
          nodeEl.className = "adg-node adg-trigger";
          nodeEl.dataset.from = "0";
          nodeEl.dataset.to = "0";
          nodeEl.innerHTML = `<span class="adg-icon">📥</span><span class="adg-title">${this._escH(name)}</span>${desc ? `<span class="adg-sub">${this._escH(String(desc).slice(0, 60))}</span>` : ""}`;
          nodesEl.appendChild(nodeEl);
        });
        fieldsSection.appendChild(nodesEl);
      }
    }

    const actionLabel = isScript ? "DO" : "THEN";
    const triggerSection  = renderSection(triggers, "triggers", "WHEN", "adg-trigger", this._diagLineBlocks.triggers);
    const condSection     = renderSection(conditions, "conditions", "IF", "adg-condition", this._diagLineBlocks.conditions);
    const actionSection   = renderSection(actions, "actions", actionLabel, "adg-action", this._diagLineBlocks.actions);

    const arrow = () => { const d = document.createElement("div"); d.className = "adg-arrow"; d.textContent = "→"; return d; };

    diag.innerHTML = "";
    const parts = [fieldsSection, triggerSection, condSection, actionSection].filter(Boolean);
    parts.forEach((part, i) => { diag.appendChild(part); if (i < parts.length - 1) diag.appendChild(arrow()); });
  }

  // Returns child actions for compound action types (used for expand/collapse in diagram)
  _getActionChildren(item) {
    if (item._isOption || item._isDefault) {
      return [].concat(item.sequence || []);
    }
    if (item.if !== undefined) {
      const thenSeq = [].concat(item.then || []);
      const elseSeq = [].concat(item.else || []);
      const ifConds = [].concat(item.if || []);
      const opts = [];
      if (thenSeq.length) opts.push({ _isOption: true, _label: "then", sequence: thenSeq, _condCount: ifConds.length, _conditions: ifConds });
      if (elseSeq.length) opts.push({ _isOption: true, _label: "else", sequence: elseSeq, _condCount: 0, _conditions: [] });
      return opts;
    }
    if (item.choose !== undefined) {
      const opts = (item.choose || []).map((opt, i) => {
        const conds = [].concat(opt.conditions || opt.condition || []);
        return {
          _isOption: true,
          _label: `option ${i + 1}`,
          _condCount: conds.length,
          _conditions: conds,
          sequence: [].concat(opt.sequence || opt.then || []),
        };
      });
      const def = [].concat(item.default || []);
      if (def.length) opts.push({ _isDefault: true, _label: "default", sequence: def, _condCount: 0, _conditions: [] });
      return opts;
    }
    if (item.repeat !== undefined) {
      return [].concat(item.repeat?.sequence || []);
    }
    if (item.parallel !== undefined) {
      return [].concat(item.parallel || []);
    }
    return [];
  }

  // Parse the YAML to find per-option and per-sub-action line numbers within a choose/if block.
  // Returns an array of { from_line, to_line, actions: [{from_line, to_line}], conditions: [{from_line, to_line}] } — one entry per option.
  // Uses content-based detection so inconsistent indentation (from manual edits) still works.
  _parseChooseBlocks(parentFromLine, parentToLine) {
    if (!this._editor || parentFromLine == null) return [];
    const lines = this._editor.state.doc.toString().split("\n");

    const chooseLine = lines[parentFromLine] || "";
    const chooseIndent = (chooseLine.match(/^(\s*)-/) || ["", ""])[1].length;
    const endLine = Math.min((parentToLine ?? parentFromLine) + 200, lines.length - 1);

    // An option boundary: a list item starting with "- conditions:" (plural, HA choose format).
    // Do NOT match "- condition:" (singular) which is a sub-condition type specifier.
    const isOptBoundary = (line) => /^\s*-\s*conditions\s*:/.test(line);
    // A sequence marker: "sequence:" key anywhere inside the choose block
    const isSeqKey = (line) => /^\s*sequence\s*:/.test(line);

    const opts = [];
    let curOpt = null;
    let inSeq = false;
    let inConds = false;
    let curAct = null;
    let curCond = null;
    let actIndent = -1;
    let condIndent = -1;

    const pushAct = (endAt) => {
      if (curAct && curOpt) { curAct.to_line = endAt; curOpt.actions.push(curAct); curAct = null; }
    };
    const pushCond = (endAt) => {
      if (curCond && curOpt) { curCond.to_line = endAt; curOpt.conditions.push(curCond); curCond = null; }
    };
    const pushOpt = (endAt) => {
      pushAct(endAt);
      pushCond(endAt);
      if (curOpt) { curOpt.to_line = endAt; opts.push(curOpt); curOpt = null; }
    };

    for (let i = parentFromLine + 1; i <= endLine; i++) {
      const line = lines[i];
      if (!line.trim()) continue;
      // Skip inline flow values like {} or [] that HA writes at column 0 inside metadata/data keys
      if (/^\s*[\{\[]/.test(line)) continue;
      const lineIndent = (line.match(/^(\s*)/) || ["", ""])[1].length;
      if (lineIndent <= chooseIndent) break;

      if (isOptBoundary(line)) {
        // Start of a new choose option
        pushOpt(i - 1);
        curOpt = { from_line: i, to_line: i, actions: [], conditions: [], _optIndent: lineIndent };
        inSeq = false;
        inConds = true;
        actIndent = -1;
        condIndent = -1;
      } else if (curOpt && isSeqKey(line)) {
        // Sequence section of the current option — end conditions section
        pushCond(i - 1);
        inConds = false;
        inSeq = true;
        actIndent = -1; // will be auto-detected from first action below
      } else if (curOpt && inConds && /^\s*-\s/.test(line)) {
        // Condition list item inside conditions
        if (condIndent < 0) condIndent = lineIndent;
        if (lineIndent === condIndent) {
          pushCond(i - 1);
          curCond = { from_line: i, to_line: i };
        }
      } else if (curOpt && inSeq && /^\s*-/.test(line)) {
        // Action list item inside sequence
        if (actIndent < 0) actIndent = lineIndent; // first item sets the level
        if (lineIndent === actIndent) {
          pushAct(i - 1);
          curAct = { from_line: i, to_line: i };
        }
      } else if (curOpt && inSeq && /^\s*-/.test(line) === false && lineIndent <= (curOpt._optIndent || 0) + 2) {
        // A key at option level or shallower resets inSeq (e.g. another key after sequence)
        // This handles edge cases where "sequence:" appears before "conditions:"
      }
    }
    pushOpt(parentToLine ?? endLine);
    return opts;
  }

  // Parse per-action line numbers within a repeat's sequence block.
  // Returns [{from_line, to_line}, ...] for each action item.
  _parseRepeatBlocks(parentFromLine, parentToLine) {
    if (!this._editor || parentFromLine == null) return [];
    const lines = this._editor.state.doc.toString().split("\n");
    const endLine = Math.min((parentToLine ?? parentFromLine) + 200, lines.length - 1);
    const actions = [];
    let inSeq = false;
    let seqIndent = -1;
    let actIndent = -1;
    let curAct = null;
    for (let i = parentFromLine + 1; i <= endLine; i++) {
      const line = lines[i];
      if (!line.trim()) continue;
      if (/^\s*[\{\[]/.test(line)) continue;
      const lineIndent = (line.match(/^(\s*)/) || ["", ""])[1].length;
      if (!inSeq) {
        if (/^\s*sequence\s*:/.test(line)) { inSeq = true; seqIndent = lineIndent; }
        continue;
      }
      if (lineIndent <= seqIndent) break; // past sequence block
      if (actIndent < 0) {
        if (/^\s*-\s/.test(line)) { actIndent = lineIndent; curAct = { from_line: i, to_line: i }; }
      } else if (lineIndent === actIndent && /^\s*-\s/.test(line)) {
        if (curAct) { curAct.to_line = i - 1; actions.push(curAct); }
        curAct = { from_line: i, to_line: i };
      } else if (lineIndent < actIndent) {
        break;
      }
    }
    if (curAct) { curAct.to_line = parentToLine ?? endLine; actions.push(curAct); }
    return actions;
  }

  // Parse per-condition line numbers within a repeat's while: or until: block.
  // sectionKey is "while" or "until". Returns [{from_line, to_line}, ...] for each condition.
  _parseRepeatCondBlocks(parentFromLine, parentToLine, sectionKey) {
    if (!this._editor || parentFromLine == null) return [];
    const lines = this._editor.state.doc.toString().split("\n");
    const endLine = Math.min((parentToLine ?? parentFromLine) + 200, lines.length - 1);
    const conds = [];
    let inSection = false;
    let sectionIndent = -1;
    let itemIndent = -1;
    let curItem = null;
    const sectionRe = new RegExp(`^\\s*${sectionKey}\\s*:`);
    for (let i = parentFromLine + 1; i <= endLine; i++) {
      const line = lines[i];
      if (!line.trim()) continue;
      const lineIndent = (line.match(/^(\s*)/) || ["", ""])[1].length;
      if (!inSection) {
        if (sectionRe.test(line)) { inSection = true; sectionIndent = lineIndent; }
        continue;
      }
      // Past section — hit sequence: or another same-level key
      if (lineIndent <= sectionIndent && !/^\s*$/.test(line)) {
        if (curItem) { curItem.to_line = i - 1; conds.push(curItem); }
        break;
      }
      if (/^\s*-\s/.test(line)) {
        if (itemIndent < 0) {
          itemIndent = lineIndent;
          curItem = { from_line: i, to_line: i };
        } else if (lineIndent === itemIndent) {
          if (curItem) { curItem.to_line = i - 1; conds.push(curItem); }
          curItem = { from_line: i, to_line: i };
        }
      }
    }
    if (curItem) { curItem.to_line = parentToLine ?? endLine; conds.push(curItem); }
    return conds;
  }

  _flattenActionsForDiagram(actions, output, depth) {
    for (const a of actions) {
      if (a.choose) {
        output.push({ ...a, _depth: depth });
        for (const option of (a.choose || [])) {
          const seq = option.sequence || option.then || [];
          this._flattenActionsForDiagram(seq, output, depth + 1);
        }
      } else if (a.parallel) {
        output.push({ ...a, _depth: depth });
        this._flattenActionsForDiagram(a.parallel, output, depth + 1);
      } else if (a.repeat) {
        output.push({ ...a, _depth: depth });
        const seq = a.repeat.sequence || [];
        this._flattenActionsForDiagram(seq, output, depth + 1);
      } else if (a.sequence) {
        this._flattenActionsForDiagram(a.sequence, output, depth);
      } else {
        output.push({ ...a, _depth: depth });
      }
    }
  }

  _blockMetaFromJson(section, item) {
    if (section === "triggers") {
      const p = item.platform || item.trigger || item.triggers?.platform || "";
      const ICONS = { sun: "🌅", state: "📡", time: "⏰", homeassistant: "🏠", webhook: "🌐", event: "⚡", template: "📋", zone: "📍", numeric_state: "🔢", device: "📱", calendar: "📅", tag: "🏷", mqtt: "📡", geo_location: "🗺", persistent_notification: "🔔", conversation: "💬" };
      let sub = "";
      if (p === "device") {
        const type = (item.type || "").replace(/_/g, " ");
        const subtype = (item.subtype || "").replace(/_/g, " ");
        sub = subtype ? `${subtype}: ${type}` : type || "device";
      } else if (p === "state" || p === "numeric_state") {
        const entities = [].concat(item.entity_id || []);
        const names = entities.map((e) => (e.includes(".") ? e.split(".")[1] : e));
        const entitySub = names.length > 1 ? `${names[0]} +${names.length - 1}` : (names[0] || "");
        const toStr = item.to !== undefined ? ` → ${item.to}` : (item.above !== undefined || item.below !== undefined ? ` ${item.above ?? ""}…${item.below ?? ""}` : "");
        sub = entitySub + toStr;
      } else {
        const entityId = (Array.isArray(item.entity_id) ? item.entity_id[0] : item.entity_id) || "";
        const shortEntity = entityId.includes(".") ? entityId.split(".")[1] : entityId;
        sub = (item.event || shortEntity || item.at || item.event_type || "").toString().split(",")[0].trim();
      }
      return { icon: ICONS[p] || "⚡", title: p || "trigger", sub };
    }
    if (section === "conditions") {
      let c = item.condition || "";
      if (!c && item.value_template) c = "template";
      if (!c && item.entity_id && item.state !== undefined) c = "state";
      if (!c && item.entity_id && (item.above !== undefined || item.below !== undefined)) c = "numeric_state";
      const ICONS = { state: "✅", template: "📋", time: "⏰", numeric_state: "🔢", zone: "📍", and: "🔗", or: "🔀", not: "❌", device: "📱", trigger: "⚡", sun: "🌅" };
      let sub = "";
      if (c === "and" || c === "or" || c === "not") {
        const nested = [].concat(item.conditions || []);
        sub = `${nested.length} condition${nested.length !== 1 ? "s" : ""}`;
      } else if (c === "template") {
        const vt = (item.value_template || "").replace(/\\"/g, '"').replace(/\\'/g, "'");
        const statesMatch = vt.match(/states\(\s*['"]([^'"]+)['"]\s*\)\s*(==|!=|>|<|>=|<=)\s*['"]?([^"'\\}\s]+)/);
        const isStateMatch = vt.match(/is_state\(\s*['"]([^'"]+)['"],\s*['"]([^'"]+)['"]\)/);
        if (statesMatch) {
          const entity = statesMatch[1];
          sub = (entity.includes(".") ? entity.split(".")[1] : entity) + ` ${statesMatch[2]} ${statesMatch[3]}`;
        } else if (isStateMatch) {
          const entity = isStateMatch[1];
          sub = (entity.includes(".") ? entity.split(".")[1] : entity) + ` == ${isStateMatch[2]}`;
        } else {
          sub = vt.replace(/\{\{|\}\}/g, "").trim().slice(0, 40);
        }
      } else if (c === "numeric_state") {
        const entityId = (Array.isArray(item.entity_id) ? item.entity_id[0] : item.entity_id) || "";
        sub = entityId.includes(".") ? entityId.split(".")[1] : entityId;
        const parts = [];
        if (item.above !== undefined) parts.push(`> ${item.above}`);
        if (item.below !== undefined) parts.push(`< ${item.below}`);
        if (parts.length) sub += ` ${parts.join(", ")}`;
      } else if (c === "time") {
        const parts = [];
        if (item.after) parts.push(`after ${item.after}`);
        if (item.before) parts.push(`before ${item.before}`);
        sub = parts.join(", ") || "";
        if (item.weekday) sub = (sub ? sub + " " : "") + [].concat(item.weekday).join(",");
      } else if (c === "sun") {
        const parts = [];
        if (item.after) parts.push(`after ${item.after}`);
        if (item.before) parts.push(`before ${item.before}`);
        sub = parts.join(", ") || "";
      } else if (c === "trigger") {
        sub = [].concat(item.id || []).join(", ");
      } else if (c === "device") {
        sub = (item.type || "").replace(/_/g, " ");
      } else {
        const entityId = (Array.isArray(item.entity_id) ? item.entity_id[0] : item.entity_id) || "";
        sub = entityId.includes(".") ? entityId.split(".")[1] : entityId;
        if (c === "state" && item.state !== undefined) sub += ` == ${Array.isArray(item.state) ? item.state.join("|") : item.state}`;
      }
      return { icon: ICONS[c] || "❓", title: c || "condition", sub };
    }
    // actions
    if (item.if !== undefined) {
      const condCount = [].concat(item.if || []).length;
      const actCount = [].concat(item.then || []).length + [].concat(item.else || []).length;
      return { icon: "🔀", title: "if/then", sub: `${condCount} condition${condCount !== 1 ? "s" : ""} · ${actCount} actions ▶` };
    }
    if (item.choose !== undefined) {
      const totalActions = (item.choose || []).reduce((n, opt) => n + ([].concat(opt.sequence || opt.then || [])).length, 0)
        + [].concat(item.default || []).length;
      return { icon: "🔀", title: "choose", sub: `${(item.choose || []).length} options · ${totalActions} actions ▶` };
    }
    if (item.parallel !== undefined) return { icon: "⚡", title: "parallel", sub: `${(item.parallel || []).length} actions` };
    if (item.repeat !== undefined) {
      const seqCount = [].concat(item.repeat?.sequence || []).length;
      const whileCount = [].concat(item.repeat?.while || []).length;
      const untilCount = [].concat(item.repeat?.until || []).length;
      const condStr = whileCount ? `while ${whileCount} cond · ` : (untilCount ? `until ${untilCount} cond · ` : "");
      return { icon: "🔁", title: "repeat", sub: item.repeat?.count ? `${item.repeat.count}× · ${seqCount} actions ▶` : `${condStr}${seqCount} actions ▶` };
    }
    if (item.wait_template !== undefined || item.wait_for_trigger !== undefined) return { icon: "⏳", title: "wait", sub: "" };
    if (item.delay !== undefined) {
      let delayStr;
      if (typeof item.delay === "object" && item.delay !== null) {
        const p = [];
        if (item.delay.days) p.push(`${item.delay.days}d`);
        if (item.delay.hours) p.push(`${item.delay.hours}h`);
        if (item.delay.minutes) p.push(`${item.delay.minutes}m`);
        if (item.delay.seconds) p.push(`${item.delay.seconds}s`);
        if (item.delay.milliseconds) p.push(`${item.delay.milliseconds}ms`);
        delayStr = p.join(" ") || "0s";
      } else {
        delayStr = String(item.delay);
      }
      return { icon: "⏱", title: "delay", sub: delayStr };
    }
    if (item.stop !== undefined) return { icon: "🛑", title: "stop", sub: String(item.stop || "") };
    if (item.event !== undefined) return { icon: "📡", title: "fire event", sub: String(item.event) };
    if (item.variables !== undefined) return { icon: "📦", title: "variables", sub: "" };
    if (item.device_id !== undefined) {
      const type = (item.type || "device action").replace(/_/g, " ");
      const subtype = (item.subtype || "").replace(/_/g, " ");
      return { icon: "📱", title: type, sub: subtype };
    }
    const svc = item.service || item.action || "";
    const SVC_ICONS = { "light.": "💡", "switch.": "🔌", "media_player.": "🎵", "notify.": "📢", "script.": "📜", "climate.": "🌡️", "homeassistant.": "🏠", "automation.": "⚙️", "input_boolean.": "🔘", "input_number.": "🔢", "input_select.": "📋", "cover.": "🪟", "lock.": "🔒", "alarm_control_panel.": "🚨", "vacuum.": "🤖", "fan.": "💨", "button.": "🔘", "scene.": "🎨", "frontend.": "🖥️" };
    const iconKey = Object.keys(SVC_ICONS).find((k) => svc.startsWith(k));
    const target = item.target?.entity_id || item.data?.entity_id || "";
    const entityList = Array.isArray(target) ? target[0] : target;
    const rawEntity = (entityList || (Array.isArray(item.entity_id) ? item.entity_id[0] : item.entity_id) || "").toString().split(",")[0].trim();
    const sub = rawEntity.includes(".") ? rawEntity.split(".")[1] : rawEntity;
    const shortSvc = svc.includes(".") ? svc.split(".").slice(1).join(".") : svc;
    return { icon: iconKey ? SVC_ICONS[iconKey] : "▶️", title: shortSvc || svc || "action", sub };
  }

  _escH(s) {
    return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  // ── Diagram from YAML fallback (when JSON not cached) ─────────────────────

  _renderDiagramFromYaml(diag, yamlText) {
    const isScript = this._editorMode === "script";
    const blocks = this._parseAutomationBlocks(yamlText);
    const total = blocks.triggers.length + blocks.conditions.length + blocks.actions.length;
    if (!total) { diag.hidden = true; return; }
    diag.hidden = false;

    const renderSection = (sectionKey, items, label, cls) => {
      if (!items.length) return "";
      const nodes = items.map((item) => {
        const { icon, title, sub } = this._blockMeta(sectionKey, item.fields);
        const safeTitle = this._escH(title);
        const safeSub = this._escH(sub);
        return `<div class="adg-node ${cls}"
            data-from="${item.from_line}" data-to="${item.to_line}"
            title="${safeTitle}${sub ? ": " + safeSub : ""}">
          <span class="adg-icon">${icon}</span>
          <span class="adg-title">${safeTitle}</span>
          ${sub ? `<span class="adg-sub">${safeSub}</span>` : ""}
        </div>`;
      }).join("");
      return `<div class="adg-section"><div class="adg-label">${label}</div><div class="adg-nodes">${nodes}</div></div>`;
    };

    const actionLabel = isScript ? "DO" : "THEN";
    const parts = [];
    if (!isScript) parts.push(renderSection("triggers", blocks.triggers, "WHEN", "adg-trigger"));
    if (!isScript && blocks.conditions.length) parts.push(renderSection("conditions", blocks.conditions, "IF", "adg-condition"));
    parts.push(renderSection("actions", blocks.actions, actionLabel, "adg-action"));

    diag.innerHTML = parts.filter(Boolean).join('<div class="adg-arrow">→</div>');
    diag.querySelectorAll(".adg-node").forEach((node) => {
      node.addEventListener("click", () => {
        const from = parseInt(node.dataset.from, 10);
        const to = parseInt(node.dataset.to, 10);
        this._jumpEditorToBlock(from, to);
      });
    });
  }

  _jumpEditorToBlock(fromLine, toLine, cursorOnly = false) {
    if (!this._editor) return;
    const doc = this._editor.state.doc;
    const safeFrom = Math.max(1, fromLine + 1);
    const safeTo = cursorOnly ? safeFrom : Math.min(doc.lines, toLine + 1);
    const from = doc.line(safeFrom).from;
    const to = doc.line(safeTo).to;
    this._editor.dispatch({ selection: { anchor: from, head: to }, scrollIntoView: true });
    this._editor.focus();
  }

  _updateDiagramHighlight(cursorLine, depth = 0) {
    const diag = this.shadowRoot.getElementById("automation-diagram");
    if (!diag || diag.hidden) return;

    // Find the narrowest (most specific) node containing the cursor line
    let bestNode = null;
    let bestRange = Infinity;
    diag.querySelectorAll(".adg-node").forEach((node) => {
      const from = parseInt(node.dataset.from, 10);
      const to = parseInt(node.dataset.to, 10);
      if (isNaN(from) || isNaN(to) || (from === 0 && to === 0)) {
        node.classList.remove("adg-active"); return;
      }
      const active = cursorLine >= from && cursorLine <= to;
      node.classList.toggle("adg-active", active);
      if (active && (to - from) < bestRange) { bestRange = to - from; bestNode = node; }
    });

    // Also highlight condition items that have line ranges
    diag.querySelectorAll(".adg-cond-item").forEach((item) => {
      const from = parseInt(item.dataset.from, 10);
      const to = parseInt(item.dataset.to, 10);
      if (isNaN(from) || isNaN(to)) return;
      const active = cursorLine >= from && cursorLine <= to;
      item.classList.toggle("adg-cond-selected", active);
    });

    // Auto-collapse: deselect expanded nodes whose range no longer contains cursor
    if (depth === 0) {
      let collapseFromLevel = Infinity;
      diag.querySelectorAll(".adg-node.adg-selected.adg-expandable").forEach((node) => {
        const from = parseInt(node.dataset.from, 10);
        const to = parseInt(node.dataset.to, 10);
        if (!isNaN(from) && !isNaN(to) && (cursorLine < from || cursorLine > to)) {
          node.classList.remove("adg-selected", "adg-has-expanded-child");
          const sec = node.closest(".adg-section.adg-dd");
          const nodeLevel = sec ? parseInt(sec.dataset.level || "0") : 0;
          collapseFromLevel = Math.min(collapseFromLevel, nodeLevel + 1);
        }
      });
      if (collapseFromLevel < Infinity) {
        diag.querySelectorAll(".adg-dd").forEach((el) => {
          if (parseInt(el.dataset.level || "0") >= collapseFromLevel) el.remove();
        });
      }
    }

    // Auto-expand: click the best unselected expandable node (max 3 levels deep)
    if (depth < 3 && bestNode &&
        bestNode.classList.contains("adg-expandable") &&
        !bestNode.classList.contains("adg-selected")) {
      this._suppressEditorJump = true;
      bestNode.click();
      this._suppressEditorJump = false;
      this._updateDiagramHighlight(cursorLine, depth + 1);
    }
  }

  // ─── Template inspector ────────────────────────────────────────────────────

  _updateTemplateInspector(cursorLine, yamlText, cursorPos) {
    const tplInsp = this.shadowRoot.getElementById("template-inspector");
    if (!tplInsp || !this._hass) return;

    const lines = yamlText.split("\n");
    const line = lines[cursorLine] || "";

    // Detect value_template on current line or ±1 line
    let templateStr = null;
    let templateLine = -1;
    for (let i = Math.max(0, cursorLine - 1); i <= Math.min(lines.length - 1, cursorLine + 1); i++) {
      const m = lines[i].match(/value_template\s*:\s*(.+)/);
      if (m) {
        templateStr = m[1].trim();
        templateLine = i;
        break;
      }
    }

    if (!templateStr) {
      tplInsp.hidden = true;
      this._templateInspectorLine = -1;
      return;
    }

    // Strip outer YAML quotes
    if ((templateStr.startsWith('"') && templateStr.endsWith('"')) ||
        (templateStr.startsWith("'") && templateStr.endsWith("'"))) {
      templateStr = templateStr.slice(1, -1);
    }
    // Unescape YAML escaped quotes
    templateStr = templateStr.replace(/\\"/g, '"').replace(/\\'/g, "'");

    // Don't re-render if same template line and content
    if (this._templateInspectorLine === templateLine && this._templateInspectorStr === templateStr) return;
    this._templateInspectorLine = templateLine;
    this._templateInspectorStr = templateStr;

    // Hide entity inspector — template inspector takes priority
    const entInsp = this.shadowRoot.getElementById("entity-inspector");
    if (entInsp) entInsp.hidden = true;

    // Position near the cursor
    if (this._editor && cursorPos !== undefined) {
      try {
        const coords = this._editor.coordsAtPos(cursorPos);
        const pane = tplInsp.parentElement;
        if (coords && pane) {
          const paneRect = pane.getBoundingClientRect();
          const relTop = coords.top - paneRect.top + pane.scrollTop;
          const maxTop = pane.clientHeight - 280;
          tplInsp.style.top = `${Math.min(Math.max(relTop - 4, 60), maxTop)}px`;
        }
      } catch (e) { /* ignore */ }
    }

    // Extract entity IDs referenced in the template
    const entityRefs = [];
    const entityPattern = /(?:states|is_state|state_attr)\s*\(\s*['"]([a-z_]+\.[a-z0-9_]+)['"]/g;
    let em;
    while ((em = entityPattern.exec(templateStr)) !== null) {
      if (!entityRefs.includes(em[1])) entityRefs.push(em[1]);
    }

    // Build entity chips with live values
    const entityChips = entityRefs.map((eid) => {
      const st = this._hass.states[eid];
      if (!st) return `<span class="ti-entity-chip ti-unknown">${this._escH(eid)}: ???</span>`;
      const name = st.attributes?.friendly_name || eid.split(".")[1];
      const val = st.state;
      const cls = val === "on" ? "ti-on" : val === "off" ? "ti-off" : val === "unavailable" ? "ti-unavail" : "";
      return `<span class="ti-entity-chip ${cls}" title="${this._escH(eid)}">${this._escH(name)}: <b>${this._escH(val)}</b></span>`;
    }).join("");

    // Clean display of the template expression
    const cleanExpr = templateStr.replace(/\{\{|\}\}/g, "").trim();

    tplInsp.hidden = false;
    tplInsp.innerHTML = `
      <div class="ti-header">
        <span class="ti-label">📋 Template</span>
        <button class="ti-close" title="Close">✕</button>
      </div>
      <div class="ti-expr" style="background:#1a1a2e;color:#f0f0f0;font-size:13px;padding:10px 12px;font-family:monospace;white-space:pre-wrap;word-break:break-word;line-height:1.5;border-radius:4px;margin:4px 6px"><code style="color:#ffcc80">${this._escH(cleanExpr)}</code></div>
      ${entityChips ? `<div class="ti-entities">${entityChips}</div>` : ""}
      <div class="ti-preview">
        <span class="ti-preview-label">Result:</span>
        <span class="ti-preview-value" id="ti-preview-val">evaluating…</span>
      </div>
    `;
    tplInsp.querySelector(".ti-close").addEventListener("click", () => {
      tplInsp.hidden = true;
      this._templateInspectorLine = -1;
    });

    // Call HA /api/template to render the template live
    this._renderTemplatePreview(templateStr);
  }

  async _renderTemplatePreview(templateStr) {
    const previewEl = this.shadowRoot.getElementById("ti-preview-val");
    if (!previewEl || !this._hass) return;
    try {
      const resp = await this._hass.callApi("POST", "template", { template: templateStr });
      // resp is the rendered string
      const result = typeof resp === "string" ? resp : JSON.stringify(resp);
      previewEl.textContent = result.length > 100 ? result.slice(0, 100) + "…" : result;
      previewEl.className = "ti-preview-value ti-result-ok";
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      previewEl.textContent = msg.slice(0, 80);
      previewEl.className = "ti-preview-value ti-result-err";
    }
  }

  _updateEntityInspector(cursorLine, yamlText, cursorPos) {
    const insp = this.shadowRoot.getElementById("entity-inspector");
    if (!insp || !this._hass) return;

    // Skip entity inspector when template inspector is active
    const tplInsp = this.shadowRoot.getElementById("template-inspector");
    if (tplInsp && !tplInsp.hidden) return;

    const lines = yamlText.split("\n");
    let entityId = null;

    // Check current line and ±3 lines for entity_id: or list item that looks like entity.domain
    for (let i = Math.max(0, cursorLine - 1); i <= Math.min(lines.length - 1, cursorLine + 2) && !entityId; i++) {
      const m = lines[i].match(/entity_id\s*:\s*([a-z_]+\.[a-z0-9_]+)/);
      if (m) { entityId = m[1].trim(); break; }
      // Also detect bare entity IDs on list lines (e.g. "      - light.kitchen")
      const listM = lines[i].match(/^\s*-\s+([a-z_]+\.[a-z0-9_]+)\s*$/);
      if (listM) { entityId = listM[1].trim(); break; }
    }

    if (!entityId || !this._hass.states[entityId]) {
      if (!entityId) insp.hidden = true;
      return;
    }

    // Position the floating inspector to the right of the cursor line
    if (this._editor && cursorPos !== undefined) {
      try {
        const coords = this._editor.coordsAtPos(cursorPos);
        const pane = insp.parentElement;
        if (coords && pane) {
          const paneRect = pane.getBoundingClientRect();
          const relTop = coords.top - paneRect.top + pane.scrollTop;
          // Keep it within visible bounds (min 60px from top, max 20px from bottom)
          const maxTop = pane.clientHeight - 200;
          insp.style.top = `${Math.min(Math.max(relTop - 4, 60), maxTop)}px`;
        }
      } catch (e) { /* coordsAtPos can fail when editor not fully laid out */ }
    }

    const stateObj = this._hass.states[entityId];
    const attrs = stateObj.attributes || {};
    const friendlyName = attrs.friendly_name || "";
    const rows = Object.entries(attrs)
      .filter(([k]) => k !== "friendly_name")
      .map(([k, v]) => {
        const raw = typeof v === "object" ? JSON.stringify(v) : String(v);
        const display = raw.length > 70 ? raw.slice(0, 70) + "…" : raw;
        return `<tr><td class="ei-key">${k}</td><td class="ei-val">${display.replace(/</g, "&lt;")}</td></tr>`;
      }).join("");

    const stateClass = stateObj.state === "on" ? "ei-on" : stateObj.state === "off" ? "ei-off" : "";
    insp.hidden = false;
    insp.innerHTML = `
      <div class="ei-header">
        <div class="ei-header-main">
          ${friendlyName ? `<span class="ei-friendly">${friendlyName}</span>` : ""}
          <span class="ei-entity">${entityId}</span>
        </div>
        <span class="ei-state ${stateClass}">${stateObj.state}</span>
        <button class="ei-close" title="Close">✕</button>
      </div>
      <div class="ei-body"><table class="ei-table">${rows || "<tr><td colspan='2' class='ei-key'>no attributes</td></tr>"}</table></div>
      <div class="ei-footer">
        <a class="ei-config-link" href="/config/entities/entity_id/${entityId}" target="_top" title="Open entity settings">⚙ Configure</a>
        <a class="ei-config-link" href="/developer-tools/state?entity_id=${entityId}" target="_top" title="Open in Developer Tools">🔧 Dev Tools</a>
      </div>
    `;
    insp.querySelector(".ei-close").addEventListener("click", () => { insp.hidden = true; });
  }

  // ─── Entity list picker ────────────────────────────────────────────────────

  _updateEntityListPicker(cursorLine, yamlText, cursorPos) {
    const picker = this.shadowRoot.getElementById("entity-list-picker");
    if (!picker || !this._hass) return;

    const lines = yamlText.split("\n");
    const line = lines[cursorLine] || "";

    // Detect if we're on an entity_id/entity_ids list line or its items
    // Look backwards for the parent key
    let listIndent = -1;
    let isEntityList = false;
    let parentKeyLine = -1;
    let parentKeyHasInlineValue = false;
    for (let i = cursorLine; i >= 0; i--) {
      const l = lines[i];
      const keyMatch = l.match(/^(\s*)(entity_ids?|entities)\s*:(.*)/);
      if (keyMatch) {
        isEntityList = true;
        listIndent = keyMatch[1].length;
        parentKeyLine = i;
        parentKeyHasInlineValue = keyMatch[3].trim().length > 0; // e.g. "entity_id: light.abc"
        break;
      }
      // If we hit a line with same or less indent that isn't a list item, stop
      const indent = l.match(/^(\s*)/)[1].length;
      const isListItem = /^\s*-/.test(l);
      if (!isListItem && indent <= (listIndent === -1 ? 999 : listIndent) && l.trim() && i < cursorLine) break;
    }

    if (!isEntityList) {
      if (!picker.hidden) this._entityListPickerOpen = false;
      picker.hidden = true;
      return;
    }

    // Close inspector — they share the same space; only one panel at a time
    const insp = this.shadowRoot.getElementById("entity-inspector");
    if (insp) insp.hidden = true;

    // Collect current entity IDs already in this list block (for display + remove)
    const currentEntities = [];
    for (let i = cursorLine; i >= 0; i--) {
      const l = lines[i];
      if (l.match(/^(\s*)(entity_ids?|entities)\s*:/)) { break; }
      const m = l.match(/^\s*-\s+(.+)\s*$/);
      if (m && m[1].includes(".")) currentEntities.unshift(m[1].trim());
    }
    // Also scan forward
    for (let i = cursorLine + 1; i < lines.length; i++) {
      const l = lines[i];
      const m = l.match(/^\s*-\s+(.+)\s*$/);
      if (m && m[1].includes(".")) currentEntities.push(m[1].trim());
      else if (l.trim() && !/^\s*-/.test(l)) break;
    }
    this._entityListCurrentEntities = [...new Set(currentEntities)];
    this._entityListInsertIndent = listIndent + 2;
    this._entityListInsertLine = cursorLine;
    this._entityListParentKeyLine = parentKeyLine;
    this._entityListParentHasInlineValue = parentKeyHasInlineValue;

    // Position picker on the right side of the editor pane (avoids covering code)
    if (this._editor && cursorPos !== undefined) {
      try {
        const coords = this._editor.coordsAtPos(cursorPos);
        const pane = picker.parentElement;
        if (coords && pane) {
          const paneRect = pane.getBoundingClientRect();
          const relTop = coords.top - paneRect.top + pane.scrollTop;
          const maxTop = pane.clientHeight - 320;
          picker.style.top = `${Math.min(Math.max(relTop - 40, 60), maxTop)}px`;
          picker.style.left = "auto";
          picker.style.right = "8px";
        }
      } catch (e) { /* */ }
    }

    picker.hidden = false;
    const wasOpen = this._entityListPickerOpen;
    if (!wasOpen) {
      this._entityListPickerOpen = true;
      const searchEl = picker.querySelector(".elp-search");
      if (searchEl) { searchEl.value = ""; searchEl.focus(); }
    }
    this._renderEntityPickerCurrentList();
    if (!wasOpen) this._renderEntityPickerResults("");
  }

  _renderEntityPickerCurrentList() {
    const picker = this.shadowRoot.getElementById("entity-list-picker");
    if (!picker) return;
    let currentEl = picker.querySelector(".elp-current");
    if (!currentEl) {
      currentEl = document.createElement("div");
      currentEl.className = "elp-current";
      picker.querySelector(".elp-search").insertAdjacentElement("beforebegin", currentEl);
    }
    const items = this._entityListCurrentEntities || [];
    if (!items.length) { currentEl.hidden = true; return; }
    currentEl.hidden = false;
    currentEl.innerHTML = items.map((eid) => {
      const name = this._hass?.states?.[eid]?.attributes?.friendly_name || eid.split(".")[1] || eid;
      return `<div class="elp-current-item" data-id="${eid}">
        <span class="elp-name" title="${eid}">${name}</span>
        <button class="elp-remove" title="Remove">✕</button>
      </div>`;
    }).join("");
    currentEl.querySelectorAll(".elp-remove").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        this._removeEntityFromList(btn.closest(".elp-current-item").dataset.id);
      });
    });
  }

  _removeEntityFromList(entityId) {
    if (!this._editor) return;
    const doc = this._editor.state.doc;
    const text = doc.toString();
    const lines = text.split("\n");
    for (let i = 0; i < lines.length; i++) {
      const m = lines[i].match(/^(\s*)-\s+(.+)\s*$/);
      if (m && m[2].trim() === entityId) {
        const lineObj = doc.line(i + 1);
        // Delete the whole line including newline
        const from = i === 0 ? 0 : doc.line(i).to;
        const to = lineObj.to;
        this._editor.dispatch({ changes: { from: i > 0 ? doc.line(i).to : 0, to: lineObj.to } });
        // Reparse
        const newText = this._editor.state.doc.toString();
        const newLines = newText.split("\n");
        this._entityListCurrentEntities = (this._entityListCurrentEntities || []).filter((e) => e !== entityId);
        this._renderEntityPickerCurrentList();
        return;
      }
    }
  }

  _renderEntityPickerResults(query) {
    const resultsEl = this.shadowRoot.getElementById("elp-results");
    if (!resultsEl || !this._hass) return;

    const q = query.toLowerCase().trim();
    const states = Object.values(this._hass.states || {});
    const matches = states
      .filter((s) => {
        if (!q) return true;
        const name = (s.attributes?.friendly_name || "").toLowerCase();
        return s.entity_id.includes(q) || name.includes(q);
      })
      .slice(0, 20);

    if (!matches.length) {
      resultsEl.innerHTML = `<div class="elp-empty">No entities found</div>`;
      return;
    }

    resultsEl.innerHTML = matches.map((s) => {
      const name = s.attributes?.friendly_name || s.entity_id.split(".")[1];
      const stateClass = s.state === "on" ? "ei-on" : s.state === "off" ? "ei-off" : "";
      return `<div class="elp-item" data-id="${s.entity_id}" title="${s.entity_id}">
        <div class="elp-item-main">
          <span class="elp-name">${name}</span>
          <span class="ei-state ${stateClass}">${s.state}</span>
        </div>
        <span class="elp-id">${s.entity_id}</span>
      </div>`;
    }).join("");

    resultsEl.querySelectorAll(".elp-item").forEach((item) => {
      item.addEventListener("click", () => {
        this._insertEntityToList(item.dataset.id);
      });
    });
  }

  _insertEntityToList(entityId) {
    if (!this._editor) return;
    const picker = this.shadowRoot.getElementById("entity-list-picker");
    const doc = this._editor.state.doc;
    const lines = doc.toString().split("\n");

    // If parent key has an inline scalar (e.g. entity_id: light.abc), convert to list
    if (this._entityListParentHasInlineValue && this._entityListParentKeyLine >= 0) {
      const pkLine = this._entityListParentKeyLine;
      const rawLine = lines[pkLine] || "";
      const m = rawLine.match(/^(\s*)(entity_ids?|entities)\s*:\s+(.+)$/);
      if (m) {
        const keyIndent = m[1];
        const key = m[2];
        const existing = m[3].trim();
        const itemIndent = keyIndent + "  ";
        const newText = `${keyIndent}${key}:\n${itemIndent}- ${existing}\n${itemIndent}- ${entityId}`;
        const lineObj = doc.line(pkLine + 1);
        this._editor.dispatch({
          changes: { from: lineObj.from, to: lineObj.to, insert: newText },
          selection: { anchor: lineObj.from + newText.length },
        });
        this._entityListParentHasInlineValue = false;
        this._entityListCurrentEntities = [...(this._entityListCurrentEntities || []), entityId];
        this._renderEntityPickerCurrentList();
        this._editor.focus();
        const searchEl = picker?.querySelector(".elp-search");
        if (searchEl) { searchEl.value = ""; searchEl.focus(); }
        this._renderEntityPickerResults("");
        return;
      }
    }

    // Normal case: insert new list item after last existing item in the block
    const cursorLine = this._entityListInsertLine ?? (doc.lineAt(this._editor.state.selection.main.head).number - 1);
    const indent = " ".repeat(this._entityListInsertIndent ?? 4);

    // Find last list item line in this block (scan forward from parent key line)
    let insertAfterLine = cursorLine;
    const startScan = (this._entityListParentKeyLine >= 0 ? this._entityListParentKeyLine : cursorLine) + 1;
    for (let i = startScan; i < lines.length; i++) {
      if (/^\s*-/.test(lines[i])) insertAfterLine = i;
      else if (lines[i].trim()) break;
    }

    const lineNum = Math.min(insertAfterLine + 1, doc.lines);
    const lineObj = doc.line(lineNum);
    const insertText = `\n${indent}- ${entityId}`;
    const insertPos = lineObj.to;

    this._editor.dispatch({
      changes: { from: insertPos, insert: insertText },
      selection: { anchor: insertPos + insertText.length },
    });
    this._editor.focus();

    // Reset search for next addition
    const searchEl = picker?.querySelector(".elp-search");
    if (searchEl) { searchEl.value = ""; searchEl.focus(); }
    this._renderEntityPickerResults("");
  }

  // ─── End automation diagram ────────────────────────────────────────────────

  _updateBlueprintButton(blueprintPath) {
    const btn = this.shadowRoot.getElementById("btn-edit-blueprint");
    if (!btn) return;
    if (blueprintPath) {
      btn.style.display = "";
      btn.title = `Open blueprint: ${blueprintPath}`;
    } else {
      btn.style.display = "none";
    }
  }

  async _openBlueprint(path) {
    if (!path || !this._hass) return;
    this._setStatus(`Loading blueprint: ${path}…`);

    try {
      const token = this._hass.auth.data.access_token;
      const resp = await fetch(`/api/kyber/blueprint?path=${encodeURIComponent(path)}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`);
      const data = await resp.json();

      // Open editor in blueprint mode
      const editorPane = this.shadowRoot.getElementById("editor-container");
      if (!this._editor) this._initEditor(editorPane);
      const container = this.shadowRoot.getElementById("app-container");
      container.classList.add("editor-open");
      editorPane.classList.add("open");
      this.shadowRoot.querySelectorAll(".editor-controls").forEach((el) => { el.style.display = "block"; });

      this._editorMode = "blueprint";
      this._currentBlueprintPath = path;
      this._currentAutomationId = null;
      this._setEditorContextLabel("blueprint", path.split("/").pop());
      this._setEditorContent(data.yaml);
      this._dirty = false;
      this.shadowRoot.getElementById("btn-save").textContent = "Save blueprint";
      this.shadowRoot.getElementById("btn-save").disabled = false;
      this._updateBlueprintButton(null); // hide "Edit blueprint" while editing the blueprint
      this._setStatus(`Blueprint: ${path}`);
      this._saveEditorSession(path, "blueprint", path.split("/").pop());
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      this._setStatus(`Failed to load blueprint: ${msg}`, "error");
    }
  }

  async _saveBlueprintYaml() {
    if (!this._currentBlueprintPath || !this._hass) return;
    const yamlText = this._editor.state.doc.toString();
    const btn = this.shadowRoot.getElementById("btn-save");
    btn.disabled = true;
    this._setStatus("Saving blueprint…");

    try {
      const token = this._hass.auth.data.access_token;
      const resp = await fetch("/api/kyber/blueprint", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ path: this._currentBlueprintPath, yaml: yamlText }),
      });
      if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`);
      this._dirty = false;
      btn.textContent = "✓ Saved";
      this._setStatus(`Blueprint saved: ${this._currentBlueprintPath}`);
      setTimeout(() => { btn.textContent = "Save blueprint"; btn.disabled = false; }, 2000);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      btn.disabled = false;
      this._setStatus(`Save failed: ${msg}`, "error");
    }
  }

  _setEditorContextLabel(mode, label) {
    const ctxLabel = this.shadowRoot.getElementById("editor-context-label");
    if (!ctxLabel) return;
    ctxLabel.textContent = `${mode} > ${label}`;
  }

  // Re-parse editor YAML server-side to update diagram config.
  // Called debounced (1.2s) after editor changes so the diagram reflects edits.
  async _reparseEditorConfig(yamlText) {
    if (!this._hass || !yamlText?.trim()) return;
    const errorBar = this.shadowRoot.getElementById("yaml-error-bar");
    // Strip standalone {} and [] lines (HA writes empty mappings/lists this way)
    const cleaned = yamlText.replace(/^\s*(?:\{\}|\[\])\s*$/gm, "");
    try {
      const token = this._hass.auth.data.access_token;
      const resp = await fetch("/api/kyber/parse_yaml", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ yaml: cleaned }),
      });
      if (!resp.ok) {
        // YAML parse error — show error banner with AI fix button
        const errText = await resp.text();
        let errMsg = errText;
        try { const j = JSON.parse(errText); errMsg = j.error || j.message || errText; } catch (_) {}
        this._showYamlError(errMsg, yamlText);
        return;
      }
      // Valid YAML — hide error bar, clear error line, and update diagram
      if (errorBar) errorBar.hidden = true;
      this._lastYamlError = null;
      this._clearErrorLine();
      const { config } = await resp.json();
      if (config) {
        this._currentAutomationConfig = config;
        this._renderAutomationDiagram(yamlText);
      }
    } catch {
      /* silent — diagram uses previous config */
    }
  }

  _showYamlError(errMsg, yamlText) {
    this._lastYamlError = errMsg;
    // Extract error line number from YAML error message (e.g. "line 36, column 1")
    const lineMatch = errMsg.match(/line\s+(\d+)/i);
    if (lineMatch) this._setErrorLine(parseInt(lineMatch[1], 10));
    let errorBar = this.shadowRoot.getElementById("yaml-error-bar");
    if (!errorBar) {
      errorBar = document.createElement("div");
      errorBar.id = "yaml-error-bar";
      errorBar.className = "yaml-error-bar";
      const statusBar = this.shadowRoot.getElementById("status-bar");
      if (statusBar) statusBar.parentElement.insertBefore(errorBar, statusBar);
      else return;
    }
    errorBar.hidden = false;
    errorBar.innerHTML = `
      <span class="yeb-icon">⚠</span>
      <span class="yeb-msg">${this._escH(errMsg).slice(0, 120)}</span>
      <button class="yeb-btn yeb-autofix" title="Ask AI to fix this error">🤖 Auto-fix</button>
      <button class="yeb-btn yeb-guided" title="Guided error resolution">💡 Guide me</button>
      <button class="yeb-close" title="Dismiss">✕</button>
    `;
    errorBar.querySelector(".yeb-autofix").addEventListener("click", () => {
      this._aiAutofix(errMsg, yamlText);
    });
    errorBar.querySelector(".yeb-guided").addEventListener("click", () => {
      this._aiGuidedFix(errMsg, yamlText);
    });
    errorBar.querySelector(".yeb-close").addEventListener("click", () => {
      errorBar.hidden = true;
    });
  }

  // Highlight the error line in the editor with a red squiggly overlay
  _setErrorLine(lineNum) {
    this._errorLineNum = lineNum;
    // Scroll to the error line first
    if (this._editor && lineNum > 0) {
      try {
        const doc = this._editor.state.doc;
        if (lineNum <= doc.lines) {
          const pos = doc.line(lineNum).from;
          this._editor.dispatch({ selection: { anchor: pos }, scrollIntoView: true });
        }
      } catch { /* ignore */ }
    }
    // Apply after CM has rendered the scroll position
    setTimeout(() => this._applyErrorLineStyle(), 150);
  }

  _clearErrorLine() {
    this._errorLineNum = null;
    this._clearErrorLineStyle();
  }

  _clearErrorLineStyle() {
    if (!this._editor) return;
    this._editor.dom.querySelectorAll("[data-error-line]").forEach((el) => {
      el.style.background = "";
      el.style.borderLeft = "";
      el.style.backgroundImage = "";
      el.style.backgroundPosition = "";
      el.style.backgroundRepeat = "";
      el.style.backgroundSize = "";
      el.style.boxSizing = "";
      el.removeAttribute("data-error-line");
    });
  }

  // Apply inline error styles directly to the .cm-line DOM element
  _applyErrorLineStyle() {
    if (!this._editor || !this._errorLineNum) return;
    this._clearErrorLineStyle();
    try {
      const doc = this._editor.state.doc;
      const lineNum = this._errorLineNum;
      if (lineNum < 1 || lineNum > doc.lines) return;
      const lineObj = doc.line(lineNum);
      const domPos = this._editor.domAtPos(lineObj.from);
      if (!domPos) return;
      const el = domPos.node.nodeType === 3 ? domPos.node.parentElement : domPos.node;
      const cmLine = el?.closest?.(".cm-line") || el;
      if (!cmLine) return;
      cmLine.setAttribute("data-error-line", "true");
      cmLine.style.background = "rgba(255,82,82,0.15)";
      cmLine.style.borderLeft = "3px solid #ff5252";
      cmLine.style.backgroundImage = "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='6' height='3'%3E%3Cpath d='M0 2.5 L1.5 0.5 L3 2.5 L4.5 0.5 L6 2.5' fill='none' stroke='%23ff5252' stroke-width='1'/%3E%3C/svg%3E\")";
      cmLine.style.backgroundPosition = "bottom left";
      cmLine.style.backgroundRepeat = "repeat-x";
      cmLine.style.backgroundSize = "6px 3px";
      cmLine.style.boxSizing = "border-box";
    } catch { /* ignore */ }
  }

  async _aiAutofix(errMsg, yamlText) {
    if (!this._hass) return;
    const errorBar = this.shadowRoot.getElementById("yaml-error-bar");

    // Auto-fix known HA YAML formatting issues ({} / [] on standalone lines)
    if (/\{\}|\[\]/.test(errMsg) && /^\s*(?:\{\}|\[\])\s*$/m.test(yamlText)) {
      const fixed = yamlText.replace(/^\s*(?:\{\}|\[\])\s*$/gm, "");
      this._showFixPreview(fixed, yamlText, errMsg);
      return;
    }

    // Show progress in the error bar
    const autofixBtn = errorBar?.querySelector(".yeb-autofix");
    if (autofixBtn) { autofixBtn.disabled = true; autofixBtn.textContent = "🤖 Fixing…"; }

    const prompt = `Fix this YAML syntax error automatically. Return ONLY the corrected YAML, no explanation, no markdown fences.

Error: ${errMsg}

YAML:
${yamlText}`;

    try {
      const token = this._hass.auth.data.access_token;
      const resp = await fetch("/api/kyber/complete", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          prompt,
          context: "yaml_fix",
          history: [],
        }),
      });
      if (!resp.ok) throw new Error(`AI request failed: ${resp.status}`);
      const data = await resp.json();
      const aiText = (data.response || data.text || "").trim();

      // Extract YAML from the AI response (strip markdown fences if present)
      let fixedYaml = aiText;
      const fenceMatch = aiText.match(/```(?:yaml)?\n([\s\S]*?)```/);
      if (fenceMatch) fixedYaml = fenceMatch[1].trim();

      if (!fixedYaml) {
        this._setStatus("AI returned empty fix", "error");
        if (autofixBtn) { autofixBtn.disabled = false; autofixBtn.textContent = "🤖 Auto-fix"; }
        return;
      }

      // Show a diff-like preview before applying
      this._showFixPreview(fixedYaml, yamlText, errMsg);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      this._setStatus(`Auto-fix failed: ${msg}`, "error");
      if (autofixBtn) { autofixBtn.disabled = false; autofixBtn.textContent = "🤖 Auto-fix"; }
    }
  }

  _showFixPreview(fixedYaml, originalYaml, errMsg) {
    const errorBar = this.shadowRoot.getElementById("yaml-error-bar");
    if (!errorBar) return;

    // Count changed lines
    const origLines = originalYaml.split("\n");
    const fixLines = fixedYaml.split("\n");
    let changedCount = 0;
    const maxLines = Math.max(origLines.length, fixLines.length);
    for (let i = 0; i < maxLines; i++) {
      if ((origLines[i] || "") !== (fixLines[i] || "")) changedCount++;
    }

    errorBar.innerHTML = `
      <span class="yeb-icon">🔧</span>
      <span class="yeb-msg">AI fix ready — ${changedCount} line${changedCount !== 1 ? "s" : ""} changed</span>
      <button class="yeb-btn yeb-apply">✅ Apply fix</button>
      <button class="yeb-btn yeb-reject">❌ Reject</button>
    `;
    errorBar.querySelector(".yeb-apply").addEventListener("click", () => {
      this._setEditorContent(fixedYaml);
      errorBar.hidden = true;
      this._setStatus("AI fix applied ✓", "success");
    });
    errorBar.querySelector(".yeb-reject").addEventListener("click", () => {
      errorBar.hidden = true;
      this._setStatus("Fix rejected");
    });
  }

  _aiGuidedFix(errMsg, yamlText) {
    // Auto-fix known HA YAML formatting issues ({} / [] on standalone lines)
    if (/\{\}|\[\]/.test(errMsg) && /^\s*(?:\{\}|\[\])\s*$/m.test(yamlText)) {
      const fixed = yamlText.replace(/^\s*(?:\{\}|\[\])\s*$/gm, "");
      this._setEditorContent(fixed);
      const errorBar = this.shadowRoot.getElementById("yaml-error-bar");
      if (errorBar) errorBar.hidden = true;
      this._setStatus("Auto-fixed: removed HA empty {} / [] lines ✓", "success");
      return;
    }
    // Send the error to the chat as a guided conversation
    const promptInput = this.shadowRoot.getElementById("prompt-input");
    if (promptInput) {
      promptInput.value = `I have a YAML error in my ${this._editorMode || "automation"}: "${errMsg}". Can you help me understand what's wrong and guide me through fixing it step by step?`;
      // Trigger the AI ask
      const askBtn = this.shadowRoot.getElementById("btn-ask");
      if (askBtn) askBtn.click();
    }
    // Hide the error bar
    const errorBar = this.shadowRoot.getElementById("yaml-error-bar");
    if (errorBar) errorBar.hidden = true;
  }

  /** Strip standalone {} and [] lines that HA writes for empty mappings/lists. */
  _stripEmptyYamlBlocks(yaml) {
    return yaml.replace(/^\s*(?:\{\}|\[\])\s*$/gm, "");
  }

  async _loadAutomation(configId) {
    if (!configId || !this._hass) return;
    const isScript = this._editorMode === "script";
    const apiPath = isScript ? `config/script/config/${configId}` : `config/automation/config/${configId}`;
    this._setStatus(`Loading ${isScript ? "script" : "automation"}…`);

    try {
      const config = await this._hass.callApi("GET", apiPath);
      this._currentAutomationConfig = config; // store for diagram
      const yamlText = this._stripEmptyYamlBlocks(this._configToYaml(config));
      this._savedYaml = yamlText; // baseline for dirty tracking
      this._setEditorContent(yamlText);
      this._currentAutomationId = configId;
      this._dirty = false;
      this.shadowRoot.getElementById("btn-save").disabled = true;
      this._setStatus(`Loaded: ${configId}`);
      this._renderAutomationDiagram(yamlText);
      // Detect use_blueprint and show/hide the Edit blueprint button
      const blueprintPath = config.use_blueprint?.path || null;
      this._currentBlueprintPath = blueprintPath;
      this._updateBlueprintButton(blueprintPath);
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
      this._savedYaml = yamlText; // update baseline for dirty tracking
      this._clearEditorDraft(); // draft is now saved to HA
      const kind = isScript ? "script" : "automation";
      this._addChatHistory("user", `I saved the YAML for ${this._currentAutomationId}.`);
      this._addChatHistory("assistant", `[CHANGE] ${kind} YAML saved: ${this._currentAutomationId}`);
      this._setStatus("Saved ✓", "success");
    } catch (err) {
      btn.disabled = false;
      const msg = err instanceof Error ? err.message : (err != null ? String(err) : "unknown error");
      this._setStatus(`Save failed: ${msg}`, "error");
      // Show error bar with AI fix options for YAML errors
      if (msg.includes("YAML") || msg.includes("parse") || msg.includes("invalid")) {
        this._showYamlError(msg, yamlText);
      }
    }
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

  // ── Session persistence ──────────────────────────────────────────────────────

  _saveEditorSession(id, mode, title) {
    try {
      sessionStorage.setItem("kyber_editor_open", JSON.stringify({ id: String(id), mode, title }));
    } catch (_) {}
  }

  _saveEditorDraft(yaml) {
    if (!this._currentAutomationId) return;
    try {
      sessionStorage.setItem("kyber_editor_draft", JSON.stringify({ id: String(this._currentAutomationId), yaml }));
    } catch (_) {}
  }

  _clearEditorDraft() {
    try { sessionStorage.removeItem("kyber_editor_draft"); } catch (_) {}
  }

  _clearEditorSession() {
    try {
      sessionStorage.removeItem("kyber_editor_open");
      sessionStorage.removeItem("kyber_editor_draft");
    } catch (_) {}
  }

  async _restoreEditorState() {
    if (this._editorRestored) return;
    this._editorRestored = true;
    let saved;
    try {
      const raw = sessionStorage.getItem("kyber_editor_open");
      if (!raw) return;
      saved = JSON.parse(raw);
    } catch (_) { return; }
    if (!saved?.id || !this._hass) return;

    // Reopen the editor with the saved ID
    const editorPane = this.shadowRoot.getElementById("editor-container");
    if (!editorPane) return;
    if (!this._editor) this._initEditor(editorPane);

    const isScript = saved.mode === "script";
    const isBlueprint = saved.mode === "blueprint";
    this._currentAutomationId = saved.id;
    this._editorTitle = saved.title || saved.id;
    this._editorMode = saved.mode || "automation";

    const container = this.shadowRoot.getElementById("app-container");
    container.classList.add("editor-open");
    editorPane.classList.add("open");
    this.shadowRoot.querySelectorAll(".editor-controls").forEach((el) => { el.style.display = "block"; });

    let ctxType = "automation";
    let saveBtnText = "Save automation";
    if (isScript)    { ctxType = "script";    saveBtnText = "Save script"; }
    if (isBlueprint) { ctxType = "blueprint"; saveBtnText = "Save blueprint"; }
    this._setEditorContextLabel(ctxType, this._editorTitle);
    const saveBtn = this.shadowRoot.getElementById("btn-save");
    if (saveBtn) saveBtn.textContent = saveBtnText;

    // Check for an unsaved draft from the previous session
    let draft = null;
    try {
      const rawDraft = sessionStorage.getItem("kyber_editor_draft");
      if (rawDraft) {
        const d = JSON.parse(rawDraft);
        if (d.id === String(saved.id) && d.yaml) draft = d.yaml;
      }
    } catch (_) {}

    if (isBlueprint) {
      // Blueprint restore: reload file from disk (drafts not yet supported for blueprints)
      this._currentBlueprintPath = saved.id;
      this._updateBlueprintButton(null);
      await this._openBlueprint(saved.id).catch(() => {});
      return; // _openBlueprint handles everything from here
    }

    if (draft) {
      // Strip any standalone {} / [] left over from old drafts
      draft = this._stripEmptyYamlBlocks(draft);
      // Fetch fresh JSON config so diagram can use the expandable JSON path
      try {
        const cfgPath = isScript ? `config/script/config/${saved.id}` : `config/automation/config/${saved.id}`;
        const config = await this._hass.callApi("GET", cfgPath);
        this._currentAutomationConfig = config;
      } catch (_) { /* fallback: diagram uses YAML path */ }
      // Load the draft — show unsaved state so user knows this isn't from HA
      this._setEditorContent(draft);
      this._dirty = true;
      if (saveBtn) saveBtn.disabled = false;
      this._setStatus("Restored unsaved draft — review and save to apply", "warning");
      // Re-parse draft YAML to get accurate JSON config (draft may differ from saved)
      this._reparseEditorConfig(draft);
      this._renderAutomationDiagram(draft);
    } else {
      await this._loadAutomation(saved.id).catch(() => {});
    }
  }
};
