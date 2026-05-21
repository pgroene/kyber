"""Deep AI-driven analyzer for automations / scripts / blueprints.

Pipeline (per item):
  1. Read raw config (via `source.read_automations` etc.) — yields a content hash.
  2. Compare hash against `AnalysisMemo`. If unchanged → SKIP.
  3. Call the configured AI task entity with a focused prompt asking for
     NON-OBVIOUS, durable facts about the home that this automation/script
     implies.
  4. Parse a JSON array of fact proposals. Filter by confidence threshold.
  5. Persist each accepted fact via `KnowledgeStore.async_add` (so it
     becomes searchable / TF-IDF indexable).
  6. Record the fact IDs + new hash in the memo so we don't re-analyze.

The whole thing is rate-limited per run (`limit` items) so a single sweep
can't pin the model. The endpoint is invoked manually from the Debug
tab; we do NOT run this on startup.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import CONF_AI_TASK_ENTITY_ID
from .integration_explorer import EXPLORER_PROGRESS_KEY
from .source import (
    AnalysisMemo,
    get_memo,
    read_automations,
    read_blueprints,
    read_scripts,
)

_LOGGER = logging.getLogger(__name__)

_MIN_CONFIDENCE = 0.65
_MAX_FACTS_PER_ITEM = 6

# Shared flag: http_api.py sets this True while a user chat request is active.
_CHAT_BUSY_KEY = "kyber_chat_busy"
# asyncio.Event key: fired when chat starts so analyzers can cancel mid-flight.
_PREEMPT_EVENT_KEY = "kyber_preempt_event"
# Flag: set True while deep analyzer is calling the AI so chat can wait.
_DEEP_AI_BUSY_KEY = "kyber_deep_learning_ai_busy"
# Per-item AI call timeout — prevents a single item from blocking Ollama forever.
# Set generously for slow hardware (e.g. Orange Pi running local models).
_AI_CALL_TIMEOUT = 300  # seconds

# Exponential backoff after being preempted by chat (seconds).
# Resets to index 0 after any successful item without preemption.
_CHAT_BACKOFF_SECONDS = [10, 20, 40, 80, 160, 300]

# Hard cap on raw config sent to AI (chars). Beyond this we truncate.
_MAX_CONFIG_CHARS = 6000


class _ChatPreemptError(Exception):
    """Raised when a chat request cancels an in-flight analyzer task."""

# Different analytical lenses — each pass uses a different angle so multiple
# passes over the same automations produce complementary (non-duplicate) facts.
_PROMPT_LENSES: list[dict[str, str]] = [
    {
        "title": "daily routines & schedules",
        "ask": (
            "Focus on DAILY ROUTINES and SCHEDULES implied by this item. "
            "Examples: 'The household wakes before sunrise on weekdays', "
            "'Lights turn off at 23:00 in the living room', "
            "'Heating is lowered automatically at night'."
        ),
    },
    {
        "title": "devices & entity inventory",
        "ask": (
            "Focus on DEVICES and ENTITIES this item reveals exist in the home. "
            "Examples: 'There is a motion sensor in the hallway', "
            "'The garage has a tilt sensor on the door', "
            "'A presence sensor is installed in the office'."
        ),
    },
    {
        "title": "occupancy & people",
        "ask": (
            "Focus on who LIVES or WORKS in the home and their BEHAVIOURAL PATTERNS. "
            "Examples: 'Someone works from home during daytime', "
            "'The household has at least one person with a morning routine', "
            "'Occupants are typically active between 07:00 and 23:00'."
        ),
    },
    {
        "title": "time & location patterns",
        "ask": (
            "Focus on SPECIFIC TIMES, DAYS, or LOCATION TRIGGERS used by this item. "
            "Examples: 'The front door light activates after sunset', "
            "'This automation only runs on weekdays', "
            "'Area-based presence detection is used in the bedroom'."
        ),
    },
    {
        "title": "energy & efficiency",
        "ask": (
            "Focus on ENERGY USE, ECO behaviour, or EFFICIENCY patterns. "
            "Examples: 'The heating is programmed to lower when no one is home', "
            "'Standby power is cut to the TV when the room is empty', "
            "'Solar or battery state influences device control'."
        ),
    },
    {
        "title": "safety & security",
        "ask": (
            "Focus on SAFETY, SECURITY, or ALERT behaviours. "
            "Examples: 'A smoke detector triggers a full-house alert', "
            "'Exterior lights flash when the alarm is armed', "
            "'Locks are checked automatically at 22:00'."
        ),
    },
    {
        "title": "entity relationships & dependencies",
        "ask": (
            "Focus on HOW ENTITIES RELATE TO EACH OTHER and WHY they work together. "
            "Describe the semantic relationship: which entity triggers or controls which, "
            "what dependency exists, and what the pairing means for the home. "
            "Examples: "
            "'Motion sensor in hallway (binary_sensor.hallway_motion) controls hallway lights — "
            "turning lights on when someone enters and off after 5 minutes of no motion', "
            "'Solar inverter output (sensor.solar_power) controls hot water boiler "
            "(switch.boiler) — boiler runs when solar production exceeds household consumption', "
            "'Dishwasher completion sensor triggers a mobile notification to the owner'. "
            "Name the actual entity_ids where visible in the config."
        ),
    },
    {
        "title": "automation purpose & use case",
        "ask": (
            "Focus on the HIGH-LEVEL PURPOSE and USE CASE of this automation. "
            "Describe in one or two sentences what problem it solves or what convenience "
            "it provides, as if explaining to someone who has never seen the home. "
            "Examples: "
            "'This automation saves energy by cutting power to the TV and standby devices "
            "when the living room has been empty for 30 minutes', "
            "'This script lets occupants set a custom wake-up time that adjusts the heating "
            "and bedroom lights to ease the morning routine', "
            "'This automation protects the home by locking all doors and arming the alarm "
            "when the last person leaves'. "
            "Be specific about entities and areas where the config reveals them."
        ),
    },
]


# ── Public types ─────────────────────────────────────────────────────
def _truncate(text: str, limit: int = _MAX_CONFIG_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… [truncated {len(text) - limit} chars]"


def _extract_entity_ids(cfg: Any) -> list[str]:
    """Walk a config structure and extract all entity_id references."""
    found: list[str] = []
    if isinstance(cfg, dict):
        for k, v in cfg.items():
            if k in ("entity_id", "entity_ids"):
                if isinstance(v, str):
                    found.append(v)
                elif isinstance(v, list):
                    found.extend(x for x in v if isinstance(x, str))
            else:
                found.extend(_extract_entity_ids(v))
    elif isinstance(cfg, list):
        for item in cfg:
            found.extend(_extract_entity_ids(item))
    return found


def _build_prompt(
    kind: str,
    item: dict[str, Any],
    prompt_variant: int = 0,
    entity_names: dict[str, str] | None = None,
    entity_areas: dict[str, str] | None = None,
    entity_devices: dict[str, tuple[str | None, str | None]] | None = None,
) -> str:
    """Build a focused prompt that asks the AI for durable facts.

    ``prompt_variant`` selects one of the analytical lenses in ``_PROMPT_LENSES``
    so that multiple passes over the same automations produce complementary facts.
    ``entity_names`` maps entity_id → friendly_name for context enrichment.
    ``entity_areas`` maps entity_id → area name (e.g. "badkamer") for room context.
    ``entity_devices`` maps entity_id → (manufacturer, model) from device registry.
    """
    if kind == "automation":
        ident = item.get("alias") or item.get("id") or "unnamed"
        body = {
            "alias": item.get("alias"),
            "description": item.get("description"),
            "mode": item.get("mode"),
            "trigger": item.get("trigger"),
            "condition": item.get("condition"),
            "action": item.get("action"),
        }
    elif kind == "script":
        ident = item.get("alias") or item.get("id") or "unnamed"
        body = {
            "alias": item.get("alias"),
            "description": item.get("description"),
            "mode": item.get("mode"),
            "fields": item.get("fields"),
            "sequence": item.get("sequence"),
        }
    else:  # blueprint
        ident = item.get("name") or item.get("path") or "unnamed"
        body = {
            "name": item.get("name"),
            "description": item.get("description"),
            "domain": item.get("domain"),
            "input_keys": item.get("input_keys"),
        }

    lens = _PROMPT_LENSES[prompt_variant % len(_PROMPT_LENSES)]
    body_yaml = json.dumps(body, indent=2, ensure_ascii=False, default=str)
    body_yaml = _truncate(body_yaml)

    # Build entity name + area + device context so the AI knows what entity_ids mean
    entity_context = ""
    if entity_names or entity_areas or entity_devices:
        entity_ids_in_config = list(dict.fromkeys(_extract_entity_ids(body)))
        resolved = []
        for eid in entity_ids_in_config:
            parts = []
            if entity_names and eid in entity_names:
                parts.append(f'"{entity_names[eid]}"')
            if entity_areas and eid in entity_areas:
                parts.append(f"area: {entity_areas[eid]}")
            if entity_devices and eid in entity_devices:
                mfr, mdl = entity_devices[eid]
                if mfr or mdl:
                    device_info = " ".join(p for p in (mfr, mdl) if p)
                    parts.append(f"device: {device_info}")
            if parts:
                resolved.append(f"  {eid} → {', '.join(parts)}")
        if resolved:
            entity_context = (
                "\n--- entity context (use these specific room/area names in your facts) ---\n"
                + "\n".join(resolved)
                + "\n--- end entity context ---\n"
            )

    return (
        f"You are reviewing a Home Assistant {kind} called '{ident}'.\n"
        f"{lens['ask']}\n"
        "Infer DURABLE, NON-OBVIOUS facts — output ONLY facts relevant to this lens. "
        "Skip generic observations ('there is an automation', 'it uses a trigger').\n"
        "IMPORTANT: ALWAYS name the specific room/area. "
        "NEVER write 'the room' or 'the area' — use the exact area name from the entity context or entity_id segments.\n"
        "IMPORTANT: Where entity_ids are visible in the config, include them in the content "
        "(e.g. 'light.living_room' or 'switch.onoff4_kamer_l3'). This makes facts searchable.\n"
        "IMPORTANT: Add all relevant entity_ids from the config to the 'tags' array.\n\n"
        "Output ONLY a JSON array. Each item: {\"category\": str, "
        "\"subject\": str, \"content\": str, \"tags\": [str], "
        "\"confidence\": float 0-1}. If nothing relevant, output [].\n\n"
        f"--- {kind} config ---\n{body_yaml}\n--- end ---\n"
        f"{entity_context}\n"
        "JSON array:"
    )


_JSON_ARRAY_RE = re.compile(r"\[[\s\S]*\]")
_ENTITY_ID_RE = re.compile(r"\b[a-z_]+\.[a-z0-9_]+\b")
_MIN_CONTENT_LENGTH = 40


def _parse_facts(raw: str, config_entity_ids: list[str] | None = None) -> list[dict[str, Any]]:
    """Parse the AI response into a list of fact dicts. Tolerant.

    ``config_entity_ids`` — entity_ids extracted from the automation/script config.
    They are merged into every fact's tags so retrieval by entity_id always works,
    even when the AI omits them from the content text.
    """
    if not raw:
        return []
    raw = raw.strip()
    # Strip code fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    match = _JSON_ARRAY_RE.search(raw)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for f in data[:_MAX_FACTS_PER_ITEM]:
        if not isinstance(f, dict):
            continue
        content = str(f.get("content") or "").strip()
        if not content or len(content) < _MIN_CONTENT_LENGTH:
            continue
        try:
            conf = float(f.get("confidence", 0.5))
        except (TypeError, ValueError):
            conf = 0.5
        tags = f.get("tags") or []
        if not isinstance(tags, list):
            tags = []
        tags = [str(t) for t in tags]
        # Always include entity_ids from config so lookup-by-entity works
        if config_entity_ids:
            for eid in config_entity_ids:
                if eid not in tags:
                    tags.append(eid)
        # Also extract any entity_ids the AI embedded in the content text
        for eid in _ENTITY_ID_RE.findall(content):
            if "." in eid and eid not in tags:
                tags.append(eid)
        out.append({
            "category": str(f.get("category") or "general").strip() or "general",
            "subject": str(f.get("subject") or "").strip(),
            "content": content,
            "tags": tags,
            "confidence": max(0.0, min(1.0, conf)),
        })
    return out


async def _run_ai(hass: HomeAssistant, ai_entity_id: str, prompt: str) -> str:
    """Call the AI, cancelling immediately if chat preempts us."""
    try:
        from .api_utilities import async_ai_call  # type: ignore
    except Exception as err:  # noqa: BLE001
        raise HomeAssistantError(f"ai_task not available: {err}")

    preempt_event: asyncio.Event | None = hass.data.get(_PREEMPT_EVENT_KEY)

    hass.data[_DEEP_AI_BUSY_KEY] = True
    ai_task: asyncio.Task = asyncio.ensure_future(
        async_ai_call(
            hass,
            task_name="kyber_deep_analyze",
            entity_id=ai_entity_id,
            instructions=prompt,
        )
    )
    # Also watch the preempt event so we can cancel mid-flight instantly.
    preempt_task: asyncio.Task | None = (
        asyncio.ensure_future(preempt_event.wait()) if preempt_event else None
    )
    try:
        watch: set = {ai_task}
        if preempt_task:
            watch.add(preempt_task)
        done, pending = await asyncio.wait(
            watch,
            timeout=_AI_CALL_TIMEOUT,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
        if preempt_task is not None and preempt_task in done:
            # Chat started — cancel AI call and raise so caller can backoff.
            ai_task.cancel()
            raise _ChatPreemptError()
        if ai_task not in done:
            raise asyncio.TimeoutError()
        result = ai_task.result()  # re-raises if AI call itself failed
        return result.data if isinstance(result.data, str) else str(result.data)
    finally:
        hass.data[_DEEP_AI_BUSY_KEY] = False
        if preempt_task and not preempt_task.done():
            preempt_task.cancel()


def _identity(kind: str, item: dict[str, Any]) -> str:
    if kind == "blueprint":
        return str(item.get("path") or item.get("name") or "")
    return str(item.get("id") or item.get("alias") or "")


_DEDUP_SIMILARITY_THRESHOLD = 0.82


async def _is_duplicate_fact(kstore: Any, content: str) -> bool:
    """Return True if a near-identical fact from deep-analyzer already exists."""
    try:
        similar = await kstore.async_semantic_search(content, limit=5, min_score=_DEDUP_SIMILARITY_THRESHOLD)
        return any(e.get("source") == "deep-analyzer" for e in similar)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Kyber deep-analyzer: dedup check failed (treating as non-duplicate): %s", err)
        return False


async def analyze_pending(
    hass: HomeAssistant,
    *,
    ai_entity_id: str,
    kinds: list[str] | None = None,
    limit: int = 5,
    force: bool = False,
    prompt_variant: int = 0,
) -> dict[str, Any]:
    """Walk all configured items; analyze ones whose hash changed (up to `limit`).

    Returns:
        {analyzed: [{kind, ident, facts, fact_ids}], skipped: N, errors: [...]}.
    """
    kinds = kinds or ["automation", "script", "blueprint"]
    memo: AnalysisMemo = get_memo(hass)
    try:
        await memo.async_load()
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Kyber deep_analyzer: memo load failed: %s", err)

    # Lazy import to avoid circular dep
    from .knowledge import get_store as get_knowledge_store
    kstore = get_knowledge_store(hass)
    try:
        if not kstore._loaded:
            await kstore.async_load()
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Kyber deep_analyzer: knowledge store load failed: %s", err)

    # Gather candidates
    candidates: list[tuple[str, dict[str, Any]]] = []
    if "automation" in kinds:
        try:
            for it in await hass.async_add_executor_job(read_automations, hass):
                candidates.append(("automation", it))
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Kyber deep_analyzer: read_automations failed: %s", err)
    if "script" in kinds:
        try:
            for it in await hass.async_add_executor_job(read_scripts, hass):
                candidates.append(("script", it))
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Kyber deep_analyzer: read_scripts failed: %s", err)
    if "blueprint" in kinds:
        try:
            for it in await hass.async_add_executor_job(read_blueprints, hass):
                candidates.append(("blueprint", it))
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Kyber deep_analyzer: read_blueprints failed: %s", err)

    # Build entity_id → friendly_name, area_name, and (manufacturer, model) lookups once.
    entity_names: dict[str, str] = {}
    entity_areas: dict[str, str] = {}
    entity_devices: dict[str, tuple[str | None, str | None]] = {}
    from homeassistant.helpers import entity_registry as er, area_registry as areg, device_registry as dr
    entity_reg = er.async_get(hass)
    area_reg = areg.async_get(hass)
    device_reg = dr.async_get(hass)
    for state in hass.states.async_all():
        friendly = state.attributes.get("friendly_name")
        if friendly:
            entity_names[state.entity_id] = friendly
        # Resolve area: entity-level first, then device-level
        reg_entry = entity_reg.async_get(state.entity_id)
        area_id = reg_entry.area_id if reg_entry else None
        if not area_id and reg_entry and reg_entry.device_id:
            dev = device_reg.async_get(reg_entry.device_id)
            area_id = dev.area_id if dev else None
        if area_id:
            area = area_reg.async_get_area(area_id)
            if area:
                entity_areas[state.entity_id] = area.name
        # Device manufacturer + model
        if reg_entry and reg_entry.device_id:
            dev = device_reg.async_get(reg_entry.device_id)
            if dev:
                entity_devices[state.entity_id] = (dev.manufacturer, dev.model)

    # Build a set of all known entity_ids for fact validation.
    all_entity_ids: set[str] = {
        state.entity_id for state in hass.states.async_all()
    }

    analyzed: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    skipped = 0
    processed = 0

    # Count how many items are pending (will actually be analyzed).
    pending_count = sum(
        1 for kind, item in candidates
        if _identity(kind, item)
        and (force or get_memo(hass).is_pending_lens(kind, _identity(kind, item), item.get("hash") or "", prompt_variant))
    )
    pending_count = min(pending_count, limit)

    def _set_deep_progress(done: int, current: str = "", paused: bool = False) -> None:
        existing = hass.data.get(EXPLORER_PROGRESS_KEY) or {}
        status = "paused_chat" if paused else ("deep_learning" if done < pending_count else existing.get("status", "done"))
        hass.data[EXPLORER_PROGRESS_KEY] = {
            **existing,
            "status": status,
            "phase": "deep_learning",
            "deep_done": done,
            "deep_total": pending_count,
            "deep_current": current,
            "updated_at": int(time.time()),
        }

    if pending_count > 0:
        _set_deep_progress(0)

    _chat_preempt_count = 0  # tracks consecutive preemptions for backoff

    for kind, item in candidates:
        ident = _identity(kind, item)
        if not ident:
            continue
        new_hash = item.get("hash") or ""
        if not force and not memo.is_pending_lens(kind, ident, new_hash, prompt_variant):
            skipped += 1
            continue
        if processed >= limit:
            # Reached this run's budget — leave for next sweep.
            break
        processed += 1

        try:
            # Check preemption before each item (catches chat that started between items).
            if hass.data.get(_CHAT_BUSY_KEY):
                raise _ChatPreemptError()

            _set_deep_progress(processed - 1, ident)

            prompt = _build_prompt(kind, item, prompt_variant, entity_names=entity_names, entity_areas=entity_areas, entity_devices=entity_devices)
            raw = await _run_ai(hass, ai_entity_id, prompt)
        except _ChatPreemptError:
            _LOGGER.info("Kyber deep-analyzer: preempted by chat — pausing")
            _set_deep_progress(processed - 1, ident, paused=True)
            while hass.data.get(_CHAT_BUSY_KEY):
                await asyncio.sleep(1)
            backoff = _CHAT_BACKOFF_SECONDS[min(_chat_preempt_count, len(_CHAT_BACKOFF_SECONDS) - 1)]
            _chat_preempt_count += 1
            _LOGGER.info("Kyber deep-analyzer: chat ended — resuming in %ds (attempt %d)", backoff, _chat_preempt_count)
            await asyncio.sleep(backoff)
            _set_deep_progress(processed - 1, ident)
            processed -= 1  # re-process this item
            continue
        except asyncio.TimeoutError:
            _LOGGER.warning(
                "Kyber deep_analyzer: AI call timed out (%ds) for %s:%s — skipping",
                _AI_CALL_TIMEOUT, kind, ident,
            )
            errors.append({"kind": kind, "ident": ident, "error": f"AI timeout after {_AI_CALL_TIMEOUT}s"})
            continue
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Kyber deep_analyzer: AI call failed for %s:%s: %s", kind, ident, err)
            errors.append({"kind": kind, "ident": ident, "error": str(err)})
            continue

        # Successful item — reset chat preemption backoff counter.
        _chat_preempt_count = 0

        facts = _parse_facts(raw, config_entity_ids=list(_extract_entity_ids(item)))
        facts = [f for f in facts if f["confidence"] >= _MIN_CONFIDENCE]

        # For the "entity relationships" lens, discard facts that don't reference
        # at least one real entity_id (they are likely hallucinated or too vague).
        if prompt_variant % len(_PROMPT_LENSES) == 6:  # entity_relationships lens
            facts = [
                f for f in facts
                if any(eid in f["content"] for eid in all_entity_ids)
            ]

        fact_ids: list[str] = []
        for f in facts:
            try:
                if await _is_duplicate_fact(kstore, f["content"]):
                    _LOGGER.debug(
                        "Kyber deep_analyzer: skipping near-duplicate fact for %s: %s",
                        ident, f["content"][:80],
                    )
                    continue
                entry = await kstore.async_add(
                    category=f["category"],
                    subject=f["subject"],
                    content=f["content"],
                    tags=f["tags"] + [f"deep:{kind}", f"src:{ident}"],
                    source="deep-analyzer",
                    confidence=f["confidence"],
                    provenance=f"Deep analysis of {kind} '{ident}'",
                )
                fact_ids.append(entry["id"])
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Kyber deep_analyzer: failed to persist fact: %s", err)

        try:
            await memo.async_record_lens(
                kind=kind,
                ident=ident,
                new_hash=new_hash,
                lens=prompt_variant,
                fact_ids=fact_ids,
                skipped=(len(fact_ids) == 0),
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Kyber deep_analyzer: memo record failed for %s:%s: %s", kind, ident, err)
        analyzed.append({
            "kind": kind,
            "ident": ident,
            "facts": [
                {k: v for k, v in f.items() if k != "confidence"}
                | {"confidence": round(float(f["confidence"]), 4)}
                for f in facts
            ],
            "fact_ids": [str(fid) for fid in fact_ids],
            "raw_response_chars": int(len(raw or "")),
        })
        _set_deep_progress(processed, ident)

    # Clear deep_learning status when done.
    if pending_count > 0:
        existing = hass.data.get(EXPLORER_PROGRESS_KEY) or {}
        hass.data[EXPLORER_PROGRESS_KEY] = {
            **existing,
            "status": existing.get("status") if existing.get("status") != "deep_learning" else "done",
            "phase": "deep_learning",
            "deep_done": processed,
            "deep_total": pending_count,
            "deep_current": "",
            "updated_at": int(time.time()),
        }

    return {
        "analyzed": analyzed,
        "skipped_unchanged": skipped,
        "errors": errors,
        "candidates_total": len(candidates),
        "processed": processed,
        "limit": limit,
    }


async def memo_status(hass: HomeAssistant) -> dict[str, Any]:
    memo = get_memo(hass)
    await memo.async_load()
    records = memo.all_records()
    by_kind: dict[str, int] = {}
    for r in records:
        by_kind[r.get("kind", "?")] = by_kind.get(r.get("kind", "?"), 0) + 1
    return {
        "total": len(records),
        "by_kind": by_kind,
        "records": records,
    }
