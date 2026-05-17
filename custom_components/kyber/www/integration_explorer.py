"""Proactive integration exploration — stores per-entity knowledge facts.

Phase 1 (integration summaries): one summary fact per integration so the AI
knows which integrations exist and what they do.

Phase 2 (per-entity facts): one knowledge entry per entity in the house.
Each entry includes the entity_id, friendly name, domain, device_class,
unit, area, and Dutch synonym hints.  These replace the old 25-sensor batch
facts which diluted TF-IDF scores and caused the wrong integration to be
recalled (or nothing at all).

Progress is tracked in hass.data[EXPLORER_PROGRESS_KEY] and exposed via
the /api/kyber/debug/status endpoint so the frontend can show a live bar.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from .knowledge import KnowledgeStore

_LOGGER = logging.getLogger(__name__)

# Key written into hass.data so the status endpoint can surface progress.
EXPLORER_PROGRESS_KEY = "kyber_explorer_progress"

# How many entities to add before yielding to the event loop.
_YIELD_EVERY = 5
# How many entities to add before flushing to disk.
_SAVE_EVERY = 50
# How many integrations to process without an entity limit.
_STARTUP_EXPLORE_LIMIT = 60

# Internal HA platforms that don't provide user-queryable data — skip them.
_SKIP_PLATFORMS = frozenset({
    "homeassistant", "persistent_notification", "recorder",
    "shopping_list", "todo", "conversation",
    "stt", "tts", "wake_word", "intent_script",
    # automations/scripts are already injected into the main prompt context
    "automation", "script",
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

# device_class → Dutch synonym hints (added as tags for TF-IDF).
# This lets Dutch queries like "welke bewegingssensors?" find the right entities.
_DC_DUTCH: dict[str, list[str]] = {
    "occupancy":    ["aanwezigheid", "beweging", "bezet", "presence"],
    "motion":       ["beweging", "bewegingssensor", "aanwezigheid"],
    "presence":     ["aanwezigheid", "thuis", "bezet"],
    "temperature":  ["temperatuur", "graden", "warmte", "koud"],
    "humidity":     ["vochtigheid", "luchtvochtigheid", "vocht"],
    "power":        ["vermogen", "watt", "verbruik"],
    "energy":       ["energie", "verbruik", "elektriciteit", "stroom", "kWh", "prijs"],
    "door":         ["deur", "open", "dicht", "inbraak"],
    "window":       ["raam", "raamcontact", "open", "dicht"],
    "illuminance":  ["lichtsterkte", "lux", "helderheid"],
    "battery":      ["batterij", "accu", "laad"],
    "co2":          ["CO2", "luchtkwaliteit", "carbon"],
    "voltage":      ["spanning", "volt"],
    "current":      ["stroom", "ampere"],
    "gas":          ["gas", "gasverbruik"],
    "water":        ["water", "waterverbruik"],
    "pm25":         ["fijnstof", "luchtkwaliteit"],
    "smoke":        ["rook", "brand", "branddetectie"],
    "moisture":     ["vocht", "nat", "droog"],
    "lock":         ["slot", "vergrendeld", "open"],
    "problem":      ["probleem", "storing", "fout"],
    "update":       ["update", "bijwerken"],
    "connectivity": ["verbinding", "internet", "wifi"],
    "plug":         ["stekker", "stopcontact"],
    "outlet":       ["stopcontact", "stekker"],
    "running":      ["actief", "aan", "draait"],
}

# Domain-level Dutch hints (used when no device_class is set)
_DOMAIN_DUTCH: dict[str, list[str]] = {
    "light":        ["lamp", "licht", "verlichting", "dimmen"],
    "switch":       ["schakelaar", "aan", "uit"],
    "cover":        ["jaloezie", "gordijn", "rolluik", "blind"],
    "climate":      ["thermostaat", "verwarming", "koeling", "temperatuur"],
    "media_player": ["muziek", "tv", "afspelen", "volume", "speaker"],
    "vacuum":       ["stofzuiger", "robot", "schoonmaken"],
    "lock":         ["slot", "deur", "vergrendeld"],
    "fan":          ["ventilator", "afzuiging", "ventilatie"],
    "camera":       ["camera", "beeld", "opname"],
    "weather":      ["weer", "temperatuur", "regen", "wind"],
    "person":       ["persoon", "thuis", "weg", "aanwezigheid"],
    "alarm_control_panel": ["alarm", "beveiliging"],
}


def _unit_suffix(unit: str | None) -> str:
    return f" ({unit})" if unit else ""


def _entity_fact(
    entity_id: str,
    name: str,
    platform: str,
    domain: str,
    device_class: str | None,
    unit: str | None,
    area_name: str | None,
    state_str: str | None,
) -> tuple[str, list[str]]:
    """Build a single-entity knowledge fact + tag list."""
    dc_part = f", device_class: {device_class}" if device_class else ""
    unit_part = _unit_suffix(unit)
    area_part = f", area: {area_name}" if area_name else ""
    state_part = f", state: {state_str}" if state_str not in (None, "unavailable", "unknown") else ""

    content = (
        f"{domain} \"{name}\" [{entity_id}]{unit_part}{dc_part}{area_part}{state_part}. "
        f"Integration: {platform}. "
        f"Use get_entity_state(\"{entity_id}\") to get current value."
    )

    # Tags: entity_id tokens, platform, domain, device_class, Dutch synonyms, area
    tags: list[str] = [
        entity_id,
        platform,
        domain,
    ]
    if device_class:
        tags.append(device_class)
        tags.extend(_DC_DUTCH.get(device_class, []))
    else:
        tags.extend(_DOMAIN_DUTCH.get(domain, []))
    if area_name:
        tags.append(area_name.lower())
    # Add name tokens as tags for fuzzy name matching
    import re
    name_tokens = re.split(r"[\s._\-]+", name.lower())
    tags.extend(t for t in name_tokens if len(t) > 2)

    return content, tags


# Bump this when the fact format changes to force re-exploration of all entities.
_EXPLORER_VERSION = 4
_EXPLORER_VERSION_TAG = f"explorer-v{_EXPLORER_VERSION}"


async def async_explore_integration(
    hass: "HomeAssistant",
    kstore: "KnowledgeStore",
    platform: str,
    entities: list[dict[str, Any]],
) -> list[str]:
    """Generate and store integration-level summary facts (not per-entity).

    Per-entity facts are stored separately in async_startup_explore_all.
    """
    if not entities or platform in _SKIP_PLATFORMS:
        return []

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
            tags=[f"integration:{platform}", "auto-discovered", _EXPLORER_VERSION_TAG] + extra_tags,
            source="integration_explorer",
            confidence=0.9,
            _save=False,  # caller bulk-saves after all integrations
        )
        stored_facts.append(content)

    # Summary fact
    domain_summary = ", ".join(
        f"{d} ({len(ents)})" for d, ents in sorted(by_domain.items())
    )
    sample_names = [
        e.get("name") or e.get("entity_id", "")
        for e in entities[:8]
        if e.get("name") or e.get("entity_id")
    ]
    summary = (
        f"Integration '{platform}' provides {len(entities)} entities. "
        f"Domains: {domain_summary}. "
        f"Example entities: {', '.join(sample_names)}."
    )
    await _store(summary, ["integration-summary"])

    # Services fact
    all_services = hass.services.async_services()
    integration_services: list[str] = []
    for domain in sorted(by_domain.keys()):
        for svc_name in list(all_services.get(domain, {}).keys())[:6]:
            integration_services.append(f"{domain}.{svc_name}")
        if len(integration_services) >= 14:
            break
    if integration_services:
        await _store(
            f"'{platform}' supports these services/actions: {', '.join(integration_services)}.",
            ["services"],
        )

    # Capability fact
    caps = [
        _DOMAIN_CAPABILITIES[d]
        for d in sorted(by_domain.keys())
        if d in _DOMAIN_CAPABILITIES
    ]
    if caps:
        await _store(f"You can use '{platform}' for: {', '.join(caps)}.", ["capabilities"])

    _LOGGER.debug("Explored integration '%s' → %d facts stored", platform, len(stored_facts))
    return stored_facts


async def async_startup_explore_all(
    hass: "HomeAssistant",
    kstore: "KnowledgeStore",
    entity_reg: Any,
) -> int:
    """Explore all entities and integrations; populate knowledge store.

    Phase 1: Integration-level summary facts (what each integration provides).
    Phase 2: Per-entity facts (one entry per entity with Dutch hints + area).

    Progress is written to hass.data[EXPLORER_PROGRESS_KEY] so the status
    endpoint and frontend can display a live progress bar.

    Returns the number of newly added facts.
    """
    from homeassistant.helpers import area_registry as ar

    await kstore.async_load()

    def _set_progress(**kwargs: Any) -> None:
        existing = hass.data.get(EXPLORER_PROGRESS_KEY) or {}
        hass.data[EXPLORER_PROGRESS_KEY] = {**existing, **kwargs, "updated_at": int(time.time())}

    _set_progress(status="starting", started_at=int(time.time()), done=0, total=0, current_platform="")

    # ── Phase 1: Integration summary facts ─────────────────────────────────────
    # Which platforms already have summary facts at the current version?
    existing_summaries: set[str] = {
        entry.get("subject", "")
        for entry in kstore._entries.values()
        if _EXPLORER_VERSION_TAG in (entry.get("tags") or [])
        and entry.get("source") == "integration_explorer"
        and "integration-summary" in (entry.get("tags") or [])
        and entry.get("subject")
    }

    platform_entities: dict[str, list[dict]] = {}
    for entry in entity_reg.entities.values():
        plat = entry.platform or "unknown"
        if plat in _SKIP_PLATFORMS:
            continue
        state = hass.states.get(entry.entity_id)
        platform_entities.setdefault(plat, []).append({
            "entity_id": entry.entity_id,
            "name": (state.attributes.get("friendly_name") if state else None) or entry.entity_id,
            "unit_of_measurement": (state.attributes.get("unit_of_measurement") if state else "") or "",
        })

    sorted_platforms = sorted(platform_entities.items(), key=lambda kv: -len(kv[1]))[:_STARTUP_EXPLORE_LIMIT]

    _set_progress(status="phase1_summaries", phase="summaries", total_integrations=len(sorted_platforms))

    summary_count = 0
    for platform, entities in sorted_platforms:
        if platform in existing_summaries:
            _LOGGER.debug("Integration '%s' summary already at v%d — skipping", platform, _EXPLORER_VERSION)
            continue
        _set_progress(current_platform=platform)
        try:
            facts = await async_explore_integration(hass, kstore, platform, entities)
            if facts:
                summary_count += 1
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Failed to explore integration '%s': %s", platform, err)
        await asyncio.sleep(0)  # yield without delay between integrations
    await kstore.async_force_save()

    _LOGGER.info(
        "Kyber explorer phase 1: %d new integration summaries (%d total)",
        summary_count, len(sorted_platforms),
    )

    # ── Phase 2: Per-entity facts ──────────────────────────────────────────────
    # Which entity_ids already have a per-entity fact at the current version?
    existing_entities: set[str] = {
        entry.get("subject", "")
        for entry in kstore._entries.values()
        if _EXPLORER_VERSION_TAG in (entry.get("tags") or [])
        and entry.get("source") == "entity_explorer"
        and entry.get("subject")
    }

    area_reg = ar.async_get(hass)

    # Collect all entities to process
    all_entities: list[tuple[str, str, str, str | None, str | None, str | None, str | None]] = []
    # (entity_id, name, platform, domain, device_class, unit, area_name)
    for entry in entity_reg.entities.values():
        plat = entry.platform or "unknown"
        if plat in _SKIP_PLATFORMS:
            continue
        eid = entry.entity_id
        if eid in existing_entities:
            continue
        state = hass.states.get(eid)
        attrs = state.attributes if state else {}
        name = attrs.get("friendly_name") or eid
        domain = eid.split(".")[0]
        device_class = attrs.get("device_class") or (entry.device_class if hasattr(entry, "device_class") else None)
        unit = attrs.get("unit_of_measurement") or ""
        state_str = state.state if state else None

        # Resolve area: entity → device → area
        area_id = entry.area_id
        if not area_id and entry.device_id:
            from homeassistant.helpers import device_registry as dr
            dev_reg = dr.async_get(hass)
            dev = dev_reg.async_get(entry.device_id)
            if dev:
                area_id = dev.area_id
        area_obj = area_reg.async_get_area(area_id) if area_id else None
        area_name = area_obj.name if area_obj else None

        all_entities.append((eid, name, plat, domain, device_class or None, unit or None, area_name, state_str))

    total = len(all_entities)
    _set_progress(status="phase2_entities", phase="entities", total=total, done=0, current_platform="")
    _LOGGER.info("Kyber explorer phase 2: %d entities to index", total)

    entity_count = 0
    unsaved = 0
    for row in all_entities:
        eid, name, plat, domain, device_class, unit, area_name, state_str = row
        try:
            content, tags = _entity_fact(eid, name, plat, domain, device_class, unit, area_name, state_str)
            await kstore.async_add(
                "general",
                content,
                subject=eid,
                tags=tags + [_EXPLORER_VERSION_TAG],
                source="entity_explorer",
                confidence=0.85,
                _save=False,
            )
            entity_count += 1
            unsaved += 1
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Entity fact failed for %s: %s", eid, err)

        if entity_count % _YIELD_EVERY == 0:
            _set_progress(done=entity_count, current_platform=domain)
            await asyncio.sleep(0.05)  # yield + slight rate-limit

        if unsaved >= _SAVE_EVERY:
            await kstore.async_force_save()
            unsaved = 0

    # Final save
    if unsaved:
        await kstore.async_force_save()

    _set_progress(
        status="done",
        done=entity_count,
        total=total,
        current_platform="",
        completed_at=int(time.time()),
    )
    _LOGGER.info(
        "Kyber explorer phase 2 complete: %d entity facts stored",
        entity_count,
    )
    return summary_count + entity_count
