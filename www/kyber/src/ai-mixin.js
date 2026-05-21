export const AIMixin = (Base) => class extends Base {
  async _downloadDebugBundle(requestId, btn) {
    const token = this._hass.auth.data.access_token;
    const orig = btn ? btn.textContent : "";
    if (btn) { btn.disabled = true; btn.textContent = "⏳ packing…"; }
    try {
      const resp = await fetch(`/api/kyber/debug/bundle?request_id=${encodeURIComponent(requestId)}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `kyber-debug-${requestId}.zip`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      if (btn) btn.textContent = "✓ downloaded";
      setTimeout(() => { if (btn) { btn.textContent = orig; btn.disabled = false; } }, 1500);
    } catch (err) {
      if (btn) { btn.textContent = `⚠ ${err.message}`; btn.disabled = false; }
    }
  }

        async _openBugReportFlow(requestId, btn) {
          const token = this._hass.auth.data.access_token;
          const shadow = this.shadowRoot;

          // Build and mount the overlay
          const overlay = document.createElement("div");
          overlay.className = "bug-report-overlay";
          overlay.innerHTML = `
            <div class="bug-report-dialog" id="br-dialog">
              <h3>🐛 Create Bug Report</h3>
              <label>What did you ask Kyber?
                <textarea id="br-asked" rows="2" placeholder="e.g. Turn on the kitchen lights"></textarea>
              </label>
              <label>What did you expect to happen?
                <textarea id="br-expected" rows="2" placeholder="e.g. Kitchen lights turn on"></textarea>
              </label>
              <label>What actually happened?
                <textarea id="br-happened" rows="3" placeholder="e.g. Nothing happened / wrong room / error message"></textarea>
              </label>
              <div class="bug-report-bundle-name">Bundle: <code>${this._escapeHtml(`kyber-debug-${requestId}.zip`)}</code></div>
              <label class="bug-report-checkbox">
                <input type="checkbox" id="br-include-bundle">
                Include debug bundle summary (PII will be redacted)
              </label>
              <div class="bug-report-actions">
                <button class="bug-report-btn-cancel" id="br-cancel">Cancel</button>
                <button class="bug-report-btn-submit" id="br-submit">Generate report →</button>
              </div>
            </div>`;
          shadow.appendChild(overlay);

          const close = () => overlay.remove();
          overlay.querySelector("#br-cancel").addEventListener("click", close);
          overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });

          overlay.querySelector("#br-submit").addEventListener("click", async () => {
            const asked = overlay.querySelector("#br-asked").value.trim();
            const expected = overlay.querySelector("#br-expected").value.trim();
            const happened = overlay.querySelector("#br-happened").value.trim();
            const includeBundle = overlay.querySelector("#br-include-bundle").checked;

            if (!asked && !happened) {
              overlay.querySelector("#br-happened").focus();
              return;
            }

            // Step 2: spinner
            const dlg = overlay.querySelector("#br-dialog");
            dlg.innerHTML = `<div class="bug-report-spinner">⏳ Generating bug report…</div>`;

            let data;
            try {
              const resp = await fetch("/api/kyber/debug/bug-report", {
                method: "POST",
                headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
                body: JSON.stringify({
                  request_id: requestId,
                  what_asked: asked,
                  what_expected: expected,
                  what_happened: happened,
                  include_bundle: includeBundle,
                  bundle_name: `kyber-debug-${requestId}.zip`,
                }),
              });
              if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
              data = await resp.json();
            } catch (err) {
              dlg.innerHTML = `<h3>🐛 Bug Report</h3><p style="color:var(--error-color,#f44)">Failed: ${this._escapeHtml(err.message)}</p><div class="bug-report-actions"><button class="bug-report-btn-cancel" id="br-cancel2">Close</button></div>`;
              dlg.querySelector("#br-cancel2").addEventListener("click", close);
              return;
            }

            // Step 3: review
            const similar = (data.similar_issues || []);
            const similarHtml = similar.length
              ? `<div class="bug-report-similar"><strong>Similar open issues:</strong><ul style="margin:4px 0 0;padding-left:18px">${similar.map(i => `<li><a href="${this._escapeAttr(i.url)}" target="_blank">#${i.number} ${this._escapeHtml(i.title)}</a> [${i.state}]</li>`).join("")}</ul></div>`
              : "";
            const noBundleNote = data.bundle_available === false
              ? `<div class="bug-report-bundle-name" style="color:var(--warning-color,#f90)">⚠ Debug snapshot not available — bundle data was not included. Attach the zip file manually after opening the issue.</div>`
              : `<div class="bug-report-bundle-name" style="color:var(--success-color,#4caf50)">📎 After opening the issue on GitHub, attach the <code>${this._escapeHtml(`kyber-debug-${requestId}.zip`)}</code> file.</div>`;

            const encodedTitle = encodeURIComponent(data.title || "");
            const encodedBody = encodeURIComponent(data.body || "");
            const ghUrl = `https://github.com/pgroene/kyber/issues/new?title=${encodedTitle}&body=${encodedBody}`;

            dlg.innerHTML = `
              <h3>🐛 Review Bug Report</h3>
              ${noBundleNote}
              ${similarHtml}
              <label class="bug-report-result-title">Title
                <input type="text" id="br-title" value="${this._escapeAttr(data.title || "")}">
              </label>
              <label>Body (markdown)
                <textarea id="br-body" rows="12">${this._escapeHtml(data.body || "")}</textarea>
              </label>
              <div class="bug-report-actions">
                <button class="bug-report-btn-cancel" id="br-close">Close</button>
                <button class="bug-report-btn-submit" id="br-download">⬇ Download bundle</button>
                <button class="bug-report-btn-submit" id="br-copy">📋 Copy</button>
                <button class="bug-report-btn-submit" id="br-open-gh">Open on GitHub ↗</button>
              </div>`;

            dlg.querySelector("#br-close").addEventListener("click", close);
            dlg.querySelector("#br-download")?.addEventListener("click", () => {
              this._downloadDebugBundle(requestId, dlg.querySelector("#br-download"));
            });
            dlg.querySelector("#br-copy").addEventListener("click", () => {
              const title = dlg.querySelector("#br-title").value;
              const body = dlg.querySelector("#br-body").value;
              const bugText = `## ${title}\n\n${body}`;
              const btn2 = dlg.querySelector("#br-copy");
              const doCopy3 = navigator.clipboard?.writeText
                ? navigator.clipboard.writeText(bugText)
                : new Promise((resolve, reject) => {
                    try {
                      const ta = document.createElement("textarea");
                      ta.value = bugText;
                      ta.style.cssText = "position:fixed;top:-9999px;left:-9999px;opacity:0";
                      document.body.appendChild(ta);
                      ta.focus(); ta.select();
                      document.execCommand("copy");
                      document.body.removeChild(ta);
                      resolve();
                    } catch (e) { reject(e); }
                  });
              doCopy3.then(() => {
                btn2.textContent = "✓ Copied!";
                setTimeout(() => { btn2.textContent = "📋 Copy"; }, 2000);
              }).catch(() => {
                btn2.textContent = "⚠ Copy failed";
                setTimeout(() => { btn2.textContent = "📋 Copy"; }, 2000);
              });
            });
            dlg.querySelector("#br-open-gh").addEventListener("click", () => {
              const t = encodeURIComponent(dlg.querySelector("#br-title").value);
              const b = encodeURIComponent(dlg.querySelector("#br-body").value);
              window.open(`https://github.com/pgroene/kyber/issues/new?title=${t}&body=${b}`, "_blank");
            });
          });
        }

  async _submitTurnFeedback(rating, knowledgeIds, btnsRoot) {
    const status = btnsRoot.querySelector(".tf-status");
    btnsRoot.querySelectorAll(".tf-btn-rate").forEach((b) => (b.disabled = true));
    try {
      const token = this._hass.auth.data.access_token;
      const resp = await fetch("/api/kyber/knowledge/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ rating, knowledge_ids: knowledgeIds || [], auto: false }),
      });
      const data = await resp.json();
      if (status) {
        status.textContent = rating >= 4
          ? `✓ thanks — boosted ${data.count || 0} fact(s)`
          : `📝 flagged ${data.count || 0} fact(s) for review`;
        status.classList.add(rating >= 4 ? "ok" : "flag");
      }
      // Refresh the picked-knowledge list so stars/needs_review badges update
      setTimeout(() => this._renderDebugTab("last_turn"), 600);
    } catch (err) {
      if (status) status.textContent = `feedback failed: ${err.message}`;
    }
  }

  async _askAI() {
    const promptInput = this.shadowRoot.getElementById("prompt-input");
    const prompt = promptInput.value.trim();
    if (!prompt) return;

    // ── Slash commands ────────────────────────────────────────────
    const slashMatch = prompt.match(/^\/(\w+)(?:\s+(.*))?$/i);
    if (slashMatch) {
      const cmd = slashMatch[1].toLowerCase();
      const argStr = (slashMatch[2] || "").trim();
      if (cmd === "autopilot") {
        const arg = argStr.toLowerCase();
        promptInput.value = "";
        if (arg === "help") { this._showHelp("autopilot"); return; }
        if (arg === "on") {
          this._autopilot = true;
          this._updateAutopilotBadge();
          this._appendMessage("⚡ Autopilot is now ON — proposals will execute automatically.", "assistant");
        } else if (arg === "off") {
          this._autopilot = false;
          this._updateAutopilotBadge();
          this._appendMessage("Autopilot is now OFF — you'll review proposals before executing.", "assistant");
        } else {
          this._appendMessage(`Autopilot is currently ${this._autopilot ? "ON ⚡" : "OFF"}. Use /autopilot on or /autopilot off.`, "assistant");
        }
        return;
      }
      if (cmd === "reset") {
        promptInput.value = "";
        if (argStr.toLowerCase() === "help") { this._showHelp("reset"); return; }
        this._buildCommandCard({
          icon: "🗑",
          title: "Reset chat",
          detail: "This will clear all messages and start a fresh conversation.",
          danger: true,
          onConfirm: async () => {
            await this._clearHistory();
          },
        });
        return;
      }
      if (cmd === "help") {
        promptInput.value = "";
        this._showHelp(argStr.trim());
        return;
      }
      if (cmd === "knowledge" || cmd === "memory") {
        promptInput.value = "";
        await this._handleKnowledgeCommand(argStr.trim());
        return;
      }
      if (cmd === "session") {
        promptInput.value = "";
        if (argStr.toLowerCase() === "help") { this._showHelp("session"); return; }
        this._handleSessionCommand(argStr.trim());
        return;
      }
      if (["dashboard", "automation", "script", "blueprint", "area", "update"].includes(cmd)) {
        promptInput.value = "";
        this._handleSlashCommand(cmd, argStr);
        return;
      }
    }
    // ─────────────────────────────────────────────────────────────

    const yamlText = this._editor ? this._editor.state.doc.toString() : "";
    const askBtn = this.shadowRoot.getElementById("btn-ask");
    askBtn.disabled = true;
    promptInput.value = "";
    this._lastPrompt = prompt; // save for retry
    this._addChatHistory("user", prompt);

    this._appendMessage(prompt, "user");
    this._setStatus("Asking AI…");
    this._showThinking();
    const requestId = (crypto.randomUUID && crypto.randomUUID()) || (Date.now() + "-" + Math.random().toString(36).slice(2));

    // 90-second timeout — each narrator batch takes up to ~60s; cancel re-enables the button
    this._chatAbort = new AbortController();
    const _chatTimeoutId = setTimeout(() => {
      if (this._chatAbort) this._chatAbort.abort(new Error("Request timed out (90s). The AI narrator may be busy — try again in a moment."));
    }, 90_000);

    // chatDone is hoisted above try so the finally block can stop the progress poll
    let chatDone = false;

    try {
      const token = this._hass.auth.data.access_token;

      // Build dashboard list from hass.panels (always available, no API call needed)
      if (this._dashboardList === null) {
        const panels = this._hass.panels || {};
        this._dashboardList = Object.values(panels)
          .filter((p) => p.component_name === "lovelace" && p.url_path
            && p.url_path !== "kyber" && p.url_path !== "lovelace")
          .map((p) => ({
            title: p.title || p.url_path,
            url_path: p.url_path,
            mode: "storage",
          }));
      }

      // Fetch custom Lovelace resources (custom cards) once per session
      if (this._lovelaceResources === undefined) {
        this._lovelaceResources = [];
        try {
          const resResp = await fetch("/api/lovelace/resources", {
            headers: { Authorization: `Bearer ${token}` },
          });
          if (resResp.ok) {
            const resources = await resResp.json();
            // Extract custom card names from JS resource URLs
            // e.g. /hacsfiles/lovelace-mushroom/mushroom.js → mushroom cards
            this._lovelaceResources = (resources || [])
              .filter((r) => r.type === "module" && r.url)
              .map((r) => r.url);
          }
        } catch (_) { /* non-fatal */ }
      }

      const resp_promise = fetch("/api/kyber/complete", {
        method: "POST",
        signal: this._chatAbort.signal,
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          yaml: yamlText,
          prompt,
          editor_mode: this._editorMode,
          dashboards: this._dashboardList,
          lovelace_resources: this._lovelaceResources || [],
          request_id: requestId,
          // Send all prior messages (everything except the just-pushed current user msg),
          // capped at HISTORY_WINDOW most recent entries.
          history: this._chatHistory.slice(0, -1).slice(-this._HISTORY_WINDOW),
          compacted_summary: this._compactedSummary,
        }),
      });

      // Poll progress while the main request is in flight
      this._pollProgress(requestId, () => chatDone).catch((err) => {
        console.error("[kyber] poll progress crashed", err);
      });
      console.debug("[kyber] started progress polling for", requestId);

      const resp = await resp_promise;
      chatDone = true;

      if (!resp.ok) {
        const err = await resp.text();
        throw new Error(`${resp.status}: ${err}`);
      }

      const data = await resp.json();
      this._hideThinking();
      this._clearWarningBanner(); // dismiss any prior "AI unavailable" banner on success
      // Store the assistant's text reply in history
      const textOnly = data.response
        .replace(/```yaml[\s\S]*?```/gi, "")
        .replace(/```plan[\s\S]*?```/gi, "")
        .trim();
      if (textOnly) {
        this._addChatHistory("assistant", textOnly);
      }
      this._appendAIResponse(data.response, data.yaml_blocks || [], data.plan || null, data.learned_fact || null, data.clarify || null, data.knowledge_used || []);

      // Show "Onthouden" chips for newly saved search aliases
      if (data.aliases_saved && data.aliases_saved.length > 0) {
        const historyEl = this.shadowRoot.getElementById("chat-history");
        data.aliases_saved.forEach((alias) => {
          const chip = document.createElement("div");
          chip.className = "chat-alias-learned";
          chip.textContent = `💡 Onthouden: ${alias}`;
          historyEl.appendChild(chip);
        });
        historyEl.scrollTop = historyEl.scrollHeight;
      }

      // Render area assignment suggestions / reports
      if (data.area_suggestions && data.area_suggestions.length > 0) {
        for (const suggestion of data.area_suggestions) {
          this._renderAreaSuggestionChip(suggestion);
        }
      }

      // Per-turn metadata is captured for the Debug tab ("Last turn") instead
      // of being attached to the chat message. The chat panel stays clean;
      // all feedback / debug-bundle UI lives in /kyber-debug.
      this._lastTurnMeta = {
        request_id: data.request_id || null,
        knowledge_used: data.knowledge_used || [],
        auto_rating: data.auto_rating || null,
        ts: Date.now(),
      };
      // Update memory badge: pulse if knowledge was recalled; increment if new fact learned
      {
        const recalledCount = (data.knowledge_used || []).length;
        const newFactLearned = !!data.learned_fact;
        const newCount = newFactLearned ? (this._memoryCount || 0) + 1 : this._memoryCount;
        if (recalledCount > 0 || newFactLearned) {
          this._updateMemoryBadge(newCount, recalledCount);
        }
      }
      // Auto-refresh debug 'Last turn' pane if it is currently open
      const debugPane = this.shadowRoot.getElementById("debug-pane");
      if (debugPane && !debugPane.hasAttribute("hidden") && this._debugTab === "last_turn") {
        this._renderDebugTab("last_turn");
      }

      // Show tool call feedback pills above the response
      if (data.tool_log && data.tool_log.length > 0) {
        this._showToolLog(data.tool_log);
      }

      this._setStatus("Done");

      // Update context badge with live entity/automation counts
      if (data.context_stats) {
        this._updateContextBadge(data.context_stats);
      }

      // Compact overflow messages in the background
      this._maybeCompact();
    } catch (err) {
      this._hideThinking();
      let msg;
      if (err.name === "AbortError") {
        msg = err.message || "Request cancelled.";
      } else {
        // err.message is like "503: {"message":"AI provider error: ..."}"
        // Try to extract a clean human-readable message from the JSON body
        const rawMsg = err.message || "";
        const jsonStart = rawMsg.indexOf("{");
        let cleanMsg = rawMsg;
        if (jsonStart !== -1) {
          try {
            const parsed = JSON.parse(rawMsg.slice(jsonStart));
            const inner = (parsed.message || "").replace(/^AI provider error:\s*/i, "").replace(/^Internal error:\s*/i, "");
            if (inner) cleanMsg = inner.length > 250 ? inner.slice(0, 250) + "…" : inner;
          } catch { /* keep cleanMsg = rawMsg */ }
        }
        // Rate limit: show a friendly waiting message
        if (/429|rate.?limit|too.?many.?request|⏳/i.test(cleanMsg)) {
          msg = "⏳ Azure rate limit — too many requests. Please wait a moment and try again.";
        } else {
          msg = `Error: ${cleanMsg}`;
        }
      }
      // "AI Task entity not found" → show persistent banner instead of chat bubble
      if (/AI Task entity.*not found/i.test(msg) || (/503/.test(err.message || "") && /ai_task/i.test(err.message || ""))) {
        const entityId = ((err.message || "").match(/ai_task\.\S+/) || [])[0] || "the configured AI task entity";
        this._showWarningBanner(`⚠️ AI model unavailable — ${entityId} not found. Check your Ollama / AI Task integration.`);
      } else {
        this._appendMessage(msg, "error");
      }
      this._setStatus(msg, "error");
    } finally {
      chatDone = true; // always stop the progress poll, even on error/abort
      clearTimeout(_chatTimeoutId);
      this._chatAbort = null;
      askBtn.disabled = false;
    }
  }

  _showWarningBanner(message) {
    const banner = this.shadowRoot?.getElementById("warning-banner");
    const text = this.shadowRoot?.getElementById("warning-banner-text");
    if (!banner || !text) return;
    text.textContent = message;
    banner.style.display = "flex";
  }

  _clearWarningBanner() {
    const banner = this.shadowRoot?.getElementById("warning-banner");
    if (banner) banner.style.display = "none";
  }

  // Render text with **bold** words as inline clickable adornment buttons.
  // onChoiceClick receives the label text when a button is clicked.
  _domainIcon(domain) {
    const icons = {
      media_player: "📺", light: "💡", switch: "🔌", sensor: "📊",
      binary_sensor: "⬤", climate: "🌡️", cover: "🪟", script: "⚡",
      automation: "🤖", scene: "🎭", button: "🔘", input_boolean: "🔘",
      lock: "🔒", camera: "📷", fan: "🌀", vacuum: "🤖", person: "👤",
      weather: "🌤️", number: "🔢", select: "📋", remote: "🎮",
      alarm_control_panel: "🚨", input_select: "📋", input_number: "🔢",
      counter: "🔢", timer: "⏱️", zone: "📍", group: "👥",
    };
    return icons[domain] || "🔧";
  }

  _entityChip(entityId) {
    const state = this._hass?.states?.[entityId];
    const domain = entityId.split(".")[0];
    const icon = this._domainIcon(domain);
    if (!state) {
      const span = document.createElement("span");
      span.className = "entity-chip";
      span.title = entityId;
      span.innerHTML = `<span class="entity-chip-icon">${icon}</span><span class="entity-chip-name">${this._escapeHTML(entityId)}</span>`;
      return span;
    }
    const name = state.attributes?.friendly_name || entityId;
    const stateVal = state.state;
    const span = document.createElement("span");
    span.className = "entity-chip";
    span.title = entityId;
    span.innerHTML = `<span class="entity-chip-icon">${icon}</span><span class="entity-chip-name">${this._escapeHTML(name)}</span><span class="entity-chip-state">${this._escapeHTML(stateVal)}</span>`;
    return span;
  }

  _injectEntityChips(container) {
    // Walk text nodes in the container and replace backtick entity IDs with chips
    const ENTITY_ID_RE = /`([a-z_]+\.[a-z0-9_]+)`/g;
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
    const replacements = [];
    let node;
    while ((node = walker.nextNode())) {
      if (!ENTITY_ID_RE.test(node.textContent)) continue;
      ENTITY_ID_RE.lastIndex = 0;
      replacements.push(node);
    }
    replacements.forEach((textNode) => {
      const frag = document.createDocumentFragment();
      let last = 0;
      const text = textNode.textContent;
      ENTITY_ID_RE.lastIndex = 0;
      let m;
      while ((m = ENTITY_ID_RE.exec(text)) !== null) {
        if (m.index > last) frag.appendChild(document.createTextNode(text.slice(last, m.index)));
        frag.appendChild(this._entityChip(m[1]));
        last = m.index + m[0].length;
      }
      if (last < text.length) frag.appendChild(document.createTextNode(text.slice(last)));
      textNode.parentNode.replaceChild(frag, textNode);
    });
  }

  _buildEntityResultGrid(previewJson) {
    try {
      const data = JSON.parse(previewJson);
      if (!data || typeof data !== "object" || data.error || data.info) return null;
      const entries = Object.entries(data);
      if (!entries.length) return null;
      const grid = document.createElement("div");
      grid.className = "entity-result-grid";
      entries.forEach(([entityId, info]) => {
        const domain = entityId.split(".")[0];
        const icon = this._domainIcon(domain);
        const liveState = this._hass?.states?.[entityId];
        const name = liveState?.attributes?.friendly_name || info.name || entityId.split(".")[1];
        const stateVal = liveState?.state || info.state || "";
        const card = document.createElement("div");
        card.className = "entity-result-card";
        card.innerHTML = `<div class="erc-icon">${icon}</div><div class="erc-body"><div class="erc-name">${this._escapeHTML(name)}</div><div class="erc-id">${this._escapeHTML(entityId)}</div>${stateVal ? `<div class="erc-state">${this._escapeHTML(stateVal)}</div>` : ""}</div>`;
        grid.appendChild(card);
      });
      return grid;
    } catch {
      return null;
    }
  }

  _renderTextWithAdornments(text, onChoiceClick) {
    const frag = document.createDocumentFragment();
    // Split on **bold** markers, keeping delimiters
    const parts = text.split(/(\*\*[^*\n]+\*\*)/g);
    parts.forEach((part) => {
      const boldMatch = part.match(/^\*\*([^*]+)\*\*$/);
      if (boldMatch) {
        const btn = document.createElement("button");
        btn.className = "inline-choice";
        btn.textContent = boldMatch[1];
        btn.addEventListener("click", () => {
          // Mark all sibling inline-choices as used so only one fires per message
          const msg = btn.closest(".chat-message");
          if (msg) msg.querySelectorAll(".inline-choice").forEach((b) => b.classList.add("used"));
          onChoiceClick(boldMatch[1]);
        });
        frag.appendChild(btn);
      } else {
        frag.appendChild(document.createTextNode(part));
      }
    });
    return frag;
  }

  _extractSuggestions(text) {
    const chips = [];

    // Strategy 1: **bold** action words from bullet list items
    const bulletLines = text.match(/^[\-\*•]\s+.+$/gm) || [];
    if (bulletLines.length >= 2) {
      bulletLines.forEach((line) => {
        const boldMatch = line.match(/\*\*([^*]{1,30})\*\*/);
        if (boldMatch) {
          const label = boldMatch[1].charAt(0).toUpperCase() + boldMatch[1].slice(1);
          if (!chips.includes(label)) chips.push(label);
        }
      });
      if (chips.length >= 2) return chips.slice(0, 12);

      // No bold — use the full bullet text (works for entity IDs and names)
      chips.length = 0;
      // Domain words → HA domain prefixes for entity ID reconstruction
      const _DOMAIN_MAP = {
        switch: "switch", light: "light", sensor: "sensor",
        binary_sensor: "binary_sensor", cover: "cover",
        media_player: "media_player", climate: "climate",
        input_boolean: "input_boolean", scene: "scene",
        script: "script", automation: "automation",
        number: "number", select: "select", button: "button",
      };
      bulletLines.forEach((line) => {
        const stripped = line.replace(/^[\-\*•]\s+/, "");
        // Detect leading domain word (e.g. "Switch: entity_name") before stripping
        const domainMatch = stripped.match(/^(switch|light|sensor|binary[_ ]sensor|cover|media[_ ]player|climate|input[_ ]boolean|scene|script|automation|number|select|button):\s*/i);
        const domainPrefix = domainMatch
          ? (_DOMAIN_MAP[domainMatch[1].toLowerCase().replace(/[\s-]/g, "_")] || "") + "."
          : "";
        const cleaned = stripped
          .replace(/^(or |and |also )?(do you want to |would you prefer to |would you like to |please |i can )/i, "")
          .replace(/\?.*$/, "")
          // Strip "(state: ...)" suffix and similar parenthetical status notes
          .replace(/\s*\(state:[^)]*\)/gi, "")
          .replace(/\s*\([^)]{0,30}\)\s*$/, "")
          // Strip leading domain word — keep entity name only
          .replace(/^(switch|light|sensor|binary.sensor|cover|media.player|climate|input.boolean|scene|script|automation|number|select|button):\s*/i, "")
          .trim();
        // Reconstruct full entity ID when possible (e.g. switch.onoff_keuken_espresso_304)
        const chipValue = (domainPrefix && /^[a-z0-9_]+$/.test(cleaned))
          ? domainPrefix + cleaned
          : cleaned;
        // Skip junk items: only "...", single chars, or empty
        if (chipValue.length > 2 && chipValue !== "..." && chipValue.length < 80 && !chips.includes(chipValue)) chips.push(chipValue);
      });
      if (chips.length >= 2) return chips.slice(0, 12);
      chips.length = 0;
    }

    // Strategy 2: Yes/No binary confirm
    if (/\b(yes|no)\b/i.test(text) && /confirm|proceed|sure/i.test(text)) {
      return ["Yes", "No"];
    }

    // Strategy 3: Quoted strings, strip (e.g., ...) first
    const strippedText = text
      .replace(/\(e\.g\.[^)]*\)/gi, "")
      .replace(/for example[^.,]*/gi, "")
      .replace(/such as[^.,]*/gi, "");
    const allQuoted = [...strippedText.matchAll(/"([^"]{1,40})"/g)].map((m) => m[1]);
    if (allQuoted.length >= 2) {
      allQuoted.forEach((v) => { if (!chips.includes(v)) chips.push(v); });
      return chips.slice(0, 12);
    }

    return chips;
  }

  _appendMessage(text, type) {
    const history = this.shadowRoot.getElementById("chat-history");
    const wrap = document.createElement("div");
    wrap.className = `chat-message-wrap ${type}`;

    const msg = document.createElement("div");
    msg.className = `chat-message ${type}`;
    msg.textContent = text;
    wrap.appendChild(msg);

    // Copy button for user and assistant messages
    if (type === "user" || type === "assistant") {
      const copyBtn = document.createElement("button");
      copyBtn.className = "chat-copy-btn";
      copyBtn.title = this._t ? this._t("copy_title") : "Copy";
      copyBtn.textContent = "📋";
      copyBtn.addEventListener("click", () => {
        const t = this._t || ((k) => k);
        const doCopy = navigator.clipboard?.writeText
          ? navigator.clipboard.writeText(text)
          : new Promise((resolve, reject) => {
              try {
                const ta = document.createElement("textarea");
                ta.value = text;
                ta.style.cssText = "position:fixed;top:-9999px;left:-9999px;opacity:0";
                document.body.appendChild(ta);
                ta.focus(); ta.select();
                document.execCommand("copy");
                document.body.removeChild(ta);
                resolve();
              } catch (e) { reject(e); }
            });
        doCopy.then(() => {
          copyBtn.textContent = t("copy_done");
          setTimeout(() => (copyBtn.textContent = "📋"), 1500);
        }).catch(() => {
          copyBtn.title = t("copy_failed_title");
          copyBtn.textContent = t("copy_fail");
          setTimeout(() => { copyBtn.textContent = "📋"; copyBtn.title = t("copy_title"); }, 2000);
        });
      });
      wrap.appendChild(copyBtn);
    }

    // Retry button on error messages
    if (type === "error" && this._lastPrompt) {
      const retryBtn = document.createElement("button");
      retryBtn.className = "chat-retry-btn";
      retryBtn.textContent = "↺ Retry";
      const savedPrompt = this._lastPrompt;
      retryBtn.addEventListener("click", () => {
        wrap.remove();
        const input = this.shadowRoot.getElementById("prompt-input");
        if (input) input.value = savedPrompt;
        this._askAI();
      });
      wrap.appendChild(retryBtn);
    }

    history.appendChild(wrap);
    history.scrollTop = history.scrollHeight;
  }

  _appendAIResponse(fullText, yamlBlocks, plan, learnedFact = null, clarify = null, knowledgeIds = []) {
    const history = this.shadowRoot.getElementById("chat-history");

    // Render clarify block: question + option buttons.
    // Shown INSTEAD of (or before) prose when the AI emits a clarify block.
    if (clarify && clarify.question) {
      const clarifyCard = document.createElement("div");
      clarifyCard.className = "chat-message assistant clarify-card";

      if (clarify.context) {
        const ctx = document.createElement("p");
        ctx.className = "clarify-context";
        ctx.textContent = clarify.context;
        clarifyCard.appendChild(ctx);
      }

      const q = document.createElement("p");
      q.className = "clarify-question";
      q.textContent = clarify.question;
      clarifyCard.appendChild(q);

      if (Array.isArray(clarify.options) && clarify.options.length > 0) {
        const chipRow = document.createElement("div");
        chipRow.className = "suggestion-chips";
        clarify.options.forEach((label) => {
          const btn = document.createElement("button");
          btn.className = "suggestion-chip";
          btn.textContent = label;
          btn.addEventListener("click", () => {
            const input = this.shadowRoot.getElementById("prompt-input");
            if (input) input.value = label;
            clarifyCard.remove();
            this._askAI();
          });
          chipRow.appendChild(btn);
        });
        clarifyCard.appendChild(chipRow);
      }

      history.appendChild(clarifyCard);
      history.scrollTop = history.scrollHeight;
      return; // clarify card replaces the normal prose rendering
    }

    // Show the text portion (strip yaml/plan blocks for cleaner display)
    const textOnly = fullText
      .replace(/```yaml[\s\S]*?```/gi, "")
      .replace(/```plan[\s\S]*?```/gi, "")
      .replace(/^#{1,3}\s*[Pp]lan\s*\n\{[\s\S]*?\n\}\s*/gm, "") // strip bare ## Plan {...} blocks
      // Strip leaked tool result markers the model sometimes echoes back
      .replace(/<<\/?TOOL_RESULT>>?/g, "")
      .replace(/\bUser:\s*$/gm, "")
      .trim();
    if (textOnly) {
      const msg = document.createElement("div");
      msg.className = "chat-message assistant";

      const hasBold = /\*\*[^*\n]+\*\*/.test(textOnly);
      const isQuestion = /\?/.test(textOnly);
      // Show chips when AI is presenting a choice — English and Dutch patterns
      const isChoiceContext = /\b(choose|pick|select|which (?:one|option)|what would you (?:like|prefer)|do you want|I can:?|options?:|confirm|proceed|sure)\b/i.test(textOnly)
        || /\b(welk|welke|welke van|which of|meerdere|multiple|disambig)\b/i.test(textOnly);

      if (hasBold) {
        // Render **bold** words as inline adornment buttons
        const onChoiceClick = (label) => {
          const input = this.shadowRoot.getElementById("prompt-input");
          if (input) input.value = label;
          this._askAI();
        };
        msg.appendChild(this._renderTextWithAdornments(textOnly, onChoiceClick));
      } else {
        msg.textContent = textOnly;
      }

      // Replace backtick entity IDs (e.g. `media_player.tv`) with rich entity chips
      this._injectEntityChips(msg);

      history.appendChild(msg);

      // Action row: copy + thumbs up/down
      const actionRow = document.createElement("div");
      actionRow.className = "chat-feedback-row";

      // Copy button
      const aiCopyBtn = document.createElement("button");
      aiCopyBtn.className = "tf-btn-rate chat-copy-btn";
      aiCopyBtn.title = "Copy";
      aiCopyBtn.textContent = "📋";
      aiCopyBtn.addEventListener("click", () => {
        const t2 = this._t || ((k) => k);
        const doCopy2 = navigator.clipboard?.writeText
          ? navigator.clipboard.writeText(textOnly)
          : new Promise((resolve, reject) => {
              try {
                const ta = document.createElement("textarea");
                ta.value = textOnly;
                ta.style.cssText = "position:fixed;top:-9999px;left:-9999px;opacity:0";
                document.body.appendChild(ta);
                ta.focus(); ta.select();
                document.execCommand("copy");
                document.body.removeChild(ta);
                resolve();
              } catch (e) { reject(e); }
            });
        doCopy2.then(() => {
          aiCopyBtn.textContent = t2("copy_done");
          setTimeout(() => (aiCopyBtn.textContent = "📋"), 1500);
        }).catch(() => {
          aiCopyBtn.title = t2("copy_failed_title");
          aiCopyBtn.textContent = t2("copy_fail");
          setTimeout(() => { aiCopyBtn.textContent = "📋"; aiCopyBtn.title = t2("copy_title"); }, 2000);
        });
      });
      actionRow.appendChild(aiCopyBtn);

      // Thumbs up/down
      if (knowledgeIds !== undefined) {
        const upBtn = document.createElement("button");
        upBtn.className = "tf-btn-rate tf-chat-up";
        upBtn.title = "Helpful";
        upBtn.textContent = "👍";
        const downBtn = document.createElement("button");
        downBtn.className = "tf-btn-rate tf-chat-down";
        downBtn.title = "Not helpful";
        downBtn.textContent = "👎";
        const statusSpan = document.createElement("span");
        statusSpan.className = "tf-status";
        upBtn.addEventListener("click", () => this._submitTurnFeedback(5, knowledgeIds, actionRow));
        downBtn.addEventListener("click", () => this._submitTurnFeedback(1, knowledgeIds, actionRow));
        actionRow.appendChild(upBtn);
        actionRow.appendChild(downBtn);
        actionRow.appendChild(statusSpan);
      }

      history.appendChild(actionRow);

      // Fallback chips for non-bold question responses (e.g. Yes/No or entity disambiguation).
      // Only shown when the AI is explicitly asking the user to pick an option.
      if (isQuestion && isChoiceContext && !hasBold && !plan) {
        const chips = this._extractSuggestions(textOnly);
        if (chips.length >= 2) {
          const VISIBLE = 6;
          const chipRow = document.createElement("div");
          chipRow.className = "suggestion-chips";

          const makeChip = (label) => {
            const btn = document.createElement("button");
            btn.className = "suggestion-chip";
            btn.textContent = label;
            btn.addEventListener("click", () => {
              const input = this.shadowRoot.getElementById("prompt-input");
              if (input) input.value = label;
              chipRow.remove();
              this._askAI();
            });
            return btn;
          };

          chips.slice(0, VISIBLE).forEach((label) => chipRow.appendChild(makeChip(label)));

          if (chips.length > VISIBLE) {
            const moreBtn = document.createElement("button");
            moreBtn.className = "suggestion-chip chip-more";
            moreBtn.textContent = `+${chips.length - VISIBLE} meer`;
            moreBtn.addEventListener("click", () => {
              moreBtn.remove();
              chips.slice(VISIBLE).forEach((label) => chipRow.appendChild(makeChip(label)));
            });
            chipRow.appendChild(moreBtn);
          }

          history.appendChild(chipRow);
        }
      }
    }

    // Handle plan blocks
    if (plan) {
      if (plan.open_dashboard) {
        const card = this._buildOpenDashboardPrompt(plan);
        history.appendChild(card);
        if (this._autopilot) {
          setTimeout(() => card.querySelector(".btn-open-editor")?.click(), 300);
        }
      } else if (plan.open_editor) {
        const card = this._buildOpenEditorPrompt(plan);
        history.appendChild(card);
        if (this._autopilot) {
          setTimeout(() => card.querySelector(".btn-open-editor")?.click(), 300);
        }
      } else if (plan.actions && plan.actions.length > 0) {
        const READ_TOOL_TYPES = new Set([
          "list_entities_by_domain", "get_entity_state", "get_area_entities",
          "list_entities_by_label", "search_entities", "get_areas", "get_labels",
        ]);
        const allToolCalls = plan.actions.every((a) => READ_TOOL_TYPES.has(a.type));
        if (allToolCalls) {
          // Auto-execute read-only tool calls without showing proposal card
          this._autoExecuteToolPlan(plan, promptInput);
        } else {
          history.appendChild(this._buildPlanCard(plan));
        }
      }
    }

    // Show memory suggestion card if the backend extracted a learned fact
    if (learnedFact) {
      history.appendChild(this._buildMemoryCard(learnedFact));
    }

    // Show each YAML block with an Apply button (when editor is open)
    yamlBlocks.forEach((block) => {
      const container = document.createElement("div");
      container.className = "yaml-suggestion";
      const label = this._editorMode === "dashboard" ? "⬆ Apply to dashboard" : "⬆ Apply to editor";
      container.innerHTML = `
        <pre>${this._escapeHtml(block)}</pre>
        <button>${label}</button>
      `;
      const applyBtn = container.querySelector("button");
      applyBtn.addEventListener("click", () => {
        this._setEditorContent(block);
        applyBtn.disabled = true;
        applyBtn.textContent = "✓ Applied";
        this._setStatus(this._editorMode === "dashboard"
          ? "Dashboard YAML applied — review and Save when ready."
          : "Suggestion applied — review and save when ready.");
      });
      history.appendChild(container);
      // Autopilot: auto-apply YAML when editor is already open
      if (this._autopilot && this.shadowRoot.getElementById("editor-container")?.classList.contains("open")) {
        setTimeout(() => applyBtn.click(), 300);
      }
    });

    history.scrollTop = history.scrollHeight;
  }

  _buildOpenDashboardPrompt(plan) {
    const card = document.createElement("div");
    card.className = "open-editor-prompt";
    const targetLabel = plan.url_path ? ` (${plan.url_path})` : "";
    card.innerHTML = `
      <div class="open-editor-summary">${this._escapeHtml(plan.summary || "Edit dashboard")}</div>
      <button class="btn-open-editor">📊 Open dashboard editor${this._escapeHtml(targetLabel)}</button>
    `;
    card.querySelector(".btn-open-editor").addEventListener("click", () => {
      this._openDashboard(plan.url_path || null);
      const btn = card.querySelector(".btn-open-editor");
      btn.disabled = true;
      btn.textContent = "✓ Dashboard editor opened";
    });
    return card;
  }

  _buildOpenEditorPrompt(plan) {
    const card = document.createElement("div");
    card.className = "open-editor-prompt";

    card.innerHTML = `
      <div class="open-editor-summary">${this._escapeHtml(plan.summary || "Edit automation")}</div>
      <button class="btn-open-editor">📝 Open YAML editor</button>
    `;

    card.querySelector(".btn-open-editor").addEventListener("click", () => {
      this._openEditor(plan.automation_id);
      const btn = card.querySelector(".btn-open-editor");
      btn.disabled = true;
      btn.textContent = "✓ Editor opened";
    });

    return card;
  }

  /** Auto-execute read-only tool calls (no user approval needed) and display results. */
  async _autoExecuteToolPlan(plan, _originalPrompt) {
    const history = this.shadowRoot?.getElementById("chat-history");
    if (!history) return;

    const spinner = document.createElement("div");
    spinner.className = "chat-message assistant";
    spinner.textContent = `🔍 Fetching data…`;
    history.appendChild(spinner);
    history.scrollTop = history.scrollHeight;

    try {
      const token = this._hass.auth.data.access_token;
      const resp = await fetch("/api/kyber/execute", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ actions: plan.actions }),
      });
      const data = await resp.json();
      const results = data.results || [];
      spinner.remove();

      // Display the tool results as formatted assistant messages
      const ENTITY_TOOL_TYPES = new Set([
        "search_entities", "list_entities_by_domain", "get_area_entities",
        "list_entities_by_label", "get_integration_entities", "list_entities_without_area",
      ]);
      results.forEach((r) => {
        const msg = document.createElement("div");
        msg.className = "chat-message assistant";
        const toolData = r.tool_result || r;
        // Render entity tools as a visual grid instead of raw JSON
        if (ENTITY_TOOL_TYPES.has(r.type)) {
          const grid = this._buildEntityResultGrid(JSON.stringify(toolData));
          if (grid) {
            const label = document.createElement("div");
            label.style.cssText = "font-size:11px;opacity:0.55;margin-bottom:4px;";
            label.textContent = `📋 ${r.type}`;
            msg.appendChild(label);
            msg.appendChild(grid);
            history.appendChild(msg);
            return;
          }
        }
        const formatted = JSON.stringify(toolData, null, 2);
        msg.textContent = `📋 ${r.type}:\n${formatted}`;
        history.appendChild(msg);
      });
      history.scrollTop = history.scrollHeight;
    } catch (err) {
      spinner.textContent = `⚠ Tool fetch failed: ${err.message}`;
    }
  }

  _showThinking() {
    const history = this.shadowRoot?.getElementById("chat-history");
    if (!history) return;
    this._hideThinking(); // ensure no duplicate
    const bubble = document.createElement("div");
    bubble.id = "kyber-thinking-bubble";
    bubble.className = "chat-message assistant";
    bubble.innerHTML = `
      <div class="thinking-bubble">
        <div class="thinking-header">
          <div class="thinking-dots">
            <span></span><span></span><span></span>
          </div>
          <span class="thinking-label">${this._t ? this._t("thinking") : "Thinking…"}</span>
          <button class="thinking-cancel" id="kyber-thinking-cancel" title="Cancel request">✕ Cancel</button>
        </div>
        <div class="thinking-events" id="kyber-thinking-events"></div>
      </div>
    `;
    history.appendChild(bubble);
    history.scrollTop = history.scrollHeight;
    const cancelBtn = bubble.querySelector("#kyber-thinking-cancel");
    if (cancelBtn) {
      cancelBtn.addEventListener("click", () => {
        if (this._chatAbort) {
          this._chatAbort.abort();
          this._chatAbort = null;
        }
      });
    }
  }

  _setThinkingLabel(label) {
    const el = this.shadowRoot?.querySelector("#kyber-thinking-bubble .thinking-label");
    if (el) el.textContent = label;
  }

  /**
   * Append a thinking event item to the thinking bubble.
   * @param {string} cssClass  - span CSS class (e.g. "thinking-info")
   * @param {string} text      - PLAIN TEXT — will be set via textContent (safe)
   * @param {string} [prefix]  - optional emoji/prefix prepended as text
   */
  _appendThinkingEvent(cssClass, text, prefix = "") {
    const events = this.shadowRoot?.getElementById("kyber-thinking-events");
    if (!events) return;
    const item = document.createElement("div");
    item.className = "thinking-event";
    const span = document.createElement("span");
    span.className = cssClass;
    span.textContent = (prefix ? prefix + " " : "") + text;
    item.appendChild(span);
    events.appendChild(item);
    const history = this.shadowRoot?.getElementById("chat-history");
    if (history) history.scrollTop = history.scrollHeight;
  }

  /**
   * Append a multi-element thinking event (tool calls).
   * All content MUST be pre-escaped with _escapeHTML before calling this.
   * @param {string} trustedHtml - HTML where all user data is already escaped
   */
  _appendThinkingEventHTML(trustedHtml) {
    const events = this.shadowRoot?.getElementById("kyber-thinking-events");
    if (!events) return;
    const item = document.createElement("div");
    item.className = "thinking-event";
    item.innerHTML = trustedHtml;
    events.appendChild(item);
    const history = this.shadowRoot?.getElementById("chat-history");
    if (history) history.scrollTop = history.scrollHeight;
  }

  _renderProgressEvent(ev) {
    if (!ev || !ev.type) return;
    if (ev.type === "info") {
      this._appendThinkingEvent("thinking-info", ev.message || "", "ℹ️");
    } else if (ev.type === "tool_call") {
      const args = ev.args ? Object.entries(ev.args).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ") : "";
      this._setThinkingLabel("Calling tool…");
      this._appendThinkingEventHTML(
        `<span class="thinking-tool-name">🔧 ${this._escapeHTML(ev.name || "?")}</span>` +
        (args ? `<span class="thinking-tool-args"> (${this._escapeHTML(args)})</span>` : "") +
        `<span class="thinking-tool-status thinking-tool-running"> …</span>`
      );
    } else if (ev.type === "tool_result") {
      // Update the most recent matching tool_call event in-place
      const events = this.shadowRoot?.getElementById("kyber-thinking-events");
      if (events) {
        const items = events.querySelectorAll(".thinking-event");
        for (let i = items.length - 1; i >= 0; i--) {
          const nameEl = items[i].querySelector(".thinking-tool-name");
          const statusEl = items[i].querySelector(".thinking-tool-status");
          if (nameEl && statusEl && nameEl.textContent.includes(ev.name) &&
              statusEl.classList.contains("thinking-tool-running")) {
            statusEl.classList.remove("thinking-tool-running");
            statusEl.classList.add("thinking-tool-done");
            statusEl.textContent = ` → ${ev.summary || "done"}`;
            if (ev.preview) {
              items[i].dataset.preview = ev.preview;
              items[i].dataset.toolName = ev.name || "";
              items[i].style.cursor = "pointer";
              items[i].title = "Click to view results";
              items[i].addEventListener("click", () => {
                let existing = items[i].querySelector(".thinking-tool-preview, .entity-result-grid");
                if (existing) { existing.remove(); return; }
                // For entity search tools, show rich entity grid
                const isEntityTool = ["search_entities", "list_entities_by_domain",
                  "get_area_entities", "list_entities_by_label", "get_integration_entities",
                  "list_entities_without_area"].includes(items[i].dataset.toolName);
                if (isEntityTool) {
                  const grid = this._buildEntityResultGrid(items[i].dataset.preview);
                  if (grid) { items[i].appendChild(grid); return; }
                }
                const pre = document.createElement("pre");
                pre.className = "thinking-tool-preview";
                pre.textContent = items[i].dataset.preview;
                items[i].appendChild(pre);
              });
            }
            break;
          }
        }
      }
      this._setThinkingLabel("Thinking…");
    } else if (ev.type === "thinking") {
      this._setThinkingLabel(ev.stage === "follow_up" ? "Reasoning over results…" : "Thinking…");
    } else if (ev.type === "warning") {
      this._appendThinkingEvent("thinking-warning", ev.message || "", "⚠️");
    } else if (ev.type === "error") {
      this._appendThinkingEvent("thinking-error", ev.message || "error", "⚠️");
    }
  }

  async _pollProgress(requestId, isDone) {
    let cursor = 0;
    let polls = 0;
    let consecutiveFails = 0;
    while (!isDone()) {
      try {
        const token = this._hass.auth.data.access_token;
        const r = await fetch(`/api/kyber/progress?id=${encodeURIComponent(requestId)}&since=${cursor}`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (r.ok) {
          consecutiveFails = 0;
          const data = await r.json();
          polls += 1;
          if (data.events && data.events.length) {
            console.debug("[kyber] progress", data.events.length, "new events, status:", data.status);
          }
          for (const ev of (data.events || [])) {
            try { this._renderProgressEvent(ev); }
            catch (err) { console.error("[kyber] render progress event failed", err, ev); }
          }
          cursor = data.next || cursor;
          if (data.status === "done") return;
        } else if (r.status === 401) {
          // Token expired or request was cleaned up — stop polling, main fetch handles auth
          console.warn("[kyber] progress poll stopped: 401 unauthorized");
          return;
        } else {
          consecutiveFails += 1;
          console.warn("[kyber] progress fetch HTTP", r.status);
          if (consecutiveFails >= 5) {
            console.warn("[kyber] progress poll stopped after", consecutiveFails, "consecutive failures");
            return;
          }
        }
      } catch (err) {
        consecutiveFails += 1;
        console.warn("[kyber] progress poll error", err);
        if (consecutiveFails >= 5) return;
      }
      await new Promise((res) => setTimeout(res, 200));
    }
    console.debug("[kyber] progress polling stopped after", polls, "polls");
  }

  /** Start a single polling loop for all Kyber status UI (explorer banner + narrator badge). */
  _startStatusPolling() {
    this._clearStatusPoll();
    this._statusPollFailures = 0;
    this._checkKyberStatus();
    this._statusPollInterval = setInterval(() => this._checkKyberStatus(), 5000);
  }

  _clearStatusPoll() {
    if (this._statusPollInterval) { clearInterval(this._statusPollInterval); this._statusPollInterval = null; }
    if (this._statusPollTimeout) { clearTimeout(this._statusPollTimeout); this._statusPollTimeout = null; }
  }

  _statusBackoff(ms) {
    this._clearStatusPoll();
    this._statusPollTimeout = setTimeout(() => {
      this._statusPollTimeout = null;
      this._statusPollFailures = 0;
      this._startStatusPolling();
    }, ms);
  }

  async _checkKyberStatus() {
    const token = this._hass?.auth?.data?.access_token;
    if (!token) return;
    let data;
    try {
      const resp = await fetch("/api/kyber/debug/status", { headers: { Authorization: `Bearer ${token}` } });
      if (!resp.ok) {
        if (resp.status === 404) this._statusBackoff(30_000); // Kyber not loaded yet
        return;
      }
      this._statusPollFailures = 0;
      data = await resp.json();
    } catch (_) {
      // ERR_CONNECTION_REFUSED → HA offline; back off after 3 failures
      this._statusPollFailures = (this._statusPollFailures || 0) + 1;
      if (this._statusPollFailures >= 3) this._statusBackoff(30_000);
      return;
    }

    const ep = data.explorer_progress || {};
    const epStatus = ep.status || "idle";
    const active = ["starting", "phase1_summaries", "phase2_entities", "narrator"].includes(epStatus);

    // Update explorer banner in chat area
    const banner = this.shadowRoot?.getElementById("explorer-banner");
    const textEl = this.shadowRoot?.getElementById("explorer-banner-text");
    if (banner) {
      if (active) {
        let bannerText;
        if (epStatus === "narrator") {
          const done = ep.narrator_done ?? 0, total = ep.narrator_total ?? 0;
          const pct = total > 0 ? Math.round(done * 100 / total) : 0;
          bannerText = `Narry is exploring your home${total > 0 ? ` ${pct}%` : ""}`;
        } else {
          const done = ep.done ?? 0, total = ep.total ?? 0;
          bannerText = `Exploring your home${total > 0 ? ` (${done} / ${total})` : ""}…`;
        }
        if (textEl) textEl.textContent = bannerText;
        banner.style.display = "";
      } else {
        banner.style.display = "none";
      }
    }

    // Update narrator progress badge in header
    const badge = this.shadowRoot?.getElementById("narrator-progress");
    if (badge) {
      if (epStatus === "narrator") {
        const done = ep.narrator_done ?? 0, total = ep.narrator_total ?? 0;
        const pct = total > 0 ? Math.round(done * 100 / total) : 0;
        badge.textContent = `🔍 ${pct}%`;
        badge.hidden = false;
        badge.title = `Narry is exploring your home: ${done} of ${total} entities (${pct}%)`;
      } else if (active) {
        const done = ep.done ?? 0, total = ep.total ?? 0;
        badge.textContent = `🔍 ${done}/${total}`;
        badge.hidden = false;
        badge.title = `Entity explorer: indexing ${done} of ${total}`;
      } else {
        badge.hidden = true;
      }
    }

    // Self-stop when nothing is running
    if (!active) this._clearStatusPoll();
  }

  _hideThinking() {
    this.shadowRoot?.getElementById("kyber-thinking-bubble")?.remove();
  }

  _renderAreaSuggestionChip(suggestion) {
    const history = this.shadowRoot?.getElementById("chat-history");
    if (!history) return;

    const chip = document.createElement("div");
    chip.className = "kyber-area-suggestion-chip";
    chip.dataset.suggestionId = suggestion.id;

    const name = this._escapeHtml(suggestion.friendly_name || suggestion.entity_id);
    const area = this._escapeHtml(suggestion.suggested_area_name);

    if (suggestion.applied) {
      chip.innerHTML = `
        <span class="area-chip-icon">🏠</span>
        <span class="area-chip-text">Assigned <strong>${name}</strong> to <strong>${area}</strong></span>
        <button class="kyber-area-undo-btn">↩ Undo</button>
      `;
      chip.querySelector(".kyber-area-undo-btn").addEventListener("click", async (evt) => {
        evt.stopPropagation();
        const btn = chip.querySelector(".kyber-area-undo-btn");
        btn.disabled = true; btn.textContent = "…";
        try {
          await this._hass.callApi("POST", "kyber/execute", {
            actions: [{ type: "assign_area", entity_id: suggestion.entity_id, area_id: suggestion.undo_area_id || "" }],
            approved: true,
          });
          await this._hass.callApi("POST", "kyber/area_suggestions/dismiss", { id: suggestion.id });
          chip.innerHTML = `<span class="area-chip-icon">↩</span><span class="area-chip-text">Moved <strong>${name}</strong> back</span>`;
          chip.classList.add("area-chip-done");
        } catch (err) {
          btn.textContent = "⚠ Error"; btn.disabled = false;
        }
      });
    } else {
      chip.innerHTML = `
        <span class="area-chip-icon">🏠</span>
        <span class="area-chip-text"><strong>${name}</strong> has no area — assign to <strong>${area}</strong>?</span>
        <button class="kyber-area-apply-btn">✓ Assign</button>
        <button class="kyber-area-dismiss-btn">✕</button>
      `;
      chip.querySelector(".kyber-area-apply-btn").addEventListener("click", async (evt) => {
        evt.stopPropagation();
        const btn = chip.querySelector(".kyber-area-apply-btn");
        btn.disabled = true; btn.textContent = "…";
        try {
          await this._hass.callApi("POST", "kyber/execute", {
            actions: [{ type: "assign_area", entity_id: suggestion.entity_id, area_id: suggestion.suggested_area_id }],
            approved: true,
          });
          await this._hass.callApi("POST", "kyber/area_suggestions/dismiss", { id: suggestion.id });
          chip.innerHTML = `<span class="area-chip-icon">✓</span><span class="area-chip-text"><strong>${name}</strong> assigned to <strong>${area}</strong></span>`;
          chip.classList.add("area-chip-done");
        } catch (err) {
          btn.textContent = "⚠ Error"; btn.disabled = false;
        }
      });
      chip.querySelector(".kyber-area-dismiss-btn").addEventListener("click", async (evt) => {
        evt.stopPropagation();
        try {
          await this._hass.callApi("POST", "kyber/area_suggestions/dismiss", { id: suggestion.id });
        } catch (_) { /* non-critical */ }
        chip.remove();
      });
    }

    history.appendChild(chip);
    history.scrollTop = history.scrollHeight;
  }
};
