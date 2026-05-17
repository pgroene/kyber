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


# ── Public types ─────────────────────────────────────────────────────
def _truncate(text: str, limit: int = _MAX_CONFIG_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… [truncated {len(text) - limit} chars]"


def _build_prompt(kind: str, item: dict[str, Any]) -> str:
    """Build a focused prompt that asks the AI for durable facts."""
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

    body_yaml = json.dumps(body, indent=2, ensure_ascii=False, default=str)
    body_yaml = _truncate(body_yaml)

    return (
        f"You are reviewing a Home Assistant {kind} called '{ident}'.\n"
        "Infer DURABLE, NON-OBVIOUS facts about the home that this implies — "
        "facts that would help an AI answer future questions about how the "
        "home is organised, who lives there, daily routines, or device usage.\n"
        "Examples of GOOD facts: 'The living-room lights turn off at 23:00 on weekdays', "
        "'The garage door has a presence sensor used to trigger lighting', "
        "'The owner uses motion-based lighting in the hallway'.\n"
        "Examples of BAD (generic / obvious) facts: 'There is an automation', "
        "'It uses a trigger', 'Lights can turn on'.\n\n"
        "Output ONLY a JSON array. Each item: {\"category\": str, "
        "\"subject\": str, \"content\": str, \"tags\": [str], "
        "\"confidence\": float 0-1}. If the item implies NO useful new fact, "
        "output an empty array [].\n\n"
        f"--- {kind} config ---\n{body_yaml}\n--- end ---\n\n"
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


async def analyze_pending(
    hass: HomeAssistant,
    *,
    ai_entity_id: str,
    kinds: list[str] | None = None,
    limit: int = 5,
    force: bool = False,
) -> dict[str, Any]:
    """Walk all configured items; analyze ones whose hash changed (up to `limit`).

    Returns:
        {analyzed: [{kind, ident, facts, fact_ids}], skipped: N, errors: [...]}.
    """
    kinds = kinds or ["automation", "script", "blueprint"]
    memo: AnalysisMemo = get_memo(hass)
    await memo.async_load()

    # Lazy import to avoid circular dep
    from .knowledge import get_knowledge_store
    kstore = get_knowledge_store(hass)
    if not kstore._loaded:
        await kstore.async_load()

    # Gather candidates
    candidates: list[tuple[str, dict[str, Any]]] = []
    if "automation" in kinds:
        for it in await hass.async_add_executor_job(read_automations, hass):
            candidates.append(("automation", it))
    if "script" in kinds:
        for it in await hass.async_add_executor_job(read_scripts, hass):
            candidates.append(("script", it))
    if "blueprint" in kinds:
        for it in await hass.async_add_executor_job(read_blueprints, hass):
            candidates.append(("blueprint", it))

    analyzed: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    skipped = 0
    processed = 0

    for kind, item in candidates:
        ident = _identity(kind, item)
        if not ident:
            continue
        new_hash = item.get("hash") or ""
        if not force and not memo.is_changed(kind, ident, new_hash):
            skipped += 1
            continue
        if processed >= limit:
            # Reached this run's budget — leave for next sweep.
            break
        processed += 1
        try:
            prompt = _build_prompt(kind, item)
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

        await memo.async_record(
            kind=kind,
            ident=ident,
            new_hash=new_hash,
            fact_ids=fact_ids,
            skipped=(len(fact_ids) == 0),
        )
        analyzed.append({
            "kind": kind,
            "ident": ident,
            "facts": facts,
            "fact_ids": fact_ids,
            "raw_response_chars": len(raw or ""),
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
