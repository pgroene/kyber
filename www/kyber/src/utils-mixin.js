export const UtilsMixin = (Base) => class extends Base {
  _escapeAttr(s) {
    if (s == null) return "";
    return String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/'/g, "&#39;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  _showMsg(text, role = "assistant") {
    this._appendMessage(text, role);
  }

  _escapeHTML(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
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

  _checkUpdateBadge() {
    const badge = this.shadowRoot?.getElementById("update-badge");
    const label = this.shadowRoot?.getElementById("update-badge-label");
    if (!badge) return;
    const updateEntity = Object.values(this._hass?.states || {}).find(
      (s) => s.entity_id?.startsWith("update.") &&
             (s.attributes?.title || s.entity_id || "").toLowerCase().includes("kyber")
    );
    const hasUpdate = updateEntity?.state === "on";
    badge.hidden = !hasUpdate;
    if (hasUpdate && label) {
      const installed = (updateEntity.attributes.installed_version || "").replace(/^v/i, "");
      const latest    = (updateEntity.attributes.latest_version    || "").replace(/^v/i, "");
      label.textContent = latest ? `→ v${latest}` : "Update available";
      badge.title = installed && latest
        ? `Kyber update: v${installed} → v${latest}\nClick to update`
        : `Kyber update available — click to install`;
      // Store versions for the popover
      badge.dataset.installed = installed;
      badge.dataset.latest    = latest;
    }
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

  /** Fetch the knowledge count from the backend and init the badge. */
  async _loadMemoryCount() {
    try {
      const token = this._hass?.auth?.data?.access_token;
      if (!token) return;
      const resp = await fetch("/api/kyber/knowledge", {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!resp.ok) return;
      const data = await resp.json();
      this._updateMemoryBadge((data.entries || []).length, false);
    } catch { /* non-fatal — badge stays at … */ }
  }

  /**
   * Update the memory badge count and optionally trigger the recall pulse.
   * @param {number|null} count    - total fact count (null = leave as-is)
   * @param {number}      recalled - number of facts recalled this turn (0 = no pulse)
   */
  _updateMemoryBadge(count, recalled = 0) {
    if (count != null) this._memoryCount = count;
    const badge = this.shadowRoot?.getElementById("memory-badge");
    const countEl = this.shadowRoot?.getElementById("memory-count");
    if (!badge || !countEl) return;
    const total = this._memoryCount != null ? String(this._memoryCount) : "…";
    countEl.textContent = recalled > 0 ? `${recalled}/${total}` : total;
    if (recalled) {
      // Force animation restart even if class is already present
      badge.classList.remove("memory-badge--recalled");
      void badge.offsetWidth; // reflow
      badge.classList.add("memory-badge--recalled");
      clearTimeout(this._memRecallTimeout);
      // 2 iterations × 1.5s + small buffer
      this._memRecallTimeout = setTimeout(
        () => badge.classList.remove("memory-badge--recalled"),
        3200,
      );
    }
  }

  /** Show or hide the memory popover, positioning it below the badge. */
  _toggleMemoryPopover() {
    const popover = this.shadowRoot?.getElementById("memory-popover");
    const badge = this.shadowRoot?.getElementById("memory-badge");
    if (!popover || !badge) return;
    if (!popover.hasAttribute("hidden")) {
      this._closeMemoryPopover();
      return;
    }
    // Position using fixed coords so overflow:hidden on .chat-pane doesn't clip it
    const rect = badge.getBoundingClientRect();
    popover.style.top = `${rect.bottom + 4}px`;
    popover.style.left = `${rect.left}px`;
    popover.removeAttribute("hidden");
    this._renderMemoryPopoverContent();
    // Close when user clicks outside (composedPath handles shadow DOM)
    const closeHandler = (e) => {
      const path = e.composedPath ? e.composedPath() : [];
      if (!path.includes(badge) && !path.includes(popover)) {
        this._closeMemoryPopover();
        document.removeEventListener("click", closeHandler, true);
      }
    };
    this._memPopoverCloseHandler = closeHandler;
    setTimeout(() => document.addEventListener("click", closeHandler, true), 0);
  }

  _closeMemoryPopover() {
    const popover = this.shadowRoot?.getElementById("memory-popover");
    if (popover) popover.setAttribute("hidden", "");
    if (this._memPopoverCloseHandler) {
      document.removeEventListener("click", this._memPopoverCloseHandler, true);
      this._memPopoverCloseHandler = null;
    }
  }

  /** Populate the popover body with the knowledge recalled this turn (or a fallback). */
  _renderMemoryPopoverContent() {
    const body = this.shadowRoot?.getElementById("memory-popover-body");
    if (!body) return;
    const recalled = this._lastTurnMeta?.knowledge_used || [];
    if (recalled.length === 0) {
      body.innerHTML = `<span style="color:var(--secondary-text-color,#888);font-size:11px">${this._t ? this._t("memory_popover_empty") : "No facts recalled this turn."}</span>`;
      return;
    }
    body.innerHTML = recalled
      .map(
        (e) => `
        <div class="memory-popover-entry">
          <span class="mem-cat">${this._escapeHtml(e.category || "general")}</span>
          ${e.subject ? ` · <strong>${this._escapeHtml(e.subject)}</strong>` : ""}
          <div>${this._escapeHtml((e.content || "").slice(0, 140))}${(e.content || "").length > 140 ? "…" : ""}</div>
        </div>`,
      )
      .join("");
  }

  /** Full-panel overlay shown while HA is restarting. Polls until HA is back, then reloads. */
  _showRestartOverlay(version = "") {
    // Remove any existing overlay
    const existing = this.shadowRoot?.getElementById("restart-overlay");
    if (existing) existing.remove();

    const t = this._t || ((k) => k);
    const overlay = document.createElement("div");
    overlay.id = "restart-overlay";
    overlay.className = "restart-overlay";
    overlay.innerHTML = `
      <div class="restart-logo">🏠</div>
      <div class="restart-title">Kyber${version ? ` v${version}` : ""}</div>
      <div class="restart-subtitle">${t("restart_title")}<br>${t("restart_subtitle")}</div>
      <div class="restart-progress"><div class="restart-progress-bar"></div></div>
      <div class="restart-dots"><span></span><span></span><span></span></div>
      <div class="restart-status" id="restart-status-text">${t("restart_waiting")}</div>
    `;

    // Attach to shadow root container so it covers the whole panel
    const container = this.shadowRoot?.querySelector(".container") || this.shadowRoot;
    if (!container) return;
    container.appendChild(overlay);

    // Poll HA — once it responds, reload
    let attempts = 0;
    const maxAttempts = 120; // ~4 minutes
    const statusEl = overlay.querySelector("#restart-status-text");

    const poll = async () => {
      if (!this.shadowRoot?.getElementById("restart-overlay")) return; // removed externally
      attempts++;
      if (attempts > maxAttempts) {
        if (statusEl) statusEl.textContent = t("restart_slow");
        return;
      }
      try {
        await this._hass.callApi("GET", "kyber/ping");
        if (statusEl) statusEl.textContent = t("restart_back");
        const bar = overlay.querySelector(".restart-progress-bar");
        if (bar) { bar.style.animation = "none"; bar.style.width = "100%"; }
        setTimeout(() => window.location.reload(), 800);
      } catch {
        const elapsed = Math.round(attempts * 2);
        if (statusEl) statusEl.textContent = `${t("restart_waiting")} (${elapsed}s)`;
        setTimeout(poll, 2000);
      }
    };

    // Give HA 4 seconds to start shutting down before polling
    setTimeout(poll, 4000);
  }
};
