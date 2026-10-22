export const DebugMixin = (Base) => class extends Base {
  _toggleDebugPane(force) {
    const pane = this.shadowRoot.getElementById("debug-pane");
    if (!pane) return;
    const wantOpen = force === undefined ? pane.hasAttribute("hidden") : !!force;
    if (wantOpen) {
      pane.removeAttribute("hidden");
      this._debugTab = this._debugTab || "last_turn";
      this._renderDebugTab(this._debugTab);
      try { localStorage.setItem("kyber_debug_open", "1"); } catch (e) { /* */ }
    } else {
      pane.setAttribute("hidden", "");
      try { localStorage.setItem("kyber_debug_open", "0"); } catch (e) { /* */ }
    }
  }

  async _renderDebugTab(tab) {
    const t = this._t || ((k) => k);
    const body = this.shadowRoot.getElementById("debug-body");
    if (!body) return;
    // Persist open/closed state keyed by "tab:sid" so it survives tab switches
    // and background re-renders triggered by AI turns.
    if (!this._debugSectionOpenState) this._debugSectionOpenState = {};
    const prevTab = this._debugTab;
    if (prevTab) {
      body.querySelectorAll("details[data-sid]").forEach((d) => {
        this._debugSectionOpenState[`${prevTab}:${d.dataset.sid}`] = d.open;
      });
    }
    this._debugTab = tab;
    body.innerHTML = `<em>${this._t ? this._t("debug_loading") : "Loading…"}</em>`;
    try {
      if (tab === "memory") {
        await this._renderDebugMemory(body);
      } else if (tab === "last_turn") {
        await this._renderDebugLastTurn(body);
      } else if (tab === "status") {
        await this._renderDebugStatus(body);
      } else if (tab === "logs") {
        await this._renderDebugLogs(body);
      } else if (tab === "tests") {
        await this._renderDebugTests(body);
      } else if (tab === "mcp") {
        await this._renderDebugMcp(body);
      }
    } catch (err) {
      body.innerHTML = `<div class="debug-error">${t("dbg_error", { msg: this._escapeHtml(err.message) })}</div>`;
    }
    // Restore persisted open/closed state for this tab
    body.querySelectorAll("details[data-sid]").forEach((d) => {
      const key = `${tab}:${d.dataset.sid}`;
      if (key in this._debugSectionOpenState) d.open = this._debugSectionOpenState[key];
    });
  }

  async _renderDebugMemory(body) {
    const t = this._t || ((k) => k);
    const resp = await this._hass.fetchWithAuth("/api/kyber/knowledge");
    if (!resp.ok) throw new Error(t("dbg_err_fetch_knowledge", { status: resp.status }));
    const data = await resp.json();
    const entries = data.entries || [];
    const categories = data.categories || [];
    let filtered = (this._debugMemFilter || "all") === "review"
      ? entries.filter((e) => e.needs_review)
      : entries;
    const textQ = (this._debugMemText || "").toLowerCase().trim();
    if (textQ) {
      filtered = filtered.filter((e) => {
        const blob = [e.content, e.subject, ...(e.tags || [])].join(" ").toLowerCase();
        return blob.includes(textQ);
      });
    }
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

    // Build review queue: needs_review entries not currently skipped
    const reviewQueue = this._buildReviewQueue(entries);

    body.innerHTML = `
      ${reviewQueue.length > 0 ? this._renderReviewCardHTML(reviewQueue, entries) : ""}
      <div class="debug-stats">
        ${t("dbg_mem_stats", { n: entries.length, count: `<strong>${entries.length}</strong>`, review: reviewCount })} · ${catBadges}
      </div>
      <div class="debug-toolbar">
        <label>${t("dbg_filter")}
          <select id="dbg-mem-filter">
            <option value="all" ${(this._debugMemFilter||'all')==='all'?'selected':''}>${t("dbg_all")}</option>
            <option value="review" ${this._debugMemFilter==='review'?'selected':''}>${t("dbg_mem_filter_review")}</option>
          </select>
        </label>
        <label>${t("dbg_sort")}
          <select id="dbg-mem-sort">
            <option value="updated" ${(this._debugMemSort||'updated')==='updated'?'selected':''}>${t("dbg_sort_recent")}</option>
            <option value="hits" ${this._debugMemSort==='hits'?'selected':''}>${t("dbg_sort_hits")}</option>
            <option value="confidence" ${this._debugMemSort==='confidence'?'selected':''}>${t("dbg_sort_conf_low")}</option>
            <option value="rating" ${this._debugMemSort==='rating'?'selected':''}>${t("dbg_sort_rating")}</option>
          </select>
        </label>
        <input type="text" id="dbg-mem-text" placeholder="${t("dbg_filter_text")}" value="${this._escapeAttr(this._debugMemText||'')}" style="padding:4px 8px;border:1px solid var(--divider-color,#ccc);border-radius:4px;font-size:0.88em;min-width:140px">
        <button id="dbg-mem-add">${t("dbg_mem_add")}</button>
        <button id="dbg-mem-analyze">${t("dbg_mem_analyze")}</button>
        <button id="dbg-mem-deep-analyze">${t("dbg_deep_start")}</button>
        <label style="display:flex;align-items:center;gap:4px;font-size:0.85em">
          <input type="checkbox" id="dbg-deep-force"> ${t("dbg_mem_reanalyze_all")}
        </label>
        <button id="dbg-mem-purge" style="color:#c00">${t("dbg_purge_title")}</button>
      </div>
      <div id="dbg-deep-status" style="display:none;margin:6px 0;padding:8px 10px;border-radius:6px;background:var(--secondary-background-color,#f0f0f0);font-size:0.88em;line-height:1.6"></div>
      <div class="kn-list">${filtered.map((e) => this._renderKnowledgeRow(e, categories)).join("")}</div>
    `;

    if (reviewQueue.length > 0) this._wireReviewCard(body, reviewQueue, entries, categories);
    body.querySelector("#dbg-mem-filter").addEventListener("change", (e) => {
      this._debugMemFilter = e.target.value;
      this._renderDebugTab("memory");
    });
    body.querySelector("#dbg-mem-sort").addEventListener("change", (e) => {
      this._debugMemSort = e.target.value;
      this._renderDebugTab("memory");
    });
    body.querySelector("#dbg-mem-text").addEventListener("input", (e) => {
      this._debugMemText = e.target.value;
      this._renderDebugTab("memory");
    });
    body.querySelector("#dbg-mem-add").addEventListener("click", () => this._showKnowledgeEditor(null, categories, null));
    body.querySelector("#dbg-mem-analyze").addEventListener("click", async () => {
      this._toggleDebugPane(false);
      await this._handleKnowledgeCommand("analyze");
    });

    // Deep analysis — start background job and poll for progress
    body.querySelector("#dbg-mem-deep-analyze").addEventListener("click", async () => {
      const force = body.querySelector("#dbg-deep-force")?.checked ?? false;
      const r = await this._hass.fetchWithAuth("/api/kyber/knowledge/analyze_deep", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ background: true, runs: 10, limit: 5, force }),
      });
      const j = await r.json();
      if (!r.ok || (j.status !== "started" && j.status !== "already_running")) {
        alert(t("dbg_deep_start_failed", { msg: j.message || r.statusText }));
        return;
      }
      this._startDeepAnalysisPolling(body);
    });

    body.querySelector("#dbg-mem-purge").addEventListener("click", () => {
      this._renderPurgeFacts(body).catch((err) => {
        body.innerHTML = `<div class="debug-error">${t("dbg_purge_panel_error", { msg: this._escapeHtml(err.message) })}</div>`;
      });
    });

    // Show status if a job is already running / recently finished
    this._refreshDeepAnalysisStatus(body);
    this._wireKnowledgeRowEvents(body, filtered, categories);
  }

  // ── Review flow ────────────────────────────────────────────────────────────

  _reviewSkipKey() { return "kyber_review_skip_v1"; }
  _reviewSkipDaysKey() { return "kyber_review_skip_days"; }
  _reviewRulesKey() { return "kyber_review_rules_v1"; }

  _getLocalStorage() {
    try {
      if (typeof globalThis.localStorage !== "undefined") return globalThis.localStorage;
      if (typeof window !== "undefined" && window.localStorage) return window.localStorage;
    } catch {
      // Ignore storage access errors in non-browser test environments.
    }
    return null;
  }

  _getReviewSkipDays() {
    const stored = this._getLocalStorage()?.getItem(this._reviewSkipDaysKey());
    return stored ? parseInt(stored, 10) : 7;
  }

  _getReviewRules() {
    try {
      const raw = this._getLocalStorage()?.getItem(this._reviewRulesKey());
      const defaults = { area_assignment: "review", label_assignment: "review", knowledge: "review" };
      return raw ? { ...defaults, ...JSON.parse(raw) } : defaults;
    } catch { return { area_assignment: "review", label_assignment: "review", knowledge: "review" }; }
  }

  _setReviewRule(type, mode) {
    const rules = this._getReviewRules();
    rules[type] = mode;
    this._getLocalStorage()?.setItem(this._reviewRulesKey(), JSON.stringify(rules));
  }

  _reviewTypeMeta(type) {
    const t = this._t || ((k) => k);
    if (type === "area_assignment") return { icon: "🏠", label: t("dbg_rv_type_area") };
    if (type === "label_assignment") return { icon: "🏷", label: t("dbg_rv_type_label") };
    return { icon: "🧠", label: t("dbg_rv_type_knowledge") };
  }

  _reviewTypeForEntry(entry) {
    if (entry.category === "proposal") return entry.proposal_type || "knowledge";
    return "knowledge";
  }

  _getSkippedIds() {
    try {
      const raw = this._getLocalStorage()?.getItem(this._reviewSkipKey());
      if (!raw) return {};
      return JSON.parse(raw);
    } catch { return {}; }
  }

  _setSkippedIds(map) {
    this._getLocalStorage()?.setItem(this._reviewSkipKey(), JSON.stringify(map));
  }

  _skipEntry(id) {
    const map = this._getSkippedIds();
    const days = this._getReviewSkipDays();
    map[id] = Date.now() + days * 86400_000;
    this._setSkippedIds(map);
  }

  _isSkipped(id) {
    const map = this._getSkippedIds();
    const expiry = map[id];
    if (!expiry) return false;
    if (Date.now() > expiry) {
      delete map[id];
      this._setSkippedIds(map);
      return false;
    }
    return true;
  }

  _buildReviewQueue(entries) {
    return entries.filter((e) => e.needs_review && !this._isSkipped(e.id));
  }

  _renderRuleBadgesHTML(rules) {
    const t = this._t || ((k) => k);
    return Object.entries(rules)
      .filter(([, mode]) => mode !== "review")
      .map(([type, mode]) => {
        const { icon, label } = this._reviewTypeMeta(type);
        const cls = mode === "auto" ? "rv-badge--auto" : "rv-badge--reject";
        const modeLabel = mode === "auto" ? t("dbg_rv_mode_auto") : t("dbg_rv_mode_reject");
        return `<span class="rv-badge ${cls}" data-badge-type="${type}" title="${t("dbg_rv_badge_reset", { label })}">${icon} ${modeLabel} ×</span>`;
      }).join("");
  }

  _renderReviewCardHTML(queue, allEntries) {
    const t = this._t || ((k) => k);
    const idx = Math.min(this._reviewIdx || 0, queue.length - 1);
    const entry = queue[idx];
    const total = queue.length;
    const skipDays = this._getReviewSkipDays();
    const pct = Math.round((idx / total) * 100);
    const rules = this._getReviewRules();
    const entryType = this._reviewTypeForEntry(entry);
    const { icon, label } = this._reviewTypeMeta(entryType);

    const isProposal = entry.category === "proposal";
    let cardContent;
    if (isProposal) {
      const entityName = this._escapeHtml(entry.entity_name || entry.subject || "");
      const areaName = this._escapeHtml(entry.area_name || "");
      const labelName = this._escapeHtml(entry.label_name || "");
      const entityId = this._escapeHtml(entry.subject || "");
      const proposalType = entry.proposal_type || entryType;
      const proposalIcon = proposalType === "area_assignment" ? "📍" : "🏷";
      const action = proposalType === "area_assignment"
        ? t("dbg_rv_assign_area", { entity: `<strong>${entityName}</strong>`, area: `<strong>${areaName}</strong>` })
        : t("dbg_rv_assign_label", { label: `<strong>${labelName}</strong>`, entity: `<strong>${entityName}</strong>` });
      // Exactly the fact text the backend stores on approval (KyberProposalApproveView).
      const memory = proposalType === "area_assignment"
        ? `${entityName} (${entityId}) is in the area '${areaName}'.`
        : `${entityName} (${entityId}) has the label '${labelName}'.`;
      cardContent = `
        <div class="review-flow-proposal-icon">${proposalIcon}</div>
        <div class="review-flow-proposal-action">${action}</div>
        <div class="review-flow-proposal-entity">${entityId}</div>
        <div class="review-flow-proposal-memory">
          <span class="review-flow-memory-label">${t("dbg_rv_memory_label")}</span>
          ${memory}
        </div>`;
    } else if (entry.category === "entity_alias") {
      // subject = alias term the user might say; content = entity_id it maps to.
      // Show the alias text prominently — that's what's being approved/rejected.
      const aliasText = this._escapeHtml(entry.subject || "");
      const entityId = entry.content || "";
      const conf = entry.confidence != null ? ` · ${Math.round(entry.confidence * 100)}%` : "";
      const prov = entry.provenance ? ` · ${this._escapeHtml(entry.provenance)}` : "";
      // Enrich with entity friendly name + area from hass.states if available
      const state = this._hass?.states?.[entityId];
      const fname = state?.attributes?.friendly_name;
      const areaId = state?.attributes?.area_id;
      const entityLabel = fname
        ? `${this._escapeHtml(fname)} <span class="rv-entity-id">(${this._escapeHtml(entityId)})</span>`
        : `<span class="rv-entity-id">${this._escapeHtml(entityId)}</span>`;
      cardContent = `
        <div class="rv-alias-question">${t("dbg_rv_alias_question")}</div>
        <div class="rv-alias-term">"${aliasText}"</div>
        <div class="rv-alias-arrow">→ ${entityLabel}</div>
        <div class="rv-meta">entity_alias${conf}${prov}</div>`;
    } else {
      const conf = entry.confidence != null ? ` · ${Math.round(entry.confidence * 100)}%` : "";
      const subj = entry.subject ? ` · ${this._escapeHtml(entry.subject)}` : "";
      const prov = entry.provenance ? ` · ${this._escapeHtml(entry.provenance)}` : "";
      cardContent = `<div class="rv-content">${this._escapeHtml(entry.content || "")}</div>
        <div class="rv-meta">${this._escapeHtml(entry.category || "general")}${subj}${conf}${prov}</div>`;
    }

    const badges = this._renderRuleBadgesHTML(rules);

    return `
      <div class="rv-wrap" id="review-flow">
        <div class="rv-head">
          <span class="rv-title">${t("dbg_rv_title")}</span>
          <span class="rv-prog">${idx + 1} / ${total}</span>
          <div class="rv-bar"><div class="rv-bar-fill" style="width:${pct}%"></div></div>
          ${badges}
        </div>
        <div class="rv-card">${cardContent}</div>
        <div class="rv-actions">
          <button class="rv-btn rv-btn-approve" id="review-approve">${t("dbg_rv_approve")}</button>
          <button class="rv-btn rv-btn-reject" id="review-reject">${t("dbg_rv_reject")}</button>
          <div class="rv-skip-group">
            <button class="rv-btn rv-btn-skip" id="review-skip">${t("dbg_rv_skip")}</button>
            <label class="rv-skip-days">
              ${t("dbg_rv_hide_for_days", { input: `<input type="number" id="review-skip-days" min="1" max="365" value="${skipDays}" style="width:36px;padding:1px 3px">` })}
            </label>
          </div>
        </div>
        <div class="rv-bulk">
          ${t("dbg_rv_for_all", { label })}
          <button class="rv-bulk-btn rv-bulk-approve" data-bulk-type="${entryType}">${t("dbg_rv_approve_all")}</button>
          <button class="rv-bulk-btn rv-bulk-reject" data-bulk-type="${entryType}">${t("dbg_rv_reject_all")}</button>
        </div>
      </div>`;
  }

  async _applyBulkRule(type, mode, queue, allEntries, container, onDone) {
    const targets = queue.filter((e) => this._reviewTypeForEntry(e) === type);
    await Promise.all(targets.map((e) => {
      if (mode === "auto") {
        if (e.category === "proposal") {
          return this._hass.fetchWithAuth("/api/kyber/proposals/approve", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ entry_id: e.id }),
          });
        }
        return this._hass.fetchWithAuth("/api/kyber/knowledge/feedback", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ rating: 5, knowledge_ids: [e.id], auto: true }),
        });
      }
      return this._hass.fetchWithAuth(`/api/kyber/knowledge?id=${encodeURIComponent(e.id)}`, {
        method: "DELETE",
      });
    }));
    // Remove processed entries from queue in-place
    for (let i = queue.length - 1; i >= 0; i--) {
      if (this._reviewTypeForEntry(queue[i]) === type) queue.splice(i, 1);
    }
    this._reviewIdx = 0;
    this._redrawReviewFlow(container, queue, allEntries, onDone);
  }

  _wireReviewFlow(container, queue, allEntries, onDone) {
    const t = this._t || ((k) => k);
    const flow = container.querySelector("#review-flow");
    if (!flow) return;

    const redraw = () => this._redrawReviewFlow(container, queue, allEntries, onDone);

    flow.querySelector("#review-skip-days").addEventListener("change", (e) => {
      const v = parseInt(e.target.value, 10);
      if (v > 0) this._getLocalStorage()?.setItem(this._reviewSkipDaysKey(), String(v));
    });

    flow.querySelector("#review-approve").addEventListener("click", async () => {
      const idx = Math.min(this._reviewIdx || 0, queue.length - 1);
      const entry = queue[idx];
      if (entry.category === "proposal") {
        const resp = await this._hass.fetchWithAuth("/api/kyber/proposals/approve", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ entry_id: entry.id }),
        });
        if (!resp.ok) {
          const err = await resp.json().catch(() => ({}));
          this._setStatus(t("dbg_failed", { msg: err.message || resp.statusText }), "error");
          return;
        }
        const result = await resp.json();
        this._setStatus(`✓ ${result.memory || t("dbg_rv_approved")}`, "ok");
      } else {
        const resp = await this._hass.fetchWithAuth("/api/kyber/knowledge/feedback", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ rating: 5, knowledge_ids: [entry.id], auto: true }),
        });
        if (!resp.ok) {
          const err = await resp.json().catch(() => ({}));
          this._setStatus(t("dbg_failed", { msg: err.message || resp.statusText }), "error");
          return;
        }
      }
      queue.splice(idx, 1);
      this._reviewIdx = Math.min(idx, queue.length - 1);
      redraw();
    });

    flow.querySelector("#review-reject").addEventListener("click", async () => {
      const idx = Math.min(this._reviewIdx || 0, queue.length - 1);
      const entry = queue[idx];
      if (!confirm(t("dbg_rv_delete_confirm", { content: entry.content }))) return;
      await this._hass.fetchWithAuth(`/api/kyber/knowledge?id=${encodeURIComponent(entry.id)}`, {
        method: "DELETE",
      });
      queue.splice(idx, 1);
      this._reviewIdx = Math.min(idx, queue.length - 1);
      redraw();
    });

    flow.querySelector("#review-skip").addEventListener("click", () => {
      const idx = Math.min(this._reviewIdx || 0, queue.length - 1);
      const entry = queue[idx];
      this._skipEntry(entry.id);
      queue.splice(idx, 1);
      this._reviewIdx = Math.min(idx, queue.length - 1);
      redraw();
    });

    flow.querySelectorAll(".rv-bulk-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const type = btn.dataset.bulkType;
        const mode = btn.classList.contains("rv-bulk-approve") ? "auto" : "reject";
        const { label } = this._reviewTypeMeta(type);
        const confirmKey = mode === "auto" ? "dbg_rv_bulk_confirm_approve" : "dbg_rv_bulk_confirm_reject";
        if (!confirm(t(confirmKey, { label }))) return;
        this._setReviewRule(type, mode);
        this._applyBulkRule(type, mode, queue, allEntries, container, onDone);
      });
    });

    flow.querySelectorAll(".rv-badge").forEach((badge) => {
      badge.addEventListener("click", () => {
        const type = badge.dataset.badgeType;
        this._setReviewRule(type, "review");
        redraw();
      });
    });
  }

  _redrawReviewFlow(container, queue, allEntries, onDone) {
    if (queue.length === 0) { onDone(); return; }
    const flow = container.querySelector("#review-flow");
    const tmp = document.createElement("div");
    tmp.innerHTML = this._renderReviewCardHTML(queue, allEntries);
    const newFlow = tmp.firstElementChild;
    if (flow) flow.replaceWith(newFlow);
    else container.appendChild(newFlow);
    this._wireReviewFlow(container, queue, allEntries, onDone);
  }

  // Thin wrappers — debug pane vs chat pane differ only in what happens when queue empties
  _wireReviewCard(body, queue, allEntries, categories) {
    this._wireReviewFlow(body, queue, allEntries, () => {
      this._reviewIdx = 0;
      this._renderDebugTab("memory");
    });
  }

  _refreshReviewCard(body, queue, allEntries, categories) {
    this._redrawReviewFlow(body, queue, allEntries, () => {
      this._reviewIdx = 0;
      this._renderDebugTab("memory");
    });
  }

  async _checkChatReviewQueue() {
    const container = this.shadowRoot && this.shadowRoot.getElementById("chat-review-queue");
    if (!container) return;
    try {
      const resp = await this._hass.fetchWithAuth("/api/kyber/knowledge");
      if (!resp.ok) return;
      const data = await resp.json();
      const entries = data.entries || [];
      const queue = this._buildReviewQueue(entries);
      if (queue.length === 0) { container.innerHTML = ""; return; }
      container.innerHTML = this._renderReviewCardHTML(queue, entries);
      this._wireReviewFlow(container, queue, entries, () => { container.innerHTML = ""; });
    } catch { /* silently fail — don't block chat */ }
  }

  _timeAgo(unixTs) {
    const t = this._t || ((k) => k);
    const secs = Math.floor(Date.now() / 1000) - unixTs;
    if (secs < 60) return t("dbg_ago_s", { n: secs });
    if (secs < 3600) return t("dbg_ago_m", { n: Math.floor(secs / 60) });
    if (secs < 86400) return t("dbg_ago_h", { n: Math.floor(secs / 3600) });
    return t("dbg_ago_d", { n: Math.floor(secs / 86400) });
  }

  async _renderPurgeFacts(body) {
    const t = this._t || ((k) => k);
    body.innerHTML = `<em>${t("dbg_purge_loading")}</em>`;
    const resp = await this._hass.fetchWithAuth("/api/kyber/knowledge");
    const data = await resp.json();
    this._purgeAllEntries = data.entries || [];
    this._purgeSelected = new Set();
    this._purgeSort = this._purgeSort || "updated";
    this._purgeText = this._purgeText || "";
    this._renderPurgeFacts_withData(body);
  }

  _renderPurgeFacts_withData(body) {
    const t = this._t || ((k) => k);
    const all = this._purgeAllEntries || [];
    const textQ = (this._purgeText || "").toLowerCase().trim();
    let filtered = all.filter((e) => {
      if (!textQ) return true;
      const blob = [e.content, e.subject, ...(e.tags || [])].join(" ").toLowerCase();
      return blob.includes(textQ);
    });
    const sort = this._purgeSort || "updated";
    filtered.sort((a, b) => {
      if (sort === "hits") return (b.hits || 0) - (a.hits || 0);
      if (sort === "confidence_asc") return (a.confidence || 0) - (b.confidence || 0);
      if (sort === "confidence_desc") return (b.confidence || 0) - (a.confidence || 0);
      if (sort === "rating") return (b.user_rating || 0) - (a.user_rating || 0);
      return (b.updated || 0) - (a.updated || 0);
    });
    const sel = this._purgeSelected;
    const selCount = filtered.filter((e) => sel.has(e.id)).length;

    // Group sources and categories for quick-select
    const sources = [...new Set(all.map((e) => e.source || "unknown"))].sort();
    const cats = [...new Set(all.map((e) => e.category || "general"))].sort();

    const rows = filtered.map((e) => {
      const checked = sel.has(e.id) ? "checked" : "";
      const conf = e.confidence != null ? `${Math.round(e.confidence * 100)}%` : "—";
      const stars = e.user_rating ? "★".repeat(e.user_rating) : "—";
      const ago = e.updated ? this._timeAgo(e.updated) : "";
      const src = this._escapeHtml(e.source || "");
      const cat = this._escapeHtml(e.category || "");
      return `
        <label class="purge-row${sel.has(e.id) ? " purge-row--sel" : ""}" style="display:flex;align-items:flex-start;gap:8px;padding:6px 4px;border-bottom:1px solid var(--divider-color,#eee);cursor:pointer">
          <input type="checkbox" class="purge-cb" data-id="${this._escapeAttr(e.id)}" ${checked} style="margin-top:3px;flex-shrink:0">
          <div style="flex:1;min-width:0">
            <div style="font-size:0.88em;line-height:1.4">${this._escapeHtml(e.content || "")}</div>
            <div style="font-size:0.78em;opacity:.65;margin-top:2px">
              <span class="kn-tag">${cat}</span>
              <span class="kn-tag">${src}</span>
              <span>${t("dbg_purge_conf", { conf })}</span> · <span>${stars}</span> · <span>${t("dbg_hits", { n: e.hits || 0 })}</span> · <span>${ago}</span>
            </div>
          </div>
        </label>`;
    }).join("");

    body.innerHTML = `
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap">
        <button id="purge-back" style="font-size:0.9em">${t("dbg_back")}</button>
        <strong style="font-size:1em">${t("dbg_purge_title")}</strong>
        <span style="font-size:0.85em;opacity:.7">${t("dbg_purge_total", { n: all.length })}</span>
      </div>

      <div class="debug-toolbar" style="margin-bottom:6px">
        <input type="text" id="purge-text" placeholder="${t("dbg_filter_text")}" value="${this._escapeAttr(this._purgeText||'')}"
          style="padding:4px 8px;border:1px solid var(--divider-color,#ccc);border-radius:4px;font-size:0.88em;min-width:150px">
        <label>${t("dbg_sort")}
          <select id="purge-sort">
            <option value="updated" ${sort==='updated'?'selected':''}>${t("dbg_sort_recent")}</option>
            <option value="hits" ${sort==='hits'?'selected':''}>${t("dbg_sort_hits")}</option>
            <option value="confidence_asc" ${sort==='confidence_asc'?'selected':''}>${t("dbg_sort_conf_low")}</option>
            <option value="confidence_desc" ${sort==='confidence_desc'?'selected':''}>${t("dbg_sort_conf_high")}</option>
            <option value="rating" ${sort==='rating'?'selected':''}>${t("dbg_sort_rating")}</option>
          </select>
        </label>
      </div>

      <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:6px;font-size:0.83em">
        <span style="opacity:.7">${t("dbg_purge_quick_select")}</span>
        ${sources.map((s) => {
          const n = all.filter((e) => e.source === s).length;
          return `<button class="qs-source" data-source="${this._escapeAttr(s)}" style="padding:2px 7px;font-size:0.9em">${this._escapeHtml(s)} (${n})</button>`;
        }).join("")}
        <button class="qs-low-conf" style="padding:2px 7px;font-size:0.9em">${this._escapeHtml(t("dbg_purge_low_conf"))}</button>
        <button id="purge-sel-all" style="padding:2px 7px;font-size:0.9em">${t("dbg_purge_select_all")}</button>
        <button id="purge-desel-all" style="padding:2px 7px;font-size:0.9em">${t("dbg_purge_deselect_all")}</button>
      </div>

      <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
        <button id="purge-do" style="background:#c00;color:#fff;padding:5px 14px;border-radius:4px;border:none;cursor:pointer;font-weight:600" ${selCount===0?'disabled':''}>
          ${t("dbg_purge_delete_selected", { n: selCount })}
        </button>
        <span id="purge-msg" style="font-size:0.85em;opacity:.8"></span>
      </div>

      <div id="purge-list" style="max-height:60vh;overflow-y:auto">${rows}</div>
    `;

    // Back
    body.querySelector("#purge-back").addEventListener("click", () => {
      this._purgeText = "";
      this._renderDebugTab("memory");
    });

    // Text filter
    body.querySelector("#purge-text").addEventListener("input", (ev) => {
      this._purgeText = ev.target.value;
      this._renderPurgeFacts_withData(body);
    });

    // Sort
    body.querySelector("#purge-sort").addEventListener("change", (ev) => {
      this._purgeSort = ev.target.value;
      this._renderPurgeFacts_withData(body);
    });

    // Checkboxes
    body.querySelectorAll(".purge-cb").forEach((cb) => {
      cb.addEventListener("change", () => {
        const id = cb.dataset.id;
        if (cb.checked) sel.add(id); else sel.delete(id);
        this._renderPurgeFacts_withData(body);
      });
    });

    // Quick-select by source
    body.querySelectorAll(".qs-source").forEach((btn) => {
      btn.addEventListener("click", () => {
        const src = btn.dataset.source;
        all.filter((e) => e.source === src).forEach((e) => sel.add(e.id));
        this._renderPurgeFacts_withData(body);
      });
    });

    // Quick-select low confidence
    body.querySelector(".qs-low-conf").addEventListener("click", () => {
      all.filter((e) => (e.confidence || 0) < 0.6).forEach((e) => sel.add(e.id));
      this._renderPurgeFacts_withData(body);
    });

    // Select / deselect all visible
    body.querySelector("#purge-sel-all").addEventListener("click", () => {
      filtered.forEach((e) => sel.add(e.id));
      this._renderPurgeFacts_withData(body);
    });
    body.querySelector("#purge-desel-all").addEventListener("click", () => {
      sel.clear();
      this._renderPurgeFacts_withData(body);
    });

    // Delete selected
    body.querySelector("#purge-do").addEventListener("click", () => this._doPurgeSelected(body, filtered));
  }

  async _doPurgeSelected(body, filtered) {
    const sel = this._purgeSelected;
    const ids = filtered.filter((e) => sel.has(e.id)).map((e) => e.id);
    if (!ids.length) return;
    const t = this._t || ((k) => k);
    const msg = body.querySelector("#purge-msg");
    const btn = body.querySelector("#purge-do");
    if (!confirm(t("dbg_purge_confirm", { n: ids.length }))) return;
    if (btn) btn.disabled = true;
    if (msg) msg.textContent = t("dbg_purge_deleting");
    try {
      const r = await this._hass.fetchWithAuth("/api/kyber/knowledge/purge", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.message || r.statusText);
      sel.clear();
      // Reload full list
      const resp2 = await this._hass.fetchWithAuth("/api/kyber/knowledge");
      const data2 = await resp2.json();
      this._purgeAllEntries = data2.entries || [];
      if (msg) msg.textContent = t("dbg_purge_deleted", { n: j.deleted });
      this._renderPurgeFacts_withData(body);
    } catch (err) {
      if (msg) msg.textContent = `❌ ${err.message}`;
      if (btn) btn.disabled = false;
    }
  }

  async _renderDebugLastTurn(body) {
    const t = this._t || ((k) => k);
    const resp = await this._hass.fetchWithAuth("/api/kyber/debug/last_turn");
    if (!resp.ok) throw new Error(t("dbg_err_fetch_last_turn", { status: resp.status }));
    const data = await resp.json();
    const snap = data.snapshot;
    if (!snap) {
      body.innerHTML = `<div class="debug-empty">${t("dbg_lt_empty")}</div>`;
      return;
    }
    const picked = snap.picked_knowledge || [];
    const toolRows = (snap.tool_log || []).map((tl) => `
      <tr>
        <td><code>${this._escapeHtml(tl.name || tl.tool || "?")}</code></td>
        <td class="dbg-mono">${this._escapeHtml(JSON.stringify(tl.args || tl.arguments || {}))}</td>
        <td>${tl.status === "error" ? "❌" : "✓"}</td>
        <td>${tl.ms ?? ""}</td>
      </tr>`).join("");
    const ts = snap.ts ? new Date(snap.ts * 1000).toLocaleTimeString() : "—";
    const knowledgeIds = (picked || []).map((p) => p.id).filter(Boolean);
    const hasKnowledge = knowledgeIds.length > 0;
    const autoNote = snap.auto_rating
      ? `<span class="tf-auto" title="${t("dbg_lt_auto_flag_title")}">${t("dbg_lt_auto_rated", { n: snap.auto_rating })}</span>`
      : "";
    const feedbackBar = `
      <div class="dbg-turn-feedback" id="dbg-turn-feedback" data-request-id="${this._escapeAttr(snap.request_id || "")}">
        <span class="tf-label">${t("dbg_lt_how_was")}</span>
        <button class="tf-btn tf-btn-rate tf-up" title="${t("dbg_lt_helpful_title")}" ${hasKnowledge ? "" : "disabled"}>${t("dbg_lt_helpful")}</button>
        <button class="tf-btn tf-btn-rate tf-down" title="${t("dbg_lt_not_helpful_title")}" ${hasKnowledge ? "" : "disabled"}>${t("dbg_lt_not_helpful")}</button>
        ${autoNote}
        <span class="tf-status"></span>
        <button class="tf-btn tf-bundle" title="${t("dbg_lt_bundle_title")}" ${snap.request_id ? "" : "disabled"}>${t("dbg_lt_bundle")}</button>
        <button class="tf-btn tf-bug-report" title="${t("dbg_lt_bug_report_title")}" ${snap.request_id ? "" : "disabled"}>${t("dbg_lt_bug_report")}</button>
        <button class="tf-btn tf-capture-test" title="${t("dbg_lt_capture_test_title")}" ${snap.request_id ? "" : "disabled"}>${t("dbg_lt_capture_test")}</button>
      </div>`;
    body.innerHTML = `
      ${feedbackBar}
      <div class="debug-stats">
        <strong>${t("dbg_lt_turn_at", { ts })}</strong> · ${snap.elapsed_ms ?? "?"} ms · ${t("dbg_lt_intent")} <code>${this._escapeHtml(snap.intent || "?")}</code>
        · ${t("dbg_lt_prompt")} ${t("dbg_chars_tokens", { chars: snap.char_count?.toLocaleString() ?? "?", tokens: snap.approx_tokens?.toLocaleString() ?? "?" })}
        · auto_rating: ${snap.auto_rating ? `⚠ ${snap.auto_rating}/5` : "—"}
      </div>
      <details class="debug-section" data-sid="user-prompt" open>
        <summary><strong>${t("dbg_lt_user_prompt")}</strong></summary>
        <pre class="dbg-pre">${this._escapeHtml(snap.user_prompt || "")}</pre>
      </details>
      <details class="debug-section" data-sid="knowledge" open>
        <summary><strong>${t("dbg_lt_knowledge_used", { n: picked.length })}</strong></summary>
        ${picked.length === 0 ? `<em>${t("dbg_lt_none_injected")}</em>` : '<div class="kn-list" id="dbg-picked-list"></div>'}
      </details>
      <details class="debug-section" data-sid="tool-calls">
        <summary><strong>${t("dbg_lt_tool_calls", { n: (snap.tool_log || []).length })}</strong></summary>
        ${toolRows ? `<table class="dbg-tools"><thead><tr><th>${t("dbg_col_tool")}</th><th>${t("dbg_col_args")}</th><th>${t("dbg_col_status")}</th><th>ms</th></tr></thead><tbody>${toolRows}</tbody></table>` : `<em>${t("dbg_lt_no_tool_calls")}</em>`}
      </details>
      <details class="debug-section" data-sid="system-prompt">
        <summary><strong>${t("dbg_lt_system_prompt")}</strong> ${t("dbg_lt_system_prompt_hint")}</summary>
        <pre class="dbg-pre">${this._escapeHtml(snap.expanded_prompt || "")}</pre>
      </details>
      <details class="debug-section" data-sid="response">
        <summary><strong>${t("dbg_lt_response_text")}</strong></summary>
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
      const ct = bar.querySelector(".tf-capture-test");
      if (ct && reqId) ct.addEventListener("click", () => this._openCaptureTestModal(snap, ct));
    }
    if (picked.length > 0) {
      const list = body.querySelector("#dbg-picked-list");
      // Fetch full entries so we get tags + feedback log for rendering
      const fullResp = await this._hass.fetchWithAuth("/api/kyber/knowledge");
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

  async _renderDebugStatus(body) {
    const t = this._t || ((k) => k);
    const resp = await this._hass.fetchWithAuth("/api/kyber/debug/status");
    this._noteAuthRejected(resp);
    if (!resp.ok) throw new Error(t("dbg_err_fetch_status", { status: resp.status }));
    const data = await resp.json();
    const k = data.knowledge || {};
    const lt = data.last_turn;
    const ep = data.explorer_progress || {};
    const ns = data.narrator_stats || {};
    const st = data.storage || {};
    const res = data.resources || {};

    const catRows = Object.entries(k.by_category || {}).map(([cat, n]) =>
      `<tr><td><code>${this._escapeHtml(cat)}</code></td><td>${n}</td></tr>`,
    ).join("");
    const epStatus = ep.status || "idle";
    const epPaused = epStatus === "paused_chat";
    const epRunning = epStatus === "phase1_summaries" || epStatus === "phase2_entities" || epStatus === "starting" || epStatus === "narrator" || epStatus === "deep_learning";
    const epDone = ep.done ?? 0;
    const epTotal = ep.total ?? 0;
    const epPct = epTotal > 0 ? Math.round((epDone / epTotal) * 100) : 0;
    const narratorDone = ep.narrator_done ?? 0;
    const narratorTotal = ep.narrator_total ?? 0;
    const deepDone = ep.deep_done ?? 0;
    const deepTotal = ep.deep_total ?? 0;
    const deepCurrent = ep.deep_current || "";
    const epLabel = epPaused
      ? (deepCurrent
        ? t("dbg_ep_paused_item", { done: deepDone, total: deepTotal, item: deepCurrent })
        : t("dbg_ep_paused", { done: deepDone, total: deepTotal }))
      : epStatus === "narrator"
      ? t("dbg_ep_narrator", { done: narratorDone, total: narratorTotal })
      : epStatus === "deep_learning"
        ? (deepCurrent
          ? t("dbg_ep_deep_item", { done: deepDone, total: deepTotal, item: deepCurrent })
          : t("dbg_ep_deep", { done: deepDone, total: deepTotal }))
        : epRunning
          ? (ep.phase === "summaries" ? t("dbg_ep_indexing_integrations", { status: epStatus }) : t("dbg_ep_indexing_entities", { done: epDone, total: epTotal, pct: epPct }))
          : epStatus === "done" ? t("dbg_ep_complete", { n: epDone })
          : t("dbg_ep_not_started");
    const epProgressBar = epTotal > 0
      ? `<progress value="${epDone}" max="${epTotal}" style="width:100%;margin-top:4px"></progress>` : "";
    const narratorProgressBar = narratorTotal > 0
      ? `<progress value="${narratorDone}" max="${narratorTotal}" style="width:100%;margin-top:4px"></progress>` : "";
    const deepProgressBar = deepTotal > 0
      ? `<progress value="${deepDone}" max="${deepTotal}" style="width:100%;margin-top:4px"></progress>` : "";

    // Narrator stats summary
    const nsTotal = ns.total ?? 0;
    const nsAccepted = (ns.accepted_first ?? 0) + (ns.accepted_retry ?? 0);
    const nsPct = nsTotal > 0 ? Math.round((nsAccepted / nsTotal) * 100) : 0;
    const nsLabel = nsTotal > 0
      ? t("dbg_ns_summary", { accepted: nsAccepted, pct: nsPct, fallback: ns.rejected ?? 0, errors: ns.errors ?? 0 })
      : t("dbg_not_yet_run");

    // Helpers for storage/resource display
    const fmtBytes = (b) => {
      if (b == null) return "—";
      if (b < 1024) return `${b} B`;
      if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
      return `${(b / (1024 * 1024)).toFixed(2)} MB`;
    };
    const fmtBuf = (n, max) => `${n} / ${max} (${max > 0 ? Math.round((n / max) * 100) : 0}%)`;

    body.innerHTML = `
      <h3>${t("dbg_st_h_runtime")}</h3>
      <table class="dbg-kv">
        <tr><th>${t("dbg_st_ai_task_entity")}</th><td><code>${this._escapeHtml(data.ai_task_entity || "—")}</code></td></tr>
        ${(data.ai_task_info && data.ai_task_info.friendly_name && data.ai_task_info.friendly_name !== data.ai_task_entity) ? `<tr><th>${t("dbg_st_display_name")}</th><td>${this._escapeHtml(data.ai_task_info.friendly_name)}</td></tr>` : ""}
        ${data.ai_task_info && data.ai_task_info.model ? `<tr><th>${t("dbg_st_model")}</th><td><code>${this._escapeHtml(data.ai_task_info.model)}</code> <a href="https://github.com/pgroene/kyber#choosing-a-model" target="_blank" rel="noopener" style="font-size:0.8em;margin-left:6px;opacity:0.7" title="${t("dbg_st_choose_model_title")}">${t("dbg_st_choose_model")}</a></td></tr>` : ""}
        ${data.ai_task_info && data.ai_task_info.server ? `<tr><th>${t("dbg_st_server")}</th><td><code>${this._escapeHtml(data.ai_task_info.server)}</code></td></tr>` : ""}
        <tr><th>${t("dbg_st_autopilot")}</th><td>${this._autopilot ? t("dbg_st_on") : t("dbg_st_off")}</td></tr>
        <tr><th>${t("dbg_st_session")}</th><td>${this._escapeHtml(this._sessionName || "—")}</td></tr>
        <tr><th>${t("dbg_st_tool_history_size")}</th><td>${data.tool_history_size}</td></tr>
      </table>
      <h3>${t("dbg_st_h_storage")}</h3>
      <table class="dbg-kv">
        ${st.total_bytes != null ? `<tr><th>${t("dbg_st_total_kyber_data")}</th><td><strong>${fmtBytes(st.total_bytes)}</strong></td></tr>` : ""}
        ${Object.entries(st.files || {}).sort((a,b) => (b[1]||0)-(a[1]||0)).map(([name, size]) =>
          `<tr><td style="padding-left:1.2em"><code>${this._escapeHtml(name)}</code></td><td>${fmtBytes(size)}</td></tr>`
        ).join("")}
        ${st.total_bytes == null ? `
          <tr><th>${t("dbg_st_knowledge_store")}</th><td>${fmtBytes(st.knowledge_file_bytes)}</td></tr>
          <tr><th>${t("dbg_st_chat_history")}</th><td>${fmtBytes(st.chat_history_file_bytes)}</td></tr>
        ` : ""}
        ${st.component_bytes != null ? `<tr><th>${t("dbg_st_component_code")}</th><td>${fmtBytes(st.component_bytes)}</td></tr>` : ""}
      </table>
      <h3>${t("dbg_st_h_resources")}</h3>
      <table class="dbg-kv">
        ${res.process_rss_bytes != null ? `<tr><th>${t("dbg_st_process_rss")}</th><td>${fmtBytes(res.process_rss_bytes)}</td></tr>` : ""}
        <tr><th>${t("dbg_st_debug_snapshots")}</th><td>${fmtBuf(res.snapshots_buffered ?? 0, res.snapshots_max ?? 50)}</td></tr>
        <tr><th>${t("dbg_st_global_log_buffer")}</th><td>${fmtBuf(res.global_log_entries ?? 0, res.global_log_max ?? 2000)}</td></tr>
        <tr><th>${t("dbg_st_tfidf_terms")}</th><td>${(res.tfidf_terms ?? 0).toLocaleString()}</td></tr>
        <tr><th>${t("dbg_st_knowledge_vectors")}</th><td>${(res.knowledge_vectors ?? 0).toLocaleString()}</td></tr>
      </table>
      <h3>${t("dbg_st_knowledge_store")}</h3>
      <table class="dbg-kv">
        <tr><th>${t("dbg_st_total_entries")}</th><td>${k.total ?? 0}</td></tr>
        <tr><th>${t("dbg_st_needs_review")}</th><td>${k.needs_review ?? 0}</td></tr>
        <tr><th>${t("dbg_st_total_hits")}</th><td>${k.total_hits ?? 0}</td></tr>
      </table>
      ${catRows ? `<h4>${t("dbg_st_h_by_category")}</h4><table class="dbg-kv">${catRows}</table>` : ""}
      <h3>${t("dbg_st_h_explorer")}</h3>
      <table class="dbg-kv">
        <tr><th>${t("dbg_st_status")}</th><td>${this._escapeHtml(epLabel)}</td></tr>
        ${ep.current_platform ? `<tr><th>${t("dbg_st_current")}</th><td><code>${this._escapeHtml(ep.current_platform)}</code></td></tr>` : ""}
        ${ep.started_at ? `<tr><th>${t("dbg_st_started")}</th><td>${new Date(ep.started_at * 1000).toLocaleTimeString()}</td></tr>` : ""}
      </table>
      ${epProgressBar}
      ${(epStatus === "narrator") ? narratorProgressBar : ""}
      ${(epStatus === "deep_learning" || epPaused) ? deepProgressBar : ""}
      <div style="margin:6px 0 12px">
        <button id="dbg-run-explorer" style="font-size:0.9em;padding:5px 14px" ${epRunning && epStatus !== "narrator" && epStatus !== "deep_learning" ? "disabled" : ""}>
          ${t("dbg_st_run_explorer")}
        </button>
      </div>
      <h3>${t("dbg_st_h_narrator")}</h3>
      <table class="dbg-kv">
        ${data.narrator_ai_task_entity ? `<tr><th>${t("dbg_st_ai_task_entity")}</th><td><code>${this._escapeHtml(data.narrator_ai_task_entity)}</code></td></tr>` : ""}
        ${(data.narrator_ai_task_info && data.narrator_ai_task_info.friendly_name && data.narrator_ai_task_info.friendly_name !== data.narrator_ai_task_entity) ? `<tr><th>${t("dbg_st_display_name")}</th><td>${this._escapeHtml(data.narrator_ai_task_info.friendly_name)}</td></tr>` : ""}
        ${data.narrator_ai_task_info && data.narrator_ai_task_info.model ? `<tr><th>${t("dbg_st_model")}</th><td><code>${this._escapeHtml(data.narrator_ai_task_info.model)}</code> <a href="https://github.com/pgroene/kyber/blob/main/docs/narrator-bench-report-2026-05.md" target="_blank" rel="noopener" style="font-size:0.8em;margin-left:6px;opacity:0.7" title="${t("dbg_st_bench_report_title")}">${t("dbg_st_bench_report")}</a></td></tr>` : ""}
        ${data.narrator_ai_task_info && data.narrator_ai_task_info.server ? `<tr><th>${t("dbg_st_server")}</th><td><code>${this._escapeHtml(data.narrator_ai_task_info.server)}</code></td></tr>` : ""}
        <tr><th>${t("dbg_st_status")}</th><td>${this._escapeHtml(nsLabel)}</td></tr>
        ${ns.last_run ? `<tr><th>${t("dbg_st_last_run")}</th><td>${this._escapeHtml(ns.last_run)}</td></tr>` : ""}
        ${nsTotal > 0 ? `
          <tr><th>${t("dbg_st_accepted_first")}</th><td>${ns.accepted_first ?? 0}</td></tr>
          <tr><th>${t("dbg_st_accepted_retry")}</th><td>${ns.accepted_retry ?? 0}</td></tr>
          <tr><th>${t("dbg_st_fallback")}</th><td>${ns.rejected ?? 0}</td></tr>
          <tr><th>${t("dbg_st_errors")}</th><td>${ns.errors ?? 0}</td></tr>
        ` : ""}
      </table>
      <div style="margin:6px 0 12px">
        <button id="dbg-run-narrator" style="font-size:0.9em;padding:5px 14px" ${epStatus === "narrator" ? "disabled" : ""}>
          ${t("dbg_st_run_narrator")}
        </button>
      </div>
      <h3>${t("dbg_st_h_deep")}</h3>
      ${(() => {
        const dj = data.deep_job || {};
        const djRunning = dj.running === true;
        const djLabel = djRunning
          ? t("dbg_dj_running", { run: dj.run ?? "?", runs: dj.runs ?? "?", item: dj.current_item || "…" })
          : epPaused
            ? t("dbg_dj_paused", { done: deepDone, total: deepTotal })
            : dj.last_result
            ? t("dbg_dj_last_run", { analyzed: dj.last_result.analyzed ?? 0, facts: dj.last_result.facts ?? 0, secs: dj.last_result.duration_s ?? "?" })
            : t("dbg_not_yet_run");
        return `
          <table class="dbg-kv">
            <tr><th>${t("dbg_st_status")}</th><td>${this._escapeHtml(djLabel)}</td></tr>
            ${dj.running ? `<tr><th>${t("dbg_st_progress")}</th><td>${t("dbg_dj_progress", { analyzed: dj.analyzed ?? 0, facts: dj.facts ?? 0, errors: dj.errors ?? 0 })}</td></tr>` : ""}
          </table>
          <div style="margin:6px 0 12px;display:flex;gap:8px;flex-wrap:wrap;align-items:center">
            <button id="dbg-run-deep" style="font-size:0.9em;padding:5px 14px" ${djRunning || epStatus === "deep_learning" || epPaused ? "disabled" : ""}>
              ${t("dbg_st_run_deep")}
            </button>
            <label style="font-size:0.85em;display:flex;align-items:center;gap:4px">
              <input type="number" id="dbg-deep-runs" value="3" min="1" max="20" style="width:44px;font-size:0.9em;padding:2px 4px"> ${t("dbg_passes")}
            </label>
            <label style="font-size:0.85em;display:flex;align-items:center;gap:4px">
              <input type="number" id="dbg-deep-limit" value="10" min="1" max="50" style="width:44px;font-size:0.9em;padding:2px 4px"> ${t("dbg_st_items_per_pass")}
            </label>
          </div>
        `;
      })()}
      <h3>${t("dbg_st_h_last_turn")}</h3>
      ${lt ? `
        <table class="dbg-kv">
          <tr><th>${t("dbg_st_when")}</th><td>${lt.ts ? new Date(lt.ts * 1000).toLocaleString() : "—"}</td></tr>
          <tr><th>${t("dbg_st_elapsed")}</th><td>${lt.elapsed_ms} ms</td></tr>
          <tr><th>${t("dbg_st_intent")}</th><td><code>${this._escapeHtml(lt.intent || "—")}</code></td></tr>
          <tr><th>${t("dbg_st_prompt_size")}</th><td>${t("dbg_chars_tokens", { chars: lt.char_count?.toLocaleString() ?? "?", tokens: lt.approx_tokens?.toLocaleString() ?? "?" })}</td></tr>
        </table>
        ${lt.request_id ? `
        <div style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap">
          <button id="dbg-download-bundle" style="font-size:0.9em;padding:6px 14px">
            ${t("dbg_st_download_bundle")}
          </button>
          <button id="dbg-open-bug-report" style="font-size:0.9em;padding:6px 14px">
            ${t("dbg_st_bug_report")}
          </button>
        </div>` : ""}
      ` : `<em>${t("dbg_st_no_turn")}</em>`}
      <h3>${t("dbg_st_h_export")}</h3>
      <p style="margin:4px 0 8px;font-size:0.88em;color:var(--secondary-text-color)">
        ${t("dbg_st_export_hint")}
      </p>
      <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center">
        <button id="dbg-export-home" style="font-size:0.9em;padding:6px 14px">
          ${t("dbg_st_export_home")}
        </button>
        <button id="dbg-export-memory" style="font-size:0.9em;padding:6px 14px">
          ${t("dbg_st_export_memory")}
        </button>
        <span id="dbg-export-status" style="font-size:0.85em;color:var(--secondary-text-color)"></span>
      </div>
    `;

    // Wire export buttons
    const exportBtn = body.querySelector("#dbg-export-home");
    if (exportBtn) {
      exportBtn.addEventListener("click", () => this._downloadHomeState(exportBtn));
    }
    const memBtn = body.querySelector("#dbg-export-memory");
    if (memBtn) {
      memBtn.addEventListener("click", () => this._downloadMemoryExport(memBtn));
    }

    // Wire last-turn debug bundle download + bug report
    const ltReqId = data.last_turn?.request_id;
    if (ltReqId) {
      const dlBtn = body.querySelector("#dbg-download-bundle");
      if (dlBtn) dlBtn.addEventListener("click", () => this._downloadDebugBundle(ltReqId, dlBtn));
      const brBtn = body.querySelector("#dbg-open-bug-report");
      if (brBtn) brBtn.addEventListener("click", () => this._openBugReportFlow(ltReqId, brBtn));
    }

    // Wire Run Now buttons
    const _runNow = async (btn, url, body_payload) => {
      if (!btn || btn.disabled) return;
      const origText = btn.textContent;
      btn.disabled = true;
      btn.textContent = t("dbg_run_starting");
      try {
        const resp = await this._hass.fetchWithAuth(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body_payload || {}),
        });
        const result = await resp.json();
        btn.textContent = result.status === "started" ? t("dbg_run_started") : result.status === "already_running" ? t("dbg_run_already_running") : result.status || t("dbg_run_done");
        setTimeout(() => {
          btn.textContent = origText;
          btn.disabled = false;
          const liveBody = this.shadowRoot?.getElementById("debug-body");
          if (liveBody) this._renderDebugStatus(liveBody);
        }, 2000);
      } catch (err) {
        btn.textContent = t("dbg_run_error");
        setTimeout(() => { btn.textContent = origText; btn.disabled = false; }, 2000);
      }
    };

    const runExplorerBtn = body.querySelector("#dbg-run-explorer");
    if (runExplorerBtn) {
      runExplorerBtn.addEventListener("click", () => _runNow(runExplorerBtn, "/api/kyber/explorer/run"));
    }
    const runNarratorBtn = body.querySelector("#dbg-run-narrator");
    if (runNarratorBtn) {
      runNarratorBtn.addEventListener("click", () => _runNow(runNarratorBtn, "/api/kyber/narrator/run"));
    }
    const runDeepBtn = body.querySelector("#dbg-run-deep");
    if (runDeepBtn) {
      runDeepBtn.addEventListener("click", () => {
        const runs = parseInt(body.querySelector("#dbg-deep-runs")?.value || "3", 10);
        const limit = parseInt(body.querySelector("#dbg-deep-limit")?.value || "10", 10);
        _runNow(runDeepBtn, "/api/kyber/knowledge/analyze_deep", { background: true, runs, limit });
      });
    }

    // Auto-refresh while explorer, narrator, or deep-analyzer is running/paused
    if (epRunning || epPaused) {
      if (!this._explorerStatusTimer) {
        this._explorerStatusTimer = setInterval(() => {
          if (!this._pollAllowed()) return;
          const liveBody = this.shadowRoot?.getElementById("debug-body");
          if (liveBody) this._renderDebugStatus(liveBody);
        }, 3000);
      }
    } else if (this._explorerStatusTimer) {
      clearInterval(this._explorerStatusTimer);
      this._explorerStatusTimer = null;
    }
  }

  async _renderDebugLogs(body) {
    const t = this._t || ((k) => k);
    const level = body.querySelector("#dbg-log-level")?.value || "";
    const url = `/api/kyber/debug/logs${level ? `?level=${level}` : ""}`;
    const resp = await this._hass.fetchWithAuth(url);
    if (!resp.ok) {
      body.innerHTML = `<em style="color:var(--error-color)">${t("dbg_logs_unavailable", { status: resp.status })}</em>`;
      return;
    }
    const data = await resp.json();
    const logs = data.logs || [];

    const LEVEL_COLOR = {
      DEBUG: "var(--secondary-text-color)",
      INFO: "var(--info-color, #2196F3)",
      WARNING: "var(--warning-color, #FF9800)",
      ERROR: "var(--error-color, #F44336)",
      CRITICAL: "var(--error-color, #F44336)",
    };

    const rows = logs.slice().reverse().map((r) => {
      const ts = r.ts ? new Date(r.ts * 1000).toLocaleTimeString(this._hass?.language || undefined, { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—";
      const color = LEVEL_COLOR[r.level] || "inherit";
      const logger = this._escapeHtml((r.logger || "").replace("custom_components.kyber.", "kyber."));
      const msg = this._escapeHtml(r.message || "");
      return `<tr>
        <td style="white-space:nowrap;color:var(--secondary-text-color);font-size:0.82em">${ts}</td>
        <td style="white-space:nowrap;font-weight:600;color:${color};font-size:0.82em">${this._escapeHtml(r.level || "")}</td>
        <td style="white-space:nowrap;color:var(--secondary-text-color);font-size:0.78em">${logger}</td>
        <td style="font-size:0.85em;word-break:break-word">${msg}</td>
      </tr>`;
    }).join("");

    body.innerHTML = `
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px">
        <select id="dbg-log-level" style="font-size:0.88em;padding:4px 8px">
          <option value=""${!level ? " selected" : ""}>${t("dbg_logs_all_levels")}</option>
          <option value="INFO"${level === "INFO" ? " selected" : ""}>INFO+</option>
          <option value="WARNING"${level === "WARNING" ? " selected" : ""}>WARNING+</option>
          <option value="ERROR"${level === "ERROR" ? " selected" : ""}>ERROR+</option>
        </select>
        <button id="dbg-log-refresh" style="font-size:0.88em;padding:4px 10px">${t("dbg_refresh")}</button>
        <button id="dbg-log-download" style="font-size:0.88em;padding:4px 10px">${t("dbg_logs_download")}</button>
        <button id="dbg-log-clear" style="font-size:0.88em;padding:4px 10px;color:var(--error-color)">${t("dbg_logs_clear")}</button>
        <span style="font-size:0.82em;color:var(--secondary-text-color)">${t("dbg_logs_records", { n: logs.length })}</span>
      </div>
      ${logs.length > 0 ? `
      <div style="overflow-x:auto;max-height:60vh">
        <table style="width:100%;border-collapse:collapse;font-family:monospace" id="dbg-log-table">
          <thead><tr style="font-size:0.78em;color:var(--secondary-text-color);border-bottom:1px solid var(--divider-color)">
            <th style="text-align:left;padding:2px 8px 4px 0">${t("dbg_col_time")}</th>
            <th style="text-align:left;padding:2px 8px 4px 0">${t("dbg_col_level")}</th>
            <th style="text-align:left;padding:2px 8px 4px 0">${t("dbg_col_logger")}</th>
            <th style="text-align:left;padding:2px 0 4px 0">${t("dbg_col_message")}</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>` : `<em style="color:var(--secondary-text-color)">${t("dbg_logs_empty")}</em>`}
    `;

    body.querySelector("#dbg-log-refresh")?.addEventListener("click", () => this._renderDebugLogs(body));
    body.querySelector("#dbg-log-clear")?.addEventListener("click", async () => {
      await this._hass.fetchWithAuth("/api/kyber/debug/logs", { method: "DELETE" });
      this._renderDebugLogs(body);
    });
    body.querySelector("#dbg-log-download")?.addEventListener("click", async () => {
      const lv = body.querySelector("#dbg-log-level")?.value || "";
      const dlUrl = `/api/kyber/debug/logs?format=txt${lv ? `&level=${lv}` : ""}`;
      const r = await this._hass.fetchWithAuth(dlUrl);
      const blob = await r.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "kyber-logs.txt";
      document.body.appendChild(a);
      a.click();
      a.remove();
    });
    body.querySelector("#dbg-log-level")?.addEventListener("change", () => this._renderDebugLogs(body));
  }

  async _downloadHomeState(btn) {
    const t = this._t || ((k) => k);
    const statusEl = btn.parentElement.querySelector("#dbg-export-status");
    const orig = btn.textContent;
    btn.disabled = true;
    btn.textContent = t("dbg_exporting");
    if (statusEl) statusEl.textContent = "";
    try {
      const resp = await this._hass.fetchWithAuth("/api/kyber/export/home-state");
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
      a.download = `kyber-home-state-${ts}.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      btn.textContent = t("dbg_downloaded");
      if (statusEl) statusEl.textContent = t("dbg_export_home_hint");
      setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 3000);
    } catch (err) {
      btn.textContent = `⚠ ${err.message}`;
      btn.disabled = false;
      if (statusEl) statusEl.textContent = "";
    }
  }

  async _downloadMemoryExport(btn) {
    const t = this._t || ((k) => k);
    const statusEl = btn.parentElement.querySelector("#dbg-export-status");
    const orig = btn.textContent;
    btn.disabled = true;
    btn.textContent = t("dbg_exporting");
    if (statusEl) statusEl.textContent = "";
    try {
      const resp = await this._hass.fetchWithAuth("/api/kyber/export/memory");
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
      a.download = `kyber-memory-${ts}.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      const counts = data.metadata?.triage_counts || {};
      btn.textContent = t("dbg_downloaded");
      if (statusEl) statusEl.textContent = t("dbg_export_memory_counts", { good: counts.good || 0, consider: counts.consider || 0, skip: counts.skip || 0 });
      setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 3000);
    } catch (err) {
      btn.textContent = `⚠ ${err.message}`;
      btn.disabled = false;
      if (statusEl) statusEl.textContent = "";
    }
  }

  _getDeepLearningRuns(root) {
    const val = parseInt(root.querySelector("select")?.value ?? "1", 10);
    return Math.min(10, Math.max(1, isNaN(val) ? 1 : val));
  }

  _startDeepAnalysisPolling(body) {
    if (this._deepPollTimer) clearInterval(this._deepPollTimer);
    this._deepPollTimer = setInterval(async () => {
      const alive = await this._refreshDeepAnalysisStatus(body);
      if (!alive) {
        clearInterval(this._deepPollTimer);
        this._deepPollTimer = null;
        this._renderDebugTab("memory");
      }
    }, 2000);
    this._refreshDeepAnalysisStatus(body);
  }

  async _refreshDeepAnalysisStatus(body) {
    const t = this._t || ((k) => k);
    const statusDiv = body?.querySelector?.("#dbg-deep-status");
    const btn = body?.querySelector?.("#dbg-mem-deep-analyze");
    if (!statusDiv || !this._pollAllowed()) return false;
    try {
      const r = await this._hass.fetchWithAuth("/api/kyber/knowledge/analyze_deep");
      if (this._noteAuthRejected(r) || !r.ok) return false;
      const data = await r.json();
      const job = data.job || {};
      const running = job.running === true;

      if (!running && !job.started_at) {
        statusDiv.style.display = "none";
        if (btn) btn.disabled = false;
        return false;
      }

      statusDiv.style.display = "block";
      if (running) {
        if (btn) { btn.disabled = true; btn.textContent = t("dbg_deep_running_btn"); }
        const elapsed = job.started_at ? Math.round(Date.now() / 1000 - job.started_at) : 0;
        statusDiv.innerHTML = `
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
            <span style="font-size:1.1em">🔄</span>
            <strong>${t("dbg_deep_running")}</strong>
            <span style="color:var(--secondary-text-color)">${elapsed}s</span>
          </div>
          <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;text-align:center">
            <div><div style="font-size:1.4em;font-weight:bold">${job.run || 0}/${job.runs || 0}</div><div style="font-size:0.8em;opacity:.7">${t("dbg_passes")}</div></div>
            <div><div style="font-size:1.4em;font-weight:bold">${job.analyzed || 0}</div><div style="font-size:0.8em;opacity:.7">${t("dbg_deep_analyzed")}</div></div>
            <div><div style="font-size:1.4em;font-weight:bold">${job.facts || 0}</div><div style="font-size:0.8em;opacity:.7">${t("dbg_deep_facts_stored")}</div></div>
          </div>
          ${job.current_item ? `<div style="margin-top:4px;font-size:0.8em;opacity:.6">📄 ${this._escapeHtml(job.current_item)}</div>` : ""}
          ${job.errors ? `<div style="color:#e44;font-size:0.8em">${t("dbg_deep_errors", { n: job.errors })}</div>` : ""}
        `;
        return true;
      } else {
        if (btn) { btn.disabled = false; btn.textContent = t("dbg_deep_start"); }
        const last = job.last_result || {};
        const dur = last.duration_s != null ? `${last.duration_s}s` : "";
        statusDiv.innerHTML = `
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
            <span style="font-size:1.1em">✅</span>
            <strong>${t("dbg_deep_last_complete")}</strong>
            ${dur ? `<span style="color:var(--secondary-text-color)">${dur}</span>` : ""}
          </div>
          <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;text-align:center">
            <div><div style="font-size:1.4em;font-weight:bold">${last.runs_completed || 0}</div><div style="font-size:0.8em;opacity:.7">${t("dbg_passes")}</div></div>
            <div><div style="font-size:1.4em;font-weight:bold">${last.analyzed || 0}</div><div style="font-size:0.8em;opacity:.7">${t("dbg_deep_analyzed")}</div></div>
            <div><div style="font-size:1.4em;font-weight:bold">${last.facts || 0}</div><div style="font-size:0.8em;opacity:.7">${t("dbg_deep_facts_stored")}</div></div>
          </div>
          ${last.errors ? `<div style="color:#e44;font-size:0.8em">${t("dbg_deep_errors", { n: last.errors })}</div>` : ""}
        `;
        return false;
      }
    } catch (_) {
      return false;
    }
  }

  // ---------------------------------------------------------------------------
  // 🧪 Tests tab — prompt regression explorer
  // ---------------------------------------------------------------------------

  async _renderDebugTests(body) {
    const t = this._t || ((k) => k);
    body.innerHTML = `<em>${t("dbg_tests_loading")}</em>`;
    let data;
    try {
      const resp = await this._hass.fetchWithAuth("/api/kyber/prompt_tests");
      data = await resp.json();
    } catch (e) {
      body.innerHTML = `<div class="debug-error">${t("dbg_tests_load_failed", { msg: this._escapeHtml(e.message) })}</div>`;
      return;
    }
    const cases = data.cases || [];
    const totalPassed = cases.reduce((s, c) => s + (c.last_run?.passed || 0), 0);
    const totalAsserts = cases.reduce((s, c) => s + ((c.last_run?.passed || 0) + (c.last_run?.failed || 0)), 0);
    const pct = totalAsserts ? Math.round(100 * totalPassed / totalAsserts) : null;
    const failing = cases.filter(c => c.last_run?.failed > 0).length;

    body.innerHTML = `
      <div style="display:flex;gap:8px;align-items:center;margin-bottom:12px;flex-wrap:wrap">
        <button id="dbg-tests-run-all" class="btn-primary" style="font-size:0.85rem;padding:5px 14px">${t("dbg_tests_run_all")}</button>
        <button id="dbg-tests-regenerate" class="btn-secondary" style="font-size:0.85rem;padding:5px 14px" title="${t("dbg_tests_regenerate_title")}">${t("dbg_tests_regenerate")}</button>
        <label style="font-size:0.8rem;color:var(--secondary-text-color);cursor:pointer" title="${t("dbg_tests_batch_title")}">
          📁 <input id="dbg-tests-prompts-file" type="file" accept=".txt" style="display:none">${t("dbg_tests_batch_capture")}
        </label>
        <span style="margin-left:auto;font-size:0.85rem;color:var(--secondary-text-color)" id="dbg-tests-status">
          ${pct !== null ? t("dbg_tests_summary", { pct, passed: totalPassed, total: totalAsserts, failing }) : t("dbg_tests_no_runs")}
        </span>
      </div>
      <div style="display:flex;gap:6px;margin-bottom:10px" id="dbg-tests-filter">
        <button class="filter-btn active" data-filter="all">${t("dbg_tests_filter_all", { n: cases.length })}</button>
        <button class="filter-btn" data-filter="fail">${t("dbg_tests_filter_failing", { n: failing })}</button>
        <button class="filter-btn" data-filter="pass">${t("dbg_tests_filter_passing", { n: cases.length - failing })}</button>
      </div>
      <div id="dbg-tests-table"></div>
    `;

    this._renderTestsTable(body, cases, "all");

    // Filter buttons
    body.querySelectorAll(".filter-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        body.querySelectorAll(".filter-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        this._renderTestsTable(body, cases, btn.dataset.filter);
      });
    });

    // Run all
    body.querySelector("#dbg-tests-run-all").addEventListener("click", async (e) => {
      e.target.disabled = true;
      e.target.textContent = t("dbg_tests_running_btn");
      const statusEl = body.querySelector("#dbg-tests-status");
      if (statusEl) statusEl.textContent = t("dbg_tests_running");
      try {
        const r = await this._hass.fetchWithAuth("/api/kyber/prompt_tests/run", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({}),
        });
        const result = await r.json();
        if (statusEl) {
          const s = result.summary || {};
          statusEl.textContent = t("dbg_tests_result", { pct: Math.round((s.score || 0) * 100), passed: s.passed, total: s.total_assertions, version: s.version, model: s.model });
        }
        // Refresh
        await this._renderDebugTests(body);
      } catch (err) {
        if (statusEl) statusEl.textContent = t("dbg_error", { msg: err.message });
        e.target.disabled = false;
        e.target.textContent = t("dbg_tests_run_all");
      }
    });

    // Regenerate
    body.querySelector("#dbg-tests-regenerate").addEventListener("click", async (e) => {
      e.target.disabled = true;
      e.target.textContent = t("dbg_tests_regenerating");
      try {
        await this._hass.fetchWithAuth("/api/kyber/prompt_tests/regenerate", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({}),
        });
        e.target.textContent = t("dbg_tests_done");
        setTimeout(() => { e.target.textContent = t("dbg_tests_regenerate"); e.target.disabled = false; }, 2000);
      } catch (err) {
        e.target.textContent = t("dbg_tests_error");
        e.target.disabled = false;
      }
    });
  }

  _renderTestsTable(body, cases, filter) {
    const t = this._t || ((k) => k);
    const table = body.querySelector("#dbg-tests-table");
    if (!table) return;
    const filtered = cases.filter(c => {
      if (filter === "fail") return c.last_run?.failed > 0;
      if (filter === "pass") return c.last_run && c.last_run.failed === 0;
      return true;
    });
    if (filtered.length === 0) {
      table.innerHTML = `<em style="color:var(--secondary-text-color)">${t("dbg_tests_empty")}</em>`;
      return;
    }
    table.innerHTML = filtered.map((c, i) => {
      const run = c.last_run;
      const passed = run?.passed ?? "—";
      const total = run ? (run.passed + run.failed) : "—";
      const score = run ? `${passed}/${total}` : "—";
      const icon = !run ? "🆕" : run.failed === 0 ? "✅" : "⚠️";
      const ms = run?.latency_ms ? `${run.latency_ms}ms` : "—";
      const model = run?.model || "—";
      const version = run?.version || "—";
      const at = run?.ran_at ? new Date(run.ran_at).toLocaleDateString() : "—";
      return `
        <div class="dbg-test-row" data-idx="${i}" style="border:1px solid var(--divider-color);border-radius:6px;margin-bottom:6px;overflow:hidden">
          <div style="display:flex;gap:10px;align-items:center;padding:8px 12px;cursor:pointer;background:var(--card-background-color)" onclick="this.closest('.dbg-test-row').querySelector('.dbg-test-detail').toggleAttribute('hidden')">
            <span style="font-size:1.1em">${icon}</span>
            <span style="flex:1;font-weight:500">${this._escapeHtml(c.label || c.id)}</span>
            <span style="color:var(--secondary-text-color);font-size:0.8rem">${score}</span>
            <span style="color:var(--secondary-text-color);font-size:0.8rem">${ms}</span>
            <span style="color:var(--secondary-text-color);font-size:0.8rem">${model}</span>
            <span style="color:var(--secondary-text-color);font-size:0.8rem">${version}</span>
            <span style="color:var(--secondary-text-color);font-size:0.8rem">${at}</span>
          </div>
          <div class="dbg-test-detail" hidden style="padding:10px 14px;background:var(--secondary-background-color);font-size:0.85rem">
            <div style="margin-bottom:6px;color:var(--secondary-text-color)">❓ ${this._escapeHtml(c.question || "")}</div>
            ${run ? `
              <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px">
                ${(run.assertion_details || []).map(a => `<span style="padding:2px 8px;border-radius:12px;font-size:0.8rem;font-weight:600;background:${a.passed ? '#16532440' : '#7f1d1d40'};color:${a.passed ? '#22c55e' : '#ef4444'};border:1px solid ${a.passed ? '#22c55e44' : '#ef444444'}">${a.passed ? '✅' : '❌'} ${this._escapeHtml(a.type)}: ${this._escapeHtml(String(a.value))}</span>`).join("")}
              </div>
              <pre style="background:#0a0c14;border-radius:4px;padding:8px;font-size:0.78rem;overflow-x:auto;white-space:pre-wrap;max-height:200px">${this._escapeHtml(run.response || "")}</pre>
            ` : `<em>${t("dbg_tests_not_run", { btn: t("dbg_tests_run_all") })}</em>`}
          </div>
        </div>`;
    }).join("");
  }

  // ---------------------------------------------------------------------------
  // 📋 Capture test modal
  // ---------------------------------------------------------------------------

  _openCaptureTestModal(snap, triggerBtn) {
    const t = this._t || ((k) => k);
    const existing = this.shadowRoot.getElementById("capture-test-overlay");
    if (existing) existing.remove();

    const defaultContains = this._extractKeywords(snap.response_text || "");
    const overlay = document.createElement("div");
    overlay.id = "capture-test-overlay";
    overlay.style.cssText = "position:fixed;inset:0;background:#00000099;z-index:9999;display:flex;align-items:center;justify-content:center";
    overlay.innerHTML = `
      <div style="background:var(--card-background-color);border-radius:10px;padding:24px;max-width:520px;width:90%;max-height:85vh;overflow-y:auto;box-shadow:0 8px 32px #0006">
        <h3 style="margin:0 0 16px">${t("dbg_ct_title")}</h3>
        <label style="font-size:0.85rem;display:block;margin-bottom:4px">${t("dbg_ct_label")}</label>
        <input id="ct-label" type="text" value="${this._escapeAttr(snap.intent || t("dbg_ct_default_label"))}"
          style="width:100%;box-sizing:border-box;padding:6px 10px;border-radius:6px;border:1px solid var(--divider-color);background:var(--secondary-background-color);color:var(--primary-text-color);font-size:0.9rem;margin-bottom:12px">
        <label style="font-size:0.85rem;display:block;margin-bottom:4px">${t("dbg_ct_contains")}</label>
        <input id="ct-contains" type="text" value="${this._escapeAttr(defaultContains.join(", "))}"
          style="width:100%;box-sizing:border-box;padding:6px 10px;border-radius:6px;border:1px solid var(--divider-color);background:var(--secondary-background-color);color:var(--primary-text-color);font-size:0.9rem;margin-bottom:12px">
        <label style="font-size:0.85rem;display:block;margin-bottom:4px">${t("dbg_ct_not_contains")}</label>
        <input id="ct-not-contains" type="text" placeholder="${t("dbg_ct_not_contains_ph")}"
          style="width:100%;box-sizing:border-box;padding:6px 10px;border-radius:6px;border:1px solid var(--divider-color);background:var(--secondary-background-color);color:var(--primary-text-color);font-size:0.9rem;margin-bottom:12px">
        <label style="font-size:0.85rem;display:block;margin-bottom:4px">${t("dbg_ct_ideal")}</label>
        <textarea id="ct-ideal" rows="3" placeholder="${t("dbg_ct_ideal_ph")}"
          style="width:100%;box-sizing:border-box;padding:6px 10px;border-radius:6px;border:1px solid var(--divider-color);background:var(--secondary-background-color);color:var(--primary-text-color);font-size:0.9rem;margin-bottom:16px;resize:vertical"></textarea>
        <div id="ct-status" style="font-size:0.85rem;margin-bottom:12px;min-height:20px"></div>
        <div style="display:flex;gap:8px;justify-content:flex-end">
          <button id="ct-cancel" class="btn-secondary" style="padding:6px 16px">${t("cmd_cancel")}</button>
          <button id="ct-save" class="btn-primary" style="padding:6px 16px">${t("dbg_ct_save")}</button>
        </div>
      </div>`;

    this.shadowRoot.appendChild(overlay);

    overlay.querySelector("#ct-cancel").addEventListener("click", () => overlay.remove());

    overlay.querySelector("#ct-save").addEventListener("click", async () => {
      const saveBtn = overlay.querySelector("#ct-save");
      const statusEl = overlay.querySelector("#ct-status");
      const label = overlay.querySelector("#ct-label").value.trim() || "Unnamed test";
      const contains = overlay.querySelector("#ct-contains").value.split(",").map(s => s.trim()).filter(Boolean);
      const notContains = overlay.querySelector("#ct-not-contains").value.split(",").map(s => s.trim()).filter(Boolean);
      const ideal = overlay.querySelector("#ct-ideal").value.trim();

      saveBtn.disabled = true;
      saveBtn.textContent = t("dbg_ct_saving");

      try {
        const resp = await this._hass.fetchWithAuth("/api/kyber/prompt_tests/capture", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            request_id: snap.request_id || "",
            snap: snap,
            label,
            ideal_description: ideal,
            assertions: {
              response_contains: contains,
              response_not_contains: notContains,
              intent: snap.intent || undefined,
            },
          }),
        });
        const result = await resp.json();
        if (result.error) throw new Error(result.error);
        statusEl.innerHTML = t("dbg_ct_saved_as", { id: `<code>${this._escapeHtml(result.id)}</code>` });
        saveBtn.textContent = t("dbg_ct_saved");
        setTimeout(() => overlay.remove(), 2000);
      } catch (err) {
        statusEl.innerHTML = `❌ ${this._escapeHtml(err.message)}`;
        saveBtn.disabled = false;
        saveBtn.textContent = t("dbg_ct_save");
      }
    });
  }

  _extractKeywords(responseText) {
    // Extract potentially meaningful tokens: entity IDs, numbers, quoted values
    const keywords = [];
    // Entity IDs
    const entityIds = responseText.match(/[a-z_]+\.[a-z0-9_]+/g) || [];
    keywords.push(...entityIds.slice(0, 3));
    // Numbers (temperatures, percentages etc.)
    const nums = responseText.match(/\b\d+(?:[.,]\d+)?(?:\s*[°%])?/g) || [];
    keywords.push(...nums.slice(0, 2));
    return [...new Set(keywords)].slice(0, 5);
  }

  // ---------------------------------------------------------------------------
  // MCP debug tab: call log + side-by-side compare
  // ---------------------------------------------------------------------------

  async _renderDebugMcp(body) {
    const t = this._t || ((k) => k);

    // Load both call logs in parallel
    let mcpCalls = [], classicCalls = [];
    try {
      const [mcpResp, classicResp] = await Promise.all([
        this._hass.fetchWithAuth("/api/kyber/mcp/log"),
        this._hass.fetchWithAuth("/api/kyber/classic/log"),
      ]);
      if (mcpResp.ok) mcpCalls = (await mcpResp.json()).calls || [];
      if (classicResp.ok) classicCalls = (await classicResp.json()).calls || [];
    } catch (_) { /* ignore */ }

    // Merge and tag with source
    const allCalls = [
      ...mcpCalls.map(c => ({ ...c, source: "mcp" })),
      ...classicCalls.map(c => ({ ...c, source: "classic" })),
    ].sort((a, b) => (a.ts || 0) - (b.ts || 0));

    const total = allCalls.length;

    body.innerHTML = `
      <!-- ── Compare tool ─────────────────────────────────────────── -->
      <details class="debug-section" data-sid="mcp-compare" open>
        <div style="margin-top:10px">
          <div style="display:flex;gap:8px;margin-bottom:10px">
            <input id="mcp-cmp-input" type="text" placeholder="${t("dbg_mcp_ask_ph")}"
              style="flex:1;padding:7px 11px;border-radius:6px;border:1px solid var(--divider-color);
                     background:var(--secondary-background-color);color:var(--primary-text-color);font-size:0.9rem">
            <button id="mcp-cmp-btn" class="btn-primary" style="padding:7px 18px;white-space:nowrap">${t("dbg_mcp_compare")}</button>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px" id="mcp-cmp-cols">
            <div>
              <div style="font-size:0.82rem;font-weight:600;color:var(--secondary-text-color);margin-bottom:6px">
                ${t("dbg_mcp_direct")}  <code style="font-weight:400;font-size:0.78rem">/api/kyber/complete</code>
              </div>
              <div id="mcp-cmp-direct" style="min-height:80px;padding:10px;border-radius:6px;
                   border:1px solid var(--divider-color);background:var(--secondary-background-color);
                   font-size:0.88rem;white-space:pre-wrap;color:var(--secondary-text-color)">—</div>
            </div>
            <div>
              <div style="font-size:0.82rem;font-weight:600;color:var(--secondary-text-color);margin-bottom:6px">
                ${t("dbg_mcp_via")}  <code style="font-weight:400;font-size:0.78rem">/api/kyber/mcp</code>
              </div>
              <div id="mcp-cmp-mcp" style="min-height:80px;padding:10px;border-radius:6px;
                   border:1px solid var(--divider-color);background:var(--secondary-background-color);
                   font-size:0.88rem;white-space:pre-wrap;color:var(--secondary-text-color)">—</div>
            </div>
          </div>
        </div>
      </details>

      <!-- ── Unified call log ──────────────────────────────────────── -->
      <details class="debug-section" data-sid="mcp-calllog" open style="margin-top:14px">
        <summary style="font-weight:600;cursor:pointer;padding:6px 0">
          ${this._escapeHtml(t("dbg_mcp_call_log"))}
          <span style="font-size:0.8rem;font-weight:400;color:var(--secondary-text-color);margin-left:8px"
                id="mcp-log-count">${t("dbg_mcp_calls_count", { total, mcp: mcpCalls.length, classic: classicCalls.length })}</span>
        </summary>
        <div style="display:flex;gap:8px;margin:8px 0;flex-wrap:wrap;align-items:center">
          <button id="mcp-log-refresh" style="font-size:0.85rem;padding:4px 12px">${t("dbg_refresh")}</button>
          <button id="mcp-log-clear-mcp" style="font-size:0.85rem;padding:4px 12px;color:var(--error-color)">${t("dbg_mcp_clear_mcp")}</button>
          <button id="mcp-log-clear-classic" style="font-size:0.85rem;padding:4px 12px;color:var(--error-color)">${t("dbg_mcp_clear_classic")}</button>
          <label style="font-size:0.82rem;margin-left:auto">
            ${t("dbg_filter_colon")}
            <select id="mcp-log-filter" style="font-size:0.82rem;padding:2px 6px">
              <option value="all">${t("dbg_all")}</option>
              <option value="mcp">${t("dbg_mcp_only")}</option>
              <option value="classic">${t("dbg_mcp_classic_only")}</option>
            </select>
          </label>
        </div>
        <div id="mcp-log-table"></div>
      </details>
    `;

    this._renderMcpLogTable(body, allCalls, "all");

    // Filter dropdown
    body.querySelector("#mcp-log-filter").addEventListener("change", () => this._refreshMcpLogTable(body));

    // Compare button
    body.querySelector("#mcp-cmp-btn").addEventListener("click", () => this._runMcpCompare(body));
    body.querySelector("#mcp-cmp-input").addEventListener("keydown", (e) => {
      if (e.key === "Enter") this._runMcpCompare(body);
    });

    // Log controls
    body.querySelector("#mcp-log-refresh").addEventListener("click", () => this._refreshMcpLogTable(body));
    body.querySelector("#mcp-log-clear-mcp").addEventListener("click", async () => {
      await this._hass.fetchWithAuth("/api/kyber/mcp/log", { method: "DELETE" });
      this._refreshMcpLogTable(body);
    });
    body.querySelector("#mcp-log-clear-classic").addEventListener("click", async () => {
      await this._hass.fetchWithAuth("/api/kyber/classic/log", { method: "DELETE" });
      this._refreshMcpLogTable(body);
    });
  }

  _renderMcpLogTable(body, allCalls, filter = "all") {
    const t = this._t || ((k) => k);
    const tableEl = body.querySelector("#mcp-log-table");
    if (!tableEl) return;

    const filtered = filter === "all" ? allCalls : allCalls.filter(c => c.source === filter);
    if (!filtered.length) {
      tableEl.innerHTML = `<em style="color:var(--secondary-text-color);font-size:0.88rem">${t("dbg_mcp_no_calls")}</em>`;
      return;
    }

    const OUTCOME_COLOR = { ok: "var(--success-color,#4caf50)", error: "var(--error-color)", tool_error: "var(--warning-color,#ff9800)", notification: "var(--secondary-text-color)" };
    const SOURCE_BADGE = {
      mcp:     `<span style="font-size:0.75rem;padding:1px 5px;border-radius:9px;background:#6366f122;color:#6366f1;font-weight:600">MCP</span>`,
      classic: `<span style="font-size:0.75rem;padding:1px 5px;border-radius:9px;background:#22c55e22;color:#16a34a;font-weight:600">Classic</span>`,
    };

    const rows = filtered.slice().reverse().map((c, i) => {
      const rowId = `mcp-row-${i}`;
      const ts = c.ts ? new Date(c.ts * 1000).toLocaleTimeString(undefined, { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—";
      const source = SOURCE_BADGE[c.source] || c.source;

      // Summary line
      let detail = "";
      if (c.source === "mcp") {
        const method = this._escapeHtml(c.method || "");
        const tool = c.tool ? ` / <code style="font-size:0.78rem">${this._escapeHtml(c.tool)}</code>` : "";
        const prompt = c.prompt ? ` <span style="color:var(--secondary-text-color);font-size:0.78rem">"${this._escapeHtml(c.prompt.slice(0, 50))}${c.prompt.length > 50 ? "…" : ""}"</span>` : "";
        detail = `<span style="font-family:monospace;font-size:0.82rem">${method}${tool}</span>${prompt}`;
      } else {
        const prompt = this._escapeHtml((c.prompt || "").slice(0, 60) + (c.prompt && c.prompt.length > 60 ? "…" : ""));
        const intent = c.intent ? ` <span style="color:var(--secondary-text-color);font-size:0.78rem">[${this._escapeHtml(c.intent)}]</span>` : "";
        detail = `<span style="font-size:0.83rem">${prompt}${intent}</span>`;
      }

      const user = this._escapeHtml((c.user_id || "").slice(0, 8) + (c.user_id && c.user_id.length > 8 ? "…" : ""));
      const latency = c.latency_ms != null ? `${c.latency_ms}ms` : "—";
      const tokens = c.token_total ? `${c.token_total}t` : (c.token_usage?.total_tokens ? `${c.token_usage.total_tokens}t` : "—");
      const actions = c.actions_executed != null ? `${c.actions_executed}⚙` : "—";
      const outcome = c.outcome || "—";
      const color = OUTCOME_COLOR[outcome] || "inherit";
      const errMsg = c.error ? `<span title="${this._escapeAttr(c.error)}" style="color:var(--error-color);cursor:help">⚠</span>` : "";

      // Build expandable detail panel
      const hasDetail = c.response || c.tool_calls?.length || c.input || c.output;
      const expandBtn = hasDetail ? `<button data-expand="${rowId}" style="font-size:0.72rem;padding:1px 5px;margin-left:6px;cursor:pointer;border-radius:4px">▶</button>` : "";

      // Detail panel HTML
      let detailPanel = "";
      if (hasDetail) {
        let detailHtml = "";

        if (c.prompt) {
          detailHtml += `<div style="margin-bottom:6px"><strong style="font-size:0.78rem;color:var(--secondary-text-color)">${t("dbg_mcp_lbl_prompt")}</strong><div style="margin-top:2px;padding:6px 8px;background:var(--card-background-color,#f5f5f5);border-radius:4px;font-size:0.82rem;white-space:pre-wrap">${this._escapeHtml(c.prompt)}</div></div>`;
        }

        if (c.tool_calls?.length) {
          const callsHtml = c.tool_calls.map(tc => `
            <div style="border:1px solid var(--divider-color);border-radius:4px;margin-bottom:4px;overflow:hidden">
              <div style="padding:3px 8px;background:var(--secondary-background-color);font-size:0.78rem;font-weight:600;font-family:monospace">🔧 ${this._escapeHtml(tc.tool || "?")}</div>
              <div style="display:grid;grid-template-columns:1fr 1fr;gap:0">
                <div style="padding:4px 8px;border-right:1px solid var(--divider-color)">
                  <div style="font-size:0.72rem;color:var(--secondary-text-color);margin-bottom:2px">${t("dbg_mcp_lbl_in")}</div>
                  <pre style="margin:0;font-size:0.75rem;white-space:pre-wrap;word-break:break-all">${this._escapeHtml(tc.input || "—")}</pre>
                </div>
                <div style="padding:4px 8px">
                  <div style="font-size:0.72rem;color:var(--secondary-text-color);margin-bottom:2px">${t("dbg_mcp_lbl_out")}</div>
                  <pre style="margin:0;font-size:0.75rem;white-space:pre-wrap;word-break:break-all">${this._escapeHtml(tc.output || "—")}</pre>
                </div>
              </div>
            </div>`).join("");
          detailHtml += `<div style="margin-bottom:6px"><strong style="font-size:0.78rem;color:var(--secondary-text-color)">${t("dbg_mcp_lbl_tool_calls", { n: c.tool_calls.length })}</strong><div style="margin-top:4px">${callsHtml}</div></div>`;
        }

        if (c.response) {
          detailHtml += `<div style="margin-bottom:6px"><strong style="font-size:0.78rem;color:var(--secondary-text-color)">${t("dbg_mcp_lbl_response")}</strong><div style="margin-top:2px;padding:6px 8px;background:var(--card-background-color,#f5f5f5);border-radius:4px;font-size:0.82rem;white-space:pre-wrap">${this._escapeHtml(c.response)}</div></div>`;
        }

        if (c.input && !c.tool_calls?.length) {
          detailHtml += `<div style="margin-bottom:4px"><strong style="font-size:0.78rem;color:var(--secondary-text-color)">${t("dbg_mcp_lbl_input")}</strong><pre style="margin:2px 0 0;font-size:0.78rem;white-space:pre-wrap;padding:4px 8px;background:var(--card-background-color,#f5f5f5);border-radius:4px">${this._escapeHtml(c.input)}</pre></div>`;
          detailHtml += `<div><strong style="font-size:0.78rem;color:var(--secondary-text-color)">${t("dbg_mcp_lbl_output")}</strong><pre style="margin:2px 0 0;font-size:0.78rem;white-space:pre-wrap;padding:4px 8px;background:var(--card-background-color,#f5f5f5);border-radius:4px">${this._escapeHtml(c.output || "—")}</pre></div>`;
        }

        detailPanel = `<tr id="${rowId}" style="display:none">
          <td colspan="8" style="padding:6px 0 10px 20px">
            <div style="border-left:3px solid var(--divider-color);padding-left:10px;max-width:100%">${detailHtml}</div>
          </td>
        </tr>`;
      }

      return `<tr style="border-bottom:1px solid var(--divider-color)">
        <td style="padding:4px 8px 4px 0;font-size:0.79rem;white-space:nowrap;color:var(--secondary-text-color)">${ts}</td>
        <td style="padding:4px 8px 4px 0">${source}</td>
        <td style="padding:4px 8px 4px 0;max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${detail}${expandBtn}</td>
        <td style="padding:4px 8px 4px 0;font-size:0.79rem;color:var(--secondary-text-color)">${user}</td>
        <td style="padding:4px 8px 4px 0;font-size:0.79rem;white-space:nowrap">${latency}</td>
        <td style="padding:4px 8px 4px 0;font-size:0.79rem;white-space:nowrap;color:var(--secondary-text-color)">${tokens}</td>
        <td style="padding:4px 8px 4px 0;font-size:0.79rem;white-space:nowrap">${actions}</td>
        <td style="padding:4px 0;font-size:0.79rem;font-weight:600;color:${color}">${outcome} ${errMsg}</td>
      </tr>${detailPanel}`;
    }).join("");

    tableEl.innerHTML = `
      <div style="overflow-x:auto;max-height:60vh">
        <table style="width:100%;border-collapse:collapse;font-family:monospace">
          <thead><tr style="font-size:0.77rem;color:var(--secondary-text-color);border-bottom:2px solid var(--divider-color)">
            <th style="text-align:left;padding:2px 8px 4px 0">${t("dbg_col_time")}</th>
            <th style="text-align:left;padding:2px 8px 4px 0">${t("dbg_col_source")}</th>
            <th style="text-align:left;padding:2px 8px 4px 0">${t("dbg_col_detail")}</th>
            <th style="text-align:left;padding:2px 8px 4px 0">${t("dbg_col_user")}</th>
            <th style="text-align:left;padding:2px 8px 4px 0">${t("dbg_col_latency")}</th>
            <th style="text-align:left;padding:2px 8px 4px 0">${t("dbg_col_tokens")}</th>
            <th style="text-align:left;padding:2px 8px 4px 0">${t("dbg_col_actions")}</th>
            <th style="text-align:left;padding:2px 0 4px 0">${t("dbg_col_outcome")}</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;

    // Expand/collapse toggle
    tableEl.querySelectorAll("button[data-expand]").forEach(btn => {
      btn.addEventListener("click", () => {
        const row = tableEl.querySelector(`#${btn.dataset.expand}`);
        if (!row) return;
        const open = row.style.display !== "none";
        row.style.display = open ? "none" : "table-row";
        btn.textContent = open ? "▶" : "▼";
      });
    });
  }

  async _runMcpCompare(body) {
    const t = this._t || ((k) => k);
    const input = body.querySelector("#mcp-cmp-input");
    const prompt = (input?.value || "").trim();
    if (!prompt) return;

    const directEl = body.querySelector("#mcp-cmp-direct");
    const mcpEl = body.querySelector("#mcp-cmp-mcp");
    const btn = body.querySelector("#mcp-cmp-btn");

    btn.disabled = true;
    directEl.textContent = t("dbg_mcp_waiting");
    mcpEl.textContent = t("dbg_mcp_waiting");

    const requestId = `mcp-cmp-${Date.now()}`;

    // Run Direct Kyber first, then MCP — sequential so timing is comparable
    btn.textContent = t("dbg_mcp_step_direct");
    directEl.textContent = t("dbg_mcp_asking");
    {
      const t0 = performance.now();
      try {
        const r = await this._hass.fetchWithAuth("/api/kyber/complete", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ prompt, yaml: "", history: [], request_id: requestId }),
        });
        const ms = Math.round(performance.now() - t0);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = await r.json();
        const tokens = d.call_tokens || d.token_usage?.total_tokens;
        const actions = (d.tool_log || []).filter(e => e.type === "tool_call").length;
        const mem = (d.knowledge_used || []).length;
        const memStr = mem > 0 ? ` · ${t("dbg_mcp_memory", { n: mem })}` : "";
        const footer = `\n\n─── ${ms}ms${tokens ? ` · ${t("dbg_mcp_tokens", { n: tokens })}` : ""} · ${actions} ⚙${memStr}`;
        directEl.textContent = (d.response || t("dbg_mcp_no_response")) + footer;
      } catch (e) {
        directEl.textContent = `❌ ${e.message}`;
      }
    }

    btn.textContent = t("dbg_mcp_step_mcp");
    mcpEl.textContent = t("dbg_mcp_asking");
    {
      const t0 = performance.now();
      try {
        const r = await this._hass.fetchWithAuth("/api/kyber/mcp", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            jsonrpc: "2.0", id: 1, method: "tools/call",
            params: { name: "kyber_ask", arguments: { prompt } },
          }),
        });
        const ms = Math.round(performance.now() - t0);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = await r.json();
        if (d.error) throw new Error(d.error.message || t("dbg_mcp_rpc_error"));
        const content = d.result?.content?.[0]?.text || "";
        let text = content;
        try {
          const parsed = JSON.parse(content);
          text = parsed.response || content;
          const tokens = parsed.token_usage?.total_tokens;
          const actions = parsed.actions_executed;
          const mem = (parsed.knowledge_used || []).length;
          const memStr = mem > 0 ? ` · ${t("dbg_mcp_memory", { n: mem })}` : "";
          const footer = `\n\n─── ${ms}ms${tokens ? ` · ${t("dbg_mcp_tokens", { n: tokens })}` : ""}${actions != null ? ` · ${t("dbg_mcp_actions", { n: actions })}` : ""}${memStr}`;
          text += footer;
        } catch (_) {
          text += `\n\n─── ${ms}ms`;
        }
        if (d.result?.isError) text = t("dbg_mcp_tool_error", { text });
        mcpEl.textContent = text;
      } catch (e) {
        mcpEl.textContent = `❌ ${e.message}`;
      }
    }

    btn.disabled = false;
    btn.textContent = t("dbg_mcp_compare");

    // Refresh the log table after compare
    try {
      await this._refreshMcpLogTable(body);
    } catch (_) { /* ignore */ }
  }

  async _refreshMcpLogTable(body) {
    const t = this._t || ((k) => k);
    let mcpCalls = [], classicCalls = [];
    try {
      const [r1, r2] = await Promise.all([
        this._hass.fetchWithAuth("/api/kyber/mcp/log"),
        this._hass.fetchWithAuth("/api/kyber/classic/log"),
      ]);
      if (r1.ok) mcpCalls = (await r1.json()).calls || [];
      if (r2.ok) classicCalls = (await r2.json()).calls || [];
    } catch (_) { /* ignore */ }
    const allCalls = [
      ...mcpCalls.map(c => ({ ...c, source: "mcp" })),
      ...classicCalls.map(c => ({ ...c, source: "classic" })),
    ].sort((a, b) => (a.ts || 0) - (b.ts || 0));
    const filter = body.querySelector("#mcp-log-filter")?.value || "all";
    this._renderMcpLogTable(body, allCalls, filter);
    const countEl = body.querySelector("#mcp-log-count");
    if (countEl) countEl.textContent = t("dbg_mcp_calls_count", { total: allCalls.length, mcp: mcpCalls.length, classic: classicCalls.length });
    return allCalls;
  }
};
