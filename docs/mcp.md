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

Kyber exposes the following tools over MCP:

| Tool | Token cost | Purpose |
|---|---|---|
| `kyber_ask` | High | Full AI pipeline — reasoning, memory, planning |
| `kyber_execute_plan` | Low | Execute a plan from `kyber_ask` directly |
| `get_entity_state` | Very low | Read current state of one or more entities |
| `list_entities` | Low | List entities with optional domain/area filter |
| `search_entities` | Very low | Find entity IDs by name, area, or keyword |
| `call_service` | Very low | Call any HA service directly |
| `get_datetime` | Very low | Current date/time/timezone from HA |
| `get_todo_items` | Very low | Items from HA todo list entities |
| `calendar_get_events` | Very low | Events from HA calendar entities |
| `kyber_remember` | Very low | Store a fact in Kyber's knowledge base |
| `kyber_recall` | Very low | Search Kyber's knowledge base |

---

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

**Returns:** AI response text, a `plan` object (if the AI produced one), number of actions executed, and token usage.

> The response may include a `plan.actions` array. Pass that directly to `kyber_execute_plan` to execute it — no need to re-invoke `kyber_ask`.

---

### `kyber_execute_plan`
Execute a plan produced by `kyber_ask`. Pass the `actions` array from the plan response to apply each action against Home Assistant.

> **Requires** the setting `MCP can change state of home` to be enabled in Kyber settings (`Settings → Kyber → Configure → Developer`).

```json
{
  "name": "kyber_execute_plan",
  "arguments": {
    "actions": [
      { "type": "call_service", "domain": "light", "service": "turn_off",
        "service_data": { "entity_id": "light.living_room" } }
    ]
  }
}
```

**Returns:** Per-action results with `status` (`ok` or `error`) and `undo_action` objects for each applied change.

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

### `search_entities`
Search entities by name, area, or keyword. Useful when you don't know the exact entity ID — search first, then call `get_entity_state` for live state.

```json
{
  "name": "search_entities",
  "arguments": {
    "query": "bedroom light",   // name, area, alias, or keyword
    "limit": 20                 // optional, default 20
  }
}
```

**Returns:** Matching entity IDs with friendly name, domain, area, and current state.

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

---

### `get_datetime`
Get the current date, time, day of week, and timezone from Home Assistant.

```json
{ "name": "get_datetime", "arguments": {} }
```

Returns `datetime`, `date`, `time`, `day_of_week`, `timezone`, and `utc`.

---

### `get_todo_items`
Fetch items from Home Assistant todo list entities (shopping lists, task lists, etc.).

```json
{
  "name": "get_todo_items",
  "arguments": {
    "entity_ids": ["todo.shopping"],   // optional — omit for all lists
    "status": "needs_action"           // needs_action | completed | all
  }
}
```

---

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

### `kyber_remember`
Store a fact about the user's home in Kyber's persistent knowledge base — entity aliases, preferences, device notes, or procedures.

```json
{
  "name": "kyber_remember",
  "arguments": {
    "subject": "tv in living room",
    "content": "The main TV is media_player.samsung_tv",
    "category": "entity_alias"   // optional: entity_alias | home_preference | user_preference | entity_fact | home_fact | general
  }
}
```

Stored facts are automatically injected into future AI context via Kyber's knowledge retrieval.

---

### `kyber_recall`
Search Kyber's knowledge base for stored facts. Use this before guessing entity IDs or user preferences.

```json
{
  "name": "kyber_recall",
  "arguments": {
    "query": "tv"
  }
}
```

**Returns:** Matching facts with subject, content, category, and confidence score.

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
