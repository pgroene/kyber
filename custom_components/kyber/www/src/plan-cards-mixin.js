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

  _buildMemoryCard(learnedFact) {
    const action = (learnedFact.actions || [])[0] || {};
    const userTerm = action.description?.match(/Save alias: (.+?) →/)?.[1]
      || learnedFact.summary?.match(/'(.+?)'/)?.[1]
      || "?";
    const haTerm = action.subject || learnedFact.summary?.match(/→ '(.+?)'/)?.[1] || "?";
    const contentText = action.content || learnedFact.summary || "";

    const card = document.createElement("div");
    card.className = "memory-card";
    card.innerHTML = `
      <div class="memory-card-header">🧠 Suggested memory</div>
      <div class="memory-card-content">
        "${this._escapeHtml(userTerm)}" → <strong>${this._escapeHtml(haTerm)}</strong><br>
        <small style="opacity:0.75">${this._escapeHtml(contentText)}</small>
      </div>
      <button class="btn-remember">💾 Remember</button>
    `;

    const btn = card.querySelector(".btn-remember");
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      btn.textContent = "Saving…";
      try {
        const token = this._hass?.auth?.data?.access_token;
        const resp = await fetch("/api/kyber/plan/execute", {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
          body: JSON.stringify({ plan: learnedFact }),
        });
        if (resp.ok) {
          btn.textContent = "✅ Remembered!";
          btn.style.background = "var(--success, #4caf50)";
        } else {
          btn.textContent = "⚠️ Failed";
          btn.disabled = false;
        }
      } catch (err) {
        btn.textContent = "⚠️ Error";
        btn.disabled = false;
      }
    });
    return card;
  }

  _buildPlanCard(plan) {
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
      assign_area: "Area",
      rename_entity: "Name",
      assign_label: "Label",
      remove_label: "Remove label",
      create_area: "Create area",
      rename_area: "Rename area",
      delete_area: "Delete area",
      call_service: "Service",
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
            ${a.high_risk ? `<span class="change-type-badge">⚠ High risk</span>` : ""}
            <span class="change-delta">${arrow}</span>
          </li>`;
      })
      .join("");

    const warnings = (plan.warnings || [])
      .map((w) => `<div class="plan-warning">⚠ ${this._escapeHtml(w)}</div>`)
      .join("");

    const missingWarning = invalidEntities.size > 0
      ? `<div class="plan-warning plan-warning-error">⛔ ${invalidEntities.size} entity ID(s) not found in Home Assistant: ${[...invalidEntities].map((e) => this._escapeHtml(e)).join(", ")}. These actions will be skipped.</div>`
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
    const autopilotCanRun = this._autopilot && autoActions.length > 0 && !requiresApproval;
    const approvalBadge = approvalActions.length > 0
      ? `<div class="plan-approval-note">🔒 ${approvalActions.length} action(s) require approval${highRiskDomains.length ? ` — high risk: ${highRiskDomains.map((d) => this._escapeHtml(d)).join(", ")}` : ""}.</div>`
      : "";
    const guardrailPrompt = this._autopilot && highRiskDomains.length > 0
      ? `<label class="plan-warning"><input type="checkbox" class="guardrail-override-checkbox"> Allow autopilot for ${this._escapeHtml(highRiskDomains.join(", "))} after I approve this plan.</label>`
      : "";

    card.innerHTML = `
      <div class="plan-overview">
        <div class="plan-overview-label">📋 Proposal</div>
        <div class="plan-overview-summary">${this._escapeHtml(plan.summary || "")}</div>
      </div>
      <div class="plan-changes-header">What will change</div>
      <ul class="plan-changes">${changeRows}</ul>
      ${missingWarning}
      ${warnings}
      ${approvalBadge}
      ${guardrailPrompt}
      ${autopilotCanRun
        ? `<div class="plan-result" style="color:var(--warning-color,#ff9800);font-size:12px">⚡ Autopilot: executing in 2s…</div>`
        : `<button class="btn-execute"${hasExecutable ? "" : " disabled"}>✅ Execute${invalidEntities.size > 0 && hasExecutable ? ` (${executableActions.length} of ${(plan.actions || []).length})` : ""}</button>`
      }
      <div class="plan-result" id="plan-result-${Date.now()}"></div>
    `;

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
      resultEl.textContent = "Executing…";
      resultEl.className = "plan-result";
      try {
        const token = this._hass.auth.data.access_token;
        const resp = await fetch("/api/kyber/execute", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({ actions: actionsToRun, approved, summary: plan.summary || "" }),
        });
        if (resp.status === 403) {
          const blocked = await resp.json().catch(() => ({}));
          resultEl.textContent = `🔒 Approval required for ${(blocked.blocked_actions || []).length} action(s). Click Execute to approve.`;
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
          resultEl.textContent = `✅ Done — ${executableActions.length} action(s) applied.`;
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
            undoBtn.textContent = `↩ Undo (${undoCount} action${undoCount > 1 ? "s" : ""})`;
            resultEl.after(undoBtn);
            undoBtn.addEventListener("click", async () => {
              undoBtn.disabled = true;
              undoBtn.textContent = "Undoing…";
              try {
                const token2 = this._hass.auth.data.access_token;
                const request = historyEntry
                  ? fetch(`/api/kyber/history/actions/${encodeURIComponent(historyEntry.id)}/undo`, {
                      method: "POST",
                      headers: { Authorization: `Bearer ${token2}` },
                    })
                  : fetch("/api/kyber/execute", {
                      method: "POST",
                      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token2}` },
                      body: JSON.stringify({ actions: undoActions, approved: true }),
                    });
                const r2 = await request;
                const d2 = await r2.json();
                if (!r2.ok || d2.status === "failed") {
                  throw new Error(d2.message || `HTTP ${r2.status}`);
                }
                undoBtn.textContent = "↩ Undone ✓";
                undoBtn.disabled = true;
                resultEl.textContent = "↩ Changes undone successfully.";
                resultEl.className = "plan-result success";
                this._addChatHistory("assistant", `[CHANGE] Undid: ${plan.summary || "previous changes"}`);
                if (typeof this._loadActionHistory === "function") {
                  this._loadActionHistory();
                }
              } catch (e) {
                undoBtn.textContent = `↩ Undo error: ${e.message}`;
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
              <span>${this._escapeHtml(labelInfo.label_name)} applied to ${this._escapeHtml(labelInfo.entity_name)}</span>
              <button class="kyber-undo-label-btn">↩ Undo</button>
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
                btn.textContent = "⚠ Error"; btn.disabled = false;
              }
            });
            resultEl.after(chip);
          });
        } else {
          const failedMsgs = failed.map((r) => r.message || "unknown error").join("; ");
          resultEl.textContent = `⚠ ${failed.length} action(s) failed: ${failedMsgs}`;
          resultEl.className = "plan-result error";

          // Record failure in chat history so the AI knows what happened
          this._addChatHistory(
            "assistant",
            `[FAILED] ${failed.length} action(s) failed for "${plan.summary || "plan"}": ${failedMsgs}`
          );

          // ── Correction micro-agent result ─────────────────────────────────
          if (data.correction && data.correction.corrected_actions && data.correction.corrected_actions.length > 0) {
            const corr = data.correction;
            resultEl.textContent += `\n🔧 Correction: ${corr.message || "Retrying with corrected plan…"}`;

            // Show toast for learned fact
            if (corr.learned_fact && typeof this._showToast === "function") {
              this._showToast(corr.learned_fact);
            }

            // Execute corrected actions automatically
            setTimeout(async () => {
              try {
                const token = this._hass.auth.data.access_token;
                const corrResp = await fetch("/api/kyber/execute", {
                  method: "POST",
                  headers: {
                    "Content-Type": "application/json",
                    Authorization: `Bearer ${token}`,
                  },
                  body: JSON.stringify({ actions: corr.corrected_actions, approved: opts.approved !== false }),
                });
                const corrData = await corrResp.json();
                const corrFailed = (corrData.results || []).filter((r) => r.status !== "ok");
                if (corrFailed.length === 0) {
                  resultEl.textContent = `🔧 Corrected & applied — ${corr.corrected_actions.length} action(s)`;
                  resultEl.className = "plan-result success";
                  this._addChatHistory(
                    "assistant",
                    `[🔧 CORRECTION] Successfully applied corrected plan: ${corr.message || plan.summary || ""}`
                  );
                } else {
                  resultEl.textContent = `🔧 Correction also failed: ${corrFailed.map((r) => r.message).join("; ")}`;
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
        resultEl.textContent = `Error: ${err.message}`;
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
  _configToYaml(obj, indent = 0) {
    const pad = "  ".repeat(indent);
    if (obj === null || obj === undefined) return "null";
    if (typeof obj === "boolean") return obj ? "true" : "false";
    if (typeof obj === "number") return String(obj);
    if (typeof obj === "string") {
      if (/[:{}\[\],&*?|<>=!%@`]/.test(obj) || /^(true|false|yes|no|null|~|\d)/.test(obj) || obj.includes("\n")) {
        return `"${obj.replace(/\\/g, "\\\\").replace(/"/g, '\\"').replace(/\n/g, "\\n")}"`;
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

  _describeTrigger(t) {
    const p = t.platform || t.trigger || "";
    switch (p) {
      case "time": return `🕐 At ${t.at || "?"}`;
      case "time_pattern": return `🕐 Every${t.hours ? ` ${t.hours}h` : ""}${t.minutes ? ` ${t.minutes}m` : ""}${t.seconds ? ` ${t.seconds}s` : ""}`;
      case "state": {
        const eid = Array.isArray(t.entity_id) ? t.entity_id.join(", ") : (t.entity_id || "?");
        return `🔄 ${eid}${t.to != null ? ` → ${t.to}` : ""}`;
      }
      case "sun": return `🌅 Sun ${t.event || "?"}`;
      case "homeassistant": return `🏠 HA ${t.event || "start"}`;
      case "template": return `📋 Template trigger`;
      case "numeric_state": {
        const eid = Array.isArray(t.entity_id) ? t.entity_id[0] : (t.entity_id || "?");
        return `🔢 ${eid}${t.above != null ? ` > ${t.above}` : ""}${t.below != null ? ` < ${t.below}` : ""}`;
      }
      case "zone": return `📍 ${t.entity_id || "?"} ${t.event || "enter/leave"} ${t.zone || ""}`;
      case "webhook": return `🌐 Webhook: ${t.webhook_id || "?"}`;
      case "conversation": return `💬 "${Array.isArray(t.command) ? t.command[0] : (t.command || "?")}"`;
      default: return `⚡ ${p || "trigger"}`;
    }
  }

  _describeCondition(c) {
    const type = c.condition || "";
    switch (type) {
      case "state": {
        const eid = Array.isArray(c.entity_id) ? c.entity_id.join(", ") : (c.entity_id || "?");
        const st = Array.isArray(c.state) ? c.state.join("/") : (c.state ?? "?");
        return `✅ ${eid} = ${st}`;
      }
      case "not": return `🚫 Not (${(c.conditions || []).length} condition${(c.conditions || []).length !== 1 ? "s" : ""})`;
      case "and": return `🔗 All of ${(c.conditions || []).length} conditions`;
      case "or": return `⚡ Any of ${(c.conditions || []).length} conditions`;
      case "template": return `📋 Template condition`;
      case "time": return `🕐 Time: ${c.after || ""}–${c.before || ""}`;
      case "numeric_state": {
        const eid = Array.isArray(c.entity_id) ? c.entity_id[0] : (c.entity_id || "?");
        return `🔢 ${eid}${c.above != null ? ` > ${c.above}` : ""}${c.below != null ? ` < ${c.below}` : ""}`;
      }
      case "zone": return `📍 ${c.entity_id || "?"} in ${c.zone || "?"}`;
      case "trigger": return `🔄 Trigger id: ${c.id || "?"}`;
      default: return `❓ ${type || "condition"}`;
    }
  }

  _describeAction(a) {
    const svc = a.service || a.action || "";
    if (svc) {
      const target = a.target?.entity_id || a.entity_id || "";
      const t = Array.isArray(target) ? target[0] : target;
      return `▶ ${svc}${t ? `  [${t}]` : ""}`;
    }
    if (a.delay !== undefined) return `⏱ Wait ${typeof a.delay === "object" ? JSON.stringify(a.delay) : a.delay}`;
    if (a.wait_template !== undefined) return "⏳ Wait for template";
    if (a.wait_for_trigger !== undefined) return "⏳ Wait for trigger";
    if (a.condition !== undefined) return "🔀 Stop if condition fails";
    if (a.choose !== undefined) return `🔀 Choose (${(a.choose || []).length} option${(a.choose || []).length !== 1 ? "s" : ""})`;
    if (a.if !== undefined) return "❓ If...then...else";
    if (a.repeat !== undefined) return `🔁 Repeat${a.repeat?.count ? ` ${a.repeat.count}×` : ""}`;
    if (a.parallel !== undefined) return "⚡ Parallel actions";
    if (a.variables !== undefined) return "📦 Set variables";
    if (a.event !== undefined) return `📣 Fire event: ${a.event}`;
    return "⚡ Action";
  }

  _evalConditionWithMocks(cond, mocks) {
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
      case "and": return (cond.conditions || []).every((c) => this._evalConditionWithMocks(c, mocks));
      case "or": return (cond.conditions || []).some((c) => this._evalConditionWithMocks(c, mocks));
      case "not": return !(cond.conditions || []).some((c) => this._evalConditionWithMocks(c, mocks));
      default: return null;
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
    row.draggable = true;
    row.dataset.idx = idx;
    const descFn = section === "trigger" ? this._describeTrigger.bind(this)
      : section === "condition" ? this._describeCondition.bind(this)
      : this._describeAction.bind(this);
    const desc = descFn(item);
    const isChanged = changedSections.has(section);
    row.innerHTML = `
      <span class="ae-drag-handle" title="Sleep om te herschikken">⠿</span>
      <span class="ae-row-desc${isChanged ? " changed" : ""}">${this._escapeHtml(desc)}</span>
      <button class="ae-row-delete" title="Verwijder">🗑</button>
    `;
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
    const allEntityIds = this._extractEntityIds(config);
    const mocks = {};
    const currentStates = {};
    allEntityIds.forEach((eid) => {
      currentStates[eid] = this._hass?.states[eid]?.state ?? "?";
    });

    const buildMockUI = () => {
      container.innerHTML = `
        <div class="ae-tester-header">🧪 Automation simulatie</div>
        ${allEntityIds.length ? `
          <div class="ae-tester-desc">Overschrijf waarden om te simuleren:</div>
          <div class="ae-tester-mocks"></div>
        ` : ""}
        <button class="ae-tester-run">▶ Simuleer</button>
        <div class="ae-tester-results"></div>
      `;
      const mocksEl = container.querySelector(".ae-tester-mocks");
      if (mocksEl) {
        allEntityIds.forEach((eid) => {
          const row = document.createElement("div");
          row.className = "ae-mock-row";
          row.innerHTML = `
            <span class="ae-mock-eid">${this._escapeHtml(eid)}</span>
            <span class="ae-mock-live">live: ${this._escapeHtml(currentStates[eid])}</span>
            <input class="ae-mock-input" data-eid="${this._escapeHtml(eid)}"
                   placeholder="${this._escapeHtml(currentStates[eid])}"
                   value="${this._escapeHtml(mocks[eid] || "")}">
          `;
          mocksEl.appendChild(row);
        });
      }
      container.querySelector(".ae-tester-run").addEventListener("click", () => {
        container.querySelectorAll(".ae-mock-input").forEach((inp) => {
          const val = inp.value.trim();
          if (val) mocks[inp.dataset.eid] = val;
          else delete mocks[inp.dataset.eid];
        });
        runSimulation();
      });
    };

    const runSimulation = () => {
      const resultsEl = container.querySelector(".ae-tester-results");
      resultsEl.innerHTML = "";
      const triggers = config.trigger || config.triggers || [];
      const conditions = config.condition || config.conditions || [];
      const actions = config.action || config.actions || [];

      let anyTriggerFires = triggers.length === 0;
      const trigSection = document.createElement("div");
      trigSection.className = "ae-sim-section";
      trigSection.innerHTML = `<div class="ae-sim-label">TRIGGERS</div>`;
      triggers.forEach((t) => {
        const result = this._evalTriggerWithMocks(t, mocks);
        if (result === true) anyTriggerFires = true;
        const item = document.createElement("div");
        item.className = "ae-sim-item";
        item.textContent = `${result === true ? "✅" : result === false ? "❌" : "❓"} ${this._describeTrigger(t)}`;
        if (result === null) item.style.opacity = "0.6";
        trigSection.appendChild(item);
      });
      resultsEl.appendChild(trigSection);

      let allConditionsPass = true;
      if (conditions.length) {
        const condSection = document.createElement("div");
        condSection.className = "ae-sim-section";
        condSection.innerHTML = `<div class="ae-sim-label">CONDITIONS</div>`;
        conditions.forEach((c) => {
          const result = this._evalConditionWithMocks(c, mocks);
          if (result === false) allConditionsPass = false;
          const item = document.createElement("div");
          item.className = "ae-sim-item";
          item.textContent = `${result === true ? "✅" : result === false ? "❌" : "❓"} ${this._describeCondition(c)}`;
          if (result === false) { item.style.fontWeight = "600"; item.style.color = "var(--danger, #e53935)"; }
          condSection.appendChild(item);
        });
        resultsEl.appendChild(condSection);
      }

      const automationWouldRun = anyTriggerFires && allConditionsPass;
      if (actions.length) {
        const actSection = document.createElement("div");
        actSection.className = "ae-sim-section";
        actSection.innerHTML = `<div class="ae-sim-label">ACTIONS${automationWouldRun ? "" : " (overgeslagen)"}</div>`;
        actions.forEach((a) => {
          const item = document.createElement("div");
          item.className = "ae-sim-item";
          item.textContent = `${automationWouldRun ? "✅" : "⬜"} ${this._describeAction(a)}`;
          if (!automationWouldRun) item.style.opacity = "0.5";
          actSection.appendChild(item);
        });
        resultsEl.appendChild(actSection);
      }

      const resultDiv = document.createElement("div");
      resultDiv.className = `ae-sim-result ${automationWouldRun ? "pass" : "fail"}`;
      resultDiv.textContent = automationWouldRun
        ? "✅ Automation ZOU draaien"
        : `❌ Automation zou NIET draaien${!anyTriggerFires ? " (geen trigger vuurt)" : !allConditionsPass ? " (conditie faalt)" : ""}`;
      resultsEl.appendChild(resultDiv);
    };

    buildMockUI();
    runSimulation();
  }

  _buildAutomationSections(workingConfig, changedSections, sectionsEl, yamlPre) {
    sectionsEl.innerHTML = "";
    const updateYaml = () => { if (yamlPre) yamlPre.textContent = this._configToYaml(workingConfig); };
    ["trigger", "condition", "action"].forEach((section) => {
      const items = workingConfig[section] || [];
      if (section === "condition" && items.length === 0) return;
      const labelMap = { trigger: "TRIGGERS", condition: "CONDITIONS", action: "ACTIONS" };
      const sectionDiv = document.createElement("div");
      sectionDiv.className = "ae-section";
      const changed = changedSections.has(section);
      sectionDiv.innerHTML = `
        <div class="ae-section-header${changed ? " changed" : ""}">
          ${labelMap[section]}
          ${section === "condition" ? `<button class="ae-btn-test-section">🧪 Test</button>` : ""}
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
      this._setupDragAndDrop(rowsEl, workingConfig[section], () => { updateYaml(); });
      sectionsEl.appendChild(sectionDiv);
    });
  }

  _buildEditAutomationCard(plan) {
    const workingConfig = JSON.parse(JSON.stringify(plan.modified_config || plan.original_config || {}));
    const isScript = (plan.entity_id || "").startsWith("script.");
    const kind = isScript ? "script" : "automation";
    const configId = plan.automation_id || (plan.entity_id || "").replace(/^(automation|script)\./, "");
    const autoName = workingConfig.alias || plan.entity_id || "Automation";
    const changedSections = this._getChangedSections(plan.original_config, plan.modified_config);

    const card = document.createElement("div");
    card.className = "automation-edit-card";
    card.dataset.automationId = String(configId);
    card.innerHTML = `
      <div class="ae-header">
        <span class="ae-icon">🤖</span>
        <span class="ae-title">${this._escapeHtml(autoName)}</span>
        <span class="ae-badge">${kind}</span>
      </div>
      <div class="ae-summary">${this._escapeHtml(plan.summary || "")}</div>
      ${(plan.changes || []).length ? `
        <ul class="ae-changes">${(plan.changes || []).map((c) => `<li>${this._escapeHtml(c)}</li>`).join("")}</ul>
      ` : ""}
      <div class="ae-sections" style="display:none"></div>
      <details class="ae-yaml-details" style="display:none">
        <summary>▼ YAML</summary>
        <pre class="ae-yaml-preview"></pre>
      </details>
      <div class="ae-actions">
        <button class="ae-btn-expand">▼ Bekijk</button>
        <button class="ae-btn-test" style="display:none">🧪 Test</button>
        <button class="ae-btn-apply">✓ Toepassen</button>
        <button class="ae-btn-cancel">✕ Annuleren</button>
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
        card.querySelector(".ae-btn-expand").textContent = "▼ Bekijk";
        card.querySelector(".ae-btn-test").style.display = "none";
      } else {
        sectionsEl.style.display = "";
        yamlDetails.style.display = "";
        this._buildAutomationSections(workingConfig, changedSections, sectionsEl, yamlPre);
        yamlPre.textContent = this._configToYaml(workingConfig);
        card.querySelector(".ae-btn-expand").textContent = "▲ Verberg";
        card.querySelector(".ae-btn-test").style.display = "";
      }
    });

    card.querySelector(".ae-btn-test").addEventListener("click", () => {
      let testerEl = card.querySelector(".ae-tester");
      if (!testerEl) { testerEl = document.createElement("div"); testerEl.className = "ae-tester"; sectionsEl.after(testerEl); }
      this._buildAutomationTester(workingConfig, configId, testerEl);
    });

    card.querySelector(".ae-btn-apply").addEventListener("click", async () => {
      const applyBtn = card.querySelector(".ae-btn-apply");
      const cancelBtn = card.querySelector(".ae-btn-cancel");
      const resultEl = card.querySelector(".ae-result");
      applyBtn.disabled = true;
      applyBtn.textContent = "Opslaan…";
      try {
        const apiPath = isScript ? `config/script/config/${configId}` : `config/automation/config/${configId}`;
        const resp = await fetch(`/api/${apiPath}`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${this._hass.auth.data.access_token}` },
          body: JSON.stringify({ ...workingConfig, id: configId }),
        });
        if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`);
        applyBtn.textContent = "✓ Opgeslagen";
        applyBtn.style.background = "var(--success, #4caf50)";
        cancelBtn.textContent = "↩ Ongedaan maken";
        cancelBtn.dataset.mode = "undo";
        cancelBtn.onclick = async () => {
          try {
            await fetch(`/api/${apiPath}`, {
              method: "POST",
              headers: { "Content-Type": "application/json", Authorization: `Bearer ${this._hass.auth.data.access_token}` },
              body: JSON.stringify({ ...(plan.original_config || workingConfig), id: configId }),
            });
            cancelBtn.textContent = "✓ Hersteld";
            cancelBtn.disabled = true;
          } catch (e) { cancelBtn.textContent = "⚠ Herstel mislukt"; }
        };
      } catch (err) {
        applyBtn.disabled = false;
        applyBtn.textContent = "✓ Toepassen";
        resultEl.textContent = `Fout: ${err.message}`;
        resultEl.className = "ae-result error";
      }
    });

    card.querySelector(".ae-btn-cancel").addEventListener("click", (e) => {
      if (e.currentTarget.dataset.mode === "undo") return; // undo handler takes over
      card.remove();
    });
    return card;
  }

  _buildCreateAutomationCard(plan) {
    const workingConfig = JSON.parse(JSON.stringify(plan.config || {}));
    const changedSections = new Set();

    const card = document.createElement("div");
    card.className = "automation-edit-card";
    card.dataset.automationId = "";
    card.innerHTML = `
      <div class="ae-header">
        <span class="ae-icon">🤖</span>
        <span class="ae-title">${this._escapeHtml(plan.alias || "Nieuwe automatisering")}</span>
        <span class="ae-badge">automation</span>
      </div>
      <div class="ae-summary">${this._escapeHtml(plan.summary || "")}</div>
      <div class="ae-sections" style="display:none"></div>
      <details class="ae-yaml-details" style="display:none">
        <summary>▼ YAML</summary>
        <pre class="ae-yaml-preview"></pre>
      </details>
      <div class="ae-actions">
        <button class="ae-btn-expand">▼ Bekijk</button>
        <button class="ae-btn-test" style="display:none">🧪 Test</button>
        <button class="ae-btn-apply">✓ Aanmaken</button>
        <button class="ae-btn-cancel">✕ Annuleren</button>
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
        card.querySelector(".ae-btn-expand").textContent = "▼ Bekijk";
        card.querySelector(".ae-btn-test").style.display = "none";
      } else {
        sectionsEl.style.display = "";
        yamlDetails.style.display = "";
        this._buildAutomationSections(workingConfig, changedSections, sectionsEl, yamlPre);
        yamlPre.textContent = this._configToYaml(workingConfig);
        card.querySelector(".ae-btn-expand").textContent = "▲ Verberg";
        card.querySelector(".ae-btn-test").style.display = "";
      }
    });

    card.querySelector(".ae-btn-test").addEventListener("click", () => {
      let testerEl = card.querySelector(".ae-tester");
      if (!testerEl) { testerEl = document.createElement("div"); testerEl.className = "ae-tester"; sectionsEl.after(testerEl); }
      this._buildAutomationTester(workingConfig, null, testerEl);
    });

    card.querySelector(".ae-btn-apply").addEventListener("click", async () => {
      const applyBtn = card.querySelector(".ae-btn-apply");
      const resultEl = card.querySelector(".ae-result");
      applyBtn.disabled = true;
      applyBtn.textContent = "Aanmaken…";
      try {
        const newId = String(Date.now());
        const configToSave = { ...workingConfig, id: newId };
        if (!configToSave.alias) configToSave.alias = plan.alias || "New Automation";
        const resp = await fetch(`/api/config/automation/config/${newId}`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${this._hass.auth.data.access_token}` },
          body: JSON.stringify(configToSave),
        });
        if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`);
        applyBtn.textContent = "✓ Aangemaakt";
        applyBtn.style.background = "var(--success, #4caf50)";
        card.querySelector(".ae-btn-cancel").textContent = "✕ Sluiten";
      } catch (err) {
        applyBtn.disabled = false;
        applyBtn.textContent = "✓ Aanmaken";
        resultEl.textContent = `Fout: ${err.message}`;
        resultEl.className = "ae-result error";
      }
    });

    card.querySelector(".ae-btn-cancel").addEventListener("click", () => card.remove());
    return card;
  }
};
