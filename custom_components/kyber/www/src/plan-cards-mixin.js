export const PlanCardsMixin = (Base) => class extends Base {
  /** Build a confirm card for slash commands. onConfirm(card) is called when Execute is clicked. */
  _buildCommandCard({ icon = "▶", title, detail, warning, danger = false, executeLabel, onConfirm }) {
    const t = this._t || ((k) => k);
    const btnLabel = executeLabel ?? t("cmd_confirm_execute");
    const history = this.shadowRoot.getElementById("chat-history");
    const card = document.createElement("div");
    card.className = `command-card${danger ? " danger" : ""}`;
    card.innerHTML = `
      <div class="command-card-title">${icon} ${this._escapeHtml(title)}</div>
      ${detail ? `<div class="command-card-detail">${this._escapeHtml(detail)}</div>` : ""}
      ${warning ? `<div class="command-card-warning">⚠ ${this._escapeHtml(warning)}</div>` : ""}
      <div class="command-card-actions">
        <button class="btn-cmd-execute${danger ? " danger" : ""}">${btnLabel}</button>
        <button class="btn-cmd-cancel">✕ ${t("cmd_cancel")}</button>
      </div>
    `;
    card.querySelector(".btn-cmd-execute").addEventListener("click", () => {
      card.querySelector(".btn-cmd-execute").disabled = true;
      card.querySelector(".btn-cmd-cancel").disabled = true;
      onConfirm(card);
    });
    card.querySelector(".btn-cmd-cancel").addEventListener("click", () => card.remove());
    history.appendChild(card);
    history.scrollTop = history.scrollHeight;
  }

  _buildMemoryCard(learnedFact, opts = {}) {
    const t = this._t || ((k) => k);
    const action = (learnedFact.actions || [])[0] || {};
    const userTerm = action.description?.match(/Save alias: (.+?) →/)?.[1]
      || learnedFact.summary?.match(/'(.+?)'/)?.[1]
      || "?";
    const haTerm = action.subject || learnedFact.summary?.match(/→ '(.+?)'/)?.[1] || "?";
    const contentText = action.content || learnedFact.summary || "";

    const card = document.createElement("div");
    card.className = "memory-card";
    card.innerHTML = `
      <div class="memory-card-header">${t("pc_memory_suggested")}</div>
      <div class="memory-card-content">
        "${this._escapeHtml(userTerm)}" → <strong>${this._escapeHtml(haTerm)}</strong><br>
        <small style="opacity:0.75">${this._escapeHtml(contentText)}</small>
      </div>
      <button class="btn-remember">${t("pc_memory_remember")}</button>
    `;

    const btn = card.querySelector(".btn-remember");
    if (opts.status === "done") {
      btn.disabled = true;
      btn.textContent = t("pc_memory_remembered");
      return card;
    }
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      btn.textContent = t("ae_saving");
      try {
        const resp = await this._hass.fetchWithAuth("/api/kyber/plan/execute", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ plan: learnedFact }),
        });
        if (resp.ok) {
          btn.textContent = t("pc_memory_remembered");
          btn.style.background = "var(--success, #4caf50)";
          this._setRenderStatus(opts.historyEntry, "learned_fact", "done");
        } else {
          btn.textContent = t("pc_memory_failed");
          btn.disabled = false;
        }
      } catch (err) {
        btn.textContent = t("pc_memory_error");
        btn.disabled = false;
      }
    });
    return card;
  }

  /**
   * opts.restored: rebuilt after a page reload — autopilot never runs it.
   * opts.status: "done" when it was executed before; Execute is then locked.
   * opts.historyEntry: persisted reply; a successful run is recorded there.
   */
  _buildPlanCard(plan, opts = {}) {
    const t = this._t || ((k) => k);
    // Persisted chat entry of this reply; named apart because doExecute shadows
    // `opts` and its success path has its own (action) historyEntry.
    const chatEntry = opts.historyEntry || null;
    const card = document.createElement("div");
    card.className = "plan-card";

    const DOMAIN_ICONS = {
      light: "mdi:lightbulb",
      switch: "mdi:toggle-switch",
      sensor: "mdi:eye",
      binary_sensor: "mdi:radiobox-marked",
      climate: "mdi:thermostat",
      media_player: "mdi:cast",
      cover: "mdi:window-shutter-open",
      fan: "mdi:fan",
      lock: "mdi:lock",
      camera: "mdi:cctv",
      automation: "mdi:robot",
      script: "mdi:script-text",
      scene: "mdi:palette",
      input_boolean: "mdi:toggle-switch",
      timer: "mdi:timer-outline",
      number: "mdi:numeric",
      input_number: "mdi:numeric",
      select: "mdi:format-list-bulleted",
      input_select: "mdi:format-list-bulleted",
      vacuum: "mdi:robot-vacuum",
      alarm_control_panel: "mdi:shield-home",
      water_heater: "mdi:water-boiler",
      humidifier: "mdi:air-humidifier",
      button: "mdi:gesture-tap-button",
      input_button: "mdi:gesture-tap-button",
      input_text: "mdi:form-textbox",
      person: "mdi:account",
      device_tracker: "mdi:map-marker",
      weather: "mdi:cloud",
      group: "mdi:group",
    };
    const ON_STATES = new Set(["on", "open", "home", "playing", "unlocked", "active", "true",
      "heat", "cool", "auto", "fan_only", "dry", "heat_cool", "heat_cool"]);

    const typeLabels = {
      assign_area: t("pc_type_assign_area"),
      rename_entity: t("pc_type_rename_entity"),
      assign_label: t("pc_type_assign_label"),
      remove_label: t("pc_type_remove_label"),
      create_area: t("pc_type_create_area"),
      rename_area: t("pc_type_rename_area"),
      delete_area: t("pc_type_delete_area"),
      call_service: t("pc_type_call_service"),
      edit_automation: t("pc_type_edit_automation"),
      update_automation: t("pc_type_update_automation"),
      create_automation: t("pc_type_create_automation"),
      create_script: t("pc_type_create_script"),
      update_script: t("pc_type_update_script"),
      add_knowledge: t("pc_type_add_knowledge"),
      update_knowledge: t("pc_type_update_knowledge"),
      delete_knowledge: t("pc_type_delete_knowledge"),
    };

    // Area-only action types don't need an entity_id
    const areaOnlyTypes = new Set(["create_area", "rename_area", "delete_area"]);
    // Service calls validate entity_id differently (may be optional)
    const serviceTypes = new Set(["call_service"]);

    // Validate entity_ids before rendering
    const invalidEntities = new Set();
    (plan.actions || []).forEach((a) => {
      if (a.entity_id && !areaOnlyTypes.has(a.type) && !serviceTypes.has(a.type)) {
        if (!this._hass || !this._hass.states[a.entity_id]) {
          invalidEntities.add(a.entity_id);
        }
      }
    });

    const buildEntityChip = (entityId, missing) => {
      if (!entityId) return "";
      const domain = entityId.split(".")[0] || "";
      const haState = this._hass?.states?.[entityId];
      const friendlyName = haState?.attributes?.friendly_name || entityId;
      const icon = haState?.attributes?.icon || DOMAIN_ICONS[domain] || "mdi:home-assistant";
      const rawState = (haState?.state || "unknown").toLowerCase();
      const isOn = ON_STATES.has(rawState);
      const stateClass = rawState === "unavailable" ? "state-unavailable" : isOn ? "state-on" : "state-off";
      const domainClass = `domain-${domain.replace(/_/g, "-")}`;
      const nameDisplay = friendlyName.length > 24 ? `${friendlyName.slice(0, 23)}…` : friendlyName;
      return `<div class="entity-chip ${stateClass} ${domainClass}${missing ? " entity-chip-missing" : ""}" title="${this._escapeHtml(entityId)}">
        <ha-icon icon="${this._escapeHtml(icon)}" class="entity-chip-icon"></ha-icon>
        <span class="entity-chip-name">${this._escapeHtml(nameDisplay)}</span>${missing ? '<span class="entity-chip-warn">⚠</span>' : ""}
      </div>`;
    };

    const changeRows = (plan.actions || [])
      .map((a) => {
        const missing = a.entity_id && invalidEntities.has(a.entity_id);
        const entityHtml = buildEntityChip(a.entity_id, missing);
        // For service calls, show domain.service as the badge
        const typeLabel = a.type === "call_service"
          ? `${a.domain || "?"}.${a.service || "?"}`
          : (typeLabels[a.type] || a.type);
        const from = a.current_state
          ? `<span class="plan-from">${this._escapeHtml(String(a.current_state))}</span>`
          : "";
        const to = a.new_state
          ? `<span class="plan-to">${this._escapeHtml(String(a.new_state))}</span>`
          : "";
        const arrow = from && to ? `${from} → ${to}` : from || to;
        return `
          <li class="change-row${missing ? " row-invalid" : ""}${a.high_risk ? " row-risk" : ""}">
            ${entityHtml}
            <span class="change-type-badge">${this._escapeHtml(typeLabel)}</span>
            ${a.high_risk ? `<span class="change-type-badge">${t("pc_high_risk")}</span>` : ""}
            <span class="change-delta">${arrow}</span>
          </li>`;
      })
      .join("");

    const warnings = (plan.warnings || [])
      .map((w) => `<div class="plan-warning">⚠ ${this._escapeHtml(w)}</div>`)
      .join("");

    const missingWarning = invalidEntities.size > 0
      ? `<div class="plan-warning plan-warning-error">${t("pc_missing_entities", { n: invalidEntities.size, ids: [...invalidEntities].map((e) => this._escapeHtml(e)).join(", ") })}</div>`
      : "";

    // Only allow executing actions whose entity_ids are valid (or are area-only / service calls)
    const executableActions = (plan.actions || []).filter(
      (a) => !a.entity_id || areaOnlyTypes.has(a.type) || serviceTypes.has(a.type) || !invalidEntities.has(a.entity_id)
    );
    const hasExecutable = executableActions.length > 0;

    const approvalActions = executableActions.filter((a) => a.requires_approval === true);
    const getGuardrailKey = (domain) => `kyber.autopilot.override.${String(domain || "").toLowerCase()}`;
    const hasGuardrailOverride = (domain) => {
      try {
        return window.localStorage.getItem(getGuardrailKey(domain)) === "1";
      } catch (_) {
        return false;
      }
    };
    const highRiskActions = approvalActions.filter((a) => a.high_risk === true);
    const highRiskDomains = [...new Set(highRiskActions.map((a) => String(a.risk_domain || a.domain || "").toLowerCase()).filter(Boolean))];
    const manualApprovalActions = approvalActions.filter((a) => !a.high_risk || !hasGuardrailOverride(a.risk_domain || a.domain));
    const autoActions = executableActions.filter((a) => !manualApprovalActions.includes(a));
    const requiresApproval = manualApprovalActions.length > 0;
    const alreadyDone = opts.status === "done";
    const autopilotCanRun = this._autopilot && !opts.restored && autoActions.length > 0 && !requiresApproval;
    const approvalBadge = approvalActions.length > 0
      ? `<div class="plan-approval-note">${highRiskDomains.length
        ? t("pc_approval_required_risk", { n: approvalActions.length, domains: highRiskDomains.map((d) => this._escapeHtml(d)).join(", ") })
        : t("pc_approval_required", { n: approvalActions.length })}</div>`
      : "";
    const guardrailPrompt = this._autopilot && !opts.restored && highRiskDomains.length > 0
      ? `<label class="plan-warning"><input type="checkbox" class="guardrail-override-checkbox"> ${t("pc_guardrail_allow", { domains: this._escapeHtml(highRiskDomains.join(", ")) })}</label>`
      : "";

    card.innerHTML = `
      <div class="plan-overview">
        <div class="plan-overview-label">${t("pc_proposal")}</div>
        <div class="plan-overview-summary">${this._escapeHtml(plan.summary || "")}</div>
      </div>
      <div class="plan-changes-header">${t("pc_what_will_change")}</div>
      <ul class="plan-changes">${changeRows}</ul>
      ${missingWarning}
      ${warnings}
      ${approvalBadge}
      ${guardrailPrompt}
      ${alreadyDone
        ? `<button class="btn-execute" disabled>${this._escapeHtml(t("restored_card_done"))}</button>`
        : autopilotCanRun
        ? `<div class="plan-result" style="color:var(--warning-color,#ff9800);font-size:12px">${t("pc_autopilot_executing")}</div>`
        : `<button class="btn-execute"${hasExecutable ? "" : " disabled"}>${invalidEntities.size > 0 && hasExecutable
          ? t("pc_execute_partial", { n: executableActions.length, total: (plan.actions || []).length })
          : t("pc_execute")}</button>`
      }
      <div class="plan-result" id="plan-result-${Date.now()}"></div>
    `;
    if (opts.restored && !alreadyDone) {
      card.querySelector(".btn-execute")?.before(this._buildRestoredNote());
    }

    // Grab the result element (last .plan-result in card)
    const allResults = card.querySelectorAll(".plan-result");
    const resultEl = allResults[allResults.length - 1];

    // doExecute(opts): user click = approved:true (runs all incl. config changes).
    // Autopilot path passes approved:false and only the safe subset.
    const doExecute = async (opts = {}) => {
      const approved = opts.approved !== false; // default: user-approved
      const actionsToRun = opts.actions || executableActions;
      if (card.querySelector(".btn-execute")) {
        card.querySelector(".btn-execute").disabled = true;
      }
      resultEl.textContent = t("pc_executing");
      resultEl.className = "plan-result";
      try {
        const resp = await this._hass.fetchWithAuth("/api/kyber/execute", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ actions: actionsToRun, approved, summary: plan.summary || "" }),
        });
        if (resp.status === 403) {
          const blocked = await resp.json().catch(() => ({}));
          resultEl.textContent = t("pc_approval_blocked", { n: (blocked.blocked_actions || []).length });
          resultEl.className = "plan-result";
          if (card.querySelector(".btn-execute")) {
            card.querySelector(".btn-execute").disabled = false;
          }
          // Auto-scroll to / highlight the execute button so it's visible
          const btn = card.querySelector(".btn-execute");
          if (btn) {
            btn.classList.add("kyber-approval-pulse");
            btn.scrollIntoView({ behavior: "smooth", block: "nearest" });
            setTimeout(() => btn.classList.remove("kyber-approval-pulse"), 3000);
          }
          return;
        }
        const data = await resp.json();
        const failed = (data.results || []).filter((r) => r.status !== "ok");
        if (failed.length === 0) {
          resultEl.textContent = t("pc_done", { n: executableActions.length });
          resultEl.className = "plan-result success";

          const ok = (data.results || []).filter((r) => r.status === "ok");
          const changeLines = ok.map((r) => {
            const action = executableActions.find(
              (a) => (a.entity_id && a.entity_id === r.entity_id) ||
                      (a.area_id && a.area_id === r.area_id) ||
                      (!a.entity_id && !a.area_id && r.type === a.type)
            ) || executableActions[ok.indexOf(r)] || {};
            const desc = action.description || "";
            const fromTo = action.current_state && action.new_state
              ? `${action.current_state} → ${action.new_state}`
              : "";
            const target = action.entity_id || action.area_id || r.entity_id || r.area_id || "";
            const svcDomain = action.domain || (action.entity_id && action.entity_id.includes(".") ? action.entity_id.split(".")[0] : "?");
            const svcLabel = action.type === "call_service"
              ? `${svcDomain}.${action.service || "?"}`
              : (action.type || "change");
            return `- ${svcLabel}${target ? " on " + target : ""}${fromTo ? ": " + fromTo : ""}${desc ? " (" + desc + ")" : ""}`;
          });

          this._setRenderStatus(chatEntry, "plan", "done");
          this._addChatHistory("user", `I clicked Execute on the proposal: "${plan.summary || ""}".`);

          const historyEntry = data.history_entry || null;
          this._addChatHistory(
            "assistant",
            `[CHANGE] The following changes were successfully applied:\n${changeLines.join("\n")}`,
            historyEntry?.id ? { history_entry_id: historyEntry.id } : null
          );
          const undoActions = ok
            .map((r) => r.undo_action)
            .filter(Boolean);
          if (typeof this._loadActionHistory === "function") {
            this._loadActionHistory();
          }
          if ((historyEntry && Array.isArray(historyEntry.undo_plan) && historyEntry.undo_plan.length > 0) || undoActions.length > 0) {
            const undoCount = historyEntry?.undo_plan?.length || undoActions.length;
            const undoBtn = document.createElement("button");
            undoBtn.className = "btn-undo";
            undoBtn.textContent = t(undoCount > 1 ? "pc_undo_many" : "pc_undo_one", { n: undoCount });
            resultEl.after(undoBtn);
            undoBtn.addEventListener("click", async () => {
              undoBtn.disabled = true;
              undoBtn.textContent = t("pc_undoing");
              try {
                const request = historyEntry
                  ? this._hass.fetchWithAuth(`/api/kyber/history/actions/${encodeURIComponent(historyEntry.id)}/undo`, {
                      method: "POST",
                    })
                  : this._hass.fetchWithAuth("/api/kyber/execute", {
                      method: "POST",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ actions: undoActions, approved: true }),
                    });
                const r2 = await request;
                const d2 = await r2.json();
                if (!r2.ok || d2.status === "failed") {
                  throw new Error(d2.message || `HTTP ${r2.status}`);
                }
                undoBtn.textContent = t("pc_undone");
                undoBtn.disabled = true;
                resultEl.textContent = t("pc_undone_result");
                resultEl.className = "plan-result success";
                this._addChatHistory("assistant", `[CHANGE] Undid: ${plan.summary || "previous changes"}`);
                if (typeof this._loadActionHistory === "function") {
                  this._loadActionHistory();
                }
              } catch (e) {
                undoBtn.textContent = t("pc_undo_error", { msg: e.message });
                undoBtn.disabled = false;
              }
            });
          }

          // Show label-applied chips for auto-labelled entities
          ok.forEach((r) => {
            const labelInfo = r.label_applied;
            if (!labelInfo) return;
            const chip = document.createElement("div");
            chip.className = "kyber-label-applied-chip";
            chip.innerHTML = `
              <ha-icon icon="${this._escapeHtml(labelInfo.icon)}"></ha-icon>
              <span>${t("pc_label_applied", { label: this._escapeHtml(labelInfo.label_name), entity: this._escapeHtml(labelInfo.entity_name) })}</span>
              <button class="kyber-undo-label-btn">${t("ae_undo")}</button>
            `;
            chip.querySelector(".kyber-undo-label-btn").addEventListener("click", async (evt) => {
              evt.stopPropagation();
              const btn = chip.querySelector(".kyber-undo-label-btn");
              btn.disabled = true;
              btn.textContent = "…";
              try {
                await this._hass.callApi("POST", "kyber/execute", {
                  actions: [{ type: "remove_label", entity_id: labelInfo.entity_id, label_id: labelInfo.label_id }],
                  approved: true,
                });
                chip.remove();
              } catch (e) {
                btn.textContent = t("pc_label_undo_error"); btn.disabled = false;
              }
            });
            resultEl.after(chip);
          });
        } else {
          const failedMsgs = failed.map((r) => r.message || "unknown error").join("; ");
          resultEl.textContent = t("pc_failed", { n: failed.length, msg: failedMsgs });
          resultEl.className = "plan-result error";

          // Record failure in chat history so the AI knows what happened
          this._addChatHistory(
            "assistant",
            `[FAILED] ${failed.length} action(s) failed for "${plan.summary || "plan"}": ${failedMsgs}`
          );

          // ── Correction micro-agent result ─────────────────────────────────
          if (data.correction && data.correction.corrected_actions && data.correction.corrected_actions.length > 0) {
            const corr = data.correction;
            resultEl.textContent += `\n${t("pc_correction", { msg: corr.message || t("pc_correction_retrying") })}`;

            // Show toast for learned fact
            if (corr.learned_fact && typeof this._showToast === "function") {
              this._showToast(corr.learned_fact);
            }

            // Execute corrected actions automatically
            setTimeout(async () => {
              try {
                const corrResp = await this._hass.fetchWithAuth("/api/kyber/execute", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ actions: corr.corrected_actions, approved: opts.approved !== false }),
                });
                const corrData = await corrResp.json();
                const corrFailed = (corrData.results || []).filter((r) => r.status !== "ok");
                if (corrFailed.length === 0) {
                  resultEl.textContent = t("pc_corrected_applied", { n: corr.corrected_actions.length });
                  resultEl.className = "plan-result success";
                  this._addChatHistory(
                    "assistant",
                    `[🔧 CORRECTION] Successfully applied corrected plan: ${corr.message || plan.summary || ""}`
                  );
                } else {
                  resultEl.textContent = t("pc_correction_failed", { msg: corrFailed.map((r) => r.message).join("; ") });
                  resultEl.className = "plan-result error";
                }
              } catch (corrErr) {
                _LOGGER.debug("Kyber: correction re-execute error", corrErr);
              }
            }, 500);
          }

          if (card.querySelector(".btn-execute")) card.querySelector(".btn-execute").disabled = false;
        }
      } catch (err) {
        resultEl.textContent = `${t("ae_error")} ${err.message}`;
        resultEl.className = "plan-result error";
        if (card.querySelector(".btn-execute")) card.querySelector(".btn-execute").disabled = false;
      }
    };

    if (card.querySelector(".btn-execute")) {
      card.querySelector(".btn-execute").addEventListener("click", () => {
        const remember = card.querySelector(".guardrail-override-checkbox")?.checked;
        if (remember) {
          highRiskDomains.forEach((domain) => {
            try {
              window.localStorage.setItem(getGuardrailKey(domain), "1");
            } catch (_) {
              // ignore storage failures
            }
          });
        }
        doExecute({ approved: true });
      });
    }

    if (autopilotCanRun) {
      const autopilotApproved = autoActions.some((a) => a.requires_approval === true);
      setTimeout(() => doExecute({ approved: !autopilotApproved ? false : true, actions: autoActions }), 2000);
    }

    return card;
  }

  // ─── Automation editing cards ──────────────────────────────────────────────

  /** Lightweight YAML serializer for automation config objects. */
  // The backend parses this YAML with PyYAML (YAML 1.1). Unquoted, these strings
  // would come back as bool/null/number ("on" → True), be cut at a comment
  // ("Lights #2" → "Lights"), trimmed, or read as a sequence item.
  _yamlNeedsQuotes(s) {
    if (s === "") return true;
    if (/^(true|false|yes|no|on|off|y|n|null|~)$/i.test(s)) return true;
    if (/^[-+.]?\d/.test(s)) return true;
    if (/[:{}\[\],&*?|<>=!%@`#'"]/.test(s)) return true;
    if (/^[ \t]|[ \t]$/.test(s)) return true;
    if (s === "-" || s.startsWith("- ")) return true;
    return /[\x00-\x1f\x7f-\x9f\u2028\u2029]/.test(s);
  }

  _configToYaml(obj, indent = 0) {
    const pad = "  ".repeat(indent);
    if (obj === null || obj === undefined) return "null";
    if (typeof obj === "boolean") return obj ? "true" : "false";
    if (typeof obj === "number") return String(obj);
    if (typeof obj === "string") {
      if (this._yamlNeedsQuotes(obj)) {
        return JSON.stringify(obj);
      }
      return obj;
    }
    if (Array.isArray(obj)) {
      if (obj.length === 0) return "[]";
      return obj.map((item) => {
        if (typeof item === "object" && item !== null && !Array.isArray(item)) {
          const lines = this._configToYaml(item, indent + 1).split("\n");
          return `${pad}- ${lines[0].trimStart()}\n${lines.slice(1).join("\n")}`;
        }
        return `${pad}- ${this._configToYaml(item, indent + 1)}`;
      }).join("\n");
    }
    if (typeof obj === "object") {
      const keys = Object.keys(obj);
      if (keys.length === 0) return "{}";
      return keys.map((k) => {
        const v = obj[k];
        // Empty list/mapping stays on the key line: "condition:\n[]" is not valid YAML
        const isEmpty = Array.isArray(v) ? v.length === 0 : (v !== null && typeof v === "object" && Object.keys(v).length === 0);
        if (isEmpty) return `${pad}${k}: ${Array.isArray(v) ? "[]" : "{}"}`;
        if (typeof v === "object" && v !== null) {
          return `${pad}${k}:\n${this._configToYaml(v, indent + 1)}`;
        }
        return `${pad}${k}: ${this._configToYaml(v, indent + 1)}`;
      }).join("\n");
    }
    return String(obj);
  }

  /** Extract all entity_ids referenced in an automation config. */
  _extractEntityIds(config) {
    const ids = new Set();
    const scan = (obj) => {
      if (!obj || typeof obj !== "object") return;
      if (Array.isArray(obj)) { obj.forEach(scan); return; }
      for (const [k, v] of Object.entries(obj)) {
        if (k === "entity_id" && typeof v === "string") ids.add(v);
        else if (k === "entity_id" && Array.isArray(v)) v.forEach((e) => typeof e === "string" && ids.add(e));
        else scan(v);
      }
    };
    scan(config);
    return [...ids];
  }

  _describeTrigger(trig) {
    const t = this._t || ((k) => k);
    const p = trig.platform || trig.trigger || "";
    switch (p) {
      case "time": return t("pc_trig_at", { at: trig.at || "?" });
      case "time_pattern": return t("pc_trig_every", { interval: `${trig.hours ? ` ${trig.hours}h` : ""}${trig.minutes ? ` ${trig.minutes}m` : ""}${trig.seconds ? ` ${trig.seconds}s` : ""}` });
      case "state": {
        const eid = Array.isArray(trig.entity_id) ? trig.entity_id.join(", ") : (trig.entity_id || "?");
        return `🔄 ${eid}${trig.attribute ? ` · ${trig.attribute}` : ""}${trig.to != null ? ` → ${trig.to}` : ""}`;
      }
      case "sun": return t("pc_trig_sun", { event: trig.event || "?" });
      case "homeassistant": return `🏠 HA ${trig.event || "start"}`;
      case "template": return t("pc_trig_template");
      case "numeric_state": {
        const eid = Array.isArray(trig.entity_id) ? trig.entity_id[0] : (trig.entity_id || "?");
        return `🔢 ${eid}${trig.above != null ? ` > ${trig.above}` : ""}${trig.below != null ? ` < ${trig.below}` : ""}`;
      }
      case "zone": return `📍 ${trig.entity_id || "?"} ${trig.event || t("pc_trig_enter_leave")} ${trig.zone || ""}`;
      case "webhook": return `🌐 Webhook: ${trig.webhook_id || "?"}`;
      case "conversation": return `💬 "${Array.isArray(trig.command) ? trig.command[0] : (trig.command || "?")}"`;
      default: return `⚡ ${p || t("pc_trigger_fallback")}`;
    }
  }

  _describeCondition(c) {
    const t = this._t || ((k) => k);
    const type = c.condition || "";
    switch (type) {
      case "state": {
        const eid = Array.isArray(c.entity_id) ? c.entity_id.join(", ") : (c.entity_id || "?");
        const st = Array.isArray(c.state) ? c.state.join("/") : (c.state ?? "?");
        return `✅ ${eid} = ${st}`;
      }
      case "not": return t((c.conditions || []).length !== 1 ? "pc_cond_not_many" : "pc_cond_not_one", { n: (c.conditions || []).length });
      case "and": return t("pc_cond_all", { n: (c.conditions || []).length });
      case "or": return t("pc_cond_any", { n: (c.conditions || []).length });
      case "template": return t("pc_cond_template");
      case "time": return t("pc_cond_time", { after: c.after || "", before: c.before || "" });
      case "numeric_state": {
        const eid = Array.isArray(c.entity_id) ? c.entity_id[0] : (c.entity_id || "?");
        return `🔢 ${eid}${c.above != null ? ` > ${c.above}` : ""}${c.below != null ? ` < ${c.below}` : ""}`;
      }
      case "zone": return `📍 ${c.entity_id || "?"} in ${c.zone || "?"}`;
      case "trigger": return t("pc_cond_trigger_id", { id: c.id || "?" });
      default: return `❓ ${type || t("pc_condition_fallback")}`;
    }
  }

  _describeAction(a) {
    const t = this._t || ((k) => k);
    const svc = a.service || a.action || "";
    if (svc) {
      const target = a.target?.entity_id || a.entity_id || "";
      const tgt = Array.isArray(target) ? target[0] : target;
      return `▶ ${svc}${tgt ? `  [${tgt}]` : ""}`;
    }
    if (a.delay !== undefined) return t("pc_act_wait", { delay: typeof a.delay === "object" ? JSON.stringify(a.delay) : a.delay });
    if (a.wait_template !== undefined) return t("pc_act_wait_template");
    if (a.wait_for_trigger !== undefined) return t("pc_act_wait_trigger");
    if (a.condition !== undefined) return t("pc_act_stop_if");
    if (a.choose !== undefined) return t((a.choose || []).length !== 1 ? "pc_act_choose_many" : "pc_act_choose_one", { n: (a.choose || []).length });
    if (a.if !== undefined) return t("pc_act_if");
    if (a.repeat !== undefined) return a.repeat?.count ? t("pc_act_repeat_n", { n: a.repeat.count }) : t("pc_act_repeat");
    if (a.parallel !== undefined) return t("pc_act_parallel");
    if (a.variables !== undefined) return t("pc_act_set_vars");
    if (a.event !== undefined) return t("pc_act_fire_event", { event: a.event });
    return t("pc_act_action");
  }

  _evalConditionWithMocks(cond, mocks) {
    // Handle shorthand string template conditions: "{{ states('x') == 'y' }}"
    if (typeof cond === "string") return this._evalTemplateSimple(cond, mocks);

    const type = cond.condition || "";
    const getState = (eid) => mocks[eid] ?? this._hass?.states[eid]?.state ?? null;
    switch (type) {
      case "state": {
        const eids = Array.isArray(cond.entity_id) ? cond.entity_id : [cond.entity_id];
        const states = Array.isArray(cond.state) ? cond.state : (cond.state != null ? [String(cond.state)] : []);
        const results = eids.map((eid) => {
          const s = getState(eid);
          if (s === null) return null;
          return states.length > 0 ? states.includes(String(s)) : true;
        });
        if (results.includes(null)) return null;
        return results.every(Boolean);
      }
      case "numeric_state": {
        const eids = Array.isArray(cond.entity_id) ? cond.entity_id : [cond.entity_id];
        const results = eids.map((eid) => {
          const s = parseFloat(getState(eid));
          if (isNaN(s)) return null;
          if (cond.above != null && s <= cond.above) return false;
          if (cond.below != null && s >= cond.below) return false;
          return true;
        });
        if (results.includes(null)) return null;
        return results.every(Boolean);
      }
      case "template": {
        const tpl = cond.value_template || cond.template || "";
        return this._evalTemplateSimple(tpl, mocks);
      }
      case "and": return (cond.conditions || []).every((c) => this._evalConditionWithMocks(c, mocks));
      case "or": return (cond.conditions || []).some((c) => this._evalConditionWithMocks(c, mocks));
      case "not": return !(cond.conditions || []).some((c) => this._evalConditionWithMocks(c, mocks));
      default: return null;
    }
  }

  /**
   * Evaluate common Jinja2 template expressions using mock entity values.
   * Handles the most common HA patterns; returns null if it can't evaluate.
   */
  _evalTemplateSimple(tpl, mocks) {
    if (!tpl) return null;
    const getState = (eid) => mocks[eid] ?? this._hass?.states[eid]?.state ?? null;

    // Strip {{ }} delimiters
    let expr = tpl.trim().replace(/^\{\{([\s\S]*)\}\}$/, "$1").trim();

    // Replace is_state('entity', 'value') → true/false
    expr = expr.replace(/is_state\(['"]([^'"]+)['"]\s*,\s*['"]([^'"]+)['"]\)/g, (_, eid, st) => {
      const val = getState(eid);
      return val === null ? "null" : (String(val) === st ? "true" : "false");
    });

    // Replace states('entity') → "value" (quoted string)
    expr = expr.replace(/states\(['"]([^'"]+)['"]\)/g, (_, eid) => {
      const val = getState(eid);
      if (val === null) return "null";
      return `"${String(val).replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
    });

    // Replace float("value") or int("value") → number
    expr = expr.replace(/(?:float|int)\("([^"]*)"\)/g, (_, v) => {
      const n = parseFloat(v);
      return isNaN(n) ? "null" : String(n);
    });

    // Replace none/None/null/NULL → null; True/False → true/false
    expr = expr.replace(/\bNone\b/g, "null").replace(/\bnone\b/g, "null");
    expr = expr.replace(/\bTrue\b/g, "true").replace(/\bFalse\b/g, "false");

    // Unescape Jinja-escaped quotes (\"...\")
    expr = expr.replace(/\\"/g, '"');

    // Only evaluate if expression looks safe (no function calls or identifiers left)
    if (/[a-zA-Z_$][a-zA-Z0-9_$]*\s*\(/.test(expr)) return null;

    try {
      // eslint-disable-next-line no-new-func
      const result = Function('"use strict"; return (' + expr + ');')();
      if (result === null || result === undefined) return null;
      return !!result;
    } catch {
      return null;
    }
  }

  _evalTriggerWithMocks(trig, mocks) {
    const p = trig.platform || trig.trigger || "";
    switch (p) {
      case "time": return true;
      case "homeassistant": return true;
      case "state": {
        const eid = Array.isArray(trig.entity_id) ? trig.entity_id[0] : trig.entity_id;
        const mockState = mocks[eid] ?? this._hass?.states[eid]?.state ?? null;
        if (trig.to != null) return mockState !== null ? String(mockState) === String(trig.to) : null;
        return true;
      }
      case "numeric_state": {
        const eid = Array.isArray(trig.entity_id) ? trig.entity_id[0] : trig.entity_id;
        const s = parseFloat(mocks[eid] ?? this._hass?.states[eid]?.state);
        if (isNaN(s)) return null;
        if (trig.above != null && s <= trig.above) return false;
        if (trig.below != null && s >= trig.below) return false;
        return true;
      }
      default: return null;
    }
  }

  _getChangedSections(original, modified) {
    const changed = new Set();
    if (!original || !modified) return changed;
    ["trigger", "condition", "action"].forEach((section) => {
      if (JSON.stringify(original[section] || []) !== JSON.stringify(modified[section] || [])) {
        changed.add(section);
      }
    });
    return changed;
  }

  _buildAutomationRow(item, section, idx, changedSections, onDelete) {
    const row = document.createElement("div");
    row.className = "ae-row";
    row.dataset.idx = idx;
    const descFn = section === "trigger" ? this._describeTrigger.bind(this)
      : section === "condition" ? this._describeCondition.bind(this)
      : this._describeAction.bind(this);
    const desc = descFn(item);
    const isChanged = changedSections.has(section);
    const t = this._t || ((k) => k);
    // Only the handle drags, so the expanded YAML below stays selectable
    row.innerHTML = `
      <span class="ae-drag-handle" draggable="true" title="${t("pc_drag_reorder")}">⠿</span>
      <button class="ae-row-toggle" aria-expanded="false" title="${t("pc_sim_expand")}">▸</button>
      <span class="ae-row-desc${isChanged ? " changed" : ""}">${this._escapeHtml(desc)}</span>
      <button class="ae-row-delete" title="${t("pc_delete")}" aria-label="${t("pc_delete")}"><svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path fill="currentColor" d="M6,19A2,2 0 0,0 8,21H16A2,2 0 0,0 18,19V7H6V19M8,9H16V19H8V9M15.5,4L14.5,3H9.5L8.5,4H5V6H19V4H15.5Z"/></svg></button>
      <pre class="ae-row-detail" hidden></pre>
    `;
    const toggleBtn = row.querySelector(".ae-row-toggle");
    const detail = row.querySelector(".ae-row-detail");
    const toggle = () => {
      const open = detail.hidden;
      if (open) detail.textContent = this._configToYaml(item);
      detail.hidden = !open;
      toggleBtn.textContent = open ? "▾" : "▸";
      toggleBtn.title = t(open ? "pc_sim_collapse" : "pc_sim_expand");
      toggleBtn.setAttribute("aria-expanded", String(open));
    };
    toggleBtn.addEventListener("click", toggle);
    row.querySelector(".ae-row-desc").addEventListener("click", toggle);
    row.querySelector(".ae-row-delete").addEventListener("click", (e) => {
      e.stopPropagation();
      onDelete();
    });
    return row;
  }

  _setupDragAndDrop(container, array, onChange) {
    let dragSrcIdx = null;
    container.addEventListener("dragstart", (e) => {
      const row = e.target.closest(".ae-row");
      if (!row) return;
      dragSrcIdx = parseInt(row.dataset.idx, 10);
      row.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
      // Firefox only starts a drag that carries data; show the whole row, not the handle
      e.dataTransfer.setData("text/plain", "");
      e.dataTransfer.setDragImage?.(row, 12, 12);
    });
    container.addEventListener("dragend", () => {
      container.querySelectorAll(".ae-row").forEach((r) => r.classList.remove("dragging", "drag-over"));
      dragSrcIdx = null;
    });
    container.addEventListener("dragover", (e) => {
      e.preventDefault();
      const row = e.target.closest(".ae-row");
      container.querySelectorAll(".ae-row").forEach((r) => r.classList.remove("drag-over"));
      if (row) row.classList.add("drag-over");
      e.dataTransfer.dropEffect = "move";
    });
    container.addEventListener("drop", (e) => {
      e.preventDefault();
      const row = e.target.closest(".ae-row");
      if (!row || dragSrcIdx === null) return;
      const destIdx = parseInt(row.dataset.idx, 10);
      if (dragSrcIdx === destIdx) return;
      const [moved] = array.splice(dragSrcIdx, 1);
      array.splice(destIdx, 0, moved);
      onChange();
    });
  }

  _buildAutomationTester(config, _automationId, container) {
    const self = this;
    const t = self._t || ((k) => k);

    // ── Detect config type — blueprint wins over sequence ─────────────────
    const isBlueprint = !!(config.blueprint?.input || config.blueprint?.name);
    const isScript    = !isBlueprint && !!(config.sequence);
    const configType  = isBlueprint ? "blueprint" : isScript ? "script" : "automation";

    // ── Collect entity IDs + extra mock fields ──────────────────────────────
    const allEntityIds = this._extractEntityIds(config);

    // Blueprint inputs become named mocks (not just entity_ids)
    const blueprintInputs = isBlueprint
      ? Object.entries(config.blueprint?.input || {}).map(([key, def]) => ({
          key,
          name: def?.name || key,
          defaultVal: def?.default !== undefined ? String(def.default) : "",
          description: def?.description || "",
        }))
      : [];

    // Script fields become named mocks
    const scriptFields = isScript
      ? Object.entries(config.fields || {}).map(([key, def]) => ({
          key,
          name: def?.name || key,
          defaultVal: def?.example !== undefined ? String(def.example) : (def?.default !== undefined ? String(def.default) : ""),
          description: def?.description || "",
        }))
      : [];

    const mocks = {};            // entity_id → mock value
    const inputMocks = {};       // blueprint input key → mock value
    const firedTriggers = new Set();
    const nodeEls = {};
    // Reset panel-level selection state when tester is rebuilt
    self._selectedSimNodeKey = null;

    const getLive = (eid) => self._hass?.states[eid]?.state ?? "?";

    const triggers   = config.trigger   || config.triggers   || [];
    const conditions = config.condition || config.conditions || [];
    const actions    = isScript
      ? (config.sequence || [])
      : (config.action   || config.actions || config.sequence || []);

    const titleMap = { script: t("pc_sim_title_script"), blueprint: t("pc_sim_title_blueprint"), automation: t("pc_sim_title_automation") };

    container.innerHTML = `
      <div class="sim-toolbar">
        <button class="sim-back-btn" id="sim-back-btn">← YAML</button>
        <div class="sim-toolbar-title">${titleMap[configType]}</div>
        <button class="sim-run-btn" id="sim-run-btn">${t("pc_sim_run")}</button>
        <div class="sim-result-badge" id="sim-result-badge"></div>
      </div>
      <div class="sim-body">
        <div class="sim-flow" id="sim-flow"></div>
        ${(allEntityIds.length || blueprintInputs.length || scriptFields.length) ? `<div class="sim-mock-panel" id="sim-mock-panel">
          <div class="sim-mock-header">${isBlueprint ? t("pc_sim_blueprint_inputs") : isScript ? t("pc_sim_script_fields") : t("pc_sim_override_entities")}</div>
          <div class="sim-mock-rows" id="sim-mock-rows"></div>
        </div>` : ""}
      </div>
      ${allEntityIds.length ? `<div class="sim-overrides-bar" id="sim-overrides-bar" hidden>
        <span class="sim-overrides-label">${t("pc_sim_overridden")}</span>
        <div class="sim-overrides-chips" id="sim-overrides-chips"></div>
        <button class="sim-reset-all-btn" id="sim-reset-all-btn">${t("pc_sim_reset_all")}</button>
      </div>` : ""}
    `;

    const flowEl = container.querySelector("#sim-flow");

    // Build flow sections based on config type
    if (isScript) {
      // Scripts: just a SEQUENCE of actions, no triggers/conditions
      flowEl.appendChild(buildSection(t("pc_sim_sequence"), actions, "action"));
    } else if (isBlueprint) {
      // Blueprints: trigger → conditions → actions (same as automation)
      if (triggers.length) {
        flowEl.appendChild(buildSection(t("pc_sim_triggers"), triggers, "trigger"));
        flowEl.appendChild(makeArrow());
      }
      // Always show CONDITIONS section (even if empty) so the flow is clear
      flowEl.appendChild(buildSection(t("pc_sim_conditions"), conditions, "condition"));
      flowEl.appendChild(makeArrow());
      flowEl.appendChild(buildSection(t("pc_sim_actions"), actions.length ? actions : [], "action"));
    } else {
      // Standard automation — always show all three sections
      flowEl.appendChild(buildSection(t("pc_sim_triggers"), triggers, "trigger"));
      flowEl.appendChild(makeArrow());
      flowEl.appendChild(buildSection(t("pc_sim_conditions"), conditions, "condition"));
      flowEl.appendChild(makeArrow());
      flowEl.appendChild(buildSection(t("pc_sim_actions"), actions, "action"));
    }

    buildMockRows();

    container.querySelector("#sim-run-btn").addEventListener("click", runSimulation);
    container.querySelector("#sim-back-btn")?.addEventListener("click", () => self._showYamlTab?.());
    container.querySelector("#sim-reset-all-btn")?.addEventListener("click", resetAll);

    runSimulation();

    // ── Auto-run debounce ─────────────────────────────────────────────────────
    let _autoRunTimer = null;
    function scheduleAutoRun() {
      clearTimeout(_autoRunTimer);
      _autoRunTimer = setTimeout(runSimulation, 350);
    }

    // ── Helpers ──────────────────────────────────────────────────────────────

    function buildSection(label, items, type) {
      const sec = document.createElement("div");
      sec.className = `sim-section${type === "trigger" ? " sim-section-triggers" : ""}`;
      const labelEl = document.createElement("div");
      labelEl.className = "sim-section-label";
      labelEl.textContent = label;
      sec.appendChild(labelEl);
      const nodesEl = document.createElement("div");
      nodesEl.className = "sim-nodes";
      if (items.length === 0) {
        const none = document.createElement("div");
        none.className = "sim-node-empty";
        none.textContent = t("pc_sim_none");
        nodesEl.appendChild(none);
      } else {
        items.forEach((item, idx) => {
          const node = buildNode(item, type, idx);
          nodeEls[`${type}:${idx}`] = node;
          nodesEl.appendChild(node);
        });
      }
      sec.appendChild(nodesEl);
      return sec;
    }

    function selectNode(type, idx, nodeEl) {
      const key = `${type}:${idx}`;
      // Deselect previous (including the current node if same key is clicked again)
      if (self._selectedSimNodeKey) {
        const prev = container.querySelector(`[data-node-key="${self._selectedSimNodeKey}"]`);
        if (prev) prev.classList.remove("sim-selected");
      }
      if (self._selectedSimNodeKey === key) {
        // Toggle off
        self._selectedSimNodeKey = null;
        self._clearNodeHighlight?.();
        return;
      }
      self._selectedSimNodeKey = key;
      nodeEl.classList.add("sim-selected");
      self._highlightNodeInEditor?.(type, idx);
    }

    function buildNode(item, type, idx) {
      const node = document.createElement("div");
      node.className = `sim-node sim-node-${type}`;
      node.dataset.type = type;
      node.dataset.idx = idx;
      node.dataset.nodeKey = `${type}:${idx}`;
      const { icon, title, sub } = describeNode(item, type);

      const header = document.createElement("div");
      header.className = "sim-node-header";
      header.innerHTML = `
        <div class="adg-icon">${icon}</div>
        <div class="adg-title">${self._escapeHtml(title)}</div>
        ${sub ? `<div class="adg-sub">${self._escapeHtml(sub)}</div>` : ""}
        ${type === "trigger" ? `<button class="sim-fire-btn" title="${t("pc_sim_fire_title")}">${t("pc_sim_fire")}</button>` : ""}
      `;
      node.appendChild(header);

      // Expand complex action types (choose / if / repeat / parallel)
      if (type === "action") {
        const body = buildComplexBody(item, `action:${idx}`);
        if (body) {
          const toggle = document.createElement("button");
          toggle.className = "sim-expand-btn";
          toggle.textContent = "▾";
          toggle.title = t("pc_sim_collapse");
          header.appendChild(toggle);
          node.appendChild(body);
          node.classList.add("sim-node-complex");
          toggle.addEventListener("click", (e) => {
            e.stopPropagation();
            const collapsed = node.classList.toggle("sim-node-collapsed");
            toggle.textContent = collapsed ? "▸" : "▾";
            toggle.title = collapsed ? t("pc_sim_expand") : t("pc_sim_collapse");
          });
        }
      }

      if (type === "trigger") {
        // Clicking anywhere on the trigger node fires/unfires it AND selects it for YAML highlight
        node.addEventListener("click", () => {
          if (firedTriggers.has(idx)) {
            firedTriggers.delete(idx);
            node.classList.remove("sim-fired");
          } else {
            firedTriggers.add(idx);
            node.classList.add("sim-fired");
          }
          selectNode(type, idx, node);
        });
      } else {
        header.addEventListener("click", () => selectNode(type, idx, node));
      }
      return node;
    }

    // ── Complex-node body builders ───────────────────────────────────────────

    function buildComplexBody(item, pathPrefix) {
      if (item.choose !== undefined) return buildChooseBody(item.choose, item.default, pathPrefix);
      if (item.if    !== undefined) return buildIfBody(item, pathPrefix);
      if (item.repeat !== undefined && (item.repeat.sequence || []).length > 0) return buildRepeatBody(item.repeat, pathPrefix);
      if (item.parallel !== undefined) return buildParallelBody(item.parallel, pathPrefix);
      return null;
    }

    function buildChooseBody(options, defaultSeq, pathPrefix) {
      const body = document.createElement("div");
      body.className = "sim-complex-body sim-complex-body-choose";
      (options || []).forEach((opt, oi) => {
        const optEl = document.createElement("div");
        optEl.className = "sim-branch";
        optEl.dataset.branchKey = `${pathPrefix}:opt:${oi}`;
        const conds = opt.conditions || opt.condition || [];
        const condText = conds.length === 0 ? t("pc_sim_always") : conds.map(describeCondShort).join(" & ");
        const label = document.createElement("div");
        label.className = "sim-branch-label";
        label.textContent = t("pc_sim_option", { n: oi + 1, cond: condText });
        label.style.cursor = "pointer";
        label.addEventListener("click", (e) => {
          e.stopPropagation();
          const parts = pathPrefix.split(":");
          if (parts[0] === "action" && parts[1] !== undefined) {
            const parentIdx = parseInt(parts[1], 10);
            if (!isNaN(parentIdx)) {
              const blocks = self._diagLineBlocks;
              if (blocks?.actions?.[parentIdx] != null) {
                const parentBlock = blocks.actions[parentIdx];
                const chooseOpts = self._parseChooseBlocks?.(parentBlock.from_line, parentBlock.to_line) || [];
                const optBlock = chooseOpts[oi];
                if (optBlock) { self._jumpEditorToBlock?.(optBlock.from_line, optBlock.to_line); return; }
              }
              self._highlightNodeInEditor?.("action", parentIdx);
            }
          }
        });
        optEl.appendChild(label);
        buildSubSequence(opt.sequence || [], `${pathPrefix}:opt:${oi}`, optEl);
        body.appendChild(optEl);
      });
      if (defaultSeq && defaultSeq.length > 0) {
        const defEl = document.createElement("div");
        defEl.className = "sim-branch sim-branch-default";
        defEl.dataset.branchKey = `${pathPrefix}:default`;
        const label = document.createElement("div");
        label.className = "sim-branch-label sim-branch-default-label";
        label.textContent = t("pc_sim_default");
        defEl.appendChild(label);
        buildSubSequence(defaultSeq, `${pathPrefix}:default`, defEl);
        body.appendChild(defEl);
      }
      return body;
    }

    function buildIfBody(item, pathPrefix) {
      const body = document.createElement("div");
      body.className = "sim-complex-body";
      if (item.then && item.then.length > 0) {
        const el = document.createElement("div");
        el.className = "sim-branch sim-branch-then";
        el.dataset.branchKey = `${pathPrefix}:then`;
        const lbl = document.createElement("div");
        lbl.className = "sim-branch-label sim-branch-then-label";
        lbl.textContent = t("pc_sim_then");
        el.appendChild(lbl);
        buildSubSequence(item.then, `${pathPrefix}:then`, el);
        body.appendChild(el);
      }
      if (item.else && item.else.length > 0) {
        const el = document.createElement("div");
        el.className = "sim-branch sim-branch-else";
        el.dataset.branchKey = `${pathPrefix}:else`;
        const lbl = document.createElement("div");
        lbl.className = "sim-branch-label sim-branch-else-label";
        lbl.textContent = t("pc_sim_else");
        el.appendChild(lbl);
        buildSubSequence(item.else, `${pathPrefix}:else`, el);
        body.appendChild(el);
      }
      return body.children.length > 0 ? body : null;
    }

    function buildRepeatBody(repeat, pathPrefix) {
      const body = document.createElement("div");
      body.className = "sim-complex-body";
      const el = document.createElement("div");
      el.className = "sim-branch";
      el.dataset.branchKey = `${pathPrefix}:repeat`;
      const lbl = document.createElement("div");
      lbl.className = "sim-branch-label";
      lbl.textContent = repeat.count ? t("pc_sim_repeats", { n: repeat.count }) : repeat.while ? t("pc_sim_while") : repeat.for_each ? t("pc_sim_for_each") : t("pc_sim_sequence_label");
      el.appendChild(lbl);
      buildSubSequence(repeat.sequence || [], `${pathPrefix}:repeat`, el);
      body.appendChild(el);
      return body;
    }

    function buildParallelBody(parallel, pathPrefix) {
      const body = document.createElement("div");
      body.className = "sim-complex-body";
      (parallel || []).forEach((branch, bi) => {
        const el = document.createElement("div");
        el.className = "sim-branch";
        el.dataset.branchKey = `${pathPrefix}:par:${bi}`;
        const lbl = document.createElement("div");
        lbl.className = "sim-branch-label";
        lbl.textContent = t("pc_sim_branch", { n: bi + 1 });
        el.appendChild(lbl);
        const seq = Array.isArray(branch) ? branch : (branch.sequence || [branch]);
        buildSubSequence(seq, `${pathPrefix}:par:${bi}`, el);
        body.appendChild(el);
      });
      return body.children.length > 0 ? body : null;
    }

    function buildSubSequence(items, pathPrefix, container) {
      items.forEach((item, idx) => {
        const key = `${pathPrefix}:${idx}`;
        const subNode = buildSubNode(item, key);
        nodeEls[key] = subNode;
        container.appendChild(subNode);
        // Recurse into nested complex nodes
        const nestedBody = buildComplexBody(item, key);
        if (nestedBody) {
          subNode.appendChild(nestedBody);
          subNode.classList.add("sim-sub-node-complex");
        }
      });
    }

    function buildSubNode(item, key) {
      const node = document.createElement("div");
      node.className = "sim-sub-node";
      node.dataset.key = key;
      node.dataset.nodeKey = key;  // for unified querySelector
      const { icon, title, sub } = describeNode(item, "action");
      node.innerHTML = `<span class="sim-sub-icon">${icon}</span><span class="sim-sub-title">${self._escapeHtml(title)}</span>${sub ? `<span class="sim-sub-sub"> — ${self._escapeHtml(sub)}</span>` : ""}`;
      // Sub-node selection: highlight the specific YAML range in the editor
      node.addEventListener("click", (e) => {
        e.stopPropagation();
        const nodeKey = key; // e.g. "action:0:opt:1:2"
        // Deselect previous (including self if toggling off)
        if (self._selectedSimNodeKey) {
          const prev = container.querySelector(`[data-node-key="${self._selectedSimNodeKey}"]`);
          if (prev) prev.classList.remove("sim-selected");
        }
        if (self._selectedSimNodeKey === nodeKey) {
          self._selectedSimNodeKey = null;
          self._clearNodeHighlight?.();
          return;
        }
        self._selectedSimNodeKey = nodeKey;
        node.classList.add("sim-selected");
        // Navigate editor to the specific YAML range for this sub-node
        // Key format: "action:<parentIdx>:opt:<optIdx>:<subIdx>..."
        const parts = nodeKey.split(":");
        if (parts[0] === "action" && parts[1] !== undefined) {
          const parentIdx = parseInt(parts[1], 10);
          if (!isNaN(parentIdx)) {
            const blocks = self._diagLineBlocks;
            const optMarker = parts.indexOf("opt");
            if (optMarker !== -1 && blocks?.actions?.[parentIdx] != null) {
              const optIdx = parseInt(parts[optMarker + 1], 10);
              const parentBlock = blocks.actions[parentIdx];
              const chooseOpts = self._parseChooseBlocks?.(parentBlock.from_line, parentBlock.to_line) || [];
              const optBlock = chooseOpts[optIdx];
              if (optBlock) {
                const subIdxStr = parts[optMarker + 2];
                const subIdx = subIdxStr !== undefined ? parseInt(subIdxStr, 10) : NaN;
                if (!isNaN(subIdx) && optBlock.actions?.[subIdx]) {
                  const subAct = optBlock.actions[subIdx];
                  self._jumpEditorToBlock?.(subAct.from_line, subAct.to_line);
                } else {
                  self._jumpEditorToBlock?.(optBlock.from_line, optBlock.to_line);
                }
                return;
              }
            }
            // Fall back to highlighting the entire parent action block
            self._highlightNodeInEditor?.("action", parentIdx);
          }
        }
      });
      return node;
    }

    function describeCondShort(c) {
      // Plain string template shorthand
      if (typeof c === "string") {
        const m = c.match(/(?:states|is_state)\(['"]([^'"]+)['"]/);
        return m ? m[1].split(".").pop() : t("pc_sim_short_template");
      }
      const ct = c.condition || "";
      if (ct === "state")         return `${String(c.entity_id || "?").split(".").pop()} = ${c.state || "?"}`;
      if (ct === "trigger")       return t("pc_sim_short_trigger", { id: Array.isArray(c.id) ? c.id.join("/") : (c.id || "?") });
      if (ct === "template")      return t("pc_sim_short_template");
      if (ct === "numeric_state") return t("pc_sim_short_numeric", { entity: String(c.entity_id || "?").split(".").pop() });
      if (ct === "device")        return t("pc_sim_short_device");
      return ct || t("pc_condition_fallback");
    }

    // ── Evaluate sub-nodes after a run ───────────────────────────────────────

    function runSubNodesForAction(item, pathPrefix, parentPass) {
      const cls = parentPass ? "sim-pass" : "sim-skip";

      if (item.choose !== undefined) {
        const options = item.choose || [];
        let matched = false;
        options.forEach((opt, oi) => {
          const optKey = `${pathPrefix}:opt:${oi}`;
          const conds = opt.conditions || opt.condition || [];
          // null = unknown/unevaluatable → do NOT treat as match; only true counts
          const result = conds.length === 0 ? true
            : conds.every(c => self._evalConditionWithMocks(c, mocks) === true);
          const branchPass = parentPass && !matched && result;
          if (branchPass) matched = true;
          const branchCls = parentPass ? (branchPass ? "sim-pass" : "sim-skip") : "sim-skip";
          markSubBranch(optKey, opt.sequence || [], branchCls);
        });
        // Default
        if (item.default && item.default.length > 0) {
          const defKey = `${pathPrefix}:default`;
          const defPass = parentPass && !matched;
          markSubBranch(defKey, item.default, defPass ? "sim-pass" : "sim-skip");
        }
        return;
      }

      if (item.if !== undefined) {
        const conds = Array.isArray(item.if) ? item.if : [item.if];
        const ifResult = parentPass
          ? conds.every(c => self._evalConditionWithMocks(c, mocks) === true)
          : false;
        if (item.then && item.then.length > 0) {
          markSubBranch(`${pathPrefix}:then`, item.then, parentPass ? (ifResult ? "sim-pass" : "sim-skip") : "sim-skip");
        }
        if (item.else && item.else.length > 0) {
          markSubBranch(`${pathPrefix}:else`, item.else, parentPass ? (!ifResult ? "sim-pass" : "sim-skip") : "sim-skip");
        }
        return;
      }

      if (item.repeat !== undefined) {
        markSubBranch(`${pathPrefix}:repeat`, item.repeat.sequence || [], cls);
        return;
      }

      if (item.parallel !== undefined) {
        (item.parallel || []).forEach((branch, bi) => {
          const seq = Array.isArray(branch) ? branch : (branch.sequence || [branch]);
          markSubBranch(`${pathPrefix}:par:${bi}`, seq, cls);
        });
      }
    }

    function markSubBranch(branchKey, seq, cls) {
      const branchEl = container.querySelector(`[data-branch-key="${CSS.escape(branchKey)}"]`);
      if (branchEl) {
        branchEl.classList.remove("sim-pass", "sim-skip", "sim-fail");
        if (cls) branchEl.classList.add(cls);
      }
      seq.forEach((item, idx) => {
        const key = `${branchKey}:${idx}`;
        const subNode = nodeEls[key];
        if (subNode) {
          subNode.classList.remove("sim-pass", "sim-skip", "sim-fail");
          subNode.classList.add(cls);
        }
        // Recurse
        runSubNodesForAction(item, key, cls === "sim-pass");
      });
    }

    function describeNode(item, type) {
      if (type === "trigger") {
        const p = item.platform || item.trigger || "";
        switch (p) {
          case "time": return { icon: "🕐", title: t("pc_node_time_trigger"), sub: t("pc_node_at", { at: item.at || "?" }) };
          case "time_pattern": return { icon: "🕐", title: t("pc_node_time_pattern"), sub: `${item.hours ? `${item.hours}h` : ""}${item.minutes ? ` ${item.minutes}m` : ""}` };
          case "state": { const e = Array.isArray(item.entity_id) ? item.entity_id[0] : (item.entity_id || "?"); return { icon: "🔄", title: t("pc_node_state_change"), sub: e + (item.to != null ? ` → ${item.to}` : "") }; }
          case "sun": return { icon: "🌅", title: t("pc_node_sun"), sub: item.event || "?" };
          case "homeassistant": return { icon: "🏠", title: t("pc_node_ha_startup"), sub: item.event || "start" };
          case "template": return { icon: "📋", title: t("pc_node_template_trigger"), sub: "" };
          case "numeric_state": { const e = Array.isArray(item.entity_id) ? item.entity_id[0] : (item.entity_id || "?"); return { icon: "🔢", title: t("pc_node_numeric_state"), sub: e }; }
          case "zone": return { icon: "📍", title: t("pc_node_zone"), sub: `${item.entity_id || "?"} ${item.event || ""}` };
          case "webhook": return { icon: "🌐", title: "Webhook", sub: item.webhook_id || "?" };
          case "conversation": return { icon: "💬", title: t("pc_node_voice_command"), sub: Array.isArray(item.command) ? item.command[0] : (item.command || "?") };
          default: return { icon: "⚡", title: p || t("pc_node_trigger"), sub: "" };
        }
      } else if (type === "condition") {
        const ct = item.condition || "";
        switch (ct) {
          case "state": { const e = Array.isArray(item.entity_id) ? item.entity_id[0] : (item.entity_id || "?"); const s = Array.isArray(item.state) ? item.state.join("/") : (item.state ?? "?"); return { icon: "🔀", title: t("pc_node_state"), sub: `${e} = ${s}` }; }
          case "not": return { icon: "🚫", title: t("pc_node_not"), sub: t("pc_node_n_conditions_opt", { n: (item.conditions || []).length }) };
          case "and": return { icon: "🔗", title: t("pc_node_all_of"), sub: t("pc_node_n_conditions", { n: (item.conditions || []).length }) };
          case "or": return { icon: "⚡", title: t("pc_node_any_of"), sub: t("pc_node_n_conditions", { n: (item.conditions || []).length }) };
          case "template": return { icon: "📋", title: t("pc_node_template"), sub: "" };
          case "time": return { icon: "🕐", title: t("pc_node_time_range"), sub: `${item.after || ""}–${item.before || ""}` };
          case "numeric_state": { const e = Array.isArray(item.entity_id) ? item.entity_id[0] : (item.entity_id || "?"); return { icon: "🔢", title: t("pc_node_numeric_state"), sub: e }; }
          case "zone": return { icon: "📍", title: t("pc_node_zone"), sub: `${item.entity_id || "?"} in ${item.zone || "?"}` };
          default: return { icon: "❓", title: ct || t("pc_node_condition"), sub: "" };
        }
      } else {
        const svc = item.service || item.action || "";
        if (svc) { const tgt = item.target?.entity_id || item.entity_id || ""; const tid = Array.isArray(tgt) ? tgt[0] : tgt; return { icon: "▶", title: svc, sub: tid || "" }; }
        if (item.delay !== undefined) return { icon: "⏱", title: t("pc_node_delay"), sub: typeof item.delay === "object" ? JSON.stringify(item.delay) : String(item.delay) };
        if (item.wait_template !== undefined) return { icon: "⏳", title: t("pc_node_wait_template"), sub: "" };
        if (item.choose !== undefined) return { icon: "🔀", title: t("pc_node_choose"), sub: t("pc_node_n_options", { n: (item.choose || []).length }) };
        if (item.if !== undefined) return { icon: "❓", title: t("pc_node_if_then_else"), sub: "" };
        if (item.repeat !== undefined) return { icon: "🔁", title: t("pc_node_repeat"), sub: item.repeat?.count ? `${item.repeat.count}×` : "" };
        if (item.parallel !== undefined) return { icon: "⚡", title: t("pc_node_parallel"), sub: "" };
        if (item.variables !== undefined) return { icon: "📦", title: t("pc_node_set_variables"), sub: "" };
        if (item.event !== undefined) return { icon: "📣", title: t("pc_node_fire_event"), sub: item.event };
        return { icon: "⚡", title: t("pc_node_action"), sub: "" };
      }
    }

    function makeArrow() {
      const el = document.createElement("div");
      el.className = "sim-section-arrow";
      el.textContent = "↓";
      return el;
    }

    function buildMockRows() {
      const mockRows = container.querySelector("#sim-mock-rows");
      if (!mockRows) return;
      mockRows.innerHTML = "";

      // Blueprint inputs — named fields with defaults
      blueprintInputs.forEach(({ key, name, defaultVal, description }) => {
        const current = inputMocks[key] !== undefined ? inputMocks[key] : defaultVal;
        const row = document.createElement("div");
        row.className = "sim-mock-row sim-mock-named-row";
        row.dataset.key = key;
        row.innerHTML = `
          <span class="sim-mock-eid">${self._escapeHtml(name)}</span>
          ${description ? `<span class="sim-mock-live">${self._escapeHtml(description)}</span>` : ""}
          <div class="sim-mock-input-row">
            <input class="sim-mock-input sim-blueprint-input" data-key="${self._escapeHtml(key)}"
                   placeholder="${self._escapeHtml(defaultVal || key)}"
                   value="${self._escapeHtml(current)}">
          </div>
        `;
        const input = row.querySelector(".sim-blueprint-input");
        input.addEventListener("input", () => {
          const val = input.value.trim();
          if (val) inputMocks[key] = val;
          else delete inputMocks[key];
          scheduleAutoRun();
        });
        mockRows.appendChild(row);
      });

      // Script fields
      scriptFields.forEach(({ key, name, defaultVal, description }) => {
        const current = inputMocks[key] !== undefined ? inputMocks[key] : defaultVal;
        const row = document.createElement("div");
        row.className = "sim-mock-row sim-mock-named-row";
        row.dataset.key = key;
        row.innerHTML = `
          <span class="sim-mock-eid">${self._escapeHtml(name)}</span>
          ${description ? `<span class="sim-mock-live">${self._escapeHtml(description)}</span>` : ""}
          <div class="sim-mock-input-row">
            <input class="sim-mock-input sim-script-input" data-key="${self._escapeHtml(key)}"
                   placeholder="${self._escapeHtml(defaultVal || key)}"
                   value="${self._escapeHtml(current)}">
          </div>
        `;
        const input = row.querySelector(".sim-script-input");
        input.addEventListener("input", () => {
          const val = input.value.trim();
          if (val) inputMocks[key] = val;
          else delete inputMocks[key];
          scheduleAutoRun();
        });
        mockRows.appendChild(row);
      });

      // Entity overrides (for automations and blueprints with entity references)
      allEntityIds.forEach((eid) => {
        const liveVal = getLive(eid);
        const overridden = mocks[eid] !== undefined;
        const isUnavailable = liveVal === "unavailable" || liveVal === "unknown" || liveVal === "?";
        const placeholder = isUnavailable ? t("pc_sim_type_override") : liveVal;
        const row = document.createElement("div");
        row.className = `sim-mock-row${overridden ? " sim-override" : ""}`;
        row.dataset.eid = eid;
        row.innerHTML = `
          <span class="sim-mock-eid">${self._escapeHtml(eid)}</span>
          <span class="sim-mock-live${isUnavailable ? " sim-mock-unavailable" : ""}">${t("pc_sim_live", { value: self._escapeHtml(liveVal) })}</span>
          <div class="sim-mock-input-row">
            <input class="sim-mock-input" data-eid="${self._escapeHtml(eid)}"
                   placeholder="${self._escapeHtml(placeholder)}"
                   value="${self._escapeHtml(overridden ? mocks[eid] : "")}">
          </div>
        `;
        if (overridden) {
          const resetBtn = document.createElement("button");
          resetBtn.className = "sim-entity-reset-btn";
          resetBtn.title = t("pc_sim_reset_live");
          resetBtn.textContent = "↺";
          resetBtn.addEventListener("click", () => { resetEntity(eid); });
          row.querySelector(".sim-mock-input-row").appendChild(resetBtn);
        }
        const input = row.querySelector(".sim-mock-input");
        input.addEventListener("input", () => {
          const val = input.value.trim();
          if (val) mocks[eid] = val;
          else delete mocks[eid];
          const isOverride = !!mocks[eid];
          row.classList.toggle("sim-override", isOverride);
          let resetBtn = row.querySelector(".sim-entity-reset-btn");
          if (isOverride && !resetBtn) {
            resetBtn = document.createElement("button");
            resetBtn.className = "sim-entity-reset-btn";
            resetBtn.title = t("pc_sim_reset_live");
            resetBtn.textContent = "↺";
            resetBtn.addEventListener("click", () => { resetEntity(eid); });
            row.querySelector(".sim-mock-input-row").appendChild(resetBtn);
          } else if (!isOverride && resetBtn) {
            resetBtn.remove();
          }
          updateOverridesBar();
          scheduleAutoRun();
        });
        row.querySelector(".sim-entity-reset-btn")?.addEventListener("click", () => { resetEntity(eid); });
        mockRows.appendChild(row);
      });
    }

    function resetEntity(eid) {
      delete mocks[eid];
      buildMockRows();
      updateOverridesBar();
      scheduleAutoRun();
    }

    function resetAll() {
      Object.keys(mocks).forEach((k) => delete mocks[k]);
      buildMockRows();
      updateOverridesBar();
      scheduleAutoRun();
    }

    function updateOverridesBar() {
      const bar = container.querySelector("#sim-overrides-bar");
      const chips = container.querySelector("#sim-overrides-chips");
      if (!bar || !chips) return;
      const keys = Object.keys(mocks);
      bar.hidden = keys.length === 0;
      if (keys.length) {
        chips.innerHTML = keys.map((eid) =>
          `<span class="sim-override-chip">${self._escapeHtml(eid.split(".").pop())} = <b>${self._escapeHtml(mocks[eid])}</b>
            <button class="sim-chip-reset" data-eid="${self._escapeHtml(eid)}" title="${t("pc_sim_reset")}">✕</button>
          </span>`
        ).join("");
        chips.querySelectorAll(".sim-chip-reset").forEach((btn) => {
          btn.addEventListener("click", () => resetEntity(btn.dataset.eid));
        });
      }
    }

    function runSimulation() {
      // Clear previous result states
      Object.values(nodeEls).forEach((n) => {
        n.classList.remove("sim-pass", "sim-fail", "sim-skip");
        n.querySelector(".sim-node-result")?.remove();
      });

      // ── Script: all sequence steps always execute ─────────────────────────
      if (isScript) {
        actions.forEach((action, idx) => {
          const node = nodeEls[`action:${idx}`];
          if (node) node.classList.add("sim-pass");
          runSubNodesForAction(action, `action:${idx}`, true);
        });
        const badge = container.querySelector("#sim-result-badge");
        if (badge) { badge.className = "sim-result-badge pass"; badge.textContent = t("pc_sim_script_executed"); }
        return;
      }

      // ── Blueprint / Automation: evaluate trigger → condition → action ──────

      // Evaluate triggers
      let anyTriggerFires = triggers.length === 0;
      triggers.forEach((trig, idx) => {
        const node = nodeEls[`trigger:${idx}`];
        const manuallyFired = firedTriggers.has(idx);
        const result = manuallyFired ? true : self._evalTriggerWithMocks(trig, mocks);
        if (result === true) anyTriggerFires = true;
        if (node) {
          const badge = document.createElement("div");
          badge.className = "sim-node-result";
          badge.textContent = result === true ? "✅" : result === false ? "❌" : "❓";
          node.appendChild(badge);
          if (result === true) node.classList.add("sim-pass");
          else if (result === false) node.classList.add("sim-fail");
        }
      });

      // Evaluate conditions
      let allConditionsPass = true;
      if (anyTriggerFires && conditions.length) {
        conditions.forEach((c, idx) => {
          const node = nodeEls[`condition:${idx}`];
          const result = self._evalConditionWithMocks(c, mocks);
          if (result === false) allConditionsPass = false;
          if (node) {
            const badge = document.createElement("div");
            badge.className = "sim-node-result";
            badge.textContent = result === true ? "✅" : result === false ? "❌" : "❓";
            node.appendChild(badge);
            if (result === true) node.classList.add("sim-pass");
            else if (result === false) node.classList.add("sim-fail");
            else node.classList.add("sim-skip");
          }
        });
      } else if (!anyTriggerFires) {
        conditions.forEach((_, idx) => nodeEls[`condition:${idx}`]?.classList.add("sim-skip"));
      }

      // Mark actions + expand sub-nodes
      const wouldRun = anyTriggerFires && allConditionsPass;
      actions.forEach((action, idx) => {
        const node = nodeEls[`action:${idx}`];
        if (node) node.classList.add(wouldRun ? "sim-pass" : "sim-skip");
        runSubNodesForAction(action, `action:${idx}`, wouldRun);
      });

      // Update result badge
      const badge = container.querySelector("#sim-result-badge");
      if (badge) {
        badge.className = `sim-result-badge ${wouldRun ? "pass" : "fail"}`;
        badge.textContent = wouldRun
          ? (isBlueprint ? t("pc_sim_would_trigger") : t("pc_sim_would_run"))
          : (!anyTriggerFires ? t("pc_sim_would_not_run_no_trigger") : !allConditionsPass ? t("pc_sim_would_not_run_condition") : t("pc_sim_would_not_run"));
      }
    }
  }

  _buildAutomationSections(workingConfig, changedSections, sectionsEl, yamlPre) {
    sectionsEl.innerHTML = "";
    const t = this._t || ((k) => k);
    const updateYaml = () => { if (yamlPre) yamlPre.textContent = this._configToYaml(workingConfig); };
    ["trigger", "condition", "action"].forEach((section) => {
      const items = workingConfig[section] || [];
      if (section === "condition" && items.length === 0) return;
      const labelMap = { trigger: t("pc_sim_triggers"), condition: t("pc_sim_conditions"), action: t("pc_sim_actions") };
      const sectionDiv = document.createElement("div");
      sectionDiv.className = "ae-section";
      const changed = changedSections.has(section);
      sectionDiv.innerHTML = `
        <div class="ae-section-header${changed ? " changed" : ""}">
          ${labelMap[section]}
          ${section === "condition" ? `<button class="ae-btn-test-section">${t("pc_test")}</button>` : ""}
        </div>
        <div class="ae-rows" data-section="${section}"></div>
      `;
      const rowsEl = sectionDiv.querySelector(".ae-rows");
      items.forEach((item, idx) => {
        const row = this._buildAutomationRow(item, section, idx, changedSections, () => {
          workingConfig[section].splice(idx, 1);
          updateYaml();
          this._buildAutomationSections(workingConfig, changedSections, sectionsEl, yamlPre);
        });
        rowsEl.appendChild(row);
      });
      // Redraw after a drop: rows and their delete handlers carry the old index
      this._setupDragAndDrop(rowsEl, workingConfig[section], () => {
        updateYaml();
        this._buildAutomationSections(workingConfig, changedSections, sectionsEl, yamlPre);
      });
      sectionsEl.appendChild(sectionDiv);
    });
  }

  /**
   * Restored cards (opts.restored, see _buildPlanCard) show a hint; a card
   * saved before (opts.status "done") keeps Apply locked and loses Cancel.
   * Apply/Cancel are recorded on opts.historyEntry.
   */
  _restoreAutomationCardState(card, opts, doneLabel) {
    if (!opts.restored) return;
    const applyBtn = card.querySelector(".ae-btn-apply");
    if (opts.status === "done") {
      applyBtn.disabled = true;
      applyBtn.textContent = doneLabel;
      card.querySelector(".ae-btn-cancel")?.remove();
    } else {
      card.querySelector(".ae-actions")?.before(this._buildRestoredNote());
    }
  }

  /**
   * "Open in editor": loads the card's current config into the YAML editor as an
   * unsaved draft and locks the card's Apply, so saving the card cannot
   * overwrite edits made in the editor. target: { entityId } for an existing
   * automation/script, { newConfigId, name } for one HA does not have yet.
   */
  async _openProposalInEditor(card, workingConfig, target) {
    const t = this._t || ((k) => k);
    const entityId = target.entityId || `automation.${target.newConfigId}`;
    await this._openEditor(entityId, target);
    // The editor's change listener marks the draft dirty and enables Save
    this._setEditorContent(this._configToYaml(workingConfig));
    this._setStatus(t("ed_proposal_loaded"), "warning");
    const applyBtn = card.querySelector(".ae-btn-apply");
    applyBtn.disabled = true;
    applyBtn.title = t("ae_in_editor");
    const resultEl = card.querySelector(".ae-result");
    resultEl.textContent = t("ae_in_editor");
    resultEl.className = "ae-result info";
  }

  /**
   * Problems the backend check still found after its correction rounds
   * (plan.check_warnings). Each finding carries a key for translation and the
   * English text as fallback.
   */
  _checkWarningsHtml(plan) {
    const warnings = Array.isArray(plan?.check_warnings) ? plan.check_warnings : [];
    if (!warnings.length) return "";
    const t = this._t || ((k) => k);
    const items = warnings.map((w) => {
      const params = {};
      for (const [k, v] of Object.entries(w.params || {})) params[k] = Array.isArray(v) ? v.join(", ") : v;
      const key = w.key === "bad_value" ? (params.attribute ? "ck_bad_attr_value" : "ck_bad_state") : `ck_${w.key}`;
      const text = t(key, params);
      return `<li>${this._escapeHtml(text === key ? (w.text || key) : text)}</li>`;
    }).join("");
    return `<div class="ae-check-warnings"><div class="ae-check-title">⚠ ${this._escapeHtml(t("ae_check_title"))}</div><ul>${items}</ul></div>`;
  }

  _buildEditAutomationCard(plan, opts = {}) {
    const t = this._t || ((k) => k);
    const workingConfig = JSON.parse(JSON.stringify(plan.modified_config || plan.original_config || {}));
    const isScript = (plan.entity_id || "").startsWith("script.");
    const kind = isScript ? "script" : "automation";
    const configId = plan.automation_id || (plan.entity_id || "").replace(/^(automation|script)\./, "");
    const autoName = workingConfig.alias || plan.entity_id || t("pc_automation_fallback");
    const changedSections = this._getChangedSections(plan.original_config, plan.modified_config);
    let originalConfig = plan.original_config || null;

    const card = document.createElement("div");
    card.className = "automation-edit-card";
    card.dataset.automationId = String(configId);
    card.innerHTML = `
      <div class="ae-header">
        <span class="ae-icon">🤖</span>
        <span class="ae-title">${this._escapeHtml(autoName)}</span>
        <span class="ae-badge">${t(kind === "script" ? "pc_kind_script" : "pc_kind_automation")}</span>
      </div>
      <div class="ae-summary">${this._escapeHtml(plan.summary || "")}</div>
      ${this._checkWarningsHtml(plan)}
      ${(plan.changes || []).length ? `
        <ul class="ae-changes">${(plan.changes || []).map((c) => `<li>${this._escapeHtml(c)}</li>`).join("")}</ul>
      ` : ""}
      <div class="ae-sections" style="display:none"></div>
      <details class="ae-yaml-details" style="display:none">
        <summary>YAML</summary>
        <pre class="ae-yaml-preview"></pre>
      </details>
      <div class="ae-actions">
        <button class="ae-btn-expand">${t("ae_view")}</button>
        <button class="ae-btn-test" style="display:none">${t("pc_test")}</button>
        <button class="ae-btn-editor">${t("ae_open_editor")}</button>
        <button class="ae-btn-apply">${t("ae_apply")}</button>
        <button class="ae-btn-cancel">${t("ae_cancel")}</button>
      </div>
      <div class="ae-result"></div>
    `;

    const sectionsEl = card.querySelector(".ae-sections");
    const yamlDetails = card.querySelector(".ae-yaml-details");
    const yamlPre = card.querySelector(".ae-yaml-preview");

    card.querySelector(".ae-btn-expand").addEventListener("click", () => {
      const expanded = sectionsEl.style.display !== "none";
      if (expanded) {
        sectionsEl.style.display = "none";
        yamlDetails.style.display = "none";
        card.querySelector(".ae-btn-expand").textContent = t("ae_view");
        card.querySelector(".ae-btn-test").style.display = "none";
      } else {
        sectionsEl.style.display = "";
        yamlDetails.style.display = "";
        this._buildAutomationSections(workingConfig, changedSections, sectionsEl, yamlPre);
        yamlPre.textContent = this._configToYaml(workingConfig);
        card.querySelector(".ae-btn-expand").textContent = t("ae_hide");
        card.querySelector(".ae-btn-test").style.display = "";
      }
    });

    card.querySelector(".ae-btn-test").addEventListener("click", () => {
      let testerEl = card.querySelector(".ae-tester");
      if (!testerEl) { testerEl = document.createElement("div"); testerEl.className = "ae-tester"; sectionsEl.after(testerEl); }
      this._buildAutomationTester(workingConfig, configId, testerEl);
    });

    card.querySelector(".ae-btn-editor").addEventListener("click", () => {
      const entityId = plan.entity_id || `${kind}.${configId}`;
      this._openProposalInEditor(card, workingConfig, { entityId }).catch(() => {});
    });

    card.querySelector(".ae-btn-apply").addEventListener("click", async () => {
      const applyBtn = card.querySelector(".ae-btn-apply");
      const cancelBtn = card.querySelector(".ae-btn-cancel");
      const resultEl = card.querySelector(".ae-result");
      applyBtn.disabled = true;
      applyBtn.textContent = t("ae_saving");
      try {
        const apiPath = isScript ? `config/script/config/${configId}` : `config/automation/config/${configId}`;
        // Undo needs the config as it was before saving. Plans rebuilt from a
        // malformed model answer may lack it, so read it from HA first.
        if (!originalConfig) {
          originalConfig = await this._hass.callApi("GET", apiPath).catch(() => null);
        }
        await this._hass.callApi("POST", apiPath, { ...workingConfig, id: configId });
        this._setRenderStatus(opts.historyEntry, "plan", "done");
        applyBtn.textContent = t("ae_saved");
        applyBtn.style.background = "var(--success, #4caf50)";
        // Without the previous config there is nothing to undo to.
        if (!originalConfig) cancelBtn.style.display = "none";
        cancelBtn.textContent = t("ae_undo");
        cancelBtn.dataset.mode = "undo";
        cancelBtn.onclick = async () => {
          try {
            await this._hass.callApi("POST", apiPath, { ...originalConfig, id: configId });
            // Undone: after a reload the card offers Apply again
            this._setRenderStatus(opts.historyEntry, "plan", "undone");
            cancelBtn.textContent = t("ae_restored");
            cancelBtn.disabled = true;
            // Re-enable apply so the user can re-apply after undo
            applyBtn.disabled = false;
            applyBtn.textContent = t("ae_reapply");
            applyBtn.style.background = "";
            // Sync editor & diagram after undo
            if (this._currentAutomationId === String(configId) && this._loadAutomation) {
              this._loadAutomation(String(configId)).catch(() => {});
            }
          } catch (e) { cancelBtn.textContent = t("ae_restore_failed"); }
        };
        // If this automation is currently open in the editor, reload it to sync YAML + diagram
        if (this._currentAutomationId === String(configId) && this._loadAutomation) {
          await this._loadAutomation(String(configId)).catch(() => {});
        }
      } catch (err) {
        applyBtn.disabled = false;
        applyBtn.textContent = t("ae_apply");
        resultEl.textContent = `${t("ae_error")} ${err.message}`;
        resultEl.className = "ae-result error";
      }
    });

    card.querySelector(".ae-btn-cancel").addEventListener("click", (e) => {
      if (e.currentTarget.dataset.mode === "undo") return; // undo handler takes over
      this._setRenderStatus(opts.historyEntry, "plan", "dismissed");
      card.remove();
    });
    this._restoreAutomationCardState(card, opts, t("ae_saved"));
    return card;
  }

  _buildCreateAutomationCard(plan, opts = {}) {
    const t = this._t || ((k) => k);
    const workingConfig = JSON.parse(JSON.stringify(plan.config || {}));
    const changedSections = new Set();

    const card = document.createElement("div");
    card.className = "automation-edit-card";
    card.dataset.automationId = "";
    card.innerHTML = `
      <div class="ae-header">
        <span class="ae-icon">🤖</span>
        <span class="ae-title">${this._escapeHtml(plan.alias || t("ae_new_automation"))}</span>
        <span class="ae-badge">${t("pc_kind_automation")}</span>
      </div>
      <div class="ae-summary">${this._escapeHtml(plan.summary || "")}</div>
      ${this._checkWarningsHtml(plan)}
      <div class="ae-sections" style="display:none"></div>
      <details class="ae-yaml-details" style="display:none">
        <summary>YAML</summary>
        <pre class="ae-yaml-preview"></pre>
      </details>
      <div class="ae-actions">
        <button class="ae-btn-expand">${t("ae_view")}</button>
        <button class="ae-btn-test" style="display:none">${t("pc_test")}</button>
        <button class="ae-btn-editor">${t("ae_open_editor")}</button>
        <button class="ae-btn-apply">${t("ae_create")}</button>
        <button class="ae-btn-cancel">${t("ae_cancel")}</button>
      </div>
      <div class="ae-result"></div>
    `;

    const sectionsEl = card.querySelector(".ae-sections");
    const yamlDetails = card.querySelector(".ae-yaml-details");
    const yamlPre = card.querySelector(".ae-yaml-preview");

    card.querySelector(".ae-btn-expand").addEventListener("click", () => {
      const expanded = sectionsEl.style.display !== "none";
      if (expanded) {
        sectionsEl.style.display = "none";
        yamlDetails.style.display = "none";
        card.querySelector(".ae-btn-expand").textContent = t("ae_view");
        card.querySelector(".ae-btn-test").style.display = "none";
      } else {
        sectionsEl.style.display = "";
        yamlDetails.style.display = "";
        this._buildAutomationSections(workingConfig, changedSections, sectionsEl, yamlPre);
        yamlPre.textContent = this._configToYaml(workingConfig);
        card.querySelector(".ae-btn-expand").textContent = t("ae_hide");
        card.querySelector(".ae-btn-test").style.display = "";
      }
    });

    card.querySelector(".ae-btn-test").addEventListener("click", () => {
      let testerEl = card.querySelector(".ae-tester");
      if (!testerEl) { testerEl = document.createElement("div"); testerEl.className = "ae-tester"; sectionsEl.after(testerEl); }
      this._buildAutomationTester(workingConfig, null, testerEl);
    });

    // One id per card, so opening the editor twice still saves a single automation
    let draftId = null;
    card.querySelector(".ae-btn-editor").addEventListener("click", () => {
      draftId = draftId || String(Date.now());
      const name = workingConfig.alias || plan.alias || t("ae_new_automation");
      const draft = { alias: name, ...workingConfig };
      this._openProposalInEditor(card, draft, { newConfigId: draftId, name }).catch(() => {});
    });

    card.querySelector(".ae-btn-apply").addEventListener("click", async () => {
      const applyBtn = card.querySelector(".ae-btn-apply");
      const resultEl = card.querySelector(".ae-result");
      applyBtn.disabled = true;
      applyBtn.textContent = t("ae_creating");
      try {
        const newId = String(Date.now());
        const configToSave = { ...workingConfig, id: newId };
        if (!configToSave.alias) configToSave.alias = plan.alias || "New Automation";
        await this._hass.callApi("POST", `config/automation/config/${newId}`, configToSave);
        this._setRenderStatus(opts.historyEntry, "plan", "done");
        applyBtn.textContent = t("ae_created");
        applyBtn.style.background = "var(--success, #4caf50)";
        card.querySelector(".ae-btn-cancel").textContent = t("pc_close");
      } catch (err) {
        applyBtn.disabled = false;
        applyBtn.textContent = t("ae_create");
        resultEl.textContent = `${t("ae_error")} ${err.message}`;
        resultEl.className = "ae-result error";
      }
    });

    card.querySelector(".ae-btn-cancel").addEventListener("click", () => {
      // After a successful create the button only closes the card; keep it on reload
      if (!card.querySelector(".ae-btn-apply").disabled) {
        this._setRenderStatus(opts.historyEntry, "plan", "dismissed");
      }
      card.remove();
    });
    this._restoreAutomationCardState(card, opts, t("ae_created"));
    return card;
  }
};
