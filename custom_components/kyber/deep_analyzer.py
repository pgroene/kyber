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

import json
import logging
import re
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import CONF_AI_TASK_ENTITY_ID
from .source import (
    AnalysisMemo,
    get_memo,
    read_automations,
    read_blueprints,
    read_scripts,
)

_LOGGER = logging.getLogger(__name__)

_MIN_CONFIDENCE = 0.55
_MAX_FACTS_PER_ITEM = 6

# Hard cap on raw config sent to AI (chars). Beyond this we truncate.
_MAX_CONFIG_CHARS = 6000

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
) -> str:
    """Build a focused prompt that asks the AI for durable facts.

    ``prompt_variant`` selects one of the analytical lenses in ``_PROMPT_LENSES``
    so that multiple passes over the same automations produce complementary facts.
    ``entity_names`` maps entity_id → friendly_name for context enrichment.
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

    # Build entity name context so the AI knows what entity_ids mean
    entity_context = ""
    if entity_names:
        entity_ids_in_config = list(dict.fromkeys(_extract_entity_ids(body)))
        resolved = [
            f"  {eid} = \"{entity_names[eid]}\""
            for eid in entity_ids_in_config
            if eid in entity_names
        ]
        if resolved:
            entity_context = (
                "\n--- entity names ---\n"
                + "\n".join(resolved)
                + "\n--- end entity names ---\n"
            )

    return (
        f"You are reviewing a Home Assistant {kind} called '{ident}'.\n"
        f"{lens['ask']}\n"
        "Infer DURABLE, NON-OBVIOUS facts — output ONLY facts relevant to this lens. "
        "Skip generic observations ('there is an automation', 'it uses a trigger').\n\n"
        "Output ONLY a JSON array. Each item: {\"category\": str, "
        "\"subject\": str, \"content\": str, \"tags\": [str], "
        "\"confidence\": float 0-1}. If nothing relevant, output [].\n\n"
        f"--- {kind} config ---\n{body_yaml}\n--- end ---\n"
        f"{entity_context}\n"
        "JSON array:"
    )


_JSON_ARRAY_RE = re.compile(r"\[[\s\S]*\]")


def _parse_facts(raw: str) -> list[dict[str, Any]]:
    """Parse the AI response into a list of fact dicts. Tolerant."""
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
        if not content:
            continue
        try:
            conf = float(f.get("confidence", 0.5))
        except (TypeError, ValueError):
            conf = 0.5
        tags = f.get("tags") or []
        if not isinstance(tags, list):
            tags = []
        out.append({
            "category": str(f.get("category") or "general").strip() or "general",
            "subject": str(f.get("subject") or "").strip(),
            "content": content,
            "tags": [str(t) for t in tags],
            "confidence": max(0.0, min(1.0, conf)),
        })
    return out


async def _run_ai(hass: HomeAssistant, ai_entity_id: str, prompt: str) -> str:
    try:
        from homeassistant.components.ai_task import async_generate_data  # type: ignore
    except Exception as err:  # noqa: BLE001
        raise HomeAssistantError(f"ai_task not available: {err}")

    result = await async_generate_data(
        hass,
        task_name="kyber_deep_analyze",
        entity_id=ai_entity_id,
        instructions=prompt,
    )
    return result.data if isinstance(result.data, str) else str(result.data)


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

    # Build entity_id → friendly_name lookup once for the whole run
    entity_names: dict[str, str] = {}
    for state in hass.states.async_all():
        friendly = state.attributes.get("friendly_name")
        if friendly:
            entity_names[state.entity_id] = friendly

    analyzed: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    skipped = 0
    processed = 0

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
            prompt = _build_prompt(kind, item, prompt_variant, entity_names=entity_names)
            raw = await _run_ai(hass, ai_entity_id, prompt)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Kyber deep_analyzer: AI call failed for %s:%s: %s", kind, ident, err)
            errors.append({"kind": kind, "ident": ident, "error": str(err)})
            continue

        facts = _parse_facts(raw)
        facts = [f for f in facts if f["confidence"] >= _MIN_CONFIDENCE]

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
