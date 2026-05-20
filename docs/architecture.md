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

## Frontend (`www/kyber/`)

The frontend is a custom element `<kyber-panel>` using Shadow DOM, split across multiple files via ES module mixins. The entry point is `www/kyber/kyber-panel.js`, which imports and composes the mixins:

```
kyber-panel.js
  └── extends AIMixin(PlanCardsMixin(SlashMixin(EditorMixin(DebugMixin(KnowledgeMixin(SessionMixin(UtilsMixin(HTMLElement))))))))
        │
        ├── src/slash-commands-mixin.js   — All /command handlers + autocomplete
        ├── src/ai-mixin.js               — _askAI(), _appendAIResponse(), tool loop
        ├── src/plan-cards-mixin.js       — _buildPlanCard(), _buildCommandCard()
        ├── src/editor-mixin.js           — CodeMirror 6 setup, save/load for automations/dashboards
        ├── src/debug-mixin.js            — Debug panel rendering, bundle download
        ├── src/knowledge-mixin.js        — Memory panel, fact cards, deep analysis
        ├── src/session-mixin.js          — Session CRUD, switching, persistence
        └── src/utils-mixin.js            — _showMsg, _setStatus, _escapeHtml, etc.
```

> **Convention:** every slash command sub-action MUST be listed in `CMD_SUBS` in `slash-commands-mixin.js` and have a corresponding entry in `_HELP_DATA.cmds` with a description. This ensures autocomplete works for all commands.

### Dependencies

- **CodeMirror 6** — bundled separately in `codemirror-bundle.js`.
- **HA built-ins** — `this.hass.callApi()`, `this.hass.callWS()`, `this.hass.panels`, state data.

### Key State Properties

| Property | Type | Description |
|---|---|---|
| `_chatHistory` | `Array<{role, content}>` | Rolling conversation buffer sent to `/complete`, persisted per-user via `/history` |
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

1. Registers all Kyber HTTP view classes with `hass.http.register_view` (chat, execution, parsing, summarization, history/sessions, progress, knowledge, and debug routes).
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

- The AI persona, first-tool routing hints, and behavioural rules (language matching, fuzzy entity resolution).
- A compact home summary plus `{area_list}` and `{notable_state_block}` placeholders filled by `_build_context`.
- The complete reference of built-in HA Lovelace card types and YAML authoring rules.
- All plan/action type specifications (see [Plan/Action System](#planaction-system)).

---

## API Endpoints

All endpoints require HA authentication (`requires_auth = True`).

### Endpoint inventory (current source)

| Endpoint | Methods | Purpose |
|---|---|---|
| `/api/kyber/complete` | `POST` | Main AI request/response pipeline (`response`, `yaml_blocks`, `plan`, metadata) |
| `/api/kyber/execute` | `POST` | Execute plan actions (`call_service`, area/label/entity operations) and produce undo actions |
| `/api/kyber/parse_yaml` | `POST` | Parse YAML text to JSON mapping before saving automation/script/dashboard configs |
| `/api/kyber/summarize` | `POST` | Compact overflow chat history into `summary` while preserving change context |
| `/api/kyber/history` | `GET`, `POST`, `DELETE` | Persist/restore/clear per-user chat history + compacted summary |
| `/api/kyber/sessions` | `GET`, `POST`, `DELETE` | Session CRUD/switching for multi-session chat history |
| `/api/kyber/sessions/name` | `POST` | Rename the current active session |
| `/api/kyber/progress` | `GET` | Poll live turn progress events by `request_id` |
| `/api/kyber/knowledge` | `GET`, `POST`, `DELETE` | List/search/create/update/delete knowledge (memory) entries |
| `/api/kyber/knowledge/analyze` | `GET`, `POST` | Analyze home config and propose memory entries |
| `/api/kyber/knowledge/analyze_deep` | `GET`, `POST` | Deep analysis pipeline for durable memory extraction |
| `/api/kyber/knowledge/feedback` | `POST` | Apply user/auto ratings to memory entries |
| `/api/kyber/knowledge/purge` | `POST` | Purge low-quality or stale knowledge entries |
| `/api/kyber/area_suggestions/dismiss` | `POST` | Dismiss a proactive area assignment suggestion |
| `/api/kyber/labels` | `GET` | List all `kyber:*` labels with their assigned entities |
| `/api/kyber/self_update` | `GET`, `POST` | Check (`GET`) or install (`POST`) latest release directly from GitHub |
| `/api/kyber/debug/last_turn` | `GET` | Return the latest captured debug snapshot |
| `/api/kyber/debug/tool_history` | `GET` | Return recent tool-call history ring buffer |
| `/api/kyber/debug/status` | `GET` | Debug overview: memory/session/turn/tool status |
| `/api/kyber/debug/bundle` | `GET` | Download ZIP debug bundle for a specific `request_id` |
| `/api/kyber/debug/bug-report` | `GET` | Download a sanitised bug report bundle |
| `/api/kyber/debug/logs` | `GET` | Return recent log records from the in-memory ring buffer |
| `/api/kyber/debug/mode` | `GET`, `POST` | Read/update runtime UI debug-mode flag |
| `/api/kyber/export/memory` | `GET` | Export all knowledge entries as JSON |
| `/api/kyber/export/home-state` | `GET` | Export full home state snapshot as JSON |
| `/api/kyber/prompt_tests` | `GET`, `POST`, `DELETE` | Prompt regression test case management |
| `/api/kyber/prompt_tests/run` | `POST` | Run one or all prompt regression tests |
| `/api/kyber/prompt_tests/capture` | `POST` | Capture current AI response as a test baseline |
| `/api/kyber/prompt_tests/regenerate` | `POST` | Re-run a test and update its expected output |

---

## Context Building

Every `/complete` request builds a rich context block injected into the AI prompt via `_build_context(hass)` and additional dynamic sections assembled in `KyberView.post`.

The full prompt structure (in order):

```
[SYSTEM_PROMPT_TEMPLATE]
  ├── Query-type → first-tool routing hints
  ├── Home summary (area/label/automation/script/entity counts)
  ├── Areas (name → id)
  └── Notable per-area home state lines [optional]

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

The prompt intentionally no longer injects full label / automation / script inventories on every turn. Those are available through tools (`get_labels`, `list_automations`, `list_scripts`) so the base prompt stays smaller and leaves more room for recent conversation history.

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
