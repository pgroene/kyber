"""Progress events, save, and summarize utilities extracted from http_api.py."""
from __future__ import annotations

import json
import logging
from http import HTTPStatus
from typing import Any

import yaml
from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

try:
    from homeassistant.components.ai_task import async_generate_data
except ImportError:  # HA < 2025.2 (test environments)
    async def async_generate_data(*args, **kwargs):  # type: ignore[misc]
        raise RuntimeError("homeassistant.components.ai_task not available (HA < 2025.2)")

from .const import CONF_AI_TASK_ENTITY_ID, DOMAIN
from .session_and_storage import (
    _async_load_chat_store, _async_save_chat_store,
    _migrate_user_to_sessions, _get_active_session, _sanitize_history,
)

_LOGGER = logging.getLogger(__name__)
_AI_LOG = logging.getLogger("custom_components.kyber.ai_calls")

# Redefine progress constants (same values as http_api.py)
_PROGRESS_KEY = "kyber_progress"
_PROGRESS_MAX_AGE = 300
_PROGRESS_MAX_ENTRIES = 64

# Max chars logged for prompt/response in normal debug mode.
_AI_LOG_PROMPT_CHARS = 2000
_AI_LOG_RESPONSE_CHARS = 1000


async def async_ai_call(
    hass: HomeAssistant,
    *,
    task_name: str,
    entity_id: str,
    instructions: str,
    **kwargs: Any,
) -> Any:
    """Wrapper around async_generate_data with structured debug logging.

    - In debug mode: logs the full request before sending and the response on return.
    - Always: logs the full prompt + error on failure (so you can reproduce it).
    """
    import time as _time
    debug: bool = bool(hass.data.get("kyber_debug_mode", False))
    if debug:
        _AI_LOG.warning(
            "[AI→] task=%s entity=%s prompt_chars=%d\n%s%s",
            task_name,
            entity_id,
            len(instructions),
            instructions[:_AI_LOG_PROMPT_CHARS],
            "…" if len(instructions) > _AI_LOG_PROMPT_CHARS else "",
        )
    _t0 = _time.monotonic()
    try:
        result = await async_generate_data(
            hass,
            task_name=task_name,
            entity_id=entity_id,
            instructions=instructions,
            **kwargs,
        )
    except Exception as err:
        elapsed_ms = int((_time.monotonic() - _t0) * 1000)
        _AI_LOG.error(
            "[AI✗] task=%s entity=%s elapsed=%dms\n--- PROMPT ---\n%s\n--- ERROR ---\n%s",
            task_name,
            entity_id,
            elapsed_ms,
            instructions,
            err,
        )
        raise
    elapsed_ms = int((_time.monotonic() - _t0) * 1000)
    if debug:
        raw = result.data if isinstance(result.data, str) else str(result.data)
        _AI_LOG.warning(
            "[AI←] task=%s elapsed=%dms response_chars=%d\n%s%s",
            task_name,
            elapsed_ms,
            len(raw),
            raw[:_AI_LOG_RESPONSE_CHARS],
            "…" if len(raw) > _AI_LOG_RESPONSE_CHARS else "",
        )
    return result


def _progress_emit(hass: HomeAssistant, request_id: str, event: dict) -> None:
    """Append a progress event for a request_id (in-memory)."""
    if not request_id:
        return
    import time
    store: dict = hass.data.setdefault(_PROGRESS_KEY, {})
    # Purge old entries (best effort, cheap)
    now = time.time()
    if len(store) > _PROGRESS_MAX_ENTRIES:
        stale = [k for k, v in store.items() if now - v.get("ts", now) > _PROGRESS_MAX_AGE]
        for k in stale:
            store.pop(k, None)
    entry = store.setdefault(request_id, {"events": [], "ts": now, "status": "running"})
    entry["ts"] = now
    entry["events"].append({**event, "t": now})


def _progress_complete(hass: HomeAssistant, request_id: str) -> None:
    """Mark a request as complete (kept briefly so client can fetch last events)."""
    if not request_id:
        return
    import time
    store: dict = hass.data.setdefault(_PROGRESS_KEY, {})
    entry = store.setdefault(request_id, {"events": [], "ts": time.time(), "status": "running"})
    entry["status"] = "done"
    entry["ts"] = time.time()


