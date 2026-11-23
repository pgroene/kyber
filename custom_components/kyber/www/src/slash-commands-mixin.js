const _HELP_DATA = {
  autopilot:  { icon: "🤖", descKey: "sc_help_autopilot", cmds: [
    { usage: "/autopilot on",  descKey: "sc_help_autopilot_on" },
    { usage: "/autopilot off", descKey: "sc_help_autopilot_off" },
  ]},
  dashboard:  { icon: "📊", descKey: "sc_help_dashboard", cmds: [
    { usage: "/dashboard open [name]", descKey: "sc_help_dashboard_open" },
    { usage: "/dashboard close",       descKey: "sc_help_editor_close" },
    { usage: "/dashboard save",        descKey: "sc_help_dashboard_save" },
    { usage: "/dashboard new",         descKey: "sc_help_dashboard_new" },
    { usage: "/dashboard delete",      descKey: "sc_help_dashboard_delete" },
  ]},
  automation: { icon: "⚡", descKey: "sc_help_automation", cmds: [
    { usage: "/automation open <name>",   descKey: "sc_help_automation_open" },
    { usage: "/automation close",         descKey: "sc_help_editor_close" },
    { usage: "/automation save",          descKey: "sc_help_automation_save" },
    { usage: "/automation new",           descKey: "sc_help_automation_new" },
    { usage: "/automation delete <name>", descKey: "sc_help_automation_delete" },
  ]},
  script:     { icon: "📜", descKey: "sc_help_script", cmds: [
    { usage: "/script open <name>",   descKey: "sc_help_script_open" },
    { usage: "/script close",         descKey: "sc_help_editor_close" },
    { usage: "/script save",          descKey: "sc_help_script_save" },
    { usage: "/script new",           descKey: "sc_help_script_new" },
    { usage: "/script delete <name>", descKey: "sc_help_script_delete" },
  ]},
  blueprint:  { icon: "🗺", descKey: "sc_help_blueprint", cmds: [
    { usage: "/blueprint open <path>",  descKey: "sc_help_blueprint_open" },
    { usage: "/blueprint browse",       descKey: "sc_help_blueprint_browse" },
  ]},
  area:       { icon: "🏠", descKey: "sc_help_area", cmds: [
    { usage: "/area new <name>",            descKey: "sc_help_area_new" },
    { usage: "/area delete <name>",         descKey: "sc_help_area_delete" },
    { usage: "/area rename <old> to <new>", descKey: "sc_help_area_rename" },
    { usage: "/area list",                  descKey: "sc_help_area_list" },
  ]},
  session:    { icon: "💬", descKey: "sc_help_session", cmds: [
    { usage: "/session new [name]",    descKey: "sc_help_session_new" },
    { usage: "/session list",          descKey: "sc_help_session_list" },
    { usage: "/session switch <name>", descKey: "sc_help_session_switch" },
    { usage: "/session delete",        descKey: "sc_help_session_delete" },
  ]},
  memory:     { icon: "🧠", descKey: "sc_help_memory", cmds: [
    { usage: "/memory list",           descKey: "sc_help_memory_list" },
    { usage: "/memory search <query>", descKey: "sc_help_memory_search" },
    { usage: "/memory add <text>",     descKey: "sc_help_memory_add" },
    { usage: "/memory delete <id>",    descKey: "sc_help_memory_delete" },
    { usage: "/memory analyze",        descKey: "sc_help_memory_analyze" },
    { usage: "/memory deep",           descKey: "sc_help_memory_deep" },
    { usage: "/memory stats",          descKey: "sc_help_memory_stats" },
  ]},
  reset:      { icon: "🔄", descKey: "sc_help_reset", cmds: [
    { usage: "/reset", descKey: "sc_help_reset_run" },
  ]},
  update:     { icon: "⬆️", descKey: "sc_help_update", cmds: [
    { usage: "/update",                descKey: "sc_help_update_check" },
    { usage: "/update restart",        descKey: "sc_help_update_restart" },
    { usage: "/update force",          descKey: "sc_help_update_force" },
    { usage: "/update force restart",  descKey: "sc_help_update_force_restart" },
  ]},
  help:       { icon: "❓", descKey: "sc_help_help", cmds: [
    { usage: "/help",           descKey: "sc_help_help_overview" },
    { usage: "/help <command>", descKey: "sc_help_help_topic" },
  ]},
};
_HELP_DATA.knowledge = _HELP_DATA.memory;

