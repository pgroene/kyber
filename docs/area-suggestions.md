# Kyber — Proactive Area Suggestions

Kyber monitors your entities and proactively suggests area assignments for devices that don't have one. These suggestions appear as interactive cards in the chat panel.

---

## When They Appear

An area suggestion card appears when Kyber detects that you are describing or referring to a location in your message, and there are entities nearby that have no area assigned. For example:

> "Turn on the kitchen lights"

If `light.ceiling_kitchen_01` has no area, Kyber may append an area suggestion card asking if you want to assign it to the **Kitchen** area.

---

## Location Intent Detection

Kyber uses a phrase-matching engine (`intent_and_context.py`) to detect location intent in your message. Supported phrases include:

**English:**
- "in the [room]", "in my [room]"
- "turn on/off the [room]"
- "the [room] lights/switch/sensor"
- "[room] is …"

**Dutch:**
- "in de [kamer]", "in mijn [kamer]"
- "zet de [kamer] … aan/uit"
- "de [kamer] …"
- "[kamer] is …"

The detected room name is matched against HA area names using fuzzy matching (case-insensitive, strip diacritics).

---

## The Suggestion Card UX

When a suggestion is triggered, Kyber shows an **area approval bar** pinned at the **top of the chat window** (above the message history). Each suggestion appears as a compact chip:

```
  Kitchen Light → assign to Kitchen?   ✓  ✗
  Espresso Machine → assign to Kitchen?  ✓  ✗
```

- **✓ (confirm)** — assigns the entity to the suggested area immediately via the HA entity registry
- **✗ (dismiss)** — suppresses this suggestion; it will not reappear for the same entity/area combination

The bar disappears automatically once all pending suggestions are confirmed or dismissed.

Dismissals are stored in `.storage/kyber.dismissed_suggestions`.

---

## Multiple Suggestions

If multiple unassigned entities are detected in the same message, Kyber shows one card per entity. Each card can be acted on independently.

---

## Tips

- Area suggestions only fire when location intent is detected. They don't appear for generic messages like "turn on all lights".
- If an entity was already narrated (has an alias), Kyber will use the alias in the suggestion card instead of the raw entity ID.
- Suggestions are per-entity — assigning one entity to an area doesn't auto-assign its siblings.
