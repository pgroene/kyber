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
    body.innerHTML = `
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
    const catRows = Object.entries(k.by_category || {}).map(([cat, n]) =>
      `<tr><td><code>${this._escapeHtml(cat)}</code></td><td>${n}</td></tr>`,
    ).join("");
    body.innerHTML = `
      <h3>Runtime</h3>
      <table class="dbg-kv">
        <tr><th>AI Task entity</th><td><code>${this._escapeHtml(data.ai_task_entity || "—")}</code></td></tr>
        <tr><th>Autopilot</th><td>${this._autopilot ? "ON ⚡" : "OFF"}</td></tr>
        <tr><th>Session</th><td>${this._escapeHtml(this._sessionName || "—")}</td></tr>
        <tr><th>Tool history size</th><td>${data.tool_history_size}</td></tr>
      </table>
      <h3>Knowledge store</h3>
      <table class="dbg-kv">
        <tr><th>Total entries</th><td>${k.total ?? 0}</td></tr>
        <tr><th>Needs review</th><td>${k.needs_review ?? 0}</td></tr>
        <tr><th>Total hits</th><td>${k.total_hits ?? 0}</td></tr>
      </table>
      ${catRows ? `<h4>By category</h4><table class="dbg-kv">${catRows}</table>` : ""}
      <h3>Last turn</h3>
      ${lt ? `
        <table class="dbg-kv">
          <tr><th>When</th><td>${lt.ts ? new Date(lt.ts * 1000).toLocaleString() : "—"}</td></tr>
          <tr><th>Elapsed</th><td>${lt.elapsed_ms} ms</td></tr>
          <tr><th>Intent</th><td><code>${this._escapeHtml(lt.intent || "—")}</code></td></tr>
          <tr><th>Prompt size</th><td>${lt.char_count?.toLocaleString() ?? "?"} chars (~${lt.approx_tokens?.toLocaleString() ?? "?"} tokens)</td></tr>
        </table>
      ` : "<em>No turn captured yet.</em>"}
    `;
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
};
