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

    const card = document.createElement("div");
    card.className = "memory-card";
    card.innerHTML = `
      <div class="memory-card-header">🧠 Suggested memory</div>
      <div class="memory-card-content">
        "${userTerm}" → <strong>${haTerm}</strong><br>
        <small style="opacity:0.75">${action.content || learnedFact.summary || ""}</small>
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

    const changeRows = (plan.actions || [])
      .map((a) => {
        const missing = a.entity_id && invalidEntities.has(a.entity_id);
        const entityHtml = a.entity_id
          ? `<span class="change-entity${missing ? " entity-missing" : ""}">${this._escapeHtml(a.entity_id)}${missing ? " ⚠" : ""}</span>`
          : "";
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
          <li class="change-row${missing ? " row-invalid" : ""}">
            ${entityHtml}
            <span class="change-type-badge">${this._escapeHtml(typeLabel)}</span>
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

    // Split executable actions by approval requirement.
    // Config/destructive actions (assign_area, rename_entity, lock unlock, etc.)
    // ALWAYS need an explicit user click — autopilot cannot bypass them.
    const approvalActions = executableActions.filter((a) => a.requires_approval === true);
    const autoActions = executableActions.filter((a) => a.requires_approval !== true);
    const requiresApproval = plan.requires_approval === true || approvalActions.length > 0;
    const autopilotCanRun = this._autopilot && autoActions.length > 0;
    const approvalBadge = requiresApproval
      ? `<div class="plan-approval-note">🔒 ${approvalActions.length} action(s) change Home Assistant configuration and require your explicit approval.</div>`
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
      ${autopilotCanRun && !requiresApproval
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
          this._addChatHistory("assistant", `[CHANGE] The following changes were successfully applied:\n${changeLines.join("\n")}`);

          // Collect undo actions from results and show Undo button
          const undoActions = ok
            .map((r) => r.undo_action)
            .filter(Boolean);
          if (undoActions.length > 0) {
            const undoBtn = document.createElement("button");
            undoBtn.className = "btn-undo";
            undoBtn.textContent = `↩ Undo (${undoActions.length} action${undoActions.length > 1 ? "s" : ""})`;
            resultEl.after(undoBtn);
            undoBtn.addEventListener("click", async () => {
              undoBtn.disabled = true;
              undoBtn.textContent = "Undoing…";
              try {
                const token2 = this._hass.auth.data.access_token;
                const r2 = await fetch("/api/kyber/execute", {
                  method: "POST",
                  headers: { "Content-Type": "application/json", Authorization: `Bearer ${token2}` },
                  body: JSON.stringify({ actions: undoActions }),
                });
                const d2 = await r2.json();
                const f2 = (d2.results || []).filter((r) => r.status !== "ok");
                if (f2.length === 0) {
                  undoBtn.textContent = "↩ Undone ✓";
                  undoBtn.disabled = true;
                  resultEl.textContent = "↩ Changes undone successfully.";
                  resultEl.className = "plan-result success";
                  this._addChatHistory("assistant", `[CHANGE] Undid: ${plan.summary || "previous changes"}`);
                } else {
                  undoBtn.textContent = `↩ Undo failed (${f2.length} error${f2.length > 1 ? "s" : ""})`;
                  undoBtn.disabled = false;
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
      card.querySelector(".btn-execute").addEventListener("click", () => doExecute({ approved: true }));
    }

    // Autopilot: only auto-execute the SAFE subset (runtime state changes).
    // Config-changing/destructive actions always wait for explicit approval.
    if (this._autopilot && autoActions.length > 0 && !requiresApproval) {
      setTimeout(() => doExecute({ approved: false, actions: autoActions }), 2000);
    } else if (this._autopilot && autoActions.length > 0 && requiresApproval) {
      // Mixed plan: auto-run safe ones, leave Execute button for the rest.
      setTimeout(() => {
        resultEl.textContent = `⚡ Autopilot: running ${autoActions.length} safe action(s); config changes await your approval…`;
        doExecute({ approved: false, actions: autoActions });
      }, 2000);
    }

    return card;
  }
};
