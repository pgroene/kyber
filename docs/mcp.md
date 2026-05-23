# Kyber — MCP Server

Kyber exposes a **Model Context Protocol (MCP)** endpoint so external AI clients — ChatGPT, Claude Desktop, Cursor, or any MCP-compatible tool — can control your Home Assistant through Kyber's full AI pipeline.

---

## What is MCP?

[Model Context Protocol](https://modelcontextprotocol.io) is an open standard that lets AI assistants connect to external tools and data sources. Think of it as a universal plug between an LLM and the outside world.

When ChatGPT or Claude connects to Kyber via MCP, they gain access to your smart home — ask the same questions and give the same commands you would in the Kyber chat panel, but from any MCP client.

---

## Enabling the MCP Server

The MCP server is **enabled by default**. To toggle it:

`Settings → Devices & Services → Kyber → Configure → Developer → Enable MCP server`

When enabled, Kyber registers:

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/kyber/mcp` | `POST` | MCP tool calls (JSON-RPC 2.0) |
| `/api/kyber/mcp/log` | `GET` | View recent MCP call log |
| `/api/kyber/mcp/log` | `DELETE` | Clear the MCP call log |

All endpoints require a valid Home Assistant **Bearer token**.

---

## Connecting from ChatGPT

1. In ChatGPT settings, go to **Connectors** (or **Tools → Add tool**)
2. Add a new **MCP server** with:
   - **URL:** `https://<your-ha-host>/api/kyber/mcp`
   - **Auth:** Bearer token (generate one in HA: *Profile → Long-Lived Access Tokens*)
3. ChatGPT will discover Kyber's tools automatically via `tools/list`

> **Tip:** Use [Nabu Casa](https://www.nabucasa.com/) or a reverse proxy to expose your HA instance securely. Never expose your HA directly on port 8123 to the internet without TLS.

---

## Connecting from Claude Desktop

Add this to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "kyber": {
      "type": "http",
      "url": "https://<your-ha-host>/api/kyber/mcp",
      "headers": {
        "Authorization": "Bearer <your-long-lived-token>"
      }
    }
  }
}
```

Restart Claude Desktop. You'll see Kyber listed as a connected tool.

---

## Available Tools

Kyber exposes four tools over MCP:

### `kyber_ask`
Send a natural-language question or command through Kyber's full AI pipeline — the same pipeline used in the chat panel, including memory, knowledge base lookup, entity context, and self-correction.

```json
{
  "name": "kyber_ask",
  "arguments": {
    "prompt": "Turn off all the lights in the living room",
    "entity_id": "conversation.kyber",   // optional override
    "user_id": "abc123"                  // optional, for rate limiting
  }
}
```

**Returns:** AI response text, number of actions executed, and token usage.

---

### `get_entity_state`
Fetch the current state and attributes of one or more HA entities.

```json
{
  "name": "get_entity_state",
  "arguments": {
    "entity_id": "light.living_room"
  }
}
```

```json
{
  "name": "get_entity_state",
  "arguments": {
    "entity_ids": ["light.living_room", "sensor.temperature_living"]
  }
}
```

---

### `list_entities`
List entities in your Home Assistant, optionally filtered by domain.

```json
{
  "name": "list_entities",
  "arguments": {
    "domain": "light",    // optional: light, switch, sensor, etc.
    "limit": 50           // optional, default 100
  }
}
```

---

### `call_service`
Call any Home Assistant service directly.

```json
{
  "name": "call_service",
  "arguments": {
    "domain": "light",
    "service": "turn_on",
    "service_data": {
      "entity_id": "light.living_room",
      "brightness": 200
    }
  }
}
```

> **Prefer `kyber_ask` over `call_service`** when you want the AI to interpret a natural-language request — it adds context awareness, entity resolution, and self-correction. Use `call_service` for direct, programmatic control.

### `calendar_get_events`
Fetch events from one or more Home Assistant calendar entities within a time range.

```json
{
  "name": "calendar_get_events",
  "arguments": {
    "entity_ids": ["calendar.work", "calendar.family"],
    "start": "2026-05-23T00:00:00",
    "end": "2026-05-30T23:59:59"
  }
}
```

| Parameter | Type | Description |
|---|---|---|
| `entity_ids` | `string[]` | Optional. Calendar entity IDs to query. Omit to query all calendars. |
| `start` | `string` | ISO 8601 start of range. Defaults to now. |
| `end` | `string` | ISO 8601 end of range. Defaults to 7 days from now. |

Returns a list of events sorted by start time, with the `calendar` field indicating which calendar each event belongs to.

---

## Transport

Kyber uses **Streamable HTTP** (MCP spec 2024-11-05):

- Single `POST` per request — no persistent SSE stream required
- JSON-RPC 2.0 over HTTP
- Batch requests supported (`[{...}, {...}]`)
- Notifications (no `id`) return `204 No Content`

---

## Rate Limiting & Token Budget

MCP calls share Kyber's rate limiter and daily token budget with the chat panel:

| Setting | Key | Default | Location |
|---|---|---|---|
| Max requests/minute | `max_requests_per_minute` | `30` | Developer section |
| Daily token budget | `max_daily_tokens` | `0` (unlimited) | Model Configuration |

When the rate limit is hit, the tool returns:
```json
{ "error": "Rate limit exceeded. Retry after 42s" }
```

When the token budget is exhausted:
```json
{ "error": "Daily token budget exceeded. Resets at midnight." }
```

---

## Debug & Monitoring

The **MCP** tab in the Kyber Debug panel shows a unified call log of all MCP and classic (chat panel) calls side by side.

**Path:** Kyber Debug sidebar (`/kyber-debug`) → **🔌 MCP** tab

```
┌──────────────────────────────────────────────────────────────────┐
│  [Memory] [Last Turn] [Status] [Logs] [Tests] [🔌 MCP ◀]         │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Side-by-side Compare                                            │
│  [Prompt ___________________________________] [▶ Run Compare]    │
│                                                                  │
│  MCP Result                    │  Classic Result                 │
│  ─────────────────────────────────────────────────────────────  │
│  "The living room light is…"   │  "The living room light is…"   │
│                                                                  │
│  Call Log  Filter: [All ▼]      [Clear MCP] [Clear Classic]     │
│  ┌────────┬──────────┬─────────┬────────┬────────┬───────────┐  │
│  │ Time   │ Source   │ Method  │ User   │ ms     │ Outcome   │  │
│  ├────────┼──────────┼─────────┼────────┼────────┼───────────┤  │
│  │ 07:14  │ 🔌 MCP   │ kyber_… │ user-1 │ 1 204  │ ✅ ok     │  │
│  │ 07:12  │ 🏠 Classic│ chat   │ user-1 │   892  │ ✅ ok     │  │
│  └────────┴──────────┴─────────┴────────┴────────┴───────────┘  │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

The log is a ring buffer of the last **200 calls** per source, stored in memory (cleared on HA restart). Use `GET /api/kyber/mcp/log` to retrieve it programmatically.

---

## Security Considerations

- The MCP endpoint requires a valid HA Bearer token — no anonymous access
- Token scope is the same as the HA user who owns the token (admin tokens can do more)
- Consider using a dedicated HA user with limited permissions for external MCP clients
- To disable MCP entirely: `Developer → Enable MCP server → OFF`

---

## See Also

- [Settings Reference](settings.md) — all configuration options
- [Debug Panel](debug-panel.md) — MCP call log and side-by-side compare
- [MCP specification](https://modelcontextprotocol.io/specification) — upstream protocol docs
