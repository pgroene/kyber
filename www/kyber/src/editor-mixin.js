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

  _setEditorContent(text) {
    this._editor.dispatch({
      changes: {
        from: 0,
        to: this._editor.state.doc.length,
        insert: text,
      },
    });
  }
};
