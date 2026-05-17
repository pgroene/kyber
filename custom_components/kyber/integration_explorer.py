"""Proactive integration exploration — stores knowledge facts from loaded integrations.

Each integration gets multiple knowledge facts so the model can discover it via
semantic search instead of needing to recognise the integration name.

For example, after exploring 'goodwe':
  Fact 1 (summary):    "goodwe provides 32 entities. Domains: sensor (28), switch (2), number (2). Example: solar_power, total_yield, ..."
  Fact 2 (sensors):    "goodwe sensor entities include: Solar Power (W), Total Yield (kWh), Grid Export (W), ..."
  Fact 3 (services):   "goodwe supports actions: switch.turn_on, switch.turn_off, number.set_value"
  Fact 4 (capability): "You can use goodwe for: solar/PV energy yield, grid export monitoring, sensor readings"

So when the user asks "wat is mijn zonne-opbrengst?" (solar yield?) the TF-IDF search
finds the goodwe facts and the model immediately knows which integration to call.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from .knowledge import KnowledgeStore

_LOGGER = logging.getLogger(__name__)

# Sample entity names to include per integration in facts
_SAMPLE_COUNT = 8

# At startup, explore this many integrations (sorted by entity count desc)
_STARTUP_EXPLORE_LIMIT = 40

# Internal HA platforms that don't provide user-queryable data — skip them
_SKIP_PLATFORMS = frozenset({
    "group", "template", "input_boolean", "input_number", "input_text",
    "input_select", "input_datetime", "timer", "counter", "script",
    "automation", "homeassistant", "persistent_notification", "zone",
    "sun", "recorder", "history_stats", "utility_meter", "shopping_list",
    "todo", "conversation", "stt", "tts", "wake_word", "intent_script",
})

# Domain → natural-language capability description
_DOMAIN_CAPABILITIES: dict[str, str] = {
    "sensor":         "sensor readings and measurements",
    "binary_sensor":  "on/off state detection",
    "switch":         "switch and power control",
    "light":          "light control (on/off, brightness, colour)",
    "climate":        "heating, cooling, and thermostat control",
    "media_player":   "media playback and volume control",
    "cover":          "blinds, curtains, covers, and garage doors",
    "camera":         "camera images and video streams",
    "fan":            "fan and ventilation control",
    "alarm_control_panel": "security alarm control",
    "lock":           "lock and door control",
    "vacuum":         "robot vacuum control",
    "weather":        "weather forecasts and conditions",
    "number":         "numeric settings and controls",
    "select":         "selection of modes and options",
    "button":         "triggering one-shot actions",
    "device_tracker": "device and person location tracking",
    "person":         "person presence and location",
    "calendar":       "calendar events and schedules",
    "event":          "event notifications",
}


def _unit_suffix(unit: str | None) -> str:
    return f" ({unit})" if unit else ""


async def async_explore_integration(
    hass: "HomeAssistant",
    kstore: "KnowledgeStore",
    platform: str,
    entities: list[dict[str, Any]],
) -> list[str]:
    """Generate and store multiple knowledge facts for one integration.

    Parameters
    ----------
    hass:       Home Assistant instance
    kstore:     Kyber knowledge store (must be loaded)
    platform:   Integration platform name (e.g. "goodwe", "buienradar")
    entities:   Entity dicts — each has entity_id, name, unit_of_measurement

    Returns
    -------
    List of fact content strings that were stored.
    """
    if not entities or platform in _SKIP_PLATFORMS:
        return []

    # Group by HA domain
    by_domain: dict[str, list[dict]] = {}
    for e in entities:
        eid = e.get("entity_id", "")
        domain = eid.split(".")[0] if "." in eid else "unknown"
        by_domain.setdefault(domain, []).append(e)

    stored_facts: list[str] = []

    async def _store(content: str, extra_tags: list[str]) -> None:
        await kstore.async_add(
            "integration_capability",
            content,
            subject=platform,
            tags=[f"integration:{platform}", "auto-discovered"] + extra_tags,
            source="integration_explorer",
            confidence=0.9,
        )
        stored_facts.append(content)

    # ── Fact 1: Summary (entity count + domains + sample names) ──────────────
    domain_summary = ", ".join(
        f"{d} ({len(ents)})" for d, ents in sorted(by_domain.items())
    )
    sample_names = [
        e.get("name") or e.get("entity_id", "")
        for e in entities[:_SAMPLE_COUNT]
        if e.get("name") or e.get("entity_id")
    ]
    summary = (
        f"Integration '{platform}' provides {len(entities)} entities. "
        f"Domains: {domain_summary}. "
        f"Example entities: {', '.join(sample_names)}."
    )
    await _store(summary, ["integration-summary"])

    # ── Fact 2: Sensor details (most searchable — includes units + names) ─────
    if "sensor" in by_domain:
        sensors = by_domain["sensor"]
        sensor_items = [
            f"{e.get('name') or e.get('entity_id', '')}"
            f"{_unit_suffix(e.get('unit_of_measurement'))}"
            for e in sensors[:_SAMPLE_COUNT]
        ]
        sensor_fact = (
            f"'{platform}' sensor entities include: {', '.join(sensor_items)}. "
            f"Total: {len(sensors)} sensors."
        )
        await _store(sensor_fact, ["sensor-data"])

    # ── Fact 3: Available services / actions ──────────────────────────────────
    all_services = hass.services.async_services()
    integration_services: list[str] = []
    for domain in sorted(by_domain.keys()):
        for svc_name in list(all_services.get(domain, {}).keys())[:6]:
            integration_services.append(f"{domain}.{svc_name}")
        if len(integration_services) >= 14:
            break

    if integration_services:
        svc_fact = (
            f"'{platform}' supports these services/actions: "
            f"{', '.join(integration_services)}."
        )
        await _store(svc_fact, ["services"])

    # ── Fact 4: Capability hints (what questions can you ask) ─────────────────
    caps = [
        _DOMAIN_CAPABILITIES[d]
        for d in sorted(by_domain.keys())
        if d in _DOMAIN_CAPABILITIES
    ]
    if caps:
        cap_fact = f"You can use '{platform}' for: {', '.join(caps)}."
        await _store(cap_fact, ["capabilities"])

    _LOGGER.debug("Explored integration '%s' → %d facts stored", platform, len(stored_facts))
    return stored_facts


async def async_startup_explore_all(
    hass: "HomeAssistant",
    kstore: "KnowledgeStore",
    entity_reg: Any,
) -> int:
    """Explore all loaded integrations at startup and populate knowledge store.

    Skips integrations that already have auto-discovered facts (idempotent).
    Returns the number of integrations that were newly explored.
    """
    await kstore.async_load()

    # Which platforms already have stored facts?
    existing: set[str] = {
        entry.get("subject", "")
        for entry in kstore._entries.values()
        if "auto-discovered" in (entry.get("tags") or [])
        and entry.get("subject")
    }

    # Build platform → entity list from the entity registry
    platform_entities: dict[str, list[dict]] = {}
    for entry in entity_reg.entities.values():
        plat = entry.platform or "unknown"
        if plat in _SKIP_PLATFORMS:
            continue
        if plat not in platform_entities:
            platform_entities[plat] = []
        state = hass.states.get(entry.entity_id)
        platform_entities[plat].append({
            "entity_id": entry.entity_id,
            "name": (state.attributes.get("friendly_name") if state else None) or entry.entity_id,
            "unit_of_measurement": (state.attributes.get("unit_of_measurement") if state else "") or "",
        })

    # Process largest integrations first; cap at _STARTUP_EXPLORE_LIMIT
    sorted_platforms = sorted(
        platform_entities.items(),
        key=lambda kv: -len(kv[1]),
    )[:_STARTUP_EXPLORE_LIMIT]

    explored = 0
    for platform, entities in sorted_platforms:
        if platform in existing:
            _LOGGER.debug("Integration '%s' already in knowledge — skipping", platform)
            continue
        try:
            facts = await async_explore_integration(hass, kstore, platform, entities)
            if facts:
                explored += 1
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Failed to explore integration '%s': %s", platform, err)

    _LOGGER.info(
        "Kyber integration explorer: explored %d new integrations (%d total platforms found)",
        explored,
        len(sorted_platforms),
    )
    return explored
