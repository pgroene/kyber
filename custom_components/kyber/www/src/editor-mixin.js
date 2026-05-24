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
          clearTimeout(self._inspectorDebounce);
          self._inspectorDebounce = setTimeout(() => {
            const yamlText = update.state.doc.toString();
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
    const newDashBtn = this.shadowRoot.getElementById("btn-new-dashboard");
    if (newDashBtn) newDashBtn.style.display = "none";

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
    const newDashBtn = this.shadowRoot.getElementById("btn-new-dashboard");
    if (newDashBtn) newDashBtn.style.display = "none";
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

    const pushItem = (endLine) => {
      if (currentItem && currentSection) {
        currentItem.to_line = endLine;
        result[currentSection].push(currentItem);
        currentItem = null;
      }
    };

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];

      // Top-level section header
      const secM = line.match(/^([a-z_]+)\s*:/);
      if (secM) {
        pushItem(i - 1);
        currentSection = sectionMap[secM[1]] || null;
        continue;
      }

      if (!currentSection) continue;

      if (/^  - /.test(line)) {
        pushItem(i - 1);
        currentItem = { from_line: i, to_line: i, fields: {} };
        const inline = line.replace(/^  -\s*/, "").trim();
        if (inline.includes(": ")) {
          const ci = inline.indexOf(": ");
          const k = inline.slice(0, ci).trim();
          const v = inline.slice(ci + 2).replace(/['"]/g, "").trim();
          if (k) currentItem.fields[k] = v;
        } else if (inline && inline.endsWith(":")) {
          // bare compound key: choose:, parallel:, repeat:, if:, sequence:
          const k = inline.slice(0, -1).trim();
          if (k) currentItem.fields[k] = true;
        } else if (inline && !inline.includes(":")) {
          // bare scalar list item
          currentItem.fields._value = inline;
        }
      } else if (currentItem && /^    \S/.test(line)) {
        const trimmed = line.trim();
        const ci = trimmed.indexOf(":");
        if (ci > 0) {
          const k = trimmed.slice(0, ci).trim();
          const v = trimmed.slice(ci + 1).trim().replace(/['"]/g, "");
          currentItem.fields[k] = v;
          currentItem._lastKey = k; // track for list-value capture
        }
      } else if (currentItem && /^      - /.test(line)) {
        // 6-space list items: first item fills in empty parent key (e.g., entity_id: \n  - sensor.x)
        const val = line.replace(/^      -\s*/, "").trim().replace(/['"]/g, "");
        const lk = currentItem._lastKey;
        if (lk && currentItem.fields[lk] === "") {
          currentItem.fields[lk] = val; // use first list item as display value
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

    // Use stored JSON config when available (more reliable than YAML re-parsing)
    const cfg = this._currentAutomationConfig;
    if (cfg) {
      this._renderDiagramFromJson(diag, cfg, yamlText);
    } else {
      this._renderDiagramFromYaml(diag, yamlText);
    }
  }

  // ── Diagram from JSON config (accurate, expanded) ─────────────────────────

  _renderDiagramFromJson(diag, cfg, yamlText) {
    const isScript = this._editorMode === "script";

    // Scripts use sequence: instead of trigger:/action:
    const triggers    = isScript ? [] : [].concat(cfg.triggers || cfg.trigger || []).filter(Boolean);
    const conditions  = isScript ? [] : [].concat(cfg.conditions || cfg.condition || []).filter(Boolean);
    const actions     = isScript
      ? [].concat(cfg.sequence || []).filter(Boolean)
      : [].concat(cfg.actions || cfg.action || []).filter(Boolean);

    // Build YAML line-range index for cursor ↔ node sync
    this._diagLineBlocks = this._parseAutomationBlocks(yamlText);

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

    // Render a single action node with optional expandable children
    const renderActionNode = (item, cls, fromLine, toLine, depth) => {
      const { icon, title, sub } = this._blockMetaFromJson("actions", item);
      const safeTitle = this._escH(title);
      const safeSub = this._escH(sub);
      const indent = depth ? `margin-left:${depth * 14}px;` : "";
      const children = this._getActionChildren(item);
      const isExpandable = children.length > 0;

      const wrapper = document.createElement("div");
      wrapper.className = "adg-node-wrapper";

      const nodeEl = document.createElement("div");
      nodeEl.className = `adg-node ${cls}${depth ? " adg-sub-node" : ""}${isExpandable ? " adg-expandable" : ""}`;
      nodeEl.dataset.from = String(fromLine);
      nodeEl.dataset.to = String(toLine);
      nodeEl.setAttribute("style", indent);
      nodeEl.setAttribute("title", `${title}${sub ? ": " + sub : ""}${isExpandable ? " — click to expand" : ""}`);
      nodeEl.innerHTML = `<span class="adg-icon">${icon}</span><span class="adg-title">${safeTitle}</span>${sub ? `<span class="adg-sub">${safeSub}</span>` : ""}${isExpandable ? `<span class="adg-expand-btn">▶</span>` : ""}`;

      const toggleExpand = () => {
        const childrenEl = wrapper.querySelector(":scope > .adg-children");
        if (!childrenEl) return;
        const open = !childrenEl.hidden;
        childrenEl.hidden = open;
        const btn = nodeEl.querySelector(".adg-expand-btn");
        if (btn) btn.textContent = open ? "▶" : "▼";
        nodeEl.classList.toggle("adg-expanded", !open);
      };

      nodeEl.addEventListener("click", (e) => {
        if (isExpandable) {
          toggleExpand();
          e.stopPropagation();
          return;
        }
        if (fromLine || toLine) this._jumpEditorToBlock(fromLine, toLine);
      });

      wrapper.appendChild(nodeEl);

      if (isExpandable) {
        const childrenEl = document.createElement("div");
        childrenEl.className = "adg-children";
        childrenEl.hidden = true;
        children.forEach((child) => {
          childrenEl.appendChild(renderActionNode(child, cls, 0, 0, depth + 1));
        });
        wrapper.appendChild(childrenEl);
      }

      return wrapper;
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
        } else {
          const { icon, title, sub } = this._blockMetaFromJson(sectionKey, item);
          const nodeEl = document.createElement("div");
          nodeEl.className = `adg-node ${cls}`;
          nodeEl.dataset.from = String(fromLine);
          nodeEl.dataset.to = String(toLine);
          nodeEl.setAttribute("title", `${title}${sub ? ": " + sub : ""}`);
          nodeEl.innerHTML = `<span class="adg-icon">${icon}</span><span class="adg-title">${this._escH(title)}</span>${sub ? `<span class="adg-sub">${this._escH(sub)}</span>` : ""}`;
          nodeEl.addEventListener("click", () => { if (fromLine || toLine) this._jumpEditorToBlock(fromLine, toLine); });
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
    if (item.if !== undefined) {
      const then = [].concat(item.then || []);
      const els  = [].concat(item.else || []);
      return [...then, ...els];
    }
    if (item.choose !== undefined) {
      const branches = (item.choose || []).flatMap((opt) => opt.sequence || opt.then || []);
      const def = [].concat(item.default || []);
      return [...branches, ...def];
    }
    if (item.repeat !== undefined) {
      return [].concat(item.repeat?.sequence || []);
    }
    if (item.parallel !== undefined) {
      return [].concat(item.parallel || []);
    }
    return [];
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
      const c = item.condition || "";
      const ICONS = { state: "✅", template: "📋", time: "⏰", numeric_state: "🔢", zone: "📍", and: "🔗", or: "🔀", not: "❌", device: "📱", trigger: "⚡" };
      const entityId = (Array.isArray(item.entity_id) ? item.entity_id[0] : item.entity_id) || "";
      const sub = entityId.includes(".") ? entityId.split(".")[1] : entityId;
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
      return { icon: "🔁", title: "repeat", sub: item.repeat?.count ? `${item.repeat.count}× · ${seqCount} actions ▶` : `${seqCount} actions ▶` };
    }
    if (item.wait_template !== undefined || item.wait_for_trigger !== undefined) return { icon: "⏳", title: "wait", sub: "" };
    if (item.delay !== undefined) return { icon: "⏱", title: "delay", sub: String(item.delay) };
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

  _jumpEditorToBlock(fromLine, toLine) {
    if (!this._editor) return;
    const doc = this._editor.state.doc;
    const safeFrom = Math.max(1, fromLine + 1);
    const safeTo = Math.min(doc.lines, toLine + 1);
    const from = doc.line(safeFrom).from;
    const to = doc.line(safeTo).to;
    this._editor.dispatch({ selection: { anchor: from, head: to }, scrollIntoView: true });
    this._editor.focus();
  }

  _updateDiagramHighlight(cursorLine) {
    const diag = this.shadowRoot.getElementById("automation-diagram");
    if (!diag || diag.hidden) return;
    diag.querySelectorAll(".adg-node").forEach((node) => {
      const from = parseInt(node.dataset.from, 10);
      const to = parseInt(node.dataset.to, 10);
      node.classList.toggle("adg-active", cursorLine >= from && cursorLine <= to);
    });
  }

  _updateEntityInspector(cursorLine, yamlText, cursorPos) {
    const insp = this.shadowRoot.getElementById("entity-inspector");
    if (!insp || !this._hass) return;

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

  async _loadAutomation(configId) {
    if (!configId || !this._hass) return;
    const isScript = this._editorMode === "script";
    const apiPath = isScript ? `config/script/config/${configId}` : `config/automation/config/${configId}`;
    this._setStatus(`Loading ${isScript ? "script" : "automation"}…`);

    try {
      const config = await this._hass.callApi("GET", apiPath);
      this._currentAutomationConfig = config; // store for diagram
      const yamlText = this._configToYaml(config);
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
      this._clearEditorDraft(); // draft is now saved to HA
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
      this._renderAutomationDiagram(draft);
    } else {
      await this._loadAutomation(saved.id).catch(() => {});
    }
  }
};