class KyberProgressView(HomeAssistantView):
    """Return progress events for an in-flight chat request."""

    url = "/api/kyber/progress"
    name = "api:kyber:progress"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        request_id = request.query.get("id", "").strip()
        since = int(request.query.get("since", "0") or 0)
        if not request_id:
            return self.json({"events": [], "status": "unknown", "next": 0})
        store: dict = hass.data.get(_PROGRESS_KEY, {})
        entry = store.get(request_id)
        if not entry:
            return self.json({"events": [], "status": "unknown", "next": 0})
        events = entry.get("events", [])
        new_events = events[since:]
        return self.json({
            "events": new_events,
            "status": entry.get("status", "running"),
            "next": len(events),
        })


class KyberSaveView(HomeAssistantView):
    """Handle POST /api/kyber/parse_yaml — parses YAML, returns JSON config.

    The frontend uses this to convert editor YAML to JSON, then calls
    HA's own config/automation/config/{id} REST endpoint directly.
    """

    url = "/api/kyber/parse_yaml"
    name = "api:kyber:parse_yaml"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        """Parse YAML and return the resulting JSON object."""
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return self.json_message("Invalid JSON body", HTTPStatus.BAD_REQUEST)

        yaml_text: str | None = body.get("yaml")
        if not yaml_text:
            return self.json_message("Missing 'yaml' field", HTTPStatus.BAD_REQUEST)

        try:
            config = yaml.safe_load(yaml_text)
        except yaml.YAMLError as err:
            return self.json_message(f"Invalid YAML: {err}", HTTPStatus.BAD_REQUEST)

        if not isinstance(config, dict):
            return self.json_message("YAML must be a mapping object", HTTPStatus.BAD_REQUEST)

        return self.json({"config": config})


_SUMMARIZE_SYSTEM_PROMPT = """\
You are a conversation summarizer for a Home Assistant AI assistant.
Your job is to maintain a running summary of a conversation between a user and an AI assistant.

Rules:
- Merge the previous summary with the new messages into one updated, concise summary.
- Always copy lines that start with [CHANGE] into the new summary exactly as written. These record actual changes made to the Home Assistant setup and must never be dropped.
- Keep the summary short and factual — focus on what was asked, what was decided, and what was changed.
- Do not include pleasantries or meta-commentary. Output only the summary text.
- Write the summary in the same language as the conversation.\
"""


class KyberSummarizeView(HomeAssistantView):
    """Handle POST /api/kyber/summarize — merges overflow messages into a running summary."""

    url = "/api/kyber/summarize"
    name = "api:kyber:summarize"
    requires_auth = True

    def __init__(self, config: dict[str, Any]) -> None:
        """Store config entry data."""
        self._config = config

    async def post(self, request: web.Request) -> web.Response:
        """Merge previous summary + overflow messages into a new summary."""
        hass: HomeAssistant = request.app["hass"]

        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return self.json_message("Invalid JSON body", HTTPStatus.BAD_REQUEST)

        previous_summary: str = body.get("previous_summary", "").strip()
        messages: list[dict] = body.get("messages", [])

        if not messages:
            return self.json({"summary": previous_summary})

        # Format the messages for the AI
        msg_lines = []
        for msg in messages:
            role = msg.get("role", "user")
            content = str(msg.get("content", "")).strip()
            if content:
                msg_lines.append(f"{'User' if role == 'user' else 'Assistant'}: {content}")

        instructions = _SUMMARIZE_SYSTEM_PROMPT
        if previous_summary:
            instructions += f"\n\nPrevious summary:\n{previous_summary}"
        instructions += f"\n\nNew messages to incorporate:\n" + "\n".join(msg_lines)
        instructions += "\n\nOutput the updated summary:"

        entity_id: str = self._config[CONF_AI_TASK_ENTITY_ID]

        try:
            result = await async_ai_call(
                hass,
                task_name=f"{DOMAIN}_summarize",
                entity_id=entity_id,
                instructions=instructions,
            )
        except Exception as err:  # noqa: BLE001 — summarize must never fail
            _LOGGER.error("Summarize AI task failed: %s", err)
            # Fall back: append messages as plain text rather than failing
            fallback_lines = [f"[{m.get('role','user').upper()}] {m.get('content','')}" for m in messages]
            fallback = (previous_summary + "\n" + "\n".join(fallback_lines)).strip()
            return self.json({"summary": fallback})

        summary_text: str = result.data if isinstance(result.data, str) else str(result.data)
        return self.json({"summary": summary_text.strip()})
