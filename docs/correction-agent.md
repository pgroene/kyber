# Kyber Correction Micro-Agent

When a plan action fails during execution, Kyber automatically invokes a **correction micro-agent** that tries to fix the problem and re-execute the corrected plan.

## How it works

```
User clicks Execute
        │
        ▼
/api/kyber/execute
        │
        ├─ All actions succeed ──► ✅ Done (chat: [CHANGE])
        │
        └─ call_service action(s) fail
                │
                ▼
        correction_agent.py
                │
                ├─ Load domain docs from domain_docs.py (no network call)
                ├─ Build focused micro-prompt
                ├─ Call AI provider (same one configured for chat)
                ├─ Parse ```plan``` block from response
                └─ Return corrected_actions + learned_fact
                        │
                        ▼
        Frontend re-executes corrected actions
                │
                ├─ Correction succeeds ──► 🔧 Corrected & applied (chat: [🔧 CORRECTION])
                ├─ Toast: "🧠 Learned: ..."
                └─ Correction also fails ──► Error shown
```

## What gets corrected

The correction agent targets **`call_service` failures** only. Registry/config actions (rename, assign area, etc.) are not correctable automatically.

Common correctable failures:
- `extra keys not allowed @ data['color_temp']` — HA 2025.x rejects `color_temp` when the entity's `supported_color_modes` doesn't include it. The agent learns to use `rgb_color` instead.
- Service parameters with wrong types or out-of-range values.

## Domain documentation

Domain docs are pre-loaded from [`domain_docs.py`](../custom_components/kyber/domain_docs.py) — no live tool call is needed. This keeps the correction agent fast (single AI round-trip).

Currently documented domains: `light`, `switch`, `media_player`, `climate`, `cover`, `fan`, `vacuum`, `lock`, `alarm_control_panel`, `input_boolean`, `input_number`, `input_select`, `scene`, `script`, `automation`.

## Chat history

Execution outcomes are recorded in chat history so the AI knows what happened in future turns:

| Event | Chat message |
|---|---|
| All actions succeed | `[CHANGE] The following changes were successfully applied: ...` |
| Actions fail | `[FAILED] N action(s) failed for "plan summary": error message` |
| Correction succeeds | `[🔧 CORRECTION] Successfully applied corrected plan: ...` |
| User undoes | `[CHANGE] Undid: previous changes` |

## Toast notifications

When the correction agent learns something new, a toast is shown at the top of the panel:

```
🧠 Learned: light correction — HA rejected parameter(s) color_temp — removed from retry
```

## Extending domain docs

To add documentation for a new domain, edit `custom_components/kyber/domain_docs.py`:

```python
DOMAIN_DOCS["my_domain"] = """\
## my_domain — actions reference

### Basic control
| Action | Key params | Notes |
|---|---|---|
| my_domain.turn_on | entity_id | ... |
"""
```

## Logging

All correction agent activity is logged under the `custom_components.kyber` logger:

```
INFO  Kyber: execution had failures — invoking correction micro-agent
INFO  Kyber: correction agent returned 3 corrected action(s)
INFO  Kyber: correction: calling Azure provider
INFO  Kyber: correction: success — 3 corrected action(s): Set lights to white using rgb_color
```

Set `logger: custom_components.kyber: debug` in your HA `configuration.yaml` for verbose output.

## Approval queue auto-popup

When a plan requires user approval (config-changing or destructive actions), and autopilot tries to execute them, the Execute button pulses with an orange glow to draw attention and scrolls into view automatically.
