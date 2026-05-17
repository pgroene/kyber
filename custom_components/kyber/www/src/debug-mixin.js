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
    const filtered = (this._debugMemFilter || "all") === "review"
      ? entries.filter((e) => e.needs_review)
      : entries;
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
        <button id="dbg-mem-add">➕ Add fact</button>
        <button id="dbg-mem-analyze">🔍 Analyze my home</button>
        <button id="dbg-mem-deep-analyze">🧬 Start deep analysis</button>
        <label style="display:flex;align-items:center;gap:4px;font-size:0.85em">
          <input type="checkbox" id="dbg-deep-force"> Re-analyze all
        </label>
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

    // Show status if a job is already running / recently finished
    this._refreshDeepAnalysisStatus(body);
    this._wireKnowledgeRowEvents(body, filtered, categories);
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
