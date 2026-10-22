export const KnowledgeMixin = (Base) => class extends Base {
  async _handleKnowledgeCommand(argStr) {
    const parts = argStr.split(/\s+/);
    const sub = (parts[0] || "").toLowerCase();
    const rest = parts.slice(1).join(" ").trim();
    const t = this._t || ((k) => k);

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
      this._appendMessage(t("kn_analyzing"), "assistant");
      try {
        const resp = await this._hass.fetchWithAuth("/api/kyber/knowledge/analyze");
        const data = await resp.json();
        this._renderAnalyzeProposals(data);
      } catch (err) {
        this._appendMessage(t("kn_analyze_failed", { msg: err.message }), "assistant");
      }
      return;
    }
    if (sub === "delete" && rest) {
      try {
        const resp = await this._hass.fetchWithAuth(`/api/kyber/knowledge?id=${encodeURIComponent(rest)}`, {
          method: "DELETE",
        });
        if (resp.ok) {
          this._appendMessage(t("kn_deleted", { id: rest }), "assistant");
        } else {
          this._appendMessage(t("kn_delete_failed", { msg: resp.status }), "assistant");
        }
      } catch (err) {
        this._appendMessage(t("kn_delete_failed", { msg: err.message }), "assistant");
      }
      return;
    }
    if (sub === "add" && rest) {
      try {
        const resp = await this._hass.fetchWithAuth("/api/kyber/knowledge", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ category: "general", content: rest, source: "user", provenance: "Added via /memory add" }),
        });
        const d = await resp.json();
        if (resp.ok) {
          this._appendMessage(t("kn_saved", { text: this._escapeHtml(rest), id: d.entry?.id }), "assistant");
        } else {
          this._appendMessage(t("kn_save_failed_msg", { msg: d.message || resp.status }), "assistant");
        }
      } catch (err) {
        this._appendMessage(t("kn_error", { msg: err.message }), "assistant");
      }
      return;
    }
    if (sub === "stats") {
      const data = await this._fetchKnowledge();
      const entries = data.entries || [];
      const by_cat = {};
      const by_src = {};
      entries.forEach((e) => {
        by_cat[e.category] = (by_cat[e.category] || 0) + 1;
        by_src[e.source || "unknown"] = (by_src[e.source || "unknown"] || 0) + 1;
      });
      const catRows = Object.entries(by_cat).map(([k, v]) => `| ${k} | ${v} |`).join("\n");
      const srcRows = Object.entries(by_src).map(([k, v]) => `| ${k} | ${v} |`).join("\n");
      this._appendMessage(
        `${t("kn_stats_title", { n: entries.length })}\n\n**${t("kn_stats_by_category")}**\n| ${t("kn_stats_col_category")} | ${t("kn_stats_col_count")} |\n|---|---|\n${catRows}\n\n**${t("kn_stats_by_source")}**\n| ${t("kn_stats_col_source")} | ${t("kn_stats_col_count")} |\n|---|---|\n${srcRows}`,
        "assistant",
      );
      return;
    }
    if (sub === "deep") {
      this._appendMessage(t("kn_deep_starting"), "assistant");
      try {
        const resp = await this._hass.fetchWithAuth("/api/kyber/knowledge/analyze_deep", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ background: true, runs: 6, limit: 5, force: false }),
        });
        const d = await resp.json();
        if (resp.ok) {
          this._appendMessage(t(d.status === "already_running" ? "kn_deep_already_running" : "kn_deep_started"), "assistant");
        } else {
          this._appendMessage(t("kn_failed", { msg: d.message || resp.status }), "assistant");
        }
      } catch (err) {
        this._appendMessage(t("kn_error", { msg: err.message }), "assistant");
      }
      return;
    }
    this._appendMessage(
      `**${t("kn_help_header")}**\n` + "`/memory` · `/memory list` · `/memory search <query>` · `/memory add <text>` · `/memory delete <id>` · `/memory analyze` · `/memory deep` · `/memory stats`",
      "assistant",
    );
  }

  async _fetchKnowledge(query = "") {
    const url = query
      ? `/api/kyber/knowledge?q=${encodeURIComponent(query)}`
      : "/api/kyber/knowledge";
    const resp = await this._hass.fetchWithAuth(url);
    return resp.json();
  }

  _renderKnowledgePanel(data, opts = {}) {
    const entries = data.entries || [];
    const categories = data.categories || ["area_alias", "entity_note", "procedure", "device_chain", "general"];
    const history = this.shadowRoot.getElementById("chat-history");
    if (!history) return;

    const t = this._t || ((k) => k);
    const card = document.createElement("div");
    card.className = "chat-message assistant kyber-knowledge-panel";
    const reviewCount = data.needs_review_count || 0;
    const header = `
      <div class="kn-header">
        <strong>${opts.query ? t("kn_title_results", { query: this._escapeHtml(opts.query) }) : t("kn_title")}</strong>
        <span class="kn-count">${t(entries.length === 1 ? "kn_count_one" : "kn_count_many", { n: entries.length })}</span>
        ${reviewCount > 0 ? `<button class="btn-kn-review-filter" title="${this._escapeAttr(t("kn_review_filter_title"))}">${t("kn_review_filter", { n: reviewCount })}</button>` : ""}
      </div>
      <div class="kn-actions-bar">
        <button class="btn-kn-analyze">${t("kn_btn_analyze")}</button>
        <button class="btn-kn-add">${t("kn_btn_add_fact")}</button>
      </div>
    `;
    if (entries.length === 0) {
      const emptyMsg = this._t ? this._t("knowledge_empty") : "No saved knowledge yet.";
      card.innerHTML = header + `<div class="kn-empty">${emptyMsg} ${this._escapeHtml(t("kn_empty_hint"))}</div>`;
    } else {
      const rows = entries.map((e) => this._renderKnowledgeRow(e, categories)).join("");
      card.innerHTML = header + `<div class="kn-list">${rows}</div>`;
    }
    history.appendChild(card);
    history.scrollTop = history.scrollHeight;

    card.querySelector(".btn-kn-analyze")?.addEventListener("click", () => this._handleKnowledgeCommand("analyze"));
    card.querySelector(".btn-kn-add")?.addEventListener("click", () => this._showKnowledgeEditor(null, categories, card));
    card.querySelector(".btn-kn-review-filter")?.addEventListener("click", async () => {
      const resp = await this._hass.fetchWithAuth("/api/kyber/knowledge?needs_review=1");
      const d = await resp.json();
      card.remove();
      this._renderKnowledgePanel(d, { interactive: true, query: t("kn_query_needs_review") });
    });
    card.querySelectorAll("[data-kn-id]").forEach((row) => {
      const id = row.getAttribute("data-kn-id");
      row.querySelector(".btn-kn-edit")?.addEventListener("click", () => {
        const entry = entries.find((e) => e.id === id);
        this._showKnowledgeEditor(entry, categories, card);
      });
      row.querySelector(".btn-kn-del")?.addEventListener("click", () => this._deleteKnowledgeEntry(id, row));
      row.querySelector(".btn-kn-clear")?.addEventListener("click", async () => {
        await this._hass.fetchWithAuth("/api/kyber/knowledge", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
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
    const t = this._t || ((k) => k);
    const tags = (e.tags || []).map((tag) => `<span class="kn-tag">${this._escapeHtml(tag)}</span>`).join("");
    const stars = [1, 2, 3, 4, 5].map((i) =>
      `<span class="kn-star ${(e.user_rating || 0) >= i ? "filled" : ""}" data-rating="${i}" title="${this._escapeAttr(t("kn_rate_title", { i }))}">★</span>`,
    ).join("");
    const conf = Math.round((e.confidence || 0) * 100);
    const prov = e.provenance ? `<div class="kn-prov">📌 ${this._escapeHtml(e.provenance)}</div>` : "";
    const reviewBadge = e.needs_review ? `<span class="kn-needs-review" title="${this._escapeAttr(t("kn_needs_review_title"))}">${t("kn_needs_review")}</span>` : "";
    const fb = (e.feedback || []).slice(-3).reverse();
    const fbBlock = fb.length
      ? `<details class="kn-fb"><summary>${t("kn_feedback", { n: (e.feedback || []).length })}</summary>${fb.map((f) => `<div class="kn-fb-item">${f.auto ? "🤖" : "👤"} ${f.rating}/5 ${f.notes ? "— " + this._escapeHtml(f.notes) : ""}</div>`).join("")}</details>`
      : "";
    return `
      <div class="kn-row ${e.needs_review ? "kn-row-flagged" : ""}" data-kn-id="${e.id}">
        <div class="kn-row-head">
          <span class="kn-cat">${this._escapeHtml(e.category || "general")}</span>
          ${e.subject ? `<span class="kn-subj">${this._escapeHtml(e.subject)}</span>` : ""}
          ${reviewBadge}
          <span class="kn-conf" title="${this._escapeAttr(t("kn_confidence"))}">${conf}%</span>
          <span class="kn-stars" title="${this._escapeAttr(t("kn_your_rating"))}">${stars}</span>
          <span class="kn-row-actions">
            ${e.needs_review ? `<button class="btn-kn-clear" title="${this._escapeAttr(t("kn_mark_resolved"))}">✓</button>` : ""}
            <button class="btn-kn-edit" title="${this._escapeAttr(t("kn_edit_hint"))}">✏️</button>
            <button class="btn-kn-del" title="${this._escapeAttr(t("kn_delete"))}">🗑️</button>
          </span>
        </div>
        <div class="kn-content">${this._escapeHtml(e.content || "")}</div>
        ${tags ? `<div class="kn-tags">${tags}</div>` : ""}
        ${prov}
        ${fbBlock}
        <div class="kn-meta">id: <code>${e.id}</code> · ${t("kn_meta_source", { source: this._escapeHtml(e.source || "manual") })} · ${t("kn_meta_hits", { n: e.hits || 0 })}</div>
      </div>
    `;
  }

  _showKnowledgeEditor(entry, categories, parentCard) {
    const isNew = !entry;
    const t = this._t || ((k) => k);
    const e = entry || { category: "general", subject: "", content: "", tags: [], confidence: 0.9, provenance: "" };
    const dlg = document.createElement("div");
    dlg.className = "kn-editor";
    dlg.innerHTML = `
      <div class="kn-editor-inner">
        <h3>${t(isNew ? "kn_editor_add_title" : "kn_editor_edit_title")}</h3>
        <label>${t("kn_f_category")}
          <select class="kn-f-cat">${categories.map((c) => `<option ${c === e.category ? "selected" : ""}>${c}</option>`).join("")}</select>
        </label>
        <label>${t("kn_f_subject")}
          <input class="kn-f-subj" value="${this._escapeAttr(e.subject || "")}" placeholder="${this._escapeAttr(t("kn_f_subject_ph"))}">
        </label>
        <label>${t("kn_f_content")}
          <textarea class="kn-f-content" rows="3" placeholder="${this._escapeAttr(t("kn_f_content_ph"))}">${this._escapeHtml(e.content || "")}</textarea>
        </label>
        <label>${t("kn_f_tags")}
          <input class="kn-f-tags" value="${this._escapeAttr((e.tags || []).join(", "))}">
        </label>
        <label>${t("kn_f_provenance")}
          <input class="kn-f-prov" value="${this._escapeAttr(e.provenance || "")}" placeholder="${this._escapeAttr(t("kn_f_provenance_ph"))}">
        </label>
        <label>${t("kn_f_confidence")}
          <input type="range" min="0" max="100" value="${Math.round((e.confidence || 0.9) * 100)}" class="kn-f-conf">
          <output class="kn-f-conf-val">${Math.round((e.confidence || 0.9) * 100)}%</output>
        </label>
        <div class="kn-editor-buttons">
          <button class="btn-kn-cancel">${t("cmd_cancel")}</button>
          <button class="btn-kn-save">${isNew ? t("kn_add") : t("btn_save")}</button>
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
        const resp = await this._hass.fetchWithAuth("/api/kyber/knowledge", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!resp.ok) {
          alert(t("kn_save_failed", { msg: resp.status }));
          return;
        }
        dlg.remove();
        parentCard?.remove();
        await this._handleKnowledgeCommand("list");
      } catch (err) {
        alert(t("kn_save_failed", { msg: err.message }));
      }
    });
  }

  async _deleteKnowledgeEntry(id, rowEl) {
    const t = this._t || ((k) => k);
    if (!confirm(t("kn_confirm_delete"))) return;
    try {
      const resp = await this._hass.fetchWithAuth(`/api/kyber/knowledge?id=${encodeURIComponent(id)}`, {
        method: "DELETE",
      });
      if (resp.ok) rowEl.remove();
    } catch (err) {
      alert(t("kn_delete_failed", { msg: err.message }));
    }
  }

  async _rateKnowledgeEntry(id, rating, rowEl) {
    try {
      const resp = await this._hass.fetchWithAuth("/api/kyber/knowledge", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
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
    const t = this._t || ((k) => k);
    const scanned = {
      automations: stats.automations_scanned || 0,
      scenes: stats.scenes_scanned || 0,
      scripts: stats.scripts_scanned || 0,
    };
    const card = document.createElement("div");
    card.className = "chat-message assistant kyber-knowledge-panel";
    if (proposals.length === 0) {
      card.innerHTML = `<div class="kn-header"><strong>${t("kn_analysis_complete")}</strong></div>
        <div class="kn-empty">${t("kn_no_proposals", scanned)}</div>`;
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
        <strong>${t(proposals.length === 1 ? "kn_analyzed_one" : "kn_analyzed_many", { n: proposals.length })}</strong>
      </div>
      <div class="kn-empty">${this._escapeHtml(t("kn_scanned_untick", scanned))}</div>
      <div class="kn-list">${rows}</div>
      <div class="kn-editor-buttons">
        <button class="btn-kn-cancel">${t("cmd_cancel")}</button>
        <button class="btn-kn-save-selected">${t("kn_save_selected")}</button>
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
        const resp = await this._hass.fetchWithAuth("/api/kyber/knowledge/analyze", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ proposals: selected }),
        });
        const result = await resp.json();
        card.querySelector(".kn-empty").textContent = t("kn_saved_entries", { n: result.count || 0 });
        card.querySelector(".kn-editor-buttons").remove();
      } catch (err) {
        alert(t("kn_save_failed", { msg: err.message }));
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
        await this._hass.fetchWithAuth("/api/kyber/knowledge", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
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
    const t = this._t || ((k) => k);
    const scoreBadge = (picked && typeof picked.score === "number")
      ? `<span class="kn-score" title="${this._escapeAttr(t("kn_score_title"))}">${t("kn_score", { score: picked.score.toFixed(2) })}</span>`
      : "";
    // Inject score badge + refine button into the row head
    return base
      .replace(
        '<span class="kn-row-actions">',
        `${scoreBadge}<button class="btn-kn-refine" title="${this._escapeAttr(t("kn_refine_title"))}">${t("kn_refine")}</button><span class="kn-row-actions">`,
      );
  }

  _showRefineDialog(id, entry) {
    const t = this._t || ((k) => k);
    const dlg = document.createElement("div");
    dlg.className = "kn-editor";
    dlg.innerHTML = `
      <div class="kn-editor-inner">
        <h3>${t("kn_refine_dialog_title")}</h3>
        <p style="margin:0;color:var(--secondary-text-color);font-size:11px;">
          ${this._escapeHtml(entry.content || "")}
        </p>
        <label>${t("kn_refine_how")}
          <textarea class="kn-f-refine" rows="4" placeholder="${this._escapeAttr(t("kn_refine_ph"))}"></textarea>
        </label>
        <label>${t("kn_refine_rating")}
          <select class="kn-f-rate">
            <option value="">${t("kn_rate_keep")}</option>
            <option value="5">${t("kn_rate_5")}</option>
            <option value="4">${t("kn_rate_4")}</option>
            <option value="3">${t("kn_rate_3")}</option>
            <option value="2">${t("kn_rate_2")}</option>
            <option value="1">${t("kn_rate_1")}</option>
          </select>
        </label>
        <div class="kn-editor-buttons">
          <button class="btn-kn-cancel">${t("cmd_cancel")}</button>
          <button class="btn-kn-save">${t("kn_refine_apply")}</button>
        </div>
      </div>
    `;
    this.shadowRoot.appendChild(dlg);
    dlg.querySelector(".btn-kn-cancel").addEventListener("click", () => dlg.remove());
    dlg.querySelector(".btn-kn-save").addEventListener("click", async () => {
      const hint = dlg.querySelector(".kn-f-refine").value.trim();
      const ratingStr = dlg.querySelector(".kn-f-rate").value;
      if (!hint && !ratingStr) { dlg.remove(); return; }
      try {
        if (hint) {
          const newContent = (entry.content || "") + "\n\nRefinement: " + hint;
          const newProv = (entry.provenance ? entry.provenance + "; " : "") + `User refined ${new Date().toISOString().slice(0, 10)}`;
          await this._hass.fetchWithAuth("/api/kyber/knowledge", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id, content: newContent, provenance: newProv, needs_review: false }),
          });
        }
        if (ratingStr) {
          await this._hass.fetchWithAuth("/api/kyber/knowledge/feedback", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ rating: parseInt(ratingStr, 10), knowledge_ids: [id], auto: false }),
          });
        }
        dlg.remove();
        this._renderDebugTab("last_turn");
      } catch (err) {
        alert(t("kn_refine_failed", { msg: err.message }));
      }
    });
  }
};
