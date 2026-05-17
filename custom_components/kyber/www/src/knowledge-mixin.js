export const KnowledgeMixin = (Base) => class extends Base {
  async _handleKnowledgeCommand(argStr) {
    const parts = argStr.split(/\s+/);
    const sub = (parts[0] || "").toLowerCase();
    const rest = parts.slice(1).join(" ").trim();
    const token = this._hass.auth.data.access_token;

    if (sub === "list" || sub === "") {
      const data = await this._fetchKnowledge();
      this._renderKnowledgePanel(data, { interactive: true });
      return;
    }
    if (sub === "search") {
      const data = await this._fetchKnowledge(rest);
      this._renderKnowledgePanel(data, { interactive: true, query: rest });
      return;
    }
    if (sub === "analyze") {
      this._appendMessage("🔍 Analyzing automations, scenes, and scripts…", "assistant");
      try {
        const resp = await fetch("/api/kyber/knowledge/analyze", {
          headers: { Authorization: `Bearer ${token}` },
        });
        const data = await resp.json();
        this._renderAnalyzeProposals(data);
      } catch (err) {
        this._appendMessage(`Analyze failed: ${err.message}`, "assistant");
      }
      return;
    }
    if (sub === "delete" && rest) {
      try {
        const resp = await fetch(`/api/kyber/knowledge?id=${encodeURIComponent(rest)}`, {
          method: "DELETE",
          headers: { Authorization: `Bearer ${token}` },
        });
        if (resp.ok) {
          this._appendMessage(`✓ Deleted memory entry \`${rest}\``, "assistant");
        } else {
          this._appendMessage(`Delete failed: ${resp.status}`, "assistant");
        }
      } catch (err) {
        this._appendMessage(`Delete failed: ${err.message}`, "assistant");
      }
      return;
    }
    this._appendMessage(
      "Usage: `/knowledge` (list), `/knowledge search <q>`, `/knowledge analyze`, `/knowledge delete <id>`",
      "assistant",
    );
  }

  async _fetchKnowledge(query = "") {
    const token = this._hass.auth.data.access_token;
    const url = query
      ? `/api/kyber/knowledge?q=${encodeURIComponent(query)}`
      : "/api/kyber/knowledge";
    const resp = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
    return resp.json();
  }

  _renderKnowledgePanel(data, opts = {}) {
    const entries = data.entries || [];
    const categories = data.categories || ["area_alias", "entity_note", "procedure", "device_chain", "general"];
    const history = this.shadowRoot.getElementById("chat-history");
    if (!history) return;

    const card = document.createElement("div");
    card.className = "chat-message assistant kyber-knowledge-panel";
    const reviewCount = data.needs_review_count || 0;
    const header = `
      <div class="kn-header">
        <strong>🧠 Memory${opts.query ? ` — results for "${this._escapeHtml(opts.query)}"` : ""}</strong>
        <span class="kn-count">${entries.length} entr${entries.length === 1 ? "y" : "ies"}</span>
        ${reviewCount > 0 ? `<button class="btn-kn-review-filter" title="Show only entries flagged by feedback">⚠ ${reviewCount} need review</button>` : ""}
      </div>
      <div class="kn-actions-bar">
        <button class="btn-kn-analyze">🔍 Analyze my home</button>
        <button class="btn-kn-add">➕ Add fact</button>
      </div>
    `;
    if (entries.length === 0) {
      card.innerHTML = header + `<div class="kn-empty">No saved knowledge yet. Click "Analyze my home" or "Add fact".</div>`;
    } else {
      const rows = entries.map((e) => this._renderKnowledgeRow(e, categories)).join("");
      card.innerHTML = header + `<div class="kn-list">${rows}</div>`;
    }
    history.appendChild(card);
    history.scrollTop = history.scrollHeight;

    card.querySelector(".btn-kn-analyze")?.addEventListener("click", () => this._handleKnowledgeCommand("analyze"));
    card.querySelector(".btn-kn-add")?.addEventListener("click", () => this._showKnowledgeEditor(null, categories, card));
    card.querySelector(".btn-kn-review-filter")?.addEventListener("click", async () => {
      const token = this._hass.auth.data.access_token;
      const resp = await fetch("/api/kyber/knowledge?needs_review=1", { headers: { Authorization: `Bearer ${token}` } });
      const d = await resp.json();
      card.remove();
      this._renderKnowledgePanel(d, { interactive: true, query: "needs review" });
    });
    card.querySelectorAll("[data-kn-id]").forEach((row) => {
      const id = row.getAttribute("data-kn-id");
      row.querySelector(".btn-kn-edit")?.addEventListener("click", () => {
        const entry = entries.find((e) => e.id === id);
        this._showKnowledgeEditor(entry, categories, card);
      });
      row.querySelector(".btn-kn-del")?.addEventListener("click", () => this._deleteKnowledgeEntry(id, row));
      row.querySelector(".btn-kn-clear")?.addEventListener("click", async () => {
        const token = this._hass.auth.data.access_token;
        await fetch("/api/kyber/knowledge", {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
          body: JSON.stringify({ id, needs_review: false }),
        });
        row.classList.remove("kn-row-flagged");
        row.querySelector(".kn-needs-review")?.remove();
        row.querySelector(".btn-kn-clear")?.remove();
      });
      row.querySelectorAll(".kn-star").forEach((star) => {
        star.addEventListener("click", () => {
          const r = parseInt(star.getAttribute("data-rating"), 10);
          this._rateKnowledgeEntry(id, r, row);
        });
      });
    });
  }

  _renderKnowledgeRow(e, categories) {
    const tags = (e.tags || []).map((t) => `<span class="kn-tag">${this._escapeHtml(t)}</span>`).join("");
    const stars = [1, 2, 3, 4, 5].map((i) =>
      `<span class="kn-star ${(e.user_rating || 0) >= i ? "filled" : ""}" data-rating="${i}" title="Rate ${i}/5">★</span>`,
    ).join("");
    const conf = Math.round((e.confidence || 0) * 100);
    const prov = e.provenance ? `<div class="kn-prov">📌 ${this._escapeHtml(e.provenance)}</div>` : "";
    const reviewBadge = e.needs_review ? `<span class="kn-needs-review" title="Flagged by feedback — please verify">⚠ needs review</span>` : "";
    const fb = (e.feedback || []).slice(-3).reverse();
    const fbBlock = fb.length
      ? `<details class="kn-fb"><summary>Feedback (${(e.feedback || []).length})</summary>${fb.map((f) => `<div class="kn-fb-item">${f.auto ? "🤖" : "👤"} ${f.rating}/5 ${f.notes ? "— " + this._escapeHtml(f.notes) : ""}</div>`).join("")}</details>`
      : "";
    return `
      <div class="kn-row ${e.needs_review ? "kn-row-flagged" : ""}" data-kn-id="${e.id}">
        <div class="kn-row-head">
          <span class="kn-cat">${this._escapeHtml(e.category || "general")}</span>
          ${e.subject ? `<span class="kn-subj">${this._escapeHtml(e.subject)}</span>` : ""}
          ${reviewBadge}
          <span class="kn-conf" title="Confidence">${conf}%</span>
          <span class="kn-stars" title="Your rating">${stars}</span>
          <span class="kn-row-actions">
            ${e.needs_review ? `<button class="btn-kn-clear" title="Mark resolved">✓</button>` : ""}
            <button class="btn-kn-edit" title="Edit / hint">✏️</button>
            <button class="btn-kn-del" title="Delete">🗑️</button>
          </span>
        </div>
        <div class="kn-content">${this._escapeHtml(e.content || "")}</div>
        ${tags ? `<div class="kn-tags">${tags}</div>` : ""}
        ${prov}
        ${fbBlock}
        <div class="kn-meta">id: <code>${e.id}</code> · source: ${this._escapeHtml(e.source || "manual")} · hits: ${e.hits || 0}</div>
      </div>
    `;
  }

  _showKnowledgeEditor(entry, categories, parentCard) {
    const isNew = !entry;
    const e = entry || { category: "general", subject: "", content: "", tags: [], confidence: 0.9, provenance: "" };
    const dlg = document.createElement("div");
    dlg.className = "kn-editor";
    dlg.innerHTML = `
      <div class="kn-editor-inner">
        <h3>${isNew ? "Add memory entry" : "Edit memory entry"}</h3>
        <label>Category
          <select class="kn-f-cat">${categories.map((c) => `<option ${c === e.category ? "selected" : ""}>${c}</option>`).join("")}</select>
        </label>
        <label>Subject (entity_id, area, or term)
          <input class="kn-f-subj" value="${this._escapeAttr(e.subject || "")}" placeholder="e.g. werkkamer or light.tv">
        </label>
        <label>Content / fact
          <textarea class="kn-f-content" rows="3" placeholder="What should Kyber remember?">${this._escapeHtml(e.content || "")}</textarea>
        </label>
        <label>Tags (comma-separated)
          <input class="kn-f-tags" value="${this._escapeAttr((e.tags || []).join(", "))}">
        </label>
        <label>Provenance / hint — where did this come from? how to verify?
          <input class="kn-f-prov" value="${this._escapeAttr(e.provenance || "")}" placeholder="e.g. User said in chat 2025-05-17">
        </label>
        <label>Confidence (0–100%)
          <input type="range" min="0" max="100" value="${Math.round((e.confidence || 0.9) * 100)}" class="kn-f-conf">
          <output class="kn-f-conf-val">${Math.round((e.confidence || 0.9) * 100)}%</output>
        </label>
        <div class="kn-editor-buttons">
          <button class="btn-kn-cancel">Cancel</button>
          <button class="btn-kn-save">${isNew ? "Add" : "Save"}</button>
        </div>
      </div>
    `;
    this.shadowRoot.appendChild(dlg);
    const confSlider = dlg.querySelector(".kn-f-conf");
    const confOut = dlg.querySelector(".kn-f-conf-val");
    confSlider.addEventListener("input", () => (confOut.textContent = confSlider.value + "%"));
    dlg.querySelector(".btn-kn-cancel").addEventListener("click", () => dlg.remove());
    dlg.querySelector(".btn-kn-save").addEventListener("click", async () => {
      const body = {
        ...(isNew ? {} : { id: e.id }),
        category: dlg.querySelector(".kn-f-cat").value,
        subject: dlg.querySelector(".kn-f-subj").value.trim(),
        content: dlg.querySelector(".kn-f-content").value.trim(),
        tags: dlg.querySelector(".kn-f-tags").value.split(",").map((t) => t.trim()).filter(Boolean),
        provenance: dlg.querySelector(".kn-f-prov").value.trim(),
        confidence: parseInt(confSlider.value, 10) / 100,
      };
      if (!body.content) {
        dlg.querySelector(".kn-f-content").focus();
        return;
      }
      try {
        const token = this._hass.auth.data.access_token;
        const resp = await fetch("/api/kyber/knowledge", {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
          body: JSON.stringify(body),
        });
        if (!resp.ok) {
          alert(`Save failed: ${resp.status}`);
          return;
        }
        dlg.remove();
        parentCard?.remove();
        await this._handleKnowledgeCommand("list");
      } catch (err) {
        alert(`Save failed: ${err.message}`);
      }
    });
  }

  async _deleteKnowledgeEntry(id, rowEl) {
    if (!confirm("Delete this memory entry?")) return;
    try {
      const token = this._hass.auth.data.access_token;
      const resp = await fetch(`/api/kyber/knowledge?id=${encodeURIComponent(id)}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (resp.ok) rowEl.remove();
    } catch (err) {
      alert(`Delete failed: ${err.message}`);
    }
  }

  async _rateKnowledgeEntry(id, rating, rowEl) {
    try {
      const token = this._hass.auth.data.access_token;
      const resp = await fetch("/api/kyber/knowledge", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ id, user_rating: rating }),
      });
      if (resp.ok) {
        rowEl.querySelectorAll(".kn-star").forEach((s) => {
          const r = parseInt(s.getAttribute("data-rating"), 10);
          s.classList.toggle("filled", r <= rating);
        });
      }
    } catch (err) {
      console.error("Rate failed", err);
    }
  }

  _renderAnalyzeProposals(data) {
    const history = this.shadowRoot.getElementById("chat-history");
    if (!history) return;
    const proposals = data.proposals || [];
    const stats = data.stats || {};
    const card = document.createElement("div");
    card.className = "chat-message assistant kyber-knowledge-panel";
    if (proposals.length === 0) {
      card.innerHTML = `<div class="kn-header"><strong>🔍 Analysis complete</strong></div>
        <div class="kn-empty">No new proposals. Scanned ${stats.automations_scanned || 0} automations, ${stats.scenes_scanned || 0} scenes, ${stats.scripts_scanned || 0} scripts.</div>`;
      history.appendChild(card);
      return;
    }
    const rows = proposals.map((p, idx) => `
      <div class="kn-row kn-proposal" data-idx="${idx}">
        <div class="kn-row-head">
          <input type="checkbox" class="kn-prop-check" checked />
          <span class="kn-cat">${this._escapeHtml(p.category || "general")}</span>
          ${p.subject ? `<span class="kn-subj">${this._escapeHtml(p.subject)}</span>` : ""}
          <span class="kn-conf">${Math.round((p.confidence || 0) * 100)}%</span>
        </div>
        <div class="kn-content">${this._escapeHtml(p.content || "")}</div>
        ${p.provenance ? `<div class="kn-prov">📌 ${this._escapeHtml(p.provenance)}</div>` : ""}
      </div>
    `).join("");
    card.innerHTML = `
      <div class="kn-header">
        <strong>🔍 Analyzed your home — ${proposals.length} proposal${proposals.length === 1 ? "" : "s"}</strong>
      </div>
      <div class="kn-empty">Scanned ${stats.automations_scanned || 0} automations, ${stats.scenes_scanned || 0} scenes, ${stats.scripts_scanned || 0} scripts. Untick anything you don't want saved.</div>
      <div class="kn-list">${rows}</div>
      <div class="kn-editor-buttons">
        <button class="btn-kn-cancel">Cancel</button>
        <button class="btn-kn-save-selected">Save selected</button>
      </div>
    `;
    history.appendChild(card);
    history.scrollTop = history.scrollHeight;
    card.querySelector(".btn-kn-cancel").addEventListener("click", () => card.remove());
    card.querySelector(".btn-kn-save-selected").addEventListener("click", async () => {
      const selected = [];
      card.querySelectorAll(".kn-prop-check").forEach((cb, i) => {
        if (cb.checked) selected.push(proposals[i]);
      });
      if (selected.length === 0) {
        card.remove();
        return;
      }
      try {
        const token = this._hass.auth.data.access_token;
        const resp = await fetch("/api/kyber/knowledge/analyze", {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
          body: JSON.stringify({ proposals: selected }),
        });
        const result = await resp.json();
        card.querySelector(".kn-empty").textContent = `✓ Saved ${result.count || 0} entries to memory.`;
        card.querySelector(".kn-editor-buttons").remove();
      } catch (err) {
        alert(`Save failed: ${err.message}`);
      }
    });
  }

  _wireKnowledgeRowEvents(root, entries, categories) {
    root.querySelectorAll("[data-kn-id]").forEach((row) => {
      const id = row.getAttribute("data-kn-id");
      row.querySelector(".btn-kn-edit")?.addEventListener("click", () => {
        const entry = entries.find((e) => e.id === id);
        this._showKnowledgeEditor(entry, categories, null);
      });
      row.querySelector(".btn-kn-del")?.addEventListener("click", () => this._deleteKnowledgeEntry(id, row));
      row.querySelector(".btn-kn-clear")?.addEventListener("click", async () => {
        const token = this._hass.auth.data.access_token;
        await fetch("/api/kyber/knowledge", {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
          body: JSON.stringify({ id, needs_review: false }),
        });
        this._renderDebugTab(this._debugTab);
      });
      row.querySelectorAll(".kn-star").forEach((star) => {
        star.addEventListener("click", () => {
          const r = parseInt(star.getAttribute("data-rating"), 10);
          this._rateKnowledgeEntry(id, r, row);
        });
      });
    });
  }

  _renderKnowledgeRowWithScore(entry, picked) {
    // Same as _renderKnowledgeRow but adds a similarity-score badge and a Refine button
    const base = this._renderKnowledgeRow(entry, []);
    const scoreBadge = (picked && typeof picked.score === "number")
      ? `<span class="kn-score" title="similarity score for last turn">score ${picked.score.toFixed(2)}</span>`
      : "";
    // Inject score badge + refine button into the row head
    return base
      .replace(
        '<span class="kn-row-actions">',
        `${scoreBadge}<button class="btn-kn-refine" title="Refine this fact — tell Kyber how it should be">✎ refine</button><span class="kn-row-actions">`,
      );
  }

  _showRefineDialog(id, entry) {
    const dlg = document.createElement("div");
    dlg.className = "kn-editor";
    dlg.innerHTML = `
      <div class="kn-editor-inner">
        <h3>Refine memory entry</h3>
        <p style="margin:0;color:var(--secondary-text-color);font-size:11px;">
          ${this._escapeHtml(entry.content || "")}
        </p>
        <label>How should Kyber update this fact?
          <textarea class="kn-f-refine" rows="4" placeholder="e.g. werkkamer is actually called 'home office' and contains light.desk + light.ceiling_office"></textarea>
        </label>
        <label>Optional new rating
          <select class="kn-f-rate">
            <option value="">— keep as is —</option>
            <option value="5">5 — perfect</option>
            <option value="4">4 — good</option>
            <option value="3">3 — okay</option>
            <option value="2">2 — wrong, please fix</option>
            <option value="1">1 — useless</option>
          </select>
        </label>
        <div class="kn-editor-buttons">
          <button class="btn-kn-cancel">Cancel</button>
          <button class="btn-kn-save">Apply refinement</button>
        </div>
      </div>
    `;
    this.shadowRoot.appendChild(dlg);
    dlg.querySelector(".btn-kn-cancel").addEventListener("click", () => dlg.remove());
    dlg.querySelector(".btn-kn-save").addEventListener("click", async () => {
      const hint = dlg.querySelector(".kn-f-refine").value.trim();
      const ratingStr = dlg.querySelector(".kn-f-rate").value;
      if (!hint && !ratingStr) { dlg.remove(); return; }
      const token = this._hass.auth.data.access_token;
      try {
        if (hint) {
          const newContent = (entry.content || "") + "\n\nRefinement: " + hint;
          const newProv = (entry.provenance ? entry.provenance + "; " : "") + `User refined ${new Date().toISOString().slice(0, 10)}`;
          await fetch("/api/kyber/knowledge", {
            method: "POST",
            headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
            body: JSON.stringify({ id, content: newContent, provenance: newProv, needs_review: false }),
          });
        }
        if (ratingStr) {
          await fetch("/api/kyber/knowledge/feedback", {
            method: "POST",
            headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
            body: JSON.stringify({ rating: parseInt(ratingStr, 10), knowledge_ids: [id], auto: false }),
          });
        }
        dlg.remove();
        this._renderDebugTab("last_turn");
      } catch (err) {
        alert(`Refine failed: ${err.message}`);
      }
    });
  }
};
