from __future__ import annotations

from collections import deque
import json
import uuid
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as ha_dt

from .const import CONF_AI_TASK_ENTITY_ID

_CI_EVENT_LOG_KEY = "kyber_ci_event_log"
_CI_EVENT_LOG_MAX = 50
_ALLOWED_REASONS = {
    "all_clear",
    "dinner_window",
    "oven_active",
    "sleep_time",
    "nobody_home",
    "manual_hold",
    "unknown",
}
_HOME_CONTEXT_PROMPT = (
    "You are checking if it is safe to do a production software deployment right now. \n"
    "Assess the current home context: is anyone having dinner (check oven, time of day 17:30-20:00, kitchen activity), \n"
    "is anyone asleep (late night, no motion), is the home in a relaxed state, \n"
    "are there any reasons this would be a bad time for a system deployment?\n\n"
    "Return ONLY valid JSON with these exact fields:\n"
    "{\n"
    '  \"can_deploy\": <true or false>,\n'
    '  \"reason\": \"<one of: all_clear, dinner_window, oven_active, sleep_time, nobody_home, manual_hold, unknown>\",\n'
    '  \"details\": \"<1-2 sentence human explanation>\",\n'
    '  \"estimated_resume\": \"<when it would be ok, e.g. \'20:00\' or \'tomorrow morning\' or \'now\'>\",\n'
    '  \"local_time\": \"<current local time HH:MM>\"\n'
    "}\n"
    "Do not include any text before or after the JSON."
)


def _event_log(hass: HomeAssistant) -> deque[dict[str, Any]]:
    log = hass.data.get(_CI_EVENT_LOG_KEY)
    if not isinstance(log, deque):
        log = deque(maxlen=_CI_EVENT_LOG_MAX)
        hass.data[_CI_EVENT_LOG_KEY] = log
    return log


def _append_event(hass: HomeAssistant, event: dict[str, Any]) -> None:
    _event_log(hass).append(event)


def _time_fallback(raw_response: str = "") -> dict[str, Any]:
    now = ha_dt.now()
    local_time = now.strftime("%H:%M")
    minutes = now.hour * 60 + now.minute
    dinner = 17 * 60 + 30 <= minutes <= 20 * 60
    can_deploy = not dinner
    return {
        "can_deploy": can_deploy,
        "reason": "all_clear" if can_deploy else "dinner_window",
        "details": (
            "Fallback time check: outside the dinner window."
            if can_deploy
            else f"Fallback time check: {local_time} is within the dinner window (17:30-20:00)."
        ),
        "estimated_resume": "now" if can_deploy else "20:00",
        "local_time": local_time,
        "raw_kyber_response": raw_response,
    }


def _extract_json_payload(raw_response: str) -> dict[str, Any]:
    text = (raw_response or "").strip()
    if not text:
        raise ValueError("empty response")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("response was not a JSON object")
    return parsed


async def _run_kyber_prompt(
    hass: HomeAssistant,
    prompt: str,
    config: dict[str, Any],
    user_id: str,
) -> str:
    from .http_api import (
        _build_context,
        _build_prompt_sections,
        _inject_knowledge_into_instructions,
        _run_ai_loop,
    )
    from .knowledge import get_store as get_knowledge_store

    entity_id = str(config.get(CONF_AI_TASK_ENTITY_ID, "")).strip()
    if not entity_id:
        raise ValueError("No AI task entity configured in Kyber settings")

    request_id = str(uuid.uuid4())
    context, _context_stats = _build_context(hass)
    kstore = get_knowledge_store(hass)
    await kstore.async_load()

    body_fields = {
        "user_prompt": prompt,
        "user_yaml": "",
        "history": [],
        "compacted_summary": "",
        "editor_mode": "chat",
        "dashboards": [],
        "lovelace_resources": [],
        "request_id": request_id,
    }

    class _MockUser:
        def __init__(self, uid: str) -> None:
            self.id = uid
            self.is_admin = False
            self.name = "CI integration"

    class _MockRequest:
        def get(self, key: str, default: Any = None) -> Any:
            if key == "hass_user":
                return _MockUser(user_id)
            return default

    sections = _build_prompt_sections(body_fields, context, _MockRequest())
    instructions = sections["instructions"]
    intent = sections["intent"]
    instructions, _ = await _inject_knowledge_into_instructions(
        hass,
        kstore,
        prompt,
        instructions,
        request_id,
        entity_id=entity_id,
        user_id=user_id or None,
        is_admin=False,
    )
    response_text, _tool_log, _exchange, _cache, _intent, _loop_instr, _aliases, _tokens = (
        await _run_ai_loop(
            hass,
            entity_id,
            instructions,
            kstore,
            prompt,
            request_id,
            [],
            intent,
            config=config,
            user_id=user_id,
            is_admin=False,
        )
    )
    return str(response_text or "")


