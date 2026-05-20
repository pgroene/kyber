# Kyber — Entity Intelligence & AI Narrator

Kyber includes an **AI narrator** that automatically generates rich, searchable descriptions and search aliases for every entity in your Home Assistant instance. This is what powers natural-language search — when you say "zet mijn koffiezet apparaat aan", Kyber can find `switch.onoff_keuken_espresso_304` even though the entity ID contains none of those words.

---

## How It Works

On startup (after the initial analysis pass), Kyber batches entities and sends them to the AI for narration. For each entity the narrator produces:

1. **A description** — a one-sentence human-readable summary of what the entity is and does.
2. **Search aliases** — 2–5 natural-language terms a user might type to find this entity.

Both are stored in the knowledge store (`.storage/kyber.knowledge`) as facts tagged with the current narrator version.

### Example

Given `switch.onoff_keuken_espresso_304` with friendly name "Onoff Keuken Espresso 304":

```
Description: Main power switch for the espresso machine in the kitchen.
Aliases: espresso machine, coffee maker, koffiezetapparaat, espresso switch, keuken espresso
```

---

## Language Detection

The narrator auto-detects the home language by sampling up to 200 entity friendly names:

```
detect_home_language(hass) → ("nl", "<dutch device vocab hint>")
```

The detection works by counting **marker words** (language-specific common words) in entity names. The language with the most marker hits wins.

| Language code | Example markers |
|---|---|
| `nl` | de, het, een, lamp, schakelaar, sensor |
| `de` | die, das, eine, licht, schalter, temperatur |
| `fr` | le, la, une, lumière, capteur, thermostat |
| `es` | el, la, una, luz, sensor, termostato |
| `it` | il, la, una, luce, sensore, termostato |
| `pt` | o, a, uma, luz, sensor, termostato |
| `en` | the, a, light, switch, sensor, thermostat |

If the detected language is not English, the narrator receives a `devices_hint` — a compact vocabulary block of device names in that language — which is injected into the batch prompt.

### Vocabulary hints

Language hints are defined in `language_hints.py` and keyed by language code. Each includes:

- **Rooms** — bedroom, kitchen, living room, etc.
- **Devices** — lights, switches, sensors, thermostats, media players
- **Kitchen appliances** — coffee maker, dishwasher, washing machine, oven, fridge, etc.

When `LANG_HINTS_VERSION` is bumped (e.g. after adding new vocabulary), the hints are re-seeded automatically on the next HA restart.

---

## Narrator Version

`_NARRATOR_VERSION` (currently `6`) is stored in `entity_narrator.py`. Each narrated entity gets tagged with `narrator-v{N}` in the knowledge store.

When you bump `_NARRATOR_VERSION`, all entities are re-narrated on the next startup — the "already narrated" check compares the stored tag against the current version tag. This is the mechanism used to pick up vocabulary improvements or prompt changes.

---

## Alias Quality Filter

To prevent the AI from hallucinating cross-domain aliases (e.g. mapping a TV child-lock switch to "espresso machine"), Kyber applies a **plausibility filter** before storing any alias:

```python
_alias_is_plausible(term, entity_id, description, name, manufacturer)
```

**Logic:**
1. Tokenize the alias term (strip stop words: de/het/een/the/a etc.)
2. Tokenize the entity_id + description + name + manufacturer
3. If there is **zero token overlap**, the alias is rejected

Examples:
- `"coffee maker"` for `switch.onoff_keuken_espresso_304` → ✅ "keuken" and "espresso" overlap
- `"coffee maker"` for `switch.onoff_tv_221_child_lock` → ❌ no overlap — rejected

Short aliases (≤ 2 characters) and empty terms always pass the filter.

---

## Startup Alias Purge

On every startup, `async_purge_implausible_aliases(kstore)` scans all stored `entity_alias` facts and removes any that fail the plausibility check. This cleans up stale bad aliases from before the filter was introduced.

The purge runs after the initial dedup step in `async_setup_entry` (`__init__.py`).

---

## Narrator Progress

You can monitor narrator progress in the **Kyber Debug panel** → **Status** tab, which shows:

- How many entities have been narrated
- How many are pending
- The current narrator version tag
- Any errors from the last batch run
