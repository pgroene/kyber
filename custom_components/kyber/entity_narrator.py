"""Entity narrator — Phase 3 background knowledge enrichment.

For each 'interesting' entity (cryptic ID, has device_class, has 3+ siblings),
assembles the full device context (manufacturer, model, area, siblings) and asks
the AI to write a rich, grounded description.

Two-pass verification:
  1. Generate description from entity context.
  2. Verify: AI self-checks for hallucinations with a yes/no question.

Up to _MAX_ATTEMPTS=3 generate+verify cycles per entity.  On exhaustion, the
entity is skipped (the Phase 2 template fact from integration_explorer remains).

Stats are tracked in hass.data[NARRATOR_STATS_KEY] and persisted to the
knowledge store so the debug panel can display them across restarts.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import TYPE_CHECKING, Any

from homeassistant.helpers import area_registry as ar, device_registry as dr

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from .knowledge import KnowledgeStore

_LOGGER = logging.getLogger(__name__)

NARRATOR_STATS_KEY = "kyber_narrator_stats"

_NARRATOR_VERSION = 1
_NARRATOR_VERSION_TAG = f"narrator-v{_NARRATOR_VERSION}"

# Imported at module level so tests can stub via sys.modules before load.
from .integration_explorer import EXPLORER_PROGRESS_KEY  # noqa: E402

# Maximum generate+verify cycles before falling back to template.
_MAX_ATTEMPTS = 3

# Pause between entities to avoid overwhelming the AI task entity.
_RATE_LIMIT_SECONDS = 3.0

# Attributes that are HA-internal noise — omit from context.
_SKIP_ATTRS: frozenset[str] = frozenset({
    "friendly_name", "unit_of_measurement", "device_class", "icon",
    "entity_picture", "attribution", "supported_features", "assumed_state",
    "restored", "supported_color_modes", "color_mode", "min_mireds",
    "max_mireds", "effect_list", "color_temp_kelvin",
    "min_color_temp_kelvin", "max_color_temp_kelvin",
})

# Regex matching opaque hex/numeric segments common in Zigbee/Z-Wave entity IDs.
_CRYPTIC_RE = re.compile(
    r"(0x[0-9a-f]{6,}|_[0-9a-f]{8,}|_[0-9]{10,})",
    re.IGNORECASE,
)


def _is_cryptic(entity_id: str) -> bool:
    """Return True if the entity_id contains hex/numeric opaque segments."""
    return bool(_CRYPTIC_RE.search(entity_id))


def is_interesting(
    entity_id: str,
    device_class: str | None,
    sibling_count: int,
) -> bool:
    """Return True if this entity qualifies for AI narration.

    Exported (no leading underscore) so tests can call it directly.
    """
    if device_class:
        return True
    if _is_cryptic(entity_id):
        return True
    if sibling_count >= 3:
        return True
    return False


def build_entity_context(
    entity_id: str,
    name: str,
    domain: str,
    device_class: str | None,
    unit: str | None,
    area_name: str | None,
    state_str: str | None,
    attributes: dict[str, Any],
    manufacturer: str | None,
    model: str | None,
    siblings: list[tuple[str, str]],
) -> str:
    """Build a structured context string from all available data sources.

    Exported so tests can inspect the output without mocking HA.
    """
    lines: list[str] = []
    lines.append(f"entity_id: {entity_id}")
    lines.append(f"friendly_name: {name}")
    lines.append(f"domain: {domain}")
    if device_class:
        lines.append(f"device_class: {device_class}")
    if unit:
        lines.append(f"unit_of_measurement: {unit}")
    if area_name:
        lines.append(f"area: {area_name}")
    if state_str and state_str not in ("unavailable", "unknown"):
        lines.append(f"current_state: {state_str}")
    for k, v in sorted(attributes.items()):
        if k in _SKIP_ATTRS or k.startswith("_"):
            continue
        sv = str(v)
        if len(sv) < 120:
            lines.append(f"attribute.{k}: {sv}")
    if manufacturer:
        lines.append(f"device_manufacturer: {manufacturer}")
    if model:
        lines.append(f"device_model: {model}")
    if siblings:
        sibling_strs = [f"{eid} ({sname})" for eid, sname in siblings[:8]]
        lines.append(f"sibling_entities: {', '.join(sibling_strs)}")
    return "\n".join(lines)


def build_generation_prompt(entity_context: str) -> str:
    """Return the prompt used to generate a rich description."""
    return (
        "You are building a knowledge base for a Home Assistant smart home.\n"
        "Write a 1-3 sentence description for the entity below. "
        "The description will be used to search and find this entity.\n\n"
        "STRICT RULES:\n"
        "- ONLY use information explicitly present in the data below. No guessing.\n"
        "- Include the entity_id VERBATIM in your description.\n"
        "- Include the area/room name if present.\n"
        "- Include the device manufacturer and model if present.\n"
        "- Include sibling entity_ids only if they add useful context.\n"
        "- Do NOT invent any details not stated in the data.\n"
        "- Write in English.\n\n"
        f"--- Entity data ---\n{entity_context}\n--- End ---\n\n"
        "Description:"
    )


def build_verification_prompt(entity_context: str, description: str) -> str:
    """Return the yes/no hallucination-check prompt."""
    return (
        "I need to verify that a description contains only information from its source data.\n\n"
        f"--- Source data ---\n{entity_context}\n--- End source data ---\n\n"
        f"--- Description to verify ---\n{description}\n--- End description ---\n\n"
        "Does the description contain ANY information that is NOT present in the source data? "
        "Answer ONLY with a single word: 'yes' or 'no'.\n"
        "Answer:"
    )


def is_hallucinated(answer: str) -> bool:
    """Parse a yes/no verification answer.

    Unknown/unclear answers are treated as hallucinated (safe fallback).
    Exported for tests.
    """
    cleaned = answer.strip().lower()[:20]
    if cleaned.startswith("no"):
        return False
    if cleaned.startswith("yes"):
        return True
    return True  # conservative


async def _run_ai(hass: "HomeAssistant", ai_entity_id: str, prompt: str) -> str:
    from homeassistant.components.ai_task import async_generate_data  # type: ignore[import]
    result = await async_generate_data(
        hass,
        task_name="kyber_narrator",
        entity_id=ai_entity_id,
        instructions=prompt,
    )
    return result.data if isinstance(result.data, str) else str(result.data)


def _init_stats() -> dict[str, Any]:
    return {
        "total": 0,
        "accepted_first": 0,
        "accepted_retry": 0,
        "rejected": 0,
        "errors": 0,
        "last_run": "",
    }


async def async_narrate_entities(
    hass: "HomeAssistant",
    kstore: "KnowledgeStore",
    entity_reg: Any,
    ai_entity_id: str,
) -> dict[str, Any]:
    """Phase 3: AI-generated descriptions for interesting entities.

    Returns the stats dict for this run.
    """
    stats = _init_stats()
    stats["last_run"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    hass.data[NARRATOR_STATS_KEY] = stats

    await kstore.async_load()

    # Which entity_ids already have narrator entries at this version?
    existing: set[str] = {
        entry.get("subject", "")
        for entry in kstore._entries.values()
        if _NARRATOR_VERSION_TAG in (entry.get("tags") or [])
        and entry.get("source") == "entity_narrator"
        and entry.get("subject")
    }

    area_reg = ar.async_get(hass)
    device_reg = dr.async_get(hass)

    # Group entity registry entries by device_id for sibling lookup.
    by_device: dict[str, list[Any]] = {}
    for reg_entry in entity_reg.entities.values():
        if reg_entry.device_id:
            by_device.setdefault(reg_entry.device_id, []).append(reg_entry)

    # Collect candidates.
    candidates: list[tuple[Any, ...]] = []
    for reg_entry in entity_reg.entities.values():
        eid = reg_entry.entity_id
        if eid in existing:
            continue
        state = hass.states.get(eid)
        attrs = state.attributes if state else {}
        device_class = (
            attrs.get("device_class")
            or (reg_entry.device_class if hasattr(reg_entry, "device_class") else None)
        )
        siblings_raw: list[Any] = []
        if reg_entry.device_id:
            siblings_raw = [
                e for e in by_device.get(reg_entry.device_id, [])
                if e.entity_id != eid
            ]
        if not is_interesting(eid, device_class, len(siblings_raw)):
            continue

        # Resolve area: entity → device → area.
        area_id = reg_entry.area_id
        if not area_id and reg_entry.device_id:
            dev = device_reg.async_get(reg_entry.device_id)
            if dev:
                area_id = dev.area_id
        area_obj = area_reg.async_get_area(area_id) if area_id else None
        area_name = area_obj.name if area_obj else None

        # Device info.
        manufacturer = model = None
        if reg_entry.device_id:
            dev = device_reg.async_get(reg_entry.device_id)
            if dev:
                manufacturer = dev.manufacturer
                model = dev.model

        # Sibling names.
        siblings: list[tuple[str, str]] = []
        for sib in siblings_raw[:8]:
            sib_state = hass.states.get(sib.entity_id)
            sib_name = (
                (sib_state.attributes.get("friendly_name") if sib_state else None)
                or sib.entity_id
            )
            siblings.append((sib.entity_id, sib_name))

        candidates.append((eid, state, reg_entry, area_name, manufacturer, model, siblings))

    total = len(candidates)
    _LOGGER.info("Kyber narrator: %d entities to narrate", total)

    def _set_progress(done: int) -> None:
        existing_prog = hass.data.get(EXPLORER_PROGRESS_KEY) or {}
        hass.data[EXPLORER_PROGRESS_KEY] = {
            **existing_prog,
            "status": "narrator" if done < total else "done",
            "phase": "narrator",
            "narrator_done": done,
            "narrator_total": total,
            "updated_at": int(time.time()),
        }

    _set_progress(0)

    done_count = 0
    for row in candidates:
        eid, state, reg_entry, area_name, manufacturer, model, siblings = row
        attrs = state.attributes if state else {}
        name = attrs.get("friendly_name") or eid
        domain = eid.split(".")[0]
        device_class = (
            attrs.get("device_class")
            or (reg_entry.device_class if hasattr(reg_entry, "device_class") else None)
        )
        unit = attrs.get("unit_of_measurement") or None
        state_str = state.state if state else None

        entity_ctx = build_entity_context(
            entity_id=eid,
            name=name,
            domain=domain,
            device_class=device_class or None,
            unit=unit,
            area_name=area_name,
            state_str=state_str,
            attributes=dict(attrs),
            manufacturer=manufacturer,
            model=model,
            siblings=siblings,
        )

        accepted = False
        description: str | None = None
        stats["total"] += 1

        try:
            for attempt in range(_MAX_ATTEMPTS):
                # Generate description.
                try:
                    gen_prompt = build_generation_prompt(entity_ctx)
                    raw = await _run_ai(hass, ai_entity_id, gen_prompt)
                    description = raw.strip()
                except Exception as gen_err:  # noqa: BLE001
                    _LOGGER.debug(
                        "Kyber narrator: generation failed for %s (attempt %d): %s",
                        eid, attempt + 1, gen_err,
                    )
                    stats["errors"] += 1
                    break

                # Basic validation: entity_id must appear verbatim.
                if eid not in description:
                    _LOGGER.debug(
                        "Kyber narrator: entity_id missing from description for %s (attempt %d)",
                        eid, attempt + 1,
                    )
                    continue

                # Self-verification: hallucination check.
                try:
                    verify_prompt = build_verification_prompt(entity_ctx, description)
                    verify_raw = await _run_ai(hass, ai_entity_id, verify_prompt)
                    hallucinated = is_hallucinated(verify_raw)
                except Exception as ver_err:  # noqa: BLE001
                    _LOGGER.debug(
                        "Kyber narrator: verification failed for %s (attempt %d): %s",
                        eid, attempt + 1, ver_err,
                    )
                    hallucinated = True  # conservative

                if not hallucinated:
                    accepted = True
                    if attempt == 0:
                        stats["accepted_first"] += 1
                    else:
                        stats["accepted_retry"] += 1
                    break
                # else: loop → retry up to _MAX_ATTEMPTS
        except Exception as outer_err:  # noqa: BLE001
            _LOGGER.warning("Kyber narrator: unexpected error for %s: %s", eid, outer_err)
            stats["errors"] += 1

        if not accepted:
            stats["rejected"] += 1

        if accepted and description:
            tags = [eid, domain, _NARRATOR_VERSION_TAG]
            if device_class:
                tags.append(device_class)
            if area_name:
                tags.append(area_name.lower())
            if manufacturer:
                tags.append(manufacturer.lower())
            try:
                await kstore.async_add(
                    "general",
                    description,
                    subject=eid,
                    tags=tags,
                    source="entity_narrator",
                    confidence=0.9,
                    provenance=f"AI narrator v{_NARRATOR_VERSION}",
                    _save=False,
                )
            except Exception as store_err:  # noqa: BLE001
                _LOGGER.warning(
                    "Kyber narrator: failed to store fact for %s: %s", eid, store_err,
                )

        done_count += 1
        _set_progress(done_count)
        hass.data[NARRATOR_STATS_KEY] = dict(stats)

        await asyncio.sleep(_RATE_LIMIT_SECONDS)

    # Final bulk save.
    try:
        await kstore.async_force_save()
    except Exception as save_err:  # noqa: BLE001
        _LOGGER.warning("Kyber narrator: final save failed: %s", save_err)

    # Persist stats to knowledge store for cross-restart visibility.
    stats_content = (
        f"Kyber narrator v{_NARRATOR_VERSION} stats: "
        f"total={stats['total']}, "
        f"accepted_first={stats['accepted_first']}, "
        f"accepted_retry={stats['accepted_retry']}, "
        f"rejected={stats['rejected']}, "
        f"errors={stats['errors']}, "
        f"last_run={stats['last_run']}"
    )
    try:
        old_stats = [
            eid for eid, e in kstore._entries.items()
            if e.get("source") == "narrator_stats"
        ]
        for old_id in old_stats:
            await kstore.async_delete(old_id)
        await kstore.async_add(
            "general",
            stats_content,
            subject="_narrator_stats",
            tags=["narrator_stats", _NARRATOR_VERSION_TAG],
            source="narrator_stats",
            confidence=1.0,
        )
    except Exception as stats_err:  # noqa: BLE001
        _LOGGER.warning("Kyber narrator: stats persistence failed: %s", stats_err)

    _set_progress(done_count)
    _LOGGER.info(
        "Kyber narrator complete: %d total, %d accepted (first=%d, retry=%d), "
        "%d rejected, %d errors",
        stats["total"],
        stats["accepted_first"] + stats["accepted_retry"],
        stats["accepted_first"],
        stats["accepted_retry"],
        stats["rejected"],
        stats["errors"],
    )
    return stats
