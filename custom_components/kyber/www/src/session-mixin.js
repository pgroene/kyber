export const SessionMixin = (Base) => class extends Base {
  _sanitizeHistoryForPersistence(messages) {
    if (!Array.isArray(messages)) return [];
    return messages
      .map((msg) => ({
        role: msg?.role === "user" ? "user" : "assistant",
        content: String(msg?.content || "").trim(),
      }))
      .filter((msg) => msg.content.length > 0)
      .slice(-200);
  }

  _resetChatView() {
    const history = this.shadowRoot.getElementById("chat-history");
    if (!history) return;
    history.innerHTML = `<div class="chat-message assistant">${this._escapeHtml(this._DEFAULT_GREETING)}</div>`;
  }

  _addChatHistory(role, content) {
    const text = String(content || "").trim();
    if (!text) return;
    this._chatHistory.push({ role: role === "user" ? "user" : "assistant", content: text });
    this._persistHistory();
    // Auto-generate session title every 5 messages
    if (this._chatHistory.length % 5 === 0) {
      this._autoNameSession();
    }
  }

  async _persistHistory() {
    if (!this._hass) return;
    try {
      await this._hass.callApi("POST", "kyber/history", {
        history: this._sanitizeHistoryForPersistence(this._chatHistory),
        compacted_summary: String(this._compactedSummary || "").trim(),
      });
    } catch (err) {
      console.warn("[Kyber] _persistHistory error:", err);
    }
  }

  async _restorePersistedHistory() {
    if (!this._hass) return;
    try {
      const data = await this._hass.callApi("GET", "kyber/history");
      const persistedHistory = this._sanitizeHistoryForPersistence(data?.history || []);
      const persistedSummary = String(data?.compacted_summary || "").trim();

      // Capture session metadata
      this._activeSessionId = data?.session_id || null;
      this._activeSessionName = data?.session_name || "Session 1";

      // Only apply restored data if nothing has been written in-memory yet.
      // This avoids races with tests and with very early user interactions.
      if (this._chatHistory.length === 0 && !this._compactedSummary) {
        this._chatHistory = persistedHistory;
        this._compactedSummary = persistedSummary;
        this._resetChatView();
        this._chatHistory.forEach((msg) => this._appendMessage(msg.content, msg.role === "user" ? "user" : "assistant"));
        console.log("[Kyber] restored", persistedHistory.length, "messages from history");
      }
      this._historyRestored = true;
      this._updateSessionIndicator();
    } catch (_) {
      // Non-fatal: start with empty in-memory history
      this._chatHistory = [];
      this._compactedSummary = "";
      this._resetChatView();
      this._historyRestored = true;
    }
  }

  async _clearHistory() {
    this._chatHistory = [];
    this._compactedSummary = "";
    this._resetChatView();
    try {
      await this._hass.callApi("DELETE", "kyber/history");
      this._setStatus("History cleared");
      this._showContextRefreshedMessage("History cleared");
    } catch (err) {
      this._setStatus(`History clear failed: ${err.message || String(err)}`, "error");
    }
  }

  _getActiveSession() {
    return this._activeSessionId ? { id: this._activeSessionId, name: this._activeSessionName || "Session 1" } : null;
  }

  _updateSessionIndicator() {
    const name = this._activeSessionName || "";
    const indicator = this.shadowRoot?.getElementById("session-indicator");
    if (indicator) indicator.textContent = name;
  }

  async _autoNameSession() {
    if (!this._hass || !this._activeSessionId) return;
    // Only use real user/assistant exchanges (skip internal [CHANGE] messages)
    const messages = this._chatHistory.filter(
      (m) => !m.content.startsWith("[CHANGE]") && !m.content.startsWith("I saved")
    );
    if (messages.length < 2) return;
    try {
      const token = this._hass.auth.data.access_token;
      const resp = await fetch("/api/kyber/sessions/name", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ messages }),
      });
      if (!resp.ok) return;
      const data = await resp.json();
      if (data.name) {
        this._activeSessionName = data.name;
        this._updateSessionIndicator();
      }
    } catch (_) {
      // Non-fatal — session keeps its current name
    }
  }

  async _loadSessionList() {
    if (!this._hass) return [];
    try {
      const token = this._hass.auth.data.access_token;
      const resp = await fetch("/api/kyber/sessions", { headers: { Authorization: `Bearer ${token}` } });
      if (!resp.ok) return [];
      const data = await resp.json();
      this._sessions = (data.sessions || []).map((s) => ({ id: s.id, name: s.name, history: Array(s.message_count), active: s.active }));
      return this._sessions;
    } catch (_) {
      return [];
    }
  }

  async _createSession(name) {
    if (!this._hass) return;
    const token = this._hass.auth.data.access_token;
    const resp = await fetch("/api/kyber/sessions", {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ name, switch: true }),
    });
    if (!resp.ok) {
      this._appendMessage(`Failed to create session (HTTP ${resp.status})`, "assistant");
      return;
    }
    const data = await resp.json();
    this._activeSessionId = data.session_id;
    this._activeSessionName = data.name;
    // Clear in-memory history for the new session
    this._chatHistory = [];
    this._compactedSummary = "";
    this._resetChatView();
    this._updateSessionIndicator();
    this._showContextRefreshedMessage("New session started");
  }

  async _switchSession(nameOrId) {
    if (!this._hass) return;
    const sessions = await this._loadSessionList();
    const num = parseInt(nameOrId, 10);
    const target = !isNaN(num) && num >= 1 && num <= sessions.length
      ? sessions[num - 1]
      : sessions.find((s) => s.name.toLowerCase() === nameOrId.toLowerCase() || s.id === nameOrId);
    if (!target) {
      this._appendMessage(`Session not found: "${nameOrId}". Use \`/session list\` to see available sessions.`, "assistant");
      return;
    }
    const token = this._hass.auth.data.access_token;
    const switchResp = await fetch("/api/kyber/sessions", {
      method: "PUT",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ action: "switch", session_id: target.id }),
    });
    if (!switchResp.ok) {
      this._appendMessage(`Failed to switch session (HTTP ${switchResp.status})`, "assistant");
      return;
    }
    this._activeSessionId = target.id;
    this._activeSessionName = target.name;
    // Reload history for this session
    this._chatHistory = [];
    this._compactedSummary = "";
    await this._restorePersistedHistory();
    this._appendMessage(`Switched to session: **${target.name}**`, "assistant");
    this._showContextRefreshedMessage("Session switched");
  }

  async _renameSession(newName) {
    if (!this._hass) return;
    const token = this._hass.auth.data.access_token;
    const resp = await fetch("/api/kyber/sessions", {
      method: "PUT",
    });
    if (!resp.ok) {
      this._appendMessage(`Failed to rename session (HTTP ${resp.status})`, "assistant");
      return;
    }
    const oldName = this._activeSessionName;
    this._activeSessionName = newName;
    this._updateSessionIndicator();
    this._appendMessage(`Session renamed from **${oldName}** to **${newName}**`, "assistant");
  }

  async _deleteSession(sessionId) {
    if (!this._hass) return;
    const token = this._hass.auth.data.access_token;
    const resp = await fetch("/api/kyber/sessions", {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId }),
    });
    if (!resp.ok) {
      this._appendMessage(`Failed to delete session (HTTP ${resp.status})`, "assistant");
      return;
    }
    const data = await resp.json();
    this._activeSessionId = data.active_session;
    this._chatHistory = [];
    this._compactedSummary = "";
    await this._restorePersistedHistory();
    this._appendMessage("Session deleted. Switched to previous session.", "assistant");
  }

  async _handleSessionCommand(argStr) {
    const parts = argStr.match(/^(\w+)(?:\s+(.*))?$/i);
    const sub = parts ? parts[1].toLowerCase() : "";
    const rest = parts ? (parts[2] || "").trim() : "";

    if (!sub || sub === "list") {
      const sessions = await this._loadSessionList();
      if (!sessions.length) {
        this._appendMessage("No sessions yet. Use `/session new [name]` to create one.", "assistant");
        return;
      }
      const lines = sessions.map((s, i) => {
        const active = s.id === this._activeSessionId ? " ← active" : "";
        return `${i + 1}. **${s.name}** (${s.history.length} messages)${active}`;
      });
      this._appendMessage("**Chat Sessions:**\n" + lines.join("\n"), "assistant");
      return;
    }
    if (sub === "new") {
      const name = rest || `Session ${(this._sessions || []).length + 1}`;
      await this._createSession(name);
      this._appendMessage(`Started new session: **${name}**`, "assistant");
      return;
    }
    if (sub === "switch") {
      if (!rest) { this._appendMessage("Usage: `/session switch <name>`", "assistant"); return; }
      await this._switchSession(rest);
      return;
    }
    if (sub === "delete") {
      const session = this._getActiveSession();
      if (!session) { this._appendMessage("No active session to delete.", "assistant"); return; }
      this._buildCommandCard({
        icon: "🗑",
        title: `Delete session: ${session.name}`,
        detail: `${session.history.length} messages will be lost.`,
        danger: true,
        onConfirm: async () => { await this._deleteSession(session.id); },
      });
      return;
    }
    this._appendMessage(`Unknown session sub-command: "${sub}". Try: new, list, switch, delete`, "assistant");
  }

  _logChange(description) {
    const entry = { role: "assistant", content: `[CHANGE] ${description}` };
    this._addChatHistory(entry.role, entry.content);
  }
};
