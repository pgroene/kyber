# Kyber — System Architecture

## Overview

Kyber is a Home Assistant custom integration that combines three layers:

| Layer | Technology | Role |
|---|---|---|
| **Frontend** | Web component (`<kyber-panel>`) | Chat UI + YAML editor |
| **Backend** | Python custom component (`custom_components/kyber/`) | HTTP API, HA registry operations |
| **AI** | Ollama (via HA `ai_task` entity) | LLM inference |

The panel is mounted in the HA sidebar at `/kyber` and communicates exclusively through the backend API endpoints registered under `/api/kyber/*`. All requests require HA authentication.

---

## Frontend (`www/kyber/kyber-panel.js`)

A single-file custom element registered as `<kyber-panel>` using the Shadow DOM. It is served from `/local/kyber/kyber-panel.js` (HA's `www/` directory) and loaded by the panel registration in `__init__.py`.

### Dependencies

- **CodeMirror 6** — bundled separately in `codemirror-bundle.js`. Provides the YAML editor with syntax highlighting, folding, bracket matching, and autocompletion.
- **HA built-ins** — accesses `this.hass` (injected by HA) for `hass.callApi`, `hass.panels`, and state data.

### Key State Properties

| Property | Type | Description |
|---|---|---|
| `_chatHistory` | `Array<{role, content}>` | Rolling conversation buffer sent to `/complete` |
| `_editor` | `EditorView` | CodeMirror 6 editor instance (created lazily) |
| `_editorMode` | `"automation" \| "script" \| "dashboard"` | Controls which save path and AI instructions are used |
| `_currentAutomationId` | `string \| null` | Config ID of the loaded automation or script |
| `_currentDashboardPath` | `string \| null` | `url_path` of the loaded dashboard (`null` = Overview) |
| `_autopilot` | `boolean` | When `true`, plans execute and YAML applies automatically |

### Layout

The panel renders a two-column grid when the editor is open:

```
┌─────────────────────────────────────────────┐
│  Toolbar (automation selector / dashboard)  │
├─────────────────────┬───────────────────────┤
│   CodeMirror YAML   │      Chat sidebar     │
│      editor         │  (messages + input)   │
└─────────────────────┴───────────────────────┘
```

When no editor is open, the chat sidebar fills the full width.

### Core Methods

**`_askAI()`**
Handles slash commands (`/autopilot on|off`), then POSTs to `/api/kyber/complete` with the current prompt, chat history, editor content, dashboard list (from `hass.panels`), and installed Lovelace resources. On success, delegates to `_appendAIResponse`.

**`_appendAIResponse(fullText, yamlBlocks, plan)`**
Renders the AI response as a chat bubble. If `yamlBlocks` are present, attaches an "Apply to editor" button. If a `plan` is present, calls `_buildPlanCard`. In autopilot mode, applies YAML and executes plans automatically.

**`_buildPlanCard(plan)`**
Renders a structured action card from the JSON plan object. Displays a summary, a before/after table for each action, and Execute / Undo buttons. POSTs to `/api/kyber/execute` on confirm.

### History Compaction

`_chatHistory` is bounded by `_COMPACT_TRIGGER` (default: 20 messages). When the limit is exceeded, overflow messages are sent to `/api/kyber/summarize` and replaced with a compact summary string (`compacted_summary`), which is injected as a `[Earlier in this conversation]` block in the next `/complete` request.

---

## Backend (`custom_components/kyber/`)

### `__init__.py`

Entry point for the integration. `async_setup_entry` is called by HA when the config entry is loaded. It:

1. Registers all four HTTP view classes with `hass.http.register_view`.
2. Registers the `<kyber-panel>` custom panel in the HA sidebar via `async_register_panel`.
3. Passes `ai_task_entity_id` (from the config entry) to views that need to call the LLM.

### `config_flow.py`

Provides the UI-driven setup flow. The user selects an `ai_task` entity (e.g., an Ollama integration entity) to use as the AI provider. The chosen entity ID is stored in the config entry as `ai_task_entity_id`.

### `http_api.py`

Contains all API view handlers (see [API Endpoints](#api-endpoints) below). Also houses:

- `_build_context(hass)` — assembles the HA state snapshot injected into every prompt (see [Context Building](#context-building)).
- `_extract_yaml_blocks(text)` / `_extract_plan_block(text)` — regex parsers for AI response fences.
- `_build_service_undo(...)` — generates reversible undo actions from pre-execution state snapshots.

### `const.py`

Defines `DOMAIN`, config key constants, and `SYSTEM_PROMPT_TEMPLATE` — a large f-string that embeds:

- The AI persona and behavioural rules (language matching, fuzzy entity resolution).
- `{area_list}`, `{label_list}`, `{automation_list}`, `{script_list}`, `{entity_list}` placeholders filled by `_build_context`.
- The complete reference of built-in HA Lovelace card types and YAML authoring rules.
- All plan/action type specifications (see [Plan/Action System](#planaction-system)).

---

## API Endpoints

All endpoints require HA authentication (`requires_auth = True`).

### `POST /api/kyber/complete`

Proxies an AI completion request to the configured `ai_task` entity (Ollama).

**Request body**

```json
{
  "prompt": "Turn on the living room lights",
  "history": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}],
  "compacted_summary": "Earlier summary of the conversation (may be empty)",
  "yaml": "Current editor YAML content (may be empty)",
  "editor_mode": "automation | script | dashboard",
  "dashboards": [{"title": "Home", "url_path": "home", "mode": "storage"}],
  "lovelace_resources": ["/hacsfiles/mini-graph-card/mini-graph-card-bundle.js"]
}
```

**Response**

```json
{
  "response": "Full AI response text (may include markdown, code blocks)",
  "yaml_blocks": ["parsed yaml string 1", "..."],
  "plan": { ... } | null
}
```

The backend assembles a single `instructions` string containing: the system prompt (with full HA context), user/dashboard/YAML sections, conversation history, and the current user message. This is passed to `async_generate_data` from `homeassistant.components.ai_task`.

---

### `POST /api/kyber/execute`

Applies a list of entity registry or service actions produced by an AI plan.

**Request body**

```json
{
  "actions": [
    {"type": "call_service", "domain": "light", "service": "turn_on", "entity_id": "light.living_room", "service_data": {"brightness": 200}},
    {"type": "assign_area", "entity_id": "light.bedroom", "area_id": "bedroom"}
  ]
}
```

**Supported action types**

| Type | Required fields | Description |
|---|---|---|
| `call_service` | `domain`, `service` | Calls any HA service; optional `entity_id`, `service_data` |
| `assign_area` | `entity_id`, `area_id` | Moves entity to an area via entity registry |
| `rename_entity` | `entity_id`, `name` | Updates entity's friendly name |
| `assign_label` | `entity_id`, `label_id` | Adds a label to an entity (creates label if missing) |
| `remove_label` | `entity_id`, `label_id` | Removes a label from an entity |
| `create_area` | `name` | Creates a new HA area |
| `rename_area` | `area_id`, `name` | Renames an existing area |
| `delete_area` | `area_id` | Deletes an area |

**Response**

```json
{
  "results": [
    {"status": "ok", "type": "call_service", "entity_id": "light.living_room", "undo_action": { ... }},
    {"status": "error", "entity_id": "switch.missing", "message": "Entity not found in registry"}
  ]
}
```

Each successful result includes an `undo_action` where reversibility is possible. For `call_service`, the pre-execution entity state is captured and used to construct the undo (e.g., restoring brightness, temperature, cover position, or volume).

---

### `POST /api/kyber/parse_yaml`

Converts a YAML string to a JSON config object. Used by the frontend before saving automation/script YAML via HA's native REST endpoints (`config/automation/config/{id}`).

**Request body**

```json
{"yaml": "alias: My Automation\ntrigger: ..."}
```

**Response**

```json
{"config": {"alias": "My Automation", "trigger": "..."}}
```

Returns `400` if the YAML is invalid or not a mapping.

---

### `POST /api/kyber/summarize`

Merges overflow chat messages into a running summary string, preserving `[CHANGE]` lines that record actual HA modifications.

**Request body**

```json
{
  "previous_summary": "User asked about lights. Changed bedroom brightness to 150.",
  "messages": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
}
```

**Response**

```json
{"summary": "Updated merged summary text..."}
```

Falls back to plain concatenation if the AI call fails, so history is never lost.

---

## Context Building

Every `/complete` request builds a rich context block injected into the AI prompt via `_build_context(hass)` and additional dynamic sections assembled in `KyberView.post`.

The full prompt structure (in order):

```
[SYSTEM_PROMPT_TEMPLATE]
  ├── Areas (name → id)
  ├── Labels (label_id | name)
  ├── Automations (entity_id | friendly_name | config_id)
  ├── Scripts (entity_id | friendly_name)
  └── Entities (entity_id | friendly_name | area | labels)

## Current user
  └── Display name and role (admin / standard user)

## Dashboards
  └── List from frontend hass.panels (title, url_path, mode)

## Custom card resources  [optional]
  └── Installed Lovelace resource URLs (HACS cards, etc.)

## ⚠️ DASHBOARD EDITOR IS CURRENTLY OPEN  [conditional]
  └── Current dashboard YAML + mandatory instruction to return full updated YAML

## Current automation YAML  [conditional, automation/script mode only]
  └── Editor content

---

[Earlier in this conversation]   ← compacted_summary (if any)
[Recent messages]                ← last N turns from _chatHistory
User: <current prompt>
Assistant:
```

The dashboard editor warning is a hard instruction that overrides the plan system — the AI must return a `\`\`\`yaml` block, not a `\`\`\`plan` block, when the editor is open.

---

## Plan/Action System

The AI signals structured intent by embedding a fenced ````plan` block in its response. The backend parses this with a regex and returns it as a structured `plan` object in the `/complete` response. The frontend renders it as an interactive plan card.

### Plan types

**Entity/service changes**

```json
{
  "summary": "Turn on the living room lights at 80% brightness",
  "actions": [
    {
      "type": "call_service",
      "domain": "light",
      "service": "turn_on",
      "entity_id": "light.living_room",
      "service_data": {"brightness": 204},
      "current_state": "off",
      "new_state": "on (80%)",
      "description": "Turn on living room light"
    }
  ],
  "warnings": []
}
```

**Open YAML editor** (for an automation or script)

```json
{
  "open_editor": true,
  "automation_id": "automation.morning_lights",
  "summary": "Add a 5-minute delay before turning off"
}
```

**Open dashboard editor**

```json
{
  "open_dashboard": true,
  "url_path": "home",
  "summary": "Add a weather card to the Home dashboard"
}
```

**Area management**

```json
{
  "summary": "Rename Bedroom to Master Bedroom",
  "actions": [
    {
      "type": "rename_area",
      "area_id": "bedroom",
      "name": "Master Bedroom",
      "current_state": "Bedroom",
      "new_state": "Master Bedroom",
      "description": "Rename area"
    }
  ]
}
```

### Undo

Every action in a plan carries a corresponding `undo_action` (same schema) returned by `/execute`. The frontend collects these from the execute response and attaches an Undo button to the plan card. Clicking Undo re-POSTs the undo actions to `/execute`.

---

## Data Flow Diagram

```
User types prompt
      │
      ▼
┌─────────────────────────────────────────┐
│            <kyber-panel>                │
│  _askAI()                               │
│  ┌──────────────────────────────────┐   │
│  │ Collect: prompt, history,        │   │
│  │ editor YAML, dashboards,         │   │
│  │ lovelace resources, editor_mode  │   │
│  └──────────────┬───────────────────┘   │
└─────────────────┼───────────────────────┘
                  │ POST /api/kyber/complete
                  ▼
┌─────────────────────────────────────────┐
│           KyberView (backend)           │
│  _build_context(hass)                   │
│    → areas, labels, entities,           │
│      automations, scripts               │
│  Assemble full instructions string      │
│  async_generate_data(ai_task_entity_id) │
└─────────────────┬───────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│      Ollama (via HA ai_task entity)     │
│  Generates response text                │
└─────────────────┬───────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│           KyberView (backend)           │
│  _extract_yaml_blocks(response_text)    │
│  _extract_plan_block(response_text)     │
│  → { response, yaml_blocks, plan }      │
└─────────────────┬───────────────────────┘
                  │ JSON response
                  ▼
┌─────────────────────────────────────────┐
│            <kyber-panel>                │
│  _appendAIResponse(text, yaml, plan)    │
│  ┌──────────────┐  ┌────────────────┐  │
│  │ YAML blocks  │  │   Plan card    │  │
│  │ → "Apply"    │  │ _buildPlanCard │  │
│  │   button     │  │ → Execute btn  │  │
│  └──────┬───────┘  └───────┬────────┘  │
└─────────┼───────────────────┼──────────┘
          │                   │
          │ Apply to editor   │ POST /api/kyber/execute
          ▼                   ▼
   CodeMirror editor   ┌─────────────────────────────┐
   updated in-place    │      KyberExecuteView        │
                       │  For each action:            │
          │            │  • entity_reg.async_update   │
          │ Save btn   │  • hass.services.async_call  │
          ▼            │  • area_reg.async_create/... │
   POST hass.callApi   └──────────────┬──────────────┘
   config/automation/                 │
   config/{id}           { results, undo_actions }
                                      │
                                      ▼
                             Undo button rendered
                             in plan card
```

---

## File Map

```
custom_components/kyber/
├── __init__.py          # Integration setup, panel + view registration
├── config_flow.py       # UI config flow (ai_task entity selection)
├── http_api.py          # All HTTP views and context builder
├── const.py             # DOMAIN, config keys, SYSTEM_PROMPT_TEMPLATE
└── manifest.json        # Integration metadata

www/kyber/
├── kyber-panel.js       # <kyber-panel> custom element (all frontend logic)
└── codemirror-bundle.js # Pre-built CodeMirror 6 bundle

docs/
└── architecture.md      # This file
```
