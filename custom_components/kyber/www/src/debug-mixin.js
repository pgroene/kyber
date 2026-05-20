export const DebugMixin = (Base) => class extends Base {
  _toggleDebugPane(force) {
    const pane = this.shadowRoot.getElementById("debug-pane");
    const chat = this.shadowRoot.querySelector(".chat-pane");
    if (!pane || !chat) return;
    const wantOpen = force === undefined ? pane.hasAttribute("hidden") : !!force;
    if (wantOpen) {
      pane.removeAttribute("hidden");
      chat.style.display = "none";
      this._debugTab = this._debugTab || "memory";
      this._renderDebugTab(this._debugTab);
    } else {
      pane.setAttribute("hidden", "");
      chat.style.display = "";
    }
  }

  async _renderDebugTab(tab) {
    this._debugTab = tab;
    const body = this.shadowRoot.getElementById("debug-body");
    if (!body) return;
    body.innerHTML = "<em>Loading…</em>";
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
      }
    } catch (err) {
      body.innerHTML = `<div class="debug-error">Error: ${this._escapeHtml(err.message)}</div>`;
    }
  }

  async _renderDebugMemory(body) {
    const token = this._hass.auth.data.access_token;
    const resp = await fetch("/api/kyber/knowledge", { headers: { Authorization: `Bearer ${token}` } });
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
        <strong>${entries.length}</strong> entries · ${reviewCount} need review · ${catBadges}
      </div>
      <div class="debug-toolbar">
        <label>Filter
          <select id="dbg-mem-filter">
            <option value="all" ${(this._debugMemFilter||'all')==='all'?'selected':''}>All</option>
            <option value="review" ${this._debugMemFilter==='review'?'selected':''}>⚠ needs review</option>
          </select>
        </label>
        <label>Sort
          <select id="dbg-mem-sort">
            <option value="updated" ${(this._debugMemSort||'updated')==='updated'?'selected':''}>Most recent</option>
            <option value="hits" ${this._debugMemSort==='hits'?'selected':''}>Most hits</option>
            <option value="confidence" ${this._debugMemSort==='confidence'?'selected':''}>Lowest confidence</option>
            <option value="rating" ${this._debugMemSort==='rating'?'selected':''}>Highest rating</option>
          </select>
        </label>
        <input type="text" id="dbg-mem-text" placeholder="🔍 Filter text…" value="${this._escapeAttr(this._debugMemText||'')}" style="padding:4px 8px;border:1px solid var(--divider-color,#ccc);border-radius:4px;font-size:0.88em;min-width:140px">
        <button id="dbg-mem-add">➕ Add fact</button>
        <button id="dbg-mem-analyze">🔍 Analyze my home</button>
        <button id="dbg-mem-deep-analyze">🧬 Start deep analysis</button>
        <label style="display:flex;align-items:center;gap:4px;font-size:0.85em">
          <input type="checkbox" id="dbg-deep-force"> Re-analyze all
        </label>
        <button id="dbg-mem-purge" style="color:#c00">🗑 Purge facts</button>
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
      const token = this._hass.auth.data.access_token;
      const force = body.querySelector("#dbg-deep-force")?.checked ?? false;
      const r = await fetch("/api/kyber/knowledge/analyze_deep", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ background: true, runs: 10, limit: 5, force }),
      });
      const j = await r.json();
      if (!r.ok || (j.status !== "started" && j.status !== "already_running")) {
        alert("Failed to start: " + (j.message || r.statusText));
        return;
      }
      this._startDeepAnalysisPolling(body);
    });

    body.querySelector("#dbg-mem-purge").addEventListener("click", () => {
      this._renderPurgeFacts(body).catch((err) => {
        body.innerHTML = `<div class="debug-error">Purge panel error: ${this._escapeHtml(err.message)}</div>`;
      });
    });

    // Show status if a job is already running / recently finished
    this._refreshDeepAnalysisStatus(body);
    this._wireKnowledgeRowEvents(body, filtered, categories);
  }

  // ── Review flow ────────────────────────────────────────────────────────────

  _reviewSkipKey() { return "kyber_review_skip_v1"; }
  _reviewSkipDaysKey() { return "kyber_review_skip_days"; }

  _getReviewSkipDays() {
    const stored = localStorage.getItem(this._reviewSkipDaysKey());
    return stored ? parseInt(stored, 10) : 7;
  }

  _getSkippedIds() {
    try {
      const raw = localStorage.getItem(this._reviewSkipKey());
      if (!raw) return {};
      return JSON.parse(raw);
    } catch { return {}; }
  }

  _setSkippedIds(map) {
    localStorage.setItem(this._reviewSkipKey(), JSON.stringify(map));
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

  _renderReviewCardHTML(queue, allEntries) {
    const idx = Math.min(this._reviewIdx || 0, queue.length - 1);
    const entry = queue[idx];
    const total = queue.length;
    const skipDays = this._getReviewSkipDays();
    const pct = Math.round(((idx) / total) * 100);
    const cat = this._escapeHtml(entry.category || "general");
    const subj = this._escapeHtml(entry.subject || "");
    const content = this._escapeHtml(entry.content || "");
    const conf = entry.confidence != null ? `${Math.round(entry.confidence * 100)}%` : "—";
    const prov = entry.provenance ? `<span class="kn-prov">${this._escapeHtml(entry.provenance)}</span>` : "";
    return `
      <div class="review-flow" id="review-flow">
        <div class="review-flow-header">
          <span class="review-flow-title">⚠ Review queue</span>
          <span class="review-flow-progress">${idx + 1} / ${total}</span>
          <div class="review-flow-bar"><div class="review-flow-bar-fill" style="width:${pct}%"></div></div>
        </div>
        <div class="review-flow-card">
          <div class="review-flow-meta">
            <span class="kn-cat">${cat}</span>
            ${subj ? `<span class="kn-subj">${subj}</span>` : ""}
            <span class="kn-conf">conf: ${conf}</span>
            ${prov}
          </div>
          <div class="review-flow-content">${content}</div>
        </div>
        <div class="review-flow-actions">
          <button class="review-btn review-btn-approve" id="review-approve" title="Approve — mark as reviewed, keep">✅ Approve</button>
          <button class="review-btn review-btn-reject" id="review-reject" title="Reject — delete this fact">🗑 Reject</button>
          <button class="review-btn review-btn-skip" id="review-skip" title="Skip for ${skipDays} day(s)">⏭ Skip</button>
          <label class="review-skip-days-label" title="Days to hide after skipping">
            Hide for <input type="number" id="review-skip-days" min="1" max="365" value="${skipDays}" style="width:40px;padding:1px 4px"> days
          </label>
        </div>
      </div>
    `;
  }

  _wireReviewCard(body, queue, allEntries, categories) {
    const flow = body.querySelector("#review-flow");
    if (!flow) return;

    flow.querySelector("#review-skip-days").addEventListener("change", (e) => {
      const v = parseInt(e.target.value, 10);
      if (v > 0) localStorage.setItem(this._reviewSkipDaysKey(), String(v));
    });

    flow.querySelector("#review-approve").addEventListener("click", async () => {
      const idx = Math.min(this._reviewIdx || 0, queue.length - 1);
      const entry = queue[idx];
      const token = this._hass.auth.data.access_token;
      // Clear needs_review flag via knowledge update endpoint
      await fetch("/api/kyber/knowledge", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ id: entry.id, user_rating: 1, needs_review: false }),
      });
      // Remove from queue and advance
      queue.splice(idx, 1);
      if (queue.length === 0) { this._reviewIdx = 0; this._renderDebugTab("memory"); return; }
      this._reviewIdx = Math.min(idx, queue.length - 1);
      this._refreshReviewCard(body, queue, allEntries, categories);
    });

    flow.querySelector("#review-reject").addEventListener("click", async () => {
      const idx = Math.min(this._reviewIdx || 0, queue.length - 1);
      const entry = queue[idx];
      if (!confirm(`Delete this fact?\n\n"${entry.content}"`)) return;
      const token = this._hass.auth.data.access_token;
      await fetch(`/api/kyber/knowledge?id=${encodeURIComponent(entry.id)}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      queue.splice(idx, 1);
      if (queue.length === 0) { this._reviewIdx = 0; this._renderDebugTab("memory"); return; }
      this._reviewIdx = Math.min(idx, queue.length - 1);
      this._refreshReviewCard(body, queue, allEntries, categories);
    });

    flow.querySelector("#review-skip").addEventListener("click", () => {
      const idx = Math.min(this._reviewIdx || 0, queue.length - 1);
      const entry = queue[idx];
      this._skipEntry(entry.id);
      queue.splice(idx, 1);
      if (queue.length === 0) { this._reviewIdx = 0; this._renderDebugTab("memory"); return; }
      this._reviewIdx = Math.min(idx, queue.length - 1);
      this._refreshReviewCard(body, queue, allEntries, categories);
    });
  }

  _refreshReviewCard(body, queue, allEntries, categories) {
    const flow = body.querySelector("#review-flow");
    if (!flow) return;
    if (queue.length === 0) { flow.remove(); return; }
    const newHtml = this._renderReviewCardHTML(queue, allEntries);
    const tmp = document.createElement("div");
    tmp.innerHTML = newHtml;
    const newFlow = tmp.firstElementChild;
    flow.replaceWith(newFlow);
    this._wireReviewCard(body, queue, allEntries, categories);
  }

  _timeAgo(unixTs) {
    const secs = Math.floor(Date.now() / 1000) - unixTs;
    if (secs < 60) return `${secs}s ago`;
    if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
    if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
    return `${Math.floor(secs / 86400)}d ago`;
  }

  async _renderPurgeFacts(body) {
    body.innerHTML = "<em>Loading facts…</em>";
    const token = this._hass.auth.data.access_token;
    const resp = await fetch("/api/kyber/knowledge", { headers: { Authorization: `Bearer ${token}` } });
    const data = await resp.json();
    this._purgeAllEntries = data.entries || [];
    this._purgeSelected = new Set();
    this._purgeSort = this._purgeSort || "updated";
    this._purgeText = this._purgeText || "";
    this._renderPurgeFacts_withData(body);
  }

  _renderPurgeFacts_withData(body) {
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
              <span>conf: ${conf}</span> · <span>${stars}</span> · <span>${e.hits || 0} hits</span> · <span>${ago}</span>
            </div>
          </div>
        </label>`;
    }).join("");

    body.innerHTML = `
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap">
        <button id="purge-back" style="font-size:0.9em">← Back</button>
        <strong style="font-size:1em">🗑 Purge facts</strong>
        <span style="font-size:0.85em;opacity:.7">${all.length} total</span>
      </div>

      <div class="debug-toolbar" style="margin-bottom:6px">
        <input type="text" id="purge-text" placeholder="🔍 Filter text…" value="${this._escapeAttr(this._purgeText||'')}"
          style="padding:4px 8px;border:1px solid var(--divider-color,#ccc);border-radius:4px;font-size:0.88em;min-width:150px">
        <label>Sort
          <select id="purge-sort">
            <option value="updated" ${sort==='updated'?'selected':''}>Most recent</option>
            <option value="hits" ${sort==='hits'?'selected':''}>Most hits</option>
            <option value="confidence_asc" ${sort==='confidence_asc'?'selected':''}>Lowest confidence</option>
            <option value="confidence_desc" ${sort==='confidence_desc'?'selected':''}>Highest confidence</option>
            <option value="rating" ${sort==='rating'?'selected':''}>Highest rating</option>
          </select>
        </label>
      </div>

      <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:6px;font-size:0.83em">
        <span style="opacity:.7">Quick-select:</span>
        ${sources.map((s) => {
          const n = all.filter((e) => e.source === s).length;
          return `<button class="qs-source" data-source="${this._escapeAttr(s)}" style="padding:2px 7px;font-size:0.9em">${this._escapeHtml(s)} (${n})</button>`;
        }).join("")}
        <button class="qs-low-conf" style="padding:2px 7px;font-size:0.9em">Confidence &lt; 60%</button>
        <button id="purge-sel-all" style="padding:2px 7px;font-size:0.9em">Select all visible</button>
        <button id="purge-desel-all" style="padding:2px 7px;font-size:0.9em">Deselect all</button>
      </div>

      <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
        <button id="purge-do" style="background:#c00;color:#fff;padding:5px 14px;border-radius:4px;border:none;cursor:pointer;font-weight:600" ${selCount===0?'disabled':''}>
          🗑 Delete selected (${selCount})
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
    const msg = body.querySelector("#purge-msg");
    const btn = body.querySelector("#purge-do");
    if (!confirm(`Delete ${ids.length} fact(s)? This cannot be undone.`)) return;
    if (btn) btn.disabled = true;
    if (msg) msg.textContent = "Deleting…";
    try {
      const token = this._hass.auth.data.access_token;
      const r = await fetch("/api/kyber/knowledge/purge", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ ids }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.message || r.statusText);
      sel.clear();
      // Reload full list
      const resp2 = await fetch("/api/kyber/knowledge", { headers: { Authorization: `Bearer ${token}` } });
      const data2 = await resp2.json();
      this._purgeAllEntries = data2.entries || [];
      if (msg) msg.textContent = `✅ Deleted ${j.deleted}`;
      this._renderPurgeFacts_withData(body);
    } catch (err) {
      if (msg) msg.textContent = `❌ ${err.message}`;
      if (btn) btn.disabled = false;
    }
  }

  async _renderDebugLastTurn(body) {
    const token = this._hass.auth.data.access_token;
    const resp = await fetch("/api/kyber/debug/last_turn", { headers: { Authorization: `Bearer ${token}` } });
    const data = await resp.json();
    const snap = data.snapshot;
    if (!snap) {
      body.innerHTML = `<div class="debug-empty">No turn captured yet. Ask Kyber something and come back.</div>`;
      return;
    }
    const picked = snap.picked_knowledge || [];
    const toolRows = (snap.tool_log || []).map((t) => `
      <tr>
        <td><code>${this._escapeHtml(t.name || t.tool || "?")}</code></td>
        <td class="dbg-mono">${this._escapeHtml(JSON.stringify(t.args || t.arguments || {}))}</td>
        <td>${t.status === "error" ? "❌" : "✓"}</td>
        <td>${t.ms ?? ""}</td>
      </tr>`).join("");
    const ts = snap.ts ? new Date(snap.ts * 1000).toLocaleTimeString() : "—";
    const knowledgeIds = (picked || []).map((p) => p.id).filter(Boolean);
    const hasKnowledge = knowledgeIds.length > 0;
    const autoNote = snap.auto_rating
      ? `<span class="tf-auto" title="Auto-flagged because the response looked uncertain">⚠ auto-rated ${snap.auto_rating}/5</span>`
      : "";
    const feedbackBar = `
      <div class="dbg-turn-feedback" id="dbg-turn-feedback" data-request-id="${this._escapeAttr(snap.request_id || "")}">
        <span class="tf-label">How was this turn?</span>
        <button class="tf-btn tf-btn-rate tf-up" title="Helpful — boost related memory" ${hasKnowledge ? "" : "disabled"}>👍 helpful</button>
        <button class="tf-btn tf-btn-rate tf-down" title="Not helpful — flag related memory for review" ${hasKnowledge ? "" : "disabled"}>👎 not helpful</button>
        ${autoNote}
        <span class="tf-status"></span>
        <button class="tf-btn tf-bundle" title="Download a zip with the full snapshot + logs of this turn" ${snap.request_id ? "" : "disabled"}>⬇ download bundle</button>
        <button class="tf-btn tf-bug-report" title="Create a GitHub bug report from this turn" ${snap.request_id ? "" : "disabled"}>🐛 bug report</button>
        <button class="tf-btn tf-capture-test" title="Capture this turn as a prompt regression test case" ${snap.request_id ? "" : "disabled"}>📋 capture test</button>
      </div>`;
    body.innerHTML = `
      ${feedbackBar}
      <div class="debug-stats">
        <strong>Turn at ${ts}</strong> · ${snap.elapsed_ms ?? "?"} ms · intent: <code>${this._escapeHtml(snap.intent || "?")}</code>
        · prompt: ${snap.char_count?.toLocaleString() ?? "?"} chars (~${snap.approx_tokens?.toLocaleString() ?? "?"} tokens)
        · auto_rating: ${snap.auto_rating ? `⚠ ${snap.auto_rating}/5` : "—"}
      </div>
      <details class="debug-section" open>
        <summary><strong>User prompt</strong></summary>
        <pre class="dbg-pre">${this._escapeHtml(snap.user_prompt || "")}</pre>
      </details>
      <details class="debug-section" open>
        <summary><strong>📌 Knowledge entries used this turn (${picked.length})</strong></summary>
        ${picked.length === 0 ? '<em>None injected.</em>' : '<div class="kn-list" id="dbg-picked-list"></div>'}
      </details>
      <details class="debug-section">
        <summary><strong>🔧 Tool calls (${(snap.tool_log || []).length})</strong></summary>
        ${toolRows ? `<table class="dbg-tools"><thead><tr><th>tool</th><th>args</th><th>status</th><th>ms</th></tr></thead><tbody>${toolRows}</tbody></table>` : '<em>No tool calls.</em>'}
      </details>
      <details class="debug-section">
        <summary><strong>📜 Expanded system prompt</strong> (what the model actually saw)</summary>
        <pre class="dbg-pre">${this._escapeHtml(snap.expanded_prompt || "")}</pre>
      </details>
      <details class="debug-section">
        <summary><strong>💬 Response text</strong></summary>
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
      const fullResp = await fetch("/api/kyber/knowledge", { headers: { Authorization: `Bearer ${token}` } });
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
    const token = this._hass.auth.data.access_token;
    const resp = await fetch("/api/kyber/debug/status", { headers: { Authorization: `Bearer ${token}` } });
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
    const epRunning = epStatus === "phase1_summaries" || epStatus === "phase2_entities" || epStatus === "starting" || epStatus === "narrator";
    const epDone = ep.done ?? 0;
    const epTotal = ep.total ?? 0;
    const epPct = epTotal > 0 ? Math.round((epDone / epTotal) * 100) : 0;
    const narratorDone = ep.narrator_done ?? 0;
    const narratorTotal = ep.narrator_total ?? 0;
    const epLabel = epStatus === "narrator"
      ? `AI narrator ${narratorDone} / ${narratorTotal}…`
      : epRunning
        ? (ep.phase === "summaries" ? `Indexing integrations… (${epStatus})` : `Indexing entities ${epDone} / ${epTotal} (${epPct}%)`)
        : epStatus === "done" ? `Complete — ${epDone} entities indexed`
        : "Not yet started";
    const epProgressBar = epTotal > 0
      ? `<progress value="${epDone}" max="${epTotal}" style="width:100%;margin-top:4px"></progress>` : "";
    const narratorProgressBar = narratorTotal > 0
      ? `<progress value="${narratorDone}" max="${narratorTotal}" style="width:100%;margin-top:4px"></progress>` : "";

    // Narrator stats summary
    const nsTotal = ns.total ?? 0;
    const nsAccepted = (ns.accepted_first ?? 0) + (ns.accepted_retry ?? 0);
    const nsPct = nsTotal > 0 ? Math.round((nsAccepted / nsTotal) * 100) : 0;
    const nsLabel = nsTotal > 0
      ? `${nsAccepted} accepted (${nsPct}%) · ${ns.rejected ?? 0} fallback · ${ns.errors ?? 0} errors`
      : "Not yet run";

    // Helpers for storage/resource display
    const fmtBytes = (b) => {
      if (b == null) return "—";
      if (b < 1024) return `${b} B`;
      if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
      return `${(b / (1024 * 1024)).toFixed(2)} MB`;
    };
    const fmtBuf = (n, max) => `${n} / ${max} (${max > 0 ? Math.round((n / max) * 100) : 0}%)`;

    body.innerHTML = `
      <h3>Runtime</h3>
      <table class="dbg-kv">
        <tr><th>AI Task entity</th><td><code>${this._escapeHtml(data.ai_task_entity || "—")}</code></td></tr>
        ${(data.ai_task_info && data.ai_task_info.friendly_name && data.ai_task_info.friendly_name !== data.ai_task_entity) ? `<tr><th>Display name</th><td>${this._escapeHtml(data.ai_task_info.friendly_name)}</td></tr>` : ""}
        ${data.ai_task_info && data.ai_task_info.model ? `<tr><th>Model</th><td><code>${this._escapeHtml(data.ai_task_info.model)}</code> <a href="https://github.com/pgroene/kyber#choosing-a-model" target="_blank" rel="noopener" style="font-size:0.8em;margin-left:6px;opacity:0.7" title="How to choose a model">📖 how to choose</a></td></tr>` : ""}
        ${data.ai_task_info && data.ai_task_info.server ? `<tr><th>Server</th><td><code>${this._escapeHtml(data.ai_task_info.server)}</code></td></tr>` : ""}
        <tr><th>Autopilot</th><td>${this._autopilot ? "ON ⚡" : "OFF"}</td></tr>
        <tr><th>Session</th><td>${this._escapeHtml(this._sessionName || "—")}</td></tr>
        <tr><th>Tool history size</th><td>${data.tool_history_size}</td></tr>
      </table>
      <h3>Storage</h3>
      <table class="dbg-kv">
        ${st.total_bytes != null ? `<tr><th>Total (Kyber data)</th><td><strong>${fmtBytes(st.total_bytes)}</strong></td></tr>` : ""}
        ${Object.entries(st.files || {}).sort((a,b) => (b[1]||0)-(a[1]||0)).map(([name, size]) =>
          `<tr><td style="padding-left:1.2em"><code>${this._escapeHtml(name)}</code></td><td>${fmtBytes(size)}</td></tr>`
        ).join("")}
        ${st.total_bytes == null ? `
          <tr><th>Knowledge store</th><td>${fmtBytes(st.knowledge_file_bytes)}</td></tr>
          <tr><th>Chat history</th><td>${fmtBytes(st.chat_history_file_bytes)}</td></tr>
        ` : ""}
        ${st.component_bytes != null ? `<tr><th>Component (code)</th><td>${fmtBytes(st.component_bytes)}</td></tr>` : ""}
      </table>
      <h3>Resources (in-memory)</h3>
      <table class="dbg-kv">
        ${res.process_rss_bytes != null ? `<tr><th>Process RSS</th><td>${fmtBytes(res.process_rss_bytes)}</td></tr>` : ""}
        <tr><th>Debug snapshots</th><td>${fmtBuf(res.snapshots_buffered ?? 0, res.snapshots_max ?? 50)}</td></tr>
        <tr><th>Global log buffer</th><td>${fmtBuf(res.global_log_entries ?? 0, res.global_log_max ?? 2000)}</td></tr>
        <tr><th>TF-IDF index terms</th><td>${(res.tfidf_terms ?? 0).toLocaleString()}</td></tr>
        <tr><th>Knowledge vectors</th><td>${(res.knowledge_vectors ?? 0).toLocaleString()}</td></tr>
      </table>
      <h3>Knowledge store</h3>
      <table class="dbg-kv">
        <tr><th>Total entries</th><td>${k.total ?? 0}</td></tr>
        <tr><th>Needs review</th><td>${k.needs_review ?? 0}</td></tr>
        <tr><th>Total hits</th><td>${k.total_hits ?? 0}</td></tr>
      </table>
      ${catRows ? `<h4>By category</h4><table class="dbg-kv">${catRows}</table>` : ""}
      <h3>Entity Explorer</h3>
      <table class="dbg-kv">
        <tr><th>Status</th><td>${this._escapeHtml(epLabel)}</td></tr>
        ${ep.current_platform ? `<tr><th>Current</th><td><code>${this._escapeHtml(ep.current_platform)}</code></td></tr>` : ""}
        ${ep.started_at ? `<tr><th>Started</th><td>${new Date(ep.started_at * 1000).toLocaleTimeString()}</td></tr>` : ""}
      </table>
      ${epProgressBar}
      ${epStatus === "narrator" ? narratorProgressBar : ""}
      <h3>AI Narrator</h3>
      <table class="dbg-kv">
        ${data.narrator_ai_task_entity ? `<tr><th>AI Task entity</th><td><code>${this._escapeHtml(data.narrator_ai_task_entity)}</code></td></tr>` : ""}
        ${(data.narrator_ai_task_info && data.narrator_ai_task_info.friendly_name && data.narrator_ai_task_info.friendly_name !== data.narrator_ai_task_entity) ? `<tr><th>Display name</th><td>${this._escapeHtml(data.narrator_ai_task_info.friendly_name)}</td></tr>` : ""}
        ${data.narrator_ai_task_info && data.narrator_ai_task_info.model ? `<tr><th>Model</th><td><code>${this._escapeHtml(data.narrator_ai_task_info.model)}</code> <a href="https://github.com/pgroene/kyber/blob/main/docs/narrator-bench-report-2026-05.md" target="_blank" rel="noopener" style="font-size:0.8em;margin-left:6px;opacity:0.7" title="Narrator model bench report">📖 bench report</a></td></tr>` : ""}
        ${data.narrator_ai_task_info && data.narrator_ai_task_info.server ? `<tr><th>Server</th><td><code>${this._escapeHtml(data.narrator_ai_task_info.server)}</code></td></tr>` : ""}
        <tr><th>Status</th><td>${this._escapeHtml(nsLabel)}</td></tr>
        ${ns.last_run ? `<tr><th>Last run</th><td>${this._escapeHtml(ns.last_run)}</td></tr>` : ""}
        ${nsTotal > 0 ? `
          <tr><th>Accepted (1st try)</th><td>${ns.accepted_first ?? 0}</td></tr>
          <tr><th>Accepted (retry)</th><td>${ns.accepted_retry ?? 0}</td></tr>
          <tr><th>Fallback (all failed)</th><td>${ns.rejected ?? 0}</td></tr>
          <tr><th>Errors</th><td>${ns.errors ?? 0}</td></tr>
        ` : ""}
      </table>
      <h3>Last turn</h3>
      ${lt ? `
        <table class="dbg-kv">
          <tr><th>When</th><td>${lt.ts ? new Date(lt.ts * 1000).toLocaleString() : "—"}</td></tr>
          <tr><th>Elapsed</th><td>${lt.elapsed_ms} ms</td></tr>
          <tr><th>Intent</th><td><code>${this._escapeHtml(lt.intent || "—")}</code></td></tr>
          <tr><th>Prompt size</th><td>${lt.char_count?.toLocaleString() ?? "?"} chars (~${lt.approx_tokens?.toLocaleString() ?? "?"} tokens)</td></tr>
        </table>
        ${lt.request_id ? `
        <div style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap">
          <button id="dbg-download-bundle" style="font-size:0.9em;padding:6px 14px">
            📦 Download debug bundle
          </button>
          <button id="dbg-open-bug-report" style="font-size:0.9em;padding:6px 14px">
            🐛 Bug report
          </button>
        </div>` : ""}
      ` : "<em>No turn captured yet.</em>"}
      <h3>Export for Eval</h3>
      <p style="margin:4px 0 8px;font-size:0.88em;color:var(--secondary-text-color)">
        Download snapshots to create test scenarios. Drop them in chat to build an eval set.
      </p>
      <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center">
        <button id="dbg-export-home" style="font-size:0.9em;padding:6px 14px">
          📥 Home state
        </button>
        <button id="dbg-export-memory" style="font-size:0.9em;padding:6px 14px">
          🧠 Memory export
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

    // Auto-refresh while explorer or narrator is running
    if (epRunning) {
      if (!this._explorerStatusTimer) {
        this._explorerStatusTimer = setInterval(() => {
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
    const token = this._hass.auth.data.access_token;
    const level = body.querySelector("#dbg-log-level")?.value || "";
    const url = `/api/kyber/debug/logs${level ? `?level=${level}` : ""}`;
    const resp = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
    if (!resp.ok) {
      body.innerHTML = `<em style="color:var(--error-color)">Debug logs endpoint not available (HTTP ${resp.status}). Try reloading the Kyber integration or restarting Home Assistant.</em>`;
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
      const ts = r.ts ? new Date(r.ts * 1000).toLocaleTimeString("nl", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—";
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
          <option value=""${!level ? " selected" : ""}>All levels</option>
          <option value="INFO"${level === "INFO" ? " selected" : ""}>INFO+</option>
          <option value="WARNING"${level === "WARNING" ? " selected" : ""}>WARNING+</option>
          <option value="ERROR"${level === "ERROR" ? " selected" : ""}>ERROR+</option>
        </select>
        <button id="dbg-log-refresh" style="font-size:0.88em;padding:4px 10px">🔄 Refresh</button>
        <button id="dbg-log-download" style="font-size:0.88em;padding:4px 10px">📥 Download</button>
        <button id="dbg-log-clear" style="font-size:0.88em;padding:4px 10px;color:var(--error-color)">🗑 Clear</button>
        <span style="font-size:0.82em;color:var(--secondary-text-color)">${logs.length} records</span>
      </div>
      ${logs.length > 0 ? `
      <div style="overflow-x:auto;max-height:60vh">
        <table style="width:100%;border-collapse:collapse;font-family:monospace" id="dbg-log-table">
          <thead><tr style="font-size:0.78em;color:var(--secondary-text-color);border-bottom:1px solid var(--divider-color)">
            <th style="text-align:left;padding:2px 8px 4px 0">Time</th>
            <th style="text-align:left;padding:2px 8px 4px 0">Level</th>
            <th style="text-align:left;padding:2px 8px 4px 0">Logger</th>
            <th style="text-align:left;padding:2px 0 4px 0">Message</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>` : `<em style="color:var(--secondary-text-color)">No logs yet. Kyber logs are captured once debug mode is enabled and a first request is made.</em>`}
    `;

    body.querySelector("#dbg-log-refresh")?.addEventListener("click", () => this._renderDebugLogs(body));
    body.querySelector("#dbg-log-clear")?.addEventListener("click", async () => {
      const t = this._hass.auth.data.access_token;
      await fetch("/api/kyber/debug/logs", { method: "DELETE", headers: { Authorization: `Bearer ${t}` } });
      this._renderDebugLogs(body);
    });
    body.querySelector("#dbg-log-download")?.addEventListener("click", async () => {
      const t = this._hass.auth.data.access_token;
      const lv = body.querySelector("#dbg-log-level")?.value || "";
      const dlUrl = `/api/kyber/debug/logs?format=txt${lv ? `&level=${lv}` : ""}`;
      const r = await fetch(dlUrl, { headers: { Authorization: `Bearer ${t}` } });
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
    const token = this._hass.auth.data.access_token;
    const statusEl = btn.parentElement.querySelector("#dbg-export-status");
    const orig = btn.textContent;
    btn.disabled = true;
    btn.textContent = "⏳ exporting…";
    if (statusEl) statusEl.textContent = "";
    try {
      const resp = await fetch("/api/kyber/export/home-state", {
        headers: { Authorization: `Bearer ${token}` },
      });
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
      btn.textContent = "✓ downloaded";
      if (statusEl) statusEl.textContent = "Drop this file in chat to create test scenarios";
      setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 3000);
    } catch (err) {
      btn.textContent = `⚠ ${err.message}`;
      btn.disabled = false;
      if (statusEl) statusEl.textContent = "";
    }
  }

  async _downloadMemoryExport(btn) {
    const token = this._hass.auth.data.access_token;
    const statusEl = btn.parentElement.querySelector("#dbg-export-status");
    const orig = btn.textContent;
    btn.disabled = true;
    btn.textContent = "⏳ exporting…";
    if (statusEl) statusEl.textContent = "";
    try {
      const resp = await fetch("/api/kyber/export/memory", {
        headers: { Authorization: `Bearer ${token}` },
      });
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
      btn.textContent = "✓ downloaded";
      if (statusEl) statusEl.textContent = `${counts.good || 0} good · ${counts.consider || 0} consider · ${counts.skip || 0} skip`;
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
    const statusDiv = body?.querySelector?.("#dbg-deep-status");
    const btn = body?.querySelector?.("#dbg-mem-deep-analyze");
    if (!statusDiv) return false;
    try {
      const token = this._hass.auth.data.access_token;
      const r = await fetch("/api/kyber/knowledge/analyze_deep", {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!r.ok) return false;
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
        if (btn) { btn.disabled = true; btn.textContent = "🧬 Running…"; }
        const elapsed = job.started_at ? Math.round(Date.now() / 1000 - job.started_at) : 0;
        statusDiv.innerHTML = `
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
            <span style="font-size:1.1em">🔄</span>
            <strong>Deep analysis running</strong>
            <span style="color:var(--secondary-text-color)">${elapsed}s</span>
          </div>
          <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;text-align:center">
            <div><div style="font-size:1.4em;font-weight:bold">${job.run || 0}/${job.runs || 0}</div><div style="font-size:0.8em;opacity:.7">passes</div></div>
            <div><div style="font-size:1.4em;font-weight:bold">${job.analyzed || 0}</div><div style="font-size:0.8em;opacity:.7">analyzed</div></div>
            <div><div style="font-size:1.4em;font-weight:bold">${job.facts || 0}</div><div style="font-size:0.8em;opacity:.7">facts stored</div></div>
          </div>
          ${job.current_item ? `<div style="margin-top:4px;font-size:0.8em;opacity:.6">📄 ${this._escapeHtml(job.current_item)}</div>` : ""}
          ${job.errors ? `<div style="color:#e44;font-size:0.8em">⚠ ${job.errors} error(s)</div>` : ""}
        `;
        return true;
      } else {
        if (btn) { btn.disabled = false; btn.textContent = "🧬 Start deep analysis"; }
        const last = job.last_result || {};
        const dur = last.duration_s != null ? `${last.duration_s}s` : "";
        statusDiv.innerHTML = `
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
            <span style="font-size:1.1em">✅</span>
            <strong>Last analysis complete</strong>
            ${dur ? `<span style="color:var(--secondary-text-color)">${dur}</span>` : ""}
          </div>
          <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;text-align:center">
            <div><div style="font-size:1.4em;font-weight:bold">${last.runs_completed || 0}</div><div style="font-size:0.8em;opacity:.7">passes</div></div>
            <div><div style="font-size:1.4em;font-weight:bold">${last.analyzed || 0}</div><div style="font-size:0.8em;opacity:.7">analyzed</div></div>
            <div><div style="font-size:1.4em;font-weight:bold">${last.facts || 0}</div><div style="font-size:0.8em;opacity:.7">facts stored</div></div>
          </div>
          ${last.errors ? `<div style="color:#e44;font-size:0.8em">⚠ ${last.errors} error(s)</div>` : ""}
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
    const token = this._hass.auth.data.access_token;
    body.innerHTML = `<em>Loading test cases…</em>`;
    let data;
    try {
      const resp = await fetch("/api/kyber/prompt_tests", { headers: { Authorization: `Bearer ${token}` } });
      data = await resp.json();
    } catch (e) {
      body.innerHTML = `<div class="debug-error">Could not load test cases: ${this._escapeHtml(e.message)}</div>`;
      return;
    }
    const cases = data.cases || [];
    const totalPassed = cases.reduce((s, c) => s + (c.last_run?.passed || 0), 0);
    const totalAsserts = cases.reduce((s, c) => s + ((c.last_run?.passed || 0) + (c.last_run?.failed || 0)), 0);
    const pct = totalAsserts ? Math.round(100 * totalPassed / totalAsserts) : null;
    const failing = cases.filter(c => c.last_run?.failed > 0).length;

    body.innerHTML = `
      <div style="display:flex;gap:8px;align-items:center;margin-bottom:12px;flex-wrap:wrap">
        <button id="dbg-tests-run-all" class="btn-primary" style="font-size:0.85rem;padding:5px 14px">▶ Run all</button>
        <button id="dbg-tests-regenerate" class="btn-secondary" style="font-size:0.85rem;padding:5px 14px" title="Re-run all test questions on live HA to refresh snapshots">🔄 Regenerate</button>
        <label style="font-size:0.8rem;color:var(--secondary-text-color);cursor:pointer" title="Drop prompts.txt to batch-capture test cases">
          📁 <input id="dbg-tests-prompts-file" type="file" accept=".txt" style="display:none">batch capture
        </label>
        <span style="margin-left:auto;font-size:0.85rem;color:var(--secondary-text-color)" id="dbg-tests-status">
          ${pct !== null ? `${pct}% passing (${totalPassed}/${totalAsserts}) · ${failing} failing` : 'No runs yet'}
        </span>
      </div>
      <div style="display:flex;gap:6px;margin-bottom:10px" id="dbg-tests-filter">
        <button class="filter-btn active" data-filter="all">All (${cases.length})</button>
        <button class="filter-btn" data-filter="fail">Failing (${failing})</button>
        <button class="filter-btn" data-filter="pass">Passing (${cases.length - failing})</button>
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
      e.target.textContent = "⏳ Running…";
      const statusEl = body.querySelector("#dbg-tests-status");
      if (statusEl) statusEl.textContent = "Running assertions…";
      try {
        const r = await fetch("/api/kyber/prompt_tests/run", {
          method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
          body: JSON.stringify({}),
        });
        const result = await r.json();
        if (statusEl) {
          const s = result.summary || {};
          statusEl.textContent = `${Math.round((s.score || 0) * 100)}% passing (${s.passed}/${s.total_assertions}) · v${s.version} · ${s.model}`;
        }
        // Refresh
        await this._renderDebugTests(body);
      } catch (err) {
        if (statusEl) statusEl.textContent = `Error: ${err.message}`;
        e.target.disabled = false;
        e.target.textContent = "▶ Run all";
      }
    });

    // Regenerate
    body.querySelector("#dbg-tests-regenerate").addEventListener("click", async (e) => {
      e.target.disabled = true;
      e.target.textContent = "⏳ Regenerating…";
      try {
        await fetch("/api/kyber/prompt_tests/regenerate", {
          method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
          body: JSON.stringify({}),
        });
        e.target.textContent = "✅ Done";
        setTimeout(() => { e.target.textContent = "🔄 Regenerate"; e.target.disabled = false; }, 2000);
      } catch (err) {
        e.target.textContent = "❌ Error";
        e.target.disabled = false;
      }
    });
  }

  _renderTestsTable(body, cases, filter) {
    const table = body.querySelector("#dbg-tests-table");
    if (!table) return;
    const filtered = cases.filter(c => {
      if (filter === "fail") return c.last_run?.failed > 0;
      if (filter === "pass") return c.last_run && c.last_run.failed === 0;
      return true;
    });
    if (filtered.length === 0) {
      table.innerHTML = `<em style="color:var(--secondary-text-color)">No test cases found. Use 📋 Capture test in the Last turn tab to add some.</em>`;
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
            ` : `<em>Not yet run. Click "▶ Run all" to execute.</em>`}
          </div>
        </div>`;
    }).join("");
  }

  // ---------------------------------------------------------------------------
  // 📋 Capture test modal
  // ---------------------------------------------------------------------------

  _openCaptureTestModal(snap, triggerBtn) {
    const existing = this.shadowRoot.getElementById("capture-test-overlay");
    if (existing) existing.remove();

    const defaultContains = this._extractKeywords(snap.response_text || "");
    const overlay = document.createElement("div");
    overlay.id = "capture-test-overlay";
    overlay.style.cssText = "position:fixed;inset:0;background:#00000099;z-index:9999;display:flex;align-items:center;justify-content:center";
    overlay.innerHTML = `
      <div style="background:var(--card-background-color);border-radius:10px;padding:24px;max-width:520px;width:90%;max-height:85vh;overflow-y:auto;box-shadow:0 8px 32px #0006">
        <h3 style="margin:0 0 16px">📋 Capture regression test</h3>
        <label style="font-size:0.85rem;display:block;margin-bottom:4px">Label</label>
        <input id="ct-label" type="text" value="${this._escapeAttr(snap.intent || "New test")}"
          style="width:100%;box-sizing:border-box;padding:6px 10px;border-radius:6px;border:1px solid var(--divider-color);background:var(--secondary-background-color);color:var(--primary-text-color);font-size:0.9rem;margin-bottom:12px">
        <label style="font-size:0.85rem;display:block;margin-bottom:4px">Response must contain (comma-separated)</label>
        <input id="ct-contains" type="text" value="${this._escapeAttr(defaultContains.join(", "))}"
          style="width:100%;box-sizing:border-box;padding:6px 10px;border-radius:6px;border:1px solid var(--divider-color);background:var(--secondary-background-color);color:var(--primary-text-color);font-size:0.9rem;margin-bottom:12px">
        <label style="font-size:0.85rem;display:block;margin-bottom:4px">Response must NOT contain (comma-separated)</label>
        <input id="ct-not-contains" type="text" placeholder="unknown, error, ..."
          style="width:100%;box-sizing:border-box;padding:6px 10px;border-radius:6px;border:1px solid var(--divider-color);background:var(--secondary-background-color);color:var(--primary-text-color);font-size:0.9rem;margin-bottom:12px">
        <label style="font-size:0.85rem;display:block;margin-bottom:4px">Describe the ideal response (for documentation)</label>
        <textarea id="ct-ideal" rows="3" placeholder="The AI should mention the temperature and the correct room name…"
          style="width:100%;box-sizing:border-box;padding:6px 10px;border-radius:6px;border:1px solid var(--divider-color);background:var(--secondary-background-color);color:var(--primary-text-color);font-size:0.9rem;margin-bottom:16px;resize:vertical"></textarea>
        <div id="ct-status" style="font-size:0.85rem;margin-bottom:12px;min-height:20px"></div>
        <div style="display:flex;gap:8px;justify-content:flex-end">
          <button id="ct-cancel" class="btn-secondary" style="padding:6px 16px">Cancel</button>
          <button id="ct-save" class="btn-primary" style="padding:6px 16px">💾 Save test case</button>
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
      saveBtn.textContent = "⏳ Saving…";

      const token = this._hass.auth.data.access_token;
      try {
        const resp = await fetch("/api/kyber/prompt_tests/capture", {
          method: "POST",
          headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
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
        statusEl.innerHTML = `✅ Saved as <code>${this._escapeHtml(result.id)}</code>`;
        saveBtn.textContent = "✅ Saved";
        setTimeout(() => overlay.remove(), 2000);
      } catch (err) {
        statusEl.innerHTML = `❌ ${this._escapeHtml(err.message)}`;
        saveBtn.disabled = false;
        saveBtn.textContent = "💾 Save test case";
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
};