export const SlashMixin = (Base) => class extends Base {
  _showHelp(topic) {
    const t = this._t || ((k) => k);
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
          <span class="kh-subtitle">${t(h.descKey)}</span>
        </div>
        <div class="kh-rows">
          ${h.cmds.map((c) => `
            <div class="kh-row" data-fill="${this._escapeAttr(c.usage)}">
              <code class="kh-usage">${this._escapeHtml(c.usage)}</code>
              <span class="kh-row-desc">${this._escapeHtml(t(c.descKey))}</span>
            </div>`).join("")}
        </div>
        <div class="kh-footer">${t("sc_help_row_hint")}</div>`;
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
      this._appendMessage(t("sc_help_not_found", { topic, known }), "assistant");
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
          <span class="kho-desc">${t(h.descKey)}</span>
        </div>`).join("");
    card.innerHTML = `
      <div class="kho-title">${t("sc_help_overview_title")}</div>
      <div class="kho-grid">${items}</div>
      <div class="kho-footer">${t("sc_help_overview_footer")} <code>/help &lt;command&gt;</code></div>`;
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
    const t = this._t || ((k) => k);
    const val = textarea.value;

    // ── Top-level slash command autocomplete (/au… /da…) ──────────────
    const slashAc = val.match(/^\/(\w*)$/);
    if (slashAc) {
      const partial = slashAc[1].toLowerCase();
      const cmds = ["autopilot on", "autopilot off", "dashboard", "automation", "script", "blueprint", "area", "knowledge", "memory", "reset", "update", "help", "session"];
      const matches = cmds.filter((c) => c.startsWith(partial)).map((c) => {
        const dk = _HELP_DATA[c.split(" ")[0]]?.descKey;
        return { entity_id: "/" + c, friendly_name: dk ? t(dk) : "" };
      });
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
    // Convention: every slash command sub-action MUST be listed in CMD_SUBS
    // and have a corresponding entry in _HELP_DATA.cmds for the description.
    const CMD_SUBS = {
      autopilot:  ["on", "off"],
      dashboard:  ["open", "close", "save", "new", "delete", "help"],
      automation: ["open", "close", "save", "new", "delete", "help"],
      script:     ["open", "close", "save", "new", "delete", "help"],
      blueprint:  ["open", "browse", "help"],
      area:       ["new", "delete", "rename", "list", "help"],
      session:    ["new", "list", "switch", "delete", "help"],
      memory:     ["list", "search", "add", "delete", "analyze", "deep", "stats", "help"],
      knowledge:  ["list", "search", "add", "delete", "analyze", "deep", "stats", "help"],
      update:     ["restart", "force", "help"],
      help:       ["autopilot", "dashboard", "automation", "script", "blueprint", "area", "session", "memory", "reset", "update", "help"],
      reset:      [],
    };

    // ── Third-level autocomplete: /update force <partial> → restart ────
    const updateForceAc = val.match(/^\/update\s+force\s+(\w*)$/i);
    if (updateForceAc) {
      const partial = (updateForceAc[1] || "").toLowerCase();
      const opts = ["restart"];
      const matches = opts
        .filter((s) => s.startsWith(partial))
        .map((s) => {
          const dk = (_HELP_DATA.update?.cmds || []).find((c) => c.usage === `/update force ${s}`)?.descKey;
          return { entity_id: `/update force ${s}`, friendly_name: dk ? t(dk) : "" };
        });
      if (matches.length) {
        this._acItems = matches;
        this._acToken = val;
        this._acIndex = -1;
        this._buildAcList(true);
        return;
      }
    }

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
          return { entity_id: `/${cmd} ${s}`, friendly_name: entry?.descKey ? t(entry.descKey) : "" };
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
            badge: type === "category" ? t("sc_badge_category") : t("sc_badge_tag"),
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
            badge: s.id === this._activeSessionId ? t("sc_badge_active") : null,
            friendly_name: t(s.message_count !== 1 ? "sc_msg_count_other" : "sc_msg_count_one", { n: s.message_count }),
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
      const resp = await this._hass.fetchWithAuth("/api/kyber/knowledge");
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
      const resp = await this._hass.fetchWithAuth("/api/kyber/sessions");
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
      case "update":     return this._cmdUpdate(action, nameArg);
    }
  }

  // ──── /update ────────────────────────────────────────────────────

  async _cmdUpdate(action = "", nameArg = "") {
    const t = this._t || ((k) => k);
    const force = action === "force";
    const withRestart = force ? nameArg.trim().toLowerCase() === "restart" : action === "restart";

    if (force) {
      return this._cmdUpdateForce(withRestart);
    }

    // ── Default: use HACS update entity ──────────────────────────────
    const allUpdateEntities = Object.values(this._hass.states || {}).filter(
      (s) => s.entity_id.startsWith("update.")
    );
    const updateEntity = allUpdateEntities.find(
      (s) => (s.attributes.title || s.entity_id).toLowerCase().includes("kyber")
    );

    if (!updateEntity) {
      const known = allUpdateEntities.map((s) => s.entity_id).join(", ") || t("sc_none");
      this._showMsg(t("sc_update_no_entity", { known }));
      return;
    }

    const entityId     = updateEntity.entity_id;
    const installedVer = (updateEntity.attributes.installed_version || t("sc_unknown")).replace(/^v/i, "");
    const latestVer    = (updateEntity.attributes.latest_version    || t("sc_unknown")).replace(/^v/i, "");
    const hasUpdate    = updateEntity.state === "on";
    const releaseUrl   = updateEntity.attributes.release_url || null;

    if (!hasUpdate) {
      this._buildCommandCard({
        icon: "🔄",
        title: t("sc_update_uptodate_title"),
        detail: t("sc_update_uptodate_detail", { ver: installedVer }),
        executeLabel: t("sc_update_refresh_hacs"),
        onConfirm: async (card) => {
          const btn = card.querySelector(".btn-cmd-execute");
          btn.textContent = t("sc_update_refreshing");
          try {
            await this._hass.callService("homeassistant", "update_entity", { entity_id: entityId });
            btn.textContent = t("sc_update_refreshed");
            await new Promise((r) => setTimeout(r, 1500));
            const refreshed = this._hass.states[entityId];
            const nowLatest = (refreshed?.attributes?.latest_version || "").replace(/^v/i, "");
            if (refreshed?.state === "on") {
              this._appendMessage(t("sc_update_found", { ver: nowLatest }), "assistant");
            } else {
              this._appendMessage(t("sc_update_uptodate_refreshed", { ver: installedVer }), "assistant");
            }
            this._checkUpdateBadge();
          } catch (err) {
          btn.textContent = t("cmd_confirm_execute"); btn.disabled = false;
            card.querySelector(".btn-cmd-cancel").disabled = false;
            this._setStatus(t("sc_refresh_failed", { msg: err.message }), "error");
          }
        },
      });
      return;
    }

    // Fetch release notes from our API (non-fatal if it fails)
    let hacsReleaseNotes = "";
    try {
      const rInfo = await this._hass.callApi("GET", "kyber/self_update");
      hacsReleaseNotes = rInfo.release_notes || "";
    } catch (_) { /* non-fatal */ }

    this._buildCommandCard({
      icon: "⬆️",
      title: t(withRestart ? "sc_update_hacs_title_restart" : "sc_update_hacs_title"),
      detail: [
        `v${installedVer} → v${latestVer}`,
        hacsReleaseNotes ? `\n📋 ${hacsReleaseNotes.trim()}` : "",
        withRestart ? `\n${t("sc_update_restart_note")}` : "",
      ].filter(Boolean).join(""),
      warning: withRestart ? t("sc_restart_warning") : null,
      onConfirm: async (card) => {
        const t = this._t || ((k) => k);
        const btn = card.querySelector(".btn-cmd-execute");
        btn.textContent = `${t("update_installing")} v${latestVer}…`;
        try {
          await this._hass.callService("update", "install", { entity_id: entityId });
          btn.textContent = `${t("update_installed")} v${latestVer}`;
          this._appendMessage(
            `${t("sc_update_done", { ver: latestVer })}\n\n` +
            (hacsReleaseNotes
              ? `📋 **${t("sc_release_notes")}:**\n${hacsReleaseNotes}`
              : (releaseUrl ? `[${t("sc_release_notes")}](${releaseUrl})` : "")),
            "assistant"
          );
          this._checkUpdateBadge();
          if (withRestart) {
            await new Promise((r) => setTimeout(r, 1500));
            this._showRestartOverlay(latestVer);
            await this._hass.callService("homeassistant", "restart", {});
          }
        } catch (err) {
          btn.textContent = t("cmd_confirm_execute"); btn.disabled = false;
          card.querySelector(".btn-cmd-cancel").disabled = false;
          this._setStatus(`${t("err_update_failed")}: ${err.message}`, "error");
        }
      },
    });
  }

  // ── /update force — bypass HACS, download directly from GitHub ───
  async _cmdUpdateForce(withRestart = false) {
    const t = this._t || ((k) => k);
    this._setStatus(t("sc_force_checking"));
    let info;
    try {
      info = await this._hass.callApi("GET", "kyber/self_update");
    } catch (err) {
      this._setStatus("");
      this._showMsg(t("sc_force_unreachable", { msg: err?.message || err?.error || String(err) }));
      return;
    }
    this._setStatus("");

    const { current_version, latest_version, update_available, release_url, release_notes } = info;

    if (!update_available) {
      this._showMsg(t("sc_force_latest", { ver: current_version, latest: latest_version }));
      this._checkUpdateBadge();
      return;
    }

    const detail = [
      `v${current_version} → v${latest_version}`,
      release_notes ? `\n📋 ${release_notes.trim()}` : "",
      withRestart ? `\n${t("sc_force_restart_note")}` : "",
    ].filter(Boolean).join("");

    this._buildCommandCard({
      icon: "⬆️",
      title: t(withRestart ? "sc_force_title_restart" : "sc_force_title"),
      detail,
      warning: withRestart ? t("sc_restart_warning") : null,
      onConfirm: async (card) => {
        const t = this._t || ((k) => k);
        const btn = card.querySelector(".btn-cmd-execute");
        btn.textContent = `${t("update_downloading")} v${latest_version}…`;
        try {
          const result = await this._hass.callApi("POST", "kyber/self_update", { restart: withRestart });
          btn.textContent = `${t("update_updated")} v${latest_version}`;
          const postNotes = result.release_notes || "";
          this._appendMessage(
            `${t("sc_force_done", { ver: latest_version })}\n\n` +
            (postNotes
              ? `📋 **${t("sc_release_notes")}:**\n${postNotes}`
              : (release_url ? `[${t("sc_release_notes")}](${release_url})` : "")) +
            `\n\n${t(result.restarting ? "sc_force_restarting" : "sc_force_restart_hint")}`,
            "assistant"
          );
          this._checkUpdateBadge();
          if (result.restarting) {
            await new Promise((r) => setTimeout(r, 1500));
            this._showRestartOverlay(latest_version);
          }
        } catch (err) {
          btn.textContent = t("cmd_confirm_execute"); btn.disabled = false;
          card.querySelector(".btn-cmd-cancel").disabled = false;
          this._setStatus(`${t("err_force_update_failed")}: ${err.message}`, "error");
        }
      },
    });
  }

  // ──── /dashboard ─────────────────────────────────────────────────

  _cmdDashboard(action, nameArg) {
    const t = this._t || ((k) => k);
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
        const label = match ? (match.title || match.url_path) : t("sc_dash_overview_default");
        this._buildCommandCard({
          icon: "📊", title: t("sc_dash_open_title"),
          detail: label,
          onConfirm: (card) => {
            this._openDashboard(urlPath);
            card.querySelector(".btn-cmd-execute").textContent = t("sc_opened");
          },
        });
        break;
      }
      case "close":
        this._closeEditor();
        this._showMsg(t("sc_dash_closed"));
        break;
      case "save":
        if (this._editorMode !== "dashboard") { this._showMsg(t("sc_dash_none_open")); return; }
        this._buildCommandCard({
          icon: "💾", title: t("sc_dash_save_title"),
          detail: this.shadowRoot.getElementById("dashboard-select")?.options[
            this.shadowRoot.getElementById("dashboard-select")?.selectedIndex]?.textContent || "",
          onConfirm: (card) => {
            this._saveDashboard().then(() => { card.querySelector(".btn-cmd-execute").textContent = t("ae_saved"); });
          },
        });
        break;
      case "new":
        this._buildCommandCard({
          icon: "＋", title: t("sc_dash_new_title"),
          detail: nameArg || t("sc_dash_new_detail"),
          onConfirm: () => this._createNewDashboard(),
        });
        break;
      case "delete": {
        const sel = this.shadowRoot.getElementById("dashboard-select");
        const urlPath = this._currentDashboardPath;
        const label = sel?.options[sel?.selectedIndex]?.textContent || urlPath || t("sc_none_paren");
        if (!urlPath) { this._showMsg(t("sc_dash_cannot_delete")); return; }
        this._buildCommandCard({
          icon: "🗑", title: t("sc_dash_delete_title"),
          detail: label, danger: true,
          warning: t("sc_dash_delete_warning"),
          onConfirm: async (card) => {
            try {
              const panels = this._hass.panels || {};
              const p = Object.values(panels).find((x) => x.url_path === urlPath);
              if (p) await this._hass.callWS({ type: "lovelace/dashboards/delete", dashboard_id: p.id || urlPath });
              this._closeEditor();
              card.querySelector(".btn-cmd-execute").textContent = t("sc_deleted");
              this._showMsg(t("sc_dash_deleted", { name: label }));
            } catch (err) {
              this._setStatus(t("sc_delete_failed", { msg: err.message }), "error");
              card.querySelector(".btn-cmd-execute").disabled = false;
            }
          },
        });
        break;
      }
      default:
        this._showMsg(t("sc_cmd_list", { cmd: "/dashboard", subs: "open [name], close, save, new, delete" }));
    }
  }

  // ──── /automation ────────────────────────────────────────────────

  _cmdAutomation(action, nameArg) {
    const t = this._t || ((k) => k);
    switch (action) {
      case "open": {
        const state = this._findEntity("automation", nameArg);
        if (!state) { this._showMsg(t("sc_auto_not_found_hint", { name: nameArg })); return; }
        this._openEditor(state.entity_id);
        break;
      }
      case "close":
        this._closeEditor();
        this._showMsg(t("sc_editor_closed"));
        break;
      case "save":
        if (!this._currentAutomationId) { this._showMsg(t("sc_auto_none_open")); return; }
        this._buildCommandCard({
          icon: "💾", title: t("sc_auto_save_title"),
          detail: this._currentAutomationId,
          onConfirm: (card) => {
            this._saveAutomation().then(() => { card.querySelector(".btn-cmd-execute").textContent = t("ae_saved"); });
          },
        });
        break;
      case "new":
        this._buildCommandCard({
          icon: "＋", title: t("sc_auto_new_title"),
          detail: t("sc_auto_new_detail"),
          onConfirm: (card) => {
            window.open("/config/automation/edit/new", "_blank");
            card.querySelector(".btn-cmd-execute").textContent = t("sc_opened");
          },
        });
        break;
      case "delete": {
        const state = this._findEntity("automation", nameArg);
        if (!state) { this._showMsg(t("sc_auto_not_found", { name: nameArg })); return; }
        const friendly = state.attributes.friendly_name || state.entity_id;
        const configId = state.attributes.id;
        this._buildCommandCard({
          icon: "🗑", title: t("sc_auto_delete_title"),
          detail: `${state.entity_id} — ${friendly}`,
          danger: true,
          warning: t("sc_auto_delete_warning"),
          onConfirm: async (card) => {
            try {
              await this._hass.callApi("DELETE", `config/automation/config/${configId}`);
              card.querySelector(".btn-cmd-execute").textContent = t("sc_deleted");
              this._showMsg(t("sc_auto_deleted", { name: friendly }));
            } catch (err) {
              this._setStatus(t("sc_delete_failed", { msg: err.message }), "error");
              card.querySelector(".btn-cmd-execute").disabled = false;
            }
          },
        });
        break;
      }
      default:
        this._showMsg(t("sc_cmd_list", { cmd: "/automation", subs: "open <name>, close, save, new, delete <name>" }));
    }
  }

  // ──── /script ────────────────────────────────────────────────────

  _cmdScript(action, nameArg) {
    const t = this._t || ((k) => k);
    switch (action) {
      case "open": {
        const state = this._findEntity("script", nameArg);
        if (!state) { this._showMsg(t("sc_script_not_found", { name: nameArg })); return; }
        this._openEditor(state.entity_id);
        break;
      }
      case "close":
        this._closeEditor();
        this._showMsg(t("sc_editor_closed"));
        break;
      case "save":
        this._buildCommandCard({
          icon: "💾", title: t("sc_script_save_title"),
          detail: this._currentAutomationId || t("sc_current_paren"),
          onConfirm: (card) => {
            this._saveAutomation().then(() => { card.querySelector(".btn-cmd-execute").textContent = t("ae_saved"); });
          },
        });
        break;
      case "new":
        this._buildCommandCard({
          icon: "＋", title: t("sc_script_new_title"),
          detail: t("sc_script_new_detail"),
          onConfirm: (card) => {
            window.open("/config/script/edit/new", "_blank");
            card.querySelector(".btn-cmd-execute").textContent = t("sc_opened");
          },
        });
        break;
      case "delete": {
        const state = this._findEntity("script", nameArg);
        if (!state) { this._showMsg(t("sc_script_not_found", { name: nameArg })); return; }
        const friendly = state.attributes.friendly_name || state.entity_id;
        const configId = state.entity_id.replace("script.", "");
        this._buildCommandCard({
          icon: "🗑", title: t("sc_script_delete_title"),
          detail: `${state.entity_id} — ${friendly}`,
          danger: true,
          warning: t("sc_script_delete_warning"),
          onConfirm: async (card) => {
            try {
              await this._hass.callApi("DELETE", `config/script/config/${configId}`);
              card.querySelector(".btn-cmd-execute").textContent = t("sc_deleted");
              this._showMsg(t("sc_script_deleted", { name: friendly }));
            } catch (err) {
              this._setStatus(t("sc_delete_failed", { msg: err.message }), "error");
              card.querySelector(".btn-cmd-execute").disabled = false;
            }
          },
        });
        break;
      }
      default:
        this._showMsg(t("sc_cmd_list", { cmd: "/script", subs: "open <name>, close, save, new, delete <name>" }));
    }
  }

  // ──── /blueprint ─────────────────────────────────────────────────

  _cmdBlueprint(action, nameArg) {
    const t = this._t || ((k) => k);
    switch (action) {
      case "open":
        if (nameArg) {
          // /blueprint open <path> — open blueprint in editor directly
          this._openBlueprint(nameArg);
        } else {
          this._buildCommandCard({
            icon: "🗺", title: t("sc_bp_browse_title"),
            detail: t("sc_bp_browse_detail"),
            onConfirm: (card) => {
              window.open("/config/blueprint", "_blank");
              card.querySelector(".btn-cmd-execute").textContent = t("sc_opened");
            },
          });
        }
        break;
      case "browse":
        this._buildCommandCard({
          icon: "🗺", title: t("sc_bp_browse_title"),
          detail: t("sc_bp_browse_detail"),
          onConfirm: (card) => {
            window.open("/config/blueprint", "_blank");
            card.querySelector(".btn-cmd-execute").textContent = t("sc_opened");
          },
        });
        break;
      default:
        this._showMsg(t("sc_bp_usage"));
    }
  }

  // ──── /area ──────────────────────────────────────────────────────

  _cmdArea(action, nameArg) {
    const t = this._t || ((k) => k);
    switch (action) {
      case "new":
      case "create": {
        const name = nameArg;
        if (!name) { this._showMsg(t("sc_usage", { usage: "/area new <name>" })); return; }
        this._buildCommandCard({
          icon: "＋", title: t("sc_area_create_title"),
          detail: name,
          onConfirm: async (card) => {
            try {
              await this._executeActions([{ type: "create_area", name }]);
              card.querySelector(".btn-cmd-execute").textContent = t("ae_created");
              this._showMsg(t("sc_area_created", { name }));
            } catch (err) {
              this._setStatus(t("sc_failed", { msg: err.message }), "error");
              card.querySelector(".btn-cmd-execute").disabled = false;
            }
          },
        });
        break;
      }
      case "delete": {
        if (!nameArg) { this._showMsg(t("sc_usage", { usage: "/area delete <name>" })); return; }
        // Find area by name
        this._buildCommandCard({
          icon: "🗑", title: t("sc_area_delete_title"),
          detail: nameArg,
          danger: true,
          warning: t("sc_area_delete_warning"),
          onConfirm: async (card) => {
            try {
              await this._executeActions([{ type: "delete_area", area_id: nameArg.toLowerCase().replace(/\s+/g, "_") }]);
              card.querySelector(".btn-cmd-execute").textContent = t("sc_deleted");
            } catch (err) {
              this._setStatus(t("sc_failed", { msg: err.message }), "error");
              card.querySelector(".btn-cmd-execute").disabled = false;
            }
          },
        });
        break;
      }
      case "rename": {
        const parts = nameArg.split(/\s+to\s+/i);
        if (parts.length < 2) { this._showMsg(t("sc_usage", { usage: "/area rename <old> to <new>" })); return; }
        const [oldName, newName] = parts;
        this._buildCommandCard({
          icon: "✏", title: t("sc_area_rename_title"),
          detail: `"${oldName}" → "${newName}"`,
          onConfirm: async (card) => {
            try {
              await this._executeActions([{
                type: "rename_area",
                area_id: oldName.trim().toLowerCase().replace(/\s+/g, "_"),
                name: newName.trim(),
              }]);
              card.querySelector(".btn-cmd-execute").textContent = t("sc_renamed");
            } catch (err) {
              this._setStatus(t("sc_failed", { msg: err.message }), "error");
              card.querySelector(".btn-cmd-execute").disabled = false;
            }
          },
        });
        break;
      }
      case "list": {
        const areaReg = Object.values(this._hass.areas || {});
        if (areaReg.length) {
          this._showMsg(t("sc_areas_header") + "\n" + areaReg.map((a) => `• ${a.name} (${a.area_id})`).join("\n"));
        } else {
          this._showMsg(t("sc_areas_none"));
        }
        break;
      }
      default:
        this._showMsg(t("sc_cmd_list", { cmd: "/area", subs: "new <name>, delete <name>, rename <old> to <new>, list" }));
    }
  }
};
