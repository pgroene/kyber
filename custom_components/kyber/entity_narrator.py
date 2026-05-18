"""Entity narrator — Phase 3 background knowledge enrichment.

For each 'interesting' entity (cryptic ID, has device_class, has 3+ siblings),
assembles the full device context (manufacturer, model, area, siblings) and asks
the AI to write a rich, grounded description.

Batch strategy (v2):
  All entities are grouped into batches. One AI call generates descriptions for
  the whole batch. The batch size is auto-calculated from average entity context
  size (to stay within the model's context window) and capped by the user-
  configurable CONF_NARRATOR_MAX_BATCH option (default 20).

  Accepted:   entity_id appears verbatim in the returned description → stored
              with confidence=0.9, fully searchable.
  Low-quality: entity_id absent or batch slot empty → stored with
              confidence=0.1 and tag "low_quality"; excluded from search by
              default so re-runs skip them.

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

_NARRATOR_VERSION = 2
_NARRATOR_VERSION_TAG = f"narrator-v{_NARRATOR_VERSION}"

# Imported at module level so tests can stub via sys.modules before load.
from .integration_explorer import EXPLORER_PROGRESS_KEY  # noqa: E402

# Characters of fixed prompt overhead (instructions header + separators).
_INSTRUCTIONS_CHARS = 480
# Estimated chars per description in the AI response.
_RESPONSE_CHARS_PER_ENTITY = 180
# Conservative prompt budget in chars: 8192 tokens × 4 chars/token × 0.75 usable.
_PROMPT_BUDGET_CHARS = int(8192 * 4 * 0.75)
# Hard cap on batch size regardless of budget — beyond this models lose count.
_MAX_RELIABLE_BATCH = 50

# Pause between batch AI calls.
_RATE_LIMIT_SECONDS = 5.0

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


def build_batch_prompt(entity_pairs: list[tuple[str, str]]) -> str:
    """Build a single prompt asking the AI to describe all entities in the batch.

    *entity_pairs* is a list of (entity_id, context_string).
    """
    count = len(entity_pairs)
    blocks = []
    for i, (eid, ctx) in enumerate(entity_pairs, start=1):
        blocks.append(f"--- Entity {i}: {eid} ---\n{ctx}")
    entities_text = "\n\n".join(blocks)

    return (
        "You are building a knowledge base for a Home Assistant smart home.\n"
        f"Write exactly one 1-2 sentence description for EACH of the {count} entities below.\n\n"
        "RULES (apply to every description):\n"
        "- Use ONLY information explicitly stated in each entity's data. No guessing.\n"
        "- Include the entity_id VERBATIM in the description.\n"
        "- Include the area/room name if present.\n"
        "- Include device manufacturer and model if present.\n"
        "- Write in English.\n\n"
        f"Reply with EXACTLY {count} numbered lines and nothing else:\n"
        "1. <description for entity 1>\n"
        "2. <description for entity 2>\n"
        f"... up to {count}.\n\n"
        f"{entities_text}\n\n"
        "Numbered descriptions:"
    )


_NUMBERED_LINE_RE = re.compile(r"^\s*(\d+)\.\s*(.+)", re.MULTILINE)


def parse_batch_response(raw: str, entity_ids: list[str]) -> dict[str, str]:
    """Parse a numbered-list AI response into {entity_id: description}.

    Only entries whose description contains the entity_id verbatim are kept;
    the rest are returned as empty string so callers can mark them low-quality.
    """
    matches = _NUMBERED_LINE_RE.findall(raw)
    result: dict[str, str] = {}
    for num_str, text in matches:
        idx = int(num_str) - 1
        if 0 <= idx < len(entity_ids):
            eid = entity_ids[idx]
            desc = text.strip()
            result[eid] = desc  # caller validates entity_id presence
    return result


def _calc_batch_size(contexts: list[str], max_batch: int) -> int:
    """Calculate batch size from actual entity context sizes.

    Stays within _PROMPT_BUDGET_CHARS and never exceeds min(max_batch, _MAX_RELIABLE_BATCH).
    """
    if not contexts:
        return min(max_batch, 10)
    avg_chars = sum(len(c) for c in contexts) / len(contexts)
    chars_per_entity = avg_chars + _RESPONSE_CHARS_PER_ENTITY
    available = _PROMPT_BUDGET_CHARS - _INSTRUCTIONS_CHARS
    calculated = max(1, int(available / chars_per_entity))
    return min(calculated, max_batch, _MAX_RELIABLE_BATCH)


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
        "accepted": 0,
        "low_quality": 0,
        "errors": 0,
        "batches": 0,
        "parse_failures": 0,
        "batch_size_used": 0,
        "last_run": "",
    }


async def async_narrate_entities(
    hass: "HomeAssistant",
    kstore: "KnowledgeStore",
    entity_reg: Any,
    ai_entity_id: str,
    *,
    max_batch: int = 20,
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

    def _set_progress(done: int, current_name: str = "") -> None:
        existing_prog = hass.data.get(EXPLORER_PROGRESS_KEY) or {}
        hass.data[EXPLORER_PROGRESS_KEY] = {
            **existing_prog,
            "status": "narrator" if done < total else "done",
            "phase": "narrator",
            "narrator_done": done,
            "narrator_total": total,
            "narrator_current": current_name,
            "updated_at": int(time.time()),
        }

    _set_progress(0)

    # Auto-calculate batch size from a sample of the first 20 entity contexts.
    sample_ctxs: list[str] = []
    for row in candidates[:20]:
        eid, state, reg_entry, area_name, manufacturer, model, siblings = row
        attrs = state.attributes if state else {}
        sample_ctxs.append(build_entity_context(
            entity_id=eid,
            name=attrs.get("friendly_name") or eid,
            domain=eid.split(".")[0],
            device_class=attrs.get("device_class") or (
                reg_entry.device_class if hasattr(reg_entry, "device_class") else None
            ),
            unit=attrs.get("unit_of_measurement") or None,
            area_name=area_name,
            state_str=state.state if state else None,
            attributes=dict(attrs),
            manufacturer=manufacturer,
            model=model,
            siblings=siblings,
        ))
    batch_size = _calc_batch_size(sample_ctxs, max_batch)
    stats["batch_size_used"] = batch_size
    _LOGGER.info(
        "Kyber narrator: batch_size=%d (max_batch=%d, avg_ctx=%.0f chars)",
        batch_size, max_batch,
        sum(len(c) for c in sample_ctxs) / max(len(sample_ctxs), 1),
    )

    done_count = 0
    for batch_start in range(0, total, batch_size):
        batch = candidates[batch_start: batch_start + batch_size]

        # Build contexts for every entity in this batch.
        batch_rows: list[tuple[str, str, str, str | None, str | None, str | None, str]] = []
        for row in batch:
            eid, state, reg_entry, area_name, manufacturer, model, siblings = row
            attrs = state.attributes if state else {}
            name = attrs.get("friendly_name") or eid
            domain = eid.split(".")[0]
            device_class = (
                attrs.get("device_class")
                or (reg_entry.device_class if hasattr(reg_entry, "device_class") else None)
            )
            entity_ctx = build_entity_context(
                entity_id=eid,
                name=name,
                domain=domain,
                device_class=device_class or None,
                unit=attrs.get("unit_of_measurement") or None,
                area_name=area_name,
                state_str=state.state if state else None,
                attributes=dict(attrs),
                manufacturer=manufacturer,
                model=model,
                siblings=siblings,
            )
            batch_rows.append((eid, name, domain, device_class, area_name, manufacturer, entity_ctx))

        entity_ids = [r[0] for r in batch_rows]
        first_name = batch_rows[0][1] if batch_rows else ""
        _set_progress(done_count, first_name)

        stats["total"] += len(batch)
        stats["batches"] += 1

        # Single AI call for the whole batch.
        descriptions: dict[str, str] = {}
        ai_failed = False
        try:
            prompt = build_batch_prompt([(r[0], r[6]) for r in batch_rows])
            raw = await _run_ai(hass, ai_entity_id, prompt)
            descriptions = parse_batch_response(raw, entity_ids)
            parsed_count = sum(1 for eid in entity_ids if eid in descriptions and eid in descriptions[eid])
            if parsed_count < len(batch) // 2:
                stats["parse_failures"] += 1
                _LOGGER.warning(
                    "Kyber narrator: batch parse failure — got %d/%d valid descriptions",
                    parsed_count, len(batch),
                )
        except Exception as err:  # noqa: BLE001
            ai_failed = True
            stats["errors"] += len(batch)
            _LOGGER.warning("Kyber narrator: batch AI error: %s", err)

        # Store results — accepted or low-quality marker.
        # Skip entirely on AI error (temporary failure — entity will be retried next run).
        if not ai_failed:
            for eid, name, domain, device_class, area_name, manufacturer, _ in batch_rows:
                description = descriptions.get(eid, "")
                if description and eid in description:
                    stats["accepted"] += 1
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
                        _LOGGER.warning("Kyber narrator: store failed for %s: %s", eid, store_err)
                else:
                    # Mark as low-quality so re-runs skip it and search ignores it.
                    stats["low_quality"] += 1
                    try:
                        await kstore.async_add(
                            "general",
                            f"{eid} — narrator could not generate a verified description.",
                            subject=eid,
                            tags=[eid, domain, _NARRATOR_VERSION_TAG, "low_quality"],
                            source="entity_narrator",
                            confidence=0.1,
                            provenance=f"AI narrator v{_NARRATOR_VERSION} (low quality)",
                            _save=False,
                        )
                    except Exception as store_err:  # noqa: BLE001
                        _LOGGER.warning("Kyber narrator: store failed (lq) for %s: %s", eid, store_err)

        done_count += len(batch)
        _set_progress(done_count, first_name)
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
        f"total={stats['total']}, accepted={stats['accepted']}, "
        f"low_quality={stats['low_quality']}, errors={stats['errors']}, "
        f"batches={stats['batches']}, parse_failures={stats['parse_failures']}, "
        f"batch_size_used={stats['batch_size_used']}, "
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
        "Kyber narrator complete: %d total in %d batches (size=%d), "
        "%d accepted, %d low-quality, %d parse failures, %d errors",
        stats["total"], stats["batches"], stats["batch_size_used"],
        stats["accepted"], stats["low_quality"],
        stats["parse_failures"], stats["errors"],
    )
    return stats
