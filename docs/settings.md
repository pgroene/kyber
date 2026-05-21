# Kyber — Settings Reference

This page documents every configurable setting in Kyber, with screen sketches so you can quickly locate each field in the UI.

> **Keeping this page up to date**
> Whenever you add, rename, or remove a setting — in `config_flow.py`, `strings.json`, `const.py`, or `debug-mixin.js` — update this file in the same PR. See the checklist at the bottom.

---

## Table of Contents

1. [Initial Setup (config flow)](#1-initial-setup-config-flow)
2. [Options (Configure)](#2-options-configure)
   - [Model Configuration](#21-model-configuration)
   - [Agents](#22-agents)
   - [Auto Assignments](#23-auto-assignments)
   - [Developer](#24-developer)
3. [Debug Panel — Status Tab](#3-debug-panel--status-tab)
   - [Entity Explorer](#31-entity-explorer)
   - [AI Narrator](#32-ai-narrator)
   - [Deep Analysis](#33-deep-analysis)
4. [Maintenance Checklist](#4-maintenance-checklist)

---

## 1. Initial Setup (config flow)

**Path:** `Settings → Devices & Services → Add Integration → search "Kyber"`

The setup form appears once, when you first add the integration. It combines entity selection with all configurable options in a single step.

```
┌─────────────────────────────────────────────────────────────┐
│  Kyber — Setup                                              │
│  Select your AI task entity and configure token limit       │
│  and startup behaviour.                                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Chat Model *                                               │
│  ┌─────────────────────────────────────────────┐           │
│  │ ai_task.ollama_llama3                    [▼] │           │
│  └─────────────────────────────────────────────┘           │
│                                                             │
│  ▼ Model Configuration                                      │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Chat Model: Context Window (tokens)                 │   │
│  │ ┌──────────────┐                                    │   │
│  │ │    20000     │  (min 2000)                        │   │
│  │ └──────────────┘                                    │   │
│  │                                                     │   │
│  │ Operations Model (optional)                         │   │
│  │ ┌─────────────────────────────────────────────┐    │   │
│  │ │ ai_task.ollama_llama3_2              [▼]     │    │   │
│  │ └─────────────────────────────────────────────┘    │   │
│  │ Used for entity narration. A smaller, cheaper       │   │
│  │ model works well here. Defaults to chat model.      │   │
│  │                                                     │   │
│  │ Operations Model: Context Window (tokens)           │   │
│  │ ┌──────────────┐                                    │   │
│  │ │    4000      │  (min 2000)                        │   │
│  │ └──────────────┘                                    │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ▼ Agents                                                   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Enable entity narrator                  [✓] ON      │   │
│  │ Narrator: run every N days              [━━●━━━] 1  │   │
│  │ Narrator batch size                     [━●━━━━] 20 │   │
│  │ Run analyze pass on HA restart          [✓] ON      │   │
│  │ Deep learning: run every N days         [━━━●━━] 7  │   │
│  │ Deep learning batch size                [●━━━━━] 5  │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ▼ Auto Assignments                                         │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Area assignment mode                                │   │
│  │   ○ Off                                             │   │
│  │   ● Suggest (recommended)                           │   │
│  │   ○ Automatic                                       │   │
│  │                                                     │   │
│  │ Label assignment mode                               │   │
│  │   ○ Off                                             │   │
│  │   ● Suggest (recommended)                           │   │
│  │   ○ Automatic                                       │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ▶ Developer  (collapsed)                                   │
│                                                             │
│                               [CANCEL]       [SUBMIT]       │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Options (Configure)

**Path:** `Settings → Devices & Services → Kyber → Configure`

After installation, click **Configure** on the Kyber integration card to edit any setting. The form is identical to the setup form but the entity selector is inside the **Model Configuration** section rather than at the top.

```
┌─────────────────────────────────────────────────────────────┐
│  Kyber options                                              │
│  Update model settings and feature flags.                   │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ▼ Model Configuration      ← click header to expand/fold  │
│  ▶ Agents                                                   │
│  ▶ Auto Assignments                                         │
│  ▶ Developer                                                │
│                                                             │
│                               [CANCEL]       [SUBMIT]       │
└─────────────────────────────────────────────────────────────┘
```

Each section expands inline. The sections are described below.

---

### 2.1 Model Configuration

Controls which AI models Kyber uses and how many tokens each is allowed.

```
┌─────────────────────────────────────────────────────────────┐
│  ▼ Model Configuration                                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Chat Model                                                 │
│  ┌─────────────────────────────────────────────┐           │
│  │ ai_task.ollama_mistral_nemo              [▼] │           │
│  └─────────────────────────────────────────────┘           │
│  Used for all chat interactions and plan generation.        │
│  Stat hint: "last call 1 420 ms · avg 1 102 ms"            │
│                                                             │
│  Chat Model: Context Window (tokens)                        │
│  ┌──────────────┐                                           │
│  │   131072     │  (min 2000)                               │
│  └──────────────┘                                           │
│                                                             │
│  Operations Model (optional)                                │
│  ┌─────────────────────────────────────────────┐           │
│  │ ai_task.ollama_llama3_2               [▼]   │           │
│  └─────────────────────────────────────────────┘           │
│  Used for entity narration and small background tasks.      │
│  Defaults to Chat Model if left blank.                      │
│                                                             │
│  Operations Model: Context Window (tokens)                  │
│  ┌──────────────┐                                           │
│  │    4000      │  (min 2000)                               │
│  └──────────────┘                                           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

| Field | Key | Default | Notes |
|---|---|---|---|
| Chat Model | `ai_task_entity_id` | *(first found)* | Any `ai_task.*` entity; see [Choosing a Model](../README.md#choosing-a-model) |
| Chat Model: Context Window | `max_tokens` | `20000` (auto-detected) | Kyber truncates its prompt to stay within this limit |
| Operations Model | `narrator_ai_task_entity_id` | *(same as chat)* | Optional separate model for narration and batch tasks |
| Operations Model: Context Window | `narrator_max_tokens` | `4000` | Context limit for the operations model |

> **Tip:** Kyber auto-detects the context window from the entity's `num_ctx` / `context_window` attribute on first setup, or falls back to the model name table in `const.py`. You can override it here.

---

### 2.2 Agents

Controls the three background processes that build Kyber's knowledge base.

```
┌─────────────────────────────────────────────────────────────┐
│  ▼ Agents                                                   │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ── Entity Narrator ──────────────────────────────────────  │
│                                                             │
│  Enable entity narrator                                     │
│  [✓] ON                                                     │
│                                                             │
│  Narrator: run every N days                                 │
│   1 ──●──────────────────────── 30                         │
│        └ value: 1                                           │
│                                                             │
│  Narrator batch size                                        │
│   1 ──────────●──────────────── 50                         │
│               └ value: 20                                   │
│                                                             │
│  ── Integration Explorer / Analyzer ─────────────────────  │
│                                                             │
│  Run analyze pass on HA restart                             │
│  [✓] ON                                                     │
│                                                             │
│  ── Deep Analysis ────────────────────────────────────────  │
│                                                             │
│  Deep learning: run every N days                            │
│   1 ──────●────────────────────── 90                       │
│            └ value: 7                                       │
│                                                             │
│  Deep learning batch size                                   │
│   1 ──●──────────────────────── 50                         │
│        └ value: 5                                           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

| Field | Key | Default | Range | Notes |
|---|---|---|---|---|
| Enable entity narrator | `narrator_enabled` | `true` | on/off | Runs after startup and on schedule; see [docs/narrator.md](narrator.md) |
| Narrator: run every N days | `narrator_interval_days` | `1` | 1–30 | How often the narrator re-processes un-narrated entities |
| Narrator batch size | `narrator_max_batch` | `20` | 1–50 | Max entities processed per narrator run |
| Run analyze pass on HA restart | `run_initial_analyze` | `true` | on/off | Re-runs the integration explorer on every HA restart |
| Deep learning: run every N days | `deep_learning_interval_days` | `7` | 1–90 | Scheduled frequency for the deep analyzer |
| Deep learning batch size | `deep_learning_max_batch` | `5` | 1–50 | Max automations/scripts analyzed per deep run |

---

### 2.3 Auto Assignments

Controls whether Kyber automatically suggests or applies area and label assignments when entities are mentioned in chat.

```
┌─────────────────────────────────────────────────────────────┐
│  ▼ Auto Assignments                                         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Area assignment mode                                       │
│  Suggest or auto-apply area assignments to entities         │
│  mentioned in conversation.                                 │
│                                                             │
│   ○ Off                                                     │
│   ● Suggest (recommended)   ← shows a one-click card       │
│   ○ Automatic               ← applies without asking       │
│                                                             │
│  Label assignment mode                                      │
│  Suggest or auto-apply kyber: device-type labels to         │
│  entities in conversation.                                  │
│                                                             │
│   ○ Off                                                     │
│   ● Suggest (recommended)   ← shows a one-click card       │
│   ○ Automatic               ← applies without asking       │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

| Field | Key | Default | Options | Notes |
|---|---|---|---|---|
| Area assignment mode | `area_assignment_mode` | `suggest` | `off` / `suggest` / `auto` | See [docs/area-suggestions.md](area-suggestions.md) |
| Label assignment mode | `label_assignment_mode` | `suggest` | `off` / `suggest` / `auto` | Applies `kyber:*` labels (e.g. `kyber:appliance`) |

---

### 2.4 Developer

Advanced options for development and debugging.

```
┌─────────────────────────────────────────────────────────────┐
│  ▶ Developer  (collapsed by default)                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Enable debug views                                         │
│  (Kyber Debug sidebar + per-turn debug tools)               │
│  [ ] OFF                                                    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

| Field | Key | Default | Notes |
|---|---|---|---|
| Enable debug views | `enable_debug_views` | `false` | Adds the **Kyber Debug** sidebar entry (`/kyber-debug`) and per-turn debug bundle downloads; see [docs/debug-panel.md](debug-panel.md) |

---

## 3. Debug Panel — Status Tab

**Path:** Kyber Debug sidebar (`/kyber-debug`) → **Status** tab

The Status tab shows live runtime state and lets you manually trigger each background process. It is only visible when **Enable debug views** is on.

```
┌─────────────────────────────────────────────────────────────┐
│  [Memory] [Last Turn] [Status ◀] [Logs] [Tests]             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Runtime                                                    │
│  ┌────────────────────┬─────────────────────────────────┐  │
│  │ AI Task entity     │ ai_task.ollama_mistral_nemo      │  │
│  │ Display name       │ Mistral Nemo                     │  │
│  │ Model              │ mistral-nemo:latest  📖          │  │
│  │ Server             │ http://localhost:11434            │  │
│  │ Autopilot          │ OFF                              │  │
│  │ Session            │ Morning routines                 │  │
│  │ Tool history size  │ 42                               │  │
│  └────────────────────┴─────────────────────────────────┘  │
│                                                             │
│  Storage                                                    │
│  ┌────────────────────┬──────────┐                         │
│  │ Total (Kyber data) │ 2.31 MB  │                         │
│  │   kyber.knowledge  │ 1.84 MB  │                         │
│  │   kyber.chat       │ 0.47 MB  │                         │
│  └────────────────────┴──────────┘                         │
│                                                             │
│  Resources (in-memory)                                      │
│  ┌────────────────────┬──────────┐                         │
│  │ Process RSS        │ 312 MB   │                         │
│  │ Debug snapshots    │ 12 / 50  │                         │
│  │ Global log buffer  │ 345/2000 │                         │
│  │ TF-IDF index terms │ 18,432   │                         │
│  │ Knowledge vectors  │ 1,204    │                         │
│  └────────────────────┴──────────┘                         │
│                                                             │
│  Knowledge store                                            │
│  ┌────────────────────┬──────────┐                         │
│  │ Total entries      │ 1,204    │                         │
│  │ Needs review       │ 7        │                         │
│  │ Total hits         │ 3,891    │                         │
│  └────────────────────┴──────────┘                         │
│  By category:                                               │
│  ┌────────────────────┬──────────┐                         │
│  │ entity_alias       │ 843      │                         │
│  │ home_fact          │ 201      │                         │
│  │ integration_fact   │ 160      │                         │
│  └────────────────────┴──────────┘                         │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

### 3.1 Entity Explorer

Shows the status of the integration indexer (Explorer) and lets you trigger a manual run.

```
┌─────────────────────────────────────────────────────────────┐
│  Entity Explorer                                            │
│  ┌───────────────────┬────────────────────────────────────┐ │
│  │ Status            │ Complete — 847 entities indexed    │ │
│  │ Started           │ 09:12:03                           │ │
│  └───────────────────┴────────────────────────────────────┘ │
│  ████████████████████████████████████ 100%                  │
│                                                             │
│  [ 🔍 Run Explorer now ]                                    │
│   ↑ Triggers a full re-index of all integrations            │
│     and dashboards. Button is disabled while running.       │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**While running:**
```
│  Status │ Indexing entities 423 / 847 (50%)                 │
│  Current│ hue                                               │
│  ████████████░░░░░░░░░░░░░░░░░░░░░░ 50%                    │
│  [ 🔍 Run Explorer now ]  ← disabled while running          │
```

---

### 3.2 AI Narrator

Shows narrator statistics and lets you trigger a manual run.

```
┌─────────────────────────────────────────────────────────────┐
│  AI Narrator                                                │
│  ┌──────────────────────┬──────────────────────────────┐   │
│  │ AI Task entity       │ ai_task.ollama_llama3_2       │   │
│  │ Model                │ llama3.2:3b  📖 bench report  │   │
│  │ Server               │ http://localhost:11434         │   │
│  │ Status               │ 843 accepted (97%) · 5 errors │   │
│  │ Last run             │ today at 08:31                 │   │
│  │ Accepted (1st try)   │ 821                           │   │
│  │ Accepted (retry)     │ 22                            │   │
│  │ Fallback (all failed)│ 5                             │   │
│  │ Errors               │ 5                             │   │
│  └──────────────────────┴──────────────────────────────┘   │
│                                                             │
│  [ ✍️ Run Narrator now ]                                    │
│   ↑ Processes un-narrated entities in batches.              │
│     Button is disabled while narrator is running.           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**While running**, a `✍️ N/T` badge appears in the chat panel header.

**While paused by chat**, the narrator waits until the current chat response is complete, then applies an exponential backoff (10 → 20 → 40 → 80 → 160 → 300 s) before resuming. See [docs/narrator.md](narrator.md) for details.

---

### 3.3 Deep Analysis

Shows deep analyzer status, progress, and lets you trigger a manual run with configurable parameters.

```
┌─────────────────────────────────────────────────────────────┐
│  Deep Analysis                                              │
│  ┌───────────────┬────────────────────────────────────────┐ │
│  │ Status        │ Last run: 48 analyzed, 312 facts in 87s│ │
│  └───────────────┴────────────────────────────────────────┘ │
│                                                             │
│  [ 🧠 Run Deep Analysis now ]  [3 ▲▼] passes  [10 ▲▼] items/pass  │
│   ↑ Triggers AI-driven fact extraction.                     │
│     "passes"   — how many times to cycle through the batch  │
│     "items/pass" — how many automations/scripts per pass    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**While running:**
```
│  Status   │ Running — pass 2 / 3, item: morning_lights    │
│  Progress │ 18 analyzed · 121 facts · 0 errors             │
│  🧠 ██████████████░░░░░░░░░░░░░░░░░  18 / 48              │
│                                                             │
│  [ 🧠 Run Deep Analysis now ]  ← disabled while running    │
```

**While paused by chat:**
```
│  Status   │ ⏸ Paused — waiting for chat (18 / 48 done)    │
│  🧠 ██████████████░░░░░░░░░░░░░░░░░  18 / 48              │
│                                                             │
│  [ 🧠 Run Deep Analysis now ]  ← disabled while paused     │
```
The in-flight AI call is cancelled immediately when a chat message arrives.
The analyzer resumes automatically after the chat response with an
exponential backoff (10 → 20 → 40 → 80 → 160 → 300 s).
See [docs/pipeline.md § 5b](pipeline.md) for full details.

**Run Now inputs** (in the Deep Analysis row only):

| Input | Id | Default | Range | Meaning |
|---|---|---|---|---|
| passes | `#dbg-deep-runs` | `3` | 1–20 | How many passes over the batch |
| items/pass | `#dbg-deep-limit` | `10` | 1–50 | How many items per pass |

---

### 3.4 Last Turn & Export

```
┌─────────────────────────────────────────────────────────────┐
│  Last turn                                                  │
│  ┌───────────────┬────────────────────────────────────────┐ │
│  │ When          │ 21 May 2026 09:12:44                   │ │
│  │ Elapsed       │ 3 241 ms                               │ │
│  │ Intent        │ informational                          │ │
│  │ Prompt size   │ 18,432 chars (~4,608 tokens)           │ │
│  └───────────────┴────────────────────────────────────────┘ │
│  [ 📦 Download debug bundle ]  [ 🐛 Bug report ]            │
│                                                             │
│  Export for Eval                                            │
│  Download snapshots to create test scenarios.               │
│  [ 📥 Home state ]  [ 🧠 Memory export ]                    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Maintenance Checklist

> When you change any setting in the integration, update this file in the **same PR**.

**Adding a new config field:**
- [ ] Add `CONF_*` and `DEFAULT_*` to `const.py`
- [ ] Add it to `_build_options_schema()` in `config_flow.py` under the right section
- [ ] Add the label to `strings.json` under `options.step.init.sections.<section>.data`
- [ ] If it also appears in the initial setup form, add it to `strings.json` under `config.step.user.data` too
- [ ] Add a row to the correct settings table in this file
- [ ] Update the ASCII art sketch if the section layout changes

**Removing or renaming a field:**
- [ ] Remove/rename in `const.py`, `config_flow.py`, `strings.json`
- [ ] Remove/rename the row in this file
- [ ] Add a migration note if existing config entries store the old key

**Adding a new Debug Panel control:**
- [ ] Add the HTML/JS in `debug-mixin.js`
- [ ] Document it in the relevant section (3.1–3.4) above
- [ ] Update the ASCII art sketch to show the new control

**Adding a new section to the options form:**
- [ ] Add `_SECTION_*` key in `config_flow.py`
- [ ] Add `sections.<key>` block in `strings.json`
- [ ] Add a new `### 2.N` subsection to this file with ASCII art and a settings table
