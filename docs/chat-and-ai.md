# Kyber — AI Chat & Smart Home Assistant

The **AI Chat** panel is the core of Kyber. It gives you a conversational interface for controlling your smart home, managing entities, editing automations, and building dashboards — all powered by a local AI model via Home Assistant's AI Task integration (e.g. Ollama).

---

## Table of Contents

1. [Opening the Panel](#opening-the-panel)
2. [Sending Messages](#sending-messages)
3. [Proposal / Plan Cards](#proposal--plan-cards)
4. [Autopilot Mode](#autopilot-mode)
5. [Conversation History & Context Compaction](#conversation-history--context-compaction)
6. [[CHANGE] Tagging](#change-tagging)
7. [Entity Autocomplete](#entity-autocomplete)
8. [Context Awareness](#context-awareness)
9. [Slash Commands](#slash-commands)

---

## Opening the Panel

Navigate to the **Kyber** entry in the Home Assistant sidebar. The panel opens in chat-only view. When the AI asks to edit an automation or dashboard, a CodeMirror YAML editor slides in on the right half of the screen.

---

## Sending Messages

Type any question or instruction in the prompt box at the bottom and press **Ask** or `Enter`.

```
You: Turn on the living room lights at 80% brightness
```

```
You: Move all the bedroom sensors to the Bedroom area
```

```
You: Rename light.bedroom_ceiling to "Ceiling Light"
```

The AI understands **natural language** and **multiple languages**. If you refer to a room in Dutch ("Slaapkamer") or use a partial name ("the couch lamp"), the AI automatically maps it to the closest matching entity or area and notes the mapping in its reply.

> **Tip:** Press `↑` / `↓` in the prompt box to navigate through your previous messages, just like a shell.

---

## Proposal / Plan Cards

When you ask the AI to change entities, areas, labels, or call services, it responds with a structured **Proposal card** instead of making changes immediately.

### What a Proposal card shows

| Element | Description |
|---|---|
| **📋 Proposal** header | A one-line summary of what the AI intends to do |
| **What will change** list | One row per action: entity ID, change type badge, from → to |
| **Warnings** | Non-fatal side-effect notices (e.g. "area has entities assigned") |
| **Missing entity errors** | Red ⛔ banner if an entity ID wasn't found in HA; those actions are skipped |
| **✅ Execute** button | Applies all valid actions |
| **↩ Undo** button | Appears after execution; reverts every change |

### Example interaction

```
You: Set the thermostat to 21°C and turn off the garden switch
```

The AI returns:

```
I'll update both devices for you.
```

Followed by a Proposal card:

```
📋 Proposal
  Adjust thermostat and garden switch

What will change
  climate.living_room   [climate.set_temperature]   19°C → 21°C
  switch.garden         [switch.turn_off]            on → off

                    ✅ Execute
```

After clicking **Execute**:

```
✅ Done — 2 action(s) applied.
↩ Undo (2 actions)
```

### Supported action types

| Badge | What it does |
|---|---|
| `Area` | Assign an entity to an area |
| `Name` | Rename an entity |
| `Label` | Add a label to an entity |
| `Remove label` | Remove a label from an entity |
| `Create area` | Create a new HA area |
| `Rename area` | Rename an existing area |
| `Delete area` | Delete an area |
| `<domain>.<service>` | Call any HA service (e.g. `light.turn_on`, `climate.set_temperature`) |

### Missing entity handling

If the AI includes an entity ID that does not exist in your Home Assistant:

- A red ⛔ banner lists the unknown IDs.
- Those rows are dimmed and **skipped** when you click Execute.
- The Execute button label shows the count: `✅ Execute (2 of 3)`.

---

## Autopilot Mode

Autopilot lets Kyber execute proposals and apply YAML suggestions automatically, without you clicking **Execute** or **Apply** each time.

### Enabling / disabling

Type a slash command in the prompt box:

```
/autopilot on
```

```
/autopilot off
```

An **⚡ AUTOPILOT ON** badge pulses orange in the status bar whenever autopilot is active.

### Behaviour in autopilot mode

| Event | Normal mode | Autopilot mode |
|---|---|---|
| Proposal card rendered | Shows **Execute** button | Auto-executes after **2 seconds** |
| YAML suggestion rendered | Shows **Apply** button | Auto-applies immediately (if editor is open) |
| Dashboard / editor open prompt | Shows **Open editor** button | Clicks button automatically after 300 ms |

> **Caution:** Autopilot makes real changes to your Home Assistant setup without confirmation. Use it only when you trust the AI's proposals for the current task.

---

## Conversation History & Context Compaction

Every message you send and every AI reply is kept in a rolling **chat history** that is forwarded to the AI with each new request. This allows multi-turn conversations where the AI remembers what was said earlier.

Kyber now persists this chat history (including the compacted summary) in Home Assistant storage, scoped to the currently logged-in user. This means chat context survives browser refreshes and Home Assistant restarts.

### Clear history

Use the **Clear history** button in the chat toolbar to reset the current user's conversation state. This clears:

- the visible chat messages in the panel
- in-memory `_chatHistory`
- persisted history and compacted summary in HA storage for that user

### History window

| Parameter | Default |
|---|---|
| Messages kept verbatim | Last **5** |
| Compaction trigger | When history exceeds **7** messages |

### Compaction (summarisation)

When the history grows beyond the trigger threshold, the oldest messages are automatically summarised server-side via the `/api/kyber/summarize` endpoint. The resulting compact summary is prepended to subsequent requests under the label `[Earlier in this conversation]`, keeping the context window efficient without losing important history.

The summariser **always preserves** lines that begin with `[CHANGE]` (see below) so the AI never forgets what has actually been done.

### What the AI sees per request

```
[Earlier in this conversation]
<compacted summary of older messages>

[Recent messages]
User: Turn on the bedroom light
Assistant: Done — bedroom light is now on.
…

User: <your current message>
Assistant:
```

---

## [CHANGE] Tagging

Every time a proposal is successfully executed, or a YAML file is saved, Kyber writes a special tagged entry into the conversation history:

```
[CHANGE] The following changes were successfully applied:
- call_service on light.bedroom: off → on (brightness 200)
- assign_area on sensor.bedroom_temp: Kitchen → Bedroom
```

```
[CHANGE] automation YAML saved: morning_lights
```

```
[CHANGE] Dashboard "My Dashboard" saved successfully.
```

These `[CHANGE]` lines are **never dropped** during compaction. They give the AI a reliable, persistent record of every change made in the current session, so follow-up questions like *"what did you just change?"* or *"undo the last thing"* always have accurate context.

---

## Entity Autocomplete

The prompt box includes a live autocomplete dropdown that helps you reference exact entity IDs without having to remember them.

### Triggering autocomplete

| Trigger | What it matches |
|---|---|
| Type any partial text (≥ 2 chars) | All `entity_id` values that **start with** your text |
| Type `/` | Available slash commands |
| Type `/automation open <partial>` | Automation names / entity IDs |
| Type `/script open <partial>` | Script names / entity IDs |
| Type `/dashboard open <partial>` | Dashboard url_paths / titles |

### Navigating the dropdown

| Key | Action |
|---|---|
| `↓` / `↑` | Move selection |
| `Enter` or `Tab` | Insert highlighted item |
| `Escape` | Close without inserting |

The dropdown shows both the `entity_id` (monospace) and the friendly name beneath it.

### Example

```
You type: light.bed[↓ dropdown opens]
   light.bedroom
   light.bedroom_ceiling   "Ceiling Light"
   light.bedroom_lamp      "Bedside Lamp"
```

Press `Enter` or `Tab` to insert the full entity ID at the cursor.

---

## Context Awareness

Every AI request is sent with a rich context block built from your live Home Assistant state. The AI therefore knows:

| Context | Detail |
|---|---|
| **All entities** | `entity_id`, friendly name, assigned area, labels |
| **Areas** | Name and `area_id` for every area |
| **Labels** | All defined labels |
| **Automations** | entity_id, friendly name, config_id |
| **Scripts** | entity_id, friendly name |
| **Dashboards** | Title, `url_path`, and mode for every Lovelace panel |
| **Custom card resources** | JS resource URLs loaded via HACS or manually |
| **Current user** | Your display name and admin/standard role |
| **Open editor content** | Full YAML of the automation or dashboard currently in the editor |

This means you can ask things like:

```
You: Which lights are in the Kitchen area?
You: Add a tile card for every sensor in the Bedroom to my Test dashboard
You: What automations do I have that use the motion sensor?
```

…and the AI can answer accurately without you copy-pasting entity IDs.

### Custom card awareness

If you have custom Lovelace cards installed (e.g. via HACS), their JS resource URLs are fetched once per session and included in context. The AI will use `type: custom:<card-name>` syntax automatically when those cards are available.

---

## Slash Commands

Slash commands are typed directly in the prompt box and execute without going to the AI.

### Autopilot

```
/autopilot on        — enable autopilot mode
/autopilot off       — disable autopilot mode
```

### Automation

```
/automation open <name>     — open automation YAML editor (partial name OK)
/automation close           — close the editor
/automation save            — save the current automation
/automation new             — open HA automation editor in a new tab
/automation delete <name>   — permanently delete an automation
```

### Script

```
/script open <name>         — open script YAML editor
/script close               — close the editor
/script save                — save the current script
/script new                 — open HA script editor in a new tab
/script delete <name>       — permanently delete a script
```

### Dashboard

```
/dashboard open [name]      — open dashboard YAML editor
/dashboard close            — close the editor
/dashboard save             — save the current dashboard
/dashboard new              — create a new dashboard (prompts for title)
/dashboard delete           — delete the currently open dashboard
```

### Area

```
/area new <name>                    — create a new area
/area delete <name>                 — delete an area
/area rename <old> to <new>         — rename an area
/area list                          — list all areas
```

### Blueprint

```
/blueprint browse           — open HA blueprint page in a new tab
```

All slash commands that make changes show a **confirmation card** with an Execute and Cancel button before taking effect. Destructive operations (delete) display an additional danger warning.

---

## Sample Conversations

### Controlling devices

```
You: Turn on all the lights in the living room at 50%

AI: I'll turn on the living room lights at 50% brightness.

📋 Proposal
  Turn on all living room lights at 50% brightness

What will change
  light.living_room_main   [light.turn_on]   off → on (brightness 127)
  light.living_room_lamp   [light.turn_on]   off → on (brightness 127)

✅ Execute
```

### Reorganising areas

```
You: All my bedroom devices are in the wrong area — move sensor.bedroom_temp,
     switch.bedroom_fan, and light.bedroom to "Bedroom"

AI: I'll move all three to the Bedroom area.

📋 Proposal
  Assign three bedroom devices to Bedroom

What will change
  sensor.bedroom_temp   [Area]   Kitchen → Bedroom
  switch.bedroom_fan    [Area]   (none)  → Bedroom
  light.bedroom         [Area]   Hallway → Bedroom

✅ Execute
```

### Multi-turn editing

```
You: Open the morning lights automation

AI: [opens editor with YAML]
    Here's the Morning Lights automation. What would you like to change?

You: Make it trigger at 7:30 instead of 7:00

AI: [returns updated YAML block with Apply button]
    I've updated the trigger time from 07:00 to 07:30.

You: Also add a condition so it only runs on weekdays

AI: [returns another updated YAML block]
    Done — I've added a weekday condition.
```