def _fallback_briefing(events: list[dict[str, Any]]) -> str:
    if not events:
        return "No recent CI events were recorded. Everything has been quiet."
    lines = []
    for event in events:
        repo = event.get("repo") or "unknown repo"
        branch = event.get("branch") or "unknown branch"
        status = event.get("status") or "info"
        message = event.get("message") or event.get("reason") or event.get("type") or "update recorded"
        timestamp = event.get("local_time") or event.get("timestamp") or "recently"
        lines.append(f"- {timestamp}: {repo} ({branch}) reported {status} — {message}")
    return "Recent CI activity while you were away:\n" + "\n".join(lines)


async def handle_get_home_context(
    hass: HomeAssistant,
    params: dict[str, Any],
    config: dict[str, Any],
    user_id: str,
) -> dict[str, Any]:
    _ = params
    raw_response = ""
    try:
        raw_response = await _run_kyber_prompt(hass, _HOME_CONTEXT_PROMPT, config, user_id)
        parsed = _extract_json_payload(raw_response)
        can_deploy = bool(parsed.get("can_deploy", True))
        reason = str(parsed.get("reason", "unknown")).strip() or "unknown"
        if reason not in _ALLOWED_REASONS:
            reason = "unknown"
        details = str(parsed.get("details", "")).strip() or "Kyber did not provide details."
        estimated_resume = str(parsed.get("estimated_resume", "now")).strip() or "now"
        local_time = str(parsed.get("local_time", "")).strip() or ha_dt.now().strftime("%H:%M")
        return {
            "can_deploy": can_deploy,
            "reason": reason,
            "details": details,
            "estimated_resume": estimated_resume,
            "local_time": local_time,
            "raw_kyber_response": raw_response,
        }
    except Exception:
        return _time_fallback(raw_response)


async def handle_ci_event(hass: HomeAssistant, params: dict[str, Any]) -> dict[str, Any]:
    event_type = str(params.get("type", "")).strip()
    repo = str(params.get("repo", "")).strip()
    branch = str(params.get("branch", "")).strip()
    status = str(params.get("status", "")).strip().lower()
    message = str(params.get("message", "")).strip()

    if not event_type:
        return {"error": "type is required"}
    if not repo:
        return {"error": "repo is required"}
    if not branch:
        return {"error": "branch is required"}
    if status not in {"success", "failure", "info"}:
        return {"error": "status must be one of: success, failure, info"}
    if not message:
        return {"error": "message is required"}

    now = ha_dt.now()
    event_data = {
        "type": event_type,
        "repo": repo,
        "branch": branch,
        "status": status,
        "message": message,
        "timestamp": now.isoformat(),
        "local_time": now.strftime("%H:%M"),
    }
    _append_event(hass, event_data)
    hass.bus.async_fire("kyber_ci_event", event_data)
    return {"fired": True, "event_type": "kyber_ci_event", "data": event_data}


async def handle_celebrate(hass: HomeAssistant, params: dict[str, Any]) -> dict[str, Any]:
    reason = str(params.get("reason") or "Manual merge to production!").strip() or "Manual merge to production!"
    now = ha_dt.now()
    event_data = {
        "type": "celebrate",
        "repo": str(params.get("repo") or "manual"),
        "branch": str(params.get("branch") or "production"),
        "status": "success",
        "message": reason,
        "timestamp": now.isoformat(),
        "local_time": now.strftime("%H:%M"),
    }
    _append_event(hass, event_data)
    hass.bus.async_fire("kyber_ci_event", event_data)
    await hass.services.async_call(
        "persistent_notification",
        "create",
        {
            "title": "Kyber CI celebration",
            "message": reason,
            "notification_id": "kyber_ci_celebration",
        },
        blocking=True,
    )
    return {"celebrated": True, "reason": reason}


async def handle_peace_briefing(
    hass: HomeAssistant,
    params: dict[str, Any],
    config: dict[str, Any],
    user_id: str,
) -> dict[str, Any]:
    try:
        max_events = int(params.get("max_events", 10))
    except (TypeError, ValueError):
        max_events = 10
    max_events = max(1, min(max_events, _CI_EVENT_LOG_MAX))
    events = list(_event_log(hass))[-max_events:]

    if not events:
        return {
            "briefing": _fallback_briefing(events),
            "events": [],
            "count": 0,
        }

    prompt = (
        "You are giving a calm briefing about recent CI/CD activity. "
        "Summarize the key events in 2-4 sentences, mention any failures that may need attention, "
        "and keep the tone reassuring.\n\n"
        f"Recent events JSON:\n{json.dumps(events, ensure_ascii=False, indent=2)}"
    )

    try:
        briefing = (await _run_kyber_prompt(hass, prompt, config, user_id)).strip()
        if not briefing:
            raise ValueError("empty briefing")
    except Exception:
        briefing = _fallback_briefing(events)

    return {
        "briefing": briefing,
        "events": events,
        "count": len(events),
    }
