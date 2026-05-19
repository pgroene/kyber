const _HELP_DATA = {
  autopilot:  { icon: "🤖", desc: "Toggle auto-execution of AI proposals", cmds: [
    { usage: "/autopilot on",  desc: "Execute proposals automatically — no confirmation needed" },
    { usage: "/autopilot off", desc: "Show a confirm card before any change is applied" },
  ]},
  dashboard:  { icon: "📊", desc: "Manage Lovelace dashboards", cmds: [
    { usage: "/dashboard open [name]", desc: "Load a dashboard into the YAML editor" },
    { usage: "/dashboard close",       desc: "Close editor without saving" },
    { usage: "/dashboard save",        desc: "Save current editor content back to HA" },
    { usage: "/dashboard new",         desc: "Create a new storage-mode dashboard" },
    { usage: "/dashboard delete",      desc: "Permanently delete the open dashboard" },
  ]},
  automation: { icon: "⚡", desc: "Manage automations", cmds: [
    { usage: "/automation open <name>",   desc: "Fuzzy-find and open an automation in the YAML editor" },
    { usage: "/automation close",         desc: "Close editor without saving" },
    { usage: "/automation save",          desc: "Save current automation YAML" },
    { usage: "/automation new",           desc: "Open HA's automation editor in a new tab" },
    { usage: "/automation delete <name>", desc: "Permanently delete an automation" },
  ]},
  script:     { icon: "📜", desc: "Manage scripts", cmds: [
    { usage: "/script open <name>",   desc: "Open a script in the YAML editor" },
    { usage: "/script close",         desc: "Close editor without saving" },
    { usage: "/script save",          desc: "Save current script YAML" },
    { usage: "/script new",           desc: "Open HA's script editor in a new tab" },
    { usage: "/script delete <name>", desc: "Permanently delete a script" },
  ]},
  blueprint:  { icon: "🗺", desc: "Browse HA blueprints", cmds: [
    { usage: "/blueprint browse", desc: "Open the HA Blueprint page in a new tab" },
  ]},
  area:       { icon: "🏠", desc: "Manage Home Assistant areas", cmds: [
    { usage: "/area new <name>",            desc: "Create a new area" },
    { usage: "/area delete <name>",         desc: "Delete an area (entities become unassigned)" },
    { usage: "/area rename <old> to <new>", desc: "Rename an area" },
    { usage: "/area list",                  desc: "List all areas with their IDs" },
  ]},
  session:    { icon: "💬", desc: "Manage named chat sessions", cmds: [
    { usage: "/session new [name]",    desc: "Create a new session and switch to it" },
    { usage: "/session list",          desc: "Show all sessions with message counts" },
    { usage: "/session switch <name>", desc: "Switch to a different session" },
    { usage: "/session delete",        desc: "Delete the current session" },
  ]},
  memory:     { icon: "🧠", desc: "View and manage Kyber's learned memory", cmds: [
    { usage: "/memory list",           desc: "Show all saved facts inline in the chat" },
    { usage: "/memory search <query>", desc: "Search saved facts by keyword or category" },
    { usage: "/memory add <text>",     desc: "Add a new fact directly from chat" },
    { usage: "/memory delete <id>",    desc: "Delete an entry by ID" },
    { usage: "/memory analyze",        desc: "Scan automations/scenes/scripts and propose new facts" },
    { usage: "/memory deep",           desc: "Start deep background analysis (6-lens rotation)" },
    { usage: "/memory stats",          desc: "Show entry counts by category and source" },
  ]},
  reset:      { icon: "🔄", desc: "Clear the current chat", cmds: [
    { usage: "/reset", desc: "Shows a danger confirm card — on Execute, clears all messages and history" },
  ]},
  update:     { icon: "⬆️", desc: "Update Kyber to the latest version via HACS", cmds: [
    { usage: "/update",         desc: "Check for updates and install if available" },
    { usage: "/update restart", desc: "Install update and restart Home Assistant automatically" },
  ]},
  help:       { icon: "❓", desc: "Show help for Kyber slash commands", cmds: [
    { usage: "/help",           desc: "Overview of all commands" },
    { usage: "/help <command>", desc: "Detailed help card for a specific command" },
  ]},
};
_HELP_DATA.knowledge = _HELP_DATA.memory;

