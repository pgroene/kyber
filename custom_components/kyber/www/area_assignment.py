"""Area assignment — discover entities without an area during conversations.

Detection strategy (conversation-first):
  1. Extract area mentions from the user's prompt and recent conversation history.
  2. For each entity in the current plan that has NO area assigned:
       - Score how well the mentioned area fits the entity (conversation text + entity_id).
  3. Suggestions at confidence ≥ 0.75 are returned to the caller.

Modes (CONF_AREA_ASSIGNMENT_MODE):
  off     — do nothing
  suggest — return suggestions for UI display; user must click Apply
  auto    — assign immediately and return reports so user can undo
"""
from __future__ import annotations

import logging
import re
import uuid
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

AREA_REPORTS_KEY = "kyber_area_reports"

# Domains whose entities are mobile / virtual and should never be area-assigned.
_SKIP_DOMAINS: frozenset[str] = frozenset({
    "person", "device_tracker", "input_boolean", "input_select", "input_number",
    "input_text", "input_datetime", "timer", "counter", "zone", "sun", "weather",
    "scene", "group", "schedule", "todo", "calendar", "persistent_notification",
    "alert", "tag",
})

_MIN_CONFIDENCE = 0.75


def _tokenize(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", text.lower()) if len(t) >= 2]


def _conversation_mentions_area(
    user_prompt: str,
    conversation_history: list[dict],
    area_name: str,
    area_id: str,
) -> float:
    """Return 0-1 confidence that this area was mentioned in the conversation.

    Checks user_prompt and the last 4 user messages in history.
    """
    # Build a single text corpus from recent user messages.
    texts = [user_prompt]
    for msg in (conversation_history or [])[-4:]:
        if msg.get("role") == "user":
            texts.append(str(msg.get("content", "")))
    corpus = " ".join(texts).lower()

    aid = area_id.lower()
    aname_tokens = _tokenize(area_name)

    # Exact area_id present in corpus
    if aid and re.search(r"\b" + re.escape(aid) + r"\b", corpus):
        return 0.95

    # All area name tokens present in corpus
    if aname_tokens and all(
        re.search(r"\b" + re.escape(t) + r"\b", corpus) for t in aname_tokens
    ):
        return 0.90

    # Any single area name token ≥ 4 chars in corpus
    for t in aname_tokens:
        if len(t) >= 4 and re.search(r"\b" + re.escape(t) + r"\b", corpus):
            return 0.80

    return 0.0


def _entity_id_suggests_area(entity_id: str, area_name: str, area_id: str) -> float:
    """Return 0-1 confidence based on entity_id slug matching area name/id."""
    slug = entity_id.split(".", 1)[-1].lower()
    aid = area_id.lower()
    aname_tokens = _tokenize(area_name)
    slug_tokens = _tokenize(slug)

    if aid and aid in slug:
        return 0.90

    if aname_tokens and all(t in slug_tokens for t in aname_tokens):
        return 0.85

    for t in aname_tokens:
        if len(t) >= 4 and t in slug_tokens:
            return 0.75

    return 0.0


def _get_entity_current_area(reg_entry: Any, hass: "HomeAssistant") -> str | None:
    """Return current area_id for an entity (entity or device level)."""
    if reg_entry.area_id:
        return reg_entry.area_id
    if reg_entry.device_id:
        from homeassistant.helpers import device_registry as dr
        dev = dr.async_get(hass).async_get(reg_entry.device_id)
        if dev and dev.area_id:
            return dev.area_id
    return None


async def async_detect_conversation_suggestions(
    hass: "HomeAssistant",
    config: dict[str, Any],
    entity_ids: list[str],
    user_prompt: str,
    conversation_history: list[dict],
) -> list[dict[str, Any]]:
    """Check plan entities for missing area assignments, guided by conversation context.

    Returns a list of suggestion dicts.  In 'auto' mode, assignments are applied
    immediately and each dict has applied=True.  In 'suggest' mode, applied=False.
    In 'off' mode, returns [].
    """
    from .const import (
        CONF_AREA_ASSIGNMENT_MODE,
        AREA_ASSIGNMENT_OFF,
        AREA_ASSIGNMENT_SUGGEST,
        AREA_ASSIGNMENT_AUTO,
        DEFAULT_AREA_ASSIGNMENT_MODE,
        DOMAIN,
    )

    mode = config.get(CONF_AREA_ASSIGNMENT_MODE, DEFAULT_AREA_ASSIGNMENT_MODE)
    if mode == AREA_ASSIGNMENT_OFF or not entity_ids:
        return []

    from homeassistant.helpers import area_registry as ar, entity_registry as er

    area_reg = ar.async_get(hass)
    entity_reg = er.async_get(hass)
    areas = area_reg.async_list_areas()
    if not areas:
        return []

    # IDs of entities already reported this session to avoid duplicates.
    existing_reports: list[dict] = hass.data.get(DOMAIN, {}).get(AREA_REPORTS_KEY, [])
    already_handled: set[str] = {r["entity_id"] for r in existing_reports}

    suggestions: list[dict[str, Any]] = []

    for eid in entity_ids:
        domain = eid.split(".")[0]
        if domain in _SKIP_DOMAINS:
            continue

        reg_entry = entity_reg.async_get(eid)
        if reg_entry is None:
            continue

        current_area = _get_entity_current_area(reg_entry, hass)
        if current_area:
            continue  # already has an area

        if eid in already_handled:
            continue

        state = hass.states.get(eid)
        friendly_name: str = (
            (state.attributes.get("friendly_name") if state else None)
            or reg_entry.name
            or eid
        )

        # Score every area; pick the best using combined conversation + entity_id signals.
        best_score = 0.0
        best_area = None
        for area in areas:
            if not area.name:
                continue
            conv_score = _conversation_mentions_area(
                user_prompt, conversation_history, area.name, area.id
            )
            eid_score = _entity_id_suggests_area(eid, area.name, area.id)
            # Conversation is the primary signal; entity_id acts as a tiebreaker.
            combined = max(conv_score, eid_score * 0.85)
            # Bonus when BOTH signals agree.
            if conv_score >= 0.80 and eid_score >= 0.75:
                combined = min(combined + 0.05, 1.0)
            if combined > best_score:
                best_score = combined
                best_area = area

        if best_area is None or best_score < _MIN_CONFIDENCE:
            continue

        applied = False
        if mode == AREA_ASSIGNMENT_AUTO:
            try:
                entity_reg.async_update_entity(eid, area_id=best_area.id)
                applied = True
                _LOGGER.info(
                    "Kyber area-assignment: auto-assigned %s → %s (confidence=%.2f)",
                    eid, best_area.name, best_score,
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Kyber area-assignment: could not assign %s: %s", eid, err)
                continue

        report = {
            "id": uuid.uuid4().hex[:12],
            "entity_id": eid,
            "friendly_name": friendly_name,
            "suggested_area_id": best_area.id,
            "suggested_area_name": best_area.name,
            "reason": "mentioned in conversation",
            "confidence": round(best_score, 2),
            "applied": applied,
            "undo_area_id": None,
        }
        suggestions.append(report)
        already_handled.add(eid)

    if suggestions:
        # Persist reports so the frontend can fetch them again after reload.
        if DOMAIN in hass.data:
            hass.data[DOMAIN][AREA_REPORTS_KEY] = existing_reports + suggestions

    return suggestions
