"""Generate the new slash-commands-mixin.js with visual help cards + unified autocomplete."""
import pathlib

JS = r"""const HELP_DATA = {
  autopilot:  { icon: "\u{1F916}", desc: "Toggle auto-execution of AI proposals", cmds: [
    { usage: "/autopilot on",  desc: "Execute proposals automatically \u2014 no confirmation needed" },
    { usage: "/autopilot off", desc: "Show a confirm card before any change is applied" },
  ]},
  dashboard:  { icon: "\u{1F4CA}", desc: "Manage Lovelace dashboards", cmds: [
    { usage: "/dashboard open [name]", desc: "Load a dashboard into the YAML editor" },
    { usage: "/dashboard close",       desc: "Close editor without saving" },
    { usage: "/dashboard save",        desc: "Save current editor content back to HA" },
    { usage: "/dashboard new",         desc: "Create a new storage-mode dashboard" },
    { usage: "/dashboard delete",      desc: "Permanently delete the open dashboard" },
  ]},
  automation: { icon: "\u26A1", desc: "Manage automations", cmds: [
    { usage: "/automation open <name>",   desc: "Fuzzy-find and open an automation in the YAML editor" },
    { usage: "/automation close",         desc: "Close editor without saving" },
    { usage: "/automation save",          desc: "Save current automation YAML" },
    { usage: "/automation new",           desc: "Open HA's automation editor in a new tab" },
    { usage: "/automation delete <name>", desc: "Permanently delete an automation" },
  ]},
  script: { icon: "\u{1F4DC}", desc: "Manage scripts", cmds: [
    { usage: "/script open <name>",   desc: "Open a script in the YAML editor" },
    { usage: "/script close",         desc: "Close editor without saving" },
    { usage: "/script save",          desc: "Save current script YAML" },
    { usage: "/script new",           desc: "Open HA's script editor in a new tab" },
    { usage: "/script delete <name>", desc: "Permanently delete a script" },
  ]},
  blueprint: { icon: "\u{1F5FA}", desc: "Browse HA blueprints", cmds: [
    { usage: "/blueprint browse", desc: "Open the HA Blueprint page in a new tab" },
  ]},
  area: { icon: "\u{1F3E0}", desc: "Manage Home Assistant areas", cmds: [
    { usage: "/area new <name>",            desc: "Create a new area" },
    { usage: "/area delete <name>",         desc: "Delete an area (entities become unassigned)" },
    { usage: "/area rename <old> to <new>", desc: "Rename an area" },
    { usage: "/area list",                  desc: "List all areas with their IDs" },
  ]},
  session: { icon: "\u{1F4AC}", desc: "Manage named chat sessions", cmds: [
    { usage: "/session new [name]",    desc: "Create a new session and switch to it" },
    { usage: "/session list",          desc: "Show all sessions with message counts" },
    { usage: "/session switch <name>", desc: "Switch to a different session" },
    { usage: "/session delete",        desc: "Delete the current session" },
  ]},
  memory: { icon: "\u{1F9E0}", desc: "View and manage Kyber's learned memory", cmds: [
    { usage: "/memory list",           desc: "Show all saved facts inline in the chat" },
    { usage: "/memory search <query>", desc: "Search saved facts by keyword or category" },
    { usage: "/memory add <text>",     desc: "Add a new fact directly from chat" },
    { usage: "/memory delete <id>",    desc: "Delete an entry by ID" },
    { usage: "/memory analyze",        desc: "Scan automations/scenes/scripts and propose new facts" },
    { usage: "/memory deep",           desc: "Start deep background analysis (6-lens rotation)" },
    { usage: "/memory stats",          desc: "Show entry counts by category and source" },
  ]},
  reset: { icon: "\u{1F504}", desc: "Clear the current chat and start fresh", cmds: [
    { usage: "/reset", desc: "Shows a danger confirm card \u2014 on Execute, clears all messages" },
  ]},
  help: { icon: "\u2753", desc: "Show help for Kyber slash commands", cmds: [
    { usage: "/help",           desc: "List all commands with one-line descriptions" },
    { usage: "/help <command>", desc: "Show detailed help card for a specific command" },
  ]},
};
HELP_DATA.knowledge = HELP_DATA.memory;

export const SlashMixin = (Base) => class extends Base {
  _showHelp(topic) {
    const history = this.shadowRoot?.getElementById("chat-history");
    if (!history) return;

    const data = HELP_DATA[topic];

    if (topic && data) {
      const rowsHtml = data.cmds.map((c) => `
        <div class="kh-row" data-fill="${c.usage}">
          <code class="kh-usage">${c.usage}</code>
          <span class="kh-desc">${c.desc}</span>
        </div>`).join("");
      const card = document.createElement("div");
      card.className = "kyber-help-card chat-message assistant";
      card.innerHTML = `
        <div class="kh-header">
          <span class="kh-icon">${data.icon}</span>
          <strong class="kh-title">${topic}</strong>
          <span class="kh-subtitle">${data.desc}</span>
        </div>
        <div class="kh-rows">${rowsHtml}</div>
        <div class="kh-footer">Click a command to fill it in \u2191</div>`;
      card.querySelectorAll(".kh-row").forEach((row) => {
        row.addEventListener("click", () => {
          const input = this.shadowRoot?.getElementById("prompt-input");
          if (input) { input.value = row.dataset.fill + " "; input.focus(); }
        });
      });
      history.appendChild(card);
      history.scrollTop = history.scrollHeight;
      return;
    }

    if (topic && !data) {
      this._appendMessage(
        `No help found for "${topic}". Try: ${Object.keys(HELP_DATA).filter((k) => k !== "knowledge").join(", ")}`,
        "assistant"
      );
      return;
    }

    // /help with no arg \u2014 overview grid
    const overviewCmds = ["autopilot", "dashboard", "automation", "script", "blueprint", "area", "session", "memory", "reset", "help"];
    const itemsHtml = overviewCmds.map((cmd) => {
      const d = HELP_DATA[cmd];
      if (!d) return "";
      return `<div class="kho-item" data-cmd="${cmd}">
        <span class="kho-icon">${d.icon}</span>
        <strong class="kho-name">/${cmd}</strong>
        <span class="kho-desc">${d.desc}</span>
      </div>`;
    }).join("");
    const overview = document.createElement("div");
    overview.className = "kyber-help-overview chat-message assistant";
    overview.innerHTML = `
      <div class="kho-title">\u2328\uFE0F Kyber Slash Commands</div>
      <div class="kho-grid">${itemsHtml}</div>
      <div class="kho-footer">Type <code>/help &lt;command&gt;</code> for details</div>`;
    overview.querySelectorAll(".kho-item").forEach((item) => {
      item.addEventListener("click", () => this._showHelp(item.dataset.cmd));
    });
    history.appendChild(overview);
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

    // \u2500\u2500 Top-level slash command autocomplete (/au\u2026 /da\u2026) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
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

    // \u2500\u2500 Unified sub-action autocomplete (/dashboard o, /memory l, etc.) \u2500\u2500
    const CMD_SUBS = {
      autopilot:  ["on", "off"],
      dashboard:  ["open", "close", "save", "new", "delete"],
      automation: ["open", "close", "save", "new", "delete"],
      script:     ["open", "close", "save", "new", "delete"],
      blueprint:  ["browse"],
      area:       ["new", "delete", "rename", "list"],
      session:    ["new", "list", "switch", "delete"],
      memory:     ["list", "search", "add", "delete", "analyze", "deep", "stats", "help"],
      knowledge:  ["list", "search", "add", "delete", "analyze", "deep", "stats", "help"],
      help:       ["autopilot", "dashboard", "automation", "script", "blueprint", "area", "session", "memory", "reset", "help"],
      reset:      [],
    };
    const cmdSubAc = val.match(/^\/(autopilot|dashboard|automation|script|blueprint|area|session|memory|knowledge|help|reset)\s+(\w*)$/i);
    if (cmdSubAc) {
      const cmd = cmdSubAc[1].toLowerCase();
      const partial = (cmdSubAc[2] || "").toLowerCase();
      const subs = CMD_SUBS[cmd] || [];
      const matches = subs
        .filter((s) => s.startsWith(partial))
        .map((s) => ({ entity_id: `/${cmd} ${s}`, friendly_name: "" }));
      if (matches.length) {
        this._acItems = matches; this._acToken = val; this._acIndex = -1;
        this._buildAcList(true);
        return;
      }
    }

    // \u2500\u2500 /memory delete <id>  \u2192  suggest fact IDs \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
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
            friendly_name: f.content.slice(0, 60) + (f.content.length > 60 ? "\u2026" : ""),
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

    // \u2500\u2500 /memory search <query>  \u2192  suggest categories + tags \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
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

    // \u2500\u2500 /session switch <name> \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    const sessionArg = val.match(/^\/session\s+(switch)\s+(.*)$/i);
    if (sessionArg) {
      const partial = (sessionArg[2] || "").toLowerCase();
      this._fetchAcSessions().then((sessions) => {
        const filtered = sessions
          .filter((s) => s.name.toLowerCase().includes(partial) || s.id.toLowerCase().includes(partial))
          .slice(0, 8)
          .map((s) => ({
            entity_id: `/session switch ${s.name}`,
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

    // \u2500\u2500 /area delete|rename <name>  \u2192  suggest area names \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
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

    // \u2500\u2500 /automation|script|dashboard open|delete|rename <name> \u2500\u2500\u2500\u2500
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
          candidates = Object.values(this._hass.areas || {})
            .map((a) => ({ entity_id: a.area_id, friendly_name: a.name }));
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

  /** Only update which item has the active class \u2014 no DOM rebuild. */
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

  /** Fetch knowledge facts for autocomplete (30s cache). */
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

  /** Fetch sessions for autocomplete (15s cache). */
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

  _closeAc() {
    this._acItems = [];
    this._acIndex = -1;
    this._acToken = "";
    const list = this.shadowRoot.getElementById("ac-list");
    if (list) { list.classList.remove("open"); list.innerHTML = ""; }
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
      case "help":
        return this._showHelp(action);
      case "dashboard":
        if (action === "help") return this._showHelp("dashboard");
        return this._cmdDashboard(action, nameArg);
      case "automation":
        if (action === "help") return this._showHelp("automation");
        return this._cmdAutomation(action, nameArg);
      case "script":
        if (action === "help") return this._showHelp("script");
        return this._cmdScript(action, nameArg);
      case "blueprint":
        if (action === "help") return this._showHelp("blueprint");
        return this._cmdBlueprint(action, nameArg);
      case "area":
        if (action === "help") return this._showHelp("area");
        return this._cmdArea(action, nameArg);
      case "session":
        if (action === "help") return this._showHelp("session");
        break;
      case "autopilot":
        if (action === "help") return this._showHelp("autopilot");
        break;
      case "reset":
        if (action === "help") return this._showHelp("reset");
        break;
      case "knowledge":
      case "memory":
        if (parts[0].toLowerCase() === "help") return this._showHelp("memory");
        return this._handleKnowledgeCommand(argStr.trim());
    }
  }

  // \u2500\u2500\u2500\u2500 /dashboard \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

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
          icon: "\u{1F4CA}", title: `Open dashboard editor`,
          detail: label,
          onConfirm: (card) => {
            this._openDashboard(urlPath);
            card.querySelector(".btn-cmd-execute").textContent = "\u2713 Opened";
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
          icon: "\u{1F4BE}", title: "Save dashboard",
          detail: this.shadowRoot.getElementById("dashboard-select")?.options[
            this.shadowRoot.getElementById("dashboard-select")?.selectedIndex]?.textContent || "",
          onConfirm: (card) => {
            this._saveDashboard().then(() => { card.querySelector(".btn-cmd-execute").textContent = "\u2713 Saved"; });
          },
        });
        break;
      case "new":
        this._buildCommandCard({
          icon: "\uff0b", title: "Create new dashboard",
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
          icon: "\u{1F5D1}", title: "Delete dashboard",
          detail: label, danger: true,
          warning: "This permanently removes the dashboard from the sidebar.",
          onConfirm: async (card) => {
            try {
              const panels = this._hass.panels || {};
              const p = Object.values(panels).find((x) => x.url_path === urlPath);
              if (p) await this._hass.callWS({ type: "lovelace/dashboards/delete", dashboard_id: p.id || urlPath });
              this._closeEditor();
              card.querySelector(".btn-cmd-execute").textContent = "\u2713 Deleted";
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

  // \u2500\u2500\u2500\u2500 /automation \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

  _cmdAutomation(action, nameArg) {
    switch (action) {
      case "open": {
        const state = this._findEntity("automation", nameArg);
        if (!state) { this._showMsg(`Automation not found: "${nameArg}". Try a partial name.`); return; }
        const friendly = state.attributes.friendly_name || state.entity_id;
        const configId = state.attributes.id || state.entity_id.replace("automation.", "");
        this._buildCommandCard({
          icon: "\u{1F4DD}", title: "Open automation editor",
          detail: `${state.entity_id} \u2014 ${friendly}`,
          onConfirm: (card) => {
            this._openEditor(state.entity_id);
            card.querySelector(".btn-cmd-execute").textContent = "\u2713 Opened";
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
          icon: "\u{1F4BE}", title: "Save automation",
          detail: this._currentAutomationId,
          onConfirm: (card) => {
            this._saveAutomation().then(() => { card.querySelector(".btn-cmd-execute").textContent = "\u2713 Saved"; });
          },
        });
        break;
      case "new":
        this._buildCommandCard({
          icon: "\uff0b", title: "Create new automation",
          detail: "Opens HA's automation editor in a new tab",
          onConfirm: (card) => {
            window.open("/config/automation/edit/new", "_blank");
            card.querySelector(".btn-cmd-execute").textContent = "\u2713 Opened";
          },
        });
        break;
      case "delete": {
        const state = this._findEntity("automation", nameArg);
        if (!state) { this._showMsg(`Automation not found: "${nameArg}".`); return; }
        const friendly = state.attributes.friendly_name || state.entity_id;
        const configId = state.attributes.id;
        this._buildCommandCard({
          icon: "\u{1F5D1}", title: "Delete automation",
          detail: `${state.entity_id} \u2014 ${friendly}`,
          danger: true,
          warning: "This permanently deletes the automation.",
          onConfirm: async (card) => {
            try {
              await this._hass.callApi("DELETE", `config/automation/config/${configId}`);
              card.querySelector(".btn-cmd-execute").textContent = "\u2713 Deleted";
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

  // \u2500\u2500\u2500\u2500 /script \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

  _cmdScript(action, nameArg) {
    switch (action) {
      case "open": {
        const state = this._findEntity("script", nameArg);
        if (!state) { this._showMsg(`Script not found: "${nameArg}".`); return; }
        const friendly = state.attributes.friendly_name || state.entity_id;
        this._buildCommandCard({
          icon: "\u{1F4DC}", title: "Open script editor",
          detail: `${state.entity_id} \u2014 ${friendly}`,
          onConfirm: (card) => {
            this._openEditor(state.entity_id);
            card.querySelector(".btn-cmd-execute").textContent = "\u2713 Opened";
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
          icon: "\u{1F4BE}", title: "Save script",
          detail: this._currentAutomationId || "(current)",
          onConfirm: (card) => {
            this._saveAutomation().then(() => { card.querySelector(".btn-cmd-execute").textContent = "\u2713 Saved"; });
          },
        });
        break;
      case "new":
        this._buildCommandCard({
          icon: "\uff0b", title: "Create new script",
          detail: "Opens HA's script editor in a new tab",
          onConfirm: (card) => {
            window.open("/config/script/edit/new", "_blank");
            card.querySelector(".btn-cmd-execute").textContent = "\u2713 Opened";
          },
        });
        break;
      case "delete": {
        const state = this._findEntity("script", nameArg);
        if (!state) { this._showMsg(`Script not found: "${nameArg}".`); return; }
        const friendly = state.attributes.friendly_name || state.entity_id;
        const configId = state.entity_id.replace("script.", "");
        this._buildCommandCard({
          icon: "\u{1F5D1}", title: "Delete script",
          detail: `${state.entity_id} \u2014 ${friendly}`,
          danger: true,
          warning: "This permanently deletes the script.",
          onConfirm: async (card) => {
            try {
              await this._hass.callApi("DELETE", `config/script/config/${configId}`);
              card.querySelector(".btn-cmd-execute").textContent = "\u2713 Deleted";
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

  // \u2500\u2500\u2500\u2500 /blueprint \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

  _cmdBlueprint(action) {
    switch (action) {
      case "open":
      case "browse":
        this._buildCommandCard({
          icon: "\u{1F5FA}", title: "Browse blueprints",
          detail: "Opens HA's Blueprint page in a new tab",
          onConfirm: (card) => {
            window.open("/config/blueprint", "_blank");
            card.querySelector(".btn-cmd-execute").textContent = "\u2713 Opened";
          },
        });
        break;
      default:
        this._showMsg(`/blueprint commands: browse (opens HA blueprint page)`);
    }
  }

  // \u2500\u2500\u2500\u2500 /area \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

  _cmdArea(action, nameArg) {
    switch (action) {
      case "new":
      case "create": {
        const name = nameArg;
        if (!name) { this._showMsg(`Usage: /area new <name>`); return; }
        this._buildCommandCard({
          icon: "\uff0b", title: "Create area",
          detail: name,
          onConfirm: async (card) => {
            try {
              await this._executeActions([{ type: "create_area", name }]);
              card.querySelector(".btn-cmd-execute").textContent = "\u2713 Created";
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
          icon: "\u{1F5D1}", title: "Delete area",
          detail: nameArg,
          danger: true,
          warning: "Entities assigned to this area will become unassigned.",
          onConfirm: async (card) => {
            try {
              await this._executeActions([{ type: "delete_area", area_id: nameArg.toLowerCase().replace(/\s+/g, "_") }]);
              card.querySelector(".btn-cmd-execute").textContent = "\u2713 Deleted";
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
          icon: "\u270f", title: "Rename area",
          detail: `"${oldName}" \u2192 "${newName}"`,
          onConfirm: async (card) => {
            try {
              await this._executeActions([{
                type: "rename_area",
                area_id: oldName.trim().toLowerCase().replace(/\s+/g, "_"),
                name: newName.trim(),
              }]);
              card.querySelector(".btn-cmd-execute").textContent = "\u2713 Renamed";
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
          this._showMsg("Areas:\n" + areaReg.map((a) => `\u2022 ${a.name} (${a.area_id})`).join("\n"));
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
"""

# The JS string above uses unicode escapes which Python will decode.
# We need to write the ACTUAL unicode chars to the JS file.
# Decode the unicode escapes properly by evaluating them as JS-style escapes manually.
# Since Python doesn't natively support \u{...}, we post-process:
import re

def decode_js_unicode(s):
    # Replace \u{XXXX} with actual unicode char
    s = re.sub(r'\\u\{([0-9A-Fa-f]+)\}', lambda m: chr(int(m.group(1), 16)), s)
    # Replace \uXXXX with actual unicode char  
    s = re.sub(r'\\u([0-9A-Fa-f]{4})', lambda m: chr(int(m.group(1), 16)), s)
    return s

content = decode_js_unicode(JS)

target = pathlib.Path(r"C:\workspaces\home-assistant\github-copilot-integration\www\kyber\src\slash-commands-mixin.js")
target.write_text(content, encoding="utf-8", newline="\n")
print(f"Written {len(content)} chars to {target}")