export const SlashMixin = (Base) => class extends Base {
  _showHelp(topic) {
    const key = topic === "memory" ? "knowledge" : (topic || "");
    const history = this.shadowRoot?.getElementById("chat-history");
    if (!history) return;

    if (key && _HELP_DATA[key]) {
      const h = _HELP_DATA[key];
      const card = document.createElement("div");
      card.className = "chat-message assistant kyber-help-card";
      card.innerHTML = `
        <div class="kh-header">
          <span class="kh-icon">${h.icon}</span>
          <strong class="kh-title">/${topic || key}</strong>
          <span class="kh-subtitle">${h.desc}</span>
        </div>
        <div class="kh-rows">
          ${h.cmds.map((c) => `
            <div class="kh-row" data-fill="${this._escapeAttr(c.usage)}">
              <code class="kh-usage">${this._escapeHtml(c.usage)}</code>
              <span class="kh-row-desc">${this._escapeHtml(c.desc)}</span>
            </div>`).join("")}
        </div>
        <div class="kh-footer">Click a row to fill it into the input ↑</div>`;
      card.querySelectorAll(".kh-row").forEach((row) => {
        row.addEventListener("click", () => {
          const ta = this.shadowRoot.getElementById("prompt-input");
          if (ta) { ta.value = row.dataset.fill + " "; ta.focus(); this._onPromptInput(ta); }
        });
      });
      history.appendChild(card);
      history.scrollTop = history.scrollHeight;
      return;
    }

    if (key && !_HELP_DATA[key]) {
      const known = Object.keys(_HELP_DATA).filter((k) => k !== "knowledge").join(", ");
      this._appendMessage(`No help found for "${topic}". Available: ${known}`, "assistant");
      return;
    }

    // /help with no topic — render overview grid
    const card = document.createElement("div");
    card.className = "chat-message assistant kyber-help-overview";
    const items = Object.entries(_HELP_DATA)
      .filter(([k]) => k !== "knowledge")
      .map(([k, h]) => `
        <div class="kho-item" data-cmd="${k}">
          <span class="kho-icon">${h.icon}</span>
          <strong class="kho-name">/${k}</strong>
          <span class="kho-desc">${h.desc}</span>
        </div>`).join("");
    card.innerHTML = `
      <div class="kho-title">⌨️ Kyber Slash Commands</div>
      <div class="kho-grid">${items}</div>
      <div class="kho-footer">Click a command for details, or type <code>/help &lt;command&gt;</code></div>`;
    card.querySelectorAll(".kho-item").forEach((el) => {
      el.addEventListener("click", () => this._showHelp(el.dataset.cmd));
    });
    history.appendChild(card);
    history.scrollTop = history.scrollHeight;
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

    // ── Top-level slash command autocomplete (/au… /da…) ──────────────
    const slashAc = val.match(/^\/(\w*)$/);
    if (slashAc) {
      const partial = slashAc[1].toLowerCase();
      const cmds = ["autopilot on", "autopilot off", "dashboard", "automation", "script", "blueprint", "area", "knowledge", "memory", "reset", "update", "help", "session"];
      const matches = cmds.filter((c) => c.startsWith(partial)).map((c) => ({
        entity_id: "/" + c,
        friendly_name: _HELP_DATA[c.split(" ")[0]]?.desc || "",
      }));
      if (matches.length) {
        this._acItems = matches;
        this._acToken = val;
        this._acIndex = -1;
        this._buildAcList(true);
        return;
      }
    }

    // ── Unified sub-action autocomplete for every command ─────────────
    // Matches: /<cmd> <partial-sub>  (e.g. "/dashboard op" → "open,…")
    const CMD_SUBS = {
      autopilot:  ["on", "off"],
      dashboard:  ["open", "close", "save", "new", "delete", "help"],
      automation: ["open", "close", "save", "new", "delete", "help"],
      script:     ["open", "close", "save", "new", "delete", "help"],
      blueprint:  ["browse", "help"],
      area:       ["new", "delete", "rename", "list", "help"],
      session:    ["new", "list", "switch", "delete", "help"],
      memory:     ["list", "search", "add", "delete", "analyze", "deep", "stats", "help"],
      knowledge:  ["list", "search", "add", "delete", "analyze", "deep", "stats", "help"],
      update:     ["restart", "help"],
      help:       ["autopilot", "dashboard", "automation", "script", "blueprint", "area", "session", "memory", "reset", "update", "help"],
      reset:      [],
    };
    const cmdSubAc = val.match(/^\/(autopilot|dashboard|automation|script|blueprint|area|session|memory|knowledge|update|help|reset)\s+(\w*)$/i);
    if (cmdSubAc) {
      const cmd = cmdSubAc[1].toLowerCase();
      const partial = (cmdSubAc[2] || "").toLowerCase();
      const subs = CMD_SUBS[cmd] || [];
      const helpData = _HELP_DATA[cmd === "knowledge" ? "memory" : cmd];
      const matches = subs
        .filter((s) => s.startsWith(partial))
        .map((s) => {
          const entry = (helpData?.cmds || []).find((c) => c.usage.match(new RegExp(`^\\/${cmd} ${s}\\b`)));
          return { entity_id: `/${cmd} ${s}`, friendly_name: entry?.desc || "" };
        });
      if (matches.length) {
        this._acItems = matches;
        this._acToken = val;
        this._acIndex = -1;
        this._buildAcList(true);
        return;
      }
    }

    // ── /memory delete <id>  →  suggest fact IDs ──────────────────────
    const memDel = val.match(/^\/(knowledge|memory)\s+delete\s+(.*)$/i);
    if (memDel) {
      const partial = (memDel[2] || "").toLowerCase();
      const cmd = memDel[1];
      this._fetchAcFacts().then((facts) => {
        const filtered = facts
          .filter((f) => f.id.toLowerCase().includes(partial) || f.content.toLowerCase().includes(partial))
          .slice(0, 8)
          .map((f) => ({
            entity_id: `/${cmd} delete ${f.id}`,
            badge: f.category,
            friendly_name: f.content.slice(0, 60) + (f.content.length > 60 ? "…" : ""),
          }));
        if (filtered.length) {
          this._acItems = filtered;
          this._acToken = val;
          this._acIndex = -1;
          this._buildAcList(true);
        }
      });
      return;
    }

    // ── /memory search <query>  →  suggest categories + tags ──────────
    const memSearch = val.match(/^\/(knowledge|memory)\s+search\s+(.*)$/i);
    if (memSearch) {
      const partial = (memSearch[2] || "").toLowerCase();
      const cmd = memSearch[1];
      this._fetchAcFacts().then((facts) => {
        const cats = [...new Set(facts.map((f) => f.category).filter(Boolean))];
        const tags = [...new Set(facts.flatMap((f) => (f.tags || "").split(",").map((t) => t.trim()).filter(Boolean)))];
        const allTerms = [
          ...cats.map((c) => ({ term: c, type: "category" })),
          ...tags.map((t) => ({ term: t, type: "tag" })),
        ];
        const filtered = allTerms
          .filter(({ term }) => !partial || term.toLowerCase().includes(partial))
          .slice(0, 8)
          .map(({ term, type }) => ({
            entity_id: `/${cmd} search ${term}`,
            badge: type,
            friendly_name: "",
          }));
        if (filtered.length) {
          this._acItems = filtered;
          this._acToken = val;
          this._acIndex = -1;
          this._buildAcList(true);
        }
      });
      return;
    }

    // ── /session switch|delete <name> ─────────────────────────────────
    const sessionArg = val.match(/^\/session\s+(switch|delete)\s+(.*)$/i);
    if (sessionArg) {
      const action = sessionArg[1].toLowerCase();
      const partial = (sessionArg[2] || "").toLowerCase();
      this._fetchAcSessions().then((sessions) => {
        const filtered = sessions
          .filter((s) => s.name.toLowerCase().includes(partial) || s.id.toLowerCase().includes(partial))
          .slice(0, 8)
          .map((s) => ({
            entity_id: `/session ${action} ${s.name}`,
            badge: s.id === this._activeSessionId ? "active" : null,
            friendly_name: `${s.message_count} msg${s.message_count !== 1 ? "s" : ""}`,
          }));
        if (filtered.length) {
          this._acItems = filtered;
          this._acToken = val;
          this._acIndex = -1;
          this._buildAcList(true);
        }
      });
      return;
    }

    // ── /area delete|rename <name>  →  suggest area names ─────────────
    const areaArg = val.match(/^\/area\s+(delete|rename)\s+(.*)$/i);
    if (areaArg) {
      const partial = (areaArg[2] || "").toLowerCase();
      const action = areaArg[1];
      const areas = Object.values(this._hass.areas || {});
      const filtered = areas
        .filter((a) => a.name.toLowerCase().includes(partial) || (a.area_id || "").toLowerCase().includes(partial))
        .slice(0, 8)
        .map((a) => ({
          entity_id: `/area ${action} ${a.name}`,
          friendly_name: a.area_id,
        }));
      if (filtered.length) {
        this._acItems = filtered;
        this._acToken = val;
        this._acIndex = -1;
        this._buildAcList(true);
        return;
      }
    }

    // ── /automation|script|dashboard open|delete <name> ──────────────
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
            .map((s) => ({
              entity_id: `/${cmd} ${action} ${s.attributes.friendly_name || s.entity_id}`,
              friendly_name: s.entity_id,
            }));
        } else if (cmd === "script") {
          candidates = Object.values(this._hass.states || {})
            .filter((s) => s.entity_id.startsWith("script."))
            .map((s) => ({
              entity_id: `/${cmd} ${action} ${s.attributes.friendly_name || s.entity_id}`,
              friendly_name: s.entity_id,
            }));
        } else if (cmd === "dashboard") {
          const panels = this._hass.panels || {};
          candidates = Object.values(panels)
            .filter((p) => p.component_name === "lovelace" && p.url_path && p.url_path !== "kyber")
            .map((p) => ({
              entity_id: `/${cmd} ${action} ${p.title || p.url_path}`,
              friendly_name: p.url_path,
            }));
        } else if (cmd === "area") {
          candidates = Object.values(this._hass.areas || {})
            .map((a) => ({
              entity_id: `/${cmd} ${action} ${a.name}`,
              friendly_name: a.area_id,
            }));
        }
        const filtered = candidates.filter((c) =>
          c.entity_id.toLowerCase().includes(partial) ||
          c.friendly_name.toLowerCase().includes(partial)
        ).slice(0, 8);
        if (filtered.length) {
          this._acItems = filtered;
          this._acToken = val;
          this._acIndex = -1;
          this._buildAcList(true);
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
        <span class="ac-id">${item.entity_id}${item.badge ? `<span class="ac-badge">${item.badge}</span>` : ""}</span>
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

  /** Fetch knowledge facts for autocomplete with 30s cache. */
  async _fetchAcFacts() {
    const now = Date.now();
    if (this._acFactsCache && now - (this._acFactsCacheTs || 0) < 30000) return this._acFactsCache;
    try {
      const token = this._hass?.auth?.data?.access_token;
      const resp = await fetch("/api/kyber/knowledge", { headers: { Authorization: `Bearer ${token}` } });
      const data = await resp.json();
      this._acFactsCache = data.entries || [];
      this._acFactsCacheTs = Date.now();
      return this._acFactsCache;
    } catch { return []; }
  }

  /** Fetch sessions for autocomplete with 15s cache. */
  async _fetchAcSessions() {
    const now = Date.now();
    if (this._acSessionsCache && now - (this._acSessionsCacheTs || 0) < 15000) return this._acSessionsCache;
    try {
      const token = this._hass?.auth?.data?.access_token;
      const resp = await fetch("/api/kyber/sessions", { headers: { Authorization: `Bearer ${token}` } });
      const data = await resp.json();
      this._acSessionsCache = data.sessions || [];
      this._acSessionsCacheTs = Date.now();
      return this._acSessionsCache;
    } catch { return []; }
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

    // /X help → show help card for that command
    if (action === "help") return this._showHelp(cmd === "knowledge" ? "memory" : cmd);

    switch (cmd) {
      case "help":       return this._showHelp(action || "");
      case "dashboard":  return this._cmdDashboard(action, nameArg);
      case "automation": return this._cmdAutomation(action, nameArg);
      case "script":     return this._cmdScript(action, nameArg);
      case "blueprint":  return this._cmdBlueprint(action, nameArg);
      case "area":       return this._cmdArea(action, nameArg);
      case "knowledge":
      case "memory":     return this._handleKnowledgeCommand(argStr.trim());
      case "update":     return this._cmdUpdate(action === "restart");
    }
  }

  // ──── /update ────────────────────────────────────────────────────

  _cmdUpdate(withRestart = false) {
    // Find the Kyber update entity provided by HACS (update.kyber or similar)
    const updateEntity = Object.values(this._hass.states || {}).find(
      (s) => s.entity_id.startsWith("update.") &&
             (s.attributes.title || s.entity_id).toLowerCase().includes("kyber")
    );

    if (!updateEntity) {
      this._showMsg("⚠️ No update entity found for Kyber. Make sure HACS is installed and Kyber is managed by HACS.");
      return;
    }

    const entityId      = updateEntity.entity_id;
    const installedVer  = updateEntity.attributes.installed_version || "unknown";
    const latestVer     = updateEntity.attributes.latest_version    || "unknown";
    const hasUpdate     = updateEntity.state === "on";
    const releaseUrl    = updateEntity.attributes.release_url       || null;

    if (!hasUpdate) {
      this._showMsg(`✅ Kyber is already up-to-date (v${installedVer}).`);
      return;
    }

    const detail = `v${installedVer} → v${latestVer}${withRestart ? " + Home Assistant will restart" : ""}`;
    const warning = withRestart ? "Home Assistant will restart after the update. Active sessions will be interrupted." : null;

    this._buildCommandCard({
      icon: "⬆️",
      title: `Update Kyber${withRestart ? " + Restart" : ""}`,
      detail,
      warning,
      onConfirm: async (card) => {
        const btn = card.querySelector(".btn-cmd-execute");
        btn.textContent = `⏳ Downloading v${latestVer}…`;
        try {
          await this._hass.callService("update", "install", { entity_id: entityId });
          btn.textContent = `✅ Kyber v${latestVer} installed`;
          this._appendMessage(`✅ Kyber updated to **v${latestVer}**${releaseUrl ? ` — [release notes](${releaseUrl})` : ""}.${withRestart ? "\n⏳ Restarting Home Assistant…" : ""}`, "assistant");
          if (withRestart) {
            await new Promise((r) => setTimeout(r, 1500));
            await this._hass.callService("homeassistant", "restart", {});
          }
        } catch (err) {
          btn.textContent = "▶ Execute";
          btn.disabled = false;
          card.querySelector(".btn-cmd-cancel").disabled = false;
          this._setStatus(`Update failed: ${err.message}`, "error");
        }
      },
    });
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
};
